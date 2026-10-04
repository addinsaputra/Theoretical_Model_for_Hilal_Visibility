"""
Open-Meteo ECMWF_IFS API Client Module
Modul untuk mengambil data cuaca historis dari Open-Meteo API (ECMWF_IFS)
"""

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry
from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime


# Setup the Open-Meteo API client with cache and retry on error
_cache_session = None
_retry_session = None
_openmeteo = None


def _get_client():
    """
    Menginisialisasi dan mengembalikan Open-Meteo API client.
    Menggunakan singleton pattern untuk menghindari inisialisasi ganda.
    """
    global _cache_session, _retry_session, _openmeteo
    if _openmeteo is None:
        _cache_session = requests_cache.CachedSession('.cache', expire_after=3600)
        _retry_session = retry(_cache_session, retries=5, backoff_factor=0.2)
        _openmeteo = openmeteo_requests.Client(session=_retry_session)
    return _openmeteo


def fetch_hourly_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    hourly_variables: Optional[List[str]] = None,
    timezone: str = "auto"
) -> pd.DataFrame:
    """
    Mengambil data cuaca hourly dari Open-Meteo Archive API.

    Args:
        latitude: Garis lintang lokasi (contoh: -6.9666 untuk Semarang)
        longitude: Garis bujur lokasi (contoh: 110.45 untuk Semarang)
        start_date: Tanggal mulai dalam format YYYY-MM-DD
        end_date: Tanggal akhir dalam format YYYY-MM-DD
        hourly_variables: Daftar variabel hourly yang diambil.
                         Default: ["temperature_2m", "relative_humidity_2m"]
        timezone: Timezone untuk output data. Default: "auto"

    Returns:
        pd.DataFrame: DataFrame berisi data cuaca hourly dengan kolom date
                     dan variabel-variabel yang diminta.

    Example:
        >>> df = fetch_hourly_weather(
        ...     latitude=-6.9666,
        ...     longitude=110.45,
        ...     start_date="2025-11-01",
        ...     end_date="2025-11-01"
        ... )
        >>> print(df.head())
    """
    if hourly_variables is None:
        hourly_variables = ["temperature_2m", "relative_humidity_2m"]

    # Setup client
    openmeteo = _get_client()

    # Setup URL dan parameters
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": hourly_variables,
        "timezone": timezone,
    }

    # Fetch data dari API
    responses = openmeteo.weather_api(url, params=params)

    # Process response (ambil response pertama)
    response = responses[0]

    # Extract hourly data
    hourly = response.Hourly()
    hourly_data = {
        "date": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left"
        )
    }

    # Extract semua variabel yang diminta
    for i, var_name in enumerate(hourly_variables):
        hourly_data[var_name] = hourly.Variables(i).ValuesAsNumpy()

    return pd.DataFrame(data=hourly_data)


def get_location_info(response) -> Dict[str, Any]:
    """
    Mengambil informasi lokasi dari respons API.

    Args:
        response: Response object dari Open-Meteo API

    Returns:
        Dict berisi informasi koordinat, elevasi, dan timezone
    """
    return {
        "latitude": response.Latitude(),
        "longitude": response.Longitude(),
        "elevation": response.Elevation(),
        "timezone": response.Timezone(),
        "timezone_abbreviation": response.TimezoneAbbreviation(),
        "utc_offset_seconds": response.UtcOffsetSeconds()
    }


def fetch_weather_with_info(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    hourly_variables: Optional[List[str]] = None,
    timezone: str = "auto",
    print_info: bool = False
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Mengambil data cuaca hourly beserta informasi lokasi.

    Args:
        latitude: Garis lintang lokasi
        longitude: Garis bujur lokasi
        start_date: Tanggal mulai (YYYY-MM-DD)
        end_date: Tanggal akhir (YYYY-MM-DD)
        hourly_variables: Daftar variabel hourly
        timezone: Timezone untuk output
        print_info: Jika True, print informasi lokasi ke console

    Returns:
        Tuple (DataFrame, Dict): DataFrame data cuaca dan dict informasi lokasi
    """
    if hourly_variables is None:
        hourly_variables = ["temperature_2m", "relative_humidity_2m"]

    openmeteo = _get_client()

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": hourly_variables,
        "timezone": timezone,
    }

    responses = openmeteo.weather_api(url, params=params)
    response = responses[0]

    # Get location info
    location_info = get_location_info(response)

    if print_info:
        print(f"\nCoordinates: {location_info['latitude']}Â°N {location_info['longitude']}Â°E")
        print(f"Elevation: {location_info['elevation']} m asl")
        print(f"Timezone: {location_info['timezone']}{location_info['timezone_abbreviation']}s")
        print(f"Timezone difference to GMT+0: {location_info['utc_offset_seconds']}s")

    # Get hourly data
    hourly = response.Hourly()
    hourly_data = {
        "date": pd.date_range(
            start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
            end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
            freq=pd.Timedelta(seconds=hourly.Interval()),
            inclusive="left"
        )
    }

    for i, var_name in enumerate(hourly_variables):
        hourly_data[var_name] = hourly.Variables(i).ValuesAsNumpy()

    dataframe = pd.DataFrame(data=hourly_data)

    return dataframe, location_info


# ============ DATACLASS DAN FUNGSI INTERPOLASI ============

@dataclass(frozen=True)
class ObservingLocation:
    """Immutable record describing an observing site.

    Parameters
    ----------
    name : str
        A human-readable name for the location (e.g. city or observatory).
    latitude : float
        Geographic latitude in decimal degrees (positive for north, negative for south).
    longitude : float
        Geographic longitude in decimal degrees (positive for east, negative for west).
    altitude : float
        Altitude in metres above sea level.
    timezone : str
        IANA time zone identifier (e.g. ``"Asia/Jakarta"``).
    """
    name: str
    latitude: float
    longitude: float
    altitude: float
    timezone: str


class ECMWF_IFSAPIError(RuntimeError):
    """Raised when the Open-Meteo ECMWF_IFS API returns an unexpected response."""


def interpolate_linear(x0: float, y0: float, x1: float, y1: float, x: float) -> float:
    """Perform linear interpolation between two points.

    Given two points (x0, y0) and (x1, y1), return the value at x.
    If x is outside the interval [x0, x1], the function returns
    y0 or y1 accordingly (no extrapolation beyond the endpoints).
    """
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    # Compute fractional distance
    f = (x - x0) / (x1 - x0)
    return y0 + f * (y1 - y0)


def get_rh_t_at_time(location: ObservingLocation, target_utc: datetime) -> Tuple[float, float, float]:
    """Compute relative humidity and temperature at an arbitrary UTC time.

    This high-level function fetches hourly data for the UTC date(s)
    bracketing the ``target_utc`` time, then interpolates the
    ``relative_humidity_2m`` and ``temperature_2m`` values linearly between
    the two surrounding hourly samples.

    Parameters
    ----------
    location : ObservingLocation
        The geographic point at which to sample the meteorological parameters.
    target_utc : datetime
        A timezone-aware UTC datetime representing the desired time
        (e.g. sunset) at which RH and temperature are needed.

    Returns
    -------
    (float, float)
        A pair ``(RH_percent, temperature_celsius)`` giving the
        interpolated relative humidity (0-100 percent) and air
        temperature (degrees Celsius) at ``target_utc``.

    Raises
    ------
    ECMWF_IFSAPIError
        If the required hourly samples are missing or the API returns
        invalid data.

    Example
    -------
    >>> from datetime import datetime, timezone
    >>> from open_meteo_api_ecmwf_ifs import ObservingLocation, get_rh_t_at_time
    >>> semarang = ObservingLocation(
    ...     name="Semarang Observatory",
    ...     latitude=-6.97,
    ...     longitude=110.42,
    ...     altitude=3.0,
    ...     timezone="Asia/Jakarta"
    ... )
    >>> sunset_utc = datetime(2025, 11, 1, 10, 30, tzinfo=timezone.utc)
    >>> rh_percent, temp_c = get_rh_t_at_time(semarang, sunset_utc)
    >>> print(f"Relative humidity: {rh_percent:.1f}%   Temperature: {temp_c:.1f}Â°C")
    """
    from datetime import timedelta
    
    if target_utc.tzinfo is None or target_utc.tzinfo.utcoffset(target_utc) is None:
        raise ValueError("target_utc must be timezone-aware and in UTC")

    # Determine the two bounding hours
    t0 = target_utc.replace(minute=0, second=0, microsecond=0)
    t1 = t0 + timedelta(hours=1)

    # Prepare to fetch data for the day(s) needed
    days_to_fetch = {t0.date(), t1.date()}
    
    # Fetch hourly data for all required days
    all_data = []
    for day in sorted(days_to_fetch):
        date_str = day.strftime("%Y-%m-%d")
        df = fetch_hourly_weather(
            latitude=location.latitude,
            longitude=location.longitude,
            start_date=date_str,
            end_date=date_str,
            hourly_variables=["temperature_2m", "relative_humidity_2m", "surface_pressure"],
            timezone="UTC"
        )
        all_data.append(df)
    
    # Combine all dataframes
    df_combined = pd.concat(all_data, ignore_index=True)
    
    # Index rows by datetime for quick lookup
    data_by_time: Dict[datetime, Dict[str, float]] = {}
    for _, row in df_combined.iterrows():
        dt = row['date'].to_pydatetime()
        data_by_time[dt] = {
            'temperature_2m': row['temperature_2m'],
            'relative_humidity_2m': row['relative_humidity_2m'],
            'surface_pressure': row['surface_pressure']
        }
    
    # Retrieve the two samples
    if t0 not in data_by_time or t1 not in data_by_time:
        raise ECMWF_IFSAPIError(
            f"Missing data for hours {t0.isoformat()} and/or {t1.isoformat()} in ECMWF_IFS response"
        )
    
    row0 = data_by_time[t0]
    row1 = data_by_time[t1]
    
    rh0 = row0.get('relative_humidity_2m')
    rh1 = row1.get('relative_humidity_2m')
    t2m0 = row0.get('temperature_2m')
    t2m1 = row1.get('temperature_2m')
    sp0 = row0.get('surface_pressure')
    sp1 = row1.get('surface_pressure')
    
    if rh0 is None or rh1 is None or t2m0 is None or t2m1 is None or sp0 is None or sp1 is None:
        raise ECMWF_IFSAPIError(
            f"Missing RH/T2M/Pressure data for interpolation around {target_utc.isoformat()}"
        )
    
    # Check for NaN values
    if pd.isna(rh0) or pd.isna(rh1) or pd.isna(t2m0) or pd.isna(t2m1) or pd.isna(sp0) or pd.isna(sp1):
        raise ECMWF_IFSAPIError(
            f"NaN values in RH/T2M/Pressure data for interpolation around {target_utc.isoformat()}"
        )

    # Interpolate to target time (fraction within the hour)
    seconds_since_t0 = (target_utc - t0).total_seconds()
    # The duration between samples is exactly 3600 seconds
    rh_interp = interpolate_linear(0.0, float(rh0), 3600.0, float(rh1), seconds_since_t0)
    t_interp = interpolate_linear(0.0, float(t2m0), 3600.0, float(t2m1), seconds_since_t0)
    sp_interp = interpolate_linear(0.0, float(sp0), 3600.0, float(sp1), seconds_since_t0)

    # Clamp relative humidity to [0, 100] percent for safety
    rh_interp = max(0.0, min(100.0, rh_interp))
    return rh_interp, t_interp, sp_interp

# ============ FUNGSI KOREKSI BIAS ============

def apply_bias_correction(
    rh: float,
    temperature: float,
    pressure: float,
    bias_t: float = 0.0,
    bias_rh: float = 0.0
) -> tuple:
    """Menerapkan koreksi bias pada data ECMWF_IFS.

    Menggunakan metode Additive Bias Correction (koreksi langsung):
        X_corrected = X_ecmwf_ifs - bias
    
    di mana bias = ECMWF_IFS - Observasi (mean bias dari jurnal).
    
    Contoh:
        - bias_t = -1 â†’ ECMWF_IFS lebih dingin 1Â°C â†’ T_corrected = T + 1
        - bias_rh = 4  â†’ ECMWF_IFS lebih lembap 4% â†’ RH_corrected = RH - 4

    Parameters
    ----------
    rh : float
        Relative humidity dari ECMWF_IFS (persen, 0-100)
    temperature : float
        Suhu dari ECMWF_IFS (derajat Celsius)
    pressure : float
        Tekanan permukaan dari ECMWF_IFS (mbar) â€” tidak dikoreksi
    bias_t : float
        Bias suhu (Â°C), default 0.0 (tanpa koreksi)
    bias_rh : float
        Bias kelembapan relatif (%), default 0.0 (tanpa koreksi)

    Returns
    -------
    (float, float, float)
        Tuple (RH_corrected, T_corrected, pressure) di mana:
        - RH_corrected di-clamp ke [0, 100]
        - T_corrected = temperature - bias_t
        - pressure tidak dikoreksi (pass-through)
    """
    t_corrected = temperature - bias_t
    rh_corrected = rh - bias_rh
    
    # Clamp RH ke [0, 100] persen
    rh_corrected = max(0.0, min(100.0, rh_corrected))
    
    return rh_corrected, t_corrected, pressure


if __name__ == "__main__":
    # Contoh penggunaan langsung saat file di-run
    df = fetch_hourly_weather(
        latitude=-6.9666,
        longitude=110.45,
        start_date="2025-11-01",
        end_date="2025-11-01",
        hourly_variables=["temperature_2m", "relative_humidity_2m", "surface_pressure"]
    )
    print("\nHourly data:\n", df)

    # Atau gunakan fungsi dengan info lokasi
    # df_weather, info = fetch_weather_with_info(
    #     latitude=-6.9666,
    #     longitude=110.45,
    #     start_date="2025-11-01",
    #     end_date="2025-11-01",
    #     print_info=True
    # )
    # print("\nHourly data:\n", df_weather)
	
	
