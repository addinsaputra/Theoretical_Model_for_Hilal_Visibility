"""Regresi ukuran sudut dan fase Bulan dari DE440s, lokasi, dan waktu lengkap."""

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from pytz import timezone as local_timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Core'))

import data_hisab as hisab
from core_crescent_visibility import HilalVisibilityCalculator
from analisis_diagnostik_crumey import _observation_semidiameter_deg, compute_delta_m


class LunarGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.utc = datetime(2023, 3, 22, 10, 42, 15, tzinfo=timezone.utc)
        cls.location = hisab.set_location(-6.917, 110.348, 89)

    def test_spherical_semidiameter_and_invalid_distance(self):
        # Pada jarak 2R, cakram bola mempunyai semidiameter 30 derajat.
        self.assertAlmostEqual(hisab.moon_semidiameter_from_distance(2 * hisab.MOON_RADIUS_KM), 30)
        for distance in (0, -1, hisab.MOON_RADIUS_KM, float('nan'), float('inf')):
            with self.subTest(distance=distance):
                with self.assertRaises(ValueError):
                    hisab.moon_semidiameter_from_distance(distance)

    def test_location_uses_wgs84_and_keeps_coordinate_precision(self):
        lat, lon, elevation = -6.917123456, 110.348987654, 89.125
        location = hisab.set_location(lat, lon, elevation)
        self.assertIs(location.model, hisab.api.wgs84)
        self.assertAlmostEqual(location.latitude.degrees, lat, places=10)
        self.assertAlmostEqual(location.longitude.degrees, lon, places=10)
        self.assertAlmostEqual(location.elevation.m, elevation, places=10)

    def test_reference_topocentric_semidiameter(self):
        # DE440s, Semarang, 2023-03-22 10:42:15 UTC, R rata-rata JPL 1737.4 km.
        # Jarak astrometrik WGS84 367506.496173 km memberi r = 975.127822 arcsec.
        sd = hisab.moon_semidiameter_time_utc(self.location, self.utc)
        self.assertAlmostEqual(sd * 3600, 975.127822067572, places=5)
        # Referensi eksternal JPL Horizons (DE441), diperiksa 2026-10-04:
        # COMMAND=301, CENTER=coord@399, SITE_COORD=110.348,-6.917,0.089,
        # START_TIME=2023-03-22 10:42:15 UT, QUANTITIES=13,20.
        # Diameter penuh = 1950.256 arcsec, radius fisik = 1737.4 km.
        # Toleransi mencakup pembulatan keluaran dan perbedaan orientasi Bumi.
        self.assertAlmostEqual(sd * 3600, 1950.256 / 2, delta=0.001)
        self.assertGreater(sd, 0.23)
        self.assertLess(sd, 0.30)

    def test_topocentric_and_geocentric_sizes_are_distinct(self):
        topo = hisab.moon_semidiameter_time_utc(self.location, self.utc)
        geo = hisab.moon_semidiameter_time_utc(None, self.utc)
        self.assertGreater(topo, geo)
        opposite = hisab.set_location(6.917, -69.652, 89)
        farther = hisab.moon_semidiameter_time_utc(opposite, self.utc)
        self.assertGreater(topo, farther)

    def test_hour_and_second_are_used(self):
        first = hisab.moon_semidiameter_time_utc(self.location, self.utc)
        later = hisab.moon_semidiameter_time_utc(self.location, self.utc + timedelta(hours=6))
        one_second = hisab.moon_semidiameter_time_utc(self.location, self.utc + timedelta(seconds=1))
        self.assertGreater(abs(first - later), 1e-5)
        self.assertNotEqual(first, one_second)

    def test_datetime_and_date_components_match(self):
        from_datetime = hisab.moon_illumination_width_utc(self.location, self.utc)
        from_components = hisab.moon_illumination_width_utc(
            self.location, year=2023, month=3, day=22, hour=10, minute=42, second=15)
        for expected, actual in zip(from_datetime, from_components):
            self.assertAlmostEqual(expected, actual, places=10)

    def test_local_and_utc_wrappers_match(self):
        local = self.utc.astimezone(local_timezone('Asia/Jakarta'))
        utc_values = hisab.moon_illumination_width_utc(self.location, self.utc)
        local_values = hisab.moon_illumination_width_local('Asia/Jakarta', self.location, local)
        local_from_components = hisab.moon_semidiameter_time_local(
            'Asia/Jakarta', self.location, year=2023, month=3, day=22,
            hour=17, minute=42, second=15)
        for expected, actual in zip(utc_values, local_values):
            self.assertAlmostEqual(expected, actual, places=10)
        self.assertAlmostEqual(utc_values[3], local_from_components, places=10)

    def test_horizontal_parallax_is_geocentric_and_width_uses_topocentric_sd(self):
        illumination_pct, width, parallax, sd = hisab.moon_illumination_width_utc(self.location, self.utc)
        _, _, geo_parallax, _ = hisab.moon_illumination_width_utc(None, self.utc)
        self.assertEqual(parallax, geo_parallax)
        self.assertAlmostEqual(width / (2 * sd), illumination_pct / 100, places=12)
        self.assertAlmostEqual(sd, hisab.moon_semidiameter_time_utc(self.location, self.utc))

    def test_photometry_uses_astrometric_geometry(self):
        observer = (hisab.ephem['Earth'] + self.location).at(hisab.ts.from_datetime(self.utc))
        astrometric = observer.observe(hisab.ephem['Moon'])
        phase = hisab.moon_phase_angle_time_utc(self.location, self.utc)
        illumination_pct, width, _, sd = hisab.moon_illumination_width_utc(self.location, self.utc)
        self.assertAlmostEqual(phase, astrometric.phase_angle(hisab.ephem['Sun']).degrees, places=12)
        self.assertGreater(abs(phase - astrometric.apparent().phase_angle(hisab.ephem['Sun']).degrees),
                           0.005)
        self.assertAlmostEqual(illumination_pct / 100,
                               astrometric.fraction_illuminated(hisab.ephem['Sun']), places=12)
        self.assertAlmostEqual(sd, hisab.moon_semidiameter_from_distance(astrometric.distance().km),
                               places=12)
        self.assertAlmostEqual(width, sd * (1 + math.cos(math.radians(phase))), places=12)

    def test_horizons_airless_reference_angles(self):
        # Snapshot JPL Horizons, DE441, 2026-10-04, site dan waktu pada setUpClass.
        # QUANTITIES=4,10,13,20,23,24,43, APPARENT=AIRLESS, EXTRA_PREC=YES.
        alt, az, _ = hisab.moon_position_time_utc(self.location, self.utc, temperature_C=None)
        self.assertAlmostEqual(alt, 9.162573588, delta=0.1 / 3600)
        self.assertAlmostEqual(az, 273.877229622, delta=0.1 / 3600)
        self.assertAlmostEqual(hisab.moon_elongation_time_utc(self.location, self.utc),
                               8.9899, delta=0.00005)
        # Native Skyfield belum mengimplementasikan seluruh geometri true PHASE Q43.
        # Toleransi ini mencakup residu yang terukur (~19.5 arcsec), bukan ekuivalensi.
        phase = hisab.moon_phase_angle_time_utc(self.location, self.utc)
        self.assertAlmostEqual(phase, 170.9826, delta=22 / 3600)

    def test_pymeeus_is_no_longer_required(self):
        with patch.dict(sys.modules, {'pymeeus': None, 'pymeeus.Epoch': None, 'pymeeus.Moon': None}):
            result = hisab.moon_illumination_width_utc(self.location, self.utc)
            self.assertEqual(len(result), 4)
            self.assertTrue(all(isinstance(value, float) for value in result))

    def test_phase_angle_matches_native_illumination(self):
        # Identitas cakram bola menghubungkan dua API publik yang digunakan pipeline.
        for location in (None, self.location):
            for utc in (self.utc, self.utc + timedelta(days=15)):
                with self.subTest(location=location, utc=utc):
                    phase = hisab.moon_phase_angle_time_utc(location, utc)
                    illumination = hisab.moon_illumination_width_utc(location, utc)[0] / 100
                    self.assertAlmostEqual(illumination, (1 + math.cos(math.radians(phase))) / 2,
                                           places=12)
                    if utc == self.utc:
                        self.assertGreater(phase, 160)  # Hilal muda: hampir fase gelap.
                    else:
                        self.assertLess(phase, 20)  # Mendekati fase penuh.
        geo = hisab.moon_phase_angle_time_utc(None, self.utc)
        topo = hisab.moon_phase_angle_time_utc(self.location, self.utc)
        self.assertGreater(abs(geo - topo), 0.01)

    def test_phase_angle_utc_local_and_components_match(self):
        local = self.utc.astimezone(local_timezone('Asia/Jakarta'))
        expected = hisab.moon_phase_angle_time_utc(self.location, self.utc)
        values = (
            hisab.moon_phase_angle_time_local('Asia/Jakarta', self.location, local),
            hisab.moon_phase_angle_time_utc(self.location, year=2023, month=3, day=22,
                                          hour=10, minute=42, second=15),
            hisab.moon_phase_angle_time_local('Asia/Jakarta', self.location,
                                            year=2023, month=3, day=22,
                                            hour=17, minute=42, second=15),
        )
        for value in values:
            self.assertAlmostEqual(value, expected, places=12)
        for utc_mode, local_mode in ((True, False), (False, True)):
            actual = (hisab.moon_phase_angle_time_utc(self.location, year=2023, month=3, day=22)
                      if utc_mode else
                      hisab.moon_phase_angle_time_local('Asia/Jakarta', self.location,
                                                       year=2023, month=3, day=22))
            midnight = datetime(2023, 3, 22, tzinfo=timezone.utc)
            if local_mode:
                midnight = local_timezone('Asia/Jakarta').localize(datetime(2023, 3, 22))
            self.assertAlmostEqual(actual, hisab.moon_phase_angle_time_utc(self.location, midnight),
                                   places=12)

    def test_phase_angle_preserves_vector_utc_inputs(self):
        phases = hisab.moon_phase_angle_time_utc(self.location, year=2023, month=3,
                                               day=[22, 23], hour=10, minute=42, second=15)
        self.assertEqual(phases.shape, (2,))
        for i in range(2):
            scalar = hisab.moon_phase_angle_time_utc(self.location, self.utc + timedelta(days=i))
            self.assertAlmostEqual(phases[i], scalar, places=10)

    def test_calculator_uses_distance_from_its_moon_position(self):
        calc = HilalVisibilityCalculator('Uji', -6.917, 110.348, 89, 'Asia/Jakarta', 9, 1444,
                                         sumber_atmosfer='manual')
        result = calc.hitung_posisi_matahari_bulan(self.utc.astimezone(local_timezone('Asia/Jakarta')))
        expected = hisab.moon_semidiameter_time_utc(self.location, self.utc)
        self.assertAlmostEqual(result['moon_semidiameter'], expected, places=10)
        self.assertAlmostEqual(result['phase_angle'],
                               hisab.moon_phase_angle_time_utc(self.location, self.utc), places=12)
        self.assertAlmostEqual(result['moon_width'],
                               hisab.moon_illumination_width_utc(self.location, self.utc)[1], places=12)
        self.assertAlmostEqual(math.sin(math.radians(result['moon_semidiameter'])) * result['moon_distance_km'],
                               hisab.MOON_RADIUS_KM)


class TimeAndCalendarTests(unittest.TestCase):
    def test_local_time_preserves_fractional_seconds(self):
        expected = datetime(2023, 3, 22, 10, 42, 15, 123456, tzinfo=timezone.utc)
        values = (
            hisab.convert_localtime_to_utc('Asia/Jakarta', year=2023, month=3, day=22,
                                          hour=17, minute=42, second=15.123456),
            hisab.convert_localtime_to_utc('Asia/Jakarta',
                                          local_datetime=datetime(2023, 3, 22, 17, 42, 15, 123456)),
            hisab.convert_localtime_to_utc('Asia/Jakarta', local_datetime=expected),
        )
        for value in values:
            self.assertEqual(value, expected)
        midnight = hisab.convert_localtime_to_utc('Asia/Jakarta', year=2023, month=3, day=22)
        self.assertEqual(midnight, datetime(2023, 3, 21, 17, tzinfo=timezone.utc))

    def test_timedelta_preserves_signed_subseconds(self):
        start = datetime(2023, 3, 22, 23, 59, 59, 750000, tzinfo=timezone.utc)
        for seconds in (0.25, 1.125, -0.25, -86400.125):
            with self.subTest(seconds=seconds):
                end = start + timedelta(seconds=seconds)
                self.assertEqual(hisab.calc_timedelta_seconds(start, end), seconds)

    def test_hijri_backward_year_boundaries(self):
        ref = datetime(2022, 7, 28, 17, 54, tzinfo=timezone.utc)
        events = [ref + timedelta(days=29.5 * offset) for offset in range(-36, 1)]
        with patch.object(hisab, 'ref_hijri_ijtima', return_value=(1, 1444, ref)), \
                patch.object(hisab, 'find_new_moon_dates', return_value=events):
            for year, month in ((1443, 1), (1442, 1), (1443, 12), (1442, 12)):
                with self.subTest(year=year, month=month):
                    offset = (year - 1444) * 12 + month - 1
                    self.assertEqual(hisab.newmoon_hijri_month_utc(year, month), events[offset + 36])

    def test_hijri_forward_year_boundaries(self):
        ref = datetime(2022, 7, 28, 17, 54, tzinfo=timezone.utc)
        events = [ref + timedelta(days=29.5 * offset) for offset in range(37)]
        with patch.object(hisab, 'ref_hijri_ijtima', return_value=(1, 1444, ref)), \
                patch.object(hisab, 'find_new_moon_dates', return_value=events):
            for year, month in ((1444, 1), (1444, 12), (1445, 1), (1446, 1)):
                with self.subTest(year=year, month=month):
                    offset = (year - 1444) * 12 + month - 1
                    self.assertEqual(hisab.newmoon_hijri_month_utc(year, month), events[offset])

    def test_real_previous_muharram_conjunctions(self):
        for year, date in ((1443, (2021, 8, 8)), (1442, (2020, 8, 19))):
            with self.subTest(year=year):
                utc = hisab.newmoon_hijri_month_utc(year, 1)
                self.assertEqual((utc.year, utc.month, utc.day), date)
                lunar_phase = hisab.almanac.moon_phase(hisab.ephem, hisab.ts.from_datetime(utc)).degrees
                self.assertLess(min(lunar_phase, 360 - lunar_phase), 0.001)


class DiagnosticSemidiameterTests(unittest.TestCase):
    def test_csv_semidiameter_is_preserved(self):
        self.assertEqual(_observation_semidiameter_deg({'Moon Semidiameter (deg)': 0.27123}), 0.27123)

    def test_old_csv_recomputes_from_best_time_and_location(self):
        row = {'Tanggal': '2023-03-22', 'Best Time Tel': '17:42:15',
               'Lat': -6.917, 'Lon': 110.348, 'Elv': 89}
        actual = _observation_semidiameter_deg(row)
        self.assertAlmostEqual(actual, 0.27086883946321444, places=10)

    def test_missing_observation_geometry_does_not_use_constant_sd(self):
        with self.assertRaises(ValueError):
            _observation_semidiameter_deg({'Tanggal': '2023-03-22'})

    def test_threshold_responds_to_observed_angular_size(self):
        small = compute_delta_m(100, 1000, 8, moon_sd_deg=0.24)
        large = compute_delta_m(100, 1000, 8, moon_sd_deg=0.29)
        self.assertEqual(small['C_obj'], large['C_obj'])
        self.assertGreater(small['C_th'], large['C_th'])


if __name__ == '__main__':
    unittest.main()
