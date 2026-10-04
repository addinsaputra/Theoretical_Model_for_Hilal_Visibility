"""Luminansi intrinsik hilal dan penerapan transmisi dari model atmosfer.

Phase law lama dipertahankan. Schaefer menghitung seluruh ekstingsi atmosfer;
modul ini hanya mengubah S10 ke nL dan menerapkan transmission_v sekali.
"""

from crescent_geometry import crescent_area

S10_TO_NL = 0.263


def hitung_luminansi_intrinsik(
    phase_angle_deg: float,
    elongation_deg: float,
    r_deg: float,
) -> float:
    """Mean extra-atmospheric crescent luminance L_star_s10 [S10].

    Sudut fase dipakai untuk magnitudo; elongasi untuk luas sabit [derajat²].
    """
    alpha = phase_angle_deg
    mv = 0.026 * alpha + 4e-9 * alpha**4 - 12.73
    D = crescent_area(elongation_deg, r_deg)
    if D <= 0:
        return 0.0
    return (2.51 ** (10.0 - mv)) / D


def terapkan_transmisi_atmosfer(
    L_star_s10: float,
    transmission_v: float,
) -> float:
    """Direct/excess luminance hilal [nL]: 0.263 * L_star_s10 * T_V."""
    if not 0.0 <= transmission_v <= 1.0:
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
