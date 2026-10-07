# Struktur proyek setelah perapian

Perapian 7 Oktober 2026 dilakukan dalam tiga tahap: pemisahan sumber daya,
pembentukan paket Python, lalu penyesuaian peluncur/dokumentasi dan verifikasi.

```text
src/hilal_visibility/
  calculator.py         # Alur perhitungan dan API HilalVisibilityCalculator
  cli.py                # Input interaktif lokasi tunggal/multi-lokasi
  batch.py              # Workflow perbandingan observasi
  ephemeris.py          # Hisab Skyfield/DE440s
  paths.py              # Lokasi data, keluaran, cache dan arsip
  datasets.py           # Pembacaan dataset tanpa menjalankan batch
  locations.py          # Pembacaan dan pemilihan lokasi
  models/               # Schaefer, Kastner, Crumey, teleskop, luas sabit
  atmosphere/           # ECMWF IFS, MERRA-2 dan provenance
  reports/              # Ekspor Excel tunggal/gabungan dan grafik gabungan
  studies/              # Diagnostik dan studi sensitivitas/perbandingan
scripts/                # Peluncur, pemeriksaan referensi, contoh workbook
data/                   # Ephemeris, lokasi dan dataset observasi
docs/reviews/           # Saran perubahan serta audit historis
tests/                  # Regresi model, ekspor dan tata letak paket
validation/             # Artefak penelitian historis beserta provenance
outputs/                # Hasil pengguna dan studi baru, diabaikan Git
.cache/                 # Cache cuaca dan catatan pemeriksaan lokal
```

## Penggunaan

Untuk menjalankan program sehari-hari, ikuti
[panduan terminal](RUNNING.md). Peluncur yang menggantikan file lama:

| File lama | Perintah dari folder proyek |
| --- | --- |
| `core_crescent_visibility.py` | `.\.venv\Scripts\python.exe .\scripts\run_visibility.py` — menu `1` tunggal / `2` multi-lokasi |
| `core_multi_location.py` | `.\.venv\Scripts\python.exe .\scripts\run_batch.py` — seluruh dataset observasi |

Instalasi editable mempertahankan data di checkout proyek:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe scripts/run_visibility.py
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q src scripts tests
.venv\Scripts\python.exe scripts/validate_crumey.py
```

API pustaka:

```python
from hilal_visibility import HilalVisibilityCalculator
```

Skrip dapat dijalankan langsung dari checkout melalui
[`scripts/`](../scripts/README.md). Lokasi sumber daya tidak bergantung pada
direktori kerja proses. `pyproject.toml` mendefinisikan paket `src` dan console
entry points mengikuti [konfigurasi setuptools](https://setuptools.pypa.io/en/latest/userguide/pyproject_config.html).
Instalasi ini ditujukan untuk penggunaan bersama checkout dan direktori data;
pengemasan ephemeris sebagai distribusi mandiri belum menjadi bagian migrasi.

## Pemetaan sumber kode untuk penggunaan sebagai pustaka

Tabel ini menunjukkan lokasi kode perhitungan. Untuk membuka menu terminal,
gunakan dua file peluncur pada bagian Penggunaan di atas.

| Lokasi/modul lama | Lokasi/modul sekarang |
| --- | --- |
| `Core/core_crescent_visibility.py` | `hilal_visibility.calculator` + `hilal_visibility.cli` |
| Ekspor/grafik gabungan pada program utama | `hilal_visibility.reports.multi_location` |
| `Core/core_multi_location.py` | `hilal_visibility.batch` |
| `Core/data_hisab.py` | `hilal_visibility.ephemeris` |
| `Core/full_rumus_crumey.py` | `hilal_visibility.models.crumey` |
| `Core/visual_limit_schaefer.py` | `hilal_visibility.models.schaefer` |
| `Core/visual_limit_kastner.py` | `hilal_visibility.models.kastner` |
| `Core/telescope_limit.py` | `hilal_visibility.models.telescope` |
| `Core/crescent_geometry.py` | `hilal_visibility.models.geometry` |
| `Core/atmosfer_*.py` | `hilal_visibility.atmosphere.*` |
| `Core/analisis_diagnostik_crumey.py` | `hilal_visibility.studies.diagnostics` |
| `Core/ifs_sensitivity_study.py` | `hilal_visibility.studies.ifs_sensitivity` |
| `Core/crumey_empirical_validation.py` | `hilal_visibility.studies.crumey_empirical` |
| `Core/change*.md` | `docs/reviews/change*.md` |
| `Core/de440s.bsp` | `data/ephemeris/de440s.bsp` |
| `Core/output/` | `outputs/` |

Import dari nama modul lama perlu mengikuti pemetaan ini. Fungsi perhitungan,
kontrak luminansi/transmisi/threshold, dan baseline bersama `F=2.0` dipertahankan.
Loader studi tetap menerima dataset Python literal yang diberikan eksplisit;
dataset bawaan sekarang JSON, tanpa mengimpor atau menjalankan skrip batch.

## Arsip dan pemeriksaan

Arsip pada `validation/` menyimpan konfigurasi/tanggal ketika dibuat dan
tidak dihitung ulang oleh migrasi. Keluaran studi baru secara default menuju
`outputs/`, sehingga hasil historis tidak tertimpa. Catatan audit historis
boleh menyebut nama lama atau nomor baris lama dalam konteks commit asal.

Sebelum migrasi direkam hash ephemeris, seluruh file validasi dan hasil lama,
serta hasil numerik fixture Semarang. Setelah migrasi, 318 hash file sama,
278 baris observasi identik, 82 lokasi tersedia, dan angka sunset/enam
timestep valid sama persis. Pemeriksaan akhir:

- **171/171 tes regresi lulus**, termasuk CLI manual dan impor/peluncur dari
  direktori kerja lain.
- **100/100 pemeriksaan referensi Crumey lulus**; probe audit aktif berhasil.
- Kompilasi `src`, `scripts` dan `tests` berhasil; `git diff --check` bersih.
- Semua tautan dokumentasi lokal yang diperiksa tersedia.
- Replay offline satu observasi berhasil melalui worker proses terpisah,
  dengan keluaran di cache lokal sebagai pemeriksaan migrasi.

Kode lama disimpan sementara pada `.cache/legacy-source/Core/` sebagai
backup lokal yang diabaikan Git. Direktori aktif `Core/` sudah digantikan
struktur paket di atas. Hasil pemeriksaan migrasi bukan validasi empiris
penglihatan manusia atau perhitungan ulang seluruh dataset penelitian.
