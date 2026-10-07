"""Regression checks for optical propagation and physical crescent inputs.

These fixtures verify implementation contracts; they are not observational
validation of the crescent model or an empirical observer calibration.
"""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


from hilal_visibility.calculator import HilalVisibilityCalculator
from hilal_visibility.models.telescope import TelescopeVisibilityModel, extended_surface_correction_factor


class OpticalDomainTests(unittest.TestCase):
    def setUp(self):
        self.model = TelescopeVisibilityModel()
        self.parameters = dict(D=100, Ds=0, M=50, age=22, t1=0.95, n=6)

    def test_invalid_optical_inputs_are_rejected(self):
        cases = {
            'D': (0, -1, math.nan, math.inf),
            'Ds': (-1, 100, 101, math.nan, math.inf),
            'M': (0, -1, math.nan, math.inf),
            'De': (0, -1, math.nan, math.inf),
            'age': (-1, math.nan, math.inf),
            't1': (0, -1, 1.01, math.nan, math.inf),
            'n': (-1, 2.5, math.nan, math.inf, True),
            'theta': (-1, math.nan, math.inf),
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        self.model.calculate_factors(**{**self.parameters, name: value})

    def test_annular_exit_pupil_is_clipped_before_area_loss(self):
        # Exit pupil 20 mm with an 8 mm central shadow, pupil 12 mm.
        factors = self.model.calculate_factors(D=200, Ds=80, M=10, De=12, t1=0.9, n=2)
        expected = 0.9**2 * (12**2 - 8**2) / 12**2
        old_scalar = 0.9**2 * (1 - (80 / 200)**2)
        self.assertAlmostEqual(factors['surface_brightness_factor'], expected)
        self.assertNotAlmostEqual(expected, old_scalar)
        self.assertFalse(factors['optically_blocked'])
        self.assertEqual(factors['FB'], factors['FI'])

    def test_secondary_shadow_can_block_a_centred_eye_pupil(self):
        for pupil in (7, 8):
            with self.subTest(pupil=pupil):
                factors = self.model.calculate_factors(D=200, Ds=80, M=10, De=pupil)
                self.assertEqual(factors['surface_brightness_factor'], 0)
                self.assertTrue(factors['optically_blocked'])
        factors = self.model.calculate_factors(D=200, Ds=80, M=10, De=8.001)
        self.assertGreater(factors['surface_brightness_factor'], 0)

    def test_unclipped_annulus_agrees_with_scalar_obstruction(self):
        factors = self.model.calculate_factors(D=100, Ds=40, M=50, De=7)
        expected = (2 / 7)**2 * 0.95**6 * (1 - 0.4**2)
        self.assertAlmostEqual(factors['surface_brightness_factor'], expected)

    def test_active_extended_wrappers_preserve_excess_contrast(self):
        result = self.model.apply_corrections(1000, 100, 100, 40, 50, De=7)
        self.assertAlmostEqual(result['I_eff'] / result['B_eff'], 0.1)
        self.assertAlmostEqual(result['delta_m'], -2.5)
        g = extended_surface_correction_factor(1000, 100, 50, 40, 0.95, 6, 22)
        factors = self.model.calculate_factors(D=100, Ds=40, M=50, age=22)
        self.assertEqual(g, factors['surface_brightness_factor'])


class CompleteOptimalPropagationTests(unittest.TestCase):
    def setUp(self):
        self.calc = HilalVisibilityCalculator(
            'Optical fixture', -7, 110, 89, 'Asia/Jakarta', 9, 1444,
            sumber_atmosfer='manual', manual_rh=75, manual_t=25,
        )
        self.sunset = datetime(2023, 3, 22, 18, tzinfo=timezone(timedelta(hours=7)))
        self.position = dict(
            sun_alt=-1, sun_az=270, moon_alt=6, moon_az=278,
            phase_angle=170, elongation=8, moon_semidiameter=0.26,
            moon_distance_km=380000, moon_width=0.003,
        )

    def run_fixture(self, config, *, use_telescope=True, source_function=None):
        def position_at(timestamp, **kwargs):
            elapsed = (timestamp - self.sunset).total_seconds() / 60
            return {**self.position, 'moon_alt': 6 - elapsed}

        # Only astronomical/weather inputs are fixtures. Visibility and the
        # complete sunset -> scan -> refinement call path execute real code.
        self.calc.hasil['observing_location'] = object()
        with (
            patch.object(self.calc, 'hitung_ijtima', return_value=(self.sunset, self.sunset)),
            patch.object(self.calc, 'tentukan_tanggal_pengamatan',
                         return_value=(self.sunset, self.sunset, 75, 25, 1013.25)),
            patch.object(self.calc, 'hitung_posisi_matahari_bulan', side_effect=position_at),
            patch.object(self.calc, 'hitung_sky_brightness_schaefer',
                         return_value=(1000, 0.2, 0.5, 10**-0.2)),
            patch.object(self.calc, 'hitung_luminansi_hilal_kastner',
                         return_value=10, side_effect=source_function),
            patch.object(self.calc, '_fetch_atmosfer_window', return_value=object()),
            patch.object(self.calc, '_atmosfer_pada_waktu', return_value=(75, 25, 1013.25)),
            patch.object(self.calc, 'tampilkan_hasil_akhir'),
            patch.object(self.calc, 'hitung_visibilitas_teleskop',
                         wraps=self.calc.hitung_visibilitas_teleskop) as telescope,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = self.calc.jalankan_perhitungan_lengkap(
                mode='optimal', min_moon_alt=2, use_telescope=use_telescope, **config,
            )
        return result, telescope.call_args_list

    def test_defaults_and_custom_settings_reach_sunset_scan_and_refinement(self):
        custom = dict(aperture=100, magnification=50, transmission=0.7, n_surfaces=10,
                      central_obstruction=40, observer_age=70, field_factor=3.1,
                      pupil_diameter_mm=3.0)
        for configuration in ({}, custom):
            with self.subTest(configuration=configuration):
                result, calls = self.run_fixture(configuration)
                self.assertGreater(len(calls), result['total_timesteps'] + 1)
                recorded = result['tel_params']
                expected = self.calc.hitung_visibilitas_teleskop(
                    10, 1000, self.position, **recorded,
                )
                for call in calls:
                    self.assertEqual(call.kwargs, recorded)
                self.assertTrue(all(call.args[2]['moon_alt'] <= 5 for call in calls[1:]))
                self.assertAlmostEqual(result['c_th_tel'], expected[3])
                for sample in result['all_timestep_results']:
                    if sample['valid']:
                        self.assertAlmostEqual(sample['c_th_tel'], expected[3])
                self.assertAlmostEqual(result['optimal_result_tel']['c_th_tel'], expected[3])
                self.assertGreaterEqual(result['optimal_time_tel'],
                                        self.sunset + timedelta(minutes=1))
                self.assertGreaterEqual(result['optimal_moon_alt_tel'], 2)

    def test_disabled_telescope_remains_disabled_in_optimal_mode(self):
        result, calls = self.run_fixture({}, use_telescope=False)
        self.assertEqual(calls, [])
        self.assertIsNone(result['optimal_time_tel'])
        self.assertIsNone(result['optimal_result_tel'])
        self.assertTrue(all(sample['delta_m_tel'] == 0
                            for sample in result['all_timestep_results'] if sample['valid']))
        self.assertIsNone(result['threshold_difference_mag'])
        self.assertIsNone(result['crumey_tel_regime'])

    def test_residual_factor_inherits_naked_eye_through_scan_and_refinement(self):
        for configuration in ({}, {'F_naked': 3.7}, {'F_naked': 3.7, 'field_factor': None}):
            with self.subTest(configuration=configuration):
                result, calls = self.run_fixture(configuration)
                F = configuration.get('F_naked', 2.0)
                self.assertEqual(result['tel_params']['field_factor'], F)
                self.assertTrue(all(call.kwargs['field_factor'] == F for call in calls))
                scenes = [result, *result['all_timestep_results'], result['optimal_result_tel']]
                for scene in scenes:
                    if scene and scene.get('valid', True):
                        self.assertEqual(scene['field_factor_comparison'], 'shared_residual_factor')
                        self.assertAlmostEqual(scene['model_trace']['telescope']['threshold']['phi'], F * math.sqrt(2))
                        self.assertAlmostEqual(scene['threshold_difference_mag'], scene['delta_m_tel'] - scene['delta_m_ne'])
                        self.assertEqual(scene['threshold_difference_mag'], scene['telescope_gain'])

    def test_independent_residual_factors_are_explicit_and_do_not_change_optics(self):
        shared, _ = self.run_fixture({'F_naked': 3.7})
        shared_difference = shared['threshold_difference_mag']
        shared_optics = shared['model_trace']['telescope']['optics']
        independent, _ = self.run_fixture({'F_naked': 3.7, 'field_factor': 1.8})
        self.assertEqual(independent['field_factor_comparison'], 'independent_residual_factors')
        self.assertEqual(shared_optics, independent['model_trace']['telescope']['optics'])
        self.assertAlmostEqual(independent['threshold_difference_mag'] - shared_difference,
                               2.5 * math.log10(3.7 / 1.8))

    def test_direct_timestep_inherits_residual_factor(self):
        with (patch.object(self.calc, 'hitung_posisi_matahari_bulan', return_value=self.position),
              patch.object(self.calc, 'hitung_sky_brightness_schaefer', return_value=(1000, .2, .5, 10**-.2)),
              patch.object(self.calc, 'hitung_luminansi_hilal_kastner', return_value=10)):
            result = self.calc.hitung_visibilitas_pada_waktu(
                self.sunset, object(), F_naked=3.7, cached_atm=(75, 25, 1013.25))
        self.assertAlmostEqual(result['model_trace']['telescope']['threshold']['phi'], 3.7 * math.sqrt(2))
        self.assertEqual(result['field_factor_comparison'], 'shared_residual_factor')

    def test_refinement_does_not_optimise_below_requested_altitude(self):
        # Increasing excess luminance would favor a later, lower crescent.
        # The search is nevertheless required to honor min_moon_alt=2.
        source = lambda position, transmission: 10 * (7 - position['moon_alt'])
        result, _ = self.run_fixture({}, source_function=source)
        for mode in ('ne', 'tel'):
            self.assertEqual(result[f'optimal_time_{mode}'], self.sunset + timedelta(minutes=4))
            self.assertEqual(result[f'optimal_moon_alt_{mode}'], 2)

    def test_invalid_configuration_fails_before_weather_or_ephemeris(self):
        for kwargs in ({'transmission': math.nan}, {'central_obstruction': 100},
                       {'field_factor': 0}, {'pupil_diameter_mm': 0},
                       {'not_an_optical_option': 1}):
            with self.subTest(kwargs=kwargs):
                with patch.object(self.calc, 'hitung_ijtima') as conjunction:
                    with self.assertRaises((ValueError, TypeError)):
                        self.calc.jalankan_perhitungan_lengkap(**kwargs)
                    conjunction.assert_not_called()

    def test_actual_pupil_override_has_no_implicit_age_sensitivity_factor(self):
        young = self.calc.hitung_visibilitas_teleskop(
            10, 1000, self.position, observer_age=22, pupil_diameter_mm=3,
        )
        older = self.calc.hitung_visibilitas_teleskop(
            10, 1000, self.position, observer_age=70, pupil_diameter_mm=3,
        )
        self.assertEqual(young, older)

    def test_blocked_optics_are_not_visible(self):
        L, B, contrast, threshold, margin = self.calc.hitung_visibilitas_teleskop(
            10, 1000, self.position, aperture=200, central_obstruction=80,
            magnification=10, pupil_diameter_mm=7,
        )
        self.assertEqual((L, B), (0, 0))
        self.assertEqual(contrast, 0.01)
        self.assertEqual(threshold, math.inf)
        self.assertEqual(margin, -math.inf)

    def test_blocked_optics_survive_the_complete_optimal_path(self):
        config = dict(aperture=200, central_obstruction=80, magnification=10,
                      pupil_diameter_mm=7)
        result, _ = self.run_fixture(config)
        self.assertEqual(result['delta_m_tel'], -math.inf)
        self.assertEqual(result['telescope_gain'], -math.inf)
        self.assertEqual(result['optimal_delta_m_tel'], -math.inf)
        for sample in result['all_timestep_results']:
            if sample['valid']:
                self.assertEqual(sample['delta_m_tel'], -math.inf)
                self.assertEqual(sample['telescope_gain'], -math.inf)

    def test_invalid_source_and_geometry_inputs_fail_in_both_modes(self):
        methods = (self.calc.hitung_visibilitas_naked_eye, self.calc.hitung_visibilitas_teleskop)
        for method in methods:
            for luminance, sky in ((-1, 1000), (math.nan, 1000), (10, 0), (10, math.inf)):
                with self.subTest(method=method.__name__, luminance=luminance, sky=sky):
                    with self.assertRaises(ValueError):
                        method(luminance, sky, self.position)
            for name, value in (('elongation', -1), ('elongation', 181),
                                ('elongation', math.nan), ('moon_semidiameter', 0),
                                ('moon_semidiameter', math.nan)):
                with self.subTest(method=method.__name__, name=name, value=value):
                    with self.assertRaises(ValueError):
                        method(10, 1000, {**self.position, name: value})


if __name__ == '__main__':
    unittest.main()
