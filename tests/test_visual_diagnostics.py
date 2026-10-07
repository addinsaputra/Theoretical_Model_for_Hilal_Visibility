"""Actual luminance diagnostics must not select or alter threshold curves."""

from pathlib import Path
import sys
import unittest


from hilal_visibility.models.crumey import (
    B_FLOOR, cdm2_to_nL, hilal_naked_eye_visibility, luminance_diagnostics,
    threshold_parameters, telescopic_extended_threshold,
)


class VisualDiagnosticsTests(unittest.TestCase):
    def test_working_regime_boundaries_and_actual_background_floor(self):
        for B, regime in ((0, 'scotopic'), (B_FLOOR / 2, 'scotopic'),
                          (0.0049, 'scotopic'), (0.005, 'mesopic'),
                          (5, 'mesopic'), (5.001, 'photopic')):
            with self.subTest(B=B):
                coefficients = threshold_parameters(B)
                self.assertEqual(coefficients['B_actual'], B)
                self.assertEqual(coefficients['regime'], regime)
                self.assertEqual(coefficients['achromatic_extrapolation'], regime != 'scotopic')
                self.assertEqual(coefficients['curve'], 'combined')
                self.assertEqual(coefficients['B_eval'], max(B, B_FLOOR))

    def test_naked_eye_diagnostics_follow_actual_sky_luminance(self):
        for B in (0.001, 0.5, 10):
            result = hilal_naked_eye_visibility(cdm2_to_nL(B / 10), cdm2_to_nL(B), 8, 0.26)
            expected = luminance_diagnostics(B)
            self.assertEqual(result['regime'], expected['regime'])
            self.assertEqual(result['achromatic_extrapolation'], expected['achromatic_extrapolation'])

    def test_telescope_regime_uses_apparent_sky_after_optics(self):
        for g in (0, 0.0001, 0.1, 1):
            with self.subTest(g=g):
                result = telescopic_extended_threshold(1e-6, 10, 0.1, 50, dimming_factor=g)
                expected = luminance_diagnostics(10 * g)
                self.assertEqual(result['B_a'], 10 * g)
                self.assertEqual(result['regime'], expected['regime'])
                self.assertEqual(result['achromatic_extrapolation'], expected['achromatic_extrapolation'])


if __name__ == '__main__':
    unittest.main()
