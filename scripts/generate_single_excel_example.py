"""Generate a reviewable workbook with real ephemeris and explicit manual weather.

Run from the repository root:
  python scripts/generate_single_excel_example.py
  python scripts/generate_single_excel_example.py --mode sunset
"""

import _bootstrap  # noqa: F401
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
from hilal_visibility.calculator import HilalVisibilityCalculator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('optimal', 'sunset'), default='optimal')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / 'outputs' / f'Contoh_Excel_Tunggal_{args.mode}_Semarang.xlsx'
    calculator = HilalVisibilityCalculator(
        'Contoh Semarang — atmosfer manual', -6.917, 110.348, 89,
        'Asia/Jakarta', 9, 1444, sumber_atmosfer='manual',
        manual_rh=75, manual_t=25, manual_p=1013.25,
    )
    calculator.jalankan_perhitungan_lengkap(
        mode=args.mode, use_telescope=True, aperture=100, magnification=50,
        interval_menit=1, min_moon_alt=2,
    )
    calculator.simpan_ke_excel(str(output))


if __name__ == '__main__':
    main()
