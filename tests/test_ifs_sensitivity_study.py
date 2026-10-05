"""Deterministic checks for the real-API IFS sensitivity study (no network)."""

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Core'))
from atmosfer_ecmwf_ifs import AtmosphericWindow, ECMWF_IFSAPIError
import ifs_sensitivity_study as study

START = datetime(2024, 4, 9, 10, tzinfo=timezone.utc)


def window(temperature=(20, 30, 25), dew=(15, 20, 18), rh_offset=0, pressure=1000):
    table = pd.DataFrame({
        'date': pd.date_range(START, periods=3, freq='h'),
        'temperature_2m': temperature, 'dew_point_2m': dew,
        'relative_humidity_2m': study.rh_from_temperature_dewpoint(temperature, dew) + rh_offset,
        'surface_pressure': pressure,
    })
    return AtmosphericWindow(table, {'latitude': -7.0, 'longitude': 110.0, 'elevation': 10.0})


def captured_pair(land=None, nearest=None):
    land = land or window()
    nearest = nearest or window()
    return {
        'case': dict(observation_no=1, location='Uji', date='2024-04-09', latitude=-7.0,
                     longitude=110.0, elevation_m=10.0, sample_group='coastal'),
        'sunset_utc': START.isoformat(),
        'windows': {'land': land.to_record(), 'nearest': nearest.to_record()}, 'errors': {},
    }


class RHInterpolationTests(unittest.TestCase):
    def test_known_magnus_result_and_saturation(self):
        self.assertAlmostEqual(float(study.rh_from_temperature_dewpoint(30, 20)), 55.077491, places=5)
        self.assertEqual(float(study.rh_from_temperature_dewpoint(25, 26)), 100)

    def test_constant_consistent_anchors_have_no_difference(self):
        data = study.rh_diagnostics(window((25, 25, 25), (20, 20, 20)),
                                    [START + timedelta(minutes=minute) for minute in (0, 15, 60, 120)])
        np.testing.assert_allclose(data['rh_T_Td_minus_direct_pp'], 0, atol=1e-12)
        np.testing.assert_allclose(data['rh_nonlinearity_only_pp'], 0, atol=1e-12)

    def test_nonlinearity_is_zero_at_anchors_but_present_between_them(self):
        data = study.rh_diagnostics(window(), [START, START + timedelta(minutes=30), START + timedelta(hours=1)])
        self.assertAlmostEqual(data.iloc[0]['rh_nonlinearity_only_pp'], 0)
        self.assertAlmostEqual(data.iloc[2]['rh_nonlinearity_only_pp'], 0)
        self.assertGreater(abs(data.iloc[1]['rh_nonlinearity_only_pp']), .1)
        np.testing.assert_allclose(data['rh_anchor_difference_interpolated_pp'], 0, atol=1e-12)

    def test_anchor_discrepancy_is_not_mislabelled_as_nonlinearity(self):
        targets = [START, START + timedelta(minutes=30)]
        original = study.rh_diagnostics(window(), targets)
        shifted = study.rh_diagnostics(window(rh_offset=2), targets)
        np.testing.assert_allclose(shifted['rh_anchor_difference_interpolated_pp'], -2)
        np.testing.assert_allclose(shifted['rh_nonlinearity_only_pp'], original['rh_nonlinearity_only_pp'])
        np.testing.assert_allclose(shifted['rh_T_Td_minus_direct_pp'], original['rh_T_Td_minus_direct_pp'] - 2)

    def test_missing_dew_point_and_uncovered_or_naive_times_fail(self):
        without_dew = AtmosphericWindow(window().hourly.drop(columns='dew_point_2m'))
        with self.assertRaises(ECMWF_IFSAPIError):
            study.rh_diagnostics(without_dew, [START])
        with self.assertRaises(ECMWF_IFSAPIError):
            study.rh_diagnostics(window(), [START - timedelta(minutes=1)])
        with self.assertRaises(ValueError):
            study.rh_diagnostics(window(), [START.replace(tzinfo=None)])

    def test_nonfinite_and_singular_formula_inputs_fail(self):
        for temperature, dewpoint in ((math.nan, 20), (25, math.inf), (-243.04, -244), (25, -243.04)):
            with self.subTest(temperature=temperature, dewpoint=dewpoint):
                with self.assertRaises(ValueError):
                    study.rh_from_temperature_dewpoint(temperature, dewpoint)


class SanityAndGridTests(unittest.TestCase):
    def test_elevation_envelope_accepts_normal_high_altitude_pressure(self):
        self.assertAlmostEqual(study.standard_pressure_hpa(0), 1013.25)
        high_pressure = study.standard_pressure_hpa(4000)
        self.assertLess(high_pressure, 700)
        self.assertEqual(study.atmosphere_flags(60, 10, high_pressure, 4000), [])
        self.assertEqual(study.atmosphere_flags(80, 25, 1010, 5), [])

    def test_gross_errors_and_pressure_unit_mix_are_flagged(self):
        self.assertIn('temperature_outside_study_bounds', study.atmosphere_flags(80, 400, 1010, 5))
        for pressure in (15, 101325, math.nan):
            self.assertIn('pressure_outside_elevation_envelope', study.atmosphere_flags(80, 25, pressure, 5))
        self.assertIn('rh_invalid', study.atmosphere_flags(120, 25, 1010, 5))

    def test_pressure_reference_rejects_unsupported_elevations(self):
        for elevation in (math.inf, math.nan, 12000):
            with self.assertRaises(ValueError):
                study.standard_pressure_hpa(elevation)

    def test_grid_distance_handles_identical_points_and_dateline(self):
        self.assertEqual(study.distance_km(-7, 110, -7, 110), 0)
        self.assertAlmostEqual(study.distance_km(0, 0, 0, 1), 111.195080, places=5)
        self.assertAlmostEqual(study.distance_km(0, 179.5, 0, -179.5), 111.195080, places=5)

    def test_identical_grid_and_data_have_zero_grid_effect(self):
        summary, traces, flags = study.analyze_case(captured_pair(), 120)
        self.assertTrue(summary['same_grid'])
        self.assertEqual(summary['grid_delta_rh_pp_max_abs'], 0)
        self.assertEqual(summary['grid_delta_temperature_C_max_abs'], 0)
        self.assertEqual(summary['grid_delta_pressure_hPa_max_abs'], 0)
        self.assertEqual(len(traces), 242)
        self.assertEqual(flags, [])

    def test_changed_grid_measurements_are_detected_independent_of_record_order(self):
        land = window()
        nearest = window((22, 32, 27), pressure=1004)
        nearest.metadata['latitude'] = -7.1
        capture = captured_pair(land, nearest)
        capture['windows'] = dict(reversed(list(capture['windows'].items())))
        summary, _, _ = study.analyze_case(capture, 120)
        self.assertFalse(summary['same_grid'])
        self.assertEqual(summary['grid_delta_temperature_C_max_abs'], 2)
        self.assertEqual(summary['grid_delta_pressure_hPa_max_abs'], 4)
        self.assertGreater(summary['grid_delta_rh_pp_max_abs'], 1)

    def test_missing_grid_is_incomplete_without_synthetic_comparison(self):
        capture = captured_pair()
        del capture['windows']['nearest']
        capture['errors']['nearest'] = 'offline'
        summary, traces, _ = study.analyze_case(capture, 120)
        self.assertEqual(summary['status'], 'incomplete')
        self.assertNotIn('grid_delta_rh_pp_max_abs', summary)
        self.assertEqual(len(traces), 121)

    def test_failed_study_still_exports_errors_and_reports_no_samples(self):
        capture = captured_pair()
        capture['windows'] = {}
        capture['errors'] = {'case': 'offline'}
        payload = dict(product_name='IFS', observations_file='source.py', observations_sha256='abc',
                       dataset_cases=278, duration_minutes=120, cases=[capture])
        with tempfile.TemporaryDirectory() as folder:
            metrics = study.save_results(payload, Path(folder))
            self.assertEqual(metrics['complete_cases'], 0)
            self.assertEqual(metrics['failed_cases'], 1)
            self.assertEqual(metrics['minute_samples'], 0)
            self.assertIsNone(metrics['max_rh_total_difference_pp'])
            self.assertIn('offline', (Path(folder) / 'raw_inputs.json').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
