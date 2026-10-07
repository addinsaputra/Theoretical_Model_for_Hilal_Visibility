"""Batch dates must select the physical day before weather and visibility."""
import contextlib
import csv
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import load_workbook
from hilal_visibility import batch
from hilal_visibility.calculator import HilalVisibilityCalculator


class BatchObservationDateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observation = batch.parse_obs(batch.OBSERVATIONS[264])
        cls.results = {}
        for mode in ('sunset', 'optimal'):
            with (patch.object(batch, 'SUMBER_ATMOSFER', 'manual'),
                  patch.object(batch, 'CALC_MODE', mode),
                  contextlib.redirect_stdout(io.StringIO())):
                cls.results[mode] = batch.run_single_observation(cls.observation, verbose=False)

    def test_reported_september_case_uses_dataset_date_in_both_modes(self):
        for mode, result in self.results.items():
            with self.subTest(mode=mode):
                self.assertTrue(result['success'], result.get('error'))
                self.assertEqual(result['tanggal_obs'], '2026-09-12')
                self.assertEqual(result['tanggal_model'], '2026-09-12')
                self.assertEqual(result['tanggal_hisab'], '2026-09-11')
                self.assertEqual(result['delta_day_offset'], 1)
                self.assertTrue(result['tanggal_cocok'])
                self.assertEqual(result['sunset_local'].date(), date(2026, 9, 12))
                self.assertGreater(result['moon_alt_sunset'], 10)
                if mode == 'optimal':
                    self.assertIsNotNone(result['optimal_time_tel'])
                    self.assertEqual(result['optimal_time_tel'].date(), date(2026, 9, 12))

    def test_gorontalo_and_sentani_share_h0_before_their_local_sunsets(self):
        observation = batch.parse_obs(batch.OBSERVATIONS[274])
        with (patch.object(batch, 'SUMBER_ATMOSFER', 'manual'),
              patch.object(batch, 'CALC_MODE', 'sunset'),
              contextlib.redirect_stdout(io.StringIO())):
            result = batch.run_single_observation(observation, verbose=False)
        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(result['delta_day_offset'], 1)
        self.assertEqual(result['tanggal_hisab'], '2026-09-11')
        self.assertEqual(result['tanggal_hisab'], self.results['sunset']['tanggal_hisab'])
        self.assertEqual(result['sunset_local'].date(), date(2026, 9, 12))

    def test_correct_date_can_legitimately_have_no_optimum_above_altitude_limit(self):
        observation = {**self.observation, 'tanggal': '2026-09-11'}
        with (patch.object(batch, 'SUMBER_ATMOSFER', 'manual'),
              patch.object(batch, 'CALC_MODE', 'optimal'),
              contextlib.redirect_stdout(io.StringIO())):
            result = batch.run_single_observation(observation, verbose=False)
        self.assertTrue(result['success'], result.get('error'))
        self.assertTrue(result['tanggal_cocok'])
        self.assertEqual(result['tanggal_model'], '2026-09-11')
        self.assertLess(result['moon_alt_sunset'], batch.MIN_MOON_ALT)
        self.assertIsNone(result['optimal_time_tel'])
        self.assertIsNone(batch._comparison_prediction(result))

    def test_date_selection_reaches_weather_and_handles_year_boundary(self):
        zone = timezone(timedelta(hours=8))
        for conjunction, target, expected_offset in (
            (datetime(2026, 9, 11, 2, tzinfo=timezone.utc), date(2026, 9, 10), -1),
            (datetime(2026, 9, 11, 2, tzinfo=timezone.utc), date(2026, 9, 11), 0),
            (datetime(2026, 9, 11, 2, tzinfo=timezone.utc), date(2026, 9, 12), 1),
            (datetime(2026, 12, 31, 2, tzinfo=timezone.utc), date(2027, 1, 1), 1),
        ):
            with self.subTest(target=target):
                calc = HilalVisibilityCalculator(
                    'Date fixture', 0.8, 122.7, 5, 'Asia/Makassar', 4, 1448,
                    sumber_atmosfer='manual', observation_date=target,
                )
                def sunset(location, tz, *, year, month, day, **kwargs):
                    return None, datetime(year, month, day, 18, tzinfo=zone)
                with (patch('hilal_visibility.calculator.sunrise_sunset_local', side_effect=sunset),
                      patch.object(calc, '_fetch_atmosfer', return_value=(75, 25, 75, 25, 1013.25)) as weather):
                    _, local, *_ = calc.tentukan_tanggal_pengamatan(conjunction)
                self.assertEqual(local.date(), target)
                self.assertEqual(weather.call_args.args[1].astimezone(zone).date(), target)
                self.assertEqual(calc.hasil['delta_day_offset'], expected_offset)

    def test_existing_hisab_plus_user_offset_remains_available(self):
        for offset in (0, 1):
            with self.subTest(offset=offset), contextlib.redirect_stdout(io.StringIO()):
                calc = HilalVisibilityCalculator(
                    'Legacy date fixture', 0.8, 122.7, 5, 'Asia/Makassar', 4, 1448,
                    sumber_atmosfer='manual', delta_day_offset=offset,
                )
                conjunction, _ = calc.hitung_ijtima()
                _, local, *_ = calc.tentukan_tanggal_pengamatan(conjunction)
                self.assertEqual(local.date(), date(2026, 9, 11) + timedelta(days=offset))

    def test_mismatched_results_are_failed_and_cannot_be_compared(self):
        wrong = dict(tanggal_pengamatan=datetime(2026, 9, 11),
                     sunset_local=datetime(2026, 9, 11, 18, tzinfo=timezone.utc))
        with (patch.object(batch, 'HilalVisibilityCalculator') as factory,
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            factory.return_value.hasil = wrong
            factory.return_value.jalankan_perhitungan_lengkap.return_value = wrong
            result = batch.run_single_observation(self.observation, verbose=False)
        self.assertFalse(result['success'])
        self.assertIn('TANGGAL TIDAK COCOK', result['error'])
        self.assertIsNone(batch._comparison_prediction(result))
        self.assertEqual(factory.call_args.kwargs['observation_date'], date(2026, 9, 12))

    def test_csv_excel_and_sidecar_record_the_dates_and_offset(self):
        result = self.results['optimal']
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            csv_path = Path(directory) / 'batch.csv'
            excel_path = Path(directory) / 'batch.xlsx'
            batch.save_to_csv([result], str(csv_path))
            batch.save_to_excel([result], str(excel_path))
            with csv_path.open(encoding='utf-8-sig', newline='') as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row['Tanggal_Model'], '2026-09-12')
            self.assertEqual(row['Tanggal_Hisab_H0'], '2026-09-11')
            self.assertEqual(row['Offset_Hari_dari_Hisab'], '1')
            self.assertEqual(row['Tanggal_Cocok'], 'True')
            wb = load_workbook(excel_path, read_only=True, data_only=True)
            try:
                dates = list(wb['Tanggal Pengamatan'].values)
                self.assertEqual(dates[1][2:7], ('2026-09-12', '2026-09-12', '2026-09-11', 1, True))
                self.assertEqual(dates[1][7:], ('2026-09-12', 'ephemeris_hijri_plus_offset_dataset', 'Asia/Jakarta'))
            finally:
                wb.close()
            audit = json.loads(Path(str(csv_path) + '.atmosphere.json').read_text(encoding='utf-8'))
            self.assertEqual(audit['observations'][0]['model_date'], '2026-09-12')
            self.assertEqual(audit['observations'][0]['offset_days'], 1)
            self.assertTrue(audit['observations'][0]['dates_match'])
            self.assertEqual(row['Zona_Acuan_H0'], 'Asia/Jakarta')
            self.assertEqual(audit['observations'][0]['h0_reference_timezone'], 'Asia/Jakarta')

    def test_october_batch_h1_is_october_11_for_both_wib_and_wit(self):
        for index in (272, 274):
            observation = {**batch.parse_obs(batch.OBSERVATIONS[index]),
                           'bulan_hijri': 5, 'tahun_hijri': 1448, 'tanggal': '2026-10-11'}
            with (self.subTest(location=observation['nama']),
                  patch.object(batch, 'SUMBER_ATMOSFER', 'manual'),
                  patch.object(batch, 'CALC_MODE', 'sunset'),
                  contextlib.redirect_stdout(io.StringIO())):
                result = batch.run_single_observation(observation, verbose=False)
            self.assertTrue(result['success'], result.get('error'))
            self.assertEqual(result['tanggal_hisab'], '2026-10-10')
            self.assertEqual(result['delta_day_offset'], 1)
            self.assertEqual(result['tanggal_model'], '2026-10-11')
            self.assertEqual(result['sunset_local'].date(), date(2026, 10, 11))
            self.assertEqual(result['h0_reference_timezone'], 'Asia/Jakarta')

    def test_single_h1_offset_uses_wib_reference_in_both_observer_timezones(self):
        for zone, lon in (('Asia/Jakarta', 110), ('Asia/Jayapura', 140)):
            calc = HilalVisibilityCalculator(
                'October H+1 fixture', -3, lon, 10, zone, 5, 1448,
                sumber_atmosfer='manual', delta_day_offset=1,
            )
            with self.subTest(zone=zone), contextlib.redirect_stdout(io.StringIO()):
                conjunction, _ = calc.hitung_ijtima()
                _, local, *_ = calc.tentukan_tanggal_pengamatan(conjunction)
            self.assertEqual(calc.hasil['tanggal_hisab'].date(), date(2026, 10, 10))
            self.assertEqual(local.date(), date(2026, 10, 11))
            self.assertEqual(calc.hasil['delta_day_offset'], 1)

    def test_wrong_gregorian_month_keeps_hijri_ephemeris_as_reference(self):
        observation = batch.parse_obs(batch.OBSERVATIONS[26])
        with (patch.object(batch, 'SUMBER_ATMOSFER', 'manual'),
              patch.object(batch, 'CALC_MODE', 'sunset'),
              contextlib.redirect_stdout(io.StringIO())):
            result = batch.run_single_observation(observation, verbose=False)
        self.assertTrue(result['success'], result.get('error'))
        self.assertEqual(result['tanggal_model'], '2022-07-29')
        self.assertEqual(result['tanggal_obs'], '2022-07-29')
        self.assertEqual(result['tanggal_dataset'], '2022-06-29')
        self.assertEqual(result['sumber_tanggal'], 'ephemeris_hijri')
        self.assertEqual(result['delta_day_offset'], 0)
        self.assertTrue(result['tanggal_cocok'])
        self.assertEqual(batch.OBSERVATIONS[26][1], '2022-06-29')

    def test_absolute_date_rejects_time_or_ambiguous_offset(self):
        arguments = ('Invalid date fixture', 0.8, 122.7, 5, 'Asia/Makassar', 4, 1448)
        for invalid in ('2026-09-12', datetime(2026, 9, 12)):
            with self.subTest(value=invalid), self.assertRaises(TypeError):
                HilalVisibilityCalculator(*arguments, observation_date=invalid)
        with self.assertRaises(ValueError):
            HilalVisibilityCalculator(*arguments, observation_date=date(2026, 9, 12), delta_day_offset=1)
