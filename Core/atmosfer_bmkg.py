"""
BMKG Weather Forecast API Client Module
========================================

This module provides helper functions and data structures to retrieve
weather forecast data from BMKG (Badan Meteorologi, Klimatologi, dan
Geofisika) public API. It provides 3-day weather forecasts with 3-hour
resolution for any location in Indonesia.

The BMKG API uses administrative area codes (adm4 - kelurahan/desa level)
instead of coordinates. This module includes a mapping of common observation
locations to their corresponding area codes.

API Information:
- Endpoint: https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4={kode_wilayah}
- Forecast period: 3 days ahead
- Data resolution: Every 3 hours (8 data points per day)
- Update frequency: 2 times daily
- Rate limit: 60 requests per minute per IP

Usage Example::

    from datetime import datetime
    from bmkg_api_forecast import ObservingLocation, get_rh_t_at_time_local

    # Define the observing site (using area code or predefined location)
    semarang = ObservingLocation(
        name="UIN Walisongo Semarang",
        latitude=-6.9167,
        longitude=110.3480,
        altitude=89.0,
        timezone="Asia/Jakarta",
        adm4_code="33.74.10.1003"  # Kode Kelurahan Ngaliyan
    )

    # Waktu sunset LOKAL (bukan UTC)
    sunset_local = datetime(2026, 1, 18, 17, 35)  # 17:35 WIB

    # Get interpolated RH and temperature at sunset
    rh_percent, temp_c = get_rh_t_at_time_local(semarang, sunset_local)
    print(f"Relative humidity: {rh_percent:.1f}%   Temperature: {temp_c:.1f}°C")

Author: Droid AI Assistant
Date: 2026-01-17
"""

from __future__ import annotations

import requests
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any

BMKG_API_URL = "https://api.bmkg.go.id/publik/prakiraan-cuaca"


@dataclass(frozen=True)
class ObservingLocation:
    """Immutable record describing an observing site.

    Parameters
    ----------
    name : str
        A human-readable name for the location.
    latitude : float
        Geographic latitude in decimal degrees.
    longitude : float
        Geographic longitude in decimal degrees.
    altitude : float
        Altitude in metres above sea level.
    timezone : str
        IANA time zone identifier (e.g. ``"Asia/Jakarta"``).
    adm4_code : str
        BMKG administrative area code (tingkat kelurahan/desa).
        Format: "xx.xx.xx.xxxx" (provinsi.kabkota.kecamatan.kelurahan)
    """
    name: str
    latitude: float
    longitude: float
    altitude: float
    timezone: str
    adm4_code: str


class BMKGAPIError(RuntimeError):
    """Raised when the BMKG API returns an unexpected response."""




def _fetch_bmkg_forecast(adm4_code: str) -> Dict[str, Any]:
    """Fetch weather forecast data from BMKG API.

    Parameters
    ----------
    adm4_code : str
        BMKG administrative area code (tingkat kelurahan/desa).

    Returns
    -------
    dict
        JSON response from BMKG API.

    Raises
    ------
    BMKGAPIError
        If the API request fails or returns invalid data.
    """
    params = {"adm4": adm4_code}
    try:
        response = requests.get(BMKG_API_URL, params=params, timeout=30)
        if not response.ok:
            raise BMKGAPIError(
                f"BMKG API request failed with status {response.status_code}: {response.text[:200]}"
            )
        data = response.json()
        return data
    except requests.RequestException as e:
        raise BMKGAPIError(f"BMKG API request failed: {e}") from e


def _parse_forecast_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse BMKG API response into a list of forecast records.

    Parameters
    ----------
    data : dict
        Raw JSON response from BMKG API.

    Returns
    -------
    list of dict
        List of forecast records with parsed LOCAL datetime and values.
        BMKG menggunakan waktu lokal Indonesia, jadi tidak perlu konversi.
    """
    records = []
    
    # Navigate the JSON structure to find weather data
    # BMKG response structure: data -> [0] -> cuaca -> [[records], [records], ...]
    try:
        location_data = data.get("data", [])
        if not location_data:
            raise BMKGAPIError("No data found in BMKG response")
        
        cuaca_data = location_data[0].get("cuaca", [])
        
        for day_data in cuaca_data:
            for record in day_data:
                local_str = record.get("local_datetime", "")
                
                # Parse LOCAL datetime (BMKG sudah menyediakan waktu lokal Indonesia)
                try:
                    local_dt = datetime.strptime(local_str, "%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError):
                    continue
                
                records.append({
                    "local_datetime": local_dt,
                    "temperature": record.get("t"),  # Temperature in °C
                    "humidity": record.get("hu"),     # Humidity in %
                    "cloud_cover": record.get("tcc"), # Cloud cover in %
                    "visibility": record.get("vs_text"),
                    "weather_desc": record.get("weather_desc"),
                    "weather_desc_en": record.get("weather_desc_en"),
                })
    except (KeyError, IndexError, TypeError) as e:
        raise BMKGAPIError(f"Failed to parse BMKG response: {e}") from e
    
    if not records:
        raise BMKGAPIError("No valid forecast records found in BMKG response")
    
    # Sort by local datetime
    records.sort(key=lambda x: x["local_datetime"])
    return records


def interpolate_linear(x0: float, y0: float, x1: float, y1: float, x: float) -> float:
    """Perform linear interpolation between two points.

    Given two points (x0, y0) and (x1, y1), return the value at x.
    Clamps to endpoints if x is outside the interval.
    """
    if x <= x0:
        return y0
    if x >= x1:
        return y1
    f = (x - x0) / (x1 - x0)
    return y0 + f * (y1 - y0)


def get_rh_t_at_time_local(location: ObservingLocation, target_local: datetime) -> Tuple[float, float]:
    """Compute relative humidity and temperature at an arbitrary LOCAL time.

    This function fetches 3-day forecast data from BMKG API and interpolates
    the humidity (hu) and temperature (t) values linearly between the two
    surrounding 3-hourly forecast samples.

    BMKG menyediakan data dalam waktu lokal Indonesia, jadi fungsi ini
    menerima waktu lokal langsung tanpa perlu konversi UTC.

    Parameters
    ----------
    location : ObservingLocation
        The observing site with BMKG adm4 code.
    target_local : datetime
        A naive or local datetime for the desired time (e.g. sunset).
        Contoh: datetime(2026, 1, 18, 17, 35) untuk 17:35 WIB

    Returns
    -------
    (float, float)
        A pair (RH_percent, temperature_celsius) interpolated to target_local.

    Raises
    ------
    BMKGAPIError
        If forecast data is unavailable or interpolation fails.
    """
    # Fetch forecast data
    raw_data = _fetch_bmkg_forecast(location.adm4_code)
    records = _parse_forecast_data(raw_data)

    # Remove timezone info from target if any (compare as naive local time)
    if target_local.tzinfo is not None:
        target_local = target_local.replace(tzinfo=None)

    # Find the two records that bracket target_local
    t0_record = None
    t1_record = None
    
    for i, record in enumerate(records):
        if record["local_datetime"] <= target_local:
            t0_record = record
            if i + 1 < len(records):
                t1_record = records[i + 1]
        else:
            if t0_record is None:
                # target is before all records, use first two
                t0_record = record
                if i + 1 < len(records):
                    t1_record = records[i + 1]
            break

    if t0_record is None:
        raise BMKGAPIError(f"No forecast data available for {target_local}")

    # If we only have one record or target is at/after last record
    if t1_record is None:
        t1_record = t0_record

    # Extract values
    rh0 = t0_record.get("humidity")
    rh1 = t1_record.get("humidity")
    t0 = t0_record.get("temperature")
    t1 = t1_record.get("temperature")

    if rh0 is None or rh1 is None or t0 is None or t1 is None:
        raise BMKGAPIError(
            f"Missing humidity/temperature data for interpolation around {target_local}"
        )

    # Calculate time fraction for interpolation
    dt0 = t0_record["local_datetime"]
    dt1 = t1_record["local_datetime"]
    
    if dt0 == dt1:
        # Same record, no interpolation needed
        return float(rh0), float(t0)

    total_seconds = (dt1 - dt0).total_seconds()
    seconds_since_t0 = (target_local - dt0).total_seconds()

    # Interpolate
    rh_interp = interpolate_linear(0.0, float(rh0), total_seconds, float(rh1), seconds_since_t0)
    t_interp = interpolate_linear(0.0, float(t0), total_seconds, float(t1), seconds_since_t0)

    # Clamp RH to valid range
    rh_interp = max(0.0, min(100.0, rh_interp))

    return rh_interp, t_interp


# Alias untuk backward compatibility
get_rh_t_at_time = get_rh_t_at_time_local


def get_full_forecast(location: ObservingLocation) -> List[Dict[str, Any]]:
    """Get complete 3-day forecast data for a location.

    Parameters
    ----------
    location : ObservingLocation
        The observing site with BMKG adm4 code.

    Returns
    -------
    list of dict
        Complete forecast records with local_datetime, temperature, humidity, etc.
    """
    raw_data = _fetch_bmkg_forecast(location.adm4_code)
    return _parse_forecast_data(raw_data)


# ============ MAIN BLOCK FOR TESTING ============
if __name__ == "__main__":
    print("BMKG Weather Forecast API Test (WAKTU LOKAL)")
    print("=" * 50)
    
    # Test dengan lokasi manual
    print("\nTesting dengan lokasi UIN Walisongo Semarang...")
    
    # Buat lokasi manual (data lokasi kini ada di daftar_lokasi.py)
    uin = ObservingLocation(
        name="UIN Walisongo Semarang",
        latitude=-6.99167,
        longitude=110.34806,
        altitude=89.0,
        timezone="Asia/Jakarta",
        adm4_code="33.74.10.1003"  # Kelurahan Ngaliyan
    )
    
    print(f"Location: {uin.name}")
    print(f"ADM4 Code: {uin.adm4_code}")
    
    try:
        # Get full forecast
        forecast = get_full_forecast(uin)
        print(f"\nForecast available: {len(forecast)} records")
        
        # Show first few records (WAKTU LOKAL)
        print("\nFirst 5 forecast records (WAKTU LOKAL):")
        for i, rec in enumerate(forecast[:5]):
            print(f"  {rec['local_datetime']} WIB - T: {rec['temperature']}°C, RH: {rec['humidity']}%")
        
        # Test interpolation with a time 1.5 hours from first record
        if forecast:
            test_time = forecast[0]["local_datetime"] + timedelta(hours=1, minutes=30)
            rh, temp = get_rh_t_at_time_local(uin, test_time)
            print(f"\nInterpolated at {test_time} WIB:")
            print(f"  Temperature: {temp:.1f}°C")
            print(f"  Humidity: {rh:.1f}%")
            
    except BMKGAPIError as e:
        print(f"API Error: {e}")


__all__ = [
    "ObservingLocation",
    "BMKGAPIError",
    "get_rh_t_at_time",
    "get_rh_t_at_time_local",
    "get_full_forecast",
]

