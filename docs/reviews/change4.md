Saya sudah mengaudit **current `main` branch** repository `addinsaputra/Theoretical_Model_for_Hilal_Visibility`, pada commit terbaru yang saya lihat `58268dfa9dd430fe525455458c65806292ad0bc4`. Fokus saya bukan hanya apakah program “jalan”, tetapi apakah **besaran yang keluar dari satu model benar-benar merupakan besaran yang dibutuhkan model berikutnya**.

Kesimpulan besarnya cukup baik: **dua kesalahan interface paling fundamental yang kita temukan sebelumnya sekarang sudah diperbaiki dengan benar**. Schaefer → Kastner tidak lagi mencampur \(K_V\) dengan Rozenberg, dan Kastner → Crumey tidak lagi memakai \((L-B)/B\). Namun saya masih menemukan **satu bug matematis yang nyata**, **dua persoalan kontrak model yang perlu dibereskan sebelum model dianggap final**, dan beberapa keterbatasan ilmiah yang sebaiknya dinyatakan eksplisit, bukan “diperbaiki” secara arbitrer.

## Hasil audit per bagian

| Bagian | Implementasi sekarang | Status |
|---|---|---|
| DE440s: elongasi, phase angle, jarak, semidiameter | Independen dan konsisten | ✅ Dapat diterima |
| Schaefer \(K_V\), \(DM_V\), \(T_V\) | Dipisahkan dengan benar | ✅ Benar |
| Sky brightness Schaefer | Extinction sudah internal; tidak diberi \(T_V\) lagi | ✅ Benar |
| Schaefer → Kastner | `transmission_v`, bukan `k_v × X` | ✅ Benar |
| Kastner \(L^\*\) | Atmosfer sudah dikeluarkan dari modul | ✅ Interface benar |
| Phase law \(L^\*\) | Masih Allen/old baseline | ⚠️ Known limitation, kita parkir |
| Area crescent | Satu fungsi bersama berbasis elongasi | ✅ Konsisten |
| Kastner → Crumey | \(L_{\rm obj}\) diperlakukan sebagai excess \(\Delta B\) | ✅ Benar |
| Contrast Crumey | \(C=L_{\rm obj}/B_{\rm sky}\) | ✅ Benar |
| Crumey naked eye | Rumus threshold konsisten secara dimensional | ✅ dengan asumsi domain |
| Crumey telescope | \(B_a=gB,\;A_a=M^2A,\;\phi=F_TF_MF\) | ✅ struktur benar |
| RH = 100% | Menyebabkan singularitas aerosol Schaefer | ❌ Harus diperbaiki |
| `F_naked=2.5`, `F_tel=2.4` | Tidak dikalibrasi khusus hilal | ⚠️ Kontrak harus diperjelas |
| “telescope gain” dengan dua F berbeda | Bukan pure optical gain | ⚠️ Perlu diperbaiki |
| Crumey pada twilight mesopic/photopic | Achromatic approximation | ⚠️ Keterbatasan penting |
| Dataset CCD BMKG untuk Crumey visual | Hanya comparison, bukan visual validation | ✅ Dokumentasi terbaru sudah benar |

---

# 1. Schaefer → Kastner sekarang sudah benar

Di [`visual_limit_schaefer.py`](https://github.com/addinsaputra/Theoretical_Model_for_Hilal_Visibility/blob/58268dfa9dd430fe525455458c65806292ad0bc4/Core/visual_limit_schaefer.py#L143-L223), sekarang ada pemisahan yang kita inginkan:

```python
K[i] = KR + KA + KO + KW

DM[i] = KR * XG + KA * XA + KO * XO + KW * XG
```

lalu:

```python
dm_v = DM[2]

return {
    ...
    "k_v": K[2],
    "extinction_mag_v": dm_v,
    "transmission_v": transmission_from_extinction_mag(dm_v),
}
```

Ini tepat dengan Schaefer: koefisien extinction dan actual light loss sepanjang LOS adalah dua besaran berbeda; intensitas setelah extinction ditentukan melalui faktor \(10^{-0.4\Delta m}\). Schaefer2000

Dengan demikian:

\[
\boxed{
A_V\equiv DM_V
=
K_RX_G+K_AX_A+K_OX_O+K_WX_G
}
\]

dan

\[
\boxed{
T_V=10^{-0.4A_V}.
}
\]

Kemudian [`visual_limit_kastner.py`](https://github.com/addinsaputra/Theoretical_Model_for_Hilal_Visibility/blob/58268dfa9dd430fe525455458c65806292ad0bc4/Core/visual_limit_kastner.py#L18-L68) menerima **hanya `transmission_v`**, tidak lagi menerima `z`, `k`, atau menghitung Rozenberg.

Ini adalah arsitektur yang saya sarankan kita **freeze**:

\[
\boxed{
L_{\rm obj}
=
L^\*\,T_V.
}
\]

Kastner asli juga memiliki struktur “extra-atmospheric source → atmospheric transmission → ground luminance”; yang kita ganti hanyalah model internal transmission-nya dengan Schaefer. katsner_Calculation of The Twil…

---

# 2. Sky brightness juga sekarang diperlakukan dengan benar

Saya cek satu hal yang sebelumnya membuat Anda bingung.

Di Schaefer, `B_sky` **sudah memasukkan extinction secara internal**:

```python
BN *= 10.0 ** (-0.4 * K[i] * X)
```

dan `BT` serta `BD` juga bergantung pada `K`, `X`, dan transmission Matahari.

Jadi program sekarang benar karena **tidak melakukan**

\[
B_{\rm sky}\times T_V
\]

lagi setelah Schaefer.

Arsitekturnya:

\[
\text{Schaefer}
\longrightarrow
\begin{cases}
B_{\rm sky} & \text{background final}\\
A_V & \text{LOS extinction hilal}\\
T_V & \text{LOS transmission hilal}
\end{cases}
\]

Kemudian hanya source hilal yang menerima:

\[
L^\*\rightarrow T_V L^\*.
\]

Tidak ada double extinction yang saya temukan pada current main path.

---

# 3. Kastner sekarang mempunyai boundary fisik yang jauh lebih bersih

Saat ini source photometry menjadi:

\[
m_V(\alpha)
\]

\[
D(\varepsilon,r)
\]

\[
L^\*_{S10}
=
\frac{10^{0.4(10-m_V)}}{D}
\]

kemudian secara terpisah:

\[
\boxed{
L_{\rm obj,nL}
=
S10_{\rm nL}\,
L^\*_{S10}\,
T_V.
}
\]

Saya juga melihat Anda sudah mengganti pembulatan lama \(2.51\) dengan exact magnitude ratio dan mengharmonisasikan conversion \(S_{10}\) terhadap zero point Crumey:

\[
S10_{\rm nL}\simeq0.2619563.
\]

Secara **unit bookkeeping**, ini lebih rapi daripada campuran `2.51` dan `0.263`.

Dan yang sangat baik: `phase_angle` serta `elongation` sekarang dua input terpisah:

```python
phase_angle_deg
elongation_deg
r_deg
```

Jadi bug lama “phase angle digunakan sebagai elongasi” sudah hilang.

Masalah large-phase phase law yang pernah kita temukan tetap ada, tetapi itu **bukan lagi interface bug**. Repository Anda bahkan sudah mendokumentasikannya. Saya setuju kita biarkan sebagai *known source-model limitation* untuk paper \(L^\*\) yang terpisah.

---

# 4. Kastner → Crumey sekarang juga sudah benar

Di [`full_rumus_crumey.py`](https://github.com/addinsaputra/Theoretical_Model_for_Hilal_Visibility/blob/58268dfa9dd430fe525455458c65806292ad0bc4/Core/full_rumus_crumey.py#L954-L1045), program sekarang melakukan:

```python
delta_B_obj_cd = nL_to_cdm2(L_hilal_nL)
B_cd = nL_to_cdm2(B_sky_nL)

C_obj = delta_B_obj_cd / B_cd
```

Jadi:

\[
\boxed{
C_{\rm obj}
=
\frac{L_{\rm obj}}{B_{\rm sky}}
}
\]

dengan

\[
B_t=B_{\rm sky}+L_{\rm obj}.
\]

Ini persis interpretasi target astronomi transparan yang kita diskusikan. Crumey membedakan target opaque dari target astronomis yang menambahkan luminance increment pada background. crumey\_ Penting_Human contrast …

Maka jika:

\[
L_{\rm obj}=0.1B,
\]

program sekarang benar memberikan:

\[
C=0.1,
\]

bukan \(-0.9\).

Saya tidak lagi menemukan fallback `1+C_old` yang dulu membuat definisi contrast menjadi bercabang dua.

---

# 5. Crumey naked-eye: secara matematis implementasinya sudah konsisten

Backend threshold sekarang pada dasarnya menghitung:

\[
\boxed{
C_{\rm th}
=
F
\left[
\left(\frac{R(B)}{A}\right)^q
+
C_\infty(B)^q
\right]^{1/q}
}
\]

dan margin:

\[
\boxed{
\Delta m_{\rm vis}
=
2.5\log_{10}
\frac{C_{\rm obj}}{C_{\rm th}}.
}
\]

Itu memberi invariant yang sangat bersih:

\[
C_{\rm obj}=C_{\rm th}
\iff
\Delta m=0.
\]

Dan:

\[
\Delta m>0
\iff
\text{above threshold}.
\]

Implementasi `increment_threshold()` juga membuat point-source limit dan large-target limit berasal dari coefficient backend yang sama. Secara internal ini jauh lebih sehat daripada versi lama.

---

# 6. Implementasi teleskop sekarang secara struktur juga benar

Ini bagian yang saya periksa cukup hati-hati.

Di [`core_crescent_visibility.py`](https://github.com/addinsaputra/Theoretical_Model_for_Hilal_Visibility/blob/58268dfa9dd430fe525455458c65806292ad0bc4/Core/core_crescent_visibility.py#L696-L756), Anda melakukan:

\[
L_a=gL_{\rm obj},
\]

\[
B_a=gB_{\rm sky},
\]

sehingga:

\[
\boxed{
C_{\rm obj,tel}
=
\frac{gL}{gB}
=
\frac{L}{B}.
}
\]

Kemudian:

\[
\boxed{
A_a=M^2A.
}
\]

Backend [`telescopic_extended_threshold()`](https://github.com/addinsaputra/Theoretical_Model_for_Hilal_Visibility/blob/58268dfa9dd430fe525455458c65806292ad0bc4/Core/full_rumus_crumey.py#L691-L745) membentuk:

\[
B_a=gB,
\]

\[
A_a=M^2A,
\]

dan:

\[
\phi=F_TF_MF.
\]

Itu konsisten dengan struktur Crumey Eq. 77–80. Crumey memang memberi:

\[
A_a=M^2A,
\]

serta menyatakan secara umum dapat diasumsikan:

\[
F_T=\sqrt2,
\qquad
F_M=1,
\]

dan apparent sky brightness mengikuti faktor pupil + telescope transmission. crumey\_ Penting_Human contrast …

Jadi keputusan Anda:

```python
FT = sqrt(2)
FM = 1
```

punya dasar dari paper.

Satu koreksi dari audit lama juga sudah diterapkan: \(\sqrt2\) monocular penalty masuk ke **threshold**, bukan stimulus. Crumey sendiri mengkritik penerapan Schaefer lama yang memperlakukan binocular factor sebagai stimulus modification.

---

# 7. Tetapi ada satu bug nyata yang masih harus diperbaiki: RH = 100%

Ini temuan terpenting yang menurut saya harus diperbaiki **sebelum** Anda freeze kode.

Pada Schaefer:

```python
rh_fraction = max(humidity / 100.0, 0.01)

KA *= (1.0 - 0.32 / math.log(rh_fraction)) ** 1.33
```

Jika:

\[
RH=100\%,
\]

maka:

\[
rh_{\rm fraction}=1
\]

dan

\[
\ln(1)=0.
\]

Sehingga muncul:

\[
\frac{0.32}{0}.
\]

Jadi secara matematis:

\[
\boxed{
RH=100\%\quad\text{adalah singularitas implementasi Schaefer ini.}
}
\]

Yang membuat ini bukan sekadar edge case teoritis adalah atmospheric module Anda saat ini mengizinkan:

\[
0\le RH\le100
\]

dan bias correction bahkan dapat menghasilkan tepat \(100\%\) setelah clipping.

Jadi ada kondisi yang mungkin:

\[
\text{IFS RH/bias}
\rightarrow100\%
\rightarrow
\text{Schaefer crash}.
\]

### Rekomendasi

Jangan secara diam-diam menulis:

```python
humidity = min(humidity, 99.9)
```

kecuali ada landasan ilmiah.

Untuk sekarang lebih transparan:

```python
if not (0.0 <= humidity < 100.0):
    raise ValueError(
        "Schaefer aerosol parameterization requires RH < 100%."
    )
```

dan biarkan kasus tersebut tercatat sebagai **outside model domain**.

Kalau nanti kita menemukan prescription asli untuk saturated atmosphere, baru kita implementasikan secara eksplisit.

---

# 8. Ada satu masalah kontrak penting: arti `F`

Ini bukan bug rumus, tetapi bisa menyebabkan double counting **secara konseptual**.

Crumey menggunakan field factor \(F\) sebagai overall scaling yang dapat mencakup laboratory scaling, observer, target, medium, dan field conditions. Pada model generic-nya, bentuk threshold memang relatif terhadap \(F\).

Tetapi hybrid Anda sekarang sudah secara eksplisit memodelkan:

- extinction atmosfer melalui Schaefer;
- sky background melalui Schaefer;
- telescope transmission melalui \(g\);
- monocular penalty melalui \(F_T=\sqrt2\);
- magnification melalui \(A_a=M^2A\).

Maka **jangan lagi mengatakan bahwa `F` juga mencakup extinction, telescope transmission, atau magnification**.

Untuk hybrid kita, saya sarankan definisi final:

\[
\boxed{
F_{\rm residual}
=
\text{laboratory scaling + observer + residual target/viewing effects}
}
\]

setelah efek fisik yang sudah dimodelkan secara eksplisit dikeluarkan.

Dengan begitu kita tidak melakukan:

\[
\text{extinction Schaefer}
+
\text{“atmospheric factor” di F}
\]

dua kali.

---

# 9. Default `F_naked=2.5` dan `F_tel=2.4` perlu dipikirkan lagi

Sekarang core mempunyai:

```python
F_naked = 2.5
field_factor = 2.4
```

dan kemudian:

\[
C_{\rm th,NE}\propto2.5
\]

sementara telescope:

\[
C_{\rm th,tel}
\propto
2.4\times\sqrt2.
\]

Ini boleh saja kalau keduanya adalah **dua calibration parameter yang memang independen**.

Tetapi saat ini keduanya belum dikalibrasi khusus hilal.

Akibatnya variabel:

```python
telescope_gain
```

tidak benar-benar hanya menunjukkan *gain akibat teleskop*. Ia juga sedikit memasukkan:

\[
2.5\rightarrow2.4
\]

sebagai perubahan field factor.

Besarnya memang kecil:

\[
2.5\log_{10}\frac{2.5}{2.4}
\approx0.044\ {\rm mag},
\]

tetapi secara konsep tidak bersih.

### Untuk perbandingan pure telescope vs naked eye

Saya lebih menyukai satu:

\[
\boxed{F_{\rm visual}}
\]

yang sama untuk observer/target condition:

\[
F_{\rm NE}=F_{\rm visual},
\]

\[
\phi_{\rm tel}
=
F_{\rm visual}
F_TF_M.
\]

Karena Crumey sendiri menuliskan telescopic factor:

\[
\phi=F_TF_MF.
\]

crumey\_ Penting_Human contrast …

Kalau nanti data visual menunjukkan memang ada \(F_{\rm tel}\) berbeda, silakan gunakan dua nilai; tetapi nama output jangan lagi **“telescope gain murni”**.

---

# 10. Saya juga menyarankan menghapus label “2.0 mahir, 2.5 tipikal, 3.0 pemula”

Saat ini docstring `hilal_naked_eye_visibility()` masih mengatakan:

```python
2.0 (pengamat mahir)
2.5 (tipikal)
3.0+ (pemula)
```

Saya tidak menemukan dasar dalam Crumey yang membenarkan mapping sederhana tersebut **untuk hilal**.

Crumey memang membahas notional \(F=2\), dan contoh nyata dapat menghasilkan nilai F lain. Tetapi \(F\) adalah aggregate field factor, bukan “skill level dial”.

Jadi lebih aman menulis:

> `F` adalah overall residual field factor. Nilai default merupakan nilai referensi/asumsi dan belum merupakan kalibrasi khusus pengamatan hilal.

Crumey sendiri menunjukkan F bergantung pada kondisi, target, observer, dan laboratory scaling; bukan hanya pengalaman observer. crumey\_ Penting_Human contrast …

---

# 11. Ada batas ilmiah Crumey yang sangat penting untuk twilight hilal

Current code menggunakan:

```python
mode='auto'
```

yang berarti **combined achromatic curve**.

Secara matematis itu bagus: tidak memaksa scotopic formula pada background yang jelas mesopic/photopic.

Tetapi ada perbedaan antara:

\[
\text{mathematically valid combined fit}
\]

dan

\[
\text{physically validated twilight-hilal perception}.
\]

Crumey menegaskan bahwa modelnya dibangun dari **achromatic target data**. Untuk objek terhadap blue sky dan kondisi mesopic ketika warna dapat dipersepsikan, ia mengatakan chromaticity harus dimasukkan dan bahkan diperlukan experimental data lain. crumey\_ Penting_Human contrast …

Ini sangat relevan karena:

\[
\text{hilal spectrum}
\neq
\text{twilight sky spectrum}.
\]

Jadi:

\[
\boxed{
C_{\rm photopic}
=
\frac{L_V}{B_V}
}
\]

belum tentu identik dengan effective perceptual contrast dalam mesopic vision.

Saya tidak menyarankan kita langsung menambahkan correction arbitrer. Justru current code lebih baik tetap sebagai:

\[
\boxed{\text{achromatic luminance-threshold approximation}}
\]

dan ini dinyatakan sebagai keterbatasan.

---

# 12. Whole-crescent area masih merupakan extrapolation paling besar dari Crumey

Ini menurut saya keterbatasan terbesar setelah \(L^\*\).

Crumey dibangun dari target yang idealnya uniform dan achromatic. Ia memang membahas nonuniform target secara pendekatan dan field factors, tetapi hilal sangat tipis adalah bentuk yang ekstrem:

- panjang puluhan arcminute,
- width beberapa arcsecond,
- cusp meruncing,
- luminance tidak uniform,
- mungkin hanya segmen tertentu yang terdeteksi mata.

Current code menggunakan:

\[
A=
\text{seluruh geometric crescent area}
\]

dan satu:

\[
\bar L_{\rm obj}
\]

untuk seluruh area.

Artinya Crumey melihat hilal kira-kira sebagai:

\[
\boxed{
\text{uniform extended target of area }A
}
\]

meskipun secara nyata bentuknya sangat elongated.

Ini **bukan coding error**; justru implementasinya konsisten dengan asumsi yang dipilih. Tetapi jangan mengatakan bahwa Crumey native sudah tervalidasi untuk geometry hilal.

Repo Anda sendiri sudah sangat baik karena `docs/CRUMEY_HILAL_LIMITATIONS.md` mengakui hal tersebut.

---

# 13. Telescope model juga masih mempunyai beberapa batas fisik

Active optical factor sekarang menurut saya jauh lebih benar:

\[
g=
\tau
\frac{
\max[\min(d,p)^2-d_s^2,0]
}{p^2}.
\]

Source dan background sama-sama dikali \(g\).

Namun model belum mencakup:

\[
PSF,\quad seeing,\quad diffraction,\quad focus,\quad scatter,
\]

\[
vignetting,\quad eyepiece\ field\ stop,\quad AFOV,
\]

dan decentered eye pupil.

Ini penting untuk hilal tipis karena width bisa hanya beberapa arcsecond.

Juga:

\[
A_a=M^2A
\]

mengasumsikan seluruh target tetap berada di field of view. Pada magnifikasi sangat besar hal ini bisa gagal.

Sekali lagi: ini bukan alasan membongkar telescope equations sekarang; cukup jadikan domain limitation.

---

# 14. Pupil dan usia jangan disamakan dengan sensitivity

Saya juga setuju dengan perubahan terbaru Anda bahwa:

```python
observer_age
```

hanya digunakan untuk fallback estimate pupil.

Crumey/Blackwell justru menunjukkan age-related threshold tidak terutama sekadar akibat pupil, tetapi juga ocular media dan sensitivity.

Jadi:

\[
\boxed{
p(\text{age})
\neq
\text{complete age sensitivity model}.
}
\]

`pupil_diameter_mm` override adalah desain yang baik.

Tetapi untuk twilight, pupil sekitar \(6.8\) mm dari dark-pupil relation belum tentu realistis. Idealnya pada masa depan pupil menjadi measured/input independent variable.

---

# 15. Dataset BMKG CCD sekarang sudah diperlakukan lebih benar

Saya melihat commit terbaru juga memperbaiki bahasa validasi.

Ini penting sekali karena Crumey secara eksplisit mengatakan model visualnya tidak diharapkan berlaku langsung pada CCD imaging. crumey\_ Penting_Human contrast …

Jadi 278 label BMKG dari CCD/telescope boleh digunakan untuk:

\[
\boxed{\text{descriptive cross-method comparison}}
\]

tetapi tidak untuk mengatakan:

\[
\boxed{\text{“Crumey visual threshold validated at XX\% accuracy.”}}
\]

README terbaru dan `crumey_empirical_validation.py` tampaknya sudah bergerak ke arah yang benar.

---

# 16. Satu koreksi terminologi atmosfer yang saya sarankan untuk skripsi/README

README masih memiliki kalimat seperti bahwa extinction dihitung “secara akurat berdasarkan parameter atmosfer aktual RH, T, P dari data reanalisis”.

Saya akan melunakkan itu.

Current Schaefer extinction menggunakan:

\[
RH,\quad T,\quad elevation,
\]

serta parameterisasi Rayleigh/aerosol/ozone/water.

**Pressure tidak masuk langsung ke formula `K_R`, `K_A`, `K_O`, `K_W`** pada implementasi Schaefer Anda. Pressure digunakan pada jalur refraction/position.

Lebih jauh, `ecmwf_ifs` yang Anda minta melalui Open-Meteo adalah historical **IFS HRES product**, jadi jangan secara otomatis disebut ERA5 reanalysis.

Lebih aman:

> “Parameterisasi extinction Schaefer dievaluasi menggunakan input meteorologi time–site dependent dari ECMWF IFS HRES melalui Open-Meteo; komponen aerosol, ozon, dan extinction tetap mengikuti parameterisasi model Schaefer.”

Itu ilmiah dan tidak overclaim.

---

# 17. Satu bug kecil lain yang layak diberi guard

Di Schaefer, angular separation menggunakan `acos(...)`.

Jika karena floating-point argument menjadi misalnya:

\[
1+10^{-16},
\]

`acos` bisa error.

Untuk robustness, sebaiknya:

```python
cos_rs = max(-1.0, min(1.0, cos_rs))
RS = math.degrees(math.acos(cos_rs))
```

Ini bukan isu yang kemungkinan besar mengubah dataset Anda, tetapi baik untuk model numerik yang hendak dipublikasikan.

---

# Kontrak final model yang menurut saya sekarang dapat dibekukan

Setelah RH=100 dan definisi \(F\) dibereskan, interface utama Anda dapat ditulis sangat sederhana.

**Source:**

\[
\alpha,\varepsilon,r
\rightarrow
L^\*.
\]

**Atmosphere Schaefer:**

\[
DM_V
=
K_RX_R+
K_AX_A+
K_OX_O+
K_WX_W,
\]

\[
T_V=10^{-0.4DM_V},
\]

dan secara independen:

\[
B_{\rm sky}
=
B_{\rm Schaefer}.
\]

**Source setelah atmosfer:**

\[
\boxed{
L_{\rm obj}
=
S10_{\rm nL}L^\*T_V.
}
\]

**Stimulus contrast:**

\[
\boxed{
C_{\rm obj}
=
\frac{L_{\rm obj}}{B_{\rm sky}}.
}
\]

**Naked eye threshold:**

\[
\boxed{
C_{\rm th,NE}
=
F
\left[
\left(\frac{R(B)}{A}\right)^q
+
C_\infty(B)^q
\right]^{1/q}.
}
\]

**Telescope:**

\[
B_a=gB,
\qquad
A_a=M^2A,
\]

\[
\phi=F_TF_MF,
\]

dan threshold dihitung pada \((A_a,B_a,\phi)\). Ini sesuai struktur telescopic threshold Crumey. crumey\_ Penting_Human contrast …

Akhirnya:

\[
\boxed{
\Delta m_{\rm vis}
=
2.5\log_{10}
\left(
\frac{C_{\rm obj}}
{C_{\rm th}}
\right).
}
\]

---

## Prioritas perbaikan yang saya sarankan

1. **Perbaiki singularitas RH=100%** dan tambahkan regression test khusus Schaefer pada RH batas.
2. **Definisikan ulang `F` secara eksplisit sebagai residual visual field factor**, sehingga atmospheric extinction, optical transmission, dan magnification tidak dihitung dua kali.
3. Untuk pure telescope gain, gunakan **base \(F\) yang sama** pada naked eye dan telescope, lalu \(F_T=\sqrt2\), \(F_M=1\) menjadi differential telescope factors. Jika tetap memakai dua F terpisah, ganti nama `telescope_gain` menjadi sesuatu seperti `threshold_difference`.
4. Hapus mapping “expert/tipikal/pemula” dari default \(F\), kecuali nanti ada visual calibration data yang mendukungnya.
5. Tambahkan diagnostic flag pada output untuk `scotopic / mesopic / photopic` dan nyatakan bahwa mesopic/photopic hilal adalah **achromatic extrapolation**.
6. Perbaiki wording README tentang IFS/reanalysis dan “actual/accurate extinction”.
7. Setelah itu, saya akan menganggap **interface Kastner–Schaefer–Crumey versi skripsi sudah cukup stabil untuk di-freeze**. Phase law \(L^\*\), spatial crescent morphology, chromatic mesopic vision, PSF/seeing, dan observer calibration menjadi lapisan riset lanjutan, bukan alasan terus membongkar interface inti.

Catatan penting: audit ini adalah **source-level audit terhadap commit current main**. Repository sudah mempunyai regression tests yang secara khusus menguji transmission, contrast, shared crescent geometry, telescope configuration, threshold contract, dan DE440 geometry; saya membaca test suite tersebut, tetapi saya tidak mengeksekusi seluruh test suite di lingkungan GitHub Anda dari sini. Jadi saya memisahkan “kode dan kontrak terlihat benar secara audit” dari “seluruh tes runtime telah saya jalankan sendiri”.

Kalau Anda setuju dengan audit ini, saya menyarankan langkah berikutnya kita fokus sangat sempit pada **dua item yang masih benar-benar blocking**: **RH=100** dan **kontrak \(F_{\rm naked}\)–\(F_{\rm telescope}\)**. Setelah dua itu selesai, baru kita dapat mengatakan bahwa penggabungan Kastner–Schaefer–Crumey secara besaran dan interface sudah *frozen*.