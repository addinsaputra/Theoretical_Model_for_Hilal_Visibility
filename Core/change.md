Baik. Untuk perbaikan program utama, saya sarankan kita **membatasi perubahan hanya pada antarmuka antar-model** yang sudah kita sepakati. Jangan dulu mengganti model airmass dan jangan dulu memperbaiki phase law \(L^\*\); itu kita parkir untuk paper terpisah.

Ada dua koreksi utama:

\[
\boxed{\text{A. Schaefer}\rightarrow\text{Kastner: extinction/transmission}}
\]

dan

\[
\boxed{\text{B. Kastner}\rightarrow\text{Crumey: arti luminansi dan contrast}}
\]

Saya sudah cek ulang repository Anda. Kedua masalah itu memang masih ada di kode saat ini.

---

# A. Perbaiki interface extinction Schaefer → Kastner

Di `Core/visual_limit_schaefer.py`, program sebenarnya **sudah menghitung besaran yang kita butuhkan**.

Saat ini:

```python
K[i] = KR + KA + KO + KW

DM[i] = KR * XG + KA * XA + KO * XO + KW * XG
```

Interpretasinya harus dibedakan:

\[
K_V
=
K_R+K_A+K_O+K_W
\]

adalah koefisien extinction, sedangkan

\[
\boxed{
DM_V=
K_RX_G+
K_AX_A+
K_OX_O+
K_WX_G
}
\]

adalah **total light loss sepanjang line of sight dalam magnitude**.

Ini sesuai langsung dengan Schaefer: ia menuliskan \(\Delta m=kX\) sebagai aproksimasi, kemudian bentuk lebih lengkap sebagai jumlah extinction masing-masing komponen dengan masing-masing air mass, dan akhirnya

\[
I_{\rm obs}=I_{\rm na}\,10^{-0.4\Delta m}.
\]

Schaefer2000

Jadi jangan lagi mengirim `K[2]` ke Kastner.

## Perubahan di `visual_limit_schaefer.py`

Saya sarankan **jangan menghapus `K` maupun `DM`**, karena keduanya berguna untuk diagnosis. Cukup tambahkan output yang maknanya eksplisit:

```python
dm_v = DM[2]
transmission_v = 10.0 ** (-0.4 * dm_v)

return {
    "sky_brightness": BL,
    "K": K,
    "DM": DM,
    "k_v": K[2],                    # diagnostic only
    "extinction_mag_v": dm_v,       # mag
    "transmission_v": transmission_v, # dimensionless
    "B": B,
}
```

Dengan demikian kontraknya menjadi:

| Variabel | Makna | Satuan |
|---|---|---:|
| `k_v` | extinction coefficient V | mag/airmass |
| `extinction_mag_v` | total LOS extinction \(A_V=\Delta m_V\) | mag |
| `transmission_v` | \(T_V=10^{-0.4A_V}\) | dimensionless |
| `sky_brightness` | background di posisi hilal | nL |

Yang dipakai Kastner hanyalah:

\[
\boxed{T_V}
\]

bukan `k_v`.

---

# B. Hapus extinction internal dari `visual_limit_kastner.py`

Saat ini file tersebut masih melakukan:

```python
X = 1 / (cos_z + 0.025 * math.exp(-11 * cos_z))

L = 0.263 * L_star * math.exp(-k * X)
```

Inilah bagian yang harus dihentikan.

Kastner asli memang menulis

\[
L_c=L^\*\exp(-KF),
\]

tetapi \(K\) di situ didefinisikan melalui faktor absorpsi natural-exponential. katsner_Calculation of The Twil…

Kita sudah memilih Schaefer sebagai pemilik atmospheric extinction. Maka **Kastner tidak perlu menghitung air mass atau extinction sendiri lagi**.

Idealnya `visual_limit_kastner.py` dipisah menjadi dua tahap.

```python
S10_TO_NL = 0.263


def crescent_area(elongation_deg: float, r_deg: float) -> float:
    e = math.radians(elongation_deg)
    return 0.5 * math.pi * r_deg**2 * (1.0 - math.cos(e))


def hitung_luminansi_intrinsik(
    phase_angle_deg: float,
    elongation_deg: float,
    r_deg: float,
):
    alpha = phase_angle_deg

    mv = (
        0.026 * alpha
        + 4e-9 * alpha**4
        - 12.73
    )

    D = crescent_area(elongation_deg, r_deg)

    if D <= 0:
        return 0.0

    L_star_s10 = (2.51 ** (10.0 - mv)) / D

    return L_star_s10


def terapkan_transmisi_atmosfer(
    L_star_s10: float,
    transmission_v: float,
) -> float:

    L_direct_nL = (
        S10_TO_NL
        * L_star_s10
        * transmission_v
    )

    return L_direct_nL
```

Perhatikan perubahan konseptualnya:

\[
\boxed{
L^\*_{S10}
}
\]

dibentuk tanpa atmosfer.

Kemudian:

\[
\boxed{
L_{\rm obj,nL}
=
0.263\,L^\*_{S10}\,T_V
}
\]

dengan

\[
T_V=10^{-0.4DM_V}.
\]

`0.263` tetap kita perlakukan hanya sebagai **konversi \(S_{10}\rightarrow\rm nL\)**, bukan bagian extinction.

---

# C. Jangan lagi kirim `z` dan `k_v` ke Kastner

Saat ini di `core_crescent_visibility.py`:

```python
luminansi_hilal_nl = hitung_luminansi_kastner(
    alpha=posisi['phase_angle'],
    r=float(posisi['moon_semidiameter']),
    z=zenith_distance,
    k=k_v
)
```

Ini harus berubah secara konseptual menjadi:

```python
L_star_s10 = hitung_luminansi_intrinsik(
    phase_angle_deg=posisi['phase_angle'],
    elongation_deg=posisi['elongation'],
    r_deg=float(posisi['moon_semidiameter']),
)

luminansi_hilal_nl = terapkan_transmisi_atmosfer(
    L_star_s10=L_star_s10,
    transmission_v=transmission_v,
)
```

Dengan demikian `visual_limit_kastner.py` sama sekali tidak perlu mengetahui:

```text
z
k
X
RH
T
pressure
```

Semua itu menjadi wilayah model atmosfer.

Ini menurut saya perubahan arsitektur paling penting karena mencegah **double extinction** di masa depan.

---

# D. Ubah output fungsi Schaefer di `core_crescent_visibility.py`

Sekarang fungsi ini hanya mengembalikan:

```python
return sky_brightness_nl, k_v
```

Saya sarankan menjadi minimal:

```python
K_list = result.get("K", [])
DM_list = result.get("DM", [])

k_v = float(K_list[2])
extinction_mag_v = float(DM_list[2])

transmission_v = 10.0 ** (-0.4 * extinction_mag_v)

return (
    sky_brightness_nl,
    k_v,
    extinction_mag_v,
    transmission_v,
)
```

`k_v` tetap disimpan untuk analisis, tetapi jangan digunakan untuk attenuation source.

Pipeline akhirnya menjadi sangat jelas:

\[
RH,T,H,z
\]

\[
\Downarrow\quad\text{Schaefer}
\]

\[
K_V,\quad DM_V,\quad B_V
\]

kemudian

\[
DM_V
\rightarrow
T_V=10^{-0.4DM_V}
\]

sementara sisi source:

\[
\alpha,\varepsilon,r
\rightarrow
L^\*
\]

dan keduanya baru bertemu:

\[
\boxed{
L_{\rm obj}
=
0.263L^\*T_V
}
\]

---

# E. Masalah kedua: `L_hilal` bukan `B_target`

Ini sekarang sangat penting untuk Crumey.

Setelah persamaan di atas, besaran

\[
L_{\rm obj}
\]

berarti **direct/excess luminance dari hilal** yang sampai kepada observer.

Sedangkan

\[
B_{\rm sky}
\]

adalah background sky luminance.

Jadi patch langit tempat hilal berada sebenarnya mempunyai total luminance:

\[
\boxed{
B_t=B_{\rm sky}+L_{\rm obj}.
}
\]

Crumey mendefinisikan contrast:

\[
C=\frac{B_t-B}{B}.
\]

Tetapi khusus astronomical object yang dilihat melalui transparent atmosphere, background tetap hadir pada posisi target; Crumey menjelaskan bahwa object memberikan **increment** \(\Delta B\), sehingga contrast adalah increment terhadap background. crumey\_ Penting_Human contrast …

Karena

\[
B_t=B+L_{\rm obj},
\]

maka:

\[
C
=
\frac{B+L_{\rm obj}-B}{B}
\]

dan akhirnya

\[
\boxed{
C_{\rm obj}
=
\frac{L_{\rm obj}}{B_{\rm sky}}.
}
\]

---

# F. Jadi formula Crumey sekarang di kode Anda salah satu \(B\)

Di `full_rumus_crumey.py` sekarang terdapat:

```python
C_obj = (L_cd - B_cd) / B_cd
```

Ini harus diganti menjadi:

```python
C_obj = L_cd / B_cd
```

Sebab `L_cd` **bukan total luminance target patch**.

`L_cd` adalah \(\Delta B\), yaitu excess luminance hilal.

Kesalahan lama sangat mudah terlihat dari contoh sederhana.

Misalkan:

\[
L_{\rm obj}=B.
\]

Artinya crescent menambahkan cahaya sebesar background itu sendiri.

Total target patch:

\[
B_t=B+B=2B.
\]

Contrast sebenarnya:

\[
C=\frac{2B-B}{B}=1.
\]

Tetapi program lama menghasilkan:

\[
C_{\rm old}
=
\frac{B-B}{B}
=0.
\]

Jadi target yang sebenarnya mempunyai **100% positive contrast** dianggap zero contrast.

Lebih ekstrem, jika:

\[
L_{\rm obj}=0.1B,
\]

contrast sebenarnya:

\[
C=0.1,
\]

tetapi formula lama memberi:

\[
C=-0.9.
\]

Itulah sebabnya sebelumnya banyak nilai contrast menjadi negatif.

---

# G. Ada empat lokasi kode Crumey yang perlu disamakan

Supaya tidak ada satu jalur memakai definisi lama dan jalur lain memakai definisi baru, cari semua pola:

```python
(Lt - B) / B
```

atau:

```python
(L_cd - B_cd) / B_cd
```

Pada repository sekarang saya melihat minimal di:

```text
full_rumus_crumey.py
    crumey_visibility()
    is_visible()
    hilal_naked_eye_visibility()

core_crescent_visibility.py
    hitung_visibilitas_teleskop()
```

Semuanya harus mempunyai satu definisi:

```python
C_obj = L_obj / B
```

lebih baik dengan nama yang tidak ambigu:

```python
delta_B_obj_cd = ...
B_sky_cd = ...

C_obj = delta_B_obj_cd / B_sky_cd
```

Saya sangat menyarankan nama `delta_B_obj` daripada sekadar `L`, karena ini langsung sesuai dengan bahasa Crumey.

---

# H. Buang fallback `1 + C_obj`

Saat ini di `core_crescent_visibility.py` terdapat workaround:

```python
L_over_B = max(1.0 + C_obj, 1e-15)

delta_m = 2.5 * (
    math.log10(L_over_B)
    - math.log10(C_th)
)
```

Workaround ini dibuat karena formula lama menghasilkan `C_obj <= 0`.

Menariknya, karena

\[
C_{\rm old}=\frac{L-B}{B},
\]

maka:

\[
1+C_{\rm old}
=
\frac{L}{B}.
\]

Jadi workaround tersebut **secara tidak sengaja mengembalikan ratio yang sebenarnya kita inginkan**.

Namun akibatnya sekarang program mempunyai dua definisi sekaligus:

```text
visible  → memakai (L-B)/B
delta_m fallback → memakai L/B
```

Ini tidak boleh dipertahankan.

Setelah diperbaiki:

```python
C_obj = L_obj / B
```

cukup gunakan:

```python
if C_obj > 0 and C_th > 0:
    delta_m = 2.5 * math.log10(C_obj / C_th)
else:
    delta_m = float("-inf")
```

dan:

```python
visible = C_obj > C_th
```

Selesai.

---

# I. Telescope juga harus memakai definisi yang sama

Sekarang `hitung_visibilitas_teleskop()` mempunyai:

```python
C_obj = (Lt_nL - B_nL) / B_nL
```

ubah menjadi:

```python
C_obj = Lt_nL / B_nL
```

Kemudian program menerapkan faktor optik yang sama kepada extended source dan background:

```python
B_corr_nL  = B_nL  * Ba_factor
Lt_corr_nL = Lt_nL * Ba_factor
```

Maka:

\[
\frac{L_{\rm obj,eff}}
{B_{\rm eff}}
=
\frac{fL_{\rm obj}}{fB}
=
\frac{L_{\rm obj}}{B}.
\]

Ini bagus: contrast objek memang invariant jika target dan background menerima attenuation optik yang sama. Yang berubah melalui teleskop terutama adaptation background dan apparent angular area, sehingga threshold Crumey berubah.

---

# J. Samakan juga area crescent

Karena kita sudah menemukan kesalahan variabel sebelumnya, jangan biarkan fungsi berbeda mempunyai konvensi berbeda.

Saat ini `full_rumus_crumey.py` masih mempunyai:

```python
crescent_area_deg2(phase_angle_deg, sd_deg)
```

dan core memanggil:

```python
phase_angle_deg=posisi['phase_angle']
```

Jika untuk baseline skripsi Anda tetap mengikuti formulasi sumber adaptasi:

\[
D=
\frac12\pi r^2(1-\cos\varepsilon),
\]

gunakan:

```python
crescent_area_deg2(elongation_deg, sd_deg)
```

dan panggil:

```python
elongation_deg=posisi['elongation']
```

Idealnya **jangan mempunyai dua implementasi `crescent_area()`** di Kastner dan Crumey. Buat satu fungsi bersama supaya kesalahan seperti ini tidak berulang.

Ini bukan perubahan phase-law \(L^\*\); ini hanya membersihkan definisi variabel.

---

# K. Nama-nama besaran saya sarankan dibuat seperti ini

Ini penting untuk skripsi dan kode sekaligus:

\[
\boxed{L^\*_{S10}}
\]

`L_star_s10`

= mean extra-atmospheric crescent luminance.

\[
\boxed{A_V=DM_V}
\]

`extinction_mag_v`

= line-of-sight extinction magnitude Schaefer.

\[
\boxed{T_V}
\]

`transmission_v`

= atmospheric transmission:

\[
T_V=10^{-0.4A_V}.
\]

\[
\boxed{L_{\rm obj}}
\]

`L_obj_nL` atau `delta_B_hilal_nL`

= direct/excess crescent luminance setelah atmosfer:

\[
L_{\rm obj}
=
0.263L^\*T_V.
\]

\[
\boxed{B_{\rm sky}}
\]

`B_sky_nL`

= background sky brightness dari Schaefer.

\[
\boxed{C_{\rm obj}}
\]

= Crumey object contrast:

\[
C_{\rm obj}
=
\frac{L_{\rm obj}}{B_{\rm sky}}.
\]

Dan

\[
\boxed{
\Delta m_{\rm vis}
=
2.5\log_{10}
\left(
\frac{C_{\rm obj}}{C_{\rm th}}
\right)
}
\]

dengan:

\[
\Delta m_{\rm vis}>0
\iff
C_{\rm obj}>C_{\rm th}.
\]

---

# L. Urutan perubahan kode yang paling aman

Saya sarankan Anda melakukannya dalam urutan ini agar mudah menemukan sumber error:

1. **`visual_limit_schaefer.py`** — tambahkan `extinction_mag_v` dan `transmission_v`; jangan ubah rumus airmass apa pun.
2. **`visual_limit_kastner.py`** — hilangkan `z`, `k`, dan perhitungan `X`; pisahkan \(L^\*\) dan application of \(T_V\); sekaligus beri input `phase_angle` dan `elongation` secara terpisah.
3. **`core_crescent_visibility.py`** — ganti plumbing `k_v → transmission_v`; tetap simpan `k_v` sebagai diagnostic output.
4. **`full_rumus_crumey.py`** — ganti semua contrast menjadi \(L_{\rm obj}/B\), lalu ubah area input menjadi elongasi.
5. **`core_crescent_visibility.py` naked-eye + telescope** — ganti contrast yang sama dan hapus workaround `1 + C_obj`.
6. Setelah semuanya lolos tes, baru perbarui `core_multi_location.py`, Excel output, README, dan diagnostic script supaya menyimpan `k_v`, `extinction_mag_v`, serta `transmission_v` sebagai tiga kolom yang berbeda.

---

## Tes minimum sebelum menjalankan 278 observasi

Sebelum batch besar, saya akan mensyaratkan lima invariant ini.

Untuk extinction:

\[
A_V=0
\Rightarrow
T_V=1.
\]

\[
A_V=1\ {\rm mag}
\Rightarrow
T_V=10^{-0.4}
=0.398107.
\]

Dan selalu:

\[
A_V\ge0
\Rightarrow
0<T_V\le1.
\]

Untuk contrast:

\[
L_{\rm obj}=B
\Rightarrow
C_{\rm obj}=1,
\]

dan:

\[
L_{\rm obj}=0.1B
\Rightarrow
C_{\rm obj}=0.1.
\]

Untuk keputusan visibilitas:

\[
\Delta m_{\rm vis}=0
\iff
C_{\rm obj}=C_{\rm th}.
\]

Kalau lima tes sederhana ini berhasil, baru saya percaya interface antar-modelnya.

---

## Arsitektur akhir yang kita tuju

Setelah perubahan tersebut, alur fisik program Anda menjadi sangat bersih:

\[
\boxed{
\text{DE440 geometry}
\rightarrow
L^\*
}
\]

dan secara paralel:

\[
\boxed{
\text{RH,T,H,geometry}
\rightarrow
\text{Schaefer}
\rightarrow
(B_{\rm sky},A_V)
}
\]

kemudian:

\[
A_V
\rightarrow
T_V
\]

\[
L^\*
\xrightarrow{\;T_V\;}
L_{\rm obj}
\]

lalu:

\[
\boxed{
C_{\rm obj}
=
\frac{L_{\rm obj}}{B_{\rm sky}}
}
\]

dan akhirnya:

\[
\boxed{
(C_{\rm obj},A,B_{\rm sky})
\rightarrow
\text{Crumey}
\rightarrow
C_{\rm th}
\rightarrow
\Delta m_{\rm vis}.
}
\]

Yang paling penting: **setiap model sekarang mempunyai satu pekerjaan yang jelas**. Kastner/source model tidak lagi “mencuri” tugas atmosfer, Schaefer tidak menentukan visibility threshold hilal, dan Crumey tidak menghitung luminansi fisik Bulan.

Untuk tahap skripsi saat ini, inilah struktur yang saya sarankan kita jadikan **kontrak final antar-model**, sambil membiarkan formulasi internal \(L^\*\) lama tetap dipakai sebagai baseline sampai paper khusus surface brightness nanti.