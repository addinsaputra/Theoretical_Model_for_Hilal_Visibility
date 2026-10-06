"""Physical input domains and stable crescent geometry near conjunction."""

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Core'))

from crescent_geometry import crescent_area
from visual_limit_kastner import hitung_luminansi_intrinsik, terapkan_transmisi_atmosfer


class CrescentInputDomainTests(unittest.TestCase):
    def test_invalid_geometry_is_not_a_zero_source(self):
        for elongation in (-1, 181, math.nan, math.inf):
            with self.subTest(elongation=elongation), self.assertRaises(ValueError):
                crescent_area(elongation, .26)
        for radius in (-1, math.nan, math.inf):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                crescent_area(8, radius)

    def test_near_conjunction_area_approaches_quadratic_limit(self):
        elongation, radius = 1e-8, .26
        expected = math.pi * radius**2 * math.radians(elongation)**2 / 4
        self.assertGreater(crescent_area(elongation, radius), 0)
        self.assertAlmostEqual(crescent_area(elongation, radius) / expected, 1)
        self.assertEqual(crescent_area(0, radius), 0)

    def test_phase_and_transmission_domains(self):
        for phase in (-1, 181, math.nan, math.inf):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                hitung_luminansi_intrinsik(phase, 8, .26)
        for luminance in (-1, math.nan, math.inf):
            with self.subTest(luminance=luminance), self.assertRaises(ValueError):
                terapkan_transmisi_atmosfer(luminance, .8)
        for transmission in (-1, 1.1, math.nan, math.inf):
            with self.subTest(transmission=transmission), self.assertRaises(ValueError):
                terapkan_transmisi_atmosfer(100, transmission)
        self.assertEqual(terapkan_transmisi_atmosfer(0, .8), 0)
        self.assertEqual(terapkan_transmisi_atmosfer(100, 0), 0)


if __name__ == '__main__':
    unittest.main()
