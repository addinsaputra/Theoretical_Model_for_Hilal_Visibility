import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
import sys
import os
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# Import modul yang diperlukan
from visual_limit_schaefer import hitung_sky_brightness
from visual_limit_kastner import hitung_fotometri_intrinsik, terapkan_transmisi_atmosfer
# Import langsung dari modul Crumey (tanpa intermediary crumey_telescope_correction.py)
from full_rumus_crumey import (
    hilal_naked_eye_visibility,
    nL_to_cd_m2,
    arcmin2_to_sr,
    crescent_area_arcmin2,
    visibility_margin_mag,
    telescopic_extended_threshold,
    threshold_parameters,
)
from telescope_limit import TelescopeVisibilityModel

# Import modul cuaca ECMWF_IFS (Open-Meteo)
from atmosfer_ecmwf_ifs import (
    ObservingLocation, AtmosphericWindow, fetch_atmospheric_window,
    ECMWF_IFSAPIError, apply_bias_correction, validate_atmosphere,
    normalize_utc_datetime,
)
from atmosphere_provenance import atmosphere_audit_record, save_atmosphere_provenance

# Import modul cuaca MERRA-2 (NASA POWER)
from atmosfer_merra2 import (
    ObservingLocation as MERRA2Location,
    get_rh_t_at_time as merra2_get_rh_t,
    PowerAPIError
)

# Import modul data_hisab menggantikan sunmoon
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'data-hisab'))
from data_hisab import (
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



def _telescope_configuration(aperture: float, magnification: float, **kwargs) -> dict:
    """One validated configuration reused at sunset, scan and refinement.

    ``observer_age`` controls only the fallback pupil estimate. A measured or
    independently modelled twilight pupil can be supplied in millimetres.
    Field factor includes any independently calibrated observer sensitivity.
    """
    parameters = {
        'aperture': aperture, 'magnification': magnification,
        'transmission': 0.95, 'n_surfaces': 6, 'central_obstruction': 0.0,
        'observer_age': 22.0, 'field_factor': 2.4, 'pupil_diameter_mm': None,
    }
    unknown = set(kwargs) - set(parameters)
    if unknown:
        raise TypeError('Unknown telescope configuration: ' + ', '.join(sorted(unknown)))
    parameters.update(kwargs)
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
    """Gain is -inf for blocked optics; two absent targets have no gain."""
    if naked_threshold <= 0 or telescopic_threshold <= 0:
        return 0.0
    if math.isinf(naked_threshold) and math.isinf(telescopic_threshold):
        return 0.0
    return 2.5 * (math.log10(naked_threshold) - math.log10(telescopic_threshold))


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
        String dalam format "DDÂ° MM' SS.SS\""
    """
    sign = "-" if deg < 0 else ""
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = (deg - d - m / 60) * 3600
    return f"{sign}{d}Â° {m}' {s:.2f}\""


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
            Bias suhu reanalisis (Â°C), definisi: bias = Reanalisis - Obs (default: 0.0)
        bias_rh : float
            Bias RH reanalisis (%), definisi: bias = Reanalisis - Obs (default: 0.0)
        sumber_atmosfer : str
            Sumber data atmosfer: 'ecmwf_ifs', 'merra2', atau 'manual'
        manual_rh : float
            RH manual (%) jika sumber='manual'
        manual_t : float
            Suhu manual (Â°C) jika sumber='manual'
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
                print(f"{indent}[âœ“] Data atmosfer MANUAL:")
                print(f"{indent}     RH={rh_raw:.2f}%, T={temperature_raw:.2f}Â°C, P={pressure:.2f} mbar")
            # Manual: tidak ada koreksi bias
            return rh_raw, temperature_raw, rh_raw, temperature_raw, pressure

        if sumber == 'ecmwf_ifs':
            try:
                window = fetch_atmospheric_window(observing_location, waktu_utc, waktu_utc)
                rh_raw, temperature_raw, pressure = window.at_time(waktu_utc)
                if record_provenance:
                    self.hasil.setdefault('atmosphere_provenance', []).append(window.to_record())
                if verbose:
                    print(f"{indent}[âœ“] Data atmosfer ECMWF_IFS berhasil diambil:")
                    print(f"{indent}     RH={rh_raw:.2f}%, T={temperature_raw:.2f}Â°C, P={pressure:.2f} mbar")
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
                    print(f"{indent}[âœ“] Data atmosfer MERRA-2 berhasil diambil:")
                    print(f"{indent}     RH={rh_raw:.2f}%, T={temperature_raw:.2f}Â°C, P={pressure:.2f} kPa")
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
            print(f"{indent}[Bias Correction] T: {temperature_raw:.2f} â†’ {temperature:.2f}Â°C (bias={self.bias_t:+.1f})")
            print(f"{indent}[Bias Correction] RH: {rh_raw:.2f} â†’ {rh:.2f}% (bias={self.bias_rh:+.1f})")

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
                                      F_naked: float = 2.5) -> tuple:
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
            Field factor untuk naked eye (default 2.5)

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
                                     field_factor: float = 2.4,
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
                                       F_naked: float = 2.5,
                                       field_factor: float = 2.4,
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
        """
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

        # Telescope gain: keuntungan threshold teleskop vs naked eye [mag]
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
                                  F_naked: float = 2.5,
                                  field_factor: float = 2.4,
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
        - Refinement Â±2 menit di sekitar puncak dengan step 15 detik
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
        telescope_config = _telescope_configuration(
            aperture, magnification, transmission=transmission, n_surfaces=n_surfaces,
            central_obstruction=central_obstruction, observer_age=observer_age,
            field_factor=field_factor, pupil_diameter_mm=pupil_diameter_mm,
        )
        print(f"\n  Mencari visibilitas optimal (interval: {interval_menit} menit, "
              f"start delay: {start_delay_menit} menit)...")

        # â”€â”€ Fetch atmosfer hourly untuk scan dan refinement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Inisialisasi tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Loop utama (kasar) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                print(f"    Berhenti: moon_alt = {result['moon_alt']:.2f}Â° (< {min_moon_alt}Â°)")
                break

            # Track best NE
            if best_result_ne is None or result['delta_m_ne'] > best_delta_m_ne:
                best_delta_m_ne = result['delta_m_ne']
                best_result_ne = result

            # Track best telescope
            if use_telescope and (best_result_tel is None or result['delta_m_tel'] > best_delta_m_tel):
                best_delta_m_tel = result['delta_m_tel']
                best_result_tel = result

            # â”€â”€ Track NE visibility window â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

            # â”€â”€ Track telescope visibility window â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                  f"gain={result['telescope_gain']:+.2f}")

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

        # â”€â”€ Refinement: presisi tinggi di sekitar puncak â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

        # â”€â”€ Durasi window kontinu terpanjang â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                                      F_naked: float = 2.5,
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
        telescope_config = _telescope_configuration(aperture, magnification, **telescope_kwargs)
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
            # Telescope gain: keuntungan threshold teleskop vs naked eye [mag]
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
            'crumey_ne_regime': crumey_ne['regime'],
            'crumey_ne_A_arcmin2': crumey_ne['A_arcmin2'],
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
        print(f"  Lintang               : {self.lintang}Â°")
        print(f"  Bujur                 : {self.bujur}Â°")
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
                print(f"  Suhu {src_label} (raw)           : {self.hasil.get('temperature_raw', 0):.2f}Â°C")
                print(f"  Suhu Terkoreksi (T)       : {self.hasil['temperature']:.2f}Â°C  (bias={bias_t:+.1f}Â°C)")
                print(f"  RH {src_label} (raw)             : {self.hasil.get('rh_raw', 0):.2f}%")
                print(f"  RH Terkoreksi             : {self.hasil['rh']:.2f}%  (bias={bias_rh:+.1f}%)")
            else:
                # Tanpa koreksi bias - tampilkan bias 0.0 untuk jelas
                print(f"  Kelembapan Relatif (RH)   : {self.hasil['rh']:.2f}%  (bias=0.0%)")
                print(f"  Suhu (T)                  : {self.hasil['temperature']:.2f}Â°C  (bias=0.0Â°C)")
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
            if 'crumey_ne_A_arcmin2' in self.hasil:
                print(f"  Luas Sabit            : {self.hasil['crumey_ne_A_arcmin2']:.4f} arcminÂ²")
            print(f"  Visib. Margin (D_m)   : {self.hasil['delta_m_ne']:.4f}")
            status_ne = "TERLIHAT" if self.hasil['delta_m_ne'] > 0 else "TIDAK TERLIHAT"
            print(f"  Status                : {status_ne}")
        
        # Tambahkan hasil optimal naked eye jika mode optimal
        if self.hasil.get('mode') == 'optimal' and self.hasil.get('optimal_time_ne'):
            print(f"\n  --- Optimal ---")
            print(f"  Waktu Optimal         : {self.hasil['optimal_time_ne'].strftime('%H:%M:%S')}")
            print(f"  Moon Alt. Optimal     : {self.hasil['optimal_moon_alt_ne']:.2f}Â°")
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
            print(f"  Weber Contrast (C_obj): {self.hasil['rasio_kontras_tel']:.4e}")
            if 'c_th_tel' in self.hasil:
                print(f"  Threshold (Crumey)    : {self.hasil['c_th_tel']:.4e}")
            print(f"  Visib. Margin (D_m)   : {self.hasil['delta_m_tel']:.4f}")
            if 'telescope_gain' in self.hasil:
                print(f"  Telescope Gain        : {self.hasil['telescope_gain']:+.4f} mag "
                      f"(= 2.5 log C_th_ne/C_th_tel)")
            status_tel = "TERLIHAT" if self.hasil['delta_m_tel'] > 0 else "TIDAK TERLIHAT"
            print(f"  Status                : {status_tel}")
        
        # Tambahkan hasil optimal teleskop jika mode optimal
        if self.hasil.get('mode') == 'optimal' and self.hasil.get('optimal_time_tel'):
            print(f"\n  --- Optimal ---")
            print(f"  Waktu Optimal         : {self.hasil['optimal_time_tel'].strftime('%H:%M:%S')}")
            print(f"  Moon Alt. Optimal     : {self.hasil['optimal_moon_alt_tel']:.2f}Â°")
            print(f"  Delta m Optimal       : {self.hasil['optimal_delta_m_tel']:.4f}")
            if 'optimal_telescope_gain' in self.hasil:
                print(f"  Telescope Gain        : {self.hasil['optimal_telescope_gain']:+.4f} mag")
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

        Sumbu X: nomor timestep (interval label 1)
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
                marker='o', markersize=4, label='Margin Naked Eye (Î”m NE)')
        ax.plot(timesteps, dm_tel_list, color='#F44336', linewidth=2,
                marker='s', markersize=4, label='Margin Teleskop (Î”m Tel)')

        # Garis threshold delta_m = 0
        ax.axhline(y=0, color='#4CAF50', linewidth=1.5, linestyle='--',
                   label='Threshold (Î”m = 0)', alpha=0.8)

        # Fill area di atas threshold
        ax.fill_between(timesteps, dm_tel_list, 0,
                        where=[v > 0 for v in dm_tel_list],
                        alpha=0.10, color='#F44336')
        ax.fill_between(timesteps, dm_ne_list, 0,
                        where=[v > 0 for v in dm_ne_list],
                        alpha=0.10, color='#2196F3')

        # Konfigurasi sumbu X â€” interval label 1, mulai tepat dari 0
        ax.set_xlabel('Timestep (menit setelah sunset)', fontsize=12, fontweight='bold')
        ax.xaxis.set_major_locator(ticker.MultipleLocator(1))
        ax.set_xlim(0, max(timesteps))

        # Konfigurasi sumbu Y â€” interval label 5, simetris terhadap 0
        ax.set_ylabel('Visibility Margin (Î”m) [mag]', fontsize=12, fontweight='bold')
        ax.yaxis.set_major_locator(ticker.MultipleLocator(5))
        ax.yaxis.set_minor_locator(ticker.MultipleLocator(1))

        # Paksa sumbu Y simetris agar Î”m = 0 selalu di tengah
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
            f'Visibilitas Hilal â€” {nama}\n'
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
            print(f"  [âœ“] Grafik disimpan: {save_path}")

        plt.close(fig)
        return True

    def simpan_ke_excel(self, filepath: str) -> str:
        """Export single-location results with separate NE/telescope columns.

        Ringkasan, Input & Konfigurasi, Rantai Model, Atmosfer, Timestep Data
        and Info Program expose recorded inputs, formulas, units and decisions.
        No weather or visibility calculation is repeated during export.
        """
        from single_excel_report import write_single_workbook

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
    - WIB  (UTC+7): bujur < 115Â° (Sumatera, Jawa, Kalimantan Barat & Tengah)
    - WITA (UTC+8): 115Â° <= bujur < 135Â° (Kalimantan Timur & Selatan, Sulawesi, Bali, Nusa Tenggara)
    - WIT  (UTC+9): bujur >= 135Â° (Maluku, Papua)
    
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


def _get_input(prompt_text, default_val, type_func=float):
    """Helper untuk input dengan default value."""
    val = input(prompt_text).strip()
    if not val:
        return default_val
    try:
        return type_func(val)
    except ValueError:
        print(f"    [!] Input '{val}' tidak valid. Menggunakan default {default_val}.")
        return default_val


def _input_bulan_tahun_hijri():
    """Input bulan dan tahun Hijriah dari user. Return (bulan, tahun) atau None."""
    nama_bulan = {
        1: "Muharram", 2: "Shafar", 3: "Rabiul Awal", 4: "Rabiul Akhir",
        5: "Jumadil Awal", 6: "Jumadil Akhir", 7: "Rajab", 8: "Sya'ban",
        9: "Ramadhan", 10: "Syawwal", 11: "Dzulqa'dah", 12: "Dzulhijjah"
    }

    print("\n--- LANGKAH 2: INPUT BULAN DAN TAHUN HIJRIAH ---")
    print("  Daftar bulan Hijriah:")
    for num, nama in nama_bulan.items():
        print(f"    {num:2d}. {nama}")

    try:
        bulan_hijri = int(input("\n  Masukkan nomor bulan Hijriah (1-12): "))
        if bulan_hijri < 1 or bulan_hijri > 12:
            print("[!] Bulan tidak valid. Program dihentikan.")
            return None

        tahun_hijri = int(input("  Masukkan tahun Hijriah (contoh: 1446): "))
        if tahun_hijri < 1:
            print("[!] Tahun tidak valid. Program dihentikan.")
            return None

        print(f"\n  âœ“ Bulan Hijriah: {nama_bulan[bulan_hijri]} {tahun_hijri} H")
        return bulan_hijri, tahun_hijri

    except ValueError:
        print("[!] Input harus berupa angka. Program dihentikan.")
        return None


def _input_mode_dan_offset():
    """Input mode perhitungan dan offset hari. Return (mode, delta_day)."""
    print("\n--- LANGKAH 3: PILIH MODE PERHITUNGAN ---")
    print("  1. Sunset  - Hitung visibilitas pada saat sunset saja")
    print("  2. Optimal - Loop dari sunset untuk mencari delta_m maksimum")

    try:
        mode_pilihan = int(input("\n  Pilih mode (1/2): "))
        mode = "sunset" if mode_pilihan == 1 else "optimal"
        print(f"  âœ“ Mode: {mode}")
    except ValueError:
        mode = "optimal"
        print(f"  âœ“ Mode default: {mode}")

    print("\n--- LANGKAH 3.5: PILIH WAKTU PENGAMATAN ---")
    print("  0. Sesuai Hisab (H)       - Default")
    print("  1. H + 1 Hari             - Besoknya")
    print("  2. H + 2 Hari             - Lusanya")
    print(" -1. H - 1 Hari             - Kemarin")
    print("  Catatan: ECMWF IFS (arsip historis ~2017-sekarang), MERRA-2 (1981-sekarang)")

    try:
        offset_pilihan = input("\n  Pilih waktu (-2/-1/0/1/2) [enter=0]: ").strip()
        delta_day = int(offset_pilihan) if offset_pilihan else 0
        print(f"  âœ“ Offset waktu: H + {delta_day} hari")
    except ValueError:
        delta_day = 0
        print(f"  âœ“ Offset default: H + 0 hari")

    return mode, delta_day


def _input_sumber_atmosfer():
    """Input sumber data atmosfer. Return (sumber, manual_rh, manual_t, manual_p)."""
    print("\n--- LANGKAH 3.6: SUMBER DATA ATMOSFER ---")
    print("  Pilih sumber data atmosfer (RH, T, P):")
    print("  1. ECMWF IFS Historical (Open-Meteo API)  - data arsip historis ~2017-sekarang")
    print("  2. MERRA-2          (NASA POWER API)   â€” data historis 1981-sekarang")
    print("  3. Input Manual     (tanpa API)        â€” masukkan RH, T, P secara manual")

    manual_rh, manual_t, manual_p = 80.0, 25.0, 1013.25

    try:
        pilihan = input("\n  Pilih sumber (1/2/3) [enter=1]: ").strip() or "1"

        if pilihan == "2":
            sumber = 'merra2'
            print(f"  âœ“ Sumber atmosfer: MERRA-2 (NASA POWER API)")
        elif pilihan == "3":
            sumber = 'manual'
            print("  Masukkan data atmosfer secara manual:")
            try:
                rh_input = input("    RH (%) [default=80.0]: ").strip()
                manual_rh = float(rh_input) if rh_input else 80.0
                t_input = input("    Suhu (Â°C) [default=25.0]: ").strip()
                manual_t = float(t_input) if t_input else 25.0
                p_input = input("    Tekanan (mbar) [default=1013.25]: ").strip()
                manual_p = float(p_input) if p_input else 1013.25
            except ValueError:
                print("  [!] Input tidak valid. Menggunakan nilai default.")
                manual_rh, manual_t, manual_p = 80.0, 25.0, 1013.25
            print(f"  âœ“ Sumber atmosfer: Input Manual")
            print(f"    RH={manual_rh:.2f}%, T={manual_t:.2f}Â°C, P={manual_p:.2f} mbar")
        else:
            sumber = 'ecmwf_ifs'
            print(f"  âœ“ Sumber atmosfer: ECMWF IFS Historical (Open-Meteo API)")
    except EOFError:
        sumber = 'ecmwf_ifs'
        print(f"  âœ“ Sumber default: ECMWF IFS Historical")

    return sumber, manual_rh, manual_t, manual_p


def _input_koreksi_bias(bias_t: float, bias_rh: float, sumber_atmosfer: str = 'ecmwf_ifs'):
    """Input koreksi bias reanalisis. Return (bias_t, bias_rh)."""
    # Koreksi bias hanya relevan untuk sumber API (bukan manual)
    if sumber_atmosfer == 'manual':
        print("\n--- LANGKAH 3.7: KOREKSI BIAS ---")
        print("  âœ“ Koreksi bias dilewati (sumber: Input Manual)")
        return 0.0, 0.0

    label = sumber_atmosfer.upper().replace('MERRA2', 'MERRA-2')
    print(f"\n--- LANGKAH 3.7: KOREKSI BIAS {label} ---")
    print(f"  Koreksi bias digunakan untuk menyesuaikan data {label} dengan data observasi.")
    print(f"  Definisi: bias = {label} - Observasi")
    print(f"  Contoh: Jika {label} 30Â°C dan Observasi 28Â°C, maka bias_t = +2.0")
    print()

    has_bias = (bias_t != 0.0 or bias_rh != 0.0)
    if has_bias:
        print(f"  [INFO] Lokasi ini memiliki data bias bawaan:")
        print(f"           bias_t = {bias_t:+.1f}Â°C")
        print(f"           bias_rh = {bias_rh:+.1f}%")
        print()

    print("  Pilih opsi koreksi bias:")
    if has_bias:
        print(f"  1. Gunakan data bawaan lokasi: T={bias_t:+.1f}Â°C, RH={bias_rh:+.1f}% [default]")
        print("  2. Tanpa koreksi (bias_t = 0, bias_rh = 0)")
        print("  3. Input manual nilai bias")
    else:
        print("  1. Tanpa koreksi (bias_t = 0, bias_rh = 0) [default]")
        print("  2. Input manual nilai bias")

    try:
        if has_bias:
            bias_pilihan = input("\n  Pilih opsi (1/2/3) [enter=1]: ").strip() or "1"
            if bias_pilihan == "2":
                bias_t, bias_rh = 0.0, 0.0
                print(f"  âœ“ Menggunakan data {label} tanpa koreksi")
            elif bias_pilihan == "3":
                bias_t_input = input("  Masukkan bias suhu (Â°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                bias_t = float(bias_t_input) if bias_t_input else 0.0
                bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                print(f"  âœ“ Koreksi bias: T={bias_t:+.1f}Â°C, RH={bias_rh:+.1f}%")
            else:
                print(f"  âœ“ Menggunakan data bawaan: T={bias_t:+.1f}Â°C, RH={bias_rh:+.1f}%")
        else:
            bias_pilihan = input("\n  Pilih opsi (1/2) [enter=1]: ").strip() or "1"
            if bias_pilihan == "2":
                bias_t_input = input("  Masukkan bias suhu (Â°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                bias_t = float(bias_t_input) if bias_t_input else 0.0
                bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                print(f"  âœ“ Koreksi bias: T={bias_t:+.1f}Â°C, RH={bias_rh:+.1f}%")
            else:
                bias_t, bias_rh = 0.0, 0.0
                print(f"  âœ“ Menggunakan data {label} tanpa koreksi")
    except ValueError:
        print("  [!] Input tidak valid. Menggunakan default tanpa koreksi.")
        bias_t, bias_rh = 0.0, 0.0

    return bias_t, bias_rh


def _input_koreksi_bias_multi(lokasi_list: list, sumber_atmosfer: str = 'ecmwf_ifs') -> dict:
    """
    Input opsi koreksi bias untuk mode multi-lokasi.

    Parameters:
    -----------
    lokasi_list : list[dict]
        Daftar lokasi yang dipilih
    sumber_atmosfer : str
        Sumber data atmosfer ('ecmwf_ifs', 'merra2', 'manual')

    Returns:
    --------
    dict
        Dictionary dengan key:
        - 'opsi': 'bawaan' | 'tanpa' | 'manual'
        - 'manual_bias_t': float (hanya jika opsi='manual')
        - 'manual_bias_rh': float (hanya jika opsi='manual')
    """
    if sumber_atmosfer == 'manual':
        print("\n--- LANGKAH 3.7: KOREKSI BIAS ---")
        print("  âœ“ Koreksi bias dilewati (sumber: Input Manual)")
        return {'opsi': 'tanpa'}

    label = sumber_atmosfer.upper().replace('MERRA2', 'MERRA-2')
    print(f"\n--- LANGKAH 3.7: KOREKSI BIAS {label} ---")
    print(f"  Koreksi bias digunakan untuk menyesuaikan data {label} dengan data observasi.")
    print(f"  Definisi: bias = {label} - Observasi")
    print()

    # Tampilkan ringkasan bias bawaan lokasi jika ada
    n_has_bias = sum(1 for lok in lokasi_list
                     if lok.get('bias_t', 0.0) != 0.0 or lok.get('bias_rh', 0.0) != 0.0)

    print("  Pilih opsi koreksi bias:")
    if n_has_bias > 0:
        print(f"  [INFO] {n_has_bias}/{len(lokasi_list)} lokasi memiliki data bias bawaan")
        for lok in lokasi_list:
            bt = lok.get('bias_t', 0.0)
            br = lok.get('bias_rh', 0.0)
            if bt != 0.0 or br != 0.0:
                nama = lok.get('nama', '')
                if len(nama) > 30:
                    nama = nama[:28] + 'â€¦'
                print(f"         {nama:<30s}  bias_t={bt:+.1f}Â°C  bias_rh={br:+.1f}%")
        print()
        print("  1. Gunakan data bawaan per lokasi [default]")
        print("  2. Tanpa koreksi (bias_t = 0, bias_rh = 0 untuk semua lokasi)")
        print("  3. Input manual (nilai seragam untuk semua lokasi)")

        try:
            pilihan = input("\n  Pilih opsi (1/2/3) [enter=1]: ").strip() or "1"
            if pilihan == "2":
                print(f"  âœ“ Menggunakan data {label} tanpa koreksi untuk semua lokasi")
                return {'opsi': 'tanpa'}
            elif pilihan == "3":
                try:
                    bias_t_input = input("  Masukkan bias suhu (Â°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                    manual_bias_t = float(bias_t_input) if bias_t_input else 0.0
                    bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                    manual_bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                    print(f"  âœ“ Koreksi bias seragam: T={manual_bias_t:+.1f}Â°C, RH={manual_bias_rh:+.1f}%")
                    print(f"    (diterapkan ke semua {len(lokasi_list)} lokasi)")
                    return {'opsi': 'manual', 'manual_bias_t': manual_bias_t, 'manual_bias_rh': manual_bias_rh}
                except ValueError:
                    print("  [!] Input tidak valid. Menggunakan data bawaan per lokasi.")
                    return {'opsi': 'bawaan'}
            else:
                print(f"  âœ“ Menggunakan data bias bawaan per lokasi ({n_has_bias} lokasi memiliki bias)")
                return {'opsi': 'bawaan'}
        except (ValueError, EOFError):
            return {'opsi': 'bawaan'}
    else:
        print("  1. Tanpa koreksi (bias_t = 0, bias_rh = 0 untuk semua lokasi) [default]")
        print("  2. Input manual (nilai bias seragam untuk semua lokasi)")

        try:
            pilihan = input("\n  Pilih opsi (1/2) [enter=1]: ").strip() or "1"
            if pilihan == "2":
                try:
                    bias_t_input = input("  Masukkan bias suhu (Â°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                    manual_bias_t = float(bias_t_input) if bias_t_input else 0.0
                    bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                    manual_bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                    print(f"  âœ“ Koreksi bias seragam: T={manual_bias_t:+.1f}Â°C, RH={manual_bias_rh:+.1f}%")
                    print(f"    (diterapkan ke semua {len(lokasi_list)} lokasi)")
                    return {'opsi': 'manual', 'manual_bias_t': manual_bias_t, 'manual_bias_rh': manual_bias_rh}
                except ValueError:
                    print("  [!] Input tidak valid. Menggunakan tanpa koreksi.")
                    return {'opsi': 'tanpa'}
            else:
                print(f"  âœ“ Menggunakan data {label} tanpa koreksi untuk semua lokasi")
                return {'opsi': 'tanpa'}
        except (ValueError, EOFError):
            print(f"  âœ“ Menggunakan data {label} tanpa koreksi untuk semua lokasi")
            return {'opsi': 'tanpa'}


def _resolve_bias_t(lokasi: dict, shared_params: dict) -> float:
    """Resolve nilai bias_t berdasarkan opsi bias yang dipilih user."""
    bias_mode = shared_params.get('bias_mode', {})
    opsi = bias_mode.get('opsi', 'tanpa')
    if opsi == 'tanpa':
        return 0.0
    elif opsi == 'manual':
        return bias_mode.get('manual_bias_t', 0.0)
    else:  # 'bawaan'
        return lokasi.get('bias_t', 0.0)


def _resolve_bias_rh(lokasi: dict, shared_params: dict) -> float:
    """Resolve nilai bias_rh berdasarkan opsi bias yang dipilih user."""
    bias_mode = shared_params.get('bias_mode', {})
    opsi = bias_mode.get('opsi', 'tanpa')
    if opsi == 'tanpa':
        return 0.0
    elif opsi == 'manual':
        return bias_mode.get('manual_bias_rh', 0.0)
    else:  # 'bawaan'
        return lokasi.get('bias_rh', 0.0)


def _input_parameter_teleskop():
    """Input parameter teleskop dan field factor. Return dict parameter."""
    defaults = {
        'aperture': 100.0, 'magnification': 50.0, 'central_obstruction': 0.0,
        'transmission': 0.95, 'n_surfaces': 6, 'observer_age': 22.0,
        'field_factor': 2.4, 'F_naked': 2.5
    }

    print("\n--- LANGKAH 4: PARAMETER TELESKOP & FIELD FACTOR ---")
    print("  Gunakan parameter default?")
    print("  (aperture=100mm, magnification=50x, obstruction=0mm,")
    print("   transmission=0.95, n_surfaces=6, age=22.0,")
    print("   field_factor_teleskop=2.4, field_factor_naked_eye=2.5)")

    try:
        default_tel = input("  Gunakan default? (Y/n): ").strip().lower()
        if default_tel == 'n':
            print("\n  Masukkan parameter (kosongkan untuk default):")
            defaults['aperture'] = _get_input("  Aperture (mm) [default: 100.0]: ", 100.0)
            defaults['magnification'] = _get_input("  Magnifikasi (x) [default: 50.0]: ", 50.0)
            defaults['central_obstruction'] = _get_input("  Obstruksi sentral (mm) [default: 0.0]: ", 0.0)
            defaults['transmission'] = _get_input("  Transmisi per permukaan/lensa (0-1) [default: 0.95]: ", 0.95)
            defaults['n_surfaces'] = _get_input("  Jumlah permukaan optik [default: 6]: ", 6, int)
            defaults['observer_age'] = _get_input("  Usia pengamat (tahun) [default: 22.0]: ", 22.0)
            defaults['field_factor'] = _get_input("  Field factor teleskop (Crumey F) [default: 2.4]: ", 2.4)
            defaults['F_naked'] = _get_input("  Field factor naked eye (Crumey F) [default: 2.5]: ", 2.5)
            print(f"  âœ“ Parameter kustom digunakan.")
        else:
            print(f"  âœ“ Parameter default digunakan.")
    except Exception as e:
        print(f"  [!] Terjadi kesalahan: {e}")
        print(f"  âœ“ Parameter default digunakan.")

    return defaults


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MULTI-LOKASI: Fungsi pendukung untuk batch processing di mode interaktif
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def _parse_range_input(input_str: str, max_val: int) -> list:
    """
    Parse input range string menjadi list of integers.
    Contoh: "1,3,5-10,15" â†’ [1, 3, 5, 6, 7, 8, 9, 10, 15]

    Parameters:
    -----------
    input_str : str
        String input dari user (contoh: "1,3,5-10,15")
    max_val : int
        Nilai maksimum yang valid (jumlah lokasi)

    Returns:
    --------
    list[int]
        List nomor lokasi (1-indexed) yang valid dan unik, terurut
    """
    result = set()
    parts = input_str.replace(' ', '').split(',')
    for part in parts:
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                start, end = int(start), int(end)
                for i in range(start, end + 1):
                    if 1 <= i <= max_val:
                        result.add(i)
            except ValueError:
                continue
        else:
            try:
                val = int(part)
                if 1 <= val <= max_val:
                    result.add(val)
            except ValueError:
                continue
    return sorted(result)


def _input_mode_lokasi() -> str:
    """
    Input mode lokasi: tunggal atau multi.

    Returns:
    --------
    str
        'single' atau 'multi'
    """
    print("\n--- LANGKAH 0: MODE LOKASI ---")
    print("  1. Lokasi Tunggal   â€” hitung visibilitas untuk satu lokasi")
    print("  2. Multi-Lokasi     â€” hitung visibilitas untuk banyak lokasi sekaligus")

    try:
        pilihan = input("\n  Pilih mode (1/2) [enter=1]: ").strip() or "1"
        if pilihan == "2":
            print("  âœ“ Mode: Multi-Lokasi")
            return 'multi'
        else:
            print("  âœ“ Mode: Lokasi Tunggal")
            return 'single'
    except (ValueError, EOFError):
        print("  âœ“ Mode default: Lokasi Tunggal")
        return 'single'


def _input_multi_lokasi() -> list:
    """
    Pilih beberapa lokasi dari daftar_lokasi untuk batch processing.

    Returns:
    --------
    list[dict] or None
        List dictionary lokasi yang dipilih, atau None jika dibatalkan
    """
    from daftar_lokasi import print_daftar_lokasi, get_list_lokasi

    print("\n--- LANGKAH 1: PILIH LOKASI PENGAMATAN (MULTI) ---")
    list_lokasi = print_daftar_lokasi()
    n = len(list_lokasi)

    print(f"\n  Pilih lokasi yang akan dihitung:")
    print(f"  1. Semua lokasi ({n} lokasi)")
    print(f"  2. Pilih beberapa (contoh: 1,3,5-10,15)")

    try:
        pilihan = input("\n  Pilih opsi (1/2) [enter=1]: ").strip() or "1"

        if pilihan == "2":
            range_str = input(f"  Masukkan nomor lokasi (1-{n}): ").strip()
            if not range_str:
                print("  [!] Input kosong. Menggunakan semua lokasi.")
                indices = list(range(1, n + 1))
            else:
                indices = _parse_range_input(range_str, n)
                if not indices:
                    print("  [!] Tidak ada nomor valid. Menggunakan semua lokasi.")
                    indices = list(range(1, n + 1))
        else:
            indices = list(range(1, n + 1))

        selected = [list_lokasi[i - 1] for i in indices]

        print(f"\n  âœ“ {len(selected)} lokasi dipilih:")
        for i, lok in enumerate(selected, 1):
            nama = lok.get('nama', '')
            lat = lok.get('lat', lok.get('lintang', 0.0))
            lon = lok.get('lon', lok.get('bujur', 0.0))
            elv = lok.get('elevasi', lok.get('elv', 0.0))
            print(f"    {i:2d}. {nama}  (Lat: {lat:.4f}Â°, Lon: {lon:.4f}Â°, Elv: {elv:.0f} m)")

        return selected

    except (ValueError, EOFError):
        print("  [!] Input error. Menggunakan semua lokasi.")
        return list_lokasi


def _run_multi_lokasi(lokasi_list: list, shared_params: dict) -> list:
    """
    Jalankan perhitungan visibilitas hilal untuk banyak lokasi.

    Parameters:
    -----------
    lokasi_list : list[dict]
        Daftar lokasi (dari daftar_lokasi)
    shared_params : dict
        Parameter bersama: bulan_hijri, tahun_hijri, mode, delta_day,
        sumber_atmosfer, tel_params, F_naked, dll.

    Returns:
    --------
    list[dict]
        List hasil per lokasi, masing-masing berisi 'lokasi', 'hasil', 'calculator', 'success'
    """
    import time

    results = []
    total = len(lokasi_list)

    print("\n" + "â–ˆ" * 70)
    print("  BATCH PROCESSING: Visibilitas Hilal Multi-Lokasi")
    print(f"  {total} lokasi Ã— Bulan {shared_params['bulan_hijri']}/{shared_params['tahun_hijri']} H")
    print(f"  Mode: {shared_params['mode']}  |  Atmosfer: {shared_params['sumber_atmosfer']}")
    print("â–ˆ" * 70)

    t_batch_start = time.time()

    for i, lokasi in enumerate(lokasi_list, 1):
        nama = lokasi.get('nama', '')
        lat = lokasi.get('lat', lokasi.get('lintang', 0.0))
        lon = lokasi.get('lon', lokasi.get('bujur', 0.0))
        elv = lokasi.get('elevasi', lokasi.get('elv', 0.0))
        tz = tentukan_timezone_indonesia(lon)

        print(f"\n{'â•' * 70}")
        print(f"  [{i:2d}/{total}] {nama}")
        print(f"         Lat={lat:.4f}Â°  Lon={lon:.4f}Â°  Elv={elv:.0f}m  TZ={tz}")
        print(f"{'â•' * 70}")

        t_start = time.time()

        try:
            calculator = HilalVisibilityCalculator(
                nama_tempat=nama,
                lintang=lat,
                bujur=lon,
                elevasi=elv,
                timezone_str=tz,
                bulan_hijri=shared_params['bulan_hijri'],
                tahun_hijri=shared_params['tahun_hijri'],
                delta_day_offset=shared_params['delta_day'],
                bias_t=_resolve_bias_t(lokasi, shared_params),
                bias_rh=_resolve_bias_rh(lokasi, shared_params),
                sumber_atmosfer=shared_params['sumber_atmosfer'],
                manual_rh=shared_params.get('manual_rh', 80.0),
                manual_t=shared_params.get('manual_t', 25.0),
                manual_p=shared_params.get('manual_p', 1013.25),
            )

            hasil = calculator.jalankan_perhitungan_lengkap(
                use_telescope=True,
                mode=shared_params['mode'],
                min_moon_alt=2.0,
                F_naked=shared_params['F_naked'],
                **shared_params['tel_params'],
            )

            elapsed = time.time() - t_start

            # Ringkasan singkat
            dm_ne = hasil.get('delta_m_ne', -99)
            dm_tel = hasil.get('delta_m_tel', -99)
            if shared_params['mode'] == 'optimal':
                dm_ne = hasil.get('optimal_delta_m_ne', dm_ne)
                dm_tel = hasil.get('optimal_delta_m_tel', dm_tel)

            status_ne = "TERLIHAT" if dm_ne > 0 else "TIDAK"
            status_tel = "TERDETEKSI" if dm_tel > 0 else "TIDAK"

            print(f"\n  RINGKASAN: Î”m_NE={dm_ne:+.3f} ({status_ne})  "
                  f"Î”m_Tel={dm_tel:+.3f} ({status_tel})  "
                  f"â± {elapsed:.1f}s")

            results.append({
                'lokasi': lokasi,
                'hasil': hasil,
                'calculator': calculator,
                'success': True,
                'elapsed': elapsed,
            })

        except Exception as e:
            elapsed = time.time() - t_start
            print(f"\n  âœ— ERROR: {e}")
            results.append({
                'lokasi': lokasi,
                'hasil': {},
                'calculator': None,
                'success': False,
                'elapsed': elapsed,
                'error': str(e),
            })

    total_time = time.time() - t_batch_start
    n_success = sum(1 for r in results if r['success'])
    print(f"\n{'â–ˆ' * 70}")
    print(f"  BATCH SELESAI: {n_success}/{total} berhasil dalam {total_time:.0f} detik")
    print(f"{'â–ˆ' * 70}")

    # Tabel ringkasan akhir
    _print_tabel_ringkasan_multi(results, shared_params)

    return results


def _print_tabel_ringkasan_multi(results: list, shared_params: dict):
    """Cetak tabel ringkasan hasil multi-lokasi ke terminal."""
    mode = shared_params['mode']
    is_opt = (mode == 'optimal')

    print(f"\n{'â•' * 110}")
    print(f"  TABEL RINGKASAN â€” Bulan {shared_params['bulan_hijri']}/{shared_params['tahun_hijri']} H"
          f"  |  Mode: {mode}  |  Atmosfer: {shared_params['sumber_atmosfer'].upper()}")
    print(f"{'â•' * 110}")

    header = (f"{'No':>3} | {'Lokasi':<35} | {'Lat':>9} | {'Lon':>9} | "
              f"{'Moon Alt':>8} | {'Elong':>7} | {'Lebar':>5} | {'Î”m NE':>8} | {'Î”m Tel':>8} | "
              f"{'NE':>6} | {'Tel':>6}")
    print(header)
    print("-" * 110)

    for i, r in enumerate(results, 1):
        lok = r['lokasi']
        nama = lok.get('nama', '')
        lat = lok.get('lat', lok.get('lintang', 0.0))
        lon = lok.get('lon', lok.get('bujur', 0.0))
        if not r['success']:
            print(f"{i:3d} | {nama:<35} | {lat:9.4f} | {lon:9.4f} | "
                  f"{'ERROR':>8} | {'':>7} | {'':>5} | {'':>8} | {'':>8} | {'':>6} | {'':>6}")
            continue

        h = r['hasil']
        moon_alt = h.get('moon_alt', 0)
        elong = h.get('elongation', 0)
        moon_width_arcmin = h.get('moon_width', 0) * 60.0

        if is_opt:
            dm_ne = h.get('optimal_delta_m_ne', h.get('delta_m_ne', -99))
            dm_tel = h.get('optimal_delta_m_tel', h.get('delta_m_tel', -99))
        else:
            dm_ne = h.get('delta_m_ne', -99)
            dm_tel = h.get('delta_m_tel', -99)

        st_ne = "Y" if dm_ne > 0 else "N"
        st_tel = "Y" if dm_tel > 0 else "N"

        print(f"{i:3d} | {nama:<35} | {lat:9.4f} | {lon:9.4f} | "
              f"{moon_alt:8.3f} | {elong:7.3f} | {moon_width_arcmin:5.2f} | {dm_ne:+8.3f} | {dm_tel:+8.3f} | "
              f"{st_ne:>6} | {st_tel:>6}")

    print(f"{'â•' * 110}")

    # Hitung statistik
    success_results = [r for r in results if r['success']]
    if success_results:
        n_ne = 0
        n_tel = 0
        for r in success_results:
            h = r['hasil']
            if is_opt:
                dm_ne_val = h.get('optimal_delta_m_ne', h.get('delta_m_ne', -1))
                dm_tel_val = h.get('optimal_delta_m_tel', h.get('delta_m_tel', -1))
            else:
                dm_ne_val = h.get('delta_m_ne', -1)
                dm_tel_val = h.get('delta_m_tel', -1)
            if dm_ne_val > 0:
                n_ne += 1
            if dm_tel_val > 0:
                n_tel += 1
        print(f"  Naked Eye terlihat: {n_ne}/{len(success_results)}  |  "
              f"Teleskop terdeteksi: {n_tel}/{len(success_results)}")


def _simpan_excel_multi(results: list, shared_params: dict, filepath: str) -> str:
    """
    Simpan hasil multi-lokasi ke file Excel gabungan.

    Sheet 1: "Ringkasan Multi-Lokasi" â€” tabel semua lokasi
    Sheet 2: "Info & Parameter" â€” konfigurasi yang digunakan

    Parameters:
    -----------
    results : list[dict]
        Hasil dari _run_multi_lokasi()
    shared_params : dict
        Parameter bersama
    filepath : str
        Path file Excel

    Returns:
    --------
    str
        Path file yang disimpan
    """
    wb = Workbook()
    mode = shared_params['mode']
    is_opt = (mode == 'optimal')

    # --- Style definitions ---
    header_font = Font(name='Segoe UI', bold=True, size=11, color='FFFFFF')
    header_fill = PatternFill(start_color='1F4E79', end_color='1F4E79', fill_type='solid')
    data_font = Font(name='Segoe UI', size=10)
    data_font_bold = Font(name='Segoe UI', size=10, bold=True)
    align_center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    align_left = Alignment(horizontal='left', vertical='center')
    thin_border = Border(
        left=Side(style='thin', color='BDD7EE'),
        right=Side(style='thin', color='BDD7EE'),
        top=Side(style='thin', color='BDD7EE'),
        bottom=Side(style='thin', color='BDD7EE')
    )
    green_fill = PatternFill(start_color='C6E0B4', end_color='C6E0B4', fill_type='solid')
    red_fill = PatternFill(start_color='F8CBAD', end_color='F8CBAD', fill_type='solid')
    yellow_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Sheet 1: Ringkasan Multi-Lokasi
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    ws = wb.active
    ws.title = "Ringkasan Multi-Lokasi"
    ws.sheet_properties.tabColor = '1F4E79'

    headers = [
        'No', 'Lokasi', 'Lat (Â°)', 'Lon (Â°)', 'Elv (m)',
        'Sunset', 'Moon Alt (Â°)', 'Elongasi (Â°)', 'Lebar Sabit (arcmin)', 'Phase Angle (Â°)',
        'Semidiameter Bulan (deg)', 'Jarak Bulan (km)',
        'RH (%)', 'T (Â°C)', 'k_v (mag/airmass)', 'extinction_mag_v (mag)', 'transmission_v',
        'Sky Bright. (nL)', 'Lumin. Hilal (nL)',
        'Î”m NE (sunset)', 'Î”m Tel (sunset)',
    ]
    if is_opt:
        headers += [
            'Î”m NE (optimal)', 'Î”m Tel (optimal)',
            'Waktu Opt NE', 'Waktu Opt Tel',
            'Durasi NE (min)', 'Durasi Tel (min)',
            'Tel Gain (mag)',
            'k_v NE Optimal (mag/airmass)', 'extinction_mag_v NE Optimal (mag)', 'transmission_v NE Optimal',
            'k_v Tel Optimal (mag/airmass)', 'extinction_mag_v Tel Optimal (mag)', 'transmission_v Tel Optimal',
            'Semidiameter NE Optimal (deg)', 'Jarak Bulan NE Optimal (km)',
            'Semidiameter Tel Optimal (deg)', 'Jarak Bulan Tel Optimal (km)',
        ]
    headers += ['Status NE', 'Status Tel']

    # Write headers
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border

    # Write data rows
    for i, r in enumerate(results, 1):
        row_idx = i + 1
        lok = r['lokasi']
        nama = lok.get('nama', '')
        lat = lok.get('lat', lok.get('lintang', 0.0))
        lon = lok.get('lon', lok.get('bujur', 0.0))
        elv = lok.get('elevasi', lok.get('elv', 0.0))

        if not r['success']:
            row_data = [i, nama, lat, lon, elv]
            row_data += ['ERROR'] + [''] * (len(headers) - 7) + ['ERROR']
            for col, val in enumerate(row_data, 1):
                cell = ws.cell(row=row_idx, column=col, value=val)
                cell.font = data_font
                cell.alignment = align_center if col != 2 else align_left
                cell.border = thin_border
                if val == 'ERROR':
                    cell.fill = red_fill
            continue

        h = r['hasil']

        # Tentukan delta_m final
        if is_opt:
            dm_ne_final = h.get('optimal_delta_m_ne', h.get('delta_m_ne', -99))
            dm_tel_final = h.get('optimal_delta_m_tel', h.get('delta_m_tel', -99))
        else:
            dm_ne_final = h.get('delta_m_ne', -99)
            dm_tel_final = h.get('delta_m_tel', -99)

        st_ne = "TERLIHAT" if dm_ne_final > 0 else "TIDAK TERLIHAT"
        st_tel = "TERDETEKSI" if dm_tel_final > 0 else "TIDAK TERDETEKSI"

        sunset_str = ''
        sunset_val = h.get('sunset_local')
        if sunset_val and hasattr(sunset_val, 'strftime'):
            sunset_str = sunset_val.strftime('%H:%M:%S')

        row_data = [
            i, nama, lat, lon, elv,
            sunset_str,
            round(h.get('moon_alt', 0), 4),
            round(h.get('elongation', 0), 4),
            round(h.get('moon_width', 0) * 60.0, 4),
            round(h.get('phase_angle', 0), 4),
            h['moon_semidiameter'],
            h['moon_distance_km'],
            round(h.get('rh', 0), 2),
            round(h.get('temperature', 0), 2),
            round(h.get('k_v', 0), 4),
            round(h['extinction_mag_v'], 4),
            h['transmission_v'],
            f"{h.get('sky_brightness_nl', 0):.4e}",
            f"{h.get('luminansi_hilal_nl', 0):.4e}",
            round(h.get('delta_m_ne', -99), 4),
            round(h.get('delta_m_tel', -99), 4),
        ]

        if is_opt:
            opt_time_ne = h.get('optimal_time_ne')
            opt_time_tel = h.get('optimal_time_tel')
            row_data += [
                round(h.get('optimal_delta_m_ne', -99), 4),
                round(h.get('optimal_delta_m_tel', -99), 4),
                opt_time_ne.strftime('%H:%M:%S') if opt_time_ne and hasattr(opt_time_ne, 'strftime') else '',
                opt_time_tel.strftime('%H:%M:%S') if opt_time_tel and hasattr(opt_time_tel, 'strftime') else '',
                h.get('visibility_duration_ne', 0),
                h.get('visibility_duration_tel', 0),
                round(h.get('optimal_telescope_gain', h.get('telescope_gain', 0)), 4),
            ]
            for result_key in ('optimal_result_ne', 'optimal_result_tel'):
                optimal = h.get(result_key) or {}
                row_data += [optimal.get('k_v'), optimal.get('extinction_mag_v'), optimal.get('transmission_v')]
            for result_key in ('optimal_result_ne', 'optimal_result_tel'):
                optimal = h.get(result_key) or {}
                row_data += [optimal.get('moon_semidiameter'), optimal.get('moon_distance_km')]

        row_data += [st_ne, st_tel]

        for col, val in enumerate(row_data, 1):
            if isinstance(val, float) and not math.isfinite(val):
                val = str(val)
            cell = ws.cell(row=row_idx, column=col, value=val)
            cell.font = data_font
            cell.alignment = align_center if col != 2 else align_left
            cell.border = thin_border

        # Warnai kolom status
        col_st_ne = len(headers) - 1
        col_st_tel = len(headers)
        ws.cell(row=row_idx, column=col_st_ne).fill = green_fill if dm_ne_final > 0 else red_fill
        ws.cell(row=row_idx, column=col_st_ne).font = data_font_bold
        ws.cell(row=row_idx, column=col_st_tel).fill = green_fill if dm_tel_final > 0 else red_fill
        ws.cell(row=row_idx, column=col_st_tel).font = data_font_bold

    # Auto-fit column widths
    for col in range(1, len(headers) + 1):
        max_len = len(str(headers[col - 1]))
        for row_idx in range(2, len(results) + 2):
            cell_val = ws.cell(row=row_idx, column=col).value
            if cell_val:
                max_len = max(max_len, len(str(cell_val)))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 3, 30)
    # Kolom lokasi lebih lebar
    ws.column_dimensions['B'].width = 38

    ws.freeze_panes = 'A2'

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # Sheet 2: Info & Parameter
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    ws2 = wb.create_sheet(title="Info & Parameter")
    ws2.sheet_properties.tabColor = 'BF8F00'
    ws2.column_dimensions['A'].width = 35
    ws2.column_dimensions['B'].width = 50

    tel = shared_params['tel_params']
    sumber_label = HilalVisibilityCalculator.SUMBER_ATMOSFER_LABEL.get(
        shared_params['sumber_atmosfer'], shared_params['sumber_atmosfer'].upper())

    info_data = [
        ('Program', 'Perhitungan Visibilitas Hilal â€” Multi-Lokasi'),
        ('Bulan Hijriah', f"{shared_params['bulan_hijri']}"),
        ('Tahun Hijriah', f"{shared_params['tahun_hijri']}"),
        ('Mode Perhitungan', mode),
        ('Offset Hari', f"H + {shared_params['delta_day']} hari"),
        ('Sumber Data Atmosfer', sumber_label),
        ('Geometri Semidiameter', 'Skyfield + DE440s; jarak astrometrik toposentrik'),
        ('Sudut Fase Bulan', 'phase_angle(Sun) native Skyfield pada posisi astrometrik'),
        ('Lebar Sabit', 'W = 2 r k; k = fraksi iluminasi astrometrik'),
        ('Radius Bola Bulan (km)', MOON_RADIUS_KM),
        ('Jumlah Lokasi', f"{len(results)}"),
        ('Berhasil', f"{sum(1 for r in results if r['success'])}"),
        ('', ''),
        ('--- Parameter Teleskop ---', ''),
        ('Aperture (mm)', f"{tel.get('aperture', 100.0)}"),
        ('Magnification (x)', f"{tel.get('magnification', 50.0)}"),
        ('Central Obstruction (mm)', f"{tel.get('central_obstruction', 0.0)}"),
        ('Transmission', f"{tel.get('transmission', 0.95)}"),
        ('N Surfaces', f"{tel.get('n_surfaces', 6)}"),
        ('Observer Age (pupil fallback)', f"{tel.get('observer_age', 22.0)}"),
        ('Pupil Override (mm)', tel.get('pupil_diameter_mm') or 'Age-based dark-pupil estimate'),
        ('Field Factor Teleskop (F)', f"{tel.get('field_factor', 2.4)}"),
        ('Field Factor Naked Eye (F)', f"{shared_params['F_naked']}"),
        ('', ''),
        ('Tanggal Eksekusi', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    ]

    for col, hdr in enumerate(['Parameter', 'Nilai'], 1):
        cell = ws2.cell(row=1, column=col, value=hdr)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = align_center
        cell.border = thin_border

    for i, (param, nilai) in enumerate(info_data, 2):
        cell_p = ws2.cell(row=i, column=1, value=param)
        cell_p.font = data_font_bold if param.startswith('---') else data_font
        cell_p.border = thin_border
        cell_v = ws2.cell(row=i, column=2, value=nilai)
        cell_v.font = data_font
        cell_v.border = thin_border

    ws2.freeze_panes = 'A2'

    # Save
    output_dir = os.path.dirname(filepath)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    wb.save(filepath)
    save_atmosphere_provenance(filepath, [
        atmosphere_audit_record(
            r['lokasi'].get('nama', ''), shared_params['sumber_atmosfer'],
            r['success'], r.get('hasil'), r.get('error'),
        ) for r in results
    ])
    print(f"\n  âœ“ Hasil multi-lokasi disimpan ke: {filepath}")
    return filepath


def _plot_multi_lokasi(results: list, shared_params: dict,
                       save_path: Optional[str] = None) -> bool:
    """
    Plot perbandingan delta_m (visibility margin) antar lokasi.

    Lollipop chart dengan dark theme: lokasi di sumbu Y, delta_m di sumbu X.
    Gradient warna berdasarkan nilai margin. Dual panel: Naked Eye & Teleskop.

    Parameters:
    -----------
    results : list[dict]
        Hasil dari _run_multi_lokasi()
    shared_params : dict
        Parameter bersama
    save_path : str or None
        Path untuk menyimpan gambar. None = hanya tampilkan.

    Returns:
    -------
    bool
        True jika berhasil, False jika gagal.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        from matplotlib.colors import LinearSegmentedColormap
        import matplotlib.patheffects as pe
        import numpy as np
    except ImportError:
        print("  [!] matplotlib belum terinstall. Jalankan: pip install matplotlib")
        return False

    success_results = [r for r in results if r['success']]
    if not success_results:
        print("  [!] Tidak ada hasil valid untuk diplot.")
        return False

    mode = shared_params['mode']
    is_opt = (mode == 'optimal')

    # Kumpulkan data
    nama_list = []
    dm_ne_list = []
    dm_tel_list = []
    lat_list = []
    lon_list = []

    for r in reversed(success_results):  # reversed agar urutan atasâ†’bawah sesuai input
        lok = r['lokasi']
        h = r['hasil']
        nama = lok.get('nama', '')
        if len(nama) > 30:
            nama = nama[:28] + 'â€¦'
        nama_list.append(nama)
        lat_list.append(lok.get('lat', lok.get('lintang', 0.0)))
        lon_list.append(lok.get('lon', lok.get('bujur', 0.0)))

        if is_opt:
            dm_ne_list.append(h.get('optimal_delta_m_ne', h.get('delta_m_ne', -99)))
            dm_tel_list.append(h.get('optimal_delta_m_tel', h.get('delta_m_tel', -99)))
        else:
            dm_ne_list.append(h.get('delta_m_ne', -99))
            dm_tel_list.append(h.get('delta_m_tel', -99))

    n = len(nama_list)

    # â”€â”€ Warna & Style â”€â”€
    BG_COLOR = '#0f1923'
    PANEL_BG = '#162230'
    GRID_COLOR = '#1e3348'
    TEXT_COLOR = '#e8edf3'
    SUBTEXT_COLOR = '#8899aa'
    ACCENT_GREEN = '#00e396'
    ACCENT_RED = '#ff4560'
    ACCENT_AMBER = '#feb019'
    THRESHOLD_COLOR = '#3a5068'

    def valor_color(v):
        """Warna gradien berdasarkan nilai margin."""
        if v >= 5:
            return ACCENT_GREEN
        elif v >= 0:
            # Interpolasi hijau â†’ kuning
            t = v / 5.0
            r_c = int(254 * (1 - t) + 0 * t)
            g_c = int(176 * (1 - t) + 227 * t)
            b_c = int(25 * (1 - t) + 150 * t)
            return f'#{r_c:02x}{g_c:02x}{b_c:02x}'
        elif v >= -5:
            # Interpolasi kuning â†’ merah
            t = abs(v) / 5.0
            r_c = int(254 * (1 - t) + 255 * t)
            g_c = int(176 * (1 - t) + 69 * t)
            b_c = int(25 * (1 - t) + 96 * t)
            return f'#{r_c:02x}{g_c:02x}{b_c:02x}'
        else:
            return ACCENT_RED

    # â”€â”€ Layout â”€â”€
    fig_height = max(7, n * 0.55 + 3.5)
    fig = plt.figure(figsize=(18, fig_height), facecolor=BG_COLOR)

    # Grid: header row + main row, two columns
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 12],
                          hspace=0.08, wspace=0.02,
                          left=0.14, right=0.96, top=0.92, bottom=0.08)

    # Header axes (untuk judul panel)
    ax_h1 = fig.add_subplot(gs[0, 0], facecolor='none')
    ax_h2 = fig.add_subplot(gs[0, 1], facecolor='none')
    for ax_h in [ax_h1, ax_h2]:
        ax_h.set_xlim(0, 1)
        ax_h.set_ylim(0, 1)
        ax_h.axis('off')

    ax_h1.text(0.5, 0.3, 'NAKED EYE', fontsize=14, fontweight='bold',
               color=TEXT_COLOR, ha='center', va='center',
               fontfamily='monospace', alpha=0.95)
    ax_h2.text(0.5, 0.3, 'TELESKOP', fontsize=14, fontweight='bold',
               color=TEXT_COLOR, ha='center', va='center',
               fontfamily='monospace', alpha=0.95)

    ax1 = fig.add_subplot(gs[1, 0], facecolor=PANEL_BG)
    ax2 = fig.add_subplot(gs[1, 1], facecolor=PANEL_BG, sharey=ax1)

    y_pos = np.arange(n)

    def draw_lollipop(ax, values, show_labels=True):
        """Gambar lollipop chart dengan glow effect."""
        # Threshold zone
        ax.axvspan(-0.5, 0.5, color=THRESHOLD_COLOR, alpha=0.15, zorder=0)
        ax.axvline(x=0, color=THRESHOLD_COLOR, linewidth=2, linestyle='-', zorder=1)

        for j, v in enumerate(values):
            c = valor_color(v)
            if not math.isfinite(v):
                ax.text(0, j, f'  {v}', va='center', ha='left',
                        color=ACCENT_RED, fontsize=9)
                continue
            # Garis lollipop
            ax.plot([0, v], [j, j], color=c, linewidth=2.5, alpha=0.7, zorder=2,
                    solid_capstyle='round')
            # Titik ujung dengan glow
            ax.scatter(v, j, color=c, s=120, zorder=4, edgecolors='none')
            ax.scatter(v, j, color=c, s=280, zorder=3, edgecolors='none', alpha=0.15)

            # Label nilai
            offset = 0.4 if v >= 0 else -0.4
            align = 'left' if v >= 0 else 'right'
            ax.text(v + offset, j, f'{v:+.2f}',
                    va='center', ha=align, fontsize=9, fontweight='bold',
                    color=c, fontfamily='monospace',
                    path_effects=[pe.withStroke(linewidth=2, foreground=BG_COLOR)])

            # Ikon status
            if v > 0:
                icon = 'â—'
                icon_color = ACCENT_GREEN
            else:
                icon = 'â—‹'
                icon_color = ACCENT_RED
            status_x = 0.03 if v >= 0 else -0.03
            # (ikon ditaruh di dekat garis 0)

        # Garis horizontal pemisah antar lokasi (subtle)
        for j in range(n):
            ax.axhline(y=j, color=GRID_COLOR, linewidth=0.5, alpha=0.5, zorder=0)

        # Styling sumbu
        ax.set_xlabel('Visibility Margin  Î”m  (mag)', fontsize=10,
                       fontweight='bold', color=SUBTEXT_COLOR, labelpad=10)
        ax.tick_params(axis='x', colors=SUBTEXT_COLOR, labelsize=9)
        ax.tick_params(axis='y', colors=TEXT_COLOR, labelsize=9)
        ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
        ax.xaxis.set_minor_locator(ticker.MultipleLocator(1))
        ax.grid(axis='x', which='major', color=GRID_COLOR, linewidth=0.8, alpha=0.6)
        ax.grid(axis='x', which='minor', color=GRID_COLOR, linewidth=0.3, alpha=0.3)

        # Hilangkan border
        for spine in ax.spines.values():
            spine.set_visible(False)

        if show_labels:
            ax.set_yticks(y_pos)
            ax.set_yticklabels(nama_list, fontsize=10, color=TEXT_COLOR,
                               fontfamily='sans-serif')
        else:
            plt.setp(ax.get_yticklabels(), visible=False)

    # â”€â”€ Gambar kedua panel â”€â”€
    draw_lollipop(ax1, dm_ne_list, show_labels=True)
    draw_lollipop(ax2, dm_tel_list, show_labels=False)

    # Simetriskan sumbu X
    finite_dm = [v for v in dm_ne_list + dm_tel_list if math.isfinite(v)]
    x_abs_max = max((abs(v) for v in finite_dm), default=5)
    x_limit = math.ceil(x_abs_max / 5) * 5 + 2
    ax1.set_xlim(-x_limit, x_limit)
    ax2.set_xlim(-x_limit, x_limit)
    ax1.set_ylim(-0.7, n - 0.3)
    ax2.set_ylim(-0.7, n - 0.3)

    # Invert agar lokasi pertama di atas
    ax1.invert_yaxis()

    # â”€â”€ Ringkasan statistik di bawah â”€â”€
    n_vis_ne = sum(1 for v in dm_ne_list if v > 0)
    n_vis_tel = sum(1 for v in dm_tel_list if v > 0)

    summary_ne = f'{n_vis_ne}/{n} terlihat'
    summary_tel = f'{n_vis_tel}/{n} terlihat'

    ax1.text(0.5, -0.08, summary_ne, transform=ax1.transAxes,
             fontsize=11, fontweight='bold', color=ACCENT_GREEN if n_vis_ne > 0 else ACCENT_RED,
             ha='center', va='top', fontfamily='monospace')
    ax2.text(0.5, -0.08, summary_tel, transform=ax2.transAxes,
             fontsize=11, fontweight='bold', color=ACCENT_GREEN if n_vis_tel > 0 else ACCENT_RED,
             ha='center', va='top', fontfamily='monospace')

    # â”€â”€ Judul utama â”€â”€
    bln = shared_params['bulan_hijri']
    thn = shared_params['tahun_hijri']
    sumber = shared_params['sumber_atmosfer'].upper()
    mode_label = "OPTIMAL" if is_opt else "SUNSET"

    fig.text(0.55, 0.97,
             f'PERBANDINGAN VISIBILITAS HILAL',
             fontsize=17, fontweight='bold', color=TEXT_COLOR,
             ha='center', va='center', fontfamily='monospace')
    fig.text(0.55, 0.945,
             f'Bulan {bln}/{thn} H   Â·   Mode {mode_label}   Â·   Atmosfer {sumber}   Â·   {n} Lokasi',
             fontsize=10, color=SUBTEXT_COLOR,
             ha='center', va='center', fontfamily='monospace')

    # â”€â”€ Legenda kustom â”€â”€
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='none', markerfacecolor=ACCENT_GREEN,
               markersize=10, label='Terlihat (Î”m â‰¥ 0)'),
        Line2D([0], [0], marker='o', color='none', markerfacecolor=ACCENT_RED,
               markersize=10, label='Tidak Terlihat (Î”m < 0)'),
        Line2D([0], [0], marker='o', color='none', markerfacecolor=ACCENT_AMBER,
               markersize=10, label='Marginal (Î”m â‰ˆ 0)'),
    ]
    fig.legend(handles=legend_elements, loc='lower center', ncol=3,
               fontsize=9, frameon=False, labelcolor=SUBTEXT_COLOR,
               bbox_to_anchor=(0.55, 0.01))

    if save_path:
        os.makedirs(os.path.dirname(save_path) or '.', exist_ok=True)
        fig.savefig(save_path, dpi=200, bbox_inches='tight',
                    facecolor=BG_COLOR, edgecolor='none')
        print(f"  [âœ“] Grafik perbandingan disimpan: {save_path}")

    plt.close(fig)
    return True


def main():
    """Fungsi utama dengan mode interaktif untuk pemilihan lokasi dan parameter."""
    from daftar_lokasi import pilih_lokasi_interaktif

    print("\n" + "=" * 70)
    print("  PROGRAM PERHITUNGAN VISIBILITAS HILAL")
    print("  Model: Schaefer (Sky Brightness) + Kastner (Luminansi Hilal)")
    print("=" * 70)

    # LANGKAH 0: Pilih Mode Lokasi (Tunggal / Multi)
    mode_lokasi = _input_mode_lokasi()

    if mode_lokasi == 'multi':
        return _main_multi()
    else:
        return _main_single()


def _main_single():
    """Alur interaktif untuk perhitungan lokasi tunggal (alur asli)."""
    from daftar_lokasi import pilih_lokasi_interaktif

    # LANGKAH 1: Pilih Lokasi
    print("\n--- LANGKAH 1: PILIH LOKASI PENGAMATAN ---")
    lokasi = pilih_lokasi_interaktif()
    if lokasi is None:
        print("[!] Lokasi tidak valid. Program dihentikan.")
        return None

    nama_tempat = lokasi.get("nama", "")
    lintang = lokasi.get("lat", lokasi.get("lintang", 0.0))
    bujur = lokasi.get("lon", lokasi.get("bujur", 0.0))
    elevasi = lokasi.get("elevasi", lokasi.get("elv", 0.0))
    bias_t = lokasi.get("bias_t", 0.0)
    bias_rh = lokasi.get("bias_rh", 0.0)
    timezone_str = tentukan_timezone_indonesia(bujur)

    print(f"\n  Lokasi    : {nama_tempat}")
    print(f"  Koordinat : {lintang}Â°, {bujur}Â°")
    print(f"  Elevasi   : {elevasi} m")
    print(f"  Timezone  : {timezone_str}")
    if bias_t != 0.0 or bias_rh != 0.0:
        print(f"  Bias Data : T={bias_t:+.1f}Â°C, RH={bias_rh:+.1f}%")

    # LANGKAH 2: Input Bulan dan Tahun Hijriah
    result = _input_bulan_tahun_hijri()
    if result is None:
        return None
    bulan_hijri, tahun_hijri = result

    # LANGKAH 3 & 3.5: Mode dan Offset
    mode, delta_day = _input_mode_dan_offset()

    # LANGKAH 3.6: Sumber Data Atmosfer
    sumber_atmosfer, manual_rh, manual_t, manual_p = _input_sumber_atmosfer()

    # LANGKAH 3.7: Koreksi Bias
    bias_t, bias_rh = _input_koreksi_bias(bias_t, bias_rh, sumber_atmosfer)

    # LANGKAH 4: Parameter Teleskop & Field Factor
    tel_params = _input_parameter_teleskop()
    F_naked = tel_params.pop('F_naked')  # pisahkan, bukan parameter teleskop

    # JALANKAN PERHITUNGAN
    print("\n" + "=" * 70)
    print("  MEMULAI PERHITUNGAN...")
    print("=" * 70)

    calculator = HilalVisibilityCalculator(
        nama_tempat=nama_tempat,
        lintang=lintang,
        bujur=bujur,
        elevasi=elevasi,
        timezone_str=timezone_str,
        bulan_hijri=bulan_hijri,
        tahun_hijri=tahun_hijri,
        delta_day_offset=delta_day,
        bias_t=bias_t,
        bias_rh=bias_rh,
        sumber_atmosfer=sumber_atmosfer,
        manual_rh=manual_rh,
        manual_t=manual_t,
        manual_p=manual_p
    )

    hasil = calculator.jalankan_perhitungan_lengkap(
        use_telescope=True,
        mode=mode,
        min_moon_alt=2.0,
        F_naked=F_naked,
        **tel_params
    )

    status_ne = "TERLIHAT" if hasil.get('delta_m_ne', -1) > 0 else "SULIT TERLIHAT"
    status_tel = "TERDETEKSI" if hasil.get('delta_m_tel', -1) > 0 else "SULIT TERDETEKSI"
    print(f"\nPROGRAM SELESAI   : Hilal {status_ne} (naked eye), {status_tel} (teleskop)")

    # LANGKAH 5: Simpan ke Excel
    print("\n--- LANGKAH 5: SIMPAN HASIL KE EXCEL ---")
    try:
        simpan_excel = input("  Simpan hasil ke file Excel? (Y/n): ").strip().lower()
    except EOFError:
        simpan_excel = 'n'

    if simpan_excel != 'n':
        nama_file_safe = nama_tempat.replace(' ', '_').replace('/', '-').replace('\\', '-')
        sumber_tag = sumber_atmosfer.upper().replace('MERRA2', 'MERRA2')
        nama_file = f"Hilal_{nama_file_safe}_{bulan_hijri}_{tahun_hijri}_{sumber_tag}.xlsx"
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(script_dir, 'output')
        filepath = os.path.join(output_dir, nama_file)
        calculator.simpan_ke_excel(filepath)
        print(f"  File: {filepath}")
    else:
        print("  Hasil tidak disimpan ke Excel.")

    # LANGKAH 6: Grafik Visualisasi Visibility Margin
    if mode.lower() == 'optimal' and hasil.get('all_timestep_results'):
        print("\n--- LANGKAH 6: GRAFIK VISUALISASI ---")
        try:
            simpan_grafik = input("  Simpan grafik visibilitas margin ke file gambar? (Y/n): ").strip().lower()
        except EOFError:
            simpan_grafik = 'n'

        if simpan_grafik != 'n':
            nama_file_safe = nama_tempat.replace(' ', '_').replace('/', '-').replace('\\', '-')
            sumber_tag = sumber_atmosfer.upper()
            nama_grafik = f"Grafik_Hilal_{nama_file_safe}_{bulan_hijri}_{tahun_hijri}_{sumber_tag}.png"
            script_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(script_dir, 'output')
            grafik_path = os.path.join(output_dir, nama_grafik)
            calculator.plot_visibility_margin(save_path=grafik_path)
        else:
            print("  Grafik tidak disimpan.")

    return hasil


def _main_multi():
    """Alur interaktif untuk perhitungan multi-lokasi (batch)."""

    # LANGKAH 1B: Pilih Lokasi-Lokasi
    lokasi_list = _input_multi_lokasi()
    if not lokasi_list:
        print("[!] Tidak ada lokasi yang dipilih. Program dihentikan.")
        return None

    # LANGKAH 2: Input Bulan dan Tahun Hijriah (shared)
    result = _input_bulan_tahun_hijri()
    if result is None:
        return None
    bulan_hijri, tahun_hijri = result

    # LANGKAH 3 & 3.5: Mode dan Offset (shared)
    mode, delta_day = _input_mode_dan_offset()

    # LANGKAH 3.6: Sumber Data Atmosfer (shared)
    sumber_atmosfer, manual_rh, manual_t, manual_p = _input_sumber_atmosfer()

    # LANGKAH 3.7: Koreksi Bias
    bias_mode = _input_koreksi_bias_multi(lokasi_list, sumber_atmosfer)

    # LANGKAH 4: Parameter Teleskop & Field Factor (shared)
    tel_params = _input_parameter_teleskop()
    F_naked = tel_params.pop('F_naked')

    # Susun shared_params
    shared_params = {
        'bulan_hijri': bulan_hijri,
        'tahun_hijri': tahun_hijri,
        'mode': mode,
        'delta_day': delta_day,
        'sumber_atmosfer': sumber_atmosfer,
        'manual_rh': manual_rh,
        'manual_t': manual_t,
        'manual_p': manual_p,
        'F_naked': F_naked,
        'tel_params': tel_params,
        'bias_mode': bias_mode,
    }

    # JALANKAN BATCH
    results = _run_multi_lokasi(lokasi_list, shared_params)

    # LANGKAH 5B: Simpan ke Excel
    print("\n--- LANGKAH 5: SIMPAN HASIL KE EXCEL ---")
    try:
        simpan_excel = input("  Simpan hasil multi-lokasi ke file Excel? (Y/n): ").strip().lower()
    except EOFError:
        simpan_excel = 'n'

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, 'output')

    if simpan_excel != 'n':
        sumber_tag = sumber_atmosfer.upper()
        nama_file = f"Hilal_Multi_{bulan_hijri}_{tahun_hijri}_{sumber_tag}_{len(results)}lokasi.xlsx"
        filepath = os.path.join(output_dir, nama_file)
        _simpan_excel_multi(results, shared_params, filepath)
        print(f"  File: {filepath}")
    else:
        print("  Hasil tidak disimpan ke Excel.")

    # LANGKAH 6B: Grafik Perbandingan Multi-Lokasi
    print("\n--- LANGKAH 6: GRAFIK PERBANDINGAN MULTI-LOKASI ---")
    try:
        simpan_grafik = input("  Simpan grafik perbandingan visibilitas antar lokasi? (Y/n): ").strip().lower()
    except EOFError:
        simpan_grafik = 'n'

    if simpan_grafik != 'n':
        sumber_tag = sumber_atmosfer.upper()
        nama_grafik = f"Grafik_Multi_{bulan_hijri}_{tahun_hijri}_{sumber_tag}_{len(results)}lokasi.png"
        grafik_path = os.path.join(output_dir, nama_grafik)
        _plot_multi_lokasi(results, shared_params, save_path=grafik_path)
    else:
        print("  Grafik tidak disimpan.")

    return results


if __name__ == "__main__":
    hasil = main()
