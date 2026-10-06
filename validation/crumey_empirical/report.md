# Pemeriksaan empiris hilal: label CCD dan threshold visual Crumey

**Status: perbandingan deskriptif lintas metode; bukan validasi empiris visual.**

Dataset memuat 278 observasi pada 26 tanggal dan 26 campaign/lunasi (tahun dan bulan Hijri). Pengguna mengonfirmasi bahwa seluruh label berasal dari CCD/citra digital melalui teleskop. Konfigurasi optik dan waktu percobaan/deteksi aktual tidak tersedia. Observasi yang memenuhi syarat kalibrasi visual: **0**. Tidak ada field factor atau koreksi bentuk hilal yang dipasang ke label CCD; default produksi tidak diubah.

Perhitungan lengkap: 276/278. Label terlihat pada kasus lengkap: 138. Baris lokasi pada tanggal yang sama dikelompokkan sebagai satu event; jumlah baris tidak diperlakukan sebagai jumlah event independen. Jumlah tanggal/lunasi tidak membuktikan independensi statistik; korelasi antarlaporan dari pengamat/lokasi yang sama masih mungkin.

Denominator tabel mencakup hanya kasus berstatus `complete`. Kasus `no_eligible_scene` (tidak ada scene scan pada altitude Bulan ≥2°) serta kegagalan cuaca/kalkulasi tetap dicatat terpisah dan tidak dianggap prediksi negatif. Karena itu, angka tabel tidak mewakili semua baris dataset bila ada pengecualian.

Prediksi memakai tanggal observasi eksplisit, atmosfer IFS HRES yang dipilih melalui `ecmwf_ifs`, hourly anchors UTC asli, interpolator produksi, dan bias T/RH nol. Tidak ada cuaca manual pengganti. Snapshot API mempertahankan model ID, lokasi grid, elevasi, satuan, dan waktu pengambilan.

Konfigurasi referensi yang **diasumsikan**, bukan metadata instrumen aktual: aperture 100 mm, pembesaran 50×, transmisi per permukaan 0,95, 6 permukaan, obstruksi 0 mm, usia 22 tahun, F=1,8. Scan produksi memakai interval 1 menit, refinement 15 detik, mulai 1 menit setelah sunset, dan altitude Bulan minimum 2°. Karena waktu percobaan aktual tidak diketahui, hasil adalah kesempatan visibilitas dalam scan model, bukan rekonstruksi kondisi saat laporan.

| Fraksi area target | TP | TN | FP | FN | Kesepakatan seimbang | Interval bootstrap event 95% |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 104 | 54 | 84 | 34 | 57.2% | 52.9–61.9% |
| 0.5 | 104 | 55 | 83 | 34 | 57.6% | 53.5–62.1% |
| 0.25 | 104 | 55 | 83 | 34 | 57.6% | 53.5–62.1% |
| 0.1 | 104 | 55 | 83 | 34 | 57.6% | 53.5–62.1% |

TP/TN/FP/FN di tabel hanya menggambarkan kesepakatan prediksi visual dengan label CCD. Angka tersebut tidak mengukur sensitivitas/spesifisitas visibilitas mata manusia. Interval bootstrap tanggal menggambarkan variasi sampling pada dataset ini; ketidakpastian metode, instrumen, waktu, awan/transparansi atmosfer, dan seleksi dataset tidak tercakup.

Bootstrap cluster tanggal mengasumsikan independensi antartanggal; ia belum mengatasi korelasi dalam satu lunasi bila suatu dataset memiliki lebih dari satu tanggal per lunasi. Dataset ini memiliki 26 tanggal dan 26 campaign unik. Kalibrasi visual mendatang memakai campaign/lunasi sebagai unit holdout bila metadata tersebut tersedia.

Fraksi area 1, 0,5, 0,25, 0,1 ditetapkan sebelum melihat hasil. Luminansi lokal hilal dipertahankan; area yang lebih kecil mewakili subset cahaya yang dicari, bukan pemampatan total flux ke area kecil. Semua fraksi menggunakan scene scan/refinement yang sama, sehingga ini pemeriksaan sensitivitas area pada scene tersebut, bukan pencarian waktu optimal independen untuk setiap asumsi bentuk. Tidak ada fraksi yang dipilih sebagai hasil kalibrasi produksi.

Kalibrasi visual yang disediakan dalam kode menolak CCD, imaging, metode campuran, dan metode tak diketahui. Ia memerlukan label `naked_eye` atau `visual_telescope` yang terverifikasi, bukti percobaan visual, jendela waktu aktual, serta konfigurasi optik/pengamat aktual untuk teleskop. Prediksi kalibrasi harus menggunakan jendela dan konfigurasi tersebut. Holdout dilakukan per campaign/lunasi (fallback per tanggal jika metadata campaign tidak tersedia); label event yang diuji tidak masuk fitting. Satu F efektif hanya mengidentifikasi koreksi gabungan; bentuk, luminansi, pengamat, dan optik tidak dapat dipisahkan dari satu parameter tersebut.

Tes unit pada data sintetis memeriksa guard metode, domain statistik, identitas perubahan F, dan isolasi holdout. Kelulusan tes tersebut adalah verifikasi perangkat lunak, bukan validasi empiris hilal.

Berkas: `raw_inputs.json` (dataset dan atmosfer asli), `predictions.json` (protokol, hash implementasi, indeks prediksi), `case_predictions/*.json` (C_obj, C_th, margin, area, atmosfer dan posisi untuk scene), `metrics.json`, dan `descriptive_predictions.csv`.

Jalankan ulang tanpa jaringan:

```powershell
.venv\Scripts\python.exe -X utf8 Core/crumey_empirical_validation.py --replay validation/crumey_empirical/raw_inputs.json --output validation/crumey_empirical_replay --workers 4
```

Sumber label BMKG: [Galeri BMKG](https://hilal.bmkg.go.id/gallery). Identifikasi seluruh label sebagai CCD berasal dari konfirmasi pengguna pada 2026-10-05; halaman galeri saat ini tidak mengautentikasi satu per satu 278 laporan historis dalam spreadsheet.

Kasus yang tidak menghasilkan prediksi:

- #27 (2022-06-29): no_eligible_scene; No scene above 2 deg
- #29 (2022-06-29): no_eligible_scene; No scene above 2 deg
