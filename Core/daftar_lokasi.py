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
# - adm4_code, bias_t, dan bias_rh tidak diisi pada data di bawah; 
#   get_list_lokasi() memberi nilai default adm4_code="" dan 
#   bias_t=0, bias_rh=0 (tidak dikoreksi)
# =============================================================================

import io
import csv
    
# Data lokasi dalam format CSV string 
# Format: nama lokasi, latitude, longitude, elevasi
DATA_LOKASI_CSV = """
pantai Loang Baloq_Mataram, -8.603710273563724, 116.0743526343624, 5
Dermaga Kokar_Alor, -8.160633661422654, 124.4469298628282, 6
Kantor BMKG NTT_Kupang, -10.152721211412, 123.6084268386404, 46
Pantai Wolulu_Kolaka, -4.437940163876542, 121.5180156752929, 1
Pantai Galesong_Takalar, -5.241962225688506, 119.3804270461404, 4
Tower Hilal Marana_Donggala, -0.578624, 119.7907213933992, 13
Bukit Persaudaraan Mauliru_Sumba Timur, -9.67563477316942, 120.295333443605, 68
Pantai Binasi_Tapanuli Tengah, 1.900397007599444, 98.54871319112205, 1
Pantai Cermin_Pariaman, -0.6360929508303517, 100.1216008412193, 5
Pantai Patra Jasa_Badung, -8.739618909814585, 115.1609513837828, 4
Pantai Tanjung Pasir_Tangerang, -6.013443129005504, 106.6789127285937, 1
POB Cibeas Pelabuhan Ratu_Sukabumi, -7.073954888421351, 106.5313851128172, 125
Tower Hilal Meras_Manado, 1.48033, 124.83367, 31
Gedung Graha NU_Balikpapan, -1.214391502304469, 116.8573002444378, 68
Tugu Christina_Ambon, -3.687469703972144, 128.1923836941696, 85
Kantor Stageof_Sorong, -0.8623221459653803, 131.2590990937428, 50
Pantai Lampu Satu_Merauke, -8.511434241469269, 140.3785140085394, 4
POB Lhoknga_Aceh Besar, 5.466784768299926, 95.2422058726947, 13
POB Syekh Belabelu_Bantul, -8.016269183330273, 110.3234649137316, 46
Tower Hilal Ave Taduma_Ternate, 0.7961631476438263, 127.2940983176842, 33
Hotel Mina Tanjung_Lombok Utara, -8.346996996074873, 116.1489666410537, 5
Tower Hilal Sulamu_Kupang, -10.04515269471165, 123.6061277641333, 15
Pantai Tanjung Moco_Tanjung Pinang, 0.8332286096672868, 104.4991907066717, 1
Ponpes Modern Islam Assalaam_Sukoharjo, -7.553293915055649, 110.7712022251706, 120
Rooftop Kantor BBMKG I Medan_Kota Medan, 3.539760834086997, 98.63706178400678, 51
Rooftop PDAM Kota Makassar_Gowa, -5.214276084461721, 119.4561729210354, 15
Pantai Purus_Kota Padang, -0.9295313925782047, 100.3500354721508, 5
POB Kalianda_Lampung Selatan, -5.794681168328539, 105.584765097417, 2
Pos Observasi Geofisika Lembang_Bandung, -6.826420320711056, 107.61856621984, 1258
Gedung Kebudayaan Provinsi Sumatera Barat_Kota Padang, -0.9548158683661738, 100.3526701201944, 21
Masjid Cakmarussalam Wakasihu_maluku Tengah, -3.75748166512398, 127.9366931385646, 15
Gedung Tower RADAR Stamet YIA_DIY, -7.903195845955204, 110.0672141090963, 14
Pantai Wisata Hiu Paus Botubarani_Bone Bolango, 0.474256829118072, 123.1007100693372, 6
Labuan Bajo_Nusa Tenggara Timur, -8.49336275382115, 119.8770098459208, 6
Pantai Tanjung Setumu_Tanjung Pinang, 0.8760089599074261, 104.4173088608222, 2
Tanjung Lesung Beach Hotel_Pandeglang, -6.479559259357492, 105.6535861308633, 1
Pos Pengamatan Dambalo_Gorontalo Utara, 0.8947964108004961, 122.9515329782496, 21
Islamic Center_Balikpapan, -1.23917005988127, 116.8824322915359, 50
Pantai Kibito_Nabire, -3.241298738990194, 135.5693028064887, 9
Dermaga Bahari_Kolaka, -4.35282009438306, 121.5162368226745, 1
POB Cikelet_Garut, -7.593820433086044, 107.6236772096795, 14
Kantor Stageof_Aceh Selatan, 3.134044281892134, 97.31173637163916, 11
Rooftop Stamet RHF_Tanjungpinang, 0.9235109454344037, 104.5290293385911, 17
Kampus 4 UAD Lantai 10_Bantul, -7.833012779061722, 110.3832251777645, 114
The Hele'yo Sentani_Jayapura, -2.598228404975657, 140.5239804972283, 76
Markaz Rukyatul Hilal Tanjung Kodok_Lamongan, -6.863960364296696, 112.3580709472701, 8
Pantai Kuala Ba'u_Aceh Selatan, 3.098438210286545, 97.30455602884486, 3
Menara Suar Distrik Navigasi Kelas 1_Ambon, -3.696290816215657, 128.1744479788526, 3
Rooftop Stageof_Bandung, -6.883392337096449, 107.5971865865387, 802
Mall GTC_Makassar, -5.169821858523188, 119.3905650987459, 14
Dusun Eri_Ambon, -3.74714397949535, 128.1307648421075, 12
Pondok Pesantren Hidayatullah_Balikpapan, -1.135183720593059, 116.9987179457806, 24
Pantai Menase_Nabire, -3.370364977623402, 135.4774129272349, 8
Halaman Stageof_Lampung Utara, -4.836056629367655, 104.8700882354863, 33
Pendopo Kantor Desa Jenggawur_Banjarnegara, -7.388465686197972, 109.6759518259036, 279
Halaman Gereja Imanuel_Ambon, -3.693833508520879, 128.1945835051309, 100
Stageof_Sleman, -7.816341614446136, 110.2945858891224, 129
Taman Wawoni_Konawe Kepulauan, -4.021863160773676, 122.9884803467164, 1
Rooftop IAIN Fattahul Muluk_Jayapura, -2.57810611220113, 140.6296987499846, 312
Pantai Tanah Lot_Tabanan, -8.621148275279072, 115.0876640708968, 10
Halaman Kantor Stageof_Malang, -8.152175271310911, 112.450820127438, 288
Rooftop Stamet Maritim_Makassar, -5.069375542871145, 119.4710198786338, 12
Pantai Pondok Bali_Subang, -6.207296470088122, 107.7760496555537, 1
Lantai 2 Stageof Saumlaki_Kepulauan Tanimbar, -7.982626296174896, 131.298800969412, 31
Halaman Kantor BBMKG Wilayah V_Jayapura, -2.57536889170754, 140.6861904946675, 40
Pantai Ria Cocoa City_Kolaka, -4.054662787855491, 121.5874455240659, 2
Kantor Stageof_Alor, -8.144531635873458, 124.5903354591743, 19
Pantai Pancur_Banyuwangi, -8.677837674709997, 114.3730947088477, 2
Pantai Luk Indah_Lombok Utara, -8.285164415868195, 116.2202994436726, 5
Kantor Stageof_Gowa, -5.21791840471671, 119.4697725314806, 26
D'Sunset Hills_Gorontalo, 0.623716651083367, 123.0286707681653, 127
Masjid Al_Hakim_Kota Padang, -0.9605002424649247, 100.3531651856612, 7
Rooftop Kantor BBMKG Wilayah IV Makassar_Kota makassar, -5.142824410680578, 119.4523597669547, 17
Villa & Resto Bukit Indah Saumlaki_Kepulauan Tanimbar, -7.979939379326653, 131.3048343968088, 59
Pantai Sibone_Alor, -8.155439264411921, 124.7279493728136, 5
Sentani Purnama Resto_Jayapura, -2.604920808424523, 140.6294757431127, 74
BMKG Pusat_DKI Jakarta, -6.155706213314788, 106.8416455263788, 46
Kantor Stageof Gorontalo, 0.6360800786639621, 123.0105697494342, 69
Halaman Kantor Stageof_Palu, -0.9053691327871062, 119.8367221941091, 76
Pantai Purirano_Kendari, -3.961888364034631, 122.6188465098542, 1
Badan Bendungan Sutami_Malang, -8.159508876608822, 112.4473009736177, 274
RTH Papalimba Puday_Kendari, -3.981588323185902, 122.5791589234257, 1
"""


def get_list_lokasi():
    """
    Mengambil daftar lokasi pengamatan sebagai list of dictionaries.
    
    Returns:
    --------
    list[dict]
        List berisi dictionary dengan keys: nama, lat, lon, elevasi, adm4_code,
        bias_t, bias_rh
        Contoh:
        [
            {"nama": "UIN WS", "lat": -6.99, "lon": 110.34, "elevasi": 89,
             "adm4_code": "33.74.10.1003", "bias_t": -1.0, "bias_rh": 2.0},
            ...
        ]
    """
    f = io.StringIO(DATA_LOKASI_CSV.strip())
    reader = csv.reader(f, skipinitialspace=True)
    
    list_lokasi = []
    for row in reader:
        if len(row) >= 7:
            # Format lengkap: nama, lat, lon, elevasi, adm4_code, bias_t, bias_rh
            data = {
                "nama": row[0].strip(),
                "lat": float(row[1]),
                "lon": float(row[2]),
                "elevasi": float(row[3]),
                "adm4_code": row[4].strip(),
                "bias_t": float(row[5]),
                "bias_rh": float(row[6])
            }
            list_lokasi.append(data)
        elif len(row) >= 5:
            # Backward compatibility: tanpa bias data
            data = {
                "nama": row[0].strip(),
                "lat": float(row[1]),
                "lon": float(row[2]),
                "elevasi": float(row[3]),
                "adm4_code": row[4].strip(),
                "bias_t": 0.0,
                "bias_rh": 0.0
            }
            list_lokasi.append(data)
        elif len(row) >= 4:
            # Backward compatibility: tanpa adm4_code dan bias
            data = {
                "nama": row[0].strip(),
                "lat": float(row[1]),
                "lon": float(row[2]),
                "elevasi": float(row[3]),
                "adm4_code": "",
                "bias_t": 0.0,
                "bias_rh": 0.0
            }
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