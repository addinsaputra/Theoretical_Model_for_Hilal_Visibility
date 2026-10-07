"""Boundary regressions for Schaefer, including saturated weather provenance."""

import contextlib
import csv
import io
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


import hilal_visibility.batch as batch
from hilal_visibility.atmosphere.ifs import apply_bias_correction, validate_atmosphere
from hilal_visibility.calculator import HilalVisibilityCalculator
from hilal_visibility.models.schaefer import hitung_sky_brightness


class SchaeferDomainTests(unittest.TestCase):
    parameters = dict(month=3, year=2023, altsun=-1, azisun=8,
                      temperature=25, latitude=-7, elevation=89, alt_objek=6)

    def test_invalid_or_saturated_rh_is_a_model_domain_error(self):
        for rh in (100, 101, -0.01, math.nan, math.inf, -math.inf, None):
            with self.subTest(rh=rh), self.assertRaisesRegex(ValueError, 'Schaefer model domain'):
                hitung_sky_brightness(humidity=rh, **self.parameters)

    def test_dry_and_near_saturated_rh_remain_finite_without_clipping(self):
        for rh in (0, 1, 75, 99, 99.9, math.nextafter(100.0, 0.0)):
            with self.subTest(rh=rh):
                result = hitung_sky_brightness(humidity=rh, **self.parameters)
                self.assertTrue(all(math.isfinite(x) for x in result['K'] + result['DM']))
                self.assertTrue(math.isfinite(result['sky_brightness']))
                self.assertTrue(0 <= result['transmission_v'] <= 1)
        low = hitung_sky_brightness(humidity=99, **self.parameters)
        high = hitung_sky_brightness(humidity=99.9, **self.parameters)
        self.assertGreater(high['k_v'], low['k_v'])

    def test_bias_corrected_saturation_is_weather_valid_but_outside_schaefer(self):
        corrected_rh, corrected_t, pressure = apply_bias_correction(95, 25, 1013.25, bias_rh=-5, bias_t=0)
        self.assertEqual(corrected_rh, 100)
        validate_atmosphere(corrected_rh, corrected_t, pressure)
        with self.assertRaisesRegex(ValueError, '0 <= RH < 100%'):
            hitung_sky_brightness(humidity=corrected_rh, **self.parameters)

    def test_coincident_directions_tolerate_roundoff_above_one(self):
        # sin² + cos² is 1.0000000000000002 for this finite direction.
        angle = 0.08
        rad = angle * (math.pi / 180.0)
        self.assertGreater(math.sin(rad)**2 + math.cos(rad)**2, 1.0)
        result = hitung_sky_brightness(
            **{**self.parameters, 'altsun': angle, 'alt_objek': angle, 'azisun': 0}, humidity=75)
        self.assertEqual(result['diagnostics']['separation_sky_deg'], 0)
        self.assertTrue(math.isfinite(result['sky_brightness']))

    def test_saturated_batch_is_invalid_and_retains_raw_weather_in_sidecar(self):
        calc = HilalVisibilityCalculator(
            'Saturated fixture', -6.917, 110.348, 89, 'Asia/Jakarta', 9, 1444,
            sumber_atmosfer='manual', manual_rh=100, manual_t=25,
        )
        observation = dict(no=1, nama='Saturated fixture', tanggal='2023-03-22',
                           lat=-6.917, lon=110.348, elv=89, bulan_hijri=9,
                           tahun_hijri=1444, observed=False, bias_rh=0, bias_t=0)
        with (patch.object(batch, 'SUMBER_ATMOSFER', 'manual'),
              patch.object(batch, 'HilalVisibilityCalculator', return_value=calc),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO())):
            failed = batch.run_single_observation(observation, verbose=False)
            self.assertFalse(failed['success'])
            self.assertIn('Outside Schaefer model domain', failed['error'])
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'saturated.csv'
                batch.save_to_csv([failed], str(path))
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    row = next(csv.DictReader(stream))
                audit = json.loads(Path(str(path) + '.atmosphere.json').read_text(encoding='utf-8'))
        self.assertEqual(row['Status'], 'invalid')
        self.assertEqual(row['Prediksi'], '')
        self.assertEqual(row['Regime_NE_Sunset'], '')
        raw = audit['observations'][0]['windows'][0]['hourly_raw']
        self.assertEqual(raw[0]['relative_humidity_2m'], 100)
        self.assertIn('Schaefer model domain', audit['observations'][0]['error'])


if __name__ == '__main__':
    unittest.main()
