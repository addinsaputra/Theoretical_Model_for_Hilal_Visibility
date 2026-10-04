"""
Module ``meteo_power_api``
========================

This module provides helper functions and data structures to retrieve
meteorological data from the NASA POWER (Prediction Of Worldwide
Energy Resources) service.  In particular, it includes functions
designed to fetch hourly relative humidity (RH) and air temperature
at 2 metres above the surface (parameters ``RH2M`` and ``T2M``) and
interpolate them to an arbitrary time such as sunset.  The goal is
to eliminate manual entry of humidity and temperature in lunar
visibility calculations by replacing them with values derived from
NASA POWER’s API.

The underlying data sets used by the POWER service are derived from
satellite observations and meteorological reanalysis models.  POWER
allows users to specify a geographic point (latitude and longitude),
select a list of parameters and choose temporal resolutions such as
hourly or daily.  When using the hourly API the service can return
data either in **Local Solar Time (LST)** or **UTC**.  LST is
computed from the longitude in 15° increments and **may not match
the government‑assigned time zone**; the hourly API defaults to
LST, therefore we explicitly request UTC so that the returned times
align with sunset times computed in UTC【173913273457392†L63-L84】.  POWER’s FAQ notes
that each hourly time stamp represents the **start of the hour**
for the entire hour’s average【325474416723728†L188-L197】.  This convention is important
when interpolating to a time between two hourly samples.

The functions in this module are built with the following design
principles:

* **Immutability of configuration:**  Locations and observation
  metadata are represented with data classes for clarity and type
  safety.
* **Separation of concerns:**  Fetching, parsing and interpolation
  logic are encapsulated in separate functions.  This makes the
  module easier to test and reason about.
* **Graceful error handling:**  Missing or invalid data from the
  POWER API raises informative exceptions rather than failing
  silently.

API Usage Guidelines
--------------------

NASA requests that users refrain from making excessive or highly
parallelised API requests in order to avoid over‑loading the
servers.  A single hourly request returns 24 records covering an
entire UTC day (00:00–23:00), so one request per location per date
is sufficient for most applications.  Consider caching responses
locally if repeated computations are performed for the same
locations or dates.

Example::

    from datetime import datetime, date, timezone
    from meteo_power_api import ObservingLocation, get_rh_t_at_time

    # Define the observing site (Semarang, Indonesia)
    semarang = ObservingLocation(
        name="Semarang Observatory",
        latitude=-6.97,
        longitude=110.42,
        altitude=3.0,
        timezone="Asia/Jakarta"
    )

    # Suppose we have computed sunset in UTC for 2026-01-08
    sunset_utc = datetime(2026, 1, 8, 10, 30, tzinfo=timezone.utc)

    # Fetch RH and temperature from POWER and interpolate to sunset
    rh_percent, temp_c = get_rh_t_at_time(semarang, sunset_utc)
    print(f"Relative humidity: {rh_percent:.1f}%   Temperature: {temp_c:.1f}°C")

"""

from __future__ import annotations

import csv
import io
import requests
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

POWER_BASE_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"


@dataclass(frozen=True)
class ObservingLocation:
    """Immutable record describing an observing site.

    Parameters
    ----------
    name : str
        A human‑readable name for the location (e.g. city or observatory).
    latitude : float
        Geographic latitude in decimal degrees (positive for north, negative for south).
    longitude : float
        Geographic longitude in decimal degrees (positive for east, negative for west).
    altitude : float
        Altitude in metres above sea level.  This module does not use altitude directly
        but stores it for completeness and potential future use.
    timezone : str
        IANA time zone identifier (e.g. ``"Asia/Jakarta"``).  The timezone is
        not used internally but serves as documentation and could be useful
        for converting times to local civil time when presenting results to
        users.
    """

    name: str
    latitude: float
    longitude: float
    altitude: float
    timezone: str


class PowerAPIError(RuntimeError):
    """Raised when the NASA POWER API returns an unexpected response."""


def _parse_power_csv(text: str) -> List[Dict[str, str]]:
    """Parse a POWER CSV response into a list of dictionaries.

    The POWER hourly CSV response often contains metadata lines
    preceding the actual header.  This helper locates the header
    starting with ``YEAR,MO,DY,HR`` and returns rows with numeric
    values converted to strings.  No type conversion occurs here
    because conversion requires knowledge of missing data codes and
    parameter names.  Missing data values are retained for later
    handling.

    Parameters
    ----------
    text : str
        The raw CSV text returned by the POWER service.

    Returns
    -------
    list of dict
        Each dictionary maps column names to raw string values.
    """
    lines = text.splitlines()
    header_index: Optional[int] = None
    # Find the first line starting with YEAR,MO,DY,HR
    for i, line in enumerate(lines):
        if line.strip().startswith("YEAR,MO,DY,HR"):
            header_index = i
            break
    if header_index is None:
        raise PowerAPIError("Unable to locate CSV header in POWER response.")
    # Reconstruct the CSV from the header onwards
    csv_text = "\n".join(lines[header_index:])
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)


def _fetch_power_hourly(day_utc: date, location: ObservingLocation) -> List[Dict[str, str]]:
    """Fetch hourly POWER data for a given UTC date and location.

    The request asks for the ``RH2M``, ``T2M``, and ``PS`` parameters for the
    specified date in UTC.  Since the hourly API defaults to Local
    Solar Time, we include ``time-standard=UTC`` to ensure that the
    timestamps in the response correspond to UTC【173913273457392†L63-L84】.  A single request
    returns 24 records covering hours 00:00 through 23:00 (each
    timestamp representing the **start** of the hour【325474416723728†L188-L197】).

    Parameters
    ----------
    day_utc : datetime.date
        The UTC date for which to request data.
    location : ObservingLocation
        The geographic point at which to sample the meteorological
        parameters.

    Returns
    -------
    list of dict
        A list of rows representing hourly samples.  Each row
        contains at least the keys ``YEAR``, ``MO``, ``DY``, ``HR``,
        ``RH2M``, ``T2M``, and ``PS``.  The values are strings that must be
        converted to numeric types by the caller.
    """
    ymd = day_utc.strftime("%Y%m%d")
    params = {
        "parameters": "RH2M,T2M,PS",
        "community": "RE",  # Renewable Energy community; choose as default
        "longitude": location.longitude,
        "latitude": location.latitude,
        "start": ymd,
        "end": ymd,
        "format": "CSV",
        "time-standard": "UTC",
    }
    response = requests.get(POWER_BASE_URL, params=params, timeout=60)
    if not response.ok:
        raise PowerAPIError(
            f"POWER API request failed with status {response.status_code}: {response.text.strip()}"
        )
    return _parse_power_csv(response.text)


def _row_to_datetime(row: Dict[str, str]) -> datetime:
    """Convert a POWER CSV row to a timezone‑aware UTC datetime.

    POWER provides columns YEAR, MO (month), DY (day) and HR (hour),
    where hour is integer 0–23.  The time stamp represents the start of the
    hour【325474416723728†L188-L197】.  Missing or malformed values raise a ValueError.

    Parameters
    ----------
    row : dict
        A row from the parsed CSV response.

    Returns
    -------
    datetime
        A timezone‑aware datetime in UTC corresponding to the start of
        the hour.
    """
    try:
        year = int(row["YEAR"])
        month = int(row["MO"])
        day = int(row["DY"])
        hour = int(float(row["HR"]))  # HR may come as float string (e.g. "0.0")
    except Exception as exc:
        raise ValueError(f"Invalid timestamp fields in row: {row}") from exc
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _extract_numeric(value: str) -> Optional[float]:
    """Convert a POWER parameter string to a float or return None for missing values.

    The POWER CSV uses ``-999`` to indicate missing data.  This helper
    returns ``None`` if the input equals ``-999``; otherwise it
    converts the string to ``float``.
    """
    try:
        val = float(value)
    except Exception:
        return None
    return None if val == -999 else val


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
    """Compute relative humidity, temperature, and pressure at an arbitrary UTC time.

    This high‑level function fetches hourly data for the UTC date(s)
    bracketing the ``target_utc`` time, then interpolates the
    ``RH2M``, ``T2M``, and ``PS`` values linearly between the two surrounding
    hourly samples.  If the two necessary samples fall on different
    calendar days (e.g. when the time is 23:30), the function
    automatically fetches data for both days.  Missing data in
    either sample triggers a ``PowerAPIError``.

    Parameters
    ----------
    location : ObservingLocation
        The geographic point at which to sample the meteorological
        parameters.
    target_utc : datetime
        A timezone‑aware UTC datetime representing the desired time
        (e.g. sunset) at which data is needed.  The
        interpolation uses the hour in which ``target_utc`` lies and the
        subsequent hour.

    Returns
    -------
    (float, float, float)
        A tuple ``(RH_percent, temperature_celsius, pressure_kpa)`` giving the
        interpolated relative humidity (0–100 percent), air
        temperature (degrees Celsius), and surface pressure (kPa) at ``target_utc``.

    Raises
    ------
    PowerAPIError
        If the required hourly samples are missing or the API returns
        invalid data.
    """
    if target_utc.tzinfo is None or target_utc.tzinfo.utcoffset(target_utc) is None:
        raise ValueError("target_utc must be timezone‑aware and in UTC")

    # Determine the two bounding hours
    t0 = target_utc.replace(minute=0, second=0, microsecond=0)
    # According to POWER, each record represents the start of the hour for that hour【325474416723728†L188-L197】
    t1 = t0 + timedelta(hours=1)

    # Prepare to fetch data for the day(s) needed
    days_to_fetch = {t0.date(), t1.date()}
    hourly_data: List[Dict[str, str]] = []
    for day in sorted(days_to_fetch):
        hourly_data.extend(_fetch_power_hourly(day, location))

    # Index rows by datetime for quick lookup
    data_by_time: Dict[datetime, Dict[str, str]] = {}
    for row in hourly_data:
        dt = _row_to_datetime(row)
        data_by_time[dt] = row

    # Retrieve the two samples
    if t0 not in data_by_time or t1 not in data_by_time:
        raise PowerAPIError(
            f"Missing data for hours {t0.isoformat()} and/or {t1.isoformat()} in POWER response"
        )
    row0 = data_by_time[t0]
    row1 = data_by_time[t1]

    rh0 = _extract_numeric(row0.get("RH2M", "-999"))
    rh1 = _extract_numeric(row1.get("RH2M", "-999"))
    t2m0 = _extract_numeric(row0.get("T2M", "-999"))
    t2m1 = _extract_numeric(row1.get("T2M", "-999"))
    ps0 = _extract_numeric(row0.get("PS", "-999"))
    ps1 = _extract_numeric(row1.get("PS", "-999"))

    if rh0 is None or rh1 is None or t2m0 is None or t2m1 is None or ps0 is None or ps1 is None:
        raise PowerAPIError(
            f"Missing RH2M/T2M/PS data for interpolation around {target_utc.isoformat()}"
        )

    # Interpolate to target time (fraction within the hour)
    seconds_since_t0 = (target_utc - t0).total_seconds()
    # The duration between samples is exactly 3600 seconds
    rh_interp = interpolate_linear(0.0, rh0, 3600.0, rh1, seconds_since_t0)
    t_interp = interpolate_linear(0.0, t2m0, 3600.0, t2m1, seconds_since_t0)
    ps_interp = interpolate_linear(0.0, ps0, 3600.0, ps1, seconds_since_t0)

    # Clamp relative humidity to [0, 100] percent for safety
    rh_interp = max(0.0, min(100.0, rh_interp))
    return rh_interp, t_interp, ps_interp

def cache_power_data(fetch_func):  # type: ignore[assignment]
    """Decorator to cache POWER API responses in memory.

    Apply this decorator to the private functions that fetch data
    from the POWER service to avoid redundant network requests when
    the same location/date combination is requested multiple times.

    Example::

        @_cache_power_data
        def _fetch_power_hourly(day, loc):
            ...
    """
    cache: Dict[Tuple[date, float, float], List[Dict[str, str]]] = {}

    def wrapper(day_utc: date, location: ObservingLocation) -> List[Dict[str, str]]:
        key = (day_utc, location.latitude, location.longitude)
        if key in cache:
            return cache[key]
        data = fetch_func(day_utc, location)
        cache[key] = data
        return data

    return wrapper


# Wrap the fetch function with the cache decorator so repeated requests
# for the same date and location reuse the previous result.  The
# decorator is applied after definition so static type checkers see
# the original signature.
_fetch_power_hourly = cache_power_data(_fetch_power_hourly)  # type: ignore[assignment]


__all__ = [
    "ObservingLocation",
    "PowerAPIError",
    "get_rh_t_at_time",
]