"""Interactive single- and multiple-location command-line interface."""
import math
import os
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
from hilal_visibility.calculator import HilalVisibilityCalculator, tentukan_timezone_indonesia
from hilal_visibility.models.crumey import DEFAULT_VISUAL_FIELD_FACTOR
from hilal_visibility.paths import OUTPUT_DIR
from hilal_visibility.atmosphere.provenance import atmosphere_audit_record, save_atmosphere_provenance
from hilal_visibility.reports.multi_location import _simpan_excel_multi, _plot_multi_lokasi
from hilal_visibility.console import configure_console_encoding
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

        print(f"\n  ✓ Bulan Hijriah: {nama_bulan[bulan_hijri]} {tahun_hijri} H")
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
        print(f"  ✓ Mode: {mode}")
    except ValueError:
        mode = "optimal"
        print(f"  ✓ Mode default: {mode}")

    print("\n--- LANGKAH 3.5: PILIH WAKTU PENGAMATAN ---")
    print("  0. Sesuai Hisab (H)       - Default")
    print("  1. H + 1 Hari             - Besoknya")
    print("  2. H + 2 Hari             - Lusanya")
    print(" -1. H - 1 Hari             - Kemarin")
    print("  Catatan: ECMWF IFS (arsip historis ~2017-sekarang), MERRA-2 (1981-sekarang)")

    try:
        offset_pilihan = input("\n  Pilih waktu (-2/-1/0/1/2) [enter=0]: ").strip()
        delta_day = int(offset_pilihan) if offset_pilihan else 0
        print(f"  ✓ Offset waktu: H + {delta_day} hari")
    except ValueError:
        delta_day = 0
        print(f"  ✓ Offset default: H + 0 hari")

    return mode, delta_day


def _input_sumber_atmosfer():
    """Input sumber data atmosfer. Return (sumber, manual_rh, manual_t, manual_p)."""
    print("\n--- LANGKAH 3.6: SUMBER DATA ATMOSFER ---")
    print("  Pilih sumber data atmosfer (RH, T, P):")
    print("  1. ECMWF IFS Historical (Open-Meteo API)  - data arsip historis ~2017-sekarang")
    print("  2. MERRA-2          (NASA POWER API)   — data historis 1981-sekarang")
    print("  3. Input Manual     (tanpa API)        — masukkan RH, T, P secara manual")

    manual_rh, manual_t, manual_p = 80.0, 25.0, 1013.25

    try:
        pilihan = input("\n  Pilih sumber (1/2/3) [enter=1]: ").strip() or "1"

        if pilihan == "2":
            sumber = 'merra2'
            print(f"  ✓ Sumber atmosfer: MERRA-2 (NASA POWER API)")
        elif pilihan == "3":
            sumber = 'manual'
            print("  Masukkan data atmosfer secara manual:")
            try:
                rh_input = input("    RH (%) [default=80.0]: ").strip()
                manual_rh = float(rh_input) if rh_input else 80.0
                t_input = input("    Suhu (°C) [default=25.0]: ").strip()
                manual_t = float(t_input) if t_input else 25.0
                p_input = input("    Tekanan (mbar) [default=1013.25]: ").strip()
                manual_p = float(p_input) if p_input else 1013.25
            except ValueError:
                print("  [!] Input tidak valid. Menggunakan nilai default.")
                manual_rh, manual_t, manual_p = 80.0, 25.0, 1013.25
            print(f"  ✓ Sumber atmosfer: Input Manual")
            print(f"    RH={manual_rh:.2f}%, T={manual_t:.2f}°C, P={manual_p:.2f} mbar")
        else:
            sumber = 'ecmwf_ifs'
            print(f"  ✓ Sumber atmosfer: ECMWF IFS Historical (Open-Meteo API)")
    except EOFError:
        sumber = 'ecmwf_ifs'
        print(f"  ✓ Sumber default: ECMWF IFS Historical")

    return sumber, manual_rh, manual_t, manual_p


def _input_koreksi_bias(bias_t: float, bias_rh: float, sumber_atmosfer: str = 'ecmwf_ifs'):
    """Input koreksi bias reanalisis. Return (bias_t, bias_rh)."""
    # Koreksi bias hanya relevan untuk sumber API (bukan manual)
    if sumber_atmosfer == 'manual':
        print("\n--- LANGKAH 3.7: KOREKSI BIAS ---")
        print("  ✓ Koreksi bias dilewati (sumber: Input Manual)")
        return 0.0, 0.0

    label = sumber_atmosfer.upper().replace('MERRA2', 'MERRA-2')
    print(f"\n--- LANGKAH 3.7: KOREKSI BIAS {label} ---")
    print(f"  Koreksi bias digunakan untuk menyesuaikan data {label} dengan data observasi.")
    print(f"  Definisi: bias = {label} - Observasi")
    print(f"  Contoh: Jika {label} 30°C dan Observasi 28°C, maka bias_t = +2.0")
    print()

    has_bias = (bias_t != 0.0 or bias_rh != 0.0)
    if has_bias:
        print(f"  [INFO] Lokasi ini memiliki data bias bawaan:")
        print(f"           bias_t = {bias_t:+.1f}°C")
        print(f"           bias_rh = {bias_rh:+.1f}%")
        print()

    print("  Pilih opsi koreksi bias:")
    if has_bias:
        print(f"  1. Gunakan data bawaan lokasi: T={bias_t:+.1f}°C, RH={bias_rh:+.1f}% [default]")
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
                print(f"  ✓ Menggunakan data {label} tanpa koreksi")
            elif bias_pilihan == "3":
                bias_t_input = input("  Masukkan bias suhu (°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                bias_t = float(bias_t_input) if bias_t_input else 0.0
                bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                print(f"  ✓ Koreksi bias: T={bias_t:+.1f}°C, RH={bias_rh:+.1f}%")
            else:
                print(f"  ✓ Menggunakan data bawaan: T={bias_t:+.1f}°C, RH={bias_rh:+.1f}%")
        else:
            bias_pilihan = input("\n  Pilih opsi (1/2) [enter=1]: ").strip() or "1"
            if bias_pilihan == "2":
                bias_t_input = input("  Masukkan bias suhu (°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                bias_t = float(bias_t_input) if bias_t_input else 0.0
                bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                print(f"  ✓ Koreksi bias: T={bias_t:+.1f}°C, RH={bias_rh:+.1f}%")
            else:
                bias_t, bias_rh = 0.0, 0.0
                print(f"  ✓ Menggunakan data {label} tanpa koreksi")
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
        print("  ✓ Koreksi bias dilewati (sumber: Input Manual)")
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
                    nama = nama[:28] + '…'
                print(f"         {nama:<30s}  bias_t={bt:+.1f}°C  bias_rh={br:+.1f}%")
        print()
        print("  1. Gunakan data bawaan per lokasi [default]")
        print("  2. Tanpa koreksi (bias_t = 0, bias_rh = 0 untuk semua lokasi)")
        print("  3. Input manual (nilai seragam untuk semua lokasi)")

        try:
            pilihan = input("\n  Pilih opsi (1/2/3) [enter=1]: ").strip() or "1"
            if pilihan == "2":
                print(f"  ✓ Menggunakan data {label} tanpa koreksi untuk semua lokasi")
                return {'opsi': 'tanpa'}
            elif pilihan == "3":
                try:
                    bias_t_input = input("  Masukkan bias suhu (°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                    manual_bias_t = float(bias_t_input) if bias_t_input else 0.0
                    bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                    manual_bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                    print(f"  ✓ Koreksi bias seragam: T={manual_bias_t:+.1f}°C, RH={manual_bias_rh:+.1f}%")
                    print(f"    (diterapkan ke semua {len(lokasi_list)} lokasi)")
                    return {'opsi': 'manual', 'manual_bias_t': manual_bias_t, 'manual_bias_rh': manual_bias_rh}
                except ValueError:
                    print("  [!] Input tidak valid. Menggunakan data bawaan per lokasi.")
                    return {'opsi': 'bawaan'}
            else:
                print(f"  ✓ Menggunakan data bias bawaan per lokasi ({n_has_bias} lokasi memiliki bias)")
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
                    bias_t_input = input("  Masukkan bias suhu (°C) [contoh: +1.5 atau -0.5, enter=0]: ").strip()
                    manual_bias_t = float(bias_t_input) if bias_t_input else 0.0
                    bias_rh_input = input("  Masukkan bias RH (%) [contoh: +5.0 atau -3.0, enter=0]: ").strip()
                    manual_bias_rh = float(bias_rh_input) if bias_rh_input else 0.0
                    print(f"  ✓ Koreksi bias seragam: T={manual_bias_t:+.1f}°C, RH={manual_bias_rh:+.1f}%")
                    print(f"    (diterapkan ke semua {len(lokasi_list)} lokasi)")
                    return {'opsi': 'manual', 'manual_bias_t': manual_bias_t, 'manual_bias_rh': manual_bias_rh}
                except ValueError:
                    print("  [!] Input tidak valid. Menggunakan tanpa koreksi.")
                    return {'opsi': 'tanpa'}
            else:
                print(f"  ✓ Menggunakan data {label} tanpa koreksi untuk semua lokasi")
                return {'opsi': 'tanpa'}
        except (ValueError, EOFError):
            print(f"  ✓ Menggunakan data {label} tanpa koreksi untuk semua lokasi")
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
        'field_factor': DEFAULT_VISUAL_FIELD_FACTOR, 'F_naked': DEFAULT_VISUAL_FIELD_FACTOR
    }

    print("\n--- LANGKAH 4: PARAMETER TELESKOP & FIELD FACTOR ---")
    print("  Gunakan parameter default?")
    print("  (aperture=100mm, magnification=50x, obstruction=0mm,")
    print("   transmission=0.95, n_surfaces=6, age=22.0,")
    print(f"   residual F visual bersama={DEFAULT_VISUAL_FIELD_FACTOR})")
    print("  F adalah nilai referensi yang belum dikalibrasi khusus hilal.")

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
            defaults['F_naked'] = _get_input(
                f"  Residual F visual [default: {DEFAULT_VISUAL_FIELD_FACTOR}]: ",
                DEFAULT_VISUAL_FIELD_FACTOR)
            defaults['field_factor'] = _get_input(
                f"  Residual F teleskop [default: sama, {defaults['F_naked']}]: ",
                defaults['F_naked'])
            print(f"  ✓ Parameter kustom digunakan.")
        else:
            print(f"  ✓ Parameter default digunakan.")
    except Exception as e:
        print(f"  [!] Terjadi kesalahan: {e}")
        print(f"  ✓ Parameter default digunakan.")

    return defaults


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-LOKASI: Fungsi pendukung untuk batch processing di mode interaktif
# ═══════════════════════════════════════════════════════════════════════════════

def _parse_range_input(input_str: str, max_val: int) -> list:
    """
    Parse input range string menjadi list of integers.
    Contoh: "1,3,5-10,15" → [1, 3, 5, 6, 7, 8, 9, 10, 15]

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
    print("  1. Lokasi Tunggal   — hitung visibilitas untuk satu lokasi")
    print("  2. Multi-Lokasi     — hitung visibilitas untuk banyak lokasi sekaligus")

    try:
        pilihan = input("\n  Pilih mode (1/2) [enter=1]: ").strip() or "1"
        if pilihan == "2":
            print("  ✓ Mode: Multi-Lokasi")
            return 'multi'
        else:
            print("  ✓ Mode: Lokasi Tunggal")
            return 'single'
    except (ValueError, EOFError):
        print("  ✓ Mode default: Lokasi Tunggal")
        return 'single'


def _input_multi_lokasi() -> list:
    """
    Pilih beberapa lokasi dari daftar_lokasi untuk batch processing.

    Returns:
    --------
    list[dict] or None
        List dictionary lokasi yang dipilih, atau None jika dibatalkan
    """
    from hilal_visibility.locations import print_daftar_lokasi, get_list_lokasi

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

        print(f"\n  ✓ {len(selected)} lokasi dipilih:")
        for i, lok in enumerate(selected, 1):
            nama = lok.get('nama', '')
            lat = lok.get('lat', lok.get('lintang', 0.0))
            lon = lok.get('lon', lok.get('bujur', 0.0))
            elv = lok.get('elevasi', lok.get('elv', 0.0))
            print(f"    {i:2d}. {nama}  (Lat: {lat:.4f}°, Lon: {lon:.4f}°, Elv: {elv:.0f} m)")

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

    print("\n" + "█" * 70)
    print("  BATCH PROCESSING: Visibilitas Hilal Multi-Lokasi")
    print(f"  {total} lokasi × Bulan {shared_params['bulan_hijri']}/{shared_params['tahun_hijri']} H")
    print(f"  Mode: {shared_params['mode']}  |  Atmosfer: {shared_params['sumber_atmosfer']}")
    print("█" * 70)

    t_batch_start = time.time()

    for i, lokasi in enumerate(lokasi_list, 1):
        nama = lokasi.get('nama', '')
        lat = lokasi.get('lat', lokasi.get('lintang', 0.0))
        lon = lokasi.get('lon', lokasi.get('bujur', 0.0))
        elv = lokasi.get('elevasi', lokasi.get('elv', 0.0))
        tz = tentukan_timezone_indonesia(lon)

        print(f"\n{'═' * 70}")
        print(f"  [{i:2d}/{total}] {nama}")
        print(f"         Lat={lat:.4f}°  Lon={lon:.4f}°  Elv={elv:.0f}m  TZ={tz}")
        print(f"{'═' * 70}")

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

            print(f"\n  RINGKASAN: Δm_NE={dm_ne:+.3f} ({status_ne})  "
                  f"Δm_Tel={dm_tel:+.3f} ({status_tel})  "
                  f"⏱ {elapsed:.1f}s")

            results.append({
                'lokasi': lokasi,
                'hasil': hasil,
                'calculator': calculator,
                'success': True,
                'elapsed': elapsed,
            })

        except Exception as e:
            elapsed = time.time() - t_start
            print(f"\n  ✗ ERROR: {e}")
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
    print(f"\n{'█' * 70}")
    print(f"  BATCH SELESAI: {n_success}/{total} berhasil dalam {total_time:.0f} detik")
    print(f"{'█' * 70}")

    # Tabel ringkasan akhir
    _print_tabel_ringkasan_multi(results, shared_params)

    return results


def _print_tabel_ringkasan_multi(results: list, shared_params: dict):
    """Cetak tabel ringkasan hasil multi-lokasi ke terminal."""
    mode = shared_params['mode']
    is_opt = (mode == 'optimal')

    print(f"\n{'═' * 110}")
    print(f"  TABEL RINGKASAN — Bulan {shared_params['bulan_hijri']}/{shared_params['tahun_hijri']} H"
          f"  |  Mode: {mode}  |  Atmosfer: {shared_params['sumber_atmosfer'].upper()}")
    print(f"{'═' * 110}")

    header = (f"{'No':>3} | {'Lokasi':<35} | {'Lat':>9} | {'Lon':>9} | "
              f"{'Moon Alt':>8} | {'Elong':>7} | {'Lebar':>5} | {'Δm NE':>8} | {'Δm Tel':>8} | "
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

    print(f"{'═' * 110}")

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






def main():
    """Fungsi utama dengan mode interaktif untuk pemilihan lokasi dan parameter."""
    from hilal_visibility.locations import pilih_lokasi_interaktif

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
    from hilal_visibility.locations import pilih_lokasi_interaktif

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
    print(f"  Koordinat : {lintang}°, {bujur}°")
    print(f"  Elevasi   : {elevasi} m")
    print(f"  Timezone  : {timezone_str}")
    if bias_t != 0.0 or bias_rh != 0.0:
        print(f"  Bias Data : T={bias_t:+.1f}°C, RH={bias_rh:+.1f}%")

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
        output_dir = str(OUTPUT_DIR)
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
            output_dir = str(OUTPUT_DIR)
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

    output_dir = str(OUTPUT_DIR)

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



def run():
    """Console entry point; calculations remain available through main()."""
    configure_console_encoding()
    main()


if __name__ == "__main__":
    run()
