# Peninjauan dan penerapan change4

Tanggal: 7 Oktober 2026. Basis peninjauan: checkout lokal pada commit
`58268df`, dibandingkan dengan saran pada [change4.md](change4.md).

Saran utama diterima. Singularitas RH dan kontrak residual F memerlukan
perbaikan implementasi. Phase law, morfologi, warna senja, adaptasi, PSF/seeing
dan kalibrasi pengamat tetap memerlukan penelitian/data tersendiri; tidak
ditambahkan koreksi empiris tanpa dasar.

| Saran | Keputusan dan pelaksanaan |
| --- | --- |
| RH 100% | Diterima. Schaefer menolak RH nonfinite atau di luar `0 <= RH < 100%` dengan `ValueError` yang menyatakan di luar domain model. Sampel meteorologi RH 100% tetap sah pada adapter atmosfer. Tidak dilakukan clipping tambahan menjadi 99.9%. |
| Catat kegagalan saturasi | Batch menyimpan status invalid, pesan error, bias dan provenance cuaca yang sudah diperoleh, termasuk RH mentah, pada sidecar ekspor. Tidak membuat prediksi negatif dari evaluasi yang gagal. |
| Arti F | Diterima. F menjadi residual laboratory/observer/target/viewing scaling. Atmosfer, throughput, magnifikasi dan FT/FM yang sudah eksplisit tidak masuk ulang. Nilai referensi belum dikalibrasi khusus hilal. |
| F bersama | Default kalkulator memakai referensi 2.0 untuk NE; teleskop mengikuti F_NE bila override tidak diberikan atau `None`. Pewarisan berlaku untuk F_NE kustom, sunset, scan dan refinement. Standalone wrapper teleskop juga memakai referensi 2.0. |
| Dua F independen | Tetap didukung sebagai konfigurasi eksplisit. Output `field_factor_comparison` membedakan base bersama dari dua residual F berbeda. Label menjadi selisih threshold; nama baru `threshold_difference_mag` dan `optimal_threshold_difference_mag`. Kunci/kolom gain lama adalah alias kompatibilitas. |
| Mapping kemahiran | Dihapus dari docstring/default hilal. Tidak ada mapping 2.0/2.5/3.0 ke mahir/tipikal/pemula. |
| Diagnostik regime | Label NE sebelumnya sudah ada; dilengkapi untuk teleskop, timestep, optimum dan ekspor. Latar teleskop memakai `g B`, bukan latar NE atau floor. Flag mesopic/photopic menyatakan extrapolasi achromatic. |
| Klaim IFS/ekstingsi | README menyatakan arsip IFS HRES berbeda dari ERA5. RH/T, elevasi, lokasi/waktu dipakai dalam parameterisasi; tekanan digunakan pada refraksi, bukan koefisien ekstingsi langsung. Klaim akurasi lokal tanpa validasi dihapus. |
| Pembulatan acos | Diterima. Argumen cosine separation dibatasi pada [-1, 1] sebelum acos. Kasus arah berimpit yang menghasilkan 1.0000000000000002 diuji. |

Audit change4 menyebut F_NE=2.5 dan F_tel=2.4 pada core; itu benar untuk
default sebelum revisi. Batch penelitian sebelumnya memakai F_NE=F_tel=1.8.
Atas permintaan pengguna, **seluruh baseline aktif mata telanjang dan teleskop
kini 2.0**, termasuk kalkulator, batch dan studi perbandingan. Diagnostik
sensitivitas juga memakai dua referensi 2.0. Override pengguna tetap didukung;
nilai referensi ini bukan kalibrasi visual.

## Kontrak dan perubahan hasil

`L_obj = L_intrinsik × T_V`, `C_obj = L_obj/B_sky`, `B_a = g B_sky`,
`A_a = M² A` dan `phi = F F_T F_M` tetap menjadi kontrak pipeline.
Residual F bersama saling menghilangkan dari rasio threshold pada waktu
yang sama. Bila dua F berbeda, selisih threshold mencakup kontribusi
`2.5 log10(F_NE/F_tel)`.

Baseline bersama 2.0 menggantikan referensi 2.5 pada revisi sebelumnya.
Pada input dan waktu yang sama, threshold menjadi 0.8 kali dan margin naik
sekitar **0.24228 mag** untuk kedua metode. Rasio threshold kedua metode
tetap sama ketika base F berubah bersama. Baseline batch/studi 1.8 → 2.0
menaikkan threshold sebesar 2/1.8 dan menurunkan margin sekitar **0.11439 mag**.
Pemanggil yang memberikan field factor secara eksplisit tetap memakai nilai
itu. Artefak perbandingan yang tersimpan mempertahankan konfigurasi historisnya
dan tidak dihitung ulang sebagai bagian perubahan baseline ini.

Definisi kerja regime adalah scotopic `<0.005 cd/m²`, mesopic `0.005–5`,
photopic `>5`. Flag `achromatic_extrapolation` menandai penggunaan model
luminansi achromatic pada mesopic/photopic. Label ini tidak memilih cabang
threshold, tidak mengukur adaptasi pengamat, dan tidak memvalidasi hilal.
`mode='auto'` tetap memakai combined pada semua latar. Bahkan kasus scotopic
masih memiliki keterbatasan spektrum, morfologi dan kalibrasi yang dijelaskan
pada [telaah keterbatasan](../CRUMEY_HILAL_LIMITATIONS.md).

Excel tunggal menampilkan diagnostik di Rantai Model dan Timestep Data.
CSV batch menambahkan kolom di bagian akhir; Excel batch memakai worksheet
Diagnostik Visual tanpa menggeser kolom data lama. Optimum yang tidak
tersedia, metode yang dinonaktifkan dan observasi gagal menghasilkan nilai
diagnostik kosong; margin infinity disimpan sebagai teks.

## Sumber yang diperiksa

- [Crumey (2014), Sec. 1.2, 1.3, 1.6.4, 3.2 dan 4](https://arxiv.org/html/1405.4209):
  residual scaling dibedakan dari perubahan stimulus, faktor monokular
  masuk threshold, regime merupakan definisi kerja, dan aplikasi berwarna
  memerlukan data tambahan.
- [Open-Meteo, Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api#data-sources):
  produk IFS disusun dari run operasional dan dibedakan dari ERA5/ERA5-Land.

## Pemeriksaan

Hasil pemeriksaan akhir:

- Seluruh **168 tes unittest lulus** (baseline sebelum revisi: 156 tes).
- `compileall` untuk src, scripts dan tests selesai tanpa error.
- Pemeriksaan referensi Crumey **100/100 lulus**.
- `git diff --check` bersih.

Perintah yang dijalankan:

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 -m compileall -q src scripts tests
python -X utf8 scripts/validate_crumey.py
```

Tes baru meliputi RH batas/hasil bias, provenance batch saturasi, pembulatan
acos, pewarisan F kustom, pengaruh dua F pada margin tanpa perubahan optik,
regime menurut latar actual/apparent, serta ekspor diagnostik CSV/XLSX.
Pemeriksaan geometri memakai DE440s lokal dan input atmosfer manual;
kelulusan numerik tidak membuktikan validasi visual empiris.
