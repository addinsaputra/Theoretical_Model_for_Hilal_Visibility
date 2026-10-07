# Perbaikan Crumey dan status validasi hilal — 5 Oktober 2026

Implementasi mata telanjang dan teleskop kini memakai satu kontrak ambang increment luminansi. Konfigurasi optik diteruskan utuh selama pencarian waktu optimal, dan helper fotometri memakai zero point yang konsisten. Perbaikan ini menyelesaikan temuan implementasi utama pada [audit baseline](reviews/AUDIT_CRUMEY_2026-10-05.md). **Kelulusan pemeriksaan rumus tidak memvalidasi penglihatan manusia terhadap hilal.**

## Perubahan implementasi

Baseline aktif mata telanjang dan teleskop disamakan menjadi `F=2.0` pada
7 Oktober 2026 atas permintaan pengguna. Angka perbandingan observasi di
laporan ini berasal dari artefak dengan konfigurasi historis `F=1.8` dan
belum dihitung ulang menggunakan baseline baru.

| Masalah baseline | Perilaku setelah perbaikan |
| --- | --- |
| Parameter optik hilang pada scan/refinement | Satu konfigurasi tervalidasi dipakai saat sunset, coarse scan, dan refinement; mode teleskop nonaktif tetap dihormati |
| Helper scotopic dipakai di background senja | Default combined konsisten untuk core, helper point/extended, dan Ricco; mode eksplisit sederhana diperiksa domainnya |
| Contrast floor menghasilkan increment menuju nol | Ambang increment tetap nonzero di bawah floor; contrast membaginya dengan background aktual |
| Magnitude dan surface brightness memakai koefisien/zero point berbeda | Keduanya berasal dari ambang luminansi yang sama dengan `Z_V=2.54e-6 lux` |
| Obstruksi dikalikan sebagai skalar setelah pupil dipotong | Area annular dihitung setelah pemotongan pupil mata; optik terblokir memberi margin `-inf` tanpa crash |
| Input fisik tidak valid menghasilkan NaN/threshold palsu | Pemeriksaan domain menolak input negatif, nonfinite, regime tidak sesuai, dan konfigurasi optik tidak fisik |

File utama: `src/hilal_visibility/models/crumey.py`, `src/hilal_visibility/calculator.py`, dan `src/hilal_visibility/models/telescope.py`. Diagnostik memakai backend yang sama. Luas sabit bersama tetap mengikuti baseline elongasi, dihitung sebagai `pi*r²*sin(elongation/2)²` agar stabil dekat konjungsi. Ini stabilisasi numerik, bukan perubahan menjadi model morfologi/fase yang telah dikalibrasi.

Telaah lanjutan juga menyamakan fotometri sumber Kastner dengan zero point V: rasio flux memakai `10**(0.4*(10-m))`, dan `S10_TO_NL=0.26195630393381236` diturunkan dari flux bintang V=10 per deg². Pembulatan lama `2.51`/`0.263` menghasilkan residual sekitar 0.007–0.009 mag. Koefisien phase law tetap. [Laporan kelemahan hilal](CRUMEY_HILAL_LIMITATIONS.md) membahas domain phase law, jarak, morfologi, warna, adaptasi, optik, dan interpretasi threshold secara terpisah dari konsistensi satuan.

## Kontrak threshold

Dengan background `B` dan luas `A` dalam steradian:

```text
B_eff = max(B, 1e-5 cd/m²)
delta_B_th = F * B_eff * [(R(B_eff)/A)^q + C_inf(B_eff)^q]^(1/q)
C_th = delta_B_th / B                         # B > 0
margin = 2.5 * [log10(L_excess/B) - log10(C_th)]
```

`increment_threshold` menerima `B=0`; contrast memerlukan `B>0`. Luas threshold harus positif. Kalkulator menangani luas hilal nol sebagai sumber tidak terlihat. `mode='auto'` memakai combined; scotopic eksplisit dibatasi `B<=0.03426 cd/m²` dan photopic eksplisit `B>=3.4 cd/m²`. Batas tersebut menyatakan domain bentuk sederhana; tidak menyatakan akurasi hilal di seluruh domain combined.

Pada teleskop dengan pupil terpusat:

```text
tau = transmission**n_surfaces
g = tau * max(min(D/M,p)**2 - (Ds/M)**2, 0) / p**2
B_app = g * B_sky; L_app = g * L_excess; A_app = M**2 * A
phi = sqrt(2) * F                         # FM=1 sebagai asumsi
delta_B_sky_th = increment_threshold(A_app,B_app,phi) / g
```

Diameter pada rumus optik harus memakai satuan yang sama. API backend menggunakan meter; API kalkulator menggunakan mm dan mengonversinya. `g=0` menghasilkan ambang sky tak hingga dan margin `-inf`. Transmisi target/background identik, sehingga `C_obj` tetap; pembesaran tidak mengalikan contrast objek.

**Keputusan cutoff:** increment dibekukan pada nilai floor untuk *luas aktual yang diberikan*. Pada teleskop luas aktual tetap `M²A` bahkan ketika `B_app` berada di bawah floor. Ini ekstensi kontinu yang dinyatakan secara eksplisit, berbeda dari Eq. 50 literal yang membekukan contrast dan pendekatan extended-source `M0` pada Sec. 3.3 paper. Kurva point source mencapai plateau; target luas dapat semakin sulit pada pembesaran ekstrem akibat dimming. Kebijakan ini tidak diklaim sebagai transkripsi seluruh aturan cutoff paper atau hasil validasi empiris hilal.

Identitas fotometri yang diuji:

```text
I_th = delta_B_th * A_sr
m_lim = -2.5 log10(I_th/Z_V)
mu_lim = m_lim + 2.5 log10(A_arcsec²)
```

Zero point surface brightness diturunkan menjadi `12.584205637`, bukan dicampur dengan angka pembulatan paper `12.58` atau `13.99`.

## Verifikasi perangkat lunak

Tes mencakup penerusan konfigurasi default/custom sepanjang workflow, pupil aktual, obstruksi yang memblokir pupil, batas refinement, floor nonzero/continuity, asymptote point/large target, background senja, identitas fotometri, overflow/domain, geometri dekat konjungsi, serta kegagalan atmosfer dan ekspor. Pemeriksaan referensi Section 3 memakai mode scotopic agar membandingkan cabang yang sesuai; kontrak combined diperiksa terpisah. Toleransi aproksimasi tidak dilonggarkan untuk menutupi perbedaan cabang.

Jalankan:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m compileall -q src scripts tests docs
.\.venv\Scripts\python.exe -X utf8 scripts/validate_crumey.py
.\.venv\Scripts\python.exe -X utf8 docs/audit_crumey_repro.py
```

Hasil verifikasi pada checkout ini:

| Pemeriksaan | Hasil |
| --- | --- |
| Suite `unittest` lengkap | **145/145 lulus** |
| `scripts/validate_crumey.py` | **100/100 lulus**, exit code 0 |
| Verifikasi bawaan `src/hilal_visibility/models/crumey.py` | **11/11 lulus** |
| `compileall` untuk Core/tests/docs | Lulus |
| Probe implementasi aktif | Exit code 0; residual identitas fotometri 0 hingga `1.8e-15 mag` |

Nilai di atas memverifikasi implementasi/kontrak yang dipilih. Mereka tidak menyatakan akurasi observasional hilal. Hasil perbandingan data dan alasan pengecualian kasus disimpan pada [laporan observasi](../validation/crumey_empirical/report.md).

## Status empiris dan asumsi hilal

Pengguna mengonfirmasi seluruh 278 label BMKG berasal dari kamera/CCD atau citra digital melalui teleskop, tanpa konfigurasi teleskop dan jam percobaan aktual. Workbook sumber cocok dengan tuple observasi; tanda `+1` menandai offset hari. Maka **0 observasi memenuhi syarat untuk kalibrasi Crumey visual**. Tidak ada faktor `F`, sensitivitas usia, atau fraksi area produksi yang diubah untuk mengejar label CCD.

[Studi observasi](../validation/crumey_empirical/report.md) menggunakan atmosfer IFS nyata yang disimpan untuk replay, tanggal/lokasi dataset, dan konfigurasi referensi 100 mm/50×. Ini perbandingan deskriptif antara prediksi visual dan label pencitraan. Waktu optimal model tidak dianggap waktu pengamatan aktual. Label negatif galeri juga tidak membuktikan kegagalan deteksi pada upaya visual yang terverifikasi.

Hasil seluruh dataset setelah penyamaan fotometri sumber: atmosfer berhasil untuk **278/278 kasus**, dengan **276 kasus dapat dimodelkan** pada scan altitude Bulan ≥2°. Kasus #27 dan #29 tidak memiliki scene yang memenuhi batas itu dan dikeluarkan dari denominator, bukan dijadikan prediksi negatif. Pada 276 kasus lengkap (138 label positif/138 negatif), diperoleh TP=104, TN=54, FP=84, FN=34, sehingga kesepakatan seimbang dengan label CCD **57.25%**. Interval bootstrap tanggal 95% adalah 52.87–61.86%, bersyarat pada dataset ini dan tidak memasukkan ketidakpastian metode, instrumen, waktu, awan, atau seleksi data. Angka tersebut bukan akurasi penglihatan manusia. Hasil 57.61% yang dicatat pada tahap sebelumnya memakai fotometri sumber yang masih dibulatkan.

Pemeriksaan artefak terpisah mencakup **14.440 scene**, hash dataset/input/runtime, ID kasus, kesamaan snapshot, area, throughput, threshold, contrast, flux magnitude sumber, margin, batas altitude, serta maksimum scan. Residual relatif identitas flux sumber maksimum `2.44e-15`. Tidak ada scene mencapai floor; background apparent minimum `1.99118e-4 cd/m²` masih di atas `1e-5 cd/m²`. Jadi perbandingan ini juga tidak menguji kebijakan cutoff gelap terhadap data. Hasil pemeriksaan tersimpan di [integrity_checks.json](../validation/crumey_empirical/integrity_checks.json).

Skenario fraksi area 1, 0.5, 0.25, dan 0.1 mempertahankan luminansi excess permukaan. Artinya skenario mengambil subset sumber yang seragam dan flux total turun bersama area; ini tidak mempertahankan flux atau memodelkan profil cusp/limb hilal. Perbandingan menggunakan sampel waktu coarse/refinement baseline, bukan optimisasi waktu mandiri setiap morfologi. Hasil sensitivitas tidak mengidentifikasi bentuk hilal terbaik.

Penurunan area dari 1 menjadi 0.1 menurunkan margin optimum pada sampel yang sama dengan median **0.0683 mag** dan maksimum **0.3856 mag**, serta mengubah satu klasifikasi dari 276 kasus. Pada kasus #90, margin area penuh `+0.00141 mag` menjadi `-0.04167 mag` untuk area 0.1. Kasus itu juga berpindah sisi ambang ketika pembulatan fotometri diperbaiki: dengan konversi lama pada sampel waktu yang sama, margin `-0.00658 mag`. Ini memperlihatkan ketidakstabilan klasifikasi sangat dekat threshold, bukan bukti bahwa salah satu fraksi area merupakan bentuk hilal yang benar. Fraksi 0.5/0.25/0.1 mempunyai kesepakatan CCD 57.61%; tidak ada fraksi yang dipilih sebagai kalibrasi produksi.

Untuk kalibrasi mendatang, pipeline mewajibkan label boolean visual dengan metode terpisah (`naked_eye` atau `visual_telescope`), percobaan terverifikasi, jendela waktu aktual, dan konfigurasi optik/pengamat aktual untuk teleskop. Seluruh campaign/lunasi ditahan di luar training secara bergiliran bila metadata tersedia, dengan fallback per tanggal; lokasi dan hari dalam campaign yang sama tidak dibagi antara train/test. Tes sintetis hanya membuktikan guard dan isolasi statistik, bukan menyediakan data empiris.

Asumsi yang masih membutuhkan data visual: luas efektif versus luminansi hilal yang tidak seragam, aspek sabit ekstrem, adaptasi/pupil senja, perbedaan spektrum hilal–langit, sensitivitas pengamat/usia, kualitas optik/seeing, dan kesempatan percobaan pada label negatif. `observer_age` hanya estimator pupil fallback; `pupil_diameter_mm` menyediakan override aktual tanpa mengarang koreksi sensitivitas usia.

Rujukan utama: PDF Crumey yang diberikan pengguna; [versi penerbit](https://academic.oup.com/mnras/article/442/3/2600/1052389). Sumber label: [galeri hilal BMKG](https://hilal.bmkg.go.id/gallery), dengan klasifikasi metode sesuai konfirmasi pengguna.
