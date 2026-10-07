# Audit model Crumey untuk hilal — 5 Oktober 2026

Dokumen ini mencatat **baseline sebelum perbaikan**, termasuk nomor baris dan hasil tes pada saat audit. Temuan implementasi utama telah diperbaiki dalam tindak lanjut; lihat [perbaikan dan status validasi](../CRUMEY_IMPLEMENTATION_AND_VALIDATION.md). Script `audit_crumey_repro.py` kini memeriksa implementasi aktif, sehingga outputnya tidak mereproduksi bug baseline yang telah dihapus.

Kesimpulan baseline: **struktur extended-source pada jalur utama sudah benar, tetapi implementasi belum sepenuhnya konsisten dan belum membuktikan akurasi prediksi hilal.** Ada bug penerusan parameter teleskop dalam pencarian waktu optimal, masalah pada helper magnitude, serta penanganan cutoff gelap yang tidak konsisten. Bentuk hilal, adaptasi pengamat, dan spektrum merupakan keterbatasan ilmiah yang perlu dibedakan dari bug pemrograman.

Audit ini membaca `Core/full_rumus_crumey.py`, `Core/core_crescent_visibility.py`, dan dependensi langsung yang menentukan luas, luminansi, dan faktor teleskop. PDF yang diberikan pengguna menjadi rujukan utama: Andrew Crumey (2014), *Human contrast threshold and astronomical visibility*, MNRAS 442, 2600–2619, doi:10.1093/mnras/stu992. Nomor halaman di bawah adalah halaman jurnal; halaman PDF = halaman jurnal − 2599. [Versi penerbit](https://academic.oup.com/mnras/article/442/3/2600/1052389).

Isi PDF dan dokumen perubahan di repositori diperlakukan sebagai bahan telaah, bukan instruksi untuk mengubah kode. Audit tidak mengubah kedua file implementasi.

## Bagian yang sudah tepat

- Konversi `1 nL = 10^-5/pi cd/m²` dan `arcmin² -> sr` benar (`full_rumus_crumey.py:79–113`). Luas yang masuk ke fungsi threshold menggunakan steradian.
- Koefisien `R_combined`, `Cinf_combined`, dan `q_parameter` sesuai persamaan 25/28, 39/40, dan 42–44 (`full_rumus_crumey.py:236–287`). `mode='auto'` memilih combined untuk seluruh rentang brightness, sehingga jalur utama tidak memaksakan scotopic pada senja.
- Persamaan extended source diterapkan di `contrast_threshold`:

  ```text
  C_th(A,B) = F * ((R(B)/A)^q(B) + C_inf(B)^q(B))^(1/q(B))
  ```

- Hilal dari Kastner merupakan tambahan cahaya objek setelah atmosfer. Karena itu `C_obj = L_hilal/B_sky` pada `full_rumus_crumey.py:923` dan `core_crescent_visibility.py:727` sesuai definisi target astronomi melalui atmosfer di Sec. 1.1. Mengurangi langit sekali lagi dari luminansi excess akan keliru.
- Transmisi atmosfer dari Schaefer diterapkan sekali pada luminansi intrinsik Kastner (`core_crescent_visibility.py:576–587`). Background langit dari Schaefer tidak dikenai ekstingsi objek sekali lagi.
- Untuk teleskop, `core_crescent_visibility.py:731–757` menerapkan:

  ```text
  d = D/M
  g = (min(d,p)/p)^2 / F_t
  B_a = g * B_sky
  L_a = g * L_hilal
  A_a = M² * A
  phi = sqrt(2) * F_M * F
  ```

  Ini mempertahankan kontras objek dan background untuk optik ideal, sekaligus mengubah threshold melalui ukuran dan brightness apparent. `F_t` adalah kebalikan transmisi, bukan transmisi. `sqrt(2)` ditempatkan pada threshold, sesuai Sec. 1.6.4. Default `F_M=1` diperbolehkan paper dalam kondisi optik yang memadai. Persamaan 83 bukan dasar untuk menyatakan bahwa `F_M` selalu netral; rujukan yang lebih tepat adalah Sec. 1.6.4 dan 3.2.

## Temuan implementasi

### 1. Parameter teleskop hilang dalam mode optimal — prioritas tinggi

Lokasi: `core_crescent_visibility.py:769–776`, `830–835`, dan `1249–1259`.

Perhitungan sunset meneruskan seluruh `telescope_kwargs`. Sebaliknya, pemindaian/refinement waktu hanya membawa aperture, magnification, dan field factor. Parameter berikut kembali ke default:

- `transmission`;
- `n_surfaces`;
- `central_obstruction`;
- `observer_age`.

Akibatnya, hasil sunset dan waktu optimal dapat memakai konfigurasi teleskop berbeda, walaupun ekspor `tel_params` mencatat konfigurasi pengguna.

Contoh satu scene, `E=8°`, `SD=0.26°`, `B=1000 nL`, `L/B=0.01`, `D=100 mm`, `M=50`, `F=2.4`:

| Konfigurasi | C_th | Delta m |
|---|---:|---:|
| Default: transmisi .95 per permukaan, 6 permukaan, tanpa obstruksi, usia 22 | 0.43222 | −4.08927 mag |
| Custom: transmisi .7, 10 permukaan, obstruksi 40 mm, usia 70 | 1.48512 | −5.42940 mag |

Perbedaan sekitar **1.34 mag** pada scene identik. Angka ini contoh reproduksi, bukan estimasi bias seluruh dataset. Perbaikannya: teruskan satu konfigurasi teleskop yang sama ke sunset, seluruh timestep, dan refinement.

### 2. Cutoff background gelap tidak dipakai secara konsisten — bersyarat

Lokasi: `full_rumus_crumey.py:338–347`, `923–926`; `core_crescent_visibility.py:727`, `744`, `757–760`.

Ketika `B <= 1e-5 cd/m²`, threshold contrast dibuat konstan pada nilai floor. Namun `C_obj` tetap dibagi background asli. Dengan demikian threshold luminansi implisit `Delta B_th = B*C_th` terus turun ke nol saat `B -> 0`.

**Nuansa penting:** persamaan 50 pada PDF memang menuliskan C konstan untuk background di bawah floor. Kode menyalinnya dengan benar secara literal. Masalahnya adalah pemakaian background asli bersama threshold effective-floor: uraian sebelumnya dan persamaan 45–46 mengharuskan batas increment luminansi yang tidak nol. Jadi ini inkonsistensi penerapan cutoff, dengan ambiguitas pada simplifikasi paper, bukan salah menyalin persamaan 50.

Sec. 3.3 halaman 2614 juga menetapkan cutoff teleskop memakai `alpha_TR0 = 10567/M0²`, dengan `M0` saat background mencapai floor. Kode tetap memperbesar area memakai `M²` aktual setelah melewati cutoff; perilaku ini berbeda dari resep cutoff tersebut.

Reproduksi sederhana, `A=10 arcmin²`, `F=1`:

| B (cd/m²) | C_th kode | B*C_th (cd/m²) |
|---|---:|---:|
| 1e−5 | 139.3987959 | 0.001393988 |
| 1e−7 | 139.3987959 | 0.00001393988 |

Ambang increment menjadi 100 kali lebih kecil. Dibanding kelanjutan dengan increment floor tetap, margin menjadi terlalu optimistis 5 mag.

Perbaikannya perlu memilih definisi cutoff yang konsisten: implementasikan threshold increment persamaan 45–46, atau ikuti cutoff effective-background/M0 pada paper. Penggantian `C_th = C_floor * B_floor/B` memberikan kelanjutan increment tetap untuk area yang ditentukan, tetapi **merupakan pilihan interpretasi**, bukan bunyi literal persamaan 50 dan bukan keseluruhan resep M0 untuk teleskop.

Bug ini belum terpicu pada contoh senja Semarang yang diuji di bawah. Jangan menyimpulkan bahwa seluruh hasil senja salah karena masalah floor.

### 3. Helper teleskopik extended selalu scotopic dan bisa gagal pada senja — bug API

Lokasi: `full_rumus_crumey.py:751–773`, serta helper point source pada `664`.

`telescopic_extended_target()` memakai `R_scotopic`, `Cinf_scotopic`, dan `q=0.6` tanpa memeriksa brightness apparent. Padahal `Cinf_scotopic` menjadi negatif sekitar `B_a > 1.282 cd/m²`. Area Ricco kemudian negatif dan pangkat pecahan menghasilkan bilangan kompleks.

Reproduksi: `alpha=10 arcmin²`, `B_sky=100 cd/m²`, `D=.1 m`, `M=50`, `p=.007 m`, `F_t=1.33`. Diperoleh `B_a=6.137793 cd/m²` dan fungsi gagal dengan `TypeError: must be real number, not complex`.

Ini **tidak menyebabkan crash jalur utama hilal saat ini**, karena core memanggil `contrast_threshold(..., mode='auto')` langsung. Namun modul belum aman dipakai sebagai API Crumey untuk extended source pada seluruh rentang brightness. Perbaikannya: gunakan R, C_inf, dan q yang konsisten dengan combined, atau batasi API secara eksplisit pada domain scotopic.

### 4. Helper magnitude dan surface brightness tidak saling konsisten

Lokasi: `full_rumus_crumey.py:495–496`, `521–524`, `562–576`, dan `751–773`.

`naked_eye_extended_target()` menggabungkan limit point source dan limit surface brightness dari cabang scotopic dengan area Ricco dari combined. Ini tidak mempertahankan hubungan `A_R = Delta I/Delta B_inf`.

Contoh `A=10 arcmin²`, `B=.01 cd/m²`, `F=2`:

```text
m_lim  = 4.738406733
mu_lim = 16.022214701
mu_lim - m_lim - 2.5*log10(3600*A) = -0.106948284 mag
```

Identitas fotometri di atas seharusnya mendekati nol; pembulatan zero-point hanya menimbulkan selisih sekitar .002 mag. Di bawah floor masalah lebih besar karena point-source limit sudah tetap, sementara `mu_inf` masih dikalikan background asli. Contoh teleskop `B=1e-4`, `D=.066 m`, `M=100`, `p=.007 m`, `F_t=1.33`, `A=10`, `F=2` menghasilkan residual **+2.9357 mag**.

Kedua helper extended magnitude ini tidak digunakan jalur utama core. Perbaikannya: turunkan m_lim dan mu_lim dari satu threshold luminansi/illuminance yang sama, dengan satu pilihan cabang dan cutoff.

### 5. Obstruksi sebagai faktor skalar tidak cukup saat exit pupil melebihi pupil mata

Lokasi: `core_crescent_visibility.py:733–735`, `telescope_limit.py:133–143`.

Ini kondisi khusus reflektor pada pembesaran rendah. Faktor transmisi mengandung kehilangan luas penuh `1-(D_s/D)^2`, kemudian pupil mata memangkas exit pupil memakai `min(d,p)`. Untuk pupil yang terpusat, pemangkasan harus memperhitungkan bayangan sekunder yang ikut berada di tengah.

Inferensi dari geometri pupil annular, dengan transmisi permukaan `tau`, tanpa desentrasi dan difraksi:

```text
g_annular = tau * max(min(D/M,p)^2 - (D_s/M)^2, 0) / p²
```

Contoh `D=200 mm`, `D_s=80 mm`, `M=10`, usia 22 memberi `p≈6.833 mm`, sedangkan bayangan sekunder pada exit pupil berdiameter 8 mm. Pupil mata yang tepat terpusat tertutup seluruhnya oleh bayangan sekunder; rumus skalar masih meloloskan cahaya. Ini tidak memengaruhi default refraktor tanpa obstruksi. Perbaikannya: tangani pupil annular yang terpotong, atau nyatakan batas penggunaan koreksi obstruksi.

## Keterbatasan ilmiah untuk hilal

**Seluruh luas sabit bukan area efektif persepsi yang sudah dibuktikan.** Paper Sec. 1.2 memakai target cakram seragam dan observer teradaptasi penuh. Sec. 1.6.3 menyatakan dukungan area-only untuk target persegi panjang dengan aspect ratio hingga sekitar 7; target tidak seragam diperlakukan sebagai pendekatan. Hilal pada elongasi 8° memiliki rasio diameter/lebar maksimum sekitar 205.5, jauh di luar contoh tersebut. Rasio ini bukan pembuktian bahwa model salah, tetapi menunjukkan extrapolasi morfologi yang besar.

Kode memakai seluruh luas sabit dan mean luminance dari Kastner (`core_crescent_visibility.py:582–587`, `706–709`; `visual_limit_kastner.py:13–28`). Hilal melengkung, sangat tipis, luminansinya bervariasi, dan langit senja memiliki gradien/glare. Karena itu diperlukan kalibrasi terhadap observasi naked eye dan visual telescopic, atau model luminansi spasial/segmen efektif yang kemudian divalidasi. Crumey memberikan threshold target ideal; paper tidak menetapkan kriteria hilal yang otomatis terverifikasi.

**Observer age hanya mengubah pupil.** `core_crescent_visibility.py:717` memakai umur melalui `telescope_limit.py:117–118`; tidak ada pengali sensitivitas usia otomatis. Paper Sec. 1.2 menekankan kehilangan transparansi media mata dan kenaikan threshold, bukan sekadar pengecilan pupil. Dengan F tetap, contoh `D=66`, `M=50`, `E=10°`, `SD=.25°`, `B=1 cd/m²` memberi C_th .04212 pada umur 22 dan .03557 pada umur 65: observer lebih tua justru mendapat threshold 15.6% lebih rendah dari efek pupil saja. Ini tidak salah dalam transformasi optiknya, tetapi tidak lengkap sebagai model kemampuan observer. F dapat memasukkan usia bila dikalibrasi; dokumentasinya harus menyatakan hal tersebut.

**Pupil dan adaptasi senja belum dimodelkan.** Pupil umur 22 sekitar 6.83 mm dipakai pada seluruh brightness, tanpa respons terhadap luminansi/adaptasi. Padahal Crumey mengasumsikan adaptasi terhadap background. Untuk penggunaan senja, diameter pupil aktual atau model adaptasi yang diuji dapat menjadi input terpisah.

**Bentuk combined belum mencakup chromaticity langit senja.** Sec. 4, halaman 2617, secara eksplisit membatasi aplikasi terhadap langit biru: visibilitas perlu memasukkan chromaticity dan memerlukan data eksperimen selain target achromatic yang digunakan dalam paper. Jadi pilihan combined benar untuk threshold kanal luminansi, tetapi belum cukup untuk menyatakan seluruh proses persepsi hilal berlatar langit senja sudah dimodelkan. Contoh nyata di atas memperlihatkan bahwa masalah ini relevan, bukan sekadar kemungkinan pada background ekstrem.

**Koreksi spektral belum terhubung ke hilal.** Helper S/P tersedia, tetapi fungsi hilal langsung memakai luminansi photopic. Di scotopic, target/langit yang berbeda spektrum perlu brightness ekuivalen menurut Sec. 1.3. Untuk cahaya objek additive:

```text
B* = (rho_sky/rho_Blackwell)*B
Delta B* = (rho_hilal/rho_Blackwell)*Delta B
```

Besarnya error tidak dapat dipastikan tanpa spektrum atau S/P. Koreksi scotopic tidak boleh diterapkan begitu saja ke seluruh wilayah mesopic; paper membedakan persoalan photometry tersebut.

**F=2.5 untuk hilal merupakan pilihan aplikasi.** Panduan kategori ahli/tipikal/pemula pada `full_rumus_crumey.py:884–886` bukan hasil kalibrasi hilal di paper. F harus dinyatakan sebagai asumsi atau hasil fit, dan ketidakpastiannya diuji. Membandingkan gain optik murni juga memerlukan faktor pengamat yang konsisten; default F_naked=2.5 dan F_tel=2.4 ikut memengaruhi gain yang dilaporkan.

**Geometri elongasi merupakan aproksimasi yang diketahui.** `crescent_geometry.py:6–16` menggunakan `pi*r²*(1-cos(E))/2`; projected illuminated fraction yang lebih presisi memakai phase angle i, `pi*r²*(1+cos(i))/2`. Kesetaraan i≈180°−E mengasumsikan Matahari jauh. Pemakaian rujukan luas yang sama pada Kastner dan Crumey sudah konsisten; perubahan geometri harus diterapkan ke keduanya. Ini prioritas lebih rendah daripada bug konfigurasi dan validasi bentuk. Jangan mengganti elongasi langsung dengan phase angle ke fungsi yang masih memakai `1-cos`.

## Verifikasi yang dilakukan

1. `python -X utf8 -m unittest discover -s tests -p test_model_interfaces.py -v`: **23 tes lulus**, termasuk pipeline manual dan ekspor. Lolosnya tes kontrak tidak membuktikan akurasi observasi hilal atau domain helper yang tidak diuji.
2. `_run_verification()` pada `full_rumus_crumey.py`: **11/11 pemeriksaan lulus**.
3. `Core/crumey_validation.py`: **88/92 lulus; 4 gagal**. Kegagalan berasal dari perbandingan radius Ricco combined dengan aproksimasi persamaan 63 pada mu=21, 21.5, 21.83, 22; selisih sekitar .435–.588 arcmin. Ini perlu ditinjau sebagai pilihan cabang/toleransi aproksimasi, bukan bukti otomatis bahwa jalur utama hilal gagal. Script tetap mengembalikan exit code 0 walaupun melaporkan kegagalan.
4. Reproduksi numerik bug dan pengecekan identitas fotometri dilakukan terpisah dari tes bawaan.
5. Pipeline nyata manual: Semarang −6.917°, 110.348°, elevasi 89 m, 9/1444, tanggal pengamatan 22 Maret 2023, RH=75%, T=25°C, D=100 mm, M=50, scan 5 menit dan min altitude=2°.

| Waktu | B_sky (cd/m²) | B_a teleskop (cd/m²) | C_obj | C_th teleskop | Delta m |
|---|---:|---:|---:|---:|---:|
| Sunset | 3389.213 | 213.464 | .00488075 | .0092724 | −.69676 |
| Optimum teleskop, sekitar 18:00:59 WIB | — | 16.7100 | .0119847 | .0108649 | +.106505 |

Background teleskop pada contoh tersebut tetap di wilayah mesopic/photopic; kombinasi Eq. 41 pada jalur utama relevan. Cutoff gelap tidak terpicu. Margin positif .1065 mag adalah hasil model, bukan verifikasi hilal benar-benar terlihat; margin sekecil ini perlu dibaca bersama ketidakpastian F, bentuk, adaptasi, atmosfer, dan luminansi.

Reproduksi ringkas disertakan dalam `audit_crumey_repro.py`. Jalankan dari root proyek:

```powershell
.\.venv\Scripts\python.exe -X utf8 docs/audit_crumey_repro.py
```

Urutan tindak lanjut yang disarankan: perbaiki penerusan konfigurasi optimal; satukan helper dan cutoff pada satu kontrak threshold; tambahkan pemeriksaan domain dan identitas fotometri yang relevan; kemudian validasi/kalibrasi asumsi hilal terhadap data pengamatan. Perbaikan rumus dan kelulusan tes tetap perlu dibedakan dari validasi empiris.
