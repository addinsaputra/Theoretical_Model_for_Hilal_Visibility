# Identitas IFS dan hasil uji sensitivitas atmosfer

Jalur `ecmwf_ifs` dalam proyek meminta **ECMWF IFS HRES 9 km melalui Open-Meteo**,
dengan selector `models=ecmwf_ifs`, pada Historical Weather API
`https://archive-api.open-meteo.com/v1/archive`.
Identitas produk mengikuti selector dan model respons yang diverifikasi sebelum
data dibaca. Nama endpoint tidak cukup untuk mengidentifikasi produk.

Pada backend Open-Meteo yang diaudit, `ecmwf_ifs` menggunakan reader IFS HRES;
`ecmwf_ifs_analysis` dan `ecmwf_ifs_analysis_long_window` merupakan selector
terpisah. Ringkasan dokumentasi dapat menggunakan istilah "analysis" lebih umum,
sehingga tulisan penelitian sebaiknya mencantumkan selector, endpoint, dan
produk persis yang dipakai. Mengubah host API saja belum membuktikan bahwa
produk yang dibandingkan berbeda.

Referensi identitas:
[backend Open-Meteo pada commit 1cd0eaa](https://github.com/open-meteo/open-meteo/blob/1cd0eaa1ed97857772a6bd968bbe373bd23636f3/Sources/App/Controllers/ForecastapiController.swift),
[Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api),
[ECMWF API](https://open-meteo.com/en/docs/ecmwf-api).
Referensi source tersebut menjelaskan penafsiran selector; commit backend yang
sedang berjalan di server Open-Meteo tidak tersedia dalam respons API.

## Metadata yang disimpan

`atmosfer_ecmwf_ifs.py` menyimpan identitas ini dalam metadata DataFrame dan
provenance JSON. Batch juga mencetak produk/endpoint dan memasukkannya ke
sheet `Ringkasan` XLSX.

| Field | Makna |
|---|---|
| `source` | Open-Meteo Historical Weather API |
| `endpoint` | URL `/v1/archive` yang diminta |
| `model` / `response_model_name` | Selector dan nama model respons yang diperiksa: `ecmwf_ifs` |
| `response_model_id` | ID model dari respons FlatBuffers; seluruh 30 respons uji bernilai 30 |
| `product_name` | ECMWF IFS HRES 9 km (Open-Meteo ecmwf_ifs) |
| `product_type` | `ifs_hres_hourly_time_series` |
| `nominal_horizontal_resolution_km` | Resolusi nominal 9 km |
| `product_identity_reference` | Referensi backend pada commit yang diaudit |
| `ifs_cycle` | `null`: cycle IFS tidak diekspos oleh respons ini |
| `ifs_cycle_availability` | Penjelasan bahwa cycle tidak tersedia |

Koordinat respons menunjukkan pusat grid yang digunakan. Elevasi respons adalah
elevasi efektif untuk downscaling, dan tidak disamakan dengan elevasi grid asli.
Suhu/RH/tekanan yang disimpan adalah input yang dipakai proyek setelah pemrosesan
Open-Meteo; raw hourly di provenance berarti sebelum interpolasi/bias proyek.

## Pengujian yang dilakukan

Alat uji: [ifs_sensitivity_study.py](../scripts/study_ifs_sensitivity.py).
Pengujian ini memakai API nyata, dengan bias suhu dan RH tetap 0:

- Tanggal paling awal dan akhir pada Lhoknga, Loang Baloq, Cikelet, Sulamu,
  Meras, dan Ternate: 12 pasangan lokasi–tanggal.
- Tanggal terakhir pada tiga lokasi tertinggi: Lembang, Rooftop Stageof Bandung,
  dan Rooftop IAIN Fattahul Muluk Jayapura: 3 pasangan.
- Rentang tanggal sampel 2022-04-02 sampai 2026-09-12; elevasi 5–1258 m.
- Window sunset sampai dua jam sesudahnya, interval satu menit.
  Sunset referensi memakai DE440s, T=10 °C dan P=1030 hPa yang sama untuk kedua grid.
- Model, elevasi yang diminta, variabel, dan window UTC identik untuk `land`
  dan `nearest`. Tanggal berasal langsung dari `OBSERVATIONS`.
- 15/15 pasangan lengkap, 30 respons API, 120 anchor hourly dan 3630 sampel menit.

### RH langsung dibandingkan RH dari T/Td

Metode alternatif menginterpolasi suhu dan dew point dahulu, kemudian memakai
[formula Magnus Open-Meteo](https://github.com/open-meteo/open-meteo/blob/1cd0eaa1ed97857772a6bd968bbe373bd23636f3/Sources/App/Helper/Meteorology.swift).
Efek nonlinear interpolasi dipisahkan dari perbedaan pada anchor API agar
perbedaan presisi/downscaling tidak semuanya dianggap kesalahan interpolasi.

Maksimum absolut perbedaan RH adalah **0.162684 poin persentase**;
efek nonlinear murni **0.162683 poin persentase**, di Rooftop Stageof Bandung,
2026-04-18. Perbedaan input ini kecil dibandingkan perubahan akibat pilihan
grid dalam sampel yang sama. Pengaruhnya terhadap margin Δm dan keputusan Y/N
belum diuji, sehingga interpolasi produksi tetap memakai RH langsung.

### Grid land dibandingkan nearest

8 dari 15 pasangan menggunakan koordinat grid berbeda. Maksimum absolut:

| Variabel | Selisih maksimum | Kasus |
|---|---:|---|
| RH | 14.527630 poin persentase | Sulamu, 2026-07-15 |
| Suhu | 1.627401 °C | Sulamu, 2026-07-15 |
| Tekanan permukaan | 1.148798 hPa | Rooftop Stageof Bandung, 2026-04-18 |

Di Sulamu, jarak lokasi–pusat grid adalah 11.02 km untuk `land` dan 4.77 km
untuk `nearest`. Angka jarak ini tidak menentukan grid mana yang lebih akurat:
representasi daratan/pantai dan kondisi setempat perlu dibandingkan dengan
pengamatan meteorologi BMKG. Pilihan produksi tetap `land`.

### Kewajaran atmosfer dan elevasi

Studi menandai RH di luar 0–100%, T di luar −20..60 °C, tekanan di luar
80..120% tekanan referensi ISA pada elevasi lokasi, dan Td > T+0.5 °C.
Ini merupakan ambang diagnostik untuk kesalahan besar/unit, bukan batas
klimatologi yang sudah dikalibrasi. Tidak ada data yang dipotong atau diubah.

**Tidak ada flag pada 120 anchor hourly nyata.** Tes terkontrol memastikan
T=400 °C, P=15 hPa, tekanan dalam Pa yang salah dibaca sebagai hPa, serta
nilai nonfinite terdeteksi. Tekanan normal pada elevasi 4000 m tetap diterima
oleh pemeriksaan elevasi meskipun lebih rendah dari 700 hPa. Validator produksi
tetap menggunakan kontrak sebelumnya; pemeriksaan baru berada di alat diagnostik.

## Artefak dan reproduksi

[Laporan lengkap](../outputs/ifs_sensitivity/report.md),
[ringkasan setiap kasus](../outputs/ifs_sensitivity/case_summary.csv),
[data mentah dan metadata](../outputs/ifs_sensitivity/raw_inputs.json),
[grafik](../outputs/ifs_sensitivity/sensitivity.png).
Artefak berada di `outputs/`, yang diabaikan Git sesuai pengaturan proyek.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/study_ifs_sensitivity.py
.\.venv\Scripts\python.exe -X utf8 scripts/study_ifs_sensitivity.py --replay outputs/ifs_sensitivity/raw_inputs.json --output outputs/ifs_sensitivity_replay
.\.venv\Scripts\python.exe -X utf8 scripts/study_ifs_sensitivity.py --all --output outputs/ifs_sensitivity_all
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

Replay dari input yang tersimpan mereproduksi metrik tanpa menghubungi API.
83 tes lokal lulus, termasuk 14 tes baru untuk diagnostik sensitivitas.
Studi ini merupakan uji sensitivitas input pada sampel spot, belum merupakan
validasi akurasi terhadap BMKG atau pengujian dampak keterlihatan pada semua
278 observasi. Tidak ada alasan dari studi ini untuk mengubah bias 0 saat ini.
