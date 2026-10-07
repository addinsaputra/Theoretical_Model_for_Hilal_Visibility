"""Geometri luas sabit bersama untuk model Kastner dan Crumey."""

import math


def crescent_area(elongation_deg: float, r_deg: float) -> float:
    """Luas sabit [derajat²]: ½ π r² (1 − cos elongasi).

    Elongasi adalah separasi Matahari–Bulan, bukan sudut fase di Bulan.
    Formulasi ini mempertahankan baseline yang ditetapkan di change.md.
    """
    if not math.isfinite(elongation_deg) or not 0.0 <= elongation_deg <= 180.0:
        raise ValueError("Elongasi harus finite dan berada dalam 0..180 derajat.")
    if not math.isfinite(r_deg) or r_deg < 0.0:
        raise ValueError("Semidiameter harus finite dan non-negatif.")
    if elongation_deg == 0 or r_deg == 0:
        return 0.0
    e = math.radians(elongation_deg)
    # Equivalent to (1-cos(e))/2, without cancellation near conjunction.
    return math.pi * r_deg**2 * math.sin(e / 2.0)**2
