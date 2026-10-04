"""Geometri luas sabit bersama untuk model Kastner dan Crumey."""

import math


def crescent_area(elongation_deg: float, r_deg: float) -> float:
    """Luas sabit [derajat²]: ½ π r² (1 − cos elongasi).

    Elongasi adalah separasi Matahari–Bulan, bukan sudut fase di Bulan.
    Formulasi ini mempertahankan baseline yang ditetapkan di change.md.
    """
    if elongation_deg <= 0 or r_deg <= 0:
        return 0.0
    e = math.radians(elongation_deg)
    return 0.5 * math.pi * r_deg**2 * (1.0 - math.cos(e))
