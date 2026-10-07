# =============================================================================
# DATA LOKASI PENGAMATAN HILAL
# =============================================================================
# Format: Nama Lokasi, Latitude, Longitude, Elevasi (mdpl)
#
# Catatan:
# - Latitude positif = Utara, negatif = Selatan
# - Longitude positif = Timur, negatif = Barat
# - Elevasi dalam meter di atas permukaan laut (mdpl)
# - Sumber data: data_keterlihatan_hilal_core.xlsx (Sheet1), 82 lokasi unik
# - bias_t dan bias_rh tidak diisi pada data di bawah;
#   get_list_lokasi() memberi nilai default bias_t=0, bias_rh=0
# =============================================================================

import io
import csv

# Data lokasi dalam format CSV string
# Format: nama lokasi, latitude, longitude, elevasi
from hilal_visibility.paths import DATA_DIR
DATA_LOKASI_CSV = (DATA_DIR / 'locations.csv').read_text(encoding='utf-8')


def get_list_lokasi():
    """
    Mengambil daftar lokasi pengamatan sebagai list of dictionaries.

    Returns:
    --------
    list[dict]
        List berisi dictionary dengan keys: nama, lat, lon, elevasi, bias_t, bias_rh
        Contoh:
        [
            {"nama": "UIN WS", "lat": -6.99, "lon": 110.34, "elevasi": 89,
             "bias_t": -1.0, "bias_rh": 2.0},
            ...
        ]
    """
    f = io.StringIO(DATA_LOKASI_CSV.strip())
    reader = csv.reader(f, skipinitialspace=True)

    list_lokasi = []
    for row in reader:
        if len(row) < 4:
            continue
        data = {
            "nama": row[0].strip(),
            "lat": float(row[1]),
            "lon": float(row[2]),
            "elevasi": float(row[3]),
            "bias_t": 0.0,
            "bias_rh": 0.0,
        }
        if len(row) >= 6:
            # Dua kolom terakhir adalah bias suhu dan RH (opsional).
            data["bias_t"] = float(row[-2])
            data["bias_rh"] = float(row[-1])
        list_lokasi.append(data)

    return list_lokasi


def get_lokasi_by_index(index: int):
    """
    Mengambil lokasi berdasarkan index (1-indexed untuk user-friendly).

    Parameters:
    -----------
    index : int
        Index lokasi (dimulai dari 1)

    Returns:
    --------
    dict or None
        Dictionary lokasi atau None jika index tidak valid
    """
    list_lokasi = get_list_lokasi()
    if 1 <= index <= len(list_lokasi):
        return list_lokasi[index - 1]
    return None


def get_lokasi_by_name(nama: str):
    """
    Mencari lokasi berdasarkan nama (partial match, case-insensitive).

    Parameters:
    -----------
    nama : str
        Nama lokasi yang dicari

    Returns:
    --------
    dict or None
        Dictionary lokasi pertama yang cocok atau None jika tidak ditemukan
    """
    list_lokasi = get_list_lokasi()
    nama_lower = nama.lower()

    for loc in list_lokasi:
        if nama_lower in loc["nama"].lower():
            return loc
    return None


def print_daftar_lokasi():
    """
    Menampilkan daftar lokasi dalam format tabel yang rapi.
    """
    list_lokasi = get_list_lokasi()

    print("\n" + "=" * 80)
    print("DAFTAR LOKASI PENGAMATAN HILAL")
    print("=" * 80)
    print(f"{'NO':<4} | {'NAMA LOKASI':<42} | {'LAT':<10} | {'LON':<10} | {'ELV':<5}")
    print("-" * 80)

    for i, data in enumerate(list_lokasi, 1):
        print(f"{i:<4} | {data['nama']:<42} | {data['lat']:<10.5f} | {data['lon']:<10.5f} | {data['elevasi']}")

    print("=" * 80)
    print(f"Total: {len(list_lokasi)} lokasi")
    return list_lokasi


def pilih_lokasi_interaktif():
    """
    Menampilkan menu interaktif untuk memilih lokasi.

    Returns:
    --------
    dict or None
        Dictionary lokasi yang dipilih atau None jika dibatalkan
    """
    list_lokasi = print_daftar_lokasi()

    print("\nMasukkan nomor lokasi (1-{}) atau 0 untuk input manual:".format(len(list_lokasi)))

    try:
        pilihan = int(input("Pilihan Anda: "))

        if pilihan == 0:
            # Input manual
            print("\n--- INPUT LOKASI MANUAL ---")
            nama = input("Nama lokasi: ")
            lat = float(input("Latitude (contoh: -6.9167): "))
            lon = float(input("Longitude (contoh: 110.3480): "))
            elv = int(input("Elevasi (meter): "))

            return {
                "nama": nama,
                "lat": lat,
                "lon": lon,
                "elevasi": elv
            }

        elif 1 <= pilihan <= len(list_lokasi):
            lokasi = list_lokasi[pilihan - 1]
            print(f"\n✓ Lokasi dipilih: {lokasi['nama']}")
            return lokasi

        else:
            print("[!] Nomor tidak valid!")
            return None

    except ValueError:
        print("[!] Input harus berupa angka!")
        return None


# --- Testing jika dijalankan langsung ---
if __name__ == "__main__":
    # Test: tampilkan daftar
    print_daftar_lokasi()

    # Test: ambil by index
    print("\n--- Test get by index ---")
    lok = get_lokasi_by_index(1)
    print(f"Index 1: {lok}")

    # Test: cari by name
    print("\n--- Test get by name ---")
    lok = get_lokasi_by_name("UIN")
    print(f"Cari 'UIN': {lok}")
