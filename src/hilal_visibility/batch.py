#!/usr/bin/env python3
"""
══════════════════════════════════════════════════════════════════════
PERBANDINGAN MODEL VISUAL CRUMEY (2014) vs LABEL CITRA HILAL BMKG
══════════════════════════════════════════════════════════════════════

Menjalankan model visibilitas hilal pada seluruh data observasi rukyatul
hilal dari lokasi-lokasi BMKG Indonesia, lalu membandingkan hasil prediksi
model visual (naked eye & teleskop) dengan label deteksi kamera/CCD.
Perbandingan lintas-metode ini deskriptif, bukan validasi ambang penglihatan
manusia. Konfigurasi alat dan jam pengamatan aktual tidak tersedia.

Fitur:
  1. Batch processing observasi di banyak lokasi sekaligus
  2. Perhitungan visibilitas naked eye dan teleskop
  3. Perbandingan prediksi model vs observasi (Y/N)
  4. Output Excel dengan format rapi

CARA PAKAI:
  Jalankan dari checkout:
      python scripts/run_batch.py

PRASYARAT:
  - Koneksi internet (untuk ECMWF IFS API)
  - Paket hilal_visibility dan dependensi sudah terinstall
  - File data/ephemeris/de440s.bsp tersedia

Author: Pipeline validasi untuk skripsi hilal
Referensi: Crumey, A. (2014), MNRAS 442, 2600-2619
══════════════════════════════════════════════════════════════════════
"""

import csv
import math
import os
import sys
import time
import traceback
from datetime import date
from typing import List
from hilal_visibility.paths import OUTPUT_DIR
from hilal_visibility.console import configure_console_encoding

from hilal_visibility.calculator import (
    HilalVisibilityCalculator,
    tentukan_timezone_indonesia,
    hisab_observation_date,
    H0_REFERENCE_TIMEZONE,
)
from hilal_visibility.ephemeris import newmoon_hijri_month_utc
from hilal_visibility.atmosphere.provenance import atmosphere_audit_record, save_atmosphere_provenance
from hilal_visibility.atmosphere.ifs import ARCHIVE_URL, IFS_MODEL, IFS_PRODUCT_NAME
from hilal_visibility.models.crumey import DEFAULT_VISUAL_FIELD_FACTOR


# ═══════════════════════════════════════════════════════════════════
# KONFIGURASI GLOBAL (nilai default)
# ═══════════════════════════════════════════════════════════════════

# --- Residual visual field factor referensi; belum dikalibrasi khusus hilal ---
F_NAKED_REF = DEFAULT_VISUAL_FIELD_FACTOR
FIELD_FACTOR_REF = DEFAULT_VISUAL_FIELD_FACTOR

# Appended CSV diagnostics and a separate Excel sheet preserve legacy columns.
VISUAL_DIAGNOSTIC_COLUMNS = (
    ('F_Residual_NE', 'F_naked'), ('F_Residual_Tel', 'field_factor'),
    ('Regime_NE_Sunset', 'crumey_ne_regime'),
    ('Regime_Tel_Sunset', 'crumey_tel_regime'),
    ('Achromatic_Extrapolation_NE_Sunset', 'crumey_ne_achromatic_extrapolation'),
    ('Achromatic_Extrapolation_Tel_Sunset', 'crumey_tel_achromatic_extrapolation'),
    ('Regime_NE_Optimal', 'opt_ne_regime'),
    ('Regime_Tel_Optimal', 'opt_tel_regime'),
    ('Achromatic_Extrapolation_NE_Optimal', 'opt_ne_achromatic_extrapolation'),
    ('Achromatic_Extrapolation_Tel_Optimal', 'opt_tel_achromatic_extrapolation'),
    ('Threshold_Difference_Sunset_mag', 'threshold_difference_mag'),
    ('Threshold_Difference_Tel_Optimal_mag', 'optimal_threshold_difference_mag'),
    ('F_Comparison', 'field_factor_comparison'),
)

DATE_DIAGNOSTIC_COLUMNS = (
    ('Tanggal_Model', 'tanggal_model'),
    ('Tanggal_Hisab_H0', 'tanggal_hisab'),
    ('Offset_Hari_dari_Hisab', 'delta_day_offset'),
    ('Tanggal_Cocok', 'tanggal_cocok'),
    ('Tanggal_Dataset_Asli', 'tanggal_dataset'),
    ('Sumber_Tanggal', 'sumber_tanggal'),
    ('Zona_Acuan_H0', 'h0_reference_timezone'),
)


def _visual_diagnostic_values(result):
    values = []
    for label, key in VISUAL_DIAGNOSTIC_COLUMNS:
        available = result.get('success', False)
        if 'NE_Optimal' in label:
            available = available and bool(result.get('optimal_time_ne'))
        elif 'Tel_Optimal' in label:
            available = available and bool(result.get('optimal_time_tel'))
        value = result.get(key) if available else None
        if isinstance(value, float) and not math.isfinite(value):
            value = str(value)
        values.append(value)
    return values

# Confirmed by the dataset owner: gallery results concern digital/CCD images.
# These labels must not be used to fit a human-vision field factor.
OBSERVATION_METHOD = 'ccd'
OBSERVATION_SOURCE = 'https://hilal.bmkg.go.id/gallery'
COMPARISON_SCOPE = 'cross_method_descriptive'

# --- Parameter teleskop default BMKG ---
TEL_PARAMS = dict(
    aperture=100.0,             # mm (refraktor BMKG tipikal)
    magnification=50.0,         # pembesaran
    transmission=0.95,          # transmisi per permukaan
    n_surfaces=6,               # jumlah permukaan optik
    central_obstruction=0.0,    # refraktor → 0
    observer_age=22.0,          # usia pengamat tipikal
    field_factor=FIELD_FACTOR_REF,
)

# --- Mode perhitungan ---
CALC_MODE = "optimal"       # "sunset" atau "optimal"
SUMBER_ATMOSFER = "ecmwf_ifs"    # "ecmwf_ifs", "merra2", "manual"

# --- Interval loop optimal ---
INTERVAL_MENIT = 1
MIN_MOON_ALT = 2.0
START_DELAY_MENIT = 1


def _input_float(prompt: str, default: float) -> float:
    """Minta input float dari user, return default jika kosong."""
    try:
        val = input(f"  {prompt} [{default}]: ").strip()
        return float(val) if val else default
    except ValueError:
        print(f"    [!] Input tidak valid, menggunakan default: {default}")
        return default


def _input_int(prompt: str, default: int) -> int:
    """Minta input int dari user, return default jika kosong."""
    try:
        val = input(f"  {prompt} [{default}]: ").strip()
        return int(val) if val else default
    except ValueError:
        print(f"    [!] Input tidak valid, menggunakan default: {default}")
        return default


def _input_konfigurasi_interaktif():
    """Konfigurasi global secara interaktif. Tekan Enter untuk pakai default."""
    global F_NAKED_REF, FIELD_FACTOR_REF, TEL_PARAMS
    global CALC_MODE, SUMBER_ATMOSFER
    global INTERVAL_MENIT, MIN_MOON_ALT, START_DELAY_MENIT

    print("\n" + "═" * 70)
    print("  KONFIGURASI GLOBAL (tekan Enter untuk pakai nilai default)")
    print("═" * 70)

    # --- Mode perhitungan ---
    print("\n  ── Mode Perhitungan ──")
    print(f"  Pilihan: 1=optimal, 2=sunset")
    mode_input = input(f"  Mode perhitungan [{CALC_MODE}]: ").strip().lower()
    if mode_input == "2" or mode_input == "sunset":
        CALC_MODE = "sunset"
    elif mode_input == "1" or mode_input == "optimal":
        CALC_MODE = "optimal"
    elif mode_input:
        print(f"    [!] Input tidak valid, menggunakan default: {CALC_MODE}")
    print(f"    → Mode: {CALC_MODE}")

    # --- Sumber atmosfer ---
    print("\n  ── Sumber Data Atmosfer ──")
    print(f"  Pilihan: 1=ecmwf_ifs, 2=merra2, 3=manual")
    atm_input = input(f"  Sumber atmosfer [{SUMBER_ATMOSFER}]: ").strip().lower()
    if atm_input in ("1", "ecmwf_ifs"):
        SUMBER_ATMOSFER = "ecmwf_ifs"
    elif atm_input in ("2", "merra2"):
        SUMBER_ATMOSFER = "merra2"
    elif atm_input in ("3", "manual"):
        SUMBER_ATMOSFER = "manual"
    elif atm_input:
        print(f"    [!] Input tidak valid, menggunakan default: {SUMBER_ATMOSFER}")
    print(f"    → Sumber: {SUMBER_ATMOSFER}")

    # --- Field factor ---
    print("\n  ── Field Factor ──")
    F_NAKED_REF = _input_float("F naked eye", F_NAKED_REF)
    FIELD_FACTOR_REF = _input_float("F teleskop", FIELD_FACTOR_REF)

    # --- Parameter teleskop ---
    print("\n  ── Parameter Teleskop ──")
    TEL_PARAMS['aperture'] = _input_float("Aperture (mm)", TEL_PARAMS['aperture'])
    TEL_PARAMS['magnification'] = _input_float("Magnifikasi", TEL_PARAMS['magnification'])
    TEL_PARAMS['transmission'] = _input_float("Transmisi/permukaan", TEL_PARAMS['transmission'])
    TEL_PARAMS['n_surfaces'] = _input_int("Jumlah permukaan optik", int(TEL_PARAMS['n_surfaces']))
    TEL_PARAMS['central_obstruction'] = _input_float("Central obstruction", TEL_PARAMS['central_obstruction'])
    TEL_PARAMS['observer_age'] = _input_float("Usia pengamat (tahun)", TEL_PARAMS['observer_age'])
    TEL_PARAMS['field_factor'] = FIELD_FACTOR_REF

    # --- Interval loop optimal ---
    print("\n  ── Interval Loop Optimal ──")
    INTERVAL_MENIT = _input_int("Interval (menit)", INTERVAL_MENIT)
    MIN_MOON_ALT = _input_float("Min altitude bulan (°)", MIN_MOON_ALT)
    START_DELAY_MENIT = _input_int("Start delay (menit)", START_DELAY_MENIT)

    # --- Ringkasan ---
    print("\n" + "─" * 70)
    print("  RINGKASAN KONFIGURASI:")
    print(f"    Mode          : {CALC_MODE}")
    print(f"    Atmosfer      : {SUMBER_ATMOSFER}")
    print(f"    F naked eye   : {F_NAKED_REF}")
    print(f"    F teleskop    : {FIELD_FACTOR_REF}")
    print(f"    Aperture      : {TEL_PARAMS['aperture']} mm")
    print(f"    Magnifikasi   : {TEL_PARAMS['magnification']}")
    print(f"    Transmisi     : {TEL_PARAMS['transmission']}")
    print(f"    N surfaces    : {TEL_PARAMS['n_surfaces']}")
    print(f"    Obstruction   : {TEL_PARAMS['central_obstruction']}")
    print(f"    Usia pengamat : {TEL_PARAMS['observer_age']} tahun")
    print(f"    Interval      : {INTERVAL_MENIT} menit")
    print(f"    Min moon alt  : {MIN_MOON_ALT}°")
    print(f"    Start delay   : {START_DELAY_MENIT} menit")
    print("─" * 70)


# ═══════════════════════════════════════════════════════════════════
# DATA OBSERVASI
# ═══════════════════════════════════════════════════════════════════
# Format per entry:
#   no, tanggal (YYYY-MM-DD), nama lokasi,
#   lat, lon, elv,
#   bulan_hijri, tahun_hijri,
#   bias_t, bias_rh,
#   observed (True=Y, False=N)

from hilal_visibility.datasets import load_observation_rows
from hilal_visibility.paths import OBSERVATIONS_PATH
OBSERVATIONS = load_observation_rows(OBSERVATIONS_PATH)


# ═══════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════

N_OBS = len(OBSERVATIONS)


def parse_obs(entry: tuple) -> dict:
    """Parse satu entry tuple menjadi dictionary."""
    return {
        'no': entry[0],
        'tanggal': entry[1],
        'nama': entry[2],
        'lat': entry[3],
        'lon': entry[4],
        'elv': entry[5],
        'bulan_hijri': entry[6],
        'tahun_hijri': entry[7],
        'bias_t': entry[8],
        'bias_rh': entry[9],
        'observed': entry[10],  # True = Y, False = N
        'observation_method': OBSERVATION_METHOD,
        'observation_source': OBSERVATION_SOURCE,
        'actual_telescope_configuration_available': False,
        'actual_observation_time_available': False,
    }


# ═══════════════════════════════════════════════════════════════════
# BATCH PROCESSING
# ═══════════════════════════════════════════════════════════════════

def select_observation_date(obs):
    """Hijri ephemeris determines the shared WIB date; dataset dates supply offsets.

    The H-2..H+2 range matches the interactive observing-day menu. A Gregorian
    date outside that campaign cannot replace the Hijri lunation supplied by
    the dataset owner, so retain H+0 and audit the original Gregorian date.
    """
    conjunction = newmoon_hijri_month_utc(obs['tahun_hijri'], obs['bulan_hijri'])
    reference = hisab_observation_date(conjunction)
    original = date.fromisoformat(obs['tanggal'])
    offset = (original - reference).days
    if -2 <= offset <= 2:
        return original, 'ephemeris_hijri_plus_offset_dataset'
    return reference, 'ephemeris_hijri'


def run_single_observation(obs: dict, verbose: bool = True) -> dict:
    """Jalankan model pada acuan ephemeris Hijriah + offset observasi.

    Returns
    -------
    dict : berisi semua hasil + metadata observasi
    """
    no = obs['no']
    nama = obs['nama']
    tanggal = obs['tanggal']
    tz = tentukan_timezone_indonesia(obs['lon'])

    if verbose:
        print(f"\n{'═' * 70}")
        print(f"[{no:2d}/{N_OBS}] {nama}")
        print(f"        Tanggal: {tanggal}  |  Hijri: {obs['bulan_hijri']}/{obs['tahun_hijri']}")
        print(f"        Lat={obs['lat']:.4f}  Lon={obs['lon']:.4f}  Elv={obs['elv']:.0f}m")
        print(f"        Observasi: {'TERLIHAT (Y)' if obs['observed'] else 'TIDAK TERLIHAT (N)'}")
        print(f"{'═' * 70}")

    try:
        selected_date, date_source = select_observation_date(obs)
        tanggal = selected_date.isoformat()
        calc = HilalVisibilityCalculator(
            nama_tempat=nama,
            lintang=obs['lat'],
            bujur=obs['lon'],
            elevasi=obs['elv'],
            timezone_str=tz,
            bulan_hijri=obs['bulan_hijri'],
            tahun_hijri=obs['tahun_hijri'],
            delta_day_offset=0,
            observation_date=selected_date,
            bias_t=obs['bias_t'],
            bias_rh=obs['bias_rh'],
            sumber_atmosfer=SUMBER_ATMOSFER,
        )

        hasil = calc.jalankan_perhitungan_lengkap(
            use_telescope=True,
            mode=CALC_MODE,
            F_naked=F_NAKED_REF,
            interval_menit=INTERVAL_MENIT,
            min_moon_alt=MIN_MOON_ALT,
            start_delay_menit=START_DELAY_MENIT,
            **TEL_PARAMS,
        )

        # Tanggal pengamatan yang dihitung model
        tgl_model = hasil.get('tanggal_pengamatan')
        if tgl_model:
            tgl_model_str = tgl_model.strftime('%Y-%m-%d')
        else:
            tgl_model_str = "?"

        # Jangan memakai hasil pada hari lain sebagai perbandingan observasi.
        tgl_cocok = (tgl_model_str == tanggal)
        sunset_local_dt = hasil.get('sunset_local')
        if not tgl_cocok or sunset_local_dt is None or sunset_local_dt.date().isoformat() != tanggal:
            raise ValueError(f'TANGGAL TIDAK COCOK: model={tgl_model_str}, observasi={tanggal}')
        tanggal_hisab = hasil.get('tanggal_hisab')
        tanggal_hisab_str = tanggal_hisab.date().isoformat() if tanggal_hisab else None
        offset_hari = hasil.get('delta_day_offset')
        if verbose:
            offset_label = f'H{offset_hari:+d}' if offset_hari is not None else 'H?'
            print(f'\n  Tanggal pengamatan: {tanggal} | Acuan H+0 WIB: {tanggal_hisab_str} | {offset_label}')
            if tanggal != obs['tanggal']:
                print(f"  Tanggal dataset asli {obs['tanggal']} di luar H-2..H+2; memakai ephemeris Hijriah.")

        # Ambil nilai datetime untuk parsing ke time
        optimal_time_ne_dt = hasil.get('optimal_time_ne') if CALC_MODE == "optimal" else None
        optimal_time_tel_dt = hasil.get('optimal_time_tel') if CALC_MODE == "optimal" else None

        # Kumpulkan hasil
        result = {
            # Metadata observasi
            'no': no,
            'nama': nama,
            'tanggal_obs': tanggal,
            'tanggal_model': tgl_model_str,
            'tanggal_cocok': tgl_cocok,
            'tanggal_hisab': tanggal_hisab_str,
            'delta_day_offset': offset_hari,
            'tanggal_dataset': obs['tanggal'],
            'sumber_tanggal': date_source,
            'h0_reference_timezone': H0_REFERENCE_TIMEZONE,
            'bulan_hijri': obs['bulan_hijri'],
            'tahun_hijri': obs['tahun_hijri'],
            'lat': obs['lat'],
            'lon': obs['lon'],
            'elv': obs['elv'],
            'observed': obs['observed'],
            'observation_method': obs.get('observation_method', OBSERVATION_METHOD),
            'observation_source': obs.get('observation_source', OBSERVATION_SOURCE),
            'comparison_scope': COMPARISON_SCOPE,
            'success': True,
            'sumber_atmosfer': hasil.get('sumber_atmosfer', SUMBER_ATMOSFER),
            'bias_t': hasil.get('bias_t', obs.get('bias_t', 0.0)),
            'bias_rh': hasil.get('bias_rh', obs.get('bias_rh', 0.0)),
            'atmosphere_provenance': hasil.get('atmosphere_provenance', []),

            # Hasil saat sunset
            'sunset_local': sunset_local_dt,
            'moon_alt_sunset': hasil.get('moon_alt', 0),
            'sun_alt_sunset': hasil.get('sun_alt', 0),
            'elongation': hasil.get('elongation', 0),
            'moon_width': hasil.get('moon_width', 0),
            'phase_angle': hasil.get('phase_angle', 0),
            'moon_semidiameter': hasil['moon_semidiameter'],
            'moon_distance_km': hasil['moon_distance_km'],
            'sky_brightness_nl': hasil.get('sky_brightness_nl', 0),
            'luminansi_hilal_nl': hasil.get('luminansi_hilal_nl', 0),
            'k_v': hasil.get('k_v', 0),
            'extinction_mag_v': hasil['extinction_mag_v'],
            'transmission_v': hasil['transmission_v'],
            'rh': hasil.get('rh', 0),
            'temperature': hasil.get('temperature', 0),
            'pressure': hasil.get('pressure'),
            'delta_m_ne_sunset': hasil.get('delta_m_ne', -99.0),
            'delta_m_tel_sunset': hasil.get('delta_m_tel', -99.0),
            'telescope_gain_sunset': hasil.get('telescope_gain', 0),
        }

        # Hasil optimal (jika mode optimal)
        if CALC_MODE == "optimal":
            # Ambil data astronomis dari result dict optimal
            opt_ne = hasil.get('optimal_result_ne') or {}
            opt_tel = hasil.get('optimal_result_tel') or {}

            result.update({
                'delta_m_ne_opt': hasil.get('optimal_delta_m_ne', -99.0),
                'delta_m_tel_opt': hasil.get('optimal_delta_m_tel', -99.0),
                'optimal_time_ne': optimal_time_ne_dt,
                'optimal_time_tel': optimal_time_tel_dt,
                'optimal_moon_alt_ne': hasil.get('optimal_moon_alt_ne', 0),
                'optimal_moon_alt_tel': hasil.get('optimal_moon_alt_tel', 0),
                'optimal_sun_alt_tel': hasil.get('optimal_sun_alt_tel', 0),
                'telescope_gain_opt': hasil.get('optimal_telescope_gain', 0),
                'vis_duration_ne': hasil.get('visibility_duration_ne', 0),
                'vis_duration_tel': hasil.get('visibility_duration_tel', 0),
                # Data astronomis optimal NE
                'opt_ne_elongation': opt_ne.get('elongation', 0),
                'opt_ne_moon_semidiameter': opt_ne.get('moon_semidiameter'),
                'opt_ne_moon_distance_km': opt_ne.get('moon_distance_km'),
                'opt_ne_sky_brightness_nl': opt_ne.get('sky_brightness_nl', 0),
                'opt_ne_luminansi_hilal_nl': opt_ne.get('luminansi_hilal_nl', 0),
                'opt_ne_k_v': opt_ne.get('k_v', 0),
                'opt_ne_extinction_mag_v': opt_ne.get('extinction_mag_v'),
                'opt_ne_transmission_v': opt_ne.get('transmission_v'),
                'opt_ne_rh': opt_ne.get('rh', 0),
                'opt_ne_temperature': opt_ne.get('temperature', 0),
                'opt_ne_pressure': opt_ne.get('pressure'),
                # Data astronomis optimal Teleskop
                'opt_tel_elongation': opt_tel.get('elongation', 0),
                'opt_tel_phase_angle': opt_tel.get('phase_angle'),
                'opt_tel_moon_semidiameter': opt_tel.get('moon_semidiameter'),
                'opt_tel_moon_distance_km': opt_tel.get('moon_distance_km'),
                'opt_tel_sky_brightness_nl': opt_tel.get('sky_brightness_nl', 0),
                'opt_tel_luminansi_hilal_nl': opt_tel.get('luminansi_hilal_nl', 0),
                'opt_tel_k_v': opt_tel.get('k_v', 0),
                'opt_tel_extinction_mag_v': opt_tel.get('extinction_mag_v'),
                'opt_tel_transmission_v': opt_tel.get('transmission_v'),
                'opt_tel_rh': opt_tel.get('rh', 0),
                'opt_tel_temperature': opt_tel.get('temperature', 0),
                'opt_tel_pressure': opt_tel.get('pressure'),
            })
        else:
            result.update({
                'delta_m_ne_opt': hasil.get('delta_m_ne', -99.0),
                'delta_m_tel_opt': hasil.get('delta_m_tel', -99.0),
                'optimal_time_ne': None,
                'optimal_time_tel': None,
                'optimal_moon_alt_ne': 0,
                'optimal_moon_alt_tel': 0,
                'optimal_sun_alt_tel': 0,
                'telescope_gain_opt': 0,
                'vis_duration_ne': 0,
                'vis_duration_tel': 0,
                'opt_ne_elongation': 0, 'opt_ne_sky_brightness_nl': 0,
                'opt_ne_luminansi_hilal_nl': 0, 'opt_ne_k_v': 0,
                'opt_ne_extinction_mag_v': None, 'opt_ne_transmission_v': None,
                'opt_ne_moon_semidiameter': None, 'opt_ne_moon_distance_km': None,
                'opt_ne_rh': 0, 'opt_ne_temperature': 0,
                'opt_ne_pressure': None,
                'opt_tel_elongation': 0, 'opt_tel_sky_brightness_nl': 0,
                'opt_tel_luminansi_hilal_nl': 0, 'opt_tel_k_v': 0,
                'opt_tel_extinction_mag_v': None, 'opt_tel_transmission_v': None,
                'opt_tel_phase_angle': None,
                'opt_tel_moon_semidiameter': None, 'opt_tel_moon_distance_km': None,
                'opt_tel_rh': 0, 'opt_tel_temperature': 0,
                'opt_tel_pressure': None,
            })

        opt_ne = hasil.get('optimal_result_ne') or {}
        opt_tel = hasil.get('optimal_result_tel') or {}
        result.update({
            'F_naked': hasil.get('F_naked'),
            'field_factor': (hasil.get('tel_params') or {}).get('field_factor'),
            **{key: hasil.get(key) for key in (
                'crumey_ne_regime', 'crumey_tel_regime',
                'crumey_ne_achromatic_extrapolation', 'crumey_tel_achromatic_extrapolation',
                'threshold_difference_mag', 'optimal_threshold_difference_mag', 'field_factor_comparison',
            )},
            'opt_ne_regime': opt_ne.get('crumey_ne_regime'),
            'opt_tel_regime': opt_tel.get('crumey_tel_regime'),
            'opt_ne_achromatic_extrapolation': opt_ne.get('crumey_ne_achromatic_extrapolation'),
            'opt_tel_achromatic_extrapolation': opt_tel.get('crumey_tel_achromatic_extrapolation'),
        })

        # Ringkasan cepat
        dm_ne = _comparison_margin(result, 'ne')
        dm_tel = _comparison_margin(result)
        pred_ne = _prediction(dm_ne) or '—'
        pred_tel = _prediction(dm_tel) or '—'
        obs_str = "Y" if obs['observed'] else "N"
        match_tel = ('✓' if pred_tel == obs_str else '✗') if dm_tel is not None else '—'

        if verbose:
            print(f"\n  RINGKASAN:")
            print(f"    Naked Eye : Δm={_display_margin(dm_ne)}  Pred={pred_ne}")
            print(f"    Teleskop  : Δm={_display_margin(dm_tel)}  Pred={pred_tel}  Obs={obs_str}  {match_tel}")

        return result

    except Exception as e:
        print(f"\n  ✗ ERROR pada obs #{no}: {e}")
        traceback.print_exc()
        return {
            'no': no,
            'nama': nama,
            'tanggal_obs': tanggal,
            'tanggal_dataset': obs['tanggal'],
            'sumber_tanggal': date_source if 'date_source' in locals() else None,
            'h0_reference_timezone': H0_REFERENCE_TIMEZONE,
            'tanggal_model': (calc.hasil['tanggal_pengamatan'].date().isoformat()
                              if 'calc' in locals() and calc.hasil.get('tanggal_pengamatan') else '?'),
            'tanggal_hisab': (calc.hasil['tanggal_hisab'].date().isoformat()
                              if 'calc' in locals() and calc.hasil.get('tanggal_hisab') else None),
            'delta_day_offset': calc.hasil.get('delta_day_offset') if 'calc' in locals() else None,
            'tanggal_cocok': False,
            'bulan_hijri': obs['bulan_hijri'],
            'tahun_hijri': obs['tahun_hijri'],
            'lat': obs['lat'],
            'lon': obs['lon'],
            'elv': obs['elv'],
            'observed': obs['observed'],
            'observation_method': obs.get('observation_method', OBSERVATION_METHOD),
            'observation_source': obs.get('observation_source', OBSERVATION_SOURCE),
            'comparison_scope': COMPARISON_SCOPE,
            'success': False,
            'sunset_local': None,
            'optimal_time_ne': None,
            'optimal_time_tel': None,
            'delta_m_ne_sunset': -99.0,
            'delta_m_tel_sunset': -99.0,
            'delta_m_ne_opt': -99.0,
            'delta_m_tel_opt': -99.0,
            'error': str(e),
            'sumber_atmosfer': SUMBER_ATMOSFER,
            'bias_t': obs['bias_t'], 'bias_rh': obs['bias_rh'],
            'atmosphere_provenance': calc.hasil.get('atmosphere_provenance', []) if 'calc' in locals() else [],
        }


def run_batch(bias_mode: str = '2', manual_bias_t: float = 0.0, manual_bias_rh: float = 0.0) -> List[dict]:
    """Jalankan model untuk semua observasi."""
    print("\n" + "█" * 70)
    print("  PERBANDINGAN DESKRIPTIF: Model visual Crumey vs label CCD BMKG")
    print("  Label CCD tidak mengkalibrasi threshold penglihatan manusia.")
    n_tanggal = len({entry[1] for entry in OBSERVATIONS})
    print(f"  {N_OBS} data observasi pada {n_tanggal} tanggal pengamatan")
    print(f"  Mode: {CALC_MODE}  |  Atmosfer: {SUMBER_ATMOSFER}")
    print('  Acuan H+0: tanggal ijtima WIB (00:00 Asia/Jakarta), sama untuk semua lokasi')
    print('  Waktu pengamatan: sunset dalam zona waktu lokal masing-masing lokasi')
    if SUMBER_ATMOSFER == 'ecmwf_ifs':
        print(f"  Produk: {IFS_PRODUCT_NAME}")
        print(f"  API: {ARCHIVE_URL}")
    print(f"  F_naked_ref={F_NAKED_REF}  |  F_tel_ref={FIELD_FACTOR_REF}")
    if bias_mode == '2':
        print("  Koreksi Bias: Tanpa koreksi (bias = 0)")
    elif bias_mode == '3':
        print(f"  Koreksi Bias: Manual Seragam (T={manual_bias_t:+.1f}°C, RH={manual_bias_rh:+.1f}%)")
    else:
        print("  Koreksi Bias: Data Bawaan Lokasi")
    print("█" * 70)

    results = []
    t_start = time.time()

    for seq_no, entry in enumerate(OBSERVATIONS, start=1):
        obs = parse_obs(entry)
        obs['no'] = seq_no
        
        # Terapkan opsi bias
        if bias_mode == '2':
            obs['bias_t'] = 0.0
            obs['bias_rh'] = 0.0
        elif bias_mode == '3':
            obs['bias_t'] = manual_bias_t
            obs['bias_rh'] = manual_bias_rh

        t_obs_start = time.time()
        result = run_single_observation(obs)
        elapsed = time.time() - t_obs_start
        result['elapsed_sec'] = elapsed
        results.append(result)
        print(f"  ⏱ Waktu: {elapsed:.1f} detik")

    total_time = time.time() - t_start
    n_success = sum(1 for r in results if r.get('success', False))
    print(f"\n{'═' * 70}")
    print(f"BATCH SELESAI: {n_success}/{N_OBS} berhasil dalam {total_time:.0f} detik")
    print(f"{'═' * 70}")

    return results


# ═══════════════════════════════════════════════════════════════════
# TABEL RINGKASAN
# ═══════════════════════════════════════════════════════════════════

def print_results_table(results: List[dict]):
    """Cetak tabel ringkasan hasil."""
    print(f"\n{'═' * 120}")
    print(f"TABEL HASIL OBSERVASI (F_naked={F_NAKED_REF:.1f}, F_tel={FIELD_FACTOR_REF:.1f})")
    print(f"{'═' * 120}")
    hdr = (f"{'No':>3} {'Tanggal':>10} {'Lokasi':<35} "
           f"{'Obs':>3} {'Moon°':>6} {'Elong°':>6} {'Lebar':>6} "
           f"{'Δm_NE':>8} {'Pr_NE':>5} "
           f"{'Δm_Tel':>8} {'Pr_Tel':>6} {'Match':>5}")
    print(hdr)
    print("─" * 120)

    for r in results:
        if not r.get('success'):
            print(f"{r['no']:>3} {r['tanggal_obs']:>10} {r['nama']:<35} "
                  f"{'?' :>3} {'?':>6} {'?':>6} {'?':>6} {'ERROR':>8} {'?':>5} "
                  f"{'ERROR':>8} {'?':>6} {'?':>5}")
            continue

        obs_str = "Y" if r['observed'] else "N"
        dm_ne = _comparison_margin(r, 'ne')
        dm_tel = _comparison_margin(r)
        pred_ne = _prediction(dm_ne) or '—'
        pred_tel = _prediction(dm_tel) or '—'
        # Cocok jika prediksi teleskop sesuai observasi
        match = ('✓' if pred_tel == obs_str else '✗') if dm_tel is not None else '—'
        moon_alt = r.get('moon_alt_sunset', 0)
        elong = r.get('elongation', 0)
        moon_width_arcmin = r.get('moon_width', 0) * 60.0

        print(f"{r['no']:>3} {r['tanggal_obs']:>10} {r['nama']:<35} "
              f"{obs_str:>3} {moon_alt:>6.2f} {elong:>6.2f} {moon_width_arcmin:>6.2f} "
              f"{_display_margin(dm_ne):>8} {pred_ne:>5} "
              f"{_display_margin(dm_tel):>8} {pred_tel:>6} {match:>5}")

    print("─" * 120)

    # Cross-method agreement only; digital detection is not visual detection.
    valid = [r for r in results if _comparison_prediction(r) is not None]
    if valid:
        n_match_tel = sum(1 for r in valid if _comparison_prediction(r) == ('Y' if r['observed'] else 'N'))
        print(f"\n  Kesesuaian model visual vs label CCD (deskriptif): "
              f"{n_match_tel}/{len(valid)} ({n_match_tel/len(valid):.1%})")


# ═══════════════════════════════════════════════════════════════════
# EXCEL OUTPUT
# ═══════════════════════════════════════════════════════════════════

def _display_margin(value):
    return f'{value:+.3f}' if value is not None else '—'


def _export_round(value, digits=4, scale=1.0):
    """Missing numbers stay empty; infinite model margins stay explicit."""
    if value is None:
        return None
    value = float(value) * scale
    if math.isnan(value):
        return None
    if not math.isfinite(value):
        return str(value)
    return round(value, digits)


def _export_scientific(value):
    if value is None or math.isnan(float(value)):
        return None
    return f"{float(value):.4e}"


def _export_duration(value):
    if value is None or not math.isfinite(float(value)):
        return None
    return int(round(float(value)))


def _prediction(value):
    """None/NaN is unavailable, whereas a genuine -inf margin means N."""
    if value is None or math.isnan(float(value)):
        return None
    return 'Y' if float(value) > 0 else 'N'


def _comparison_margin(result, method='tel'):
    if not result.get('success'):
        return None
    if CALC_MODE == 'optimal':
        if not result.get('optimal_time_' + method):
            return None
        margin = result.get('delta_m_' + method + '_opt')
    else:
        margin = result.get('delta_m_' + method + '_sunset')
    return margin if _prediction(margin) is not None else None


def _comparison_prediction(result):
    return _prediction(_comparison_margin(result))


def save_to_excel(results: List[dict], filepath: str, bias_mode_str: str = "Tanpa koreksi (bias = 0)"):
    """Simpan semua hasil ke file Excel dengan format rapi 2-baris header."""
    from datetime import time as dt_time
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.styles.colors import Color
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    # ── Styles ──
    thin_border = Border(
        left=Side('thin'), right=Side('thin'),
        top=Side('thin'), bottom=Side('thin'))
    thin_border_no_top = Border(
        left=Side('thin'), right=Side('thin'),
        bottom=Side('thin'))

    hdr_font = Font(name='Times New Roman', bold=True, size=11,
                    color=Color(theme=1))
    data_font = Font(name='Times New Roman', size=10)
    center = Alignment(horizontal='center', vertical='center')
    center_no_v = Alignment(horizontal='center')
    left_align = Alignment(horizontal='left', vertical='center')

    # Header fills (warna grup)
    meta_fill = PatternFill('solid', fgColor='0070C0')
    sunset_fill = PatternFill('solid',
                              fgColor=Color(theme=9, tint=-0.249977111117893))
    opt_ne_fill = PatternFill('solid',
                              fgColor=Color(theme=7, tint=-0.249977111117893))
    tel_fill = PatternFill('solid',
                           fgColor=Color(theme=6, tint=-0.249977111117893))

    # Data fills (warna muda untuk kolom Δm & prediksi)
    sunset_data_fill = PatternFill('solid',
                                   fgColor=Color(theme=9, tint=0.3999755851924192))
    opt_ne_data_fill = PatternFill('solid',
                                   fgColor=Color(theme=7, tint=0.3999755851924192))
    tel_data_fill = PatternFill('solid',
                                fgColor=Color(theme=6, tint=0.3999755851924192))

    green_fill = PatternFill('solid', fgColor='C6EFCE')
    red_fill = PatternFill('solid', fgColor='FFC7CE')

    # Ringkasan styles (tetap Arial)
    ringkasan_hdr_font = Font(name='Arial', bold=True, size=11, color='FFFFFF')
    ringkasan_hdr_fill = PatternFill('solid', fgColor='1F4E79')
    ringkasan_data_font = Font(name='Arial', size=10)
    ringkasan_border = Border(
        left=Side('thin', 'B0B0B0'), right=Side('thin', 'B0B0B0'),
        top=Side('thin', 'B0B0B0'), bottom=Side('thin', 'B0B0B0'))

    # ═══ Sheet 1: Hasil Observasi ═══
    ws = wb.active
    ws.title = "Hasil Observasi"

    # ── Row 1: Header grup (merged) + metadata kolom (merged 2 baris) ──
    meta_headers = ['No', 'Tanggal', 'Lokasi', 'Lat', 'Lon', 'Elv',
                    'Bulan Hijri', 'Time Zone']
    for ci, h in enumerate(meta_headers, 1):
        col_letter = get_column_letter(ci)
        ws.merge_cells(f'{col_letter}1:{col_letter}2')
        c = ws.cell(row=1, column=ci, value=h)
        c.font = hdr_font
        c.fill = meta_fill
        c.alignment = center
        c.border = thin_border

    # Grup: Sunset (I1:W1)
    ws.merge_cells('I1:W1')
    c = ws.cell(row=1, column=9,
                value='DATA VISIBILITAS HILAL NAKED EYE DAN TELESKOP SAAT SUNSET')
    c.font = hdr_font; c.fill = sunset_fill
    c.alignment = center_no_v; c.border = thin_border

    # Grup: Optimal NE (X1:AG1)
    ws.merge_cells('X1:AG1')
    c = ws.cell(row=1, column=24,
                value='DATA VISIBILITAS HILAL NAKED EYE WAKTU OPTIMAL ATAU BEST TIME')
    c.font = hdr_font; c.fill = opt_ne_fill
    c.alignment = center_no_v; c.border = thin_border

    # Grup: Teleskop (AH1:AV1)
    ws.merge_cells('AH1:AV1')
    c = ws.cell(row=1, column=34,
                value='DATA VISIBILITAS HILAL BERBANTUAN TELESKOP BEST TIME')
    c.font = hdr_font; c.fill = tel_fill
    c.alignment = center_no_v; c.border = thin_border

    # ── Row 2: Sub-header kolom per grup ──
    # Diagnostik atmosfer disimpan di kolom tambahan agar layout lama tetap terbaca.
    ws.merge_cells('AW1:BB1')
    c = ws.cell(row=1, column=49, value='EKSTINGSI LOS DAN TRANSMISI ATMOSFER')
    c.font = hdr_font; c.fill = sunset_fill
    c.alignment = center_no_v; c.border = thin_border
    diagnostic_columns = (
        ('extinction_mag_v', 'extinction_mag_v Sunset (mag)'),
        ('transmission_v', 'transmission_v Sunset'),
        ('opt_ne_extinction_mag_v', 'extinction_mag_v NE Optimal (mag)'),
        ('opt_ne_transmission_v', 'transmission_v NE Optimal'),
        ('opt_tel_extinction_mag_v', 'extinction_mag_v Tel Optimal (mag)'),
        ('opt_tel_transmission_v', 'transmission_v Tel Optimal'),
    )
    for ci, (_, label) in enumerate(diagnostic_columns, 49):
        c = ws.cell(row=2, column=ci, value=label)
        c.font = hdr_font; c.fill = sunset_fill
        c.alignment = center; c.border = thin_border
        ws.column_dimensions[get_column_letter(ci)].width = 24

    ws.merge_cells('BC1:BE1')
    c = ws.cell(row=1, column=55, value='SEMIDIAMETER TOPOSENTRIK BULAN (DE440s)')
    c.font = hdr_font; c.fill = sunset_fill
    c.alignment = center_no_v; c.border = thin_border
    geometry_columns = (
        ('moon_semidiameter', 'Semidiameter Sunset (deg)'),
        ('opt_ne_moon_semidiameter', 'Semidiameter NE Optimal (deg)'),
        ('opt_tel_moon_semidiameter', 'Semidiameter Tel Optimal (deg)'),
    )
    for ci, (_, label) in enumerate(geometry_columns, 55):
        c = ws.cell(row=2, column=ci, value=label)
        c.font = hdr_font; c.fill = sunset_fill
        c.alignment = center; c.border = thin_border
        ws.column_dimensions[get_column_letter(ci)].width = 24

    ws.merge_cells('BF1:BH1')
    c = ws.cell(row=1, column=58, value='TEKANAN UDARA PERMUKAAN (hPa)')
    c.font = hdr_font; c.fill = sunset_fill
    c.alignment = center_no_v; c.border = thin_border
    pressure_columns = (
        ('pressure', 'P_Sunset (hPa)'),
        ('opt_ne_pressure', 'P_NE_Optimal (hPa)'),
        ('opt_tel_pressure', 'P_Tel_Optimal (hPa)'),
    )
    for ci, (_, label) in enumerate(pressure_columns, 58):
        c = ws.cell(row=2, column=ci, value=label)
        c.font = hdr_font; c.fill = sunset_fill
        c.alignment = center; c.border = thin_border
        ws.column_dimensions[get_column_letter(ci)].width = 24

    # Sunset (I-W)
    sunset_hdrs = {
        9: 'Sunset Lokal', 10: 'Moon Alt (\u00b0)', 11: 'Sun Alt (\u00b0)',
        12: 'Elongasi (\u00b0)',
        13: 'Lebar Sabit (arcmin)', 14: 'Phase Angle (\u00b0)',
        15: 'Sky Bright (nL)', 16: 'Lum Hilal (nL)',
        17: 'k_v (mag/airmass)', 18: 'RH (%)', 19: 'T (\u00b0C)',
    }
    for ci, h in sunset_hdrs.items():
        c = ws.cell(row=2, column=ci, value=h)
        c.font = hdr_font; c.fill = sunset_fill
        c.alignment = center; c.border = thin_border

    # Δm NE sunset (T2:U2)
    ws.merge_cells('T2:U2')
    c = ws.cell(row=2, column=20, value='\u0394m NE')
    c.font = hdr_font; c.fill = sunset_fill
    c.alignment = center; c.border = thin_border

    # Δm Tel sunset (V2:W2)
    ws.merge_cells('V2:W2')
    c = ws.cell(row=2, column=22, value='\u0394m Tel ')
    c.font = hdr_font; c.fill = sunset_fill
    c.alignment = center; c.border = thin_border

    # Optimal NE (X-AG)
    opt_ne_hdrs = {
        24: 'Best Time NE', 25: 'Moon Alt (\u00b0)', 26: 'Elongasi (\u00b0)',
        27: 'Sky Bright (nL)', 28: 'Lum Hilal (nL)',
        29: 'k_v (mag/airmass)', 30: 'RH (%)', 31: 'T (\u00b0C)',
    }
    for ci, h in opt_ne_hdrs.items():
        c = ws.cell(row=2, column=ci, value=h)
        c.font = hdr_font; c.fill = opt_ne_fill
        c.alignment = center; c.border = thin_border

    # Δm NE optimal (AF2:AG2)
    ws.merge_cells('AF2:AG2')
    c = ws.cell(row=2, column=32, value='\u0394m NE')
    c.font = hdr_font; c.fill = opt_ne_fill
    c.alignment = center; c.border = thin_border

    # Teleskop (AH-AV)
    tel_hdrs = {
        34: 'Best Time Tel', 35: 'Moon Alt (\u00b0)', 36: 'Sun Alt (\u00b0)',
        37: 'Elongasi (\u00b0)',
        38: 'Sky Bright (nL)', 39: 'Lum Hilal (nL)',
        40: 'k_v (mag/airmass)', 41: 'RH (%)', 42: 'T (\u00b0C)',
        43: 'Selisih Threshold Opt', 44: 'Leg time (mnt)',
        47: 'Observasi Tel', 48: 'Correct',
    }
    for ci, h in tel_hdrs.items():
        c = ws.cell(row=2, column=ci, value=h)
        c.font = hdr_font; c.fill = tel_fill
        c.alignment = center; c.border = thin_border

    # Δm Tel teleskop (AS2:AT2)
    ws.merge_cells('AS2:AT2')
    c = ws.cell(row=2, column=45, value='\u0394m Tel')
    c.font = hdr_font; c.fill = tel_fill
    c.alignment = center; c.border = thin_border

    # ── Helper functions ──
    def _parse_time(time_val):
        """Parse waktu (datetime, string, atau datetime.time) ke datetime.time."""
        if not time_val:
            return None
        try:
            # Jika sudah datetime.time, return langsung
            if isinstance(time_val, dt_time):
                return time_val
            # Jika datetime object, ambil bagian time
            if hasattr(time_val, 'hour') and hasattr(time_val, 'minute') and hasattr(time_val, 'second'):
                return dt_time(time_val.hour, time_val.minute, time_val.second)
            # Jika string, parse seperti sebelumnya
            s = str(time_val).strip()
            if ' ' in s:
                time_part = s.split(' ')[1].split('+')[0].split('-')[0]
            else:
                time_part = s
            parts = time_part.split(':')
            return dt_time(int(parts[0]), int(parts[1]),
                           round(float(parts[2])) if len(parts) > 2 else 0)
        except Exception:
            return None

    def _tz_offset(lon):
        """UTC offset zona waktu Indonesia dari bujur."""
        if lon < 115:
            return 7   # WIB
        elif lon < 135:
            return 8   # WITA
        return 9       # WIT

    # ── Data rows (mulai baris 3) ──
    # Kolom yang diberi warna Δm data
    SUNSET_DM_COLS = {20, 21, 22, 23}
    OPT_NE_DM_COLS = {32, 33}
    TEL_DM_COLS = {45, 46, 47}

    for i, r in enumerate(results, 3):
        obs_str = "Y" if r['observed'] else "N"
        dm_ne_sun = r.get('delta_m_ne_sunset')
        dm_tel_sun = r.get('delta_m_tel_sunset')
        dm_ne_opt = r.get('delta_m_ne_opt')
        dm_tel_opt = r.get('delta_m_tel_opt')
        pred_ne_sun = _prediction(dm_ne_sun)
        pred_tel_sun = _prediction(dm_tel_sun)
        has_opt_ne = r.get('success') and bool(r.get('optimal_time_ne'))
        has_opt_tel = r.get('success') and bool(r.get('optimal_time_tel'))
        pred_ne_opt = _prediction(dm_ne_opt) if has_opt_ne else None
        pred_tel_opt = _prediction(dm_tel_opt) if has_opt_tel else None
        comparison = _comparison_prediction(r)
        cocok = ("\u2713" if comparison == obs_str else "\u2717") if comparison is not None else None

        row_data = {
            # Metadata (A-H)
            1: r['no'],
            2: r['tanggal_obs'],
            3: r['nama'],
            4: r.get('lat', 0),
            5: r.get('lon', 0),
            6: r.get('elv', 0),
            7: f"{r.get('bulan_hijri', 0)}/{r.get('tahun_hijri', 0)}",
            8: _tz_offset(r.get('lon', 0)),
            # Sunset (I-W)
            9: _parse_time(r.get('sunset_local', '')),
            10: _export_round(r.get('moon_alt_sunset'), 4),
            11: _export_round(r.get('sun_alt_sunset'), 4),
            12: _export_round(r.get('elongation'), 4),
            13: _export_round(r.get('moon_width'), scale=60.0),
            14: _export_round(r.get('phase_angle'), 4),
            15: _export_scientific(r.get('sky_brightness_nl')),
            16: _export_scientific(r.get('luminansi_hilal_nl')),
            17: _export_round(r.get('k_v'), 4),
            18: _export_round(r.get('rh'), 2),
            19: _export_round(r.get('temperature'), 2),
            20: _export_round(dm_ne_sun),
            21: pred_ne_sun,
            22: _export_round(dm_tel_sun),
            23: pred_tel_sun,
            # Optimal NE (X-AG)
            24: _parse_time(r.get('optimal_time_ne', '')),
            25: _export_round(r.get('optimal_moon_alt_ne'), 4),
            26: _export_round(r.get('opt_ne_elongation'), 4),
            27: _export_scientific(r.get('opt_ne_sky_brightness_nl')),
            28: _export_scientific(r.get('opt_ne_luminansi_hilal_nl')),
            29: _export_round(r.get('opt_ne_k_v'), 4),
            30: _export_round(r.get('opt_ne_rh'), 2),
            31: _export_round(r.get('opt_ne_temperature'), 2),
            32: _export_round(dm_ne_opt),
            33: pred_ne_opt,
            # Teleskop (AH-AV)
            34: _parse_time(r.get('optimal_time_tel', '')),
            35: _export_round(r.get('optimal_moon_alt_tel'), 4),
            36: _export_round(r.get('optimal_sun_alt_tel'), 4),
            37: _export_round(r.get('opt_tel_elongation'), 4),
            38: _export_scientific(r.get('opt_tel_sky_brightness_nl')),
            39: _export_scientific(r.get('opt_tel_luminansi_hilal_nl')),
            40: _export_round(r.get('opt_tel_k_v'), 4),
            41: _export_round(r.get('opt_tel_rh'), 2),
            42: _export_round(r.get('opt_tel_temperature'), 2),
            43: _export_round(r.get('telescope_gain_opt'), 4),
            44: _export_duration(r.get('vis_duration_tel')),
            45: _export_round(dm_tel_opt),
            46: pred_tel_opt,
            47: obs_str,
            48: cocok,
        }
        for ci, (key, _) in enumerate(diagnostic_columns, 49):
            value = r.get(key) if r.get('success') else None
            row_data[ci] = value if value is None or math.isfinite(value) else str(value)
        for ci, (key, _) in enumerate(geometry_columns, 55):
            row_data[ci] = r.get(key) if r.get('success') else None
        for ci, (key, _) in enumerate(pressure_columns, 58):
            row_data[ci] = r.get(key) if r.get('success') else None

        if not has_opt_ne:
            for ci in (*range(24, 34), 51, 52, 56, 59):
                row_data[ci] = None
        if not has_opt_tel:
            for ci in (*range(34, 47), 53, 54, 57, 60):
                row_data[ci] = None

        if not r.get('success'):
            for ci in range(9, 47):
                row_data[ci] = None
            row_data[48] = 'ERROR'

        for ci, val in row_data.items():
            if isinstance(val, float) and not math.isfinite(val):
                val = str(val)
            c = ws.cell(row=i, column=ci, value=val)
            c.font = data_font
            c.alignment = left_align if ci == 3 else center
            c.border = thin_border_no_top

            # Format waktu
            if ci in (9, 24, 34) and isinstance(val, dt_time):
                c.number_format = 'h:mm:ss'
            if ci in (58, 59, 60):
                c.number_format = '0.00'

            # Warna Δm data
            if ci in SUNSET_DM_COLS:
                c.fill = sunset_data_fill
            elif ci in OPT_NE_DM_COLS:
                c.fill = opt_ne_data_fill
            elif ci in TEL_DM_COLS:
                c.fill = tel_data_fill

            # Kolom Correct
            if ci == 48:
                if row_data[48] == "\u2713":
                    c.fill = green_fill
                elif row_data[48] in ("\u2717", 'ERROR'):
                    c.fill = red_fill

    # ── Column widths ──
    col_widths = {
        'A': 4, 'B': 12, 'C': 30, 'D': 11, 'E': 12, 'F': 7,
        'G': 13, 'H': 7.57,
        'I': 14.29, 'J': 12.71, 'K': 12.71, 'L': 14, 'M': 17,
        'N': 17, 'O': 13, 'P': 16, 'Q': 8, 'R': 13, 'S': 13,
        'T': 9.29, 'U': 4, 'V': 9.29, 'W': 4.43,
        'X': 14.57, 'Y': 12.86, 'Z': 11.86, 'AA': 15.71, 'AB': 15,
        'AC': 8.29, 'AD': 9.14, 'AE': 7.57, 'AF': 9, 'AG': 3.86,
        'AH': 14.71, 'AI': 12.86, 'AJ': 12.71, 'AK': 11.86,
        'AL': 15.71, 'AM': 15, 'AN': 7.29, 'AO': 9, 'AP': 7.43,
        'AQ': 13.29, 'AR': 15.14, 'AS': 8.43, 'AT': 4.29,
        'AU': 14.43, 'AV': 8.29,
    }
    for col, width in col_widths.items():
        ws.column_dimensions[col].width = width

    ws.freeze_panes = 'A3'

    # ═══ Sheet 2: Ringkasan ═══
    ws2 = wb.create_sheet("Ringkasan")
    ws2.sheet_properties.tabColor = 'BF8F00'
    ws2.column_dimensions['A'].width = 35
    ws2.column_dimensions['B'].width = 25

    valid = [r for r in results if r.get('success', False)]
    comparable = [r for r in valid if _comparison_prediction(r) is not None]
    n_match_tel = sum(1 for r in comparable
                      if _comparison_prediction(r) == ('Y' if r['observed'] else 'N'))

    summary_data = [
        ("KONFIGURASI", ""),
        ("Acuan Tanggal", "Tanggal ijtima WIB dari ephemeris bulan/tahun Hijriah; tanggal dataset dalam H-2..H+2 menentukan offset"),
        ("Definisi H+0", "Tanggal kalender ijtima WIB, dengan awal hari 00:00 WIB; sama untuk semua lokasi"),
        ("Zona Acuan H+0", H0_REFERENCE_TIMEZONE),
        ("Tanggal Dataset di Luar Acuan", "Memakai H+0 ephemeris; tanggal dataset asli dicatat pada sheet Tanggal Pengamatan"),
        ("Metode Label Observasi", OBSERVATION_METHOD),
        ("Sumber Label Observasi", OBSERVATION_SOURCE),
        ("Cakupan Perbandingan", "Lintas-metode/deskriptif; bukan validasi visual"),
        ("Metadata Alat/Jam Aktual", "Tidak tersedia; model memakai konfigurasi referensi"),
        ("Mode Perhitungan", CALC_MODE),
        ("Sumber Atmosfer", SUMBER_ATMOSFER),
        ("Produk IFS", IFS_PRODUCT_NAME if SUMBER_ATMOSFER == 'ecmwf_ifs' else 'N/A'),
        ("Model API IFS", IFS_MODEL if SUMBER_ATMOSFER == 'ecmwf_ifs' else 'N/A'),
        ("Endpoint IFS", ARCHIVE_URL if SUMBER_ATMOSFER == 'ecmwf_ifs' else 'N/A'),
        ("Ekstingsi LOS / A_V", "extinction_mag_v = DM[2] [mag]"),
        ("Transmisi Atmosfer / T_V", "transmission_v = 10^(-0.4 A_V)"),
        ("Definisi Luminansi Hilal", "Direct/excess luminance setelah atmosfer [nL]"),
        ("Kontras Objek", "C_obj = L_obj / B_sky"),
        ("Semidiameter Bulan", "asin(1737.4 km / jarak astrometrik toposentrik DE440s)"),
        ("Sudut Fase Bulan", "phase_angle(Sun) native Skyfield pada posisi astrometrik"),
        ("Lebar Sabit", "W = 2 r k; k = fraksi iluminasi astrometrik"),
        ("Koreksi Bias", bias_mode_str),
        ("F Naked Eye", F_NAKED_REF),
        ("F Teleskop", FIELD_FACTOR_REF),
        ("Kontrak F", "Residual laboratory/observer/target/viewing; atmosfer, throughput, M dan FT/FM terpisah"),
        ("Selisih Threshold", "2.5 log10(C_th,NE/C_th,tel); mencakup perubahan F jika berbeda. Tel_Gain adalah alias lama."),
        ("Regime", "Latar aktual NE atau latar apparent teleskop; mesopic/photopic adalah extrapolasi achromatic"),
        ("Aperture Teleskop (mm)", TEL_PARAMS['aperture']),
        ("Magnifikasi", TEL_PARAMS['magnification']),
        ("Transmisi/permukaan", TEL_PARAMS['transmission']),
        ("Jumlah permukaan", TEL_PARAMS['n_surfaces']),
        ("", ""),
        ("HASIL VALIDASI", ""),
        ("Total Observasi", len(results)),
        ("Observasi Berhasil", len(valid)),
        ("Teleskop Dapat Dibandingkan", len(comparable)),
        ("Tanpa Hasil Perbandingan Teleskop", len(valid) - len(comparable)),
        ("Observasi Terlihat (Y)", sum(1 for r in results if r['observed'])),
        ("Observasi Tidak Terlihat (N)",
         sum(1 for r in results if not r['observed'])),
        ("", ""),
        ("KESESUAIAN MODEL VISUAL vs LABEL CCD (DESKRIPTIF)", ""),
        ("Kecocokan Teleskop",
         f"{n_match_tel}/{len(comparable)} ({n_match_tel/len(comparable):.1%})"
         if comparable else "N/A"),
    ]

    for i, (label, val) in enumerate(summary_data, 1):
        cl = ws2.cell(row=i, column=1, value=label)
        cv = ws2.cell(row=i, column=2, value=val)
        if label and not val and val != 0:
            cl.font = ringkasan_hdr_font
            cl.fill = ringkasan_hdr_fill
            cv.fill = ringkasan_hdr_fill
        else:
            cl.font = ringkasan_data_font
            cv.font = ringkasan_data_font
        cl.border = ringkasan_border
        cv.border = ringkasan_border

    visual = wb.create_sheet('Diagnostik Visual')
    visual.append(['No', 'Lokasi', *[label for label, _ in VISUAL_DIAGNOSTIC_COLUMNS]])
    for result in results:
        visual.append([result.get('no'), result.get('nama'), *_visual_diagnostic_values(result)])
    visual.freeze_panes = 'C2'
    visual.auto_filter.ref = visual.dimensions
    for cell in visual[1]:
        cell.font = hdr_font
        cell.fill = tel_fill
        cell.alignment = Alignment(wrap_text=True, vertical='center')
        visual.column_dimensions[cell.column_letter].width = 28
    visual.row_dimensions[1].height = 48

    dates = wb.create_sheet('Tanggal Pengamatan')
    dates.append(['No', 'Lokasi', 'Tanggal observasi', 'Tanggal model',
                  'Acuan H+0 WIB', 'Offset hari', 'Tanggal cocok', 'Tanggal dataset asli', 'Sumber tanggal', 'Zona acuan H+0'])
    for result in results:
        dates.append([result.get('no'), result.get('nama'), result.get('tanggal_obs'),
                      *[result.get(key) for _, key in DATE_DIAGNOSTIC_COLUMNS]])
    dates.freeze_panes = 'C2'
    dates.auto_filter.ref = dates.dimensions
    for cell in dates[1]:
        cell.font = ringkasan_hdr_font
        cell.fill = meta_fill
        cell.alignment = Alignment(wrap_text=True, vertical='center')
        dates.column_dimensions[cell.column_letter].width = 18
    dates.column_dimensions['A'].width = 8
    dates.column_dimensions['B'].width = 50
    dates.column_dimensions['H'].width = 24
    dates.column_dimensions['I'].width = 45
    dates.column_dimensions['J'].width = 24
    dates.row_dimensions[1].height = 32

    # Save
    out_dir = os.path.dirname(filepath)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    wb.save(filepath)
    _save_batch_atmosphere_provenance(results, filepath)
    print(f"\n  \u2713 Excel disimpan: {filepath}")


# ═══════════════════════════════════════════════════════════════════
# CSV OUTPUT
# ═══════════════════════════════════════════════════════════════════

def _save_batch_atmosphere_provenance(results, filepath):
    save_atmosphere_provenance(filepath, [
        atmosphere_audit_record(
            r.get('nama', ''), r.get('sumber_atmosfer', SUMBER_ATMOSFER),
            r.get('success', False), r, r.get('error'),
        ) | {
            'observation_date': r.get('tanggal_obs'),
            'model_date': r.get('tanggal_model'),
            'hisab_reference_date': r.get('tanggal_hisab'),
            'offset_days': r.get('delta_day_offset'),
            'dates_match': r.get('tanggal_cocok'),
            'original_dataset_date': r.get('tanggal_dataset'),
            'date_source': r.get('sumber_tanggal'),
            'h0_reference_timezone': r.get('h0_reference_timezone', H0_REFERENCE_TIMEZONE),
        } for r in results
    ])


def save_to_csv(results: List[dict], filepath: str):
    """Simpan hasil ke file CSV dengan format flat yang mudah dibaca program.

    Kolom: No, Tanggal, Lokasi, Lat, Lon, Elv, Bulan_Hijri,
           sun_alt_sunset, Moon_Alt_Sunset, Elongasi_Sunset,
           W_arcmin, Phase_Angle, Sky_Bright_Sunset, Lum_Hilal_Sunset,
           kV_Sunset, RH_Sunset, T_Sunset, Dm_NE_Sunset, Dm_Tel_Sunset,
           Best_Time_Tel, sun_alt_BT, Moon_Alt_BT, Elongasi_BT,
           Sky_Bright_BT, Lum_Hilal_BT, kV_BT, RH_BT, T_BT,
           Tel_Gain, Leg_Time_min, Dm_Tel_BT, Prediksi, Observasi

    Diagnostik tambahan: extinction_mag_v dan transmission_v untuk sunset,
    best time teleskop, serta kV_NE_Optimal/extinction_mag_v_NE_Optimal/
    transmission_v_NE_Optimal untuk best time naked eye.
    Geometri: moon_semidiameter_deg_* dan moon_distance_km_* untuk ketiga
    waktu pengamatan; Phase_Angle_BT untuk analisis source pada best time.
    Tekanan permukaan: P_Sunset, P_NE_Optimal, P_Tel_Optimal dalam hPa;
    kolom kosong jika tekanan/waktu optimal tidak tersedia atau observasi gagal.
    """
    headers = [
        'No', 'Tanggal', 'Lokasi', 'Lat', 'Lon', 'Elv', 'Bulan_Hijri',
        'sun_alt_sunset', 'Moon_Alt_Sunset', 'Elongasi_Sunset',
        'W_arcmin', 'Phase_Angle', 'Sky_Bright_Sunset', 'Lum_Hilal_Sunset',
        'kV_Sunset', 'RH_Sunset', 'T_Sunset', 'Dm_NE_Sunset', 'Dm_Tel_Sunset',
        'Best_Time_Tel', 'sun_alt_BT', 'Moon_Alt_BT', 'Elongasi_BT',
        'Sky_Bright_BT', 'Lum_Hilal_BT', 'kV_BT', 'RH_BT', 'T_BT',
        'Tel_Gain', 'Leg_Time_min', 'Dm_Tel_BT', 'Prediksi', 'Observasi',
        'extinction_mag_v_Sunset', 'transmission_v_Sunset',
        'extinction_mag_v_BT', 'transmission_v_BT',
        'kV_NE_Optimal', 'extinction_mag_v_NE_Optimal', 'transmission_v_NE_Optimal',
        'moon_semidiameter_deg_Sunset', 'moon_distance_km_Sunset',
        'moon_semidiameter_deg_BT', 'moon_distance_km_BT',
        'moon_semidiameter_deg_NE_Optimal', 'moon_distance_km_NE_Optimal',
        'Phase_Angle_BT',
        'Status', 'Error',
        'P_Sunset', 'P_NE_Optimal', 'P_Tel_Optimal',
        'Observation_Method', 'Observation_Source', 'Comparison_Scope',
        'Actual_Telescope_Config_Available', 'Actual_Observation_Time_Available',
        *[label for label, _ in VISUAL_DIAGNOSTIC_COLUMNS],
        *[label for label, _ in DATE_DIAGNOSTIC_COLUMNS],
    ]

    out_dir = os.path.dirname(filepath)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        column_positions = {name: index for index, name in enumerate(headers)}

        for r in results:
            # Parse Best_Time_Tel ke string HH:MM:SS
            bt_val = r.get('optimal_time_tel')
            bt_str = ''
            if bt_val:
                try:
                    if hasattr(bt_val, 'hour'):
                        bt_str = f"{bt_val.hour:02d}:{bt_val.minute:02d}:{bt_val.second:02d}"
                    else:
                        bt_str = str(bt_val)
                except Exception:
                    bt_str = ''

            dm_tel_bt = r.get('delta_m_tel_opt', -99)
            prediksi = _comparison_prediction(r)
            observasi = "Y" if r.get('observed', False) else "N"

            # Helper: format angka ke string (format standar internasional)
            def _f4(val):
                return f"{float(val):.4f}" if r.get('success') and val is not None and not math.isnan(float(val)) else ''
            def _f2(val):
                return f"{float(val):.2f}" if r.get('success') and val is not None and not math.isnan(float(val)) else ''
            def _full(val):
                return f"{float(val)}" if r.get('success') and val is not None and not math.isnan(float(val)) else ''

            row = [
                str(r.get('no', '')),
                r.get('tanggal_obs', ''),
                r.get('nama', ''),
                _f4(r.get('lat', 0)),
                _f4(r.get('lon', 0)),
                _f2(r.get('elv', 0)),
                f"{r.get('bulan_hijri', 0)}/{r.get('tahun_hijri', 0)}",
                _f4(r.get('sun_alt_sunset', 0)),
                _f4(r.get('moon_alt_sunset', 0)),
                _f4(r.get('elongation', 0)),
                _f4(float(r['moon_width']) * 60.0 if r.get('moon_width') is not None else None),
                _f4(r.get('phase_angle', 0)),
                _full(r.get('sky_brightness_nl', 0)),
                _full(r.get('luminansi_hilal_nl', 0)),
                _f4(r.get('k_v', 0)),
                _f2(r.get('rh', 0)),
                _f2(r.get('temperature', 0)),
                _f4(r.get('delta_m_ne_sunset', -99)),
                _f4(r.get('delta_m_tel_sunset', -99)),
                bt_str,
                _f4(r.get('optimal_sun_alt_tel', 0)),
                _f4(r.get('optimal_moon_alt_tel', 0)),
                _f4(r.get('opt_tel_elongation', 0)),
                _full(r.get('opt_tel_sky_brightness_nl', 0)),
                _full(r.get('opt_tel_luminansi_hilal_nl', 0)),
                _f4(r.get('opt_tel_k_v', 0)),
                _f2(r.get('opt_tel_rh', 0)),
                _f2(r.get('opt_tel_temperature', 0)),
                _f4(r.get('telescope_gain_opt', 0)),
                _export_duration(r.get('vis_duration_tel')) if r.get('success') else None,
                _f4(dm_tel_bt),
                prediksi if r.get('success') else '',
                observasi,
                _full(r.get('extinction_mag_v')),
                _full(r.get('transmission_v')),
                _full(r.get('opt_tel_extinction_mag_v')),
                _full(r.get('opt_tel_transmission_v')),
                _f4(r.get('opt_ne_k_v', 0)),
                _full(r.get('opt_ne_extinction_mag_v')),
                _full(r.get('opt_ne_transmission_v')),
                _full(r.get('moon_semidiameter')),
                _full(r.get('moon_distance_km')),
                _full(r.get('opt_tel_moon_semidiameter')),
                _full(r.get('opt_tel_moon_distance_km')),
                _full(r.get('opt_ne_moon_semidiameter')),
                _full(r.get('opt_ne_moon_distance_km')),
                _full(r.get('opt_tel_phase_angle')),
                'valid' if r.get('success') else 'invalid',
                r.get('error', ''),
                _full(r.get('pressure')),
                _full(r.get('opt_ne_pressure')),
                _full(r.get('opt_tel_pressure')),
                r.get('observation_method', OBSERVATION_METHOD),
                r.get('observation_source', OBSERVATION_SOURCE),
                r.get('comparison_scope', COMPARISON_SCOPE),
                False,
                False,
            ]

            if not r.get('optimal_time_ne'):
                for name in ('kV_NE_Optimal', 'extinction_mag_v_NE_Optimal', 'transmission_v_NE_Optimal',
                             'moon_semidiameter_deg_NE_Optimal', 'moon_distance_km_NE_Optimal', 'P_NE_Optimal'):
                    row[column_positions[name]] = ''
            if not r.get('optimal_time_tel'):
                for name in ('sun_alt_BT', 'Moon_Alt_BT', 'Elongasi_BT', 'Sky_Bright_BT', 'Lum_Hilal_BT',
                             'kV_BT', 'RH_BT', 'T_BT', 'Tel_Gain', 'Leg_Time_min', 'Dm_Tel_BT',
                             'extinction_mag_v_BT', 'transmission_v_BT', 'moon_semidiameter_deg_BT',
                             'moon_distance_km_BT', 'Phase_Angle_BT', 'P_Tel_Optimal'):
                    row[column_positions[name]] = ''
            row.extend(_visual_diagnostic_values(r))
            row.extend(r.get(key) for _, key in DATE_DIAGNOSTIC_COLUMNS)
            writer.writerow(row)

    _save_batch_atmosphere_provenance(results, filepath)
    print(f"  \u2713 CSV disimpan : {filepath}")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def _input_koreksi_bias_batch() -> tuple:
    print("\n--- KOREKSI BIAS ---")
    print("  Pilih opsi koreksi bias untuk semua lokasi:")
    print("  1. Gunakan data bawaan lokasi (jika ada)")
    print("  2. Tanpa koreksi (bias_t = 0, bias_rh = 0)")
    print("  3. Input manual nilai bias seragam untuk semua lokasi")
    try:
        pilihan = input("\n  Pilih opsi (1/2/3) [enter=2]: ").strip() or "2"
        if pilihan == "2":
            print("  ✓ Menggunakan data tanpa koreksi")
            return "2", 0.0, 0.0, "Tanpa koreksi (bias = 0)"
        elif pilihan == "3":
            t_str = input("  Masukkan bias suhu (°C) [enter=0]: ").strip()
            bias_t = float(t_str) if t_str else 0.0
            rh_str = input("  Masukkan bias RH (%) [enter=0]: ").strip()
            bias_rh = float(rh_str) if rh_str else 0.0
            print(f"  ✓ Koreksi bias seragam: T={bias_t:+.1f}°C, RH={bias_rh:+.1f}%")
            return "3", bias_t, bias_rh, f"Manual Seragam (T={bias_t:+.1f}°C, RH={bias_rh:+.1f}%)"
        elif pilihan == "1":
            print("  ✓ Menggunakan data bawaan lokasi")
            return "1", 0.0, 0.0, "Data Bawaan Lokasi"
        else:
            print("  [!] Pilihan tidak valid, menggunakan data tanpa koreksi.")
            return "2", 0.0, 0.0, "Tanpa koreksi (bias = 0)"
    except EOFError:
        return "2", 0.0, 0.0, "Tanpa koreksi (bias = 0)"
    except ValueError:
        print("  [!] Input tidak valid, menggunakan data tanpa koreksi.")
        return "2", 0.0, 0.0, "Tanpa koreksi (bias = 0)"

def main():
    """Entry point utama."""
    # 0. Konfigurasi interaktif
    _input_konfigurasi_interaktif()

    # 1. Prompt Bias
    bias_mode, manual_bias_t, manual_bias_rh, bias_mode_str = _input_koreksi_bias_batch()

    # 2. Batch run
    results = run_batch(bias_mode, manual_bias_t, manual_bias_rh)

    # 3. Tampilkan tabel
    print_results_table(results)

    # 4. Simpan ke Excel
    output_dir = str(OUTPUT_DIR)

    bias_tag = "NoBias" if bias_mode == '2' else ("ManualBias" if bias_mode == '3' else "BiasBawaan")
    excel_path = os.path.join(output_dir,
        f"Validasi_Crumey_{SUMBER_ATMOSFER}_{CALC_MODE}_{bias_tag}.xlsx")
    save_to_excel(results, excel_path, bias_mode_str)

    # 5. Simpan ke CSV
    csv_path = os.path.join(output_dir,
        f"Validasi_Crumey_{SUMBER_ATMOSFER}_{CALC_MODE}_{bias_tag}.csv")
    save_to_csv(results, csv_path)

    # 6. Ringkasan akhir
    print(f"\n{'█' * 70}")
    print("  VALIDASI SELESAI")
    print(f"{'█' * 70}")
    print(f"  Excel : {excel_path}")
    print(f"  CSV   : {csv_path}")
    print(f"{'█' * 70}\n")

    return results


def run():
    """Console entry point; keep main() results available to library callers."""
    configure_console_encoding()
    main()


if __name__ == "__main__":
    run()
