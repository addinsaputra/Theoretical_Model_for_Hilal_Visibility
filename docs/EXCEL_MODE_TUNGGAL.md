# Excel lokasi tunggal

Panggilan `calculator.simpan_ke_excel(filepath)` menghasilkan laporan baru dengan enam lembar yang dapat dibaca. Perhitungan perantara disimpan pada `model_trace` ketika model berjalan; ekspor memakai snapshot tersebut, tanpa API cuaca atau perhitungan model tambahan. Jalankan perhitungan kembali untuk mendapatkan rincian lengkap jika objek hasil berasal dari versi lama.

| Lembar | Isi |
| --- | --- |
| Ringkasan | Keputusan, margin, waktu evaluasi, kondisi langit, window model dan grafik mode optimal. |
| Input & Konfigurasi | Lokasi, waktu, atmosfer, bias, pencarian waktu, teleskop, pupil, field factor, konstanta dan asumsi aktif. |
| Rantai Model | Geometri, luas, `M_v`, `L*`, luminansi intrinsik, ekstingsi, luminansi pengamat, latar, optik, koefisien Crumey, threshold, margin dan keputusan. |
| Atmosfer | Snapshot sunset dan kedua optimum; airmass, komponen ekstingsi U/B/V/R/I, night/twilight/daylight band V. |
| Timestep Data | Tabel yang dapat difilter, dengan blok input bersama, NE dan TEL. Kolom dapat dilipat memakai kelompok Excel. |
| Info Program | Panduan satuan, nilai kosong/nonfinite, metode, batas asumsi dan status validasi. |

`Ringkasan` dan `Rantai Model` mempunyai kolom D/E untuk mata telanjang/teleskop saat sunset serta F/G untuk waktu optimal masing-masing. Waktu optimal kedua metode tidak harus sama. Perbandingan threshold gain selalu memakai NE dan TEL pada waktu yang sama, termasuk pada optimum teleskop.

Besaran yang sebelumnya tidak terlihat sekarang mencakup `M_v`, `D_luas` dalam deg², luas arcmin² dan sr, `L*` dalam S10, luminansi intrinsik dan setelah atmosfer dalam nL/cd/m², fluks lux, `k_v`, `A_V = DM[2]`, `T_V`, `D_ap`, `D_s`, `M`, pupil mata dan exit pupil, transmisi total, faktor optik annular `g`, luas tampak `M²A`, field factor dasar/monokular/efektif, floor, `R`, `C∞`, `q`, luas Ricco, ambang increment/kontras, rasio terhadap ambang, margin serta keputusan.

`D_luas` Kastner adalah **luas**, sedangkan `D_ap` teleskop adalah **diameter**. `A_V` adalah ekstingsi total, sedangkan `Δm` adalah margin visibilitas. `L` adalah luminansi excess, sehingga `C_obj=L/B_sky`. Atmosfer sudah masuk pada perhitungan latar Schaefer; latar tidak ditransmisikan ulang dengan `T_V` sumber. Tekanan dicatat sebagai input refraksi dan bukan input eksplisit ekstingsi.

Nilai finite tetap numerik, termasuk transmisi yang sangat kecil. Format sel membatasi digit tampilan tanpa membulatkan data sebelum disimpan. Waktu disimpan sebagai tanggal/jam Excel tanpa timezone; label dan konfigurasi menyatakan zona waktu. Infinity disimpan sebagai teks `inf`/`-inf`, dan grafik mengosongkan nilai nonfinite. Parameter tidak berlaku, teleskop nonaktif, optimum tidak tersedia dan diagnostik belum direkam dibiarkan kosong. Data di bawah horizon mempertahankan geometri tetapi tidak menampilkan sentinel `-99` sebagai hasil visibilitas.

Grafik memakai worksheet tersembunyi `_Data Grafik`, menyertakan hasil scan dan optimum refinement yang tersedia, serta garis ambang nol. Window dan durasinya berasal dari grid model, bukan lama pengamatan yang diukur. Ekspor tetap menulis file pendamping `.xlsx.atmosphere.json` untuk provenance atmosfer.

Contoh yang dapat dibuat ulang memakai lokasi Semarang, Ramadhan 1444 H, ephemeris DE440s, dan **atmosfer manual** RH 75%, T 25 °C, P 1013.25 hPa. Teleskop referensi 100 mm, 50×. Contoh ini bukan hasil pengamatan aktual maupun kalibrasi.

```powershell
.venv\Scripts\python.exe docs/generate_single_excel_example.py
.venv\Scripts\python.exe docs/generate_single_excel_example.py --mode sunset
```

Pemeriksaan regresi meliputi pemisahan kolom/waktu, angka numerik, identitas fluks fotometri, transmisi tunggal, throughput target/latar, luas tampak, field factor, pembentukan langit, hasil nonaktif/tidak tersedia, infinity dan ekspor tanpa perhitungan ulang. Kelulusan pemeriksaan tersebut tidak membuktikan validitas empiris asumsi hilal atau sensitivitas manusia. Label BMKG yang dikonfirmasi sebagai CCD tidak digunakan untuk mengkalibrasi model visual.
