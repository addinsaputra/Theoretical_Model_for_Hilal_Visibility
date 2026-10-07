"""The dataset's H+0 date is the shared WIB calendar day of conjunction."""
from datetime import date, datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from hilal_visibility.calculator import hisab_observation_date


class HisabReferenceDateTests(unittest.TestCase):
    def test_noon_and_sunset_do_not_move_the_reference_day(self):
        wib = timezone(timedelta(hours=7))
        with patch('hilal_visibility.calculator.sunrise_sunset_local',
                   side_effect=AssertionError('H+0 must not depend on sunset')):
            for hour in (0, 11, 12, 17, 18, 23):
                with self.subTest(hour=hour):
                    conjunction = datetime(2026, 9, 11, hour, 30, tzinfo=wib)
                    self.assertEqual(hisab_observation_date(conjunction), date(2026, 9, 11))

    def test_wib_midnight_is_the_day_boundary(self):
        self.assertEqual(hisab_observation_date(datetime(2026, 10, 10, 16, 59, 59, tzinfo=timezone.utc)),
                         date(2026, 10, 10))
        self.assertEqual(hisab_observation_date(datetime(2026, 10, 10, 17, tzinfo=timezone.utc)),
                         date(2026, 10, 11))

    def test_october_event_has_one_reference_despite_wit_already_being_next_day(self):
        conjunction = datetime(2026, 10, 10, 15, 49, 55, tzinfo=timezone.utc)
        wit = conjunction.astimezone(timezone(timedelta(hours=9)))
        self.assertEqual(wit.date(), date(2026, 10, 11))
        self.assertEqual(hisab_observation_date(conjunction), date(2026, 10, 10))
        self.assertEqual(hisab_observation_date(wit), date(2026, 10, 10))

    def test_wib_date_is_used_when_utc_is_still_the_previous_day(self):
        conjunction = datetime(2026, 9, 10, 18, tzinfo=timezone.utc)
        self.assertEqual(hisab_observation_date(conjunction), date(2026, 9, 11))

    def test_naive_conjunction_is_rejected_instead_of_using_host_timezone(self):
        with self.assertRaises(ValueError):
            hisab_observation_date(datetime(2026, 10, 10, 15, 49, 55))
