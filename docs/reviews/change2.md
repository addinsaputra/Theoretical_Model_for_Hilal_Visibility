Saya setuju: **sekarang jangan masuk dulu ke Schaefer → Kastner**. Lapisan berikutnya yang harus “dibekukan” adalah atmosfer, karena RH dan T masuk langsung ke extinction Schaefer, sedangkan P memengaruhi refraksi/posisi apparent dalam pipeline Anda.

Saya sudah membuka repo baru `addinsaputra/Theoretical_Model_for_Hilal_Visibility`, khususnya `Core/atmosfer_ecmwf_ifs.py`, `core_crescent_visibility.py`, `visual_limit_schaefer.py`, dan struktur tesnya. Kesimpulan awal saya cukup tegas:

> **Memakai ECMWF IFS sebagai kandidat sumber atmosfer utama masuk akal, tetapi implementasi IFS di repo saat ini belum bisa dianggap final. Ada beberapa persoalan fundamental pada pengambilan datanya.**

## 1. Hal paling penting: sekarang kode Anda belum benar-benar mengunci ECMWF IFS

Di `atmosfer_ecmwf_ifs.py`, request-nya pada dasarnya:

```python
url = "https://archive-api.open-meteo.com/v1/archive"

params = {
    "latitude": latitude,
    "longitude": longitude,
    "start_date": start_date,
    "end_date": end_date,
    "hourly": hourly_variables,
    "timezone": timezone,
}
```

Tidak ada:

```python
"models": "ecmwf_ifs"
```

Ini sangat penting.

Open-Meteo menyatakan bahwa Historical Weather API secara default memakai **Best Match**, dan Best Match menggabungkan:

\[
\boxed{\text{IFS HRES + ERA5 + ERA5-Land}}
\]

secara seamless. Untuk benar-benar meminta IFS, model harus dipilih secara eksplisit. [open-meteo.com](https://open-meteo.com/en/docs/historical-weather-api)

Jadi sekarang nama file:

```text
atmosfer_ecmwf_ifs.py
```

dan label:

```text
ECMWF IFS
```

belum menjamin data yang dikembalikan memang IFS.

Ini menurut saya **critical issue #1**.

Seharusnya minimal:

```python
params = {
    ...
    "models": "ecmwf_ifs",
}
```

Open-Meteo memang menyediakan identifier resmi `ecmwf_ifs`. [GitHub](https://github.com/open-meteo/open-meteo/blob/main/openapi/historical-weather.yml?utm_source=chatgpt.com)

---

## 2. IFS yang Anda ambil sebenarnya bukan “raw ECMWF variables” sepenuhnya

Ini temuan penting kedua.

Anda meminta:

```python
[
    "temperature_2m",
    "relative_humidity_2m",
    "surface_pressure",
]
```

Sekilas terlihat seperti ketiganya langsung berasal dari ECMWF IFS. Ternyata tidak.

Untuk IFS, ECMWF secara native menyediakan antara lain:

\[
T_{2m}
\]

dan

\[
T_{d,2m}
\]

(dew-point temperature).

Open-Meteo menjelaskan bahwa **relative humidity 2 m dihitung dari temperature dan dew point**, bukan merupakan field native IFS yang langsung diteruskan. [Open Meteo](https://open-meteo.com/en/docs/ecmwf-api)

Jadi:

\[
\boxed{
RH_{2m,\ OpenMeteo}
=
f(T_{2m,\ IFS}, T_{d,2m,\ IFS})
}
\]

Ini bukan masalah secara otomatis. Secara meteorologis itu sah.

Tetapi dalam skripsi nanti jangan menulis:

> “RH diperoleh langsung dari ECMWF IFS.”

Lebih akurat:

> “RH 2 m diperoleh melalui Open-Meteo dari temperature dan dew-point temperature ECMWF IFS.”

---

## 3. `surface_pressure` juga bukan sekadar field IFS mentah dalam jalur Open-Meteo ini

Yang lebih menarik lagi, dokumentasi Open-Meteo menjelaskan bahwa `surface_pressure` mereka untuk ECMWF dihitung dari:

- mean sea-level pressure,
- temperature 2 m,
- terrain elevation. [Open Meteo](https://open-meteo.com/en/docs/ecmwf-api)

Dengan kata lain:

\[
P_s
=
f(P_{MSL},T_{2m},h).
\]

Padahal ECMWF sendiri sebenarnya memiliki parameter native:

```text
sp = surface pressure
```

dan parameter ini tercantum dalam katalog data ECMWF. [ECMWF](https://www.ecmwf.int/en/forecasts/datasets/open-data)

Jadi ada perbedaan antara:

\[
P_{s,\mathrm{ECMWF\ native}}
\]

dan

\[
P_{s,\mathrm{OpenMeteo\ derived}}.
\]

Sekali lagi, derived bukan berarti salah. Tetapi **provenance-nya harus jelas**.

---

# 4. Masalah yang lebih serius: elevasi observatorium tidak dikirim ke API

`ObservingLocation` Anda sudah menyimpan:

```python
altitude
```

dan database lokasi Anda bahkan memiliki elevasi aktual masing-masing site.

Tetapi `fetch_hourly_weather()` hanya mengirim:

```python
latitude
longitude
```

tanpa:

```python
elevation=location.altitude
```

Ini menurut saya **critical issue #2**.

Open-Meteo secara eksplisit mengatakan bahwa parameter `elevation` digunakan untuk statistical downscaling. Kalau tidak diberikan, mereka memakai DEM 90 m dan bahkan dapat memilih grid cell daratan dengan elevasi yang dianggap sesuai. `surface_pressure` juga berubah mengikuti elevasi. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api)

Bayangkan lokasi:

```text
POB Lembang
elevation ≈ 1258 m
```

versus pantai:

```text
elevation ≈ 1–5 m
```

Untuk tekanan:

\[
P(1258\,m)
\]

tentu sangat berbeda dari:

\[
P(0\,m).
\]

Anda **sudah memiliki elevasi observatorium yang jauh lebih tepat daripada DEM otomatis**, jadi API seharusnya menerimanya.

Saya akan mengubah interface menjadi:

```python
fetch_hourly_weather(
    latitude,
    longitude,
    elevation,
    ...
)
```

dan request:

```python
params = {
    "latitude": latitude,
    "longitude": longitude,
    "elevation": elevation,
    ...
    "models": "ecmwf_ifs",
}
```

---

# 5. Untuk banyak lokasi Anda yang berada di pantai, pemilihan grid cell juga penting

Database lokasi Anda banyak sekali berisi:

- pantai,
- dermaga,
- rooftop dekat pantai,
- menara suar,
- pulau kecil.

Open-Meteo default:

```text
cell_selection = land
```

dan bukan sekadar nearest grid cell. Sistem dapat memilih land grid cell dengan elevasi yang dianggap cocok. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api?utm_source=chatgpt.com)

Ini sebenarnya masuk akal untuk observatorium di darat, tetapi harus dibuat **eksplisit**:

```python
"cell_selection": "land"
```

daripada bergantung pada default tersembunyi.

Untuk penelitian Anda saya cenderung memilih:

\[
\boxed{\texttt{cell\_selection="land"}}
\]

karena objeknya pengamat yang berdiri di daratan, termasuk site pantai.

Tapi yang jauh lebih penting adalah menyimpan metadata:

\[
(lat_{requested},lon_{requested})
\]

dan

\[
(lat_{returned},lon_{returned},h_{returned}).
\]

Sekarang fungsi:

```python
get_location_info()
```

sudah ada, tetapi metadata itu praktis tidak ikut masuk ke pipeline utama.

Padahal untuk audit ilmiah sangat berguna.

---

# 6. Fallback RH=80%, T=25°C, P=1013.25 adalah hal yang harus kita hapus

Sekarang di `core_crescent_visibility.py`, jika ECMWF gagal:

```python
except ECMWF_IFSAPIError:
    ...
    rh_raw, temperature_raw, pressure = 80.0, 25.0, 1013.25
```

Bagi aplikasi umum, fallback seperti ini mungkin ramah pengguna.

Bagi **penelitian**, ini berbahaya.

Misalnya satu data 2022 gagal diambil.

Program tetap menghasilkan:

\[
RH=80\%
\]

\[
T=25^\circ C
\]

\[
P=1013.25\ {\rm hPa}
\]

lalu Schaefer menghitung extinction dan sky brightness seolah-olah angka itu observasi nyata.

Akibatnya Anda bisa mendapat:

```text
prediction = tidak terlihat
```

dan membandingkannya dengan BMKG, padahal atmospheric input-nya sebenarnya fabricated.

Saya menyarankan:

\[
\boxed{\text{API failure} \Rightarrow \text{record invalid / raise error}}
\]

bukan default meteorologi.

Untuk penelitian, **missing data lebih baik daripada synthetic data yang tidak ditandai**.

---

# 7. Ada bug desain lain pada mode optimal: atmosfer membeku setelah +1 jam

Ini tidak terlihat di modul IFS sendiri tetapi muncul ketika masuk ke `core_crescent_visibility.py`.

Sekarang Anda fetch atmosfer pada:

\[
t_0 = sunset
\]

dan

\[
t_1 = sunset+1h.
\]

Kemudian semua timestep optimal diinterpolasi menggunakan kedua titik itu.

Masalahnya `_interpolasi_atmosfer()` melakukan:

```python
frac = max(
    0.0,
    min(
        1.0,
        (t - t0).total_seconds() / total
    )
)
```

Artinya untuk:

\[
t > sunset + 1h
\]

akan selalu:

\[
frac=1.
\]

Jadi:

\[
RH(t)=RH(t_1)
\]

\[
T(t)=T(t_1)
\]

\[
P(t)=P(t_1)
\]

selamanya setelah satu jam.

Padahal loop Anda bisa berjalan sampai:

```python
max_steps = 120
```

atau sekitar **2 jam**.

Jadi setelah +60 menit:

\[
\boxed{\text{atmosfer menjadi frozen}}
\]

Ini **critical issue #3** untuk mode optimal.

Solusinya bukan menambah +2 jam secara hard-coded.

Lebih bersih:

\[
\boxed{
\text{ambil hourly series untuk seluruh observation window}
}
\]

misalnya:

```text
09 UTC
10 UTC
11 UTC
12 UTC
13 UTC
```

lalu setiap timestep mencari pasangan jam terdekat:

\[
[t_i,t_{i+1}]
\]

dan melakukan interpolasi:

\[
X(t)
=
X_i+
\frac{t-t_i}{t_{i+1}-t_i}
(X_{i+1}-X_i).
\]

Ini jauh lebih benar.

---

# 8. Interpolasi linear ke waktu sunset sendiri masuk akal

Bagian ini menurut saya tidak bermasalah.

Data historical IFS dari Open-Meteo disediakan hourly, sedangkan sunset misalnya terjadi:

\[
10:42:15\ UTC.
\]

Jadi mengambil:

\[
X_{10:00}
\]

dan:

\[
X_{11:00}
\]

kemudian:

\[
X(10{:}42{:}15)
=
X_{10}
+
f(X_{11}-X_{10})
\]

adalah pendekatan yang wajar untuk:

- T,
- RH,
- P.

Open-Meteo juga menyatakan T2m, RH2m, dan surface pressure adalah **instantaneous variables** pada timestamp tersebut. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api)

Jadi konsep interpolasinya boleh dipertahankan.

Yang harus dibuang adalah pola “hanya dua titik untuk seluruh malam”.

---

# 9. Tidak ada bug satuan tekanan

Ini kabar baik.

Open-Meteo mengembalikan:

\[
P_s\ [hPa].
\]

Kode Anda menyebutnya:

```text
mbar
```

Tetapi:

\[
\boxed{1\ hPa = 1\ mbar}
\]

secara numerik.

Jadi:

```text
1007.3 hPa
```

sama numeriknya dengan:

```text
1007.3 mbar.
```

Tidak perlu konversi.

---

# 10. Satu hal yang perlu kita sadari: P saat ini tidak masuk langsung ke Schaefer

Saya cek `visual_limit_schaefer.py`.

Function signature-nya:

```python
hitung_sky_brightness(
    ...
    humidity,
    temperature,
    latitude,
    elevation,
    alt_objek,
)
```

Tidak ada:

```python
pressure
```

Rayleigh extinction-nya masih dihitung dari:

\[
K_R
=
0.1066
e^{-h/8200}
\left(\frac{\lambda}{0.55}\right)^{-4}.
\]

Jadi dalam pipeline sekarang:

\[
RH,T
\]

langsung memengaruhi extinction Schaefer, sedangkan:

\[
P
\]

terutama dipakai untuk **refraction Skyfield**:

\[
P,T
\rightarrow
h_{\rm apparent}.
\]

Artinya prioritas ketelitian atmosfer kita saat ini:

\[
\boxed{RH \approx T > P}
\]

untuk Schaefer sendiri.

Bukan berarti P tidak penting, tetapi jangan mengira P sekarang masuk ke persamaan extinction Schaefer—belum.

---

# 11. Apakah ECMWF IFS memang “yang terbaik”?

Di sini saya ingin sedikit mengoreksi kesimpulan awal.

Saya setuju bahwa **IFS sangat layak sebagai kandidat utama**. Open-Meteo menyediakan historical IFS HRES dengan resolusi sekitar **9 km**, hourly, dari 2017 sampai sekarang, sementara ERA5 sekitar 0.25°/~25 km. Open-Meteo bahkan menyatakan historical IFS mereka sebagai dataset dengan resolusi dan presisi tertinggi untuk kondisi cuaca historis global. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api)

Tetapi:

\[
\boxed{\text{IFS terbaik secara global}}
\]

tidak otomatis berarti:

\[
\boxed{\text{IFS terbaik untuk RH/T di 82 site hilal Indonesia}}
\]

ECMWF sendiri mencatat bahwa error T2m tergantung:

- geography,
- altitude,
- season,
- time of day,
- kompleksitas topografi,
- coastal land/sea mask. [ECMWF Confluence](https://confluence.ecmwf.int/spaces/FUG/pages/673551653/Section%2B9.2.1.1%2BCauses%2Bof%2Berrors%2Bin%2B2m%2Btemperature?utm_source=chatgpt.com)

Dan ini sangat relevan bagi dataset Anda karena banyak site justru:

> pantai + pulau kecil + pegunungan + rooftop pesisir.

Bahkan verifikasi ECMWF terbaru menyatakan ECMWF tidak selalu menjadi yang terbaik untuk **surface parameters pada short range**, walaupun kemampuan model globalnya sangat tinggi. [ECMWF](https://www.ecmwf.int/en/about/media-centre/news/2026/2025-forecast-evaluation?utm_source=chatgpt.com)

Ada juga penelitian RH di Vietnam yang menemukan keterbatasan representasi 2-m dewpoint di wilayah tropis meskipun ECMWF secara keseluruhan tetap skilful. [DOI](https://doi.org/10.1002/met.70159?utm_source=chatgpt.com)

Jadi untuk skripsi, saya tidak akan menulis:

> “IFS dipilih karena merupakan model cuaca paling akurat.”

Saya akan menulis lebih hati-hati:

> **IFS dipilih sebagai kandidat utama karena resolusi spasialnya tinggi, tersedia hourly, mencakup seluruh lokasi penelitian, dan memiliki performa NWP global yang kuat; akurasi lokal parameter T dan RH tetap dievaluasi terhadap data observasi.**

Itu lebih ilmiah.

---

# 12. IFS atau ERA5 untuk penelitian Anda?

Menurut saya ini harus ditentukan berdasarkan **tujuan dataset**, bukan reputasi model.

| Tujuan | Lebih cocok |
|---|---|
| Rekonstruksi keadaan atmosfer aktual 2022–2024 dengan detail spasial tinggi | **IFS historical 9 km** |
| Reanalysis homogen untuk studi jangka panjang | **ERA5** |
| Analisis iklim/dekadal | **ERA5** |
| Input T/RH lokal per kejadian hilal | **IFS layak menjadi kandidat utama** |
| Klaim “paling akurat di lokasi BMKG Indonesia” | Harus divalidasi dahulu |

Open-Meteo sendiri memperingatkan bahwa ERA5 lebih cocok ketika konsistensi antar-dekade penting, karena operational IFS mengalami model upgrades. [Open Meteo](https://open-meteo.com/en/docs/historical-weather-api)

Karena penelitian Anda hanya beberapa tahun, **2022–2024**, saya tidak terlalu khawatir terhadap homogenitas dekadal.

Saya justru lebih peduli terhadap:

\[
\text{coastal grid}
+
\text{site elevation}
+
\text{RH/T bias lokal}.
\]

---

# 13. Bentuk atmosfer yang menurut saya ideal untuk proyek ini

Saya ingin layer atmosfer Anda nanti mempunyai kontrak seperti:

\[
\boxed{
(\phi,\lambda,h,t)
\rightarrow
(T_{2m},T_{d,2m},RH_{2m},P_s)
}
\]

beserta metadata:

\[
\boxed{
\text{model, grid lat/lon, grid elevation, valid time, source}
}
\]

Saya bahkan akan mengambil **dew point juga**, walaupun Schaefer tidak memerlukannya.

Mengapa?

Karena nanti kita bisa sanity-check:

\[
RH
\overset{?}{=}
f(T,T_d)
\]

dan mendeteksi nilai atmosfer yang aneh.

---

## Prioritas perbaikannya

Kalau kita melanjutkan audit ini, urutan yang saya rekomendasikan hanya satu:

1. **pin `models="ecmwf_ifs"`**;
2. kirim **actual site elevation** ke API;
3. hapus fallback RH/T/P palsu;
4. redesign fetch menjadi **hourly atmospheric window**, bukan sunset + 1 h;
5. simpan provenance: requested/returned coordinate, elevation, model, timestamps dan hourly raw values;
6. tambahkan `dew_point_2m` untuk validation;
7. tambahkan tes khusus atmosfer;
8. baru lakukan **validation IFS vs BMKG/ERA5** sebelum menetapkan IFS sebagai final primary dataset.

Dan ada satu hal dokumentasi: README repo baru masih mempunyai beberapa sisa istilah **ERA5** serta contoh `sumber_atmosfer='era5'`, sedangkan dispatcher sekarang memakai `ecmwf_ifs`. Itu perlu dibereskan setelah keputusan atmosfer final.