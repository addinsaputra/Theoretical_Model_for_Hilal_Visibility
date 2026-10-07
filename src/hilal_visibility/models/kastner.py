"""Luminansi intrinsik hilal dan penerapan transmisi dari model atmosfer.

Phase law lama dipertahankan. Schaefer menghitung seluruh ekstingsi atmosfer;
modul ini hanya mengubah S10 ke nL dan menerapkan transmission_v sekali.
"""

import math

from hilal_visibility.models.geometry import crescent_area
from hilal_visibility.models.crumey import cdm2_to_nL, mag_to_lux

# One S10 is the flux of a V=10 star distributed over one square degree.
# Derive its luminance from the same V zero point as the threshold photometry,
# instead of mixing rounded 0.263 nL and 2.51 with an exact magnitude scale.
S10_TO_NL = cdm2_to_nL(mag_to_lux(10.0) / math.radians(1.0)**2)


def hitung_fotometri_intrinsik(
    phase_angle_deg: float,
    elongation_deg: float,
    r_deg: float,
) -> dict:
    """Photometry actually used by Kastner, including intermediate quantities.

    Sudut fase dipakai untuk magnitudo; elongasi untuk luas sabit [derajat²].
    """
    if not math.isfinite(phase_angle_deg) or not 0.0 <= phase_angle_deg <= 180.0:
        raise ValueError("Sudut fase harus finite dan berada dalam 0..180 derajat.")
    alpha = phase_angle_deg
    mv = 0.026 * alpha + 4e-9 * alpha**4 - 12.73
    D = crescent_area(elongation_deg, r_deg)
    L_star = (10.0 ** (0.4 * (10.0 - mv))) / D if D > 0 else 0.0
    return {'M_v': mv, 'area_deg2': D, 'L_star_s10': L_star,
            'S10_to_nL': S10_TO_NL, 'intrinsic_luminance_nL': S10_TO_NL * L_star}


def hitung_luminansi_intrinsik(
    phase_angle_deg: float, elongation_deg: float, r_deg: float,
) -> float:
    """Mean extra-atmospheric crescent luminance L_star_s10 [S10]."""
    return hitung_fotometri_intrinsik(phase_angle_deg, elongation_deg, r_deg)['L_star_s10']


def terapkan_transmisi_atmosfer(
    L_star_s10: float,
    transmission_v: float,
) -> float:
    """Direct/excess luminance [nL] with the shared exact V zero point."""
    if not math.isfinite(L_star_s10) or L_star_s10 < 0:
        raise ValueError("Luminansi intrinsik harus finite dan non-negatif.")
    if not math.isfinite(transmission_v) or not 0.0 <= transmission_v <= 1.0:
        raise ValueError("Transmisi atmosfer harus antara 0 dan 1.")
    return S10_TO_NL * L_star_s10 * transmission_v


def hitung_luminansi_kastner(
    *,
    phase_angle_deg: float,
    elongation_deg: float,
    r_deg: float,
    transmission_v: float,
) -> float:
    """Wrapper luminansi hilal [nL] dengan transmisi eksplisit dari Schaefer.

    Kontrak lama dengan z/k telah diganti; tidak ada airmass di modul ini.
    """
    L_star_s10 = hitung_luminansi_intrinsik(phase_angle_deg, elongation_deg, r_deg)
    return terapkan_transmisi_atmosfer(L_star_s10, transmission_v)


if __name__ == "__main__":
    # Transmisi contoh untuk A_V = 1 mag; produksi memakai output Schaefer.
    phase_angle_deg = 171.59194444444
    elongation_deg = 8.4
    r_deg = 0.2625
    L_star_s10 = hitung_luminansi_intrinsik(phase_angle_deg, elongation_deg, r_deg)
    L_obj_nL = terapkan_transmisi_atmosfer(L_star_s10, 10.0 ** (-0.4))
    print(f"Luminansi intrinsik (L_star_s10): {L_star_s10:.4f} S10")
    print(f"Luminansi excess hilal (L_obj_nL): {L_obj_nL:.4f} nL")
    print(f"Luas sabit: {crescent_area(elongation_deg, r_deg) * 3600:.4f} arcmin²")
