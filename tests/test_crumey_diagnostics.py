"""Keep diagnostic recomputations on the same telescope threshold contract."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


import hilal_visibility.studies.diagnostics as diagnostics
from hilal_visibility.calculator import HilalVisibilityCalculator


class DiagnosticThresholdTests(unittest.TestCase):
    def test_diagnostic_and_core_match_across_optical_regimes(self):
        calc = HilalVisibilityCalculator('Uji', -7, 110, 89, 'Asia/Jakarta', 9, 1444,
                                         sumber_atmosfer='manual')
        position = {'elongation': 8, 'moon_semidiameter': .26}
        for aperture, magnification, obstruction in (
            (100, 50, 0), (100, 5000, 0), (200, 10, 80), (200, 20, 40),
        ):
            with self.subTest(D=aperture, M=magnification, Ds=obstruction):
                with patch.multiple(diagnostics, TEL_APERTURE=aperture,
                                    TEL_MAG=magnification, TEL_OBSTRUCTION=obstruction,
                                    F_TEL=2.4):
                    diagnostic = diagnostics.compute_delta_m(
                        10, 1000, 8, 'telescope', moon_sd_deg=.26)
                    result = calc.hitung_visibilitas_teleskop(
                        10, 1000, position, aperture=aperture,
                        magnification=magnification, central_obstruction=obstruction,
                        field_factor=diagnostics.F_TEL)
                    self.assertAlmostEqual(diagnostic['C_obj'], result[2])
                    self.assertAlmostEqual(diagnostic['C_th'], result[3])
                    self.assertAlmostEqual(diagnostic['delta_m'], result[4])
                    self.assertAlmostEqual(diagnostics.compute_telescope_Ba(1000), result[1])

    def test_diagnostic_rejects_unknown_mode_and_invalid_background(self):
        for mode, background in (('typo', 1000), ('telescope', 0),
                                 ('telescope', float('nan'))):
            with self.subTest(mode=mode, B=background), self.assertRaises(ValueError):
                diagnostics.compute_delta_m(10, background, 8, mode, moon_sd_deg=.26)


if __name__ == '__main__':
    unittest.main()
