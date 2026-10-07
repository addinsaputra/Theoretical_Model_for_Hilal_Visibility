Ya, revisinya **sudah jauh lebih baik** dibanding versi yang masih ada di GitHub. Dua masalah utama yang kita bahas sebelumnya—semidiameter berbasis PyMeeus dan phase angle yang dihitung manual—sudah Anda perbaiki dengan arah yang tepat. Saya juga melakukan pemeriksaan sintaks; file berhasil melewati `py_compile`, jadi secara sintaks Python tidak ada error. Saya belum bisa menjalankan uji numerik Skyfield+DE440s di lingkungan ini karena paket Skyfield/berkas DE440s tidak tersedia di runtime saya, jadi penilaian numeriknya saya cocokkan dengan dokumentasi resmi Skyfield/JPL.

Namun, saya menemukan **dua hal ilmiah yang masih cukup penting untuk diperbaiki sebelum file ini saya anggap final**: definisi phase angle yang sekarang masih memakai posisi `apparent`, dan rumus crescent width yang masih diturunkan dari elongasi. Ada juga beberapa perbaikan sekunder.

## 1. Semidiameter: revisi Anda sudah benar

Anda sekarang menetapkan:

```python
MOON_RADIUS_KM = 1737.4
```

dan menghitung:

```python
np.degrees(np.arcsin(MOON_RADIUS_KM / distance_km))
```

kemudian jaraknya berasal dari:

```python
moon_apparent.distance().km
```

Ini sudah menggantikan metode lama berbasis `PyMeeus → parallax → SD`. data_hisab data_hisab

Secara matematis:

\[
SD=\arcsin\left(\frac{R_\mathrm{Moon}}{\Delta}\right)
\]

dan ini persis pendekatan yang dicontohkan dokumentasi resmi Skyfield ketika menghitung angular diameter dari radius fisik dan jarak objek. [Rhodes Mill](https://rhodesmill.org/skyfield/examples.html?utm_source=chatgpt.com)

Konstanta:

\[
R_\mathrm{Moon}=1737.4\ {\rm km}
\]

juga valid. JPL mencantumkan mean radius Bulan 1737,4 km, dan dokumentasi lunar JPL bahkan merekomendasikan model bola dengan radius tersebut. [JPL Solar System Dynamics](https://ssd.jpl.nasa.gov/sats/phys_par/?utm_source=chatgpt.com)

Jadi bagian ini:

\[
\boxed{\text{SUDAH BENAR}}
\]

dan menurut saya jauh lebih defensible untuk skripsi daripada implementasi PyMeeus sebelumnya.

Terlebih lagi, ketika `location` diberikan, jaraknya menjadi topocentric:

```python
observer = ephem["Earth"] + location
...
moon_apparent = observer_at.observe(ephem["Moon"]).apparent()
```

sehingga semidiameter juga berubah sedikit sesuai posisi pengamat. data_hisab

Itu cocok dengan kebutuhan visibilitas hilal.

---

# 2. Helper `_lunar_observation_utc()` adalah perbaikan desain yang bagus

Ini menurut saya keputusan desain terbaik dalam revisi ini:

```python
def _lunar_observation_utc(...):
    ...
    observer = ephem["Earth"] if location is None else ephem["Earth"] + location
    observer_at = observer.at(t)
    moon_apparent = observer_at.observe(ephem["Moon"]).apparent()
```

data_hisab

Sebelumnya beberapa fungsi membangun geometri Bulan secara terpisah. Sekarang Anda mulai memakai satu sumber geometri yang sama.

Ini bagus karena mengurangi risiko:

\[
\text{SD dari model A}
+
\text{elongasi dari model B}
+
\text{phase dari model C}.
\]

Tetapi saya justru menyarankan helper ini disempurnakan sedikit lagi. Saya akan kembali ke masalah tersebut pada bagian phase angle.

---

# 3. Elongasi: sudah benar, jangan diubah

Fungsi Anda masih:

```python
m = (earth + location).at(t).observe(moon).apparent()
s = (earth + location).at(t).observe(sun).apparent()

return s.separation_from(m).degrees
```

data_hisab

Ini adalah:

\[
E=\angle(S-O-M)
\]

dengan observer berada pada lokasi pengamatan.

Karena keduanya menggunakan:

```python
.observe(...).apparent()
```

yang Anda dapat adalah **topocentric apparent elongation**.

Itu sangat tepat kalau elongasi dimaksudkan sebagai separation yang benar-benar tampak di langit. Horizons Quantity #23 juga didefinisikan sebagai apparent Sun–Observer–Target elongation pada lokasi pengamat. [JPL Solar System Dynamics](https://ssd.jpl.nasa.gov/horizons/manual.html)

Jadi:

\[
\boxed{\text{elongation: pertahankan}}
\]

Tidak perlu Horizons API untuk menggantikannya.

---

# 4. Phase angle: implementasinya sudah jauh lebih baik, tetapi ada satu detail penting

Sekarang Anda melakukan:

```python
_, _, moon_apparent = _lunar_observation_utc(...)

return moon_apparent.phase_angle(ephem["Sun"]).degrees
```

data_hisab

Penggunaan native:

```python
.phase_angle(sun)
```

adalah keputusan yang benar.

Skyfield mendefinisikan fungsi tersebut sebagai:

\[
\boxed{\text{Sun-target-observer}}
\]

atau untuk Bulan:

\[
\alpha=\angle(S-M-O)
\]

dengan:

- \(0^\circ\) = full moon,
- \(180^\circ\) = new moon/dark side. [Rhodes Mill](https://rhodesmill.org/skyfield/api-position.html?utm_source=chatgpt.com)


Jadi Anda sudah tidak perlu lagi dot-product manual.

Tetapi ada satu persoalan:

```python
moon_apparent
```

berasal dari:

```python
.observe(moon).apparent()
```

Sedangkan untuk **physical phase angle** yang dipakai dalam model luminansi Kastner, menurut saya sebaiknya kita memakai **astrometric phase angle**, bukan apparent phase angle.

Mengapa?

Skyfield membedakan:

```text
observe()
```

sebagai astrometric position dengan light-time correction, sementara:

```text
.apparent()
```

kemudian menambahkan efek seperti aberration dan gravitational light deflection. [Rhodes Mill](https://rhodesmill.org/skyfield/api-position.html?utm_source=chatgpt.com)

Ini juga persis perbedaan yang dibuat Horizons.

Horizons Quantity #24, Sun–Target–Observer, memasukkan stellar aberration dan karena itu bisa berbeda beberapa arcsecond dari true phase angle. JPL menjelaskannya secara eksplisit. [JPL Solar System Dynamics](https://ssd.jpl.nasa.gov/horizons/manual.html)

Sedangkan Horizons Quantity #43 memberikan:

\[
\boxed{\text{true PHASE ANGLE}}
\]

pada lokasi observer. [JPL Solar System Dynamics](https://ssd.jpl.nasa.gov/horizons/manual.html)

Untuk model photometric Kastner, yang kita perlukan secara konseptual adalah geometri illumination:

\[
\boxed{\alpha_\mathrm{true}}
\]

bukan perubahan arah citra karena aberration.

Jadi saya akan sedikit mengubah arsitektur helper Anda menjadi:

```python
observer_at = observer.at(t)

moon_astrometric = observer_at.observe(ephem["Moon"])
moon_apparent = moon_astrometric.apparent()
```

lalu keduanya disimpan.

Kemudian:

```python
phase_angle = moon_astrometric.phase_angle(ephem["Sun"]).degrees
```

sedangkan altitude, azimuth, dan apparent elongation tetap memakai:

```python
moon_apparent
```

Dengan demikian Anda memiliki pemisahan fisik yang sangat bersih:

| Besaran | Posisi |
|---|---|
| Altitude / azimuth | `apparent()` |
| Apparent elongation | `apparent()` |
| Phase angle untuk Kastner | `astrometric` |
| Illumination geometry | `astrometric` |
| Jarak untuk SD | astrometric range |
| Refraction | setelah alt/az |

Ini menurut saya perubahan paling penting berikutnya.

---

# 5. Crescent width: ini justru masalah utama yang tersisa

Sekarang kode Anda menghitung:

```python
elongation_deg = sun_apparent.separation_from(moon_apparent).degrees
...
width_deg = semidiameter_deg * (
    1.0 - np.cos(np.radians(elongation_deg))
)
```

data_hisab

Secara historis rumus seperti ini memang banyak digunakan:

\[
W=SD(1-\cos E).
\]

Tetapi setelah Anda sekarang sudah mempunyai **phase angle yang benar**, sebaiknya jangan lagi menurunkan width dari elongasi.

Kenapa?

Untuk spherical Moon, illuminated fraction adalah:

\[
k=\frac{1+\cos\alpha}{2}.
\]

Skyfield sendiri memakai hubungan ini untuk `fraction_illuminated()`. [Rhodes Mill](https://rhodesmill.org/skyfield/api-position.html?utm_source=chatgpt.com)

Lebar bagian yang diterangi sepanjang garis Sun-Moon kemudian:

\[
W = D\,k
\]

dengan:

\[
D=2SD.
\]

Sehingga:

\[
\boxed{
W=SD(1+\cos\alpha)
}
\]

atau bahkan lebih sederhana:

\[
\boxed{
W=2SD\,k
}
\]

Karena Anda sudah menghitung:

```python
illumination_pct
```

cara yang paling konsisten adalah:

```python
illumination_fraction = illumination_pct / 100.0
width_deg = 2.0 * semidiameter_deg * illumination_fraction
```

Ini jauh lebih bagus.

### Kenapa rumus lama hampir sama tetapi tidak identik?

Rumus lama:

\[
W=SD(1-\cos E)
\]

secara implisit mengasumsikan:

\[
\alpha=180^\circ-E.
\]

Kalau itu benar sempurna:

\[
\cos\alpha
=
-\cos E
\]

sehingga:

\[
SD(1+\cos\alpha)
=
SD(1-\cos E).
\]

Tetapi geometri Sun–Moon–observer bukan segitiga dengan Matahari di tak hingga. Matahari mempunyai jarak finite, dan untuk topocentric observer ada parallax pula.

Jadi secara persis:

\[
\boxed{
\alpha\neq180^\circ-E
}
\]

meskipun nilainya dekat.

Untuk hilal yang sangat tipis, perbedaan kecil pada sudut bisa relatif cukup berarti terhadap **crescent width yang memang sangat kecil**.

Karena width kemudian bisa masuk ke ukuran extended source dan akhirnya threshold Crumey, saya tidak ingin membiarkan inkonsistensi ini.

Jadi di sini rekomendasi saya cukup tegas:

\[
\boxed{
\textbf{ubah crescent width agar berasal dari phase angle / illuminated fraction}
}
\]

bukan dari elongasi.

---

# 6. Bahkan illumination Anda sekarang mengalami inkonsistensi kecil dengan width

Perhatikan:

```python
illumination_pct =
    moon_apparent.fraction_illuminated(ephem["Sun"]) * 100

width_deg =
    semidiameter_deg *
    (1.0 - cos(elongation_deg))
```

data_hisab

Jadi dalam fungsi yang sama:

\[
k
\]

ditentukan dari **phase angle**, sedangkan:

\[
W
\]

ditentukan dari **elongation**.

Padahal untuk spherical Moon seharusnya keduanya menggambarkan geometri yang sama:

\[
W=2SD\,k.
\]

Ini membuat sebuah sanity check sederhana:

\[
\boxed{
\frac{W}{2SD}\stackrel{?}{=}k
}
\]

tidak akan selalu persis terpenuhi.

Setelah Anda ubah menjadi:

```python
illumination_fraction = ...
width_deg = 2 * semidiameter_deg * illumination_fraction
```

maka hubungan tersebut otomatis selalu konsisten.

Menurut saya ini penting sekali untuk pipeline Kastner–Crumey Anda.

---

# 7. `set_location()` masih menggunakan `Topos` yang deprecated

Sekarang:

```python
location = api.Topos(
    lat_str,
    long_str,
    elevation_m=elevation
)
```

data_hisab

Skyfield sudah mendeprekasi `Topos` sejak lama dan merekomendasikan:

```python
api.wgs84.latlon(...)
```

Dokumentasi Skyfield menjelaskan bahwa `Topos` lama secara internal memakai IERS2010, sedangkan umumnya koordinat GPS/lokasi modern diharapkan menggunakan WGS84. [Rhodes Mill](https://rhodesmill.org/skyfield/installation.html?utm_source=chatgpt.com)

Saya akan menggantinya dengan:

```python
def set_location(latitude, longitude, elevation):
    return api.wgs84.latlon(
        latitude_degrees=latitude,
        longitude_degrees=longitude,
        elevation_m=elevation,
    )
```

Selain lebih modern, ini juga membuat file Anda konsisten karena untuk horizontal parallax Anda sudah memakai:

```python
api.wgs84.radius.km
```

data_hisab

Sekarang sebenarnya ada sedikit campuran:

\[
\text{observer geometry: IERS2010/Topos}
\]

dengan:

\[
\text{Earth radius: WGS84}.
\]

Perbedaannya sangat kecil dan tidak akan mengubah kesimpulan visibilitas hilal, tetapi dari sisi metodologi software ilmiah lebih baik dibuat satu datum.

---

# 8. Horizontal parallax baru Anda sudah lebih masuk akal

Anda menghitung:

```python
horizontal_parallax_deg = np.degrees(np.arcsin(
    api.wgs84.radius.km /
    moon_geocentric.distance().km
))
```

dan secara eksplisit tidak lagi menggunakannya untuk memperoleh semidiameter. data_hisab

Ini bagus.

Artinya sekarang:

\[
HP=\arcsin\left(\frac{R_E}{\Delta_\mathrm{geo}}\right)
\]

hanya diagnostic output.

Sedangkan:

\[
SD=\arcsin\left(\frac{R_M}{\Delta_\mathrm{topo}}\right).
\]

Ini pemisahan yang jauh lebih bersih dibanding:

\[
SD=0.27254\times HP
\]

yang sebelumnya digunakan.

Saya akan mempertahankan bagian ini.

---

# 9. Saya menemukan satu bug lama di perhitungan Hijriah mundur

Bagian ini belum berkaitan dengan perubahan Skyfield, tetapi karena kita sedang audit file, perlu saya tunjukkan.

Pada branch tahun sebelum 1444:

```python
idx = np.arange(1,len(new_moon_datetimes)+1) - len(new_moon_datetimes)

idx1 = np.where(
    (idx%12==hijri_month-1)
    &
    ((idx/12).astype(int)-1==hijri_year-ref_hijri_y)
)
```

data_hisab

Ada edge case pada **Muharram tahun sebelumnya**.

Misalnya referensi:

\[
1\ \mathrm{Muharram}\ 1444
\]

adalah:

\[
idx=0.
\]

Maka:

\[
1\ \mathrm{Muharram}\ 1443
\]

harus:

\[
idx=-12.
\]

Tetapi:

```python
(idx / 12).astype(int) - 1
```

memberikan:

\[
-1-1=-2
\]

padahal offset tahunnya seharusnya:

\[
1443-1444=-1.
\]

Jadi exact multiple \(-12,-24,\dots\) bermasalah.

Cara yang jauh lebih bersih adalah memanfaatkan floor division:

```python
month_offset = idx % 12
year_offset = idx // 12
```

lalu:

```python
idx1 = np.where(
    (month_offset == hijri_month - 1)
    & (year_offset == hijri_year - ref_hijri_y)
)
```

Karena:

\[
-1//12=-1
\]

dan:

\[
-12//12=-1.
\]

Ini tidak memengaruhi rentang penelitian Anda yang bergerak setelah Muharram 1444, tetapi sebaiknya diperbaiki agar `data_hisab.py` secara umum benar.

---

# 10. `calc_timedelta_seconds()` bisa dibuat lebih presisi

Sekarang:

```python
timedelta = datetime2 - datetime1
timedelta_s = (timedelta.days*86400.0) + timedelta.seconds
```

data_hisab

Ini membuang:

```python
timedelta.microseconds
```

Padahal waktu konjungsi Skyfield bisa memiliki precision di bawah detik.

Lebih bersih cukup:

```python
return (datetime2 - datetime1).total_seconds()
```

Untuk Moon age memang perbedaan subdetik tidak signifikan secara fisik, tetapi kalau tujuan kita menjaga pipeline presisi, ini mudah diperbaiki.

---

# 11. Ada satu docstring yang agak menyesatkan

Anda menulis pada phase angle:

> `input UTC array didukung`

data_hisab

Tetapi `_lunar_observation_utc()` melakukan:

```python
ts.from_datetime(utc_datetime)
```

data_hisab

yang pada jalur ini dirancang untuk Python `datetime`, bukan array datetime umum.

Selain itu `moon_semidiameter_from_distance()` secara eksplisit:

```python
distance_km = float(distance_km)
```

jadi bagian modul baru Anda memang scalar-oriented. data_hisab

Saya akan menghapus klaim array tersebut kecuali nanti Anda memang sengaja membuat vectorized API.

---

# Status akhir file saat ini

| Komponen | Penilaian saya | Tindakan |
|---|---|---|
| DE440s | ✅ | Pertahankan |
| Konjungsi Skyfield | ✅ | Pertahankan |
| Topocentric apparent elongation | ✅ | Pertahankan |
| PyMeeus dihapus | ✅ | Sangat bagus |
| Radius Bulan 1737.4 km | ✅ | Pertahankan |
| Semidiameter dari distance | ✅ | Pertahankan |
| Native `phase_angle()` | ✅ | Pertahankan metodenya |
| `phase_angle()` dari `apparent()` | ⚠️ | Lebih baik astrometric untuk Kastner |
| Illumination | ✅/⚠️ | Sebaiknya gunakan geometri yang sama dengan phase |
| Width dari elongation | **⚠️ penting** | Ganti menjadi phase/illumination-based |
| Horizontal parallax | ✅ | Pertahankan sebagai diagnostik |
| `api.Topos` | ⚠️ | Ganti `api.wgs84.latlon()` |
| Backward Hijri indexing | ⚠️ | Ada bug Muharram |
| `calc_timedelta_seconds` | minor | Gunakan `.total_seconds()` |

### Bentuk yang menurut saya paling ideal

Setelah revisi berikutnya, saya ingin arsitektur data lunar Anda secara konseptual menjadi:

\[
\text{DE440s}
\rightarrow
\begin{cases}
\text{Astrometric geometry}\\
\text{Apparent sky geometry}
\end{cases}
\]

kemudian:

\[
\begin{aligned}
\text{Astrometric:}\quad
&\Delta,\ SD,\ \alpha,\ k,\ W\\
\text{Apparent:}\quad
&E,\ h,\ A
\end{aligned}
\]

dengan hubungan internal:

\[
SD=\arcsin(R_M/\Delta),
\]

\[
k=\frac{1+\cos\alpha}{2},
\]

dan

\[
\boxed{W=2SD\,k=SD(1+\cos\alpha)}.
\]

Ini jauh lebih rapi daripada mencampurkan \(E\) dan \(\alpha\).

**Kesimpulan saya:** revisi Anda sudah berhasil menyelesaikan masalah semidiameter yang paling jelas dari versi lama, tetapi saya **belum akan menganggap `data_hisab.py` final** sebelum mengubah width menjadi phase-angle based dan memutuskan phase angle Kastner sebagai true/astrometric phase angle. Setelah dua hal itu dibereskan, baru sangat masuk akal kita membuat `jpl_horizons_validator.py` untuk menguji `SD`, elongation, phase angle, dan altitude terhadap Horizons tanpa menjadikan Horizons dependency utama.