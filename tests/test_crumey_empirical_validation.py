"""Software checks for empirical-study safeguards; not empirical validation."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

import hilal_visibility.studies.crumey_empirical as study
def visual_case(number, event, observed, method='naked_eye'):
    case = dict(observation_no=number, date=event, observed=observed, label_method=method,
                timezone_str='UTC',
                visual_attempt_verified=True,
                actual_attempt_window=dict(start_utc=f'{event}T10:00:00+00:00',
                                           end_utc=f'{event}T10:30:00+00:00'))
    if method == 'visual_telescope':
        case['actual_telescope'] = {k: v for k, v in study.TELESCOPE.items() if k != 'field_factor'}
    return case


def synthetic_rows():
    # Artificial examples exist solely to test train/test isolation.
    rows = []
    for event_index, pair in enumerate(((-2, 1), (-1, 2), (.1, 3), (.2, 4)), 1):
        event = f'2024-04-{event_index:02d}'
        for label, margin in zip((False, True), pair):
            rows.append(dict(case=visual_case(len(rows) + 1, event, label),
                             prediction_time_window_verified=True,
                             margin_by_area_fraction={'1.0': margin}))
    return rows


class EligibilityTests(unittest.TestCase):
    def test_all_actual_bmkg_labels_are_imaging_and_ineligible(self):
        rows = study.load_observations(study.OBSERVATIONS_PATH)
        self.assertEqual(len(rows), 278)
        self.assertEqual(len(set(row['date'] for row in rows)), 26)
        self.assertEqual(sum(row['observed'] for row in rows), 139)
        self.assertTrue(all(row['label_method'] == 'ccd' for row in rows))
        self.assertTrue(all(not study.calibration_eligibility(row)['eligible'] for row in rows))

    def test_ccd_unknown_and_mixed_methods_cannot_fit_visual_f(self):
        for methods in (None, ['ccd', 'ccd'], ['unknown', 'unknown'],
                        ['naked_eye', 'ccd'], ['naked_eye', 'visual_telescope']):
            with self.subTest(methods=methods), self.assertRaises(ValueError):
                study.fit_field_factor([-1, 1], [False, True], ['a', 'b'], observation_methods=methods)

    def test_actual_visual_attempt_and_time_window_are_required(self):
        case = visual_case(1, '2024-04-09', True)
        self.assertTrue(study.calibration_eligibility(case)['eligible'])
        for change in (dict(visual_attempt_verified=False), dict(actual_attempt_window=None),
                       dict(actual_attempt_window=dict(start_utc='2024-04-09T10:00:00', end_utc='2024-04-09T10:01:00')),
                       dict(actual_attempt_window=dict(start_utc='2024-04-09T10:10:00+00:00', end_utc='2024-04-09T10:01:00+00:00'))):
            with self.subTest(change=change):
                self.assertFalse(study.calibration_eligibility({**case, **change})['eligible'])

    def test_actual_telescope_configuration_is_required(self):
        case = visual_case(1, '2024-04-09', True, 'visual_telescope')
        self.assertTrue(study.calibration_eligibility(case)['eligible'])
        del case['actual_telescope']['magnification']
        self.assertIn('actual_optical_and_observer_configuration_is_missing',
                      study.calibration_eligibility(case)['reasons'])

    def test_nonboolean_labels_and_unrelated_event_dates_are_ineligible(self):
        case = visual_case(1, '2024-04-09', True)
        case['observed'] = 'False'
        self.assertIn('observation_label_is_not_boolean', study.calibration_eligibility(case)['reasons'])
        case = visual_case(1, '2024-04-09', True)
        case['actual_attempt_window'] = dict(start_utc='2024-06-09T10:00:00+00:00',
                                            end_utc='2024-06-09T10:30:00+00:00')
        self.assertIn('actual_attempt_window_does_not_match_observation_date',
                      study.calibration_eligibility(case)['reasons'])

    def test_grouped_fit_rejects_unverified_prediction_time_or_optics(self):
        rows = synthetic_rows()
        rows[0]['prediction_time_window_verified'] = False
        with self.assertRaisesRegex(ValueError, 'actual visual attempt window'):
            study.grouped_validation(rows)
        rows = synthetic_rows()
        for row in rows:
            row['case'] = visual_case(row['case']['observation_no'], row['case']['date'],
                                      row['case']['observed'], 'visual_telescope')
        with self.assertRaisesRegex(ValueError, 'actual telescope'):
            study.grouped_validation(rows)


class StatisticalContractTests(unittest.TestCase):
    def test_confusion_matrix_and_balanced_accuracy(self):
        metrics = study.binary_metrics([False, False, True, True], [False, True, True, True])
        self.assertEqual((metrics['tn'], metrics['fp'], metrics['fn'], metrics['tp']), (1, 1, 0, 2))
        self.assertEqual(metrics['balanced_accuracy'], .75)
        self.assertIsNone(study.binary_metrics([True], [True])['balanced_accuracy'])

    def test_nonboolean_labels_and_predictions_are_rejected(self):
        for invalid in ('False', 'True', 0, 1, np.nan, None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    study.binary_metrics([invalid, True], [False, True])
                with self.assertRaises(ValueError):
                    study.binary_metrics([False, True], [invalid, True])
                with self.assertRaises(ValueError):
                    study.fit_field_factor([-1, 1], [invalid, True], ['a', 'b'],
                                            observation_methods=['naked_eye', 'naked_eye'])
        self.assertEqual(study.binary_metrics([np.bool_(False), True], [False, np.bool_(True)])['accuracy'], 1)

    def test_date_weighting_does_not_count_many_sites_as_many_events(self):
        weights = study.event_weights(['a', 'a', 'a', 'b'])
        np.testing.assert_allclose(weights, [1 / 3, 1 / 3, 1 / 3, 1])
        self.assertAlmostEqual(weights[:3].sum(), weights[3])

    def test_field_factor_margin_shift_and_reference_tie_break(self):
        fit = study.fit_field_factor([-1, 1], [False, True], ['a', 'b'],
                                    observation_methods=['naked_eye', 'naked_eye'])
        self.assertEqual(fit['field_factor'], study.F_REF)
        self.assertEqual(fit['shift_mag'], 0)
        fit = study.fit_field_factor([1, 3], [False, True], ['a', 'b'],
                                    observation_methods=['naked_eye', 'naked_eye'])
        self.assertGreater(fit['field_factor'], study.F_REF)
        self.assertAlmostEqual(fit['shift_mag'], 2.5 * np.log10(fit['field_factor'] / study.F_REF))

    def test_held_out_date_labels_never_change_its_fitted_factor(self):
        rows = synthetic_rows()
        baseline = study.grouped_validation(rows)
        altered = copy.deepcopy(rows)
        for row in altered:
            if row['case']['date'] == '2024-04-01':
                row['case']['observed'] = not row['case']['observed']
        changed = study.grouped_validation(altered)
        before = next(f for f in baseline['folds'] if f['held_out_event'] == '2024-04-01')
        after = next(f for f in changed['folds'] if f['held_out_event'] == '2024-04-01')
        self.assertEqual(before['field_factor'], after['field_factor'])
        self.assertNotIn('2024-04-01', before['train_events'])
        self.assertEqual(before['train_n'], 6)

    def test_two_dates_in_one_lunation_are_held_out_together(self):
        rows = synthetic_rows()
        for index, row in enumerate(rows):
            row['case']['hijri_year'] = 1445
            row['case']['hijri_month'] = 10 if index < 4 else 11
        evaluation = study.grouped_validation(rows)
        self.assertEqual(len(evaluation['folds']), 2)
        fold = next(item for item in evaluation['folds'] if item['held_out_event'] == '1445-10')
        self.assertEqual(fold['held_out_dates'], ['2024-04-01', '2024-04-02'])
        self.assertEqual(fold['train_events'], ['1445-11'])
        self.assertEqual(fold['test_n'], 4)

    def test_fit_rejects_nonfinite_margins_and_invalid_bounds(self):
        for margins, bounds in (([np.nan, 1], study.F_BOUNDS), ([1, np.inf], study.F_BOUNDS),
                                ([1, 2], (-1, 20)), ([1, 2], (study.F_REF + .1, 20)),
                                ([1, 2], (.5, np.inf))):
            with self.subTest(margins=margins, bounds=bounds), self.assertRaises(ValueError):
                study.fit_field_factor(margins, [False, True], ['a', 'b'], bounds=bounds,
                                        observation_methods=['naked_eye', 'naked_eye'])

    def test_bounds_require_exactly_two_values(self):
        for bounds in ((.5,), (.5, 20, 100), None):
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                study.fit_field_factor([-1, 1], [False, True], ['a', 'b'], bounds=bounds,
                                        observation_methods=['naked_eye', 'naked_eye'])

    def test_zero_luminance_margin_roundtrips_export_resume_and_report(self):
        import json
        from hilal_visibility.models.crumey import visibility_margin_mag
        margin = visibility_margin_mag(0.0, 0.1)
        self.assertEqual(margin, float('-inf'))
        row = dict(case=visual_case(1, '2024-04-09', False), status='complete', error=None,
                   margin_ref=margin, margin_by_area_fraction={str(f): margin for f in study.AREA_FRACTIONS},
                   samples=[dict(luminansi_hilal_nl=0.0, delta_m_ne=margin, delta_m_tel=margin)])
        row['case']['label_method'] = 'ccd'
        encoded = study.prediction_json_record(row)
        self.assertEqual(encoded['samples'][0]['delta_m_tel'], '-Infinity')
        self.assertEqual(study.decoded_margin(encoded['margin_ref']), margin)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            study.write_json(output / 'snapshot.json', encoded)
            replay = json.loads((output / 'snapshot.json').read_text(encoding='utf-8'))
            metrics = study.save_analysis(dict(cases=[replay]), output)
            self.assertEqual(metrics['complete'], 1)
            self.assertEqual(metrics['area_fraction_comparisons'][0]['cross_method_agreement']['tn'], 1)
            self.assertEqual(json.loads((output / 'metrics.json').read_text(encoding='utf-8'))['complete'], 1)
            self.assertIn('1 tanggal dan 1 campaign', (output / 'report.md').read_text(encoding='utf-8'))
            # API/weather storage remains strict: a nonfinite atmosphere is
            # not encoded as a legitimate zero-signal visibility margin.
            with self.assertRaises(ValueError):
                study.write_json(output / 'invalid_weather.json', dict(relative_humidity_2m=float('nan')))

    def test_ccd_analysis_exports_descriptive_metrics_without_any_f_fit(self):
        rows = synthetic_rows()
        for row in rows:
            row['case']['label_method'] = 'ccd'
            row['status'] = 'complete'
            for fraction in study.AREA_FRACTIONS:
                row['margin_by_area_fraction'][str(fraction)] = row['margin_by_area_fraction']['1.0']
        with tempfile.TemporaryDirectory() as folder:
            metrics = study.save_analysis(dict(cases=rows), Path(folder))
        self.assertFalse(metrics['empirical_visual_validation'])
        self.assertFalse(metrics['default_calibration_applied'])
        self.assertTrue(all(not row['eligible'] for row in metrics['visual_calibration_eligibility']))
        self.assertTrue(all('descriptive_full_sample_fit' not in row for row in metrics['area_fraction_comparisons']))


if __name__ == '__main__':
    unittest.main()
