# Data masukan

- `ephemeris/de440s.bsp`: ephemeris JPL lokal untuk perhitungan astronomi.
- `locations.csv`: 82 lokasi; kolom tanpa header: nama, lintang, bujur,
  elevasi dalam meter. Loader mempertahankan bias default nol.
- `observations/bmkg_ccd.json`: 278 observasi yang dipisahkan dari skrip batch,
  beserta skema kolom dan sumber label. Label berasal dari kamera/CCD dan
  digunakan untuk perbandingan deskriptif lintas metode.

Koordinat, tanggal, label dan nilai data dipertahankan saat migrasi.
Keterangan offset dari pemilik dataset memakai tanggal ijtima **WIB** sebagai
H+0 untuk semua lokasi. Kolom tanggal berisi hari pengamatan yang sudah
dipilih; program tidak menambahkan offset lagi pada tanggal tersebut.
`hilal_visibility.paths` menyelesaikan lokasi file berdasarkan checkout,
sehingga program dapat dijalankan dari direktori kerja lain.
