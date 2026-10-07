# Peluncur program

Gunakan perintah dari **folder utama proyek**, yang berisi `.venv/` dan
`scripts/`. Untuk langkah menu dan contoh isian, buka
[panduan menjalankan dari terminal](../docs/RUNNING.md).

## Lokasi tunggal atau multi-lokasi yang Anda pilih

```powershell
.\.venv\Scripts\python.exe .\scripts\run_visibility.py
```

Menu awal `1` = lokasi tunggal, `2` = multi-lokasi. Pada multi-lokasi,
pilih semua 82 lokasi atau beberapa nomor, misalnya `1,2`.
Ini peluncur pengganti `core_crescent_visibility.py`.

## Seluruh dataset observasi penelitian

```powershell
.\.venv\Scripts\python.exe .\scripts\run_batch.py
```

Menjalankan 278 kasus dari dataset penelitian, dengan konfigurasi batch.
Ini peluncur pengganti `core_multi_location.py`. Hasil Excel/CSV disimpan
otomatis ke `outputs/`.

## Alat tambahan

Jalankan satu perintah sesuai kebutuhan:

| Kebutuhan | Perintah |
| --- | --- |
| Pemeriksaan referensi Crumey | `.\.venv\Scripts\python.exe .\scripts\validate_crumey.py` |
| Contoh workbook dengan atmosfer manual | `.\.venv\Scripts\python.exe .\scripts\generate_single_excel_example.py --mode sunset` |
| Pilihan studi sensitivitas IFS | `.\.venv\Scripts\python.exe .\scripts\study_ifs_sensitivity.py --help` |
| Pilihan perbandingan dataset observasi | `.\.venv\Scripts\python.exe .\scripts\compare_crumey_observations.py --help` |
| Probe audit implementasi aktif | `.\.venv\Scripts\python.exe .\scripts\audit_crumey_repro.py` |
| Diagnostik CSV di `outputs/` | `.\.venv\Scripts\python.exe .\scripts\analyze_crumey.py` |

Logika perhitungan berada pada paket `src/hilal_visibility/`.
Nama dan lokasi modul dijelaskan pada [panduan struktur](../docs/PROJECT_STRUCTURE.md).
