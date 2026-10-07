"""Crescent calculation API, independent of interactive input workflows."""
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
import os
import pandas as pd

# Import modul yang diperlukan
from hilal_visibility.models.schaefer import hitung_sky_brightness
from hilal_visibility.models.kastner import hitung_fotometri_intrinsik, terapkan_transmisi_atmosfer
# Import langsung dari modul Crumey (tanpa intermediary crumey_telescope_correction.py)
from hilal_visibility.models.crumey import (
    hilal_naked_eye_visibility,
    nL_to_cd_m2,
    arcmin2_to_sr,
    crescent_area_arcmin2,
    visibility_margin_mag,
    telescopic_extended_threshold,
    threshold_parameters,
    DEFAULT_VISUAL_FIELD_FACTOR,
)
from hilal_visibility.models.telescope import TelescopeVisibilityModel

# Import modul cuaca ECMWF_IFS (Open-Meteo)
from hilal_visibility.atmosphere.ifs import (
    ObservingLocation, AtmosphericWindow, fetch_atmospheric_window,
    ECMWF_IFSAPIError, apply_bias_correction, validate_atmosphere,
    normalize_utc_datetime,
)
from hilal_visibility.atmosphere.provenance import atmosphere_audit_record, save_atmosphere_provenance

# Import modul cuaca MERRA-2 (NASA POWER)
from hilal_visibility.atmosphere.merra2 import (
    ObservingLocation as MERRA2Location,
    get_rh_t_at_time as merra2_get_rh_t,
    PowerAPIError
)

# Geometri dan kalender Skyfield/DE440s
from hilal_visibility.ephemeris import (
    newmoon_hijri_month_utc,
    convert_utc_to_localtime,
    convert_localtime_to_utc,
    sunrise_sunset_utc,
    sunrise_sunset_local,
    sun_position_time_utc,
    sun_position_time_local,
    moon_position_time_utc,
    moon_position_time_local,
    moon_elongation_time_utc,
    moon_elongation_time_local,
    moon_phase_angle_time_utc,
    moon_phase_angle_time_local,
    MOON_RADIUS_KM,
    moon_semidiameter_from_distance,
    set_location,
    refraction_horizon_degree
)



def _telescope_configuration(aperture: float, magnification: float, *,
                             F_visual: float = DEFAULT_VISUAL_FIELD_FACTOR, **kwargs) -> dict:
    """One validated configuration reused at sunset, scan and refinement.

    ``observer_age`` controls only the fallback pupil estimate. A measured or
    independently modelled twilight pupil can be supplied in millimetres.
    The residual field factor inherits F_visual unless explicitly overridden.
    It excludes atmosphere, throughput, magnification and the separate FT/FM.
    """
    parameters = {
        'aperture': aperture, 'magnification': magnification,
        'transmission': 0.95, 'n_surfaces': 6, 'central_obstruction': 0.0,
        'observer_age': 22.0, 'field_factor': F_visual, 'pupil_diameter_mm': None,
    }
    unknown = set(kwargs) - set(parameters)
    if unknown:
        raise TypeError('Unknown telescope configuration: ' + ', '.join(sorted(unknown)))
    parameters.update(kwargs)
    if parameters['field_factor'] is None:
        parameters['field_factor'] = F_visual
    if not math.isfinite(parameters['field_factor']) or parameters['field_factor'] <= 0:
        raise ValueError('field_factor must be positive and finite')
    TelescopeVisibilityModel().calculate_factors(
        D=parameters['aperture'], Ds=parameters['central_obstruction'],
        M=parameters['magnification'], De=parameters['pupil_diameter_mm'],
        age=parameters['observer_age'], t1=parameters['transmission'],
        n=parameters['n_surfaces'],
    )
    return parameters


def _validated_crescent_area_sr(posisi: Dict[str, float]) -> float:
    """Validate geometric domain while retaining E=0 as a no-source case."""
    elongation = float(posisi['elongation'])
    semidiameter = float(posisi['moon_semidiameter'])
    if not math.isfinite(elongation) or not (0 <= elongation <= 180):
        raise ValueError('Elongation must be finite and in [0, 180] degrees')
    if not math.isfinite(semidiameter) or semidiameter <= 0:
        raise ValueError('Moon semidiameter must be positive and finite')
    return arcmin2_to_sr(crescent_area_arcmin2(elongation, semidiameter))


def _threshold_gain_mag(naked_threshold: float, telescopic_threshold: float) -> float:
    """Threshold difference; -inf for blocked optics, zero for absent targets.

    Includes any difference in residual F as well as optics and FT/FM.
    """
    if naked_threshold <= 0 or telescopic_threshold <= 0:
        return 0.0
    if math.isinf(naked_threshold) and math.isinf(telescopic_threshold):
        return 0.0
    return 2.5 * (math.log10(naked_threshold) - math.log10(telescopic_threshold))


def _visibility_diagnostics(crumey_ne: dict, telescope_trace: Optional[dict],
                            F_naked: float, field_factor: float,
                            threshold_difference: float) -> dict:
    """Shared output contract for sunset, scan and refined optima."""
    tel = (telescope_trace or {}).get('coefficients') or {}
    return {
        'crumey_ne_regime': crumey_ne['regime'],
        'crumey_ne_achromatic_extrapolation': crumey_ne['achromatic_extrapolation'],
        'crumey_tel_regime': tel.get('regime'),
        'crumey_tel_achromatic_extrapolation': tel.get('achromatic_extrapolation'),
        'threshold_difference_mag': threshold_difference if telescope_trace else None,
        'field_factor_comparison': (
            'shared_residual_factor' if F_naked == field_factor else 'independent_residual_factors'
        ) if telescope_trace else None,
    }


def deg_to_dms(deg: float) -> str:
    """
    Konversi derajat desimal ke format derajat-menit-detik (DMS).
    
    Parameters:
    -----------
    deg : float
        Nilai dalam derajat desimal
        
    Returns:
    --------
    str
        String dalam format "DD° MM' SS.SS\""
    """
    sign = "-" if deg < 0 else ""
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = (deg - d - m / 60) * 3600
    return f"{sign}{d}° {m}' {s:.2f}\""


class HilalVisibilityCalculator:
    """Kelas utama untuk kalkulasi visibilitas hilal"""
    
    # Mapping nama sumber atmosfer untuk label
    SUMBER_ATMOSFER_LABEL = {
        'ecmwf_ifs': 'ECMWF IFS Historical (Open-Meteo API)',
        'merra2': 'MERRA-2 Reanalysis (NASA POWER API)',
        'manual': 'Input Manual',
    }

    def __init__(self,
                 nama_tempat: str,
                 lintang: float,
                 bujur: float,
                 elevasi: float,
                 timezone_str: str,
                 bulan_hijri: int,
                 tahun_hijri: int,
                 delta_day_offset: int = 0,
                 bias_t: float = 0.0,
                 bias_rh: float = 0.0,
                 sumber_atmosfer: str = 'ecmwf_ifs',
                 manual_rh: float = 80.0,
                 manual_t: float = 25.0,
                 manual_p: float = 1013.25):
        """
        Inisialisasi kalkulator visibilitas hilal.

        Parameters:
        -----------
        nama_tempat : str
            Nama lokasi pengamatan
        lintang : float
            Lintang dalam derajat (positif untuk utara, negatif untuk selatan)
        bujur : float
            Bujur dalam derajat (positif untuk timur, negatif untuk barat)
        elevasi : float
            Ketinggian dalam meter di atas permukaan laut
        timezone_str : str
            Zona waktu (contoh: "Asia/Jakarta" atau "+7")
        bulan_hijri : int
            Bulan hijriah (1-12)
        tahun_hijri : int
            Tahun hijriah
        delta_day_offset : int
            Offset hari untuk pengamatan (default: 0)
        bias_t : float
            Bias suhu reanalisis (°C), definisi: bias = Reanalisis - Obs (default: 0.0)
        bias_rh : float
            Bias RH reanalisis (%), definisi: bias = Reanalisis - Obs (default: 0.0)
        sumber_atmosfer : str
            Sumber data atmosfer: 'ecmwf_ifs', 'merra2', atau 'manual'
        manual_rh : float
            RH manual (%) jika sumber='manual'
        manual_t : float
            Suhu manual (°C) jika sumber='manual'
        manual_p : float
            Tekanan manual (mbar) jika sumber='manual'
        """
        self.nama_tempat = nama_tempat
        self.lintang = lintang
        self.bujur = bujur
        self.elevasi = elevasi
        self.timezone_str = timezone_str
        self.bulan_hijri = bulan_hijri
        self.tahun_hijri = tahun_hijri
        self.delta_day_offset = delta_day_offset
        self.bias_t = bias_t
        self.bias_rh = bias_rh
        self.sumber_atmosfer = sumber_atmosfer.lower()
        if self.sumber_atmosfer not in self.SUMBER_ATMOSFER_LABEL:
            raise ValueError(f"Sumber atmosfer tidak dikenal: '{sumber_atmosfer}'")
        self.manual_rh = manual_rh
        self.manual_t = manual_t
        self.manual_p = manual_p
        
        # Setup lokasi untuk perhitungan astronomis
        self.location = set_location(lintang, bujur, elevasi)
        
        # Catatan: parameter moonlight (ALTMOON, AZIMOON, PHASE_MOON, SNELLEN)
        # telah dihapus karena modul Schaefer sudah diadaptasi khusus untuk
        # visibilitas hilal (Bulan = objek pengamatan, bukan sumber background)
        
        # Hasil perhitungan akan disimpan di sini
        self.hasil: Dict[str, Any] = {}

    def _fetch_atmosfer(self,
                        observing_location: ObservingLocation,
                        waktu_utc: datetime,
                        verbose: bool = True,
                        *, record_provenance: bool = True) -> Tuple[float, float, float, float, float]:
        """
        Mengambil data atmosfer dan menerapkan koreksi bias.
        Dispatch berdasarkan self.sumber_atmosfer: 'ecmwf_ifs', 'merra2', atau 'manual'.

        Returns:
        --------
        rh_raw, temperature_raw, rh, temperature, pressure
        """
        indent = "  " if verbose else "    "
        sumber = self.sumber_atmosfer
        label = self.SUMBER_ATMOSFER_LABEL.get(sumber, sumber.upper())
        waktu_utc = normalize_utc_datetime(waktu_utc)

        if sumber == 'manual':
            rh_raw = self.manual_rh
            temperature_raw = self.manual_t
            pressure = self.manual_p
            validate_atmosphere(rh_raw, temperature_raw, pressure)
            if record_provenance:
                self._record_atmosphere_point(observing_location, waktu_utc, rh_raw, temperature_raw, pressure)
            if verbose:
                print(f"{indent}[✓] Data atmosfer MANUAL:")
                print(f"{indent}     RH={rh_raw:.2f}%, T={temperature_raw:.2f}°C, P={pressure:.2f} mbar")
            # Manual: tidak ada koreksi bias
            return rh_raw, temperature_raw, rh_raw, temperature_raw, pressure

        if sumber == 'ecmwf_ifs':
            try:
                window = fetch_atmospheric_window(observing_location, waktu_utc, waktu_utc)
                rh_raw, temperature_raw, pressure = window.at_time(waktu_utc)
                if record_provenance:
                    self.hasil.setdefault('atmosphere_provenance', []).append(window.to_record())
                if verbose:
                    print(f"{indent}[✓] Data atmosfer ECMWF_IFS berhasil diambil:")
                    print(f"{indent}     RH={rh_raw:.2f}%, T={temperature_raw:.2f}°C, P={pressure:.2f} mbar")
            except ECMWF_IFSAPIError as e:
                if verbose:
                    print(f"{indent}[!] ECMWF_IFS API Error: {e}")
                    print(f"{indent}[!] Observasi tidak valid: data atmosfer tidak tersedia.")
                raise

        elif sumber == 'merra2':
            try:
                loc_merra = MERRA2Location(
                    name=self.nama_tempat, latitude=self.lintang,
                    longitude=self.bujur, altitude=self.elevasi,
                    timezone=self.timezone_str
                )
                rh_raw, temperature_raw, pressure = merra2_get_rh_t(loc_merra, waktu_utc)
                if verbose:
                    print(f"{indent}[✓] Data atmosfer MERRA-2 berhasil diambil:")
                    print(f"{indent}     RH={rh_raw:.2f}%, T={temperature_raw:.2f}°C, P={pressure:.2f} kPa")
                # MERRA-2 mengembalikan tekanan dalam kPa, konversi ke mbar
                pressure = pressure * 10.0
            except PowerAPIError as e:
                if verbose:
                    print(f"{indent}[!] MERRA-2 API Error: {e}")
                    print(f"{indent}[!] Observasi tidak valid: data atmosfer tidak tersedia.")
                raise

        else:
            raise ValueError(f"Sumber atmosfer tidak dikenal: '{sumber}'")

        validate_atmosphere(rh_raw, temperature_raw, pressure)
        if record_provenance and sumber != 'ecmwf_ifs':
            self._record_atmosphere_point(observing_location, waktu_utc, rh_raw, temperature_raw, pressure)

        # Terapkan koreksi bias (untuk semua sumber API)
        rh, temperature, pressure = apply_bias_correction(
            rh_raw, temperature_raw, pressure,
            bias_t=self.bias_t,
            bias_rh=self.bias_rh
        )

        if verbose and (self.bias_t != 0.0 or self.bias_rh != 0.0):
            print(f"{indent}[Bias Correction] T: {temperature_raw:.2f} → {temperature:.2f}°C (bias={self.bias_t:+.1f})")
            print(f"{indent}[Bias Correction] RH: {rh_raw:.2f} → {rh:.2f}% (bias={self.bias_rh:+.1f})")

        return rh_raw, temperature_raw, rh, temperature, pressure

    def _atmosphere_metadata(self, location: ObservingLocation) -> Dict[str, Any]:
        metadata = {
            'source': self.SUMBER_ATMOSFER_LABEL[self.sumber_atmosfer],
            'requested_latitude': location.latitude,
            'requested_longitude': location.longitude,
            'requested_elevation': location.altitude,
            'time_axis_timezone': 'UTC',
            'units': {'relative_humidity_2m': '%', 'temperature_2m': '°C',
                      'surface_pressure': 'hPa'},
            'sampling': 'manual input' if self.sumber_atmosfer == 'manual'
                        else 'interpolated by provider adapter',
        }
        return metadata

    def _record_atmosphere_point(self, location, time_utc, rh, temperature, pressure):
        record = self._atmosphere_metadata(location)
        record['hourly_raw'] = [{
            'date': time_utc.isoformat(), 'relative_humidity_2m': float(rh),
            'temperature_2m': float(temperature), 'surface_pressure': float(pressure),
        }]
        self.hasil.setdefault('atmosphere_provenance', []).append(record)

    def _fetch_atmosfer_window(self, observing_location: ObservingLocation,
                              start_utc: datetime, end_utc: datetime,
                              verbose: bool = True) -> AtmosphericWindow:
        """Keep the real hourly anchors over the entire scan and refinement."""
        start_utc = normalize_utc_datetime(start_utc)
        end_utc = normalize_utc_datetime(end_utc)
        if end_utc < start_utc:
            raise ValueError('end_utc must not precede start_utc')
        if self.sumber_atmosfer == 'ecmwf_ifs':
            window = fetch_atmospheric_window(observing_location, start_utc, end_utc)
        else:
            lower = pd.Timestamp(start_utc).floor('h')
            upper = pd.Timestamp(end_utc).ceil('h')
            rows = []
            for i, timestamp in enumerate(pd.date_range(lower, upper, freq='h')):
                rh_raw, temperature_raw, _, _, pressure = self._fetch_atmosfer(
                    observing_location, timestamp.to_pydatetime(), verbose=verbose and i == 0,
                    record_provenance=False,
                )
                rows.append({'date': timestamp, 'relative_humidity_2m': rh_raw,
                             'temperature_2m': temperature_raw, 'surface_pressure': pressure})
            window = AtmosphericWindow(pd.DataFrame(rows), {
                **self._atmosphere_metadata(observing_location),
                'window_start_utc': start_utc.isoformat(), 'window_end_utc': end_utc.isoformat(),
            })
        self.hasil.setdefault('atmosphere_provenance', []).append(window.to_record())
        if verbose:
            print(f"  Atmosfer hourly tersedia: {start_utc.isoformat()} - {end_utc.isoformat()}")
        return window

    def _atmosfer_pada_waktu(self, window: AtmosphericWindow, target_utc: datetime):
        raw = window.at_time(target_utc)
        if self.sumber_atmosfer == 'manual':
            return raw
        return apply_bias_correction(*raw, bias_t=self.bias_t, bias_rh=self.bias_rh)

    def hitung_ijtima(self) -> Tuple[datetime, datetime]:
        """
        Menghitung waktu ijtima (konjungsi) untuk bulan hijriah yang ditentukan.
        
        Returns:
        --------
        ijtima_utc : datetime
            Waktu ijtima dalam UTC
        ijtima_local : datetime
            Waktu ijtima dalam waktu lokal
        """
        ijtima_utc = newmoon_hijri_month_utc(self.tahun_hijri, self.bulan_hijri)
        ijtima_local = convert_utc_to_localtime(self.timezone_str, utc_datetime=ijtima_utc)
        
        self.hasil['ijtima_utc'] = ijtima_utc
        self.hasil['ijtima_local'] = ijtima_local
        
        return ijtima_utc, ijtima_local
    
    def tentukan_tanggal_pengamatan(self, ijtima_utc: datetime) -> Tuple[datetime, datetime, float, float, float]:
        """
        Menentukan tanggal pengamatan berdasarkan waktu ijtima dan sunset.

        ALUR KOREKSI SUNSET:
        1. Hitung sunset GEOMETRIS (tanpa koreksi refraksi) menggunakan skyfield
        2. Gunakan waktu sunset geometris untuk mengambil data atmosfer (RH, T) dari sumber yang dipilih
        3. Hitung sunset APPARENT dengan koreksi refraksi menggunakan T dari API
        4. Data RH dan T digunakan untuk perhitungan sky brightness

        ATURAN HISAB:
        1. Konversi ijtima UTC ke waktu lokal
        2. Jika ijtima lokal terjadi sebelum jam 12:00 (tengah malam - siang):
           - Gunakan tanggal ijtima lokal untuk pengamatan (sore hari itu)
        3. Jika ijtima lokal terjadi setelah jam 12:00 (siang - tengah malam):
           - Bandingkan dengan sunset lokal sore hari itu
           - Jika ijtima < sunset: amati hari berikutnya
           - Jika ijtima >= sunset: amati hari yang sama

        Contoh untuk kasus Muharram 1444 (29 Juli 2022):
        - Ijtima UTC: 2022-07-28 17:55:02
        - Ijtima Lokal (WIB): 2022-07-29 00:55:02
        - Karena ijtima lokal (00:55) < 12:00, maka pengamatan dilakukan pada 29 Juli 2022 sore
        - Sunset 29 Juli sore: ~17:30 WIB -> Bulan sudah cukup tinggi untuk diamati

        Parameters:
        -----------
        ijtima_utc : datetime
            Waktu ijtima dalam UTC

        Returns:
        --------
        sunset_utc : datetime
            Waktu sunset dalam UTC pada hari pengamatan
        sunset_local : datetime
            Waktu sunset dalam waktu lokal (dengan koreksi refraksi)
        rh : float
            Relative humidity dalam persen (dari API, terkoreksi bias)
        temperature : float
            Suhu dalam derajat Celsius (dari API, terkoreksi bias)
        pressure : float
            Tekanan udara dalam mbar (dari API)
        """
        # Konversi ijtima ke waktu lokal
        ijtima_local = convert_utc_to_localtime(self.timezone_str, utc_datetime=ijtima_utc)

        # Aturan sederhana berdasarkan jam ijtima lokal
        if ijtima_local.hour < 12:
            # Ijtima terjadi sebelum jam 12:00 (tengah malam sampai sebelum siang)
            tanggal_pengamatan = ijtima_local.date()
        else:
            # Ijtima terjadi setelah jam 12:00 (siang sampai tengah malam)
            # Gunakan sunrise_sunset_local untuk estimasi sunset
            _, sunset_local_ijtima = sunrise_sunset_local(
                self.location,
                self.timezone_str,
                year=ijtima_utc.year,
                month=ijtima_utc.month,
                day=ijtima_utc.day
            )

            if ijtima_local < sunset_local_ijtima:
                tanggal_pengamatan = ijtima_local.date() + timedelta(days=1)
            else:
                tanggal_pengamatan = ijtima_local.date()

        # Terapkan delta day offset
        tanggal_pengamatan += timedelta(days=self.delta_day_offset)

        # LANGKAH 1: Hitung ESTIMASI sunset untuk fetch weather
        # Gunakan default T dan P untuk estimasi awal (standard refraction)
        _, sunset_est_local = sunrise_sunset_local(
            self.location,
            self.timezone_str,
            year=tanggal_pengamatan.year,
            month=tanggal_pengamatan.month,
            day=tanggal_pengamatan.day
        )
        sunset_est_utc = convert_localtime_to_utc(self.timezone_str, local_datetime=sunset_est_local)

        # LANGKAH 2: Ambil data atmosfer (RH dan T) pada waktu sunset geometris
        loc = ObservingLocation(
            name=self.nama_tempat,
            latitude=self.lintang,
            longitude=self.bujur,
            altitude=self.elevasi,
            timezone=self.timezone_str
        )

        # Pastikan sunset_est_utc adalah timezone-aware UTC datetime
        if sunset_est_utc.tzinfo is None or sunset_est_utc.tzinfo.utcoffset(sunset_est_utc) is None:
            sunset_est_utc = sunset_est_utc.replace(tzinfo=timezone.utc)

        # Ambil data atmosfer dan terapkan koreksi bias
        rh_raw, temperature_raw, rh, temperature, pressure = self._fetch_atmosfer(
            loc, sunset_est_utc, verbose=True
        )

        # LANGKAH 3: Hitung sunset APPARENT dengan koreksi refraksi menggunakan T terkoreksi
        _, sunset_local = sunrise_sunset_local(
            self.location,
            self.timezone_str,
            year=tanggal_pengamatan.year,
            month=tanggal_pengamatan.month,
            day=tanggal_pengamatan.day,
            temperature_C=temperature,  # Gunakan temperature terkoreksi
            pressure_mbar=pressure  # Gunakan pressure dari API
        )

        # Konversi sunset lokal ke UTC
        sunset_utc = convert_localtime_to_utc(self.timezone_str, local_datetime=sunset_local)

        # Simpan hasil (raw + corrected)
        self.hasil['sunset_utc'] = sunset_utc
        self.hasil['sunset_local'] = sunset_local
        self.hasil['sunset_est_utc'] = sunset_est_utc
        self.hasil['sunset_est_local'] = sunset_est_local
        self.hasil['tanggal_pengamatan'] = datetime.combine(tanggal_pengamatan, datetime.min.time())
        self.hasil['rh_raw'] = rh_raw
        self.hasil['temperature_raw'] = temperature_raw
        self.hasil['rh'] = rh
        self.hasil['temperature'] = temperature
        self.hasil['pressure'] = pressure
        self.hasil['bias_t'] = self.bias_t
        self.hasil['bias_rh'] = self.bias_rh
        self.hasil['sumber_atmosfer'] = self.sumber_atmosfer
        self.hasil['observing_location'] = loc  # Simpan untuk digunakan di loop optimal

        return sunset_utc, sunset_local, rh, temperature, pressure
    
    def hitung_posisi_matahari_bulan(self, sunset_local: datetime,
                                     temperature_C: float = 10.0,
                                     pressure_mbar: float = 1030.0) -> Dict[str, float]:
        """
        Menghitung posisi matahari dan bulan saat sunset.
        
        Parameters:
        -----------
        sunset_local : datetime
            Waktu sunset dalam waktu lokal
        temperature_C : float
            Suhu udara dalam derajat Celsius (untuk koreksi refraksi)
        pressure_mbar : float
            Tekanan udara dalam mbar (untuk koreksi refraksi)
            
        Returns:
        --------
        Dict[str, float]
            Dictionary berisi:
            - sun_alt: Altitude matahari (derajat)
            - sun_az: Azimuth matahari (derajat)
            - moon_alt: Altitude bulan (derajat)
            - moon_az: Azimuth bulan (derajat)
            - elongation: Elongasi toposentrik (derajat)
            - phase_angle: Sudut fase bulan (derajat)
            - moon_semidiameter: Semidiameter toposentrik bulan (derajat)
            - moon_distance_km: Jarak astrometrik pengamat ke Bulan (km), DE440s
        """
        # Posisi matahari (menggunakan local time + koreksi refraksi dinamis)
        sun_alt, sun_az, _ = sun_position_time_local(
            self.location,
            self.timezone_str,
            local_datetime=sunset_local,
            temperature_C=temperature_C,
            pressure_mbar=pressure_mbar
        )
        
        # Posisi bulan (menggunakan local time + koreksi refraksi dinamis)
        moon_alt, moon_az, moon_distance_km = moon_position_time_local(
            self.location,
            self.timezone_str,
            local_datetime=sunset_local,
            temperature_C=temperature_C,
            pressure_mbar=pressure_mbar
        )
        
        # Elongasi toposentrik
        elongation = moon_elongation_time_local(
            self.timezone_str,
            location=self.location,
            local_datetime=sunset_local
        )
        
        # Sudut fase bulan
        phase_angle = moon_phase_angle_time_local(
            self.timezone_str,
            location=self.location,
            local_datetime=sunset_local
        )
        
        # Radius sudut dari jarak astrometrik; lebar dari fase iluminasi.
        moon_semidiameter = moon_semidiameter_from_distance(moon_distance_km)
        moon_width = moon_semidiameter * (1.0 + math.cos(math.radians(phase_angle)))
        
        return {
            'sun_alt': sun_alt,
            'sun_az': sun_az,
            'moon_alt': moon_alt,
            'moon_az': moon_az,
            'elongation': elongation,
            'phase_angle': phase_angle,
            'moon_semidiameter': moon_semidiameter,
            'moon_distance_km': float(moon_distance_km),
            'moon_width': moon_width,
        }
    
    def hitung_sky_brightness_schaefer(
        self,
        rh: float,
        temperature: float,
        posisi: Dict[str, float],
    ) -> Tuple[float, float, float, float]:
        """Return B_sky [nL], k_v [mag/airmass], A_V [mag], dan T_V.

        K dan DM tetap dihitung oleh Schaefer. k_v hanya untuk diagnostik;
        source model menerima transmission_v, bukan koefisien ekstingsi.
        Jika Schaefer gagal, propagasikan error agar tidak memakai ekstingsi
        asumsi yang tidak memiliki total kehilangan cahaya sepanjang LOS.
        """
        azisun = abs(posisi['sun_az'] - posisi['moon_az'])
        result = hitung_sky_brightness(
            month=self.hasil['tanggal_pengamatan'].month,
            year=self.hasil['tanggal_pengamatan'].year,
            altsun=posisi['sun_alt'],
            azisun=azisun,
            humidity=rh,
            temperature=temperature,
            latitude=self.lintang,
            elevation=self.elevasi,
            alt_objek=max(posisi['moon_alt'], 0.0),
        )
        B_sky_nL = float(result["sky_brightness"])
        if B_sky_nL <= 0:
            raise ValueError("Sky brightness Schaefer harus positif.")
        self._scene_atmosphere = result
        return (
            B_sky_nL,
            float(result["k_v"]),
            float(result["extinction_mag_v"]),
            float(result["transmission_v"]),
        )

    def hitung_luminansi_hilal_kastner(
        self,
        posisi: Dict[str, float],
        transmission_v: float,
    ) -> float:
        """Direct/excess luminance hilal [nL] dengan transmisi Schaefer."""
        photometry = hitung_fotometri_intrinsik(
            phase_angle_deg=posisi['phase_angle'],
            elongation_deg=posisi['elongation'],
            r_deg=float(posisi['moon_semidiameter']),
        )
        self._scene_photometry = photometry
        return terapkan_transmisi_atmosfer(photometry['L_star_s10'], transmission_v)
    
    def hitung_visibilitas_naked_eye(self,
                                      luminansi_hilal_nl: float,
                                      sky_brightness_nl: float,
                                      posisi: dict,
                                      F_naked: float = DEFAULT_VISUAL_FIELD_FACTOR) -> tuple:
        """
        Menghitung visibilitas hilal mata telanjang menggunakan model Crumey (2014).

        Hilal memberi increment cahaya di atas background:
          C_obj = delta_B_obj / B_sky.
        Luas dari elongasi dan background menentukan threshold Crumey.

        Parameters
        ----------
        luminansi_hilal_nl : float
            Direct/excess luminance hilal [nL] dari model Kastner
        sky_brightness_nl : float
            Kecerahan langit [nanoLambert] dari model Schaefer
        posisi : dict
            Dictionary posisi matahari & bulan (harus berisi:
            'elongation', 'moon_semidiameter')
        F_naked : float
            Residual visual field factor (referensi 2.0, belum dikalibrasi
            khusus hilal); tidak menggandakan efek fisik yang sudah eksplisit.

        Returns
        -------
        rasio_kontras : float
            Kontras increment C_obj = L_obj / B_sky
        delta_m : float
            Margin [mag]: 2.5 * log10(C_obj / C_th)
            Positif = terlihat, negatif = tidak terlihat
        crumey_result : dict
            Hasil lengkap dari hilal_naked_eye_visibility()
        """
        if not math.isfinite(sky_brightness_nl) or sky_brightness_nl <= 0.0:
            raise ValueError("Sky brightness harus positif dan finite")
        if not math.isfinite(luminansi_hilal_nl) or luminansi_hilal_nl < 0:
            raise ValueError('Luminansi excess harus non-negatif dan finite')
        if not math.isfinite(F_naked) or F_naked <= 0:
            raise ValueError('F_naked must be positive and finite')
        _validated_crescent_area_sr(posisi)

        # Panggil model Crumey untuk naked eye
        result = hilal_naked_eye_visibility(
            L_hilal_nL=luminansi_hilal_nl,
            B_sky_nL=sky_brightness_nl,
            elongation_deg=posisi['elongation'],
            moon_sd_deg=float(posisi['moon_semidiameter']),
            F=F_naked,
            mode='auto',  # kurva combined pada seluruh background
        )

        rasio_kontras = result['C_obj']
        delta_m = result['delta_m']


        return rasio_kontras, delta_m, result
    
    def hitung_visibilitas_teleskop(self,
                                     luminansi_hilal_nl: float,
                                     sky_brightness_nl: float,
                                     posisi: Dict[str, float],
                                     aperture: float = 66.0,
                                     magnification: float = 50.0,
                                     transmission: float = 0.95,
                                     n_surfaces: int = 6,
                                     central_obstruction: float = 0.0,
                                     observer_age: float = 22.0,
                                     field_factor: float = DEFAULT_VISUAL_FIELD_FACTOR,
                                     pupil_diameter_mm: Optional[float] = None
                                     ) -> Tuple[float, float, float, float, float]:
        """Extended-source visibility with the shared Crumey threshold contract.

        Target excess and sky luminance receive the same annulus-aware optical
        factor g; retinal area is M^2 A. Monocular sqrt(2) corrects the threshold.
        FM=1 is an optical/observer assumption (Secs. 1.6.4 and 3.2), not Eq. 83
        and not an empirically established crescent calibration.

        ``observer_age`` affects only the fallback pupil estimate, without an
        age-dependent sensitivity correction. ``pupil_diameter_mm`` overrides
        that estimate for a measured or independently modelled twilight pupil.
        Transmission is per optical surface; obstruction and pupil use mm.
        field_factor is residual laboratory/observer/target/viewing scaling,
        excluding atmosphere, throughput, magnification and separate FT/FM.

        Returns (L_apparent_nL, B_apparent_nL, C_object, C_threshold, margin_mag).
        Positive margin means above the model threshold. A centred pupil fully
        hidden by the secondary shadow gives zero throughput and margin -inf.
        Invalid physical inputs raise ValueError instead of yielding NaNs.
        """
        if not math.isfinite(sky_brightness_nl) or sky_brightness_nl <= 0:
            raise ValueError('Sky brightness harus positif dan finite')
        if not math.isfinite(luminansi_hilal_nl) or luminansi_hilal_nl < 0:
            raise ValueError('Luminansi excess harus non-negatif dan finite')
        if not math.isfinite(field_factor) or field_factor <= 0:
            raise ValueError('field_factor must be positive and finite')

        A_sr = _validated_crescent_area_sr(posisi)
        factors = TelescopeVisibilityModel().calculate_factors(
            D=aperture, Ds=central_obstruction, M=magnification,
            De=pupil_diameter_mm, age=observer_age, t1=transmission,
            n=n_surfaces,
        )
        g = factors['surface_brightness_factor']
        self._scene_telescope = {'optics': factors, 'threshold': None,
                                'coefficients': threshold_parameters(nL_to_cd_m2(sky_brightness_nl * g))}
        I_eff = luminansi_hilal_nl * g
        B_eff = sky_brightness_nl * g
        C_obj = luminansi_hilal_nl / sky_brightness_nl
        if A_sr == 0:
            return I_eff, B_eff, C_obj, float('inf'), float('-inf')
        threshold = telescopic_extended_threshold(
            A_sr, nL_to_cd_m2(sky_brightness_nl), aperture / 1000.0,
            magnification, p=factors['De'] / 1000.0, Ft=factors['Ft'],
            F=field_factor, FT=math.sqrt(2), FM=1.0, mode='auto',
            dimming_factor=g,
        )
        c_th_tel = threshold['C_th']
        self._scene_telescope['threshold'] = threshold
        delta_m_tel = visibility_margin_mag(C_obj, c_th_tel)
        return I_eff, B_eff, C_obj, c_th_tel, delta_m_tel

    def hitung_visibilitas_pada_waktu(self,
                                       waktu_local: datetime,
                                       observing_location: ObservingLocation,
                                       aperture: float = 66.0,
                                       magnification: float = 50.0,
                                       F_naked: float = DEFAULT_VISUAL_FIELD_FACTOR,
                                       field_factor: Optional[float] = None,
                                       cached_atm: Optional[Tuple[float, float, float]] = None,
                                       transmission: float = 0.95,
                                       n_surfaces: int = 6,
                                       central_obstruction: float = 0.0,
                                       observer_age: float = 22.0,
                                       pupil_diameter_mm: Optional[float] = None,
                                       use_telescope: bool = True,
                                       ) -> Dict[str, Any]:
        """
        Menghitung visibilitas hilal pada waktu tertentu.

        Parameters
        ----------
        cached_atm : (rh, temperature, pressure) atau None
            Jika diberikan, gunakan data atmosfer ini (dari interpolasi)
            tanpa melakukan API call. Jika None, fetch via API.
        field_factor : float atau None
            Residual F teleskop; None mengikuti F_naked untuk perbandingan
            dengan base visual yang sama. Nilai eksplisit tetap didukung.
        """
        field_factor = F_naked if field_factor is None else field_factor
        if cached_atm is not None:
            rh, temperature, pressure = cached_atm
            validate_atmosphere(rh, temperature, pressure)
        else:
            # Konversi waktu lokal ke UTC untuk API call
            waktu_utc = waktu_local.astimezone(timezone.utc)
            _, _, rh, temperature, pressure = self._fetch_atmosfer(
                observing_location, waktu_utc, verbose=False
            )
        
        # LANGKAH 2: Hitung posisi matahari dan bulan dengan T/P dinamis
        posisi = self.hitung_posisi_matahari_bulan(
            waktu_local,
            temperature_C=temperature,
            pressure_mbar=pressure
        )
        
        # Jika bulan sudah di bawah horizon, kembalikan hasil kosong
        if posisi['moon_alt'] <= 0:
            return {
                'waktu_local': waktu_local,
                'moon_alt': posisi['moon_alt'],
                'sun_alt': posisi['sun_alt'],
                'valid': False,
                'delta_m_ne': -99.0,
                'delta_m_tel': -99.0,
                'telescope_gain': 0.0,
                'rh': rh,
                'temperature': temperature
            }
        
        # LANGKAH 3: Hitung sky brightness (Schaefer)
        sky_brightness_nl, k_v, extinction_mag_v, transmission_v = self.hitung_sky_brightness_schaefer(rh, temperature, posisi)
        
        # Hitung luminansi hilal (Kastner)
        luminansi_hilal_nl = self.hitung_luminansi_hilal_kastner(posisi, transmission_v)
        
        # Hitung visibilitas naked eye
        rasio_kontras_ne, delta_m_ne, crumey_ne = self.hitung_visibilitas_naked_eye(
            luminansi_hilal_nl, sky_brightness_nl, posisi, F_naked=F_naked
        )

        # The same optical configuration is used for every evaluated time.
        if use_telescope:
            (luminansi_hilal_tel_nl, sky_brightness_tel_nl,
             rasio_kontras_tel, c_th_tel, delta_m_tel) = self.hitung_visibilitas_teleskop(
                luminansi_hilal_nl, sky_brightness_nl, posisi,
                aperture=aperture, magnification=magnification,
                transmission=transmission, n_surfaces=n_surfaces,
                central_obstruction=central_obstruction, observer_age=observer_age,
                field_factor=field_factor, pupil_diameter_mm=pupil_diameter_mm,
            )
        else:
            luminansi_hilal_tel_nl = sky_brightness_tel_nl = 0.0
            rasio_kontras_tel = c_th_tel = delta_m_tel = 0.0

        # Threshold difference; telescope_gain is the compatibility alias.
        c_th_ne = crumey_ne['C_th']
        telescope_gain = _threshold_gain_mag(c_th_ne, c_th_tel)

        return {
            'waktu_local': waktu_local,
            'moon_alt': posisi['moon_alt'],
            'sun_alt': posisi['sun_alt'],
            'moon_az': posisi['moon_az'],
            'sun_az': posisi['sun_az'],
            'moon_width': posisi.get('moon_width'),
            'elongation': posisi['elongation'],
            'phase_angle': posisi['phase_angle'],
            'moon_semidiameter': posisi['moon_semidiameter'],
            'moon_distance_km': posisi['moon_distance_km'],
            'sky_brightness_nl': sky_brightness_nl,
            'luminansi_hilal_nl': luminansi_hilal_nl,
            'luminansi_hilal_tel_nl': luminansi_hilal_tel_nl,
            'sky_brightness_tel_nl': sky_brightness_tel_nl,
            'k_v': k_v,
            'extinction_mag_v': extinction_mag_v,
            'transmission_v': transmission_v,
            'delta_m_ne': delta_m_ne,
            'delta_m_tel': delta_m_tel,
            'rasio_kontras_ne': rasio_kontras_ne,
            'rasio_kontras_tel': rasio_kontras_tel,
            'c_th_tel': c_th_tel,
            'telescope_gain': telescope_gain,
            'rh': rh,
            'temperature': temperature,
            'pressure': pressure,
            'crumey_ne_C_th': crumey_ne['C_th'],
            **_visibility_diagnostics(
                crumey_ne, self._scene_telescope if use_telescope else None,
                F_naked, field_factor, telescope_gain,
            ),
            'model_trace': {
                'photometry': getattr(self, '_scene_photometry', None),
                'atmosphere': getattr(self, '_scene_atmosphere', None),
                'naked_eye': crumey_ne,
                'naked_eye_coefficients': threshold_parameters(nL_to_cd_m2(sky_brightness_nl)),
                'telescope': self._scene_telescope if use_telescope else None,
            },
            'valid': True
        }
    
    def cari_visibilitas_optimal(self,
                                  sunset_local: datetime,
                                  observing_location: ObservingLocation,
                                  aperture: float = 66.0,
                                  magnification: float = 50.0,
                                  F_naked: float = DEFAULT_VISUAL_FIELD_FACTOR,
                                  field_factor: Optional[float] = None,
                                  interval_menit: int = 1,
                                  min_moon_alt: float = 2.0,
                                  start_delay_menit: int = 1,
                                  transmission: float = 0.95,
                                  n_surfaces: int = 6,
                                  central_obstruction: float = 0.0,
                                  observer_age: float = 22.0,
                                  pupil_diameter_mm: Optional[float] = None,
                                  use_telescope: bool = True) -> Dict[str, Any]:
        """
        Loop dari sunset hingga bulan mendekati horizon untuk mencari
        waktu optimal (delta_m maksimum).

        Perbaikan v2:
        - Atmosfer hourly mencakup seluruh scan dan refinement
        - Default interval 1 menit (sebelumnya 2 menit)
        - Refinement ±2 menit di sekitar puncak dengan step 15 detik
        - Track window visibilitas kontinu (start, end, durasi terpanjang)
        - Start delay 1 menit agar teleskop bisa mendeteksi lebih awal

        Parameters
        ----------
        interval_menit : int
            Interval antar timestep dalam menit (default 1)
        min_moon_alt : float
            Altitude bulan minimum (derajat) sebelum loop berhenti (default 2.0)
        start_delay_menit : int
            Delay setelah sunset sebelum loop dimulai (default 1)
        """
        if not math.isfinite(interval_menit) or interval_menit <= 0:
            raise ValueError('interval_menit must be positive and finite')
        if not math.isfinite(start_delay_menit) or start_delay_menit < 0:
            raise ValueError('start_delay_menit must be nonnegative and finite')
        if not math.isfinite(min_moon_alt) or not (0 <= min_moon_alt <= 90):
            raise ValueError('min_moon_alt must be finite and in [0, 90] degrees')
        if not math.isfinite(F_naked) or F_naked <= 0:
            raise ValueError('F_naked must be positive and finite')
        telescope_config = _telescope_configuration(
            aperture, magnification, F_visual=F_naked,
            transmission=transmission, n_surfaces=n_surfaces,
            central_obstruction=central_obstruction, observer_age=observer_age,
            field_factor=field_factor, pupil_diameter_mm=pupil_diameter_mm,
        )
        print(f"\n  Mencari visibilitas optimal (interval: {interval_menit} menit, "
              f"start delay: {start_delay_menit} menit)...")

        # ── Fetch atmosfer hourly untuk scan dan refinement ──────────────────────
        sunset_utc = convert_localtime_to_utc(self.timezone_str, local_datetime=sunset_local)
        if sunset_utc.tzinfo is None:
            sunset_utc = sunset_utc.replace(tzinfo=timezone.utc)
        max_steps = 120
        scan_start_utc = sunset_utc + timedelta(minutes=start_delay_menit)
        scan_end_utc = scan_start_utc + timedelta(minutes=(max_steps - 1) * interval_menit)
        atmosphere_window = self._fetch_atmosfer_window(
            observing_location, scan_start_utc - timedelta(minutes=2),
            scan_end_utc + timedelta(minutes=2), verbose=True,
        )

        # ── Inisialisasi tracking ─────────────────────────────────────────
        best_result_ne = None
        best_result_tel = None
        best_delta_m_ne = float('-inf')
        best_delta_m_tel = float('-inf')

        # Tracking visibility window: first & last visible
        visibility_start_ne = None
        visibility_end_ne = None
        visibility_start_tel = None
        visibility_end_tel = None

        # Tracking window kontinu terpanjang (NE)
        current_streak_ne = 0
        longest_streak_ne = 0
        streak_start_ne = None
        last_visible_in_streak_ne = None
        best_window_start_ne = None
        best_window_end_ne = None

        # Tracking window kontinu terpanjang (Teleskop)
        current_streak_tel = 0
        longest_streak_tel = 0
        streak_start_tel = None
        last_visible_in_streak_tel = None
        best_window_start_tel = None
        best_window_end_tel = None

        all_results = []
        current_time = sunset_local + timedelta(minutes=start_delay_menit)
        step_count = 0

        # ── Loop utama (kasar) ────────────────────────────────────────────
        while step_count < max_steps:
            # Interpolasi atmosfer untuk waktu ini
            waktu_utc = convert_localtime_to_utc(self.timezone_str, local_datetime=current_time)
            if waktu_utc.tzinfo is None:
                waktu_utc = waktu_utc.replace(tzinfo=timezone.utc)
            rh, temperature, pressure = self._atmosfer_pada_waktu(atmosphere_window, waktu_utc)

            result = self.hitung_visibilitas_pada_waktu(
                current_time, observing_location, **telescope_config,
                F_naked=F_naked, use_telescope=use_telescope,
                cached_atm=(rh, temperature, pressure)
            )

            all_results.append(result)

            if not result['valid'] or result['moon_alt'] < min_moon_alt:
                print(f"    Berhenti: moon_alt = {result['moon_alt']:.2f}° (< {min_moon_alt}°)")
                break

            # Track best NE
            if best_result_ne is None or result['delta_m_ne'] > best_delta_m_ne:
                best_delta_m_ne = result['delta_m_ne']
                best_result_ne = result

            # Track best telescope
            if use_telescope and (best_result_tel is None or result['delta_m_tel'] > best_delta_m_tel):
                best_delta_m_tel = result['delta_m_tel']
                best_result_tel = result

            # ── Track NE visibility window ────────────────────────────────
            if result['delta_m_ne'] > 0:
                if visibility_start_ne is None:
                    visibility_start_ne = current_time
                visibility_end_ne = current_time
                # Track streak kontinu
                if current_streak_ne == 0:
                    streak_start_ne = current_time
                current_streak_ne += 1
                last_visible_in_streak_ne = current_time
            else:
                if current_streak_ne > longest_streak_ne:
                    longest_streak_ne = current_streak_ne
                    best_window_start_ne = streak_start_ne
                    best_window_end_ne = last_visible_in_streak_ne
                current_streak_ne = 0

            # ── Track telescope visibility window ─────────────────────────
            if result['delta_m_tel'] > 0:
                if visibility_start_tel is None:
                    visibility_start_tel = current_time
                visibility_end_tel = current_time
                if current_streak_tel == 0:
                    streak_start_tel = current_time
                current_streak_tel += 1
                last_visible_in_streak_tel = current_time
            else:
                if current_streak_tel > longest_streak_tel:
                    longest_streak_tel = current_streak_tel
                    best_window_start_tel = streak_start_tel
                    best_window_end_tel = last_visible_in_streak_tel
                current_streak_tel = 0

            # Tampilkan progress
            waktu_str = result['waktu_local'].strftime('%H:%M:%S')
            rh_val = result.get('rh', 0) or 0
            t_val = result.get('temperature', 0) or 0
            print(f"    {waktu_str} | alt={result['moon_alt']:5.2f} | "
                  f"RH={rh_val:5.1f}% | T={t_val:5.1f}C | "
                  f"B={result['sky_brightness_nl']:8.1e} | "
                  f"L={result['luminansi_hilal_nl']:8.1e} | "
                  f"dm_ne={result['delta_m_ne']:+5.2f} | "
                  f"dm_tel={result['delta_m_tel']:+5.2f} | "
                  f"selisih_threshold={result['telescope_gain']:+.2f}")

            current_time += timedelta(minutes=interval_menit)
            step_count += 1

        # Finalisasi streak terakhir (jika loop berakhir saat masih visible)
        if current_streak_ne > longest_streak_ne:
            longest_streak_ne = current_streak_ne
            best_window_start_ne = streak_start_ne
            best_window_end_ne = last_visible_in_streak_ne
        if current_streak_tel > longest_streak_tel:
            longest_streak_tel = current_streak_tel
            best_window_start_tel = streak_start_tel
            best_window_end_tel = last_visible_in_streak_tel

        print(f"  Selesai loop kasar: {len(all_results)} timestep dihitung")

        # ── Refinement: presisi tinggi di sekitar puncak ──────────────────
        if best_result_ne or best_result_tel:
            peak_times = []
            if best_result_ne:
                peak_times.append(best_result_ne['waktu_local'])
            if best_result_tel:
                peak_times.append(best_result_tel['waktu_local'])

            refine_start = max(
                sunset_local + timedelta(minutes=start_delay_menit),
                min(peak_times) - timedelta(minutes=2),
            )
            refine_end = max(peak_times) + timedelta(minutes=2)
            refine_step = timedelta(seconds=15)

            print(f"\n  Refinement: {refine_start.strftime('%H:%M:%S')} - "
                  f"{refine_end.strftime('%H:%M:%S')} (per 15 detik)")

            t_refine = refine_start
            while t_refine <= refine_end:
                waktu_utc_r = convert_localtime_to_utc(
                    self.timezone_str, local_datetime=t_refine
                )
                if waktu_utc_r.tzinfo is None:
                    waktu_utc_r = waktu_utc_r.replace(tzinfo=timezone.utc)
                rh_r, temp_r, pres_r = self._atmosfer_pada_waktu(atmosphere_window, waktu_utc_r)
                result_r = self.hitung_visibilitas_pada_waktu(
                    t_refine, observing_location, **telescope_config,
                    F_naked=F_naked, use_telescope=use_telescope,
                    cached_atm=(rh_r, temp_r, pres_r)
                )
                if result_r['valid'] and result_r['moon_alt'] >= min_moon_alt:
                    if best_result_ne is None or result_r['delta_m_ne'] > best_delta_m_ne:
                        best_delta_m_ne = result_r['delta_m_ne']
                        best_result_ne = result_r
                        print(f"    ^ NE peak refined: "
                              f"{t_refine.strftime('%H:%M:%S')} "
                              f"dm={result_r['delta_m_ne']:+.4f}")
                    if use_telescope and (best_result_tel is None or result_r['delta_m_tel'] > best_delta_m_tel):
                        best_delta_m_tel = result_r['delta_m_tel']
                        best_result_tel = result_r
                        print(f"    ^ Tel peak refined: "
                              f"{t_refine.strftime('%H:%M:%S')} "
                              f"dm={result_r['delta_m_tel']:+.4f}")
                t_refine += refine_step

        # ── Durasi window kontinu terpanjang ──────────────────────────────
        visibility_duration_ne = longest_streak_ne * interval_menit
        visibility_duration_tel = longest_streak_tel * interval_menit

        return {
            'optimal_time_ne': best_result_ne['waktu_local'] if best_result_ne else None,
            'optimal_delta_m_ne': best_delta_m_ne,
            'optimal_moon_alt_ne': best_result_ne['moon_alt'] if best_result_ne else None,
            'optimal_time_tel': best_result_tel['waktu_local'] if best_result_tel else None,
            'optimal_delta_m_tel': best_delta_m_tel,
            'optimal_moon_alt_tel': best_result_tel['moon_alt'] if best_result_tel else None,
            'optimal_sun_alt_tel': best_result_tel['sun_alt'] if best_result_tel else None,
            'optimal_telescope_gain': best_result_tel.get('telescope_gain', 0.0) if best_result_tel else 0.0,
            'optimal_threshold_difference_mag': best_result_tel.get('threshold_difference_mag') if best_result_tel else None,
            'best_result_ne': best_result_ne,
            'best_result_tel': best_result_tel,
            'visibility_duration_ne': visibility_duration_ne,
            'visibility_duration_tel': visibility_duration_tel,
            'visibility_start_ne': visibility_start_ne,
            'visibility_start_tel': visibility_start_tel,
            'visibility_end_ne': visibility_end_ne,
            'visibility_end_tel': visibility_end_tel,
            'best_window_start_ne': best_window_start_ne,
            'best_window_end_ne': best_window_end_ne,
            'best_window_start_tel': best_window_start_tel,
            'best_window_end_tel': best_window_end_tel,
            'total_timesteps': len(all_results),
            'all_results': all_results
        }


    
    def jalankan_perhitungan_lengkap(self,
                                      use_telescope: bool = True,
                                      aperture: float = 100.0,
                                      magnification: float = 50.0,
                                      F_naked: float = DEFAULT_VISUAL_FIELD_FACTOR,
                                      mode: str = "sunset",
                                      interval_menit: int = 1,
                                      min_moon_alt: float = 2.0,
                                      start_delay_menit: int = 1,
                                      **telescope_kwargs) -> Dict[str, Any]:
        """
        Menjalankan seluruh algoritma perhitungan visibilitas hilal.

        ALUR PROGRAM:
        1. Hitung ijtima/konjungsi
        2. Tentukan tanggal pengamatan dan hitung sunset dengan alur koreksi:
           a. Hitung sunset geometris (tanpa refraksi)
           b. Ambil data atmosfer (RH, T) dari sumber yang dipilih pada waktu sunset geometris
           c. Hitung sunset apparent dengan koreksi refraksi menggunakan T dari API
        3. Hitung posisi matahari dan bulan saat sunset
        4. Hitung sky brightness menggunakan model Schaefer (dengan RH dan T dari API)
        5. Hitung luminansi hilal menggunakan model Kastner
        6. Hitung visibilitas naked eye dan teleskop

        Parameters:
        -----------
        use_telescope : bool
            Apakah akan menghitung visibilitas teleskop
        aperture : float
            Diameter aperture teleskop (mm)
        magnification : float
            Pembesaran teleskop

        Returns:
        --------
        Dict[str, Any]
            Dictionary berisi seluruh hasil perhitungan
        """
        if mode.lower() not in {'sunset', 'optimal'}:
            raise ValueError("mode must be 'sunset' or 'optimal'")
        if not math.isfinite(F_naked) or F_naked <= 0:
            raise ValueError('F_naked must be positive and finite')
        telescope_config = _telescope_configuration(
            aperture, magnification, F_visual=F_naked, **telescope_kwargs,
        )
        print("Menjalankan perhitungan visibilitas hilal...")

        # Langkah 1: Hitung ijtima
        ijtima_utc, ijtima_local = self.hitung_ijtima()

        # Langkah 2: Tentukan tanggal pengamatan dan hitung sunset dengan koreksi refraksi
        sunset_utc, sunset_local, rh, temperature, pressure = self.tentukan_tanggal_pengamatan(ijtima_utc)

        # Langkah 3: Hitung posisi matahari dan bulan (menggunakan local time)
        posisi = self.hitung_posisi_matahari_bulan(
            sunset_local,
            temperature_C=temperature,
            pressure_mbar=pressure
        )

        # Langkah 4: Hitung sky brightness (Schaefer)
        sky_brightness_nl, k_v, extinction_mag_v, transmission_v = self.hitung_sky_brightness_schaefer(rh, temperature, posisi)

        # Langkah 5: Hitung luminansi hilal (Kastner)
        luminansi_hilal_nl = self.hitung_luminansi_hilal_kastner(posisi, transmission_v)

        # Langkah 6: Hitung visibilitas naked eye
        rasio_kontras_ne, delta_m_ne, crumey_ne = self.hitung_visibilitas_naked_eye(
            luminansi_hilal_nl, sky_brightness_nl, posisi, F_naked=F_naked
        )

        # Langkah 7: Hitung visibilitas teleskop (jika diminta)
        if use_telescope:
            (luminansi_hilal_tel_nl, sky_brightness_tel_nl,
             rasio_kontras_tel, c_th_tel, delta_m_tel) = self.hitung_visibilitas_teleskop(
                luminansi_hilal_nl, sky_brightness_nl, posisi,
                **telescope_config
            )
            # Threshold difference; includes any explicit residual-F difference.
            c_th_ne = crumey_ne['C_th']
            telescope_gain = _threshold_gain_mag(c_th_ne, c_th_tel)
        else:
            luminansi_hilal_tel_nl = sky_brightness_tel_nl = 0.0
            rasio_kontras_tel = c_th_tel = delta_m_tel = 0.0
            telescope_gain = 0.0

        # Simpan parameter teleskop yang digunakan
        self.hasil['tel_params'] = dict(telescope_config)
        self.hasil['F_naked'] = F_naked
        self.hasil['use_telescope'] = use_telescope
        self.hasil['scan_params'] = {
            'interval_menit': interval_menit, 'min_moon_alt': min_moon_alt,
            'start_delay_menit': start_delay_menit, 'refinement_seconds': 15,
        }

        # Simpan semua hasil termasuk data posisi lengkap
        self.hasil.update({
            # Data posisi matahari
            'sun_alt': posisi['sun_alt'],
            'sun_az': posisi['sun_az'],
            # Data posisi bulan
            'moon_alt': posisi['moon_alt'],
            'moon_az': posisi['moon_az'],
            'elongation': posisi['elongation'],
            'phase_angle': posisi['phase_angle'],
            'moon_semidiameter': posisi['moon_semidiameter'],
            'moon_distance_km': posisi['moon_distance_km'],
            'moon_width': posisi['moon_width'],
            # Data perhitungan (saat sunset)
            'luminansi_hilal_nl': luminansi_hilal_nl,
            'sky_brightness_nl': sky_brightness_nl,
            'luminansi_hilal_tel_nl': luminansi_hilal_tel_nl,
            'sky_brightness_tel_nl': sky_brightness_tel_nl,
            'k_v': k_v,
            'extinction_mag_v': extinction_mag_v,
            'transmission_v': transmission_v,
            'rasio_kontras_ne': rasio_kontras_ne,
            'delta_m_ne': delta_m_ne,
            'rasio_kontras_tel': rasio_kontras_tel,
            'c_th_tel': c_th_tel,
            'delta_m_tel': delta_m_tel,
            'telescope_gain': telescope_gain,
            'crumey_ne_C_th': crumey_ne['C_th'],
            'crumey_ne_A_arcmin2': crumey_ne['A_arcmin2'],
            **_visibility_diagnostics(
                crumey_ne, self._scene_telescope if use_telescope else None,
                F_naked, telescope_config['field_factor'], telescope_gain,
            ),
            'model_trace': {
                'photometry': getattr(self, '_scene_photometry', None),
                'atmosphere': getattr(self, '_scene_atmosphere', None),
                'naked_eye': crumey_ne,
                'naked_eye_coefficients': threshold_parameters(nL_to_cd_m2(sky_brightness_nl)),
                'telescope': self._scene_telescope if use_telescope else None,
            },
        })
        
        # Langkah 8: Cari visibilitas optimal (jika mode = "optimal")
        if mode.lower() == "optimal":
            observing_location = self.hasil.get('observing_location')
            
            hasil_optimal = self.cari_visibilitas_optimal(
                sunset_local=sunset_local,
                observing_location=observing_location,
                **telescope_config,
                F_naked=F_naked,
                interval_menit=interval_menit,
                min_moon_alt=min_moon_alt,
                start_delay_menit=start_delay_menit,
                use_telescope=use_telescope,
            )
            
            self.hasil.update({
                'mode': 'optimal',
                'optimal_time_ne': hasil_optimal['optimal_time_ne'],
                'optimal_delta_m_ne': hasil_optimal['optimal_delta_m_ne'],
                'optimal_moon_alt_ne': hasil_optimal['optimal_moon_alt_ne'],
                'optimal_time_tel': hasil_optimal['optimal_time_tel'],
                'optimal_delta_m_tel': hasil_optimal['optimal_delta_m_tel'],
                'optimal_moon_alt_tel': hasil_optimal['optimal_moon_alt_tel'],
                'optimal_sun_alt_tel': hasil_optimal['optimal_sun_alt_tel'],
                'optimal_telescope_gain': hasil_optimal['optimal_telescope_gain'],
                'optimal_threshold_difference_mag': hasil_optimal['optimal_threshold_difference_mag'],
                'optimal_result_ne': hasil_optimal['best_result_ne'],
                'optimal_result_tel': hasil_optimal['best_result_tel'],
                'visibility_duration_ne': hasil_optimal['visibility_duration_ne'],
                'visibility_duration_tel': hasil_optimal['visibility_duration_tel'],
                'visibility_start_ne': hasil_optimal['visibility_start_ne'],
                'visibility_start_tel': hasil_optimal['visibility_start_tel'],
                'visibility_end_ne': hasil_optimal['visibility_end_ne'],
                'visibility_end_tel': hasil_optimal['visibility_end_tel'],
                'best_window_start_ne': hasil_optimal['best_window_start_ne'],
                'best_window_end_ne': hasil_optimal['best_window_end_ne'],
                'best_window_start_tel': hasil_optimal['best_window_start_tel'],
                'best_window_end_tel': hasil_optimal['best_window_end_tel'],
                'total_timesteps': hasil_optimal['total_timesteps'],
                'all_timestep_results': hasil_optimal['all_results']
            })
        else:
            self.hasil['mode'] = 'sunset'
        
        # Tampilkan hasil akhir
        self.tampilkan_hasil_akhir()
        
        return self.hasil
    
    def tampilkan_hasil_akhir(self):
        """Menampilkan ringkasan hasil perhitungan akhir"""
        print("\n" + "=" * 70)
        print("HASIL PERHITUNGAN VISIBILITAS HILAL")
        print("=" * 70)
        
        # === INFORMASI LOKASI ===
        print(f"\n{'='*30} LOKASI {'='*31}")
        print(f"  Nama Tempat           : {self.nama_tempat}")
        print(f"  Lintang               : {self.lintang}°")
        print(f"  Bujur                 : {self.bujur}°")
        print(f"  Elevasi               : {self.elevasi} m")
        print(f"  Timezone              : {self.timezone_str}")
        print(f"  Bulan/Tahun Hijri     : {self.bulan_hijri}/{self.tahun_hijri}")
        
        # === WAKTU ===
        print(f"\n{'='*30} WAKTU {'='*32}")
        if 'ijtima_utc' in self.hasil:
            print(f"  Ijtima UTC            : {self.hasil['ijtima_utc'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Ijtima Lokal          : {self.hasil['ijtima_local'].strftime('%Y-%m-%d %H:%M:%S')}")
        if 'tanggal_pengamatan' in self.hasil:
            print(f"  Tanggal Pengamatan    : {self.hasil['tanggal_pengamatan'].strftime('%Y-%m-%d')}")
        if 'sunset_utc' in self.hasil:
            print(f"  Sunset UTC            : {self.hasil['sunset_utc'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  Sunset Lokal          : {self.hasil['sunset_local'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        # === DATA ATMOSFER ===
        print(f"\n{'='*28} DATA ATMOSFER {'='*28}")
        if 'rh' in self.hasil:
            # Tampilkan nilai raw dan corrected hanya jika ada bias
            bias_t = self.hasil.get('bias_t', 0.0)
            bias_rh = self.hasil.get('bias_rh', 0.0)
            src_label = self.SUMBER_ATMOSFER_LABEL.get(self.sumber_atmosfer, self.sumber_atmosfer.upper()).split(' ')[0]
            if bias_t != 0.0 or bias_rh != 0.0:
                print(f"  Suhu {src_label} (raw)           : {self.hasil.get('temperature_raw', 0):.2f}°C")
                print(f"  Suhu Terkoreksi (T)       : {self.hasil['temperature']:.2f}°C  (bias={bias_t:+.1f}°C)")
                print(f"  RH {src_label} (raw)             : {self.hasil.get('rh_raw', 0):.2f}%")
                print(f"  RH Terkoreksi             : {self.hasil['rh']:.2f}%  (bias={bias_rh:+.1f}%)")
            else:
                # Tanpa koreksi bias - tampilkan bias 0.0 untuk jelas
                print(f"  Kelembapan Relatif (RH)   : {self.hasil['rh']:.2f}%  (bias=0.0%)")
                print(f"  Suhu (T)                  : {self.hasil['temperature']:.2f}°C  (bias=0.0°C)")
        if 'pressure' in self.hasil:
            print(f"  Tekanan Udara (P)         : {self.hasil['pressure']:.2f} mbar")
        if 'k_v' in self.hasil:
            print(f"  Koefisien Ekstingsi (k_V) : {self.hasil['k_v']:.4f} mag/airmass")
        if 'extinction_mag_v' in self.hasil:
            print(f"  Ekstingsi LOS (A_V)       : {self.hasil['extinction_mag_v']:.4f} mag")
            print(f"  Transmisi Atmosfer (T_V)  : {self.hasil['transmission_v']:.6e}")
        
        # === POSISI MATAHARI ===
        print(f"\n{'='*27} POSISI MATAHARI {'='*27}")
        if 'sun_alt' in self.hasil:
            print(f"  Altitude Matahari     : {deg_to_dms(self.hasil['sun_alt'])}")
            print(f"  Azimuth Matahari      : {deg_to_dms(self.hasil['sun_az'])}")
        
        # === POSISI BULAN ===
        print(f"\n{'='*28} POSISI BULAN {'='*29}")
        if 'moon_alt' in self.hasil:
            print(f"  Altitude Bulan        : {deg_to_dms(self.hasil['moon_alt'])}")
            print(f"  Azimuth Bulan         : {deg_to_dms(self.hasil['moon_az'])}")
        if 'elongation' in self.hasil:
            print(f"  Elongasi Toposentrik  : {deg_to_dms(self.hasil['elongation'])}")
        if 'phase_angle' in self.hasil:
            print(f"  Phase Angle           : {deg_to_dms(self.hasil['phase_angle'])}")
        if 'moon_semidiameter' in self.hasil:
            print(f"  Semidiameter Bulan    : {deg_to_dms(float(self.hasil['moon_semidiameter']))}")
            print(f"  Jarak Bulan DE440s    : {self.hasil['moon_distance_km']:.3f} km (toposentrik)")
        if 'moon_width' in self.hasil:
            width_arcmin = self.hasil['moon_width'] * 60.0
            print(f"  Lebar Sabit Bulan     : {width_arcmin:.3f} arcmin")
        
        # === VISIBILITAS HILAL NAKED EYE (Crumey 2014) ===
        print(f"\n{'='*22} VISIBILITAS HILAL NAKED EYE {'='*21}")
        if 'luminansi_hilal_nl' in self.hasil:
            print(f"  Luminansi Hilal       : {self.hasil['luminansi_hilal_nl']:.4e} nL")
            print(f"  Sky Brightness        : {self.hasil['sky_brightness_nl']:.4e} nL")
        if 'rasio_kontras_ne' in self.hasil:
            print(f"  Weber Contrast (C_obj): {self.hasil['rasio_kontras_ne']:.4e}")
            if 'crumey_ne_C_th' in self.hasil:
                print(f"  Threshold (Crumey)    : {self.hasil['crumey_ne_C_th']:.4e}")
            if 'crumey_ne_regime' in self.hasil:
                print(f"  Regime                : {self.hasil['crumey_ne_regime']}")
            if self.hasil.get('crumey_ne_achromatic_extrapolation'):
                print("  Aproksimasi           : extrapolasi threshold luminansi achromatic")
            if 'crumey_ne_A_arcmin2' in self.hasil:
                print(f"  Luas Sabit            : {self.hasil['crumey_ne_A_arcmin2']:.4f} arcmin²")
            print(f"  Visib. Margin (D_m)   : {self.hasil['delta_m_ne']:.4f}")
            status_ne = "TERLIHAT" if self.hasil['delta_m_ne'] > 0 else "TIDAK TERLIHAT"
            print(f"  Status                : {status_ne}")
        
        # Tambahkan hasil optimal naked eye jika mode optimal
        if self.hasil.get('mode') == 'optimal' and self.hasil.get('optimal_time_ne'):
            print(f"\n  --- Optimal ---")
            print(f"  Waktu Optimal         : {self.hasil['optimal_time_ne'].strftime('%H:%M:%S')}")
            print(f"  Moon Alt. Optimal     : {self.hasil['optimal_moon_alt_ne']:.2f}°")
            print(f"  Delta m Optimal       : {self.hasil['optimal_delta_m_ne']:.4f}")
            if self.hasil['visibility_duration_ne'] > 0:
                print(f"  Durasi Visibilitas    : {self.hasil['visibility_duration_ne']} menit (window kontinu terpanjang)")
                ws_ne = self.hasil.get('best_window_start_ne')
                we_ne = self.hasil.get('best_window_end_ne')
                if ws_ne and we_ne:
                    print(f"  Window Visibilitas    : {ws_ne.strftime('%H:%M:%S')} - {we_ne.strftime('%H:%M:%S')}")
            else:
                print(f"  Durasi Visibilitas    : 0 menit (tidak pernah delta_m > 0)")
        
        if self.hasil.get('delta_m_ne', -1) > 0:
            print(f"\n  >> Hilal BERPOTENSI terlihat dengan mata telanjang")
        else:
            print(f"\n  >> Hilal SULIT terlihat dengan mata telanjang")
        
        # === VISIBILITAS HILAL TELESKOP ===
        print(f"\n{'='*24} VISIBILITAS HILAL TELESKOP {'='*22}")
        if 'rasio_kontras_tel' in self.hasil:
            print(f"  Luminansi (Teleskop)  : {self.hasil['luminansi_hilal_tel_nl']:.4e} nL")
            print(f"  Sky Bright. (Teleskop): {self.hasil['sky_brightness_tel_nl']:.4e} nL")
            if self.hasil.get('crumey_tel_regime'):
                print(f"  Regime (latar tampak) : {self.hasil['crumey_tel_regime']}")
            if self.hasil.get('crumey_tel_achromatic_extrapolation'):
                print("  Aproksimasi           : extrapolasi threshold luminansi achromatic")
            print(f"  Weber Contrast (C_obj): {self.hasil['rasio_kontras_tel']:.4e}")
            if 'c_th_tel' in self.hasil:
                print(f"  Threshold (Crumey)    : {self.hasil['c_th_tel']:.4e}")
            print(f"  Visib. Margin (D_m)   : {self.hasil['delta_m_tel']:.4f}")
            if 'telescope_gain' in self.hasil:
                print(f"  Selisih Threshold     : {self.hasil['telescope_gain']:+.4f} mag "
                      f"(= 2.5 log C_th_ne/C_th_tel)")
                if self.hasil.get('field_factor_comparison') == 'independent_residual_factors':
                    print("  Perbandingan F        : F berbeda; selisih mencakup perubahan residual F")
            status_tel = "TERLIHAT" if self.hasil['delta_m_tel'] > 0 else "TIDAK TERLIHAT"
            print(f"  Status                : {status_tel}")
        
        # Tambahkan hasil optimal teleskop jika mode optimal
        if self.hasil.get('mode') == 'optimal' and self.hasil.get('optimal_time_tel'):
            print(f"\n  --- Optimal ---")
            print(f"  Waktu Optimal         : {self.hasil['optimal_time_tel'].strftime('%H:%M:%S')}")
            print(f"  Moon Alt. Optimal     : {self.hasil['optimal_moon_alt_tel']:.2f}°")
            print(f"  Delta m Optimal       : {self.hasil['optimal_delta_m_tel']:.4f}")
            if 'optimal_telescope_gain' in self.hasil:
                print(f"  Selisih Threshold     : {self.hasil['optimal_telescope_gain']:+.4f} mag")
            if self.hasil['visibility_duration_tel'] > 0:
                print(f"  Durasi Visibilitas    : {self.hasil['visibility_duration_tel']} menit (window kontinu terpanjang)")
                ws_tel = self.hasil.get('best_window_start_tel')
                we_tel = self.hasil.get('best_window_end_tel')
                if ws_tel and we_tel:
                    print(f"  Window Visibilitas    : {ws_tel.strftime('%H:%M:%S')} - {we_tel.strftime('%H:%M:%S')}")
            else:
                print(f"  Durasi Visibilitas    : 0 menit (tidak pernah delta_m > 0)")
        
        if self.hasil.get('delta_m_tel', -1) > 0:
            print(f"\n  >> Hilal TERDETEKSI dengan teleskop")
        else:
            print(f"\n  >> Hilal SULIT terdeteksi dengan teleskop")
        
        # Total timesteps (jika mode optimal)
        if self.hasil.get('mode') == 'optimal':
            print(f"\n  Total timesteps       : {self.hasil.get('total_timesteps', 0)}")
        
        print("\n" + "=" * 70)

    def plot_visibility_margin(self, save_path: Optional[str] = None) -> bool:
        """
        Plot grafik visibilitas margin (naked eye & teleskop) vs timestep.

        Sumbu X: nomor timestep (jarak label menyesuaikan jumlah data)
        Sumbu Y: visibility margin / delta_m (interval label 5)

        Parameters
        ----------
        save_path : str or None
            Path file untuk menyimpan gambar. Jika None, hanya tampilkan.

        Returns
        -------
        bool
            True jika plot berhasil dibuat, False jika tidak ada data.
        """
        all_results = self.hasil.get('all_timestep_results', [])
        if not all_results:
            print("  [!] Tidak ada data timestep. Plot hanya tersedia pada mode optimal.")
            return False

        try:
            import matplotlib
            matplotlib.use('Agg')  # non-interactive backend
            import matplotlib.pyplot as plt
            import matplotlib.ticker as ticker
        except ImportError:
            print("  [!] matplotlib belum terinstall. Jalankan: pip install matplotlib")
            return False

        # Kumpulkan data valid
        timesteps = []
        dm_ne_list = []
        dm_tel_list = []
        waktu_labels = []
        idx = 0
        for r in all_results:
            if not r.get('valid'):
                continue
            timesteps.append(idx)
            dm_ne_list.append(r['delta_m_ne'])
            dm_tel_list.append(r['delta_m_tel'])
            waktu_labels.append(r['waktu_local'].strftime('%H:%M'))
            idx += 1

        if not timesteps:
            print("  [!] Tidak ada data valid untuk diplot.")
            return False

        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot kedua garis
        ax.plot(timesteps, dm_ne_list, color='#2196F3', linewidth=2,
                marker='o', markersize=4, label='Margin Naked Eye (Δm NE)')
        ax.plot(timesteps, dm_tel_list, color='#F44336', linewidth=2,
                marker='s', markersize=4, label='Margin Teleskop (Δm Tel)')

        # Garis threshold delta_m = 0
        ax.axhline(y=0, color='#4CAF50', linewidth=1.5, linestyle='--',
                   label='Threshold (Δm = 0)', alpha=0.8)

        # Fill area di atas threshold
        ax.fill_between(timesteps, dm_tel_list, 0,
                        where=[v > 0 for v in dm_tel_list],
                        alpha=0.10, color='#F44336')
        ax.fill_between(timesteps, dm_ne_list, 0,
                        where=[v > 0 for v in dm_ne_list],
                        alpha=0.10, color='#2196F3')

        # Batasi jumlah label agar grafik dengan banyak timestep tetap terbaca.
        ax.set_xlabel('Timestep (menit setelah sunset)', fontsize=12, fontweight='bold')
        ax.xaxis.set_major_locator(ticker.MaxNLocator(
            nbins=22, integer=True, steps=[1, 2, 5, 10],
        ))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(1))
        ax.set_xlim(0, max(timesteps))

        # Konfigurasi sumbu Y — interval label 5, simetris terhadap 0
        ax.set_ylabel('Visibility Margin (Δm) [mag]', fontsize=12, fontweight='bold')
        ax.yaxis.set_major_locator(ticker.MultipleLocator(5))
        ax.yaxis.set_minor_locator(ticker.MultipleLocator(1))

        # Paksa sumbu Y simetris agar Δm = 0 selalu di tengah
        # Default: -20 s/d +20. Jika data melebihi 20, perluas ke kelipatan 5.
        finite_dm = [v for v in dm_ne_list + dm_tel_list if math.isfinite(v)]
        y_abs_max = max((abs(v) for v in finite_dm), default=20)
        y_limit = max(20, math.ceil(y_abs_max / 5) * 5)
        ax.set_ylim(-y_limit, y_limit)

        # Format label sumbu Y: ...-10 -5 0 +5 +10...
        def y_formatter(val, pos):
            if val == 0:
                return '0'
            return f'{val:+.0f}'
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(y_formatter))

        # Judul dan informasi
        nama = self.nama_tempat
        bln = self.bulan_hijri
        thn = self.tahun_hijri
        sunset_str = self.hasil.get('sunset_local', '')
        if hasattr(sunset_str, 'strftime'):
            sunset_str = sunset_str.strftime('%Y-%m-%d %H:%M:%S')
        ax.set_title(
            f'Visibilitas Hilal — {nama}\n'
            f'Bulan {bln}/{thn} H | Sunset: {sunset_str}',
            fontsize=14, fontweight='bold', pad=15
        )

        ax.legend(loc='best', fontsize=10, framealpha=0.9)
        ax.grid(True, which='major', linestyle='-', alpha=0.3)
        ax.grid(True, which='minor', linestyle=':', alpha=0.15)

        plt.tight_layout()

        if save_path:
            os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
            fig.savefig(save_path, dpi=150, bbox_inches='tight')
            print(f"  [✓] Grafik disimpan: {save_path}")

        plt.close(fig)
        return True

    def simpan_ke_excel(self, filepath: str) -> str:
        """Export single-location results with separate NE/telescope columns.

        Ringkasan, Input & Konfigurasi, Rantai Model, Atmosfer, Timestep Data
        and Info Program expose recorded inputs, formulas, units and decisions.
        No weather or visibility calculation is repeated during export.
        """
        from hilal_visibility.reports.single_excel import write_single_workbook

        output = write_single_workbook(self, filepath)
        save_atmosphere_provenance(output, [atmosphere_audit_record(
            self.nama_tempat, self.sumber_atmosfer, True, self.hasil,
        )])
        print(f"\n  Hasil Excel disimpan ke: {output}")
        return output


def tentukan_timezone_indonesia(longitude: float) -> str:
    """
    Menentukan timezone Indonesia berdasarkan bujur (longitude).
    
    Pembagian zona waktu Indonesia:
    - WIB  (UTC+7): bujur < 115° (Sumatera, Jawa, Kalimantan Barat & Tengah)
    - WITA (UTC+8): 115° <= bujur < 135° (Kalimantan Timur & Selatan, Sulawesi, Bali, Nusa Tenggara)
    - WIT  (UTC+9): bujur >= 135° (Maluku, Papua)
    
    Parameters:
    -----------
    longitude : float
        Bujur lokasi dalam derajat
        
    Returns:
    --------
    str
        Timezone IANA string
    """
    if longitude < 115.0:
        return "Asia/Jakarta"    # WIB (UTC+7)
    elif longitude < 135.0:
        return "Asia/Makassar"   # WITA (UTC+8)
    else:
        return "Asia/Jayapura"   # WIT (UTC+9)
