# Panduan menjalankan program dari terminal

Anda tetap dapat menjalankan file Python langsung seperti sebelum perapian.
Gunakan file peluncur di `scripts/` sesuai kebutuhan berikut.

| Kebutuhan | File yang dijalankan | Pilihan berikutnya |
| --- | --- | --- |
| Menghitung satu lokasi | `scripts/run_visibility.py` | Menu awal: `1` |
| Menghitung beberapa atau semua 82 lokasi pada satu bulan/tahun Hijriah | `scripts/run_visibility.py` | Menu awal: `2` |
| Menjalankan seluruh 278 kasus pada dataset observasi penelitian | `scripts/run_batch.py` | Isi konfigurasi batch; lokasi dan periode diambil dari dataset |

Untuk menghitung beberapa lokasi yang Anda pilih sendiri, gunakan menu `2`
pada **`run_visibility.py`**. `run_batch.py` menjalankan kasus yang sudah
tersimpan dalam dataset, yang mencakup banyak lokasi dan periode pengamatan.

## 1. Buka terminal di folder proyek

Buka folder proyek di VS Code lalu pilih **Terminal → New Terminal**, atau
buka PowerShell pada folder tersebut. Folder proyek adalah folder yang
berisi `README.md`, `pyproject.toml`, `.venv/`, `scripts/`, dan `src/`.
Semua perintah di bawah diasumsikan dijalankan dari folder ini.

Pada komputer ini, Anda dapat berpindah ke folder proyek dengan:

```powershell
Set-Location "C:\Users\Invisible\crescent_visibility_telescope"
```

Perintah menggunakan Python pada `.venv` secara langsung. Anda dapat
menyalin perintahnya tanpa mengaktifkan virtual environment terlebih dahulu.

## 2. Lokasi tunggal

Jalankan:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_visibility.py
```

Ikuti menu berikut:

1. Pada **MODE LOKASI**, masukkan `1` untuk lokasi tunggal.
2. Pilih nomor lokasi dari daftar. Pilihan `0` membuka input nama, lintang,
   bujur dan elevasi lokasi sendiri.
3. Masukkan nomor bulan Hijriah (`1–12`) dan tahun Hijriah.
4. Pilih mode perhitungan: `1` = **sunset**, `2` = **optimal**.
5. Masukkan offset hari. `0` berarti tanggal ijtima dalam **WIB**;
   `1` berarti satu tanggal setelahnya. Acuan ini sama untuk semua lokasi,
   sementara sunset dan waktu hasil tetap memakai zona waktu lokasi.
6. Pilih sumber atmosfer: `1` = ECMWF IFS, `2` = MERRA-2,
   `3` = input manual. Pada input manual, isi RH, suhu dan tekanan.
7. Ikuti pilihan koreksi bias jika memakai sumber API.
8. Tekan Enter pada pertanyaan parameter default untuk memakai konfigurasi
   teleskop bawaan dan **F mata telanjang = F teleskop = 2.0**.
9. Pada pertanyaan menyimpan Excel, tekan Enter atau ketik `Y` untuk
   menyimpan; ketik `n` untuk melewati. Mode optimal juga menawarkan grafik.

Contoh percobaan dengan atmosfer manual:

| Pertanyaan | Jawaban contoh |
| --- | --- |
| Mode lokasi | `1` |
| Nomor lokasi | `1` (lokasi pertama pada daftar) |
| Bulan Hijriah | `9` (Ramadhan) |
| Tahun Hijriah | `1444` |
| Mode perhitungan | `1` (sunset) |
| Offset hari | `0` |
| Sumber atmosfer | `3` (manual) |
| RH | `75` |
| Suhu | `25` |
| Tekanan | `1013.25` |
| Gunakan parameter default? | Enter |
| Simpan Excel? | `Y` atau `n`, sesuai kebutuhan |

Nilai cuaca contoh merupakan input percobaan. Untuk evaluasi pengamatan,
gunakan input yang sesuai lokasi dan waktu. RH harus berada dalam
`0 <= RH < 100%` untuk evaluasi Schaefer.

## 3. Multi-lokasi yang dipilih sendiri

Gunakan perintah yang sama:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_visibility.py
```

Ikuti menu berikut:

1. Pada **MODE LOKASI**, masukkan `2` untuk multi-lokasi.
2. Pada pemilihan lokasi, masukkan `1` untuk semua 82 lokasi atau `2`
   untuk memilih beberapa lokasi.
3. Jika memilih beberapa, ketik nomor seperti `1,3,5-10`, lalu Enter.
   Untuk percobaan singkat dengan dua lokasi, ketik `1,2`.
4. Masukkan bulan/tahun Hijriah, mode perhitungan, offset hari, sumber
   atmosfer, koreksi bias, dan parameter teleskop.
5. Pilihan tersebut dipakai bersama untuk semua lokasi yang dipilih.
   Jika memakai atmosfer manual, nilai RH/T/P yang dimasukkan juga sama;
   sumber API mengambil cuaca sesuai lokasi dan waktu masing-masing.
6. Tunggu perhitungan dan tabel ringkasan. Pilih penyimpanan Excel dan
   grafik perbandingan ketika diminta.

Pada mode ini, pilihan perhitungan tetap **`1` = sunset, `2` = optimal**.
Jika kolom nomor lokasi dibiarkan kosong atau tidak memuat nomor yang
valid, program memakai semua lokasi. Masukkan nomor valid seperti `1,2`
untuk menjalankan hanya dua lokasi.

## 4. Batch dataset observasi penelitian

Peluncur ini menggantikan cara menjalankan `core_multi_location.py` dahulu:

```powershell
.\.venv\Scripts\python.exe .\scripts\run_batch.py
```

Program menjalankan 278 kasus dari
[`data/observations/bmkg_ccd.json`](../data/observations/bmkg_ccd.json).
Dataset menyediakan lokasi, periode Hijriah dan label observasi. Menu
batch meminta konfigurasi perhitungan, sumber atmosfer, F, parameter
teleskop, interval pencarian waktu dan koreksi bias.

Batch memakai **bulan/tahun Hijriah sebagai acuan ephemeris** untuk menghitung
ijtima. **H+0 adalah tanggal kalender ijtima dalam WIB (`Asia/Jakarta`), dengan
awal hari 00:00 WIB, untuk semua lokasi.** Konvensi ini mengikuti pencatatan
offset oleh pemilik dataset BMKG. H+0 memakai tanggal WIB yang sama, meskipun
ijtima lokal di WIT sudah melewati tengah malam. Tanggal pengamatan dalam
dataset yang berada dalam H-2 sampai H+2 dipakai
untuk menentukan offset setiap kasus, sehingga H+0/H+1 dapat tercampur tanpa
offset seragam untuk 278 kasus. Jika tanggal dataset jauh dari acuan tersebut,
program memakai H+0 dari ephemeris. Contohnya, periode `1/1444` dengan tanggal
dataset `2022-06-29` dihitung pada `2022-07-29`; tanggal asli tetap dicatat.
Tanggal terpilih menentukan sunset, cuaca, dan pencarian waktu optimal di
zona waktu lokal masing-masing lokasi. Tanggal dataset yang sudah benar
dipakai langsung; offset tidak ditambahkan lagi pada tanggal tersebut.
Contoh: ijtima Jumadilawal 1448 jatuh pada 10 Oktober 2026 malam WIB atau
11 Oktober dini hari WIT. Acuan H+0 tetap **10 Oktober** untuk semua lokasi;
pengamatan **H+1 berarti 11 Oktober**, baik di WIB, WITA, maupun WIT.
Terminal menampilkan offset per kasus; CSV dan sheet Excel `Tanggal Pengamatan`
memuat tanggal model, acuan H+0, offset, kecocokan, tanggal dataset asli, serta
sumber pemilihan tanggal, serta zona acuan H+0. Jika tanggal hitung berbeda dari tanggal terpilih,
kasus ditandai gagal dan tidak dipakai untuk perbandingan.

Kolom waktu optimal tetap bisa kosong bila tidak ada timestep yang memenuhi
altitude minimum Bulan (default `2°`). Itu berarti tidak ada hasil optimal
pada batas pencarian yang dipilih; periksa kolom tanggal untuk membedakannya
dari kesalahan pemilihan hari pengamatan.

**Urutan pilihan mode pada batch adalah `1` = optimal, `2` = sunset**.
Tekan Enter untuk nilai default yang tercantum di setiap pertanyaan.
Baseline F mata telanjang dan teleskop masing-masing adalah `2.0`.

Batch menyimpan Excel dan CSV secara otomatis setelah perhitungan.
Label dataset berasal dari kamera/CCD; hasilnya merupakan perbandingan
deskriptif dengan model visual. Sumber atmosfer API memerlukan internet.

## 5. Lokasi file hasil

Keluaran baru disimpan di **`outputs/`** pada folder proyek:

| Alur | Hasil |
| --- | --- |
| Lokasi tunggal | Workbook Excel jika dipilih; grafik margin tersedia pada mode optimal |
| Multi-lokasi yang dipilih sendiri | Workbook gabungan jika dipilih; grafik perbandingan jika dipilih |
| Batch dataset | Excel dan CSV otomatis dengan nama `Validasi_Crumey_<sumber>_<mode>_<bias>` |

Ekspor Excel/CSV juga menyimpan file pendamping `.atmosphere.json` untuk
provenance cuaca. Jika Anda melewati pilihan menyimpan pada menu biasa,
hasil tetap ditampilkan di terminal. `validation/` menyimpan arsip
penelitian terdokumentasi dari perhitungan sebelumnya.

## 6. Nama file lama dan peluncur sekarang

| File yang dahulu dijalankan | File yang sekarang dijalankan |
| --- | --- |
| `Core/core_crescent_visibility.py` | `scripts/run_visibility.py` |
| `Core/core_multi_location.py` | `scripts/run_batch.py` |

Kode perhitungan berada di `src/hilal_visibility/`; gunakan peluncur di
`scripts/` untuk membuka menu terminal.

Perintah berikut juga membuka menu lokasi tunggal/multi-lokasi yang sama:

```powershell
.\.venv\Scripts\python.exe -m hilal_visibility
```

Anda dapat tetap memakai cara menjalankan file langsung di bagian 2–4.

## 7. Instalasi pertama atau pemulihan lingkungan

Checkout ini sudah disiapkan dengan `.venv`. Untuk checkout baru, jalankan
sekali dari folder proyek menggunakan Python 3.10 atau lebih baru:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

| Pesan/masalah | Tindakan |
| --- | --- |
| `.venv\Scripts\python.exe` tidak ditemukan | Pastikan terminal berada pada folder proyek; buat `.venv` melalui perintah instalasi jika belum tersedia |
| `can't open file ... scripts/run_visibility.py` | Pastikan folder `scripts/` terlihat dari direktori terminal saat ini |
| `No module named hilal_visibility` atau dependensi | Jalankan instalasi dengan Python `.venv` yang sama seperti perintah menjalankan program |
| Ephemeris tidak ditemukan | Pastikan `data/ephemeris/de440s.bsp` tersedia |
| API cuaca gagal | Periksa koneksi dan pesan error; menu `run_visibility.py` menyediakan sumber manual untuk input RH/T/P yang Anda tentukan |
| Simbol pada hasil lama terlihat rusak | Tutup lalu buka kembali file di `outputs/` yang sudah diperbaiki. Peluncur sekarang memakai UTF-8 untuk keluaran terminal; gunakan Windows Terminal atau terminal VS Code untuk menampilkan simbol seperti `°` dan `Δm` |
