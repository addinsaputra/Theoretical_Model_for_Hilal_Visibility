Ya, saya sudah audit versi terbaru di repo **`Theoretical_Model_for_Hilal_Visibility`**. Perubahan yang kita bahas sebelumnya memang sudah masuk dengan arah yang benar. Dari sisi **engineering data atmosfer**, implementasinya sekarang sudah jauh lebih layak untuk penelitian.

Yang belum saya anggap selesai justru bukan lagi bug pemrogramannya, tetapi **pemilihan produk IFS mana yang secara ilmiah paling tepat untuk merekonstruksi atmosfer pada observasi hilal 2022–2024**, serta validitas koreksi bias yang sekarang masih digunakan.

## Status implementasi sekarang

Di `Core/atmosfer_ecmwf_ifs.py`, saya sudah melihat bahwa model sekarang benar-benar dikunci:

```python
IFS_MODEL = "ecmwf_ifs"
```

dan request membawa:

```python
"models": IFS_MODEL
"cell_selection": "land"
"temperature_unit": "celsius"
```

serta:

```python
params["elevation"] = elevation
```

Lebih bagus lagi, respons API tidak sekadar dipercaya, tetapi diverifikasi bahwa:

```python
response.Model() == Model.ecmwf_ifs
```

dan identitas variabel, unit, altitude field, panjang array, time axis, serta metadata lokasi juga divalidasi. Ini menyelesaikan masalah besar versi sebelumnya: sekarang kita memang dapat menyatakan bahwa jalur tersebut **secara eksplisit meminta ECMWF IFS**, bukan Open-Meteo Best Match.

Struktur `AtmosphericWindow` juga bagus. Ia mengharuskan timestamp hourly kontinu, unique, terurut, menolak nilai NaN/nonfinite, tidak melakukan extrapolation, dan melakukan interpolasi terhadap anchor hourly asli. Jadi masalah lama:

\[
t>sunset+1h
\Rightarrow
T,RH,P=\text{konstan}
\]

sudah hilang.

Pipeline sekarang juga melakukan:

\[
\text{raw hourly}
\rightarrow
\text{interpolasi waktu}
\rightarrow
\text{bias correction}
\]

bukan mengoreksi tiap anchor dahulu. Untuk additive bias yang konstan, ini adalah struktur yang bersih.

Yang menurut saya sangat penting adalah perubahan failure handling. API failure sekarang di-propagate sebagai error dan batch menandai observasi:

```text
success = False
```

tanpa mengisi:

\[
RH=80\%,\quad T=25^\circ C,\quad P=1013.25
\]

secara fiktif. Untuk penelitian, ini keputusan yang benar.

Sidecar:

```text
<hasil>.atmosphere.json
```

juga merupakan langkah bagus. Anda sekarang menyimpan raw hourly data, dew point, koordinat requested/returned, elevasi efektif, model, endpoint, unit, waktu retrieval, window UTC, dan bias. Dengan demikian kalau Open-Meteo mengubah backend di masa depan, Anda masih mempunyai **input atmosfer aktual yang benar-benar dipakai saat eksperimen**.

Jadi secara software:

\[
\boxed{\text{pipeline atmosfer sudah jauh lebih matang}}
\]

---

# Tetapi sekarang muncul persoalan ilmiah yang lebih penting

Saya awalnya menganggap pertanyaannya tinggal:

> IFS vs ERA5.

Setelah membaca dokumentasi Open-Meteo terbaru lebih dalam, ternyata kita perlu membedakan **dua jenis IFS historical**.

Open-Meteo sekarang menyediakan:

| Produk | Konsep |
|---|---|
| Historical Weather API | ECMWF **IFS analysis** 9 km |
| Historical Forecast API | forecast historis, first hours dari successive operational runs |
| ERA5 | reanalysis 0.25° |
| ERA5-Land | land reanalysis ~9–11 km |

Kode Anda sekarang memakai:

```text
https://archive-api.open-meteo.com/v1/archive
```

yakni **Historical Weather API**.

Dokumentasi Open-Meteo menyebut `ECMWF IFS` pada endpoint ini sebagai IFS 9 km dari 2017 hingga sekarang. Mereka juga secara eksplisit membedakannya dari Historical Forecast API. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api?utm_source=chatgpt.com)

Ini penting karena tujuan skripsi Anda bukan:

> “Bagaimana cuaca diprakirakan pada saat itu?”

melainkan:

> **“Bagaimana kondisi atmosfer yang paling representatif pada waktu observasi hilal?”**

---

## Historical Weather IFS vs Historical Forecast IFS

Ada sedikit hal menarik dalam dokumentasinya.

Untuk Historical Weather, Open-Meteo menyatakan ECMWF IFS sebagai data 9 km dan menyebutnya sangat presisi untuk kondisi historis. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api?utm_source=chatgpt.com)

Tetapi pada dokumentasi Historical Forecast, mereka justru mengatakan:

> untuk representasi kondisi masa lalu dalam beberapa tahun terakhir yang paling akurat, gunakan Historical Forecast API.

Historical Forecast dibentuk dengan menyambungkan beberapa jam awal dari successive operational model runs yang terus diinisialisasi menggunakan observasi aktual. Untuk IFS HRES 9 km, arsipnya tersedia sejak 2017 sehingga ketiga event Anda 2022, 2023, dan 2024 tercakup. [Open Meteo](https://open-meteo.com/en/docs/historical-forecast-api?utm_source=chatgpt.com)

Jadi saya **tidak akan langsung menyatakan `archive-api ECMWF IFS` pasti lebih baik daripada Historical Forecast IFS**.

Sebaliknya, menurut saya ini harus menjadi eksperimen kecil.

Dan justru ini bisa memperkuat metodologi skripsi Anda.

---

# Menurut saya prioritas selanjutnya bukan mengubah kode Schaefer

Sekarang kita perlu menentukan:

\[
\boxed{
\text{produk atmosfer terbaik untuk kasus hilal Indonesia}
}
\]

bukan secara reputasi global, tetapi berdasarkan data Anda sendiri.

Saya menyarankan membandingkan paling tidak:

| Kandidat | Kode |
|---|---|
| IFS Historical Weather / Analysis | yang sekarang |
| IFS Historical Forecast | kandidat pembanding utama |
| ERA5 atau ERA5-Land | baseline reanalysis |

Kemudian bandingkan dengan data observasi meteorologi BMKG yang tersedia.

Untuk setiap waktu observasi:

\[
T_\text{model}-T_\text{obs}
\]

\[
RH_\text{model}-RH_\text{obs}
\]

dan jika tersedia:

\[
P_\text{model}-P_\text{obs}.
\]

Metric minimal:

\[
ME=\frac1n\sum(M-O)
\]

\[
MAE=\frac1n\sum|M-O|
\]

\[
RMSE=
\sqrt{\frac1n\sum(M-O)^2}.
\]

Baru setelah itu kita boleh mengatakan:

> “IFS dipilih karena memberikan performa terbaik pada data lokasi dan waktu observasi hilal yang digunakan.”

Itu jauh lebih kuat daripada:

> “IFS dipilih karena resolusinya 9 km.”

---

# Ada satu persoalan yang menurut saya bahkan lebih mendesak: bias correction

Di `core_multi_location.py`, dataset 31 observasi Anda masih membawa nilai seperti:

```python
bias_t = -1
bias_rh = 2
```

atau:

```python
bias_t = -4
bias_rh = 10
```

dan sebagainya.

Secara kode mekanismenya sudah benar:

\[
T_\text{corrected}
=
T_\text{IFS}-bias_T
\]

\[
RH_\text{corrected}
=
RH_\text{IFS}-bias_{RH}.
\]

Tetapi pertanyaan fundamentalnya adalah:

> **bias tersebut berasal dari validasi ECMWF IFS yang sekarang digunakan atau bukan?**

Kalau angka bias itu berasal dari:

- ERA5,
- NASA POWER/MERRA-2,
- penelitian terdahulu dengan model lain,
- rerata regional suatu jurnal,
- atau data yang tidak identik dengan Open-Meteo IFS 9 km,

maka menurut saya **jangan diterapkan ke IFS**.

Karena:

\[
bias_\text{ERA5}
\neq
bias_\text{IFS}.
\]

Bahkan:

\[
bias_\text{IFS,Semarang}
\]

belum tentu sama dengan:

\[
bias_\text{IFS,Kupang}.
\]

Dan bias dapat berubah secara:

\[
f(location,season,time\ of\ day,elevation).
\]

Jadi sebelum kita lanjut, saya justru menyarankan membuat **baseline IFS tanpa bias**:

\[
bias_T=0
\]

\[
bias_{RH}=0.
\]

Kemudian estimasi bias dari validasi terhadap BMKG.

Ini menurut saya lebih fundamental daripada pemilihan antara dua endpoint tadi.

---

# Satu penyempurnaan fisik untuk RH

Sekarang data IFS yang Anda minta adalah:

```python
temperature_2m
relative_humidity_2m
surface_pressure
dew_point_2m
```

Open-Meteo menjelaskan bahwa ECMWF sebenarnya menyediakan native:

\[
T_{2m}
\]

dan:

\[
T_{d,2m},
\]

sedangkan:

\[
RH_{2m}
\]

dihitung Open-Meteo dari \(T\) dan \(T_d\). `surface_pressure` juga merupakan derived variable dari MSL pressure, temperature, dan terrain elevation. [Open Meteo](https://open-meteo.com/en/docs/ecmwf-api?utm_source=chatgpt.com)

Sekarang Anda melakukan interpolasi:

\[
T(t)
\]

\[
RH(t)
\]

\[
P(t)
\]

secara independen.

Itu **tidak salah secara praktis**, terutama karena intervalnya hanya satu jam.

Tetapi kalau kita ingin benar-benar konsisten secara termodinamika, cara yang lebih elegan adalah:

\[
T_i,T_{d,i}
\rightarrow
\text{interpolasi}
\rightarrow
T(t),T_d(t)
\]

kemudian hitung:

\[
RH(t)=f(T(t),T_d(t)).
\]

Open-Meteo sendiri memakai formulasi berbentuk:

\[
RH=
100
\frac{
\exp\left(\frac{17.625T_d}{243.04+T_d}\right)
}{
\exp\left(\frac{17.625T}{243.04+T}\right)
}.
\]

Formula ini terlihat langsung dalam source code Open-Meteo. [GitHub](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Helper/Meteorology.swift?utm_source=chatgpt.com)

Jadi daripada dew point hanya menjadi metadata audit, kita dapat menggunakannya untuk menjaga konsistensi:

\[
\boxed{T,T_d\rightarrow RH}
\]

Saya **belum menyebut perubahan ini wajib**. Lebih baik kita tes dahulu:

\[
\Delta RH
=
RH_{\text{linear direct}}
-
RH_{T/T_d}.
\]

Kalau perbedaannya cuma misalnya \(0.05\%\), tidak ada manfaat praktis mengubah arsitektur. Kalau beberapa persen pada twilight tropis, baru layak diubah.

---

# Saya juga akan memperketat sanity check

Sekarang validator atmosfer menerima secara umum:

```python
temperature > -273.15
pressure > 0
```

Secara matematis benar, tapi nilai seperti:

\[
T=400^\circ C
\]

atau:

\[
P=15\ {\rm hPa}
\]

masih dianggap valid.

Untuk proyek khusus observasi permukaan di Indonesia, saya lebih suka soft physical bounds, misalnya:

\[
-20<T<60^\circ C
\]

dan mungkin:

\[
700<P<1100\ {\rm hPa}.
\]

Atau kalau ingin library tetap general:

\[
-100<T<70^\circ C
\]

\[
300<P<1100\ {\rm hPa}.
\]

Tujuannya bukan untuk modelling, melainkan menangkap kesalahan unit atau respons API yang aneh.

Ini minor dibanding persoalan pemilihan dataset dan bias.

---

# Ada satu output yang menurut saya masih perlu ditambahkan

Saya cek `hitung_visibilitas_pada_waktu()`, dan sekarang bagus karena hasil tiap timestep sudah menyimpan:

```python
'rh': rh,
'temperature': temperature,
'pressure': pressure,
```

Tetapi di `core_multi_location.py`, tabel utama masih terutama mengekspor:

```text
RH
T
```

sementara \(P\) lebih banyak hidup di provenance JSON.

Karena pressure benar-benar digunakan untuk:

\[
P,T
\rightarrow \text{refraksi}
\rightarrow h_\mathrm{Moon},h_\mathrm{Sun},
\]

saya akan menambahkan:

```text
P_Sunset
P_NE_Optimal
P_Tel_Optimal
```

ke CSV/XLSX utama juga.

JSON tetap menjadi sumber audit lengkap, tetapi tabel hasil penelitian sebaiknya menunjukkan ketiga input atmosfer utama:

\[
\boxed{RH,\;T,\;P}.
\]

---

## Tentang provenance JSON: saya suka desain ini

Struktur sekarang sudah cukup kuat untuk reproducibility.

Contohnya menyimpan:

```text
requested_latitude
requested_longitude
requested_elevation
returned latitude/longitude
effective elevation
model
endpoint
cell_selection
units
retrieved_at_utc
hourly_raw
dew_point_2m
```

Ini penting khususnya karena banyak site Anda berada di pantai.

Open-Meteo menjelaskan bahwa `cell_selection` default/land selection bisa memilih grid cell beberapa kilometer dari koordinat requested, dan elevation parameter digunakan untuk statistical downscaling. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api?utm_source=chatgpt.com)

Untuk lokasi seperti:

- Lhoknga,
- Loang Baloq,
- Cikelet,
- Kupang,
- Manado,

saya ingin nanti melihat:

\[
\Delta d=
distance(
lat_\text{site},lon_\text{site},
lat_\text{grid},lon_\text{grid})
\]

karena **coastal grid selection dapat menjadi sumber error yang lebih besar daripada interpolasi waktu**.

Jadi `cell_selection="land"` adalah pilihan yang masuk akal, tetapi nanti perlu sanity check untuk beberapa site pantai terhadap:

```text
land
nearest
```

Tidak harus semua 31 data.

---

# Tentang 67 tes

Saya tidak bisa mengklaim menjalankan test suite lokal Anda dari GitHub connector, tetapi secara statis coverage atmosfernya sekarang memang jauh lebih kuat.

Ada satu catatan bookkeeping kecil: pada branch `main` yang saya baca sekarang, saya menghitung:

- `test_atmosfer_ecmwf_ifs.py`: **24** method `test_*`;
- `test_lunar_geometry.py`: **24**;
- `test_model_interfaces.py`: **21**.

Secara statis totalnya **69 method test**. Jadi jika run lokal Anda melaporkan 67, ada kemungkinan checkout lokal saat menjalankan tes sedikit berbeda dari commit yang sekarang ada di GitHub, atau ada detail discovery lain. Ini bukan masalah ilmiah, tapi sebelum menetapkan commit “baseline skripsi”, saya akan menjalankan ulang:

```bash
python -X utf8 -m unittest discover -s tests -v
```

pada commit yang persis sama dengan `main`.

---

# Posisi saya sekarang

Untuk **implementasi pengambilan IFS**, sebagian besar concern teknis saya sebelumnya sudah selesai.

Saya akan menilai statusnya seperti ini:

| Bagian | Status |
|---|---|
| Pin ECMWF IFS | ✅ |
| Validasi model respons | ✅ |
| Actual site elevation | ✅ |
| `cell_selection=land` eksplisit | ✅ |
| UTC normalization | ✅ |
| Unit/variable validation | ✅ |
| Hourly full-window interpolation | ✅ |
| No extrapolation/freeze | ✅ |
| Bias sesudah interpolasi | ✅ teknis |
| Fail-closed, no fake weather | ✅ |
| Raw provenance | ✅ |
| Dew point disimpan | ✅ |
| Pressure masuk timestep calculation | ✅ |
| Pressure di tabel utama | ⚠️ sebaiknya ditambah |
| RH interpolation thermodynamic | 🟡 perlu sensitivity test |
| Bias IFS secara ilmiah | **🔴 belum tervalidasi** |
| Historical Weather vs Historical Forecast IFS | **🔴 perlu dibandingkan** |
| Coastal grid selection | 🟡 perlu spot validation |

Jadi saya **belum akan menyentuh Schaefer–Kastner**.

Tahap paling logis sekarang adalah membuat **validasi sumber atmosfer**. Kita bandingkan raw IFS Historical Weather, IFS Historical Forecast, dan kalau perlu ERA5 terhadap data BMKG pada kasus yang tersedia. Setelah itu kita bisa menjawab dengan data, bukan asumsi:

\[
\boxed{\text{dataset atmosfer mana yang memang paling tepat untuk skripsi Anda}}
\]

dan sekaligus menentukan apakah **bias correction perlu sama sekali**. Setelah keputusan itu selesai, barulah lapisan input penelitian benar-benar dapat dianggap fixed.