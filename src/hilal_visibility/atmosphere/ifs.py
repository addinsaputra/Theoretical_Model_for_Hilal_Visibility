"""ECMWF IFS HRES hourly archive through Open-Meteo (model ecmwf_ifs).

The retrieval API is Historical Weather /v1/archive. Product identity follows
the explicit model selector and the verified SDK response model, rather than
the API endpoint's name. Analysis and Analysis Long-Window have separate model
selectors in Open-Meteo. The IFS cycle is not exposed by this API response.

RH and surface pressure are Open-Meteo derived variables. Temperature and
pressure are downscaled to the requested site elevation; these are not raw
ECMWF grid fields. Missing atmospheric samples raise ECMWF_IFSAPIError.
"""

from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone as utc_timezone
import math
from typing import Any, Dict, List, Optional, Tuple

import openmeteo_requests
from openmeteo_sdk.Model import Model
from openmeteo_sdk.Unit import Unit
from openmeteo_sdk.Variable import Variable
import pandas as pd
import requests_cache
from retry_requests import retry
from hilal_visibility.paths import CACHE_DIR


ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
IFS_MODEL = "ecmwf_ifs"
IFS_PRODUCT_NAME = "ECMWF IFS HRES 9 km (Open-Meteo ecmwf_ifs)"
IFS_IDENTITY_REFERENCE = (
    "https://github.com/open-meteo/open-meteo/blob/"
    "1cd0eaa1ed97857772a6bd968bbe373bd23636f3/"
    "Sources/App/Controllers/ForecastapiController.swift"
)
ATMOSPHERIC_VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "surface_pressure", "dew_point_2m",
)
_VARIABLE_SPECS = {
    "temperature_2m": (Variable.temperature, Unit.celsius, "°C"),
    "relative_humidity_2m": (Variable.relative_humidity, Unit.percentage, "%"),
    "surface_pressure": (Variable.surface_pressure, Unit.hectopascal, "hPa"),
    "dew_point_2m": (Variable.dew_point, Unit.celsius, "°C"),
}
_cache_session = None
_retry_session = None
_openmeteo = None


class ECMWF_IFSAPIError(RuntimeError):
    """Unavailable, malformed, or invalid atmospheric data from Open-Meteo."""


@dataclass(frozen=True)
class ObservingLocation:
    """Site coordinates, elevation above sea level (m), and IANA timezone."""

    name: str
    latitude: float
    longitude: float
    altitude: float
    timezone: str


def _get_client():
    global _cache_session, _retry_session, _openmeteo
    if _openmeteo is None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_session = requests_cache.CachedSession(str(CACHE_DIR / 'atmosphere'), expire_after=3600)
        _retry_session = retry(_cache_session, retries=5, backoff_factor=0.2)
        _openmeteo = openmeteo_requests.Client(session=_retry_session)
    return _openmeteo


def normalize_utc_datetime(value: datetime) -> datetime:
    """Accept any aware datetime and normalize before choosing UTC dates."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Atmospheric times must be timezone-aware")
    return value.astimezone(utc_timezone.utc)


def validate_atmosphere(rh: float, temperature: float, pressure: float) -> None:
    """Reject invalid input rather than converting it into plausible weather."""
    try:
        valid = all(math.isfinite(v) for v in (rh, temperature, pressure))
        valid = valid and 0 <= rh <= 100 and temperature > -273.15 and pressure > 0
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ECMWF_IFSAPIError(
            f"Invalid atmosphere: RH={rh!r} %, T={temperature!r} °C, P={pressure!r} hPa"
        )


def _decode_text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def get_location_info(response) -> Dict[str, Any]:
    """Returned grid coordinates and effective elevation used for downscaling.

    The returned elevation can equal the requested elevation. It must not be
    interpreted as the native ECMWF grid elevation.
    """
    return {
        "latitude": float(response.Latitude()),
        "longitude": float(response.Longitude()),
        "elevation": float(response.Elevation()),
        "timezone": _decode_text(response.Timezone()),
        "timezone_abbreviation": _decode_text(response.TimezoneAbbreviation()),
        "utc_offset_seconds": int(response.UtcOffsetSeconds()),
    }


def fetch_weather_with_info(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    hourly_variables: Optional[List[str]] = None,
    timezone: str = "auto",
    print_info: bool = False,
    *,
    elevation: Optional[float] = None,
    cell_selection: str = "land",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Fetch pinned IFS data and provenance using a single request/parser.

    Dates follow the requested API timezone; the DataFrame date column is
    always UTC. Unavailable values remain NaN in this low-level table; the
    atmospheric window validates every sample needed for interpolation.
    Existing positional arguments remain supported; elevation is keyword-only.
    """
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("latitude must be finite and in [-90, 90]")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("longitude must be finite and in [-180, 180]")
    if elevation is not None and not math.isfinite(elevation):
        raise ValueError("elevation must be finite")
    if date.fromisoformat(start_date) > date.fromisoformat(end_date):
        raise ValueError("start_date must not follow end_date")
    if cell_selection not in ("land", "sea", "nearest"):
        raise ValueError("cell_selection must be land, sea, or nearest")
    variables = list(hourly_variables) if hourly_variables is not None else [
        "temperature_2m", "relative_humidity_2m",
    ]
    if not variables or len(set(variables)) != len(variables):
        raise ValueError("hourly_variables must be nonempty and unique")
    params = {
        "latitude": latitude, "longitude": longitude,
        "start_date": start_date, "end_date": end_date,
        "hourly": variables, "timezone": timezone,
        "models": IFS_MODEL, "cell_selection": cell_selection,
        "temperature_unit": "celsius",
    }
    if elevation is not None:
        params["elevation"] = elevation
    try:
        responses = _get_client().weather_api(ARCHIVE_URL, params=params, timeout=30)
        if len(responses) != 1:
            raise ECMWF_IFSAPIError("Expected one ECMWF IFS response")
        response = responses[0]
        if response.Model() != Model.ecmwf_ifs:
            raise ECMWF_IFSAPIError("Response does not identify the requested ECMWF IFS model")
        hourly = response.Hourly()
        if hourly is None or hourly.Interval() != 3600 or hourly.TimeEnd() <= hourly.Time():
            raise ECMWF_IFSAPIError("Missing or invalid hourly time axis")
        if hourly.VariablesLength() != len(variables):
            raise ECMWF_IFSAPIError("Unexpected number of hourly variables")
        times = pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq="h", inclusive="left",
        )
        data = {"date": times}
        units = {}
        for i, name in enumerate(variables):
            variable = hourly.Variables(i)
            if name in _VARIABLE_SPECS:
                variable_id, unit_id, unit_label = _VARIABLE_SPECS[name]
                if (variable.Variable() != variable_id or variable.Unit() != unit_id
                        or (name != "surface_pressure" and variable.Altitude() != 2)):
                    raise ECMWF_IFSAPIError(f"Unexpected variable or unit for {name}")
                units[name] = unit_label
            values = variable.ValuesAsNumpy()
            if not hasattr(values, "__len__") or len(values) != len(times):
                raise ECMWF_IFSAPIError(f"Hourly array length mismatch for {name}")
            data[name] = values
        info = get_location_info(response)
        if not all(math.isfinite(info[k]) for k in ("latitude", "longitude", "elevation")):
            raise ECMWF_IFSAPIError("Invalid returned location metadata")
        info.update({
            "source": "Open-Meteo Historical Weather API", "endpoint": ARCHIVE_URL,
            "model": IFS_MODEL, "response_model_id": int(response.Model()),
            "response_model_name": IFS_MODEL,
            "product_name": IFS_PRODUCT_NAME,
            "product_type": "ifs_hres_hourly_time_series",
            "nominal_horizontal_resolution_km": 9,
            "product_identity_reference": IFS_IDENTITY_REFERENCE,
            "ifs_cycle": None,
            "ifs_cycle_availability": "not exposed by this API response",
            "requested_latitude": latitude, "requested_longitude": longitude,
            "requested_elevation": elevation, "cell_selection": cell_selection,
            "requested_timezone": timezone, "time_axis_timezone": "UTC",
            "start_date": start_date, "end_date": end_date, "units": units,
            "elevation_meaning": "effective elevation used for downscaling",
            "retrieved_at_utc": datetime.now(utc_timezone.utc).isoformat(),
            "derived_variables": {
                "relative_humidity_2m": "derived from temperature and dew point",
                "surface_pressure": "derived from MSL pressure, temperature and elevation",
            },
        })
        dataframe = pd.DataFrame(data)
        dataframe.attrs["weather_metadata"] = info
    except ECMWF_IFSAPIError:
        raise
    except Exception as exc:
        raise ECMWF_IFSAPIError(
            f"ECMWF IFS request/response failed for {start_date}..{end_date} "
            f"at ({latitude}, {longitude}): {exc}"
        ) from exc
    if print_info:
        print(f"Product: {info['product_name']}; response model ID: {info['response_model_id']}")
        print(f"API: {info['endpoint']}")
        print(f"Coordinates: {info['latitude']}°, {info['longitude']}°")
        print(f"Effective elevation: {info['elevation']} m asl")
        print(f"Timezone: {info['timezone']} ({info['timezone_abbreviation']}); dates stored in UTC")
    return dataframe, info


def fetch_hourly_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    hourly_variables: Optional[List[str]] = None,
    timezone: str = "auto",
    *,
    elevation: Optional[float] = None,
    cell_selection: str = "land",
) -> pd.DataFrame:
    """Fetch IFS hourly data; metadata is retained in DataFrame.attrs."""
    dataframe, _ = fetch_weather_with_info(
        latitude, longitude, start_date, end_date, hourly_variables, timezone,
        elevation=elevation, cell_selection=cell_selection,
    )
    return dataframe


@dataclass
class AtmosphericWindow:
    """Validated UTC hourly samples, with no endpoint extrapolation."""

    hourly: pd.DataFrame
    metadata: Dict[str, Any] = field(default_factory=dict)
    _indexed: pd.DataFrame = field(init=False, repr=False)

    def __post_init__(self):
        try:
            self.hourly = self.hourly.copy()
            self.hourly["date"] = pd.to_datetime(self.hourly["date"], utc=True)
            self._indexed = self.hourly.set_index("date")
            index = self._indexed.index
            if (index.empty or index.hasnans or not index.is_unique
                    or not index.is_monotonic_increasing
                    or any(index[i] - index[i - 1] != pd.Timedelta(hours=1)
                           for i in range(1, len(index)))):
                raise ECMWF_IFSAPIError("Missing, duplicate, or non-hourly atmospheric timestamps")
            for timestamp, row in self._indexed.iterrows():
                validate_atmosphere(
                    row["relative_humidity_2m"], row["temperature_2m"], row["surface_pressure"],
                )
                if "dew_point_2m" in row:
                    dew = row["dew_point_2m"]
                    if not math.isfinite(dew) or dew <= -273.15:
                        raise ECMWF_IFSAPIError(f"Invalid dew point at {timestamp.isoformat()}")
        except ECMWF_IFSAPIError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ECMWF_IFSAPIError(f"Malformed atmospheric series: {exc}") from exc

    def at_time(self, target_utc: datetime) -> Tuple[float, float, float]:
        """Return raw (RH %, T °C, P hPa) between the actual hourly anchors."""
        target = pd.Timestamp(normalize_utc_datetime(target_utc))
        index = self._indexed.index
        if target < index[0] or target > index[-1]:
            raise ECMWF_IFSAPIError(f"Time {target.isoformat()} lies outside the atmospheric window")
        # pandas searchsorted can reject subsecond targets against an SDK
        # datetime64[s] index. Scalar comparisons preserve the target precision.
        right = bisect_left(index, target)
        columns = ["relative_humidity_2m", "temperature_2m", "surface_pressure"]
        if index[right] == target:
            return tuple(float(v) for v in self._indexed.iloc[right][columns])
        left = right - 1
        fraction = (target - index[left]).total_seconds() / 3600.0
        values0 = self._indexed.iloc[left][columns]
        values1 = self._indexed.iloc[right][columns]
        return tuple(float(a + fraction * (b - a)) for a, b in zip(values0, values1))

    def to_record(self) -> Dict[str, Any]:
        """JSON-safe provenance and raw hourly inputs, before bias correction."""
        return {
            **self.metadata,
            "hourly_raw": [
                {"date": timestamp.isoformat(), **{k: float(v) for k, v in row.items()}}
                for timestamp, row in self._indexed.iterrows()
            ],
        }


def fetch_atmospheric_window(
    location: ObservingLocation, start_utc: datetime, end_utc: datetime,
) -> AtmosphericWindow:
    """Fetch one UTC date range containing all bounding hours of a window."""
    start = normalize_utc_datetime(start_utc)
    end = normalize_utc_datetime(end_utc)
    if end < start:
        raise ValueError("end_utc must not precede start_utc")
    lower = start.replace(minute=0, second=0, microsecond=0)
    upper = end.replace(minute=0, second=0, microsecond=0)
    if upper < end:
        upper += timedelta(hours=1)
    dataframe, metadata = fetch_weather_with_info(
        latitude=location.latitude, longitude=location.longitude,
        elevation=location.altitude, start_date=lower.date().isoformat(),
        end_date=upper.date().isoformat(), hourly_variables=list(ATMOSPHERIC_VARIABLES),
        timezone="UTC", cell_selection="land",
    )
    selected = dataframe.loc[(dataframe["date"] >= lower) & (dataframe["date"] <= upper)]
    expected = pd.date_range(lower, upper, freq="h")
    if len(selected) != len(expected) or not pd.DatetimeIndex(selected["date"]).equals(expected):
        raise ECMWF_IFSAPIError(f"Missing hourly samples for {lower.isoformat()}..{upper.isoformat()}")
    return AtmosphericWindow(selected, {
        **metadata, "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat(),
    })


def get_rh_t_at_time(location: ObservingLocation, target_utc: datetime) -> Tuple[float, float, float]:
    """Interpolate (RH %, T °C, P hPa); an exact hour needs just that sample."""
    return fetch_atmospheric_window(location, target_utc, target_utc).at_time(target_utc)


def interpolate_linear(x0: float, y0: float, x1: float, y1: float, x: float) -> float:
    """Legacy bounded scalar helper; atmospheric windows reject extrapolation."""
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0)


def apply_bias_correction(
    rh: float, temperature: float, pressure: float,
    bias_t: float = 0.0, bias_rh: float = 0.0,
) -> Tuple[float, float, float]:
    """Subtract explicit additive biases; clip corrected RH to [0, 100].

    Bias = model minus observation. Pressure is unchanged, in hPa (= mbar).
    Only corrected RH is clipped; invalid raw atmospheric inputs are rejected.
    """
    validate_atmosphere(rh, temperature, pressure)
    if not math.isfinite(bias_t) or not math.isfinite(bias_rh):
        raise ValueError("Atmospheric biases must be finite")
    corrected = (max(0.0, min(100.0, rh - bias_rh)), temperature - bias_t, pressure)
    validate_atmosphere(*corrected)
    return corrected


if __name__ == "__main__":
    df, info = fetch_weather_with_info(
        -6.9666, 110.45, "2024-04-09", "2024-04-09",
        hourly_variables=list(ATMOSPHERIC_VARIABLES), timezone="UTC",
        elevation=3.0, print_info=True,
    )
    print(df)
