"""Numerical contracts for the achromatic Crumey threshold, not crescent data validation."""

import math
from pathlib import Path
import sys
import unittest


import hilal_visibility.models.crumey as crumey
class IncrementThresholdTests(unittest.TestCase):
    def test_combined_equation_across_dark_mesopic_and_daylight_backgrounds(self):
        area, factor = 2.3e-6, 2.4
        for background in (1e-5, 1e-4, 0.01, 0.193, 1, 3.4, 100, 3400, 1e5):
            with self.subTest(background=background):
                q = crumey.q_parameter(background)
                expected = factor * background * (
                    (crumey.R_combined(background) / area) ** q
                    + crumey.Cinf_combined(background) ** q
                ) ** (1 / q)
                actual = crumey.increment_threshold(area, background, factor)
                self.assertAlmostEqual(actual / expected, 1, places=12)
                self.assertAlmostEqual(
                    crumey.contrast_threshold(area, background, factor) * background / actual,
                    1, places=12,
                )

    def test_floor_keeps_increment_nonzero_and_contrast_uses_actual_background(self):
        area = crumey.arcmin2_to_sr(10)
        at_floor = crumey.increment_threshold(area, crumey.B_FLOOR)
        for background in (0, 1e-12, 1e-7, crumey.B_FLOOR):
            with self.subTest(background=background):
                self.assertGreater(at_floor, 0)
                self.assertEqual(crumey.increment_threshold(area, background), at_floor)
                if background:
                    self.assertAlmostEqual(
                        background * crumey.contrast_threshold(area, background) / at_floor,
                        1, places=12,
                    )
        above = crumey.increment_threshold(area, crumey.B_FLOOR * (1 + 1e-8))
        self.assertLess(abs(above / at_floor - 1), 1e-7)
        with self.assertRaises(ValueError):
            crumey.contrast_threshold(area, 0)

    def test_single_regime_forms_and_floor_are_consistent(self):
        area, factor = 3e-6, 1.7
        for mode, background, R, Cinf in (
            ('scotopic', 0.01, crumey.R_scotopic, crumey.Cinf_scotopic),
            ('photopic', 100, crumey.R_photopic, crumey.Cinf_photopic),
        ):
            with self.subTest(mode=mode):
                q = 0.6 if mode == 'scotopic' else crumey.q_parameter(background)
                expected = factor * background * ((R(background) / area) ** q + Cinf(background) ** q) ** (1 / q)
                self.assertAlmostEqual(crumey.increment_threshold(area, background, factor, mode) / expected, 1, places=12)
        self.assertEqual(
            crumey.increment_threshold(area, 0, factor, 'scotopic'),
            crumey.increment_threshold(area, crumey.B_FLOOR, factor, 'scotopic'),
        )

    def test_point_and_large_area_asymptotes_share_coefficients(self):
        for background in (0, 1e-7, 0.01, 1, 100):
            with self.subTest(background=background):
                point = crumey.point_source_threshold_illuminance(background, 2)
                large = crumey.large_target_threshold_luminance(background, 2)
                self.assertAlmostEqual(
                    crumey.increment_threshold(1e-20, background, 2) * 1e-20 / point,
                    1, places=6,
                )
                self.assertAlmostEqual(
                    crumey.increment_threshold(1e10, background, 2) / large,
                    1, places=6,
                )
                self.assertAlmostEqual(crumey.ricco_area_sr(background) * large / point, 1, places=12)

    def test_bad_threshold_inputs_are_rejected_before_cutoff(self):
        for key, bad_values in (
            ('A_sr', (0, -1, math.nan, math.inf)),
            ('B', (-1, math.nan, math.inf)),
            ('F', (0, -1, math.nan, math.inf)),
        ):
            for value in bad_values:
                args = dict(A_sr=1e-6, B=1e-7, F=2)
                args[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    crumey.increment_threshold(**args)
        for background in (0, 1e-7, 1):
            with self.subTest(background=background), self.assertRaises(ValueError):
                crumey.increment_threshold(1e-6, background, mode='typo')
        for function in (crumey.point_source_threshold_illuminance,
                         crumey.large_target_threshold_luminance, crumey.ricco_area_sr):
            for value in (-1, math.nan, math.inf):
                with self.subTest(function=function.__name__, B=value), self.assertRaises(ValueError):
                    function(value)

    def test_unsupported_explicit_regimes_and_nonpositive_q_raise(self):
        for mode, background in (('scotopic', 0.04), ('scotopic', 100),
                                  ('photopic', 0), ('photopic', 1)):
            with self.subTest(mode=mode, background=background), self.assertRaises(ValueError):
                crumey.increment_threshold(1e-6, background, mode=mode)
        with self.assertRaises(ValueError):
            crumey.increment_threshold(1e-6, 1e20)


class PhotometryContractTests(unittest.TestCase):
    def test_lux_magnitude_and_luminance_surface_brightness_round_trips(self):
        for magnitude in (-25, 0, 6, 25):
            self.assertAlmostEqual(crumey.lux_to_mag(crumey.mag_to_lux(magnitude)), magnitude, places=12)
            self.assertAlmostEqual(crumey.cdm2_to_mag_arcsec2(crumey.mag_arcsec2_to_cdm2(magnitude)), magnitude, places=12)
        for area in (0.01, 10, 10000):
            excess = 0.023
            magnitude = crumey.lux_to_mag(excess * crumey.arcmin2_to_sr(area))
            mu = crumey.cdm2_to_mag_arcsec2(excess)
            self.assertAlmostEqual(mu - magnitude, 2.5 * math.log10(3600 * area), places=12)

    def test_photometry_and_magnitude_helpers_reject_nonfinite_inputs(self):
        for function in (crumey.mag_to_lux, crumey.mag_arcsec2_to_cdm2,
                         crumey.lux_to_mag, crumey.cdm2_to_mag_arcsec2,
                         crumey.naked_eye_limiting_mag, crumey.naked_eye_surface_brightness_limit):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(function=function.__name__, value=value), self.assertRaises(ValueError):
                    function(value)
        for area in (0, -1, math.nan, math.inf):
            with self.subTest(area=area), self.assertRaises(ValueError):
                crumey.naked_eye_extended_target(area, 21)

    def test_naked_eye_helpers_preserve_identity_and_increment_backend(self):
        for background in (1e-9, 1e-5, 0.01, 1, 1000):
            for area in (0.01, 10, 1000):
                with self.subTest(background=background, area=area):
                    result = crumey.naked_eye_extended_target(area, crumey.cdm2_to_mag_arcsec2(background), F=2.2)
                    self.assertAlmostEqual(
                        result['mu_lim'] - result['m_lim'], 2.5 * math.log10(3600 * area), places=12,
                    )
                    expected = crumey.increment_threshold(crumey.arcmin2_to_sr(area), background, 2.2)
                    self.assertAlmostEqual(crumey.mag_to_lux(result['m_lim']) / (expected * crumey.arcmin2_to_sr(area)), 1, places=12)

    def test_paper_dark_sky_reference_remains_close(self):
        self.assertAlmostEqual(crumey.naked_eye_limiting_mag(21.83, 2), 6.18, delta=0.05)
        self.assertAlmostEqual(crumey.naked_eye_surface_brightness_limit(21.83, 1), 24.94, delta=0.1)
        self.assertAlmostEqual(crumey.telescopic_cutoff_mag(.1), 12.70, delta=0.15)


class TelescopicThresholdTests(unittest.TestCase):
    def test_equal_source_background_dimming_and_actual_apparent_area(self):
        area, background, D, M, p, Ft = 2e-6, 100, .1, 50, .007, 1.33
        result = crumey.telescopic_extended_threshold(area, background, D, M, p, Ft, F=2.4)
        g = (min(D / M, p) / p) ** 2 / Ft
        expected = crumey.increment_threshold(M * M * area, g * background, 2.4 * math.sqrt(2))
        self.assertAlmostEqual(result['B_a'], g * background, places=12)
        self.assertEqual(result['A_app_sr'], M * M * area)
        self.assertAlmostEqual(result['delta_B_app_th'] / expected, 1, places=12)
        self.assertAlmostEqual(result['delta_B_th'] * g / expected, 1, places=12)
        self.assertAlmostEqual(result['C_th'] * background / result['delta_B_th'], 1, places=12)
        # Source and background receive the same g; their contrast is unchanged.
        self.assertAlmostEqual((g * 0.23) / result['B_a'], 0.23 / background)

    def test_telescope_helpers_match_contract_including_twilight_and_high_magnification(self):
        area = 10
        for background in (1e-9, 1e-4, 0.01, 100):
            for magnification in (5, 50, 1000):
                with self.subTest(background=background, magnification=magnification):
                    mu = crumey.cdm2_to_mag_arcsec2(background)
                    result = crumey.telescopic_extended_target(area, mu, .1, magnification)
                    self.assertTrue(math.isfinite(result['m_lim']))
                    self.assertTrue(math.isfinite(result['mu_lim']))
                    self.assertAlmostEqual(result['mu_lim'] - result['m_lim'], 2.5 * math.log10(3600 * area), places=12)
                    self.assertAlmostEqual(
                        crumey.mag_to_lux(result['m_lim']) / (result['delta_B_th'] * crumey.arcmin2_to_sr(area)), 1, places=12,
                    )
                    self.assertEqual(result['m0'], crumey.telescopic_point_source_limit(mu, .1, magnification))

    def test_point_limit_saturates_but_extended_area_keeps_actual_magnification(self):
        mu = crumey.cdm2_to_mag_arcsec2(1e-4)
        cutoff = crumey.telescopic_cutoff_mag(.1)
        for magnification in (100, 200, 1000):
            self.assertAlmostEqual(crumey.telescopic_point_source_limit(mu, .1, magnification), cutoff, places=12)
        smaller = crumey.telescopic_extended_threshold(1e-6, 1e-4, .1, 100)
        larger = crumey.telescopic_extended_threshold(1e-6, 1e-4, .1, 200)
        self.assertEqual(larger['A_app_sr'], 4 * smaller['A_app_sr'])
        self.assertTrue(smaller['floor_applied'])
        self.assertTrue(larger['floor_applied'])
        # With finite large-area increment floor, excessive M dims a resolved
        # object without indefinitely improving its sky-referred threshold.
        self.assertGreater(larger['delta_B_th'], smaller['delta_B_th'])

    def test_telescope_point_and_large_area_asymptotes_share_backend(self):
        for background in (1e-7, 0.01, 100):
            with self.subTest(background=background):
                result = crumey.telescopic_extended_target(1e-16, crumey.cdm2_to_mag_arcsec2(background), .1, 50)
                self.assertAlmostEqual(result['m_lim'], result['m0'], places=6)
                large = crumey.telescopic_extended_target(1e12, crumey.cdm2_to_mag_arcsec2(background), .1, 50)
                self.assertAlmostEqual(large['mu_lim'], large['mu_inf'], places=6)

    def test_zero_sky_and_fully_blocked_optics_have_explicit_increment_semantics(self):
        zero_sky = crumey.telescopic_extended_threshold(1e-6, 0, .1, 50)
        self.assertGreater(zero_sky['delta_B_th'], 0)
        self.assertTrue(math.isfinite(zero_sky['delta_B_th']))
        self.assertEqual(zero_sky['C_th'], math.inf)
        blocked = crumey.telescopic_extended_threshold(1e-6, 1, .1, 50, dimming_factor=0)
        self.assertEqual(blocked['B_a'], 0)
        self.assertEqual(blocked['C_th'], math.inf)
        self.assertEqual(blocked['delta_B_th'], math.inf)

    def test_invalid_optical_domains_and_field_factors_are_rejected(self):
        invalid = {
            'D': (0, -1, math.nan, math.inf),
            'M': (0, -1, math.nan, math.inf),
            'p': (0, -1, math.nan, math.inf),
            'Ft': (0, .99, -1, math.nan, math.inf),
            'F': (0, -1, math.nan, math.inf),
            'FT': (0, -1, math.nan, math.inf),
            'FM': (0, -1, math.nan, math.inf),
            'dimming_factor': (-1, 1.01, math.nan, math.inf),
        }
        for key, values in invalid.items():
            for value in values:
                args = dict(A_sr=1e-6, B=1, D=.1, M=50)
                args[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    crumey.telescopic_extended_threshold(**args)
        for function in (crumey.telescopic_point_source_limit, crumey.telescopic_extended_target):
            args = dict(mu_sky=21, D=.1, M=50, Ft=.7)
            if function is crumey.telescopic_extended_target:
                args['alpha_arcmin2'] = 10
            with self.subTest(function=function.__name__), self.assertRaises(ValueError):
                function(**args)

    def test_overflowing_apparent_geometry_reports_domain_error(self):
        with self.assertRaises(ValueError):
            crumey.telescopic_extended_threshold(1e-6, 1, .1, 1e200)
        with self.assertRaises(ValueError):
            crumey.telescopic_point_source_limit(21, .1, 1e200)


class VisibilityInputTests(unittest.TestCase):
    def test_negative_or_nonfinite_excess_and_background_are_rejected(self):
        for excess, background in ((-1, 1), (math.nan, 1), (math.inf, 1),
                                   (1, 0), (1, -1), (1, math.nan), (1, math.inf)):
            for function in (crumey.is_visible, crumey.crumey_visibility):
                with self.subTest(function=function.__name__, excess=excess, background=background), self.assertRaises(ValueError):
                    function(excess, background, 1e-6)
            with self.subTest(function='hilal', excess=excess, background=background), self.assertRaises(ValueError):
                crumey.hilal_naked_eye_visibility(excess, background, 8, .26)

    def test_zero_source_is_valid_but_unknown_mode_is_always_rejected(self):
        result = crumey.hilal_naked_eye_visibility(0, 1000, 0, .26)
        self.assertFalse(result['visible'])
        self.assertEqual(result['delta_m'], -math.inf)
        with self.assertRaises(ValueError):
            crumey.hilal_naked_eye_visibility(0, 1000, 0, .26, mode='typo')


if __name__ == '__main__':
    unittest.main()
