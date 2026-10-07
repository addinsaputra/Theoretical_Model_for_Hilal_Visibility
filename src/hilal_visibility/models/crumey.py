"""
=============================================================================
Implementasi Lengkap Model Crumey (2014)
"Human contrast threshold and astronomical visibility"
MNRAS 442, 2600-2619 (2014), doi:10.1093/mnras/stu992

Modul ini menyediakan:
  1. Konversi satuan (nL, fL, cd/m², mag, mag/arcsec², lux, steradian)
  2. Model inti threshold (scotopic, photopic, combined) — Eq. 23-52
  3. Koreksi S/P ratio & color index — Eq. 5-18
  4. Field factor (F) support — Sec. 1.2, 1.6
  5. Penanganan zero-background (B ≤ 10⁻⁵ cd/m²) — Eq. 45-52
  6. Visibilitas mata telanjang (bintang & extended) — Eq. 53-63
  7. Visibilitas teleskopik (point source & extended) — Eq. 65-89
  8. Fungsi utilitas & verifikasi
=============================================================================
"""

import math
from typing import Optional, Dict, Tuple

from hilal_visibility.models.geometry import crescent_area


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 1: KONSTANTA
# ═══════════════════════════════════════════════════════════════════════════

# --- Zero-point fotometri ---
Z_V = 2.54e-6  # V-band illuminance zero-point [lux] (Cox 1999, di bawah eq. 4)
_ARCSEC2_TO_SR = (math.pi / (180.0 * 3600.0)) ** 2
_MU_ZERO_POINT = -2.5 * math.log10(_ARCSEC2_TO_SR / Z_V)

# --- S/P ratio referensi ---
RHO_BLACKWELL = 1.408   # S/P ratio lampu 2850K milik Blackwell (di bawah eq. 7)
RHO_KNOLL     = 1.155   # S/P ratio lampu 2360K milik Knoll (= RHO_BLACKWELL/1.220)

# --- Koefisien Blackwell (1946) untuk R(B) ---
# Scotopic branch (Eq. 23, koefisien dari Eq. 26)
_r1 =  6.505e-4
_r2 = -8.461e-4
# Photopic branch (Eq. 24, koefisien dari Eq. 27)
_r3 = 1.772e-4
_r4 = 7.167e-5
# Combined hyperbola (Eq. 25, koefisien dari Eq. 28)
_a1 =  5.949e-8
_a2 = -2.389e-7
_a3 =  2.459e-7
_a4 =  4.120e-4
_a5 = -4.225e-4

# --- Koefisien Taylor (1960) untuk C∞(B) ---
# Scotopic branch (Eq. 35, koefisien dari Eq. 37)
_k1 =  7.633e-3
_k2 = -7.174e-3
# Photopic branch (Eq. 36, koefisien dari Eq. 38)
_k3 = 0.0
_k4 = 2.720e-3
# Combined hyperbola (Eq. 39, koefisien dari Eq. 40)
_b1 =  9.606e-6
_b2 = -4.112e-5
_b3 =  5.019e-5
_b4 =  4.837e-3
_b5 = -4.884e-3

# --- Konstanta zero-background (Eq. 50-52) ---
_XI1  = 1.150e-4   # [sr]  — batas R untuk B → 0
_XI2  = 1.286e-1   # [dimensionless] — batas C∞ untuk B → 0
_ZETA = 1.150e-9   # [lux] — threshold illuminance point-source pada B=0

# --- Batas luminansi background efektif nol ---
B_FLOOR = 1e-5  # [cd/m²] ≈ 25 mag/arcsec²

# Conservative domains for the simplified single-regime threshold forms.
# Combined is used for the intervening mesopic range and by default everywhere.
SCOTOPIC_MAX_B = 3.426e-2  # 10^-2 footLambert
PHOTOPIC_MIN_B = 3.40

# Shared application reference, not a crescent-specific visual calibration.
# Atmosphere, optical throughput, magnification and FT/FM are modelled separately.
DEFAULT_VISUAL_FIELD_FACTOR = 2.0


def _finite_value(name: str, value: float) -> float:
    """Reject missing, nonnumeric, NaN and infinite physical inputs."""
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} harus berupa bilangan finite.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} harus finite.")
    return result


def _positive_value(name: str, value: float) -> float:
    result = _finite_value(name, value)
    if result <= 0:
        raise ValueError(f"{name} harus > 0.")
    return result


def _nonnegative_value(name: str, value: float) -> float:
    result = _finite_value(name, value)
    if result < 0:
        raise ValueError(f"{name} harus >= 0.")
    return result


def _validate_mode(mode: str) -> str:
    if mode not in ('auto', 'combined', 'scotopic', 'photopic'):
        raise ValueError(f"Mode threshold tidak dikenal: {mode!r}.")
    return 'combined' if mode == 'auto' else mode


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 2: KONVERSI SATUAN
# ═══════════════════════════════════════════════════════════════════════════

# --- nanoLambert <-> cd/m² ---
# 1 nL = 1e-9 Lambert; 1 Lambert = (1/π) × 10⁴ cd/m²
# Jadi: 1 nL = 10⁻⁵/π cd/m²
_NL_TO_CDM2 = 1e-5 / math.pi
_CDM2_TO_NL = math.pi * 1e5

# --- footLambert <-> cd/m² (satuan asli Blackwell) ---
# 1 fL = 3.426 cd/m² (disebutkan di Sec. 1.2)
_FL_TO_CDM2 = 3.426


def nL_to_cdm2(nL: float) -> float:
    """Konversi nanoLambert → cd/m²."""
    return nL * _NL_TO_CDM2


def cdm2_to_nL(cdm2: float) -> float:
    """Konversi cd/m² → nanoLambert."""
    return cdm2 * _CDM2_TO_NL


def fL_to_cdm2(fL: float) -> float:
    """Konversi footLambert → cd/m² (1 fL = 3.426 cd/m²)."""
    return fL * _FL_TO_CDM2


def arcmin2_to_sr(area_arcmin2: float) -> float:
    """Konversi luas angular arcmin² → steradian."""
    rad_per_arcmin = math.pi / (180.0 * 60.0)
    return area_arcmin2 * rad_per_arcmin ** 2


def sr_to_arcmin2(area_sr: float) -> float:
    """Konversi luas angular steradian → arcmin²."""
    rad_per_arcmin = math.pi / (180.0 * 60.0)
    return area_sr / rad_per_arcmin ** 2


def mag_to_lux(m_V: float) -> float:
    """V-magnitude → illuminance [lux].
    Dari definisi: m_V = -2.5 log(I/Z_V), atau I = Z_V × 10^(-0.4 m_V).
    Lihat persamaan di bawah eq. 4: m_V = -2.5 log J - 13.99.
    """
    m_V = _finite_value('m_V', m_V)
    try:
        result = Z_V * 10.0 ** (-0.4 * m_V)
    except OverflowError as exc:
        raise ValueError("m_V berada di luar rentang numerik fotometri.") from exc
    return _positive_value('illuminance hasil konversi', result)


def lux_to_mag(I_lux: float) -> float:
    """Illuminance [lux] → V-magnitude.
    m_V = -2.5 log(J/Z_V); -13.99 dalam paper adalah pembulatan.
    """
    I_lux = _nonnegative_value('I_lux', I_lux)
    if I_lux == 0:
        return float('inf')
    return -2.5 * (math.log10(I_lux) - math.log10(Z_V))


def cdm2_to_mag_arcsec2(B: float) -> float:
    """Luminance [cd/m²] → surface brightness [mag/arcsec²].
    μ_V = -2.5 log(B × sr_per_arcsec² / Z_V).
    Ini memakai zero point yang sama dengan magnitude terintegrasi;
    12.58 dalam paper adalah pembulatan.
    """
    B = _nonnegative_value('B', B)
    if B == 0:
        return float('inf')
    return -2.5 * math.log10(B) + _MU_ZERO_POINT


def mag_arcsec2_to_cdm2(mu: float) -> float:
    """Surface brightness [mag/arcsec²] → luminance [cd/m²].
    B = 10^((μ_zero - μ) / 2.5), dengan zero point dari Z_V.
    """
    mu = _finite_value('mu', mu)
    try:
        result = 10.0 ** ((_MU_ZERO_POINT - mu) / 2.5)
    except OverflowError as exc:
        raise ValueError("mu berada di luar rentang numerik fotometri.") from exc
    return _positive_value('luminance hasil konversi', result)


def deg2_to_arcmin2(area_deg2: float) -> float:
    """Konversi luas angular derajat² → arcmin²."""
    return area_deg2 * 3600.0


# --- Alias backward-compatible (nama dari crumey.py lama) ---
NANO_LAMBERT_TO_CD_M2 = _NL_TO_CDM2
CD_M2_TO_NANO_LAMBERT = _CDM2_TO_NL
nL_to_cd_m2 = nL_to_cdm2
cd_m2_to_nL = cdm2_to_nL


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 3: KOREKSI S/P RATIO DAN COLOR INDEX
# ═══════════════════════════════════════════════════════════════════════════

def sp_ratio_temperature(T: float) -> float:
    """S/P ratio (ρ_T) untuk sumber blackbody pada temperatur T [K].
    Eq. 7: ρ_T = 5.738×10⁶/T² − 8.152×10³/T + 3.564
    Akurat ~1% untuk 2000 ≤ T ≤ 50000 K.
    """
    return (5.738e6) / T**2 - (8.152e3) / T + 3.564


def sp_ratio_color_index(c: float) -> float:
    """S/P ratio (ρ_c) dari color index (B−V) = c.
    Eq. 13 (aproksimasi linier): log ρ_c = -0.1094c + 0.4378
    Akurat ~5% untuk -0.17 ≤ c ≤ 1.65.
    """
    return 10.0 ** (-0.1094 * c + 0.4378)


def sp_ratio_color_index_full(c: float) -> float:
    """S/P ratio dari color index — polinomial lengkap.
    Eq. 12: log ρ_c = polinom derajat-6 dalam c.
    Lebih akurat dari aproksimasi linier, terutama di ujung-ujung rentang.
    """
    log_rho = (-0.05905 * c**6 + 0.1674 * c**5 - 0.06563 * c**4
               - 0.1843  * c**3 + 0.2031 * c**2 - 0.1802  * c + 0.4447)
    return 10.0 ** log_rho


def color_correction_mag(color_index: float, lab_temp: float = 2850) -> float:
    """Koreksi magnitude untuk bintang dengan color index (B−V) tertentu,
    relatif terhadap sumber laboratorium Blackwell (2850K) atau Knoll (2360K).

    Eq. 15: m* − m_T = -2.5 log(ρ_T / ρ_c)

    Kasus khusus (Eq. 16): m* − m_2850 = 0.72 − 0.27(B−V)
    Kasus khusus (Eq. 17): m* − m_2360 = 0.94 − 0.27(B−V)

    Return: koreksi magnitude limit (positif = bintang dengan S/P lebih besar
                      bisa terdeteksi pada magnitude V yang lebih redup)
    """
    rho_T = sp_ratio_temperature(lab_temp)
    rho_c = sp_ratio_color_index(color_index)
    return -2.5 * math.log10(rho_T / rho_c)


def color_correction_between_stars(c1: float, c2: float) -> float:
    """Perbedaan magnitude threshold antara dua bintang dengan color index
    berbeda. Eq. 18: m1 − m2 = 0.27(c2 − c1).
    """
    return 0.27 * (c2 - c1)


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 4: MODEL INTI — R(B), C∞(B), q(B)
# ═══════════════════════════════════════════════════════════════════════════

# --- R(B): Ricco factor (= C × A pada limit point-source) ---

def R_scotopic(B: float) -> float:
    """R scotopic sederhana. Eq. 23 + Eq. 26.
    R = (r₁·B⁻¹/⁴ + r₂)²
    Valid untuk B ≲ 7×10⁻² cd/m² (sekitar 15.5 mag/arcsec²).
    """
    B = _positive_value('B', B)
    return (_r1 * B ** (-0.25) + _r2) ** 2


def R_photopic(B: float) -> float:
    """R photopic sederhana. Eq. 24 + Eq. 27.
    R = (r₃·B⁻¹/⁴ + r₄)²
    Valid untuk B ≳ 7×10⁻² cd/m².
    """
    B = _positive_value('B', B)
    return (_r3 * B ** (-0.25) + _r4) ** 2


def R_combined(B: float) -> float:
    """R combined (full-range hyperbola). Eq. 25 + Eq. 28.
    R = (√(a₁B⁻¹/² + a₂B⁻¹/⁴ + a₃) + a₄B⁻¹/⁴ + a₅)²
    Menangani transisi scotopic-photopic secara smooth.
    """
    B = _positive_value('B', B)
    inner_sq = _a1 * B ** (-0.5) + _a2 * B ** (-0.25) + _a3
    inner = math.sqrt(max(inner_sq, 0.0))
    return (inner + _a4 * B ** (-0.25) + _a5) ** 2


# --- C∞(B): threshold kontras untuk target sangat besar ---

def Cinf_scotopic(B: float) -> float:
    """C∞ scotopic sederhana. Eq. 35 + Eq. 37.
    C∞ = k₁·B⁻¹/⁴ + k₂
    """
    B = _positive_value('B', B)
    return _k1 * B ** (-0.25) + _k2


def Cinf_photopic(B: float) -> float:
    """C∞ photopic = konstan (Weber's law). Eq. 36 + Eq. 38.
    C∞ = k₄ = 2.720×10⁻³
    """
    _positive_value('B', B)
    return _k4


def Cinf_combined(B: float) -> float:
    """C∞ combined (full-range hyperbola). Eq. 39 + Eq. 40.
    C∞ = √(b₁B⁻¹/² + b₂B⁻¹/⁴ + b₃) + b₄B⁻¹/⁴ + b₅
    """
    B = _positive_value('B', B)
    inner_sq = _b1 * B ** (-0.5) + _b2 * B ** (-0.25) + _b3
    inner = math.sqrt(max(inner_sq, 0.0))
    return inner + _b4 * B ** (-0.25) + _b5


# --- q(B): eksponen penggabung (joining parameter) ---

def q_parameter(B: float) -> float:
    """Parameter q piecewise. Eqs. 42-44.
    q = 1.146 − 0.0885 log₁₀B   jika B ≥ 3.40 cd/m²     (photopic)
    q = 0.8861 + 0.4 log₁₀B      jika 0.193 ≤ B < 3.40    (mesopic)
    q = 0.6                        jika B < 0.193            (scotopic)

    Catatan: untuk astronomi malam, q selalu = 0.6 (= 3/5).
    """
    B = _positive_value('B', B)
    logB = math.log10(B)
    if B >= 3.40:
        return _positive_value('q(B)', 1.146 - 0.0885 * logB)
    elif B >= 0.193:
        return 0.8861 + 0.4 * logB
    else:
        return 0.6


# --- Alias backward-compatible (nama dari crumey.py lama) ---
crumey_R = R_combined
crumey_Cinf = Cinf_combined
crumey_q = q_parameter


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 5: FUNGSI THRESHOLD UTAMA
# ═══════════════════════════════════════════════════════════════════════════

def _threshold_components(B: float, mode: str = 'auto') -> Tuple[float, float, float, float]:
    """One coefficient selection for increment, point and extended limits.

    The floor uses the same branch coefficients evaluated exactly at B_FLOOR,
    rather than the rounded Xi constants, so the increment remains continuous.
    Raw R/Cinf functions are analytic formulas; the threshold contract restricts
    the simplified branches to conservative single-regime domains.
    """
    B = _nonnegative_value('B', B)
    mode = _validate_mode(mode)
    if mode == 'scotopic' and B > SCOTOPIC_MAX_B:
        raise ValueError(f"mode='scotopic' memerlukan B <= {SCOTOPIC_MAX_B}; gunakan combined.")
    if mode == 'photopic' and B < PHOTOPIC_MIN_B:
        raise ValueError(f"mode='photopic' memerlukan B >= {PHOTOPIC_MIN_B}; gunakan combined.")
    B_eff = max(B, B_FLOOR)
    if mode == 'scotopic':
        R, Cinf, q = R_scotopic(B_eff), Cinf_scotopic(B_eff), 0.6
    elif mode == 'photopic':
        R, Cinf, q = R_photopic(B_eff), Cinf_photopic(B_eff), q_parameter(B_eff)
    else:
        R, Cinf, q = R_combined(B_eff), Cinf_combined(B_eff), q_parameter(B_eff)
    return B_eff, _positive_value('R(B)', R), _positive_value('Cinf(B)', Cinf), _positive_value('q(B)', q)


def luminance_diagnostics(B: float) -> dict:
    """Working luminance regimes (Crumey Sec. 1.3), not curve selection.

    Mesopic spans 0.005 through 5 cd/m². These labels describe the actual
    background, without reconstructing the observer's adaptation history.
    Mesopic/photopic crescent predictions extrapolate achromatic target data;
    no chromatic correction or claim of visual validation is implied.
    """
    B = _nonnegative_value('B', B)
    regime = 'scotopic' if B < 0.005 else 'mesopic' if B <= 5.0 else 'photopic'
    return {'regime': regime, 'achromatic_extrapolation': regime != 'scotopic'}


def threshold_parameters(B: float, mode: str = 'auto') -> dict:
    """Expose the coefficients used by the threshold contract for audit/export.

    This selects the same branch and floor as increment_threshold. The regime
    label is diagnostic only; auto always uses the combined curve.
    """
    B_eval, R, Cinf, q = _threshold_components(B, mode)
    B = float(B)
    return {'B_actual': B, 'B_eval': B_eval, 'R': R, 'C_inf': Cinf,
            'q': q, 'ricco_area_sr': R / Cinf, 'floor_applied': B <= B_FLOOR,
            'curve': 'combined' if mode in ('auto', 'combined') else mode,
            **luminance_diagnostics(B)}


def increment_threshold(A_sr: float, B: float, F: float = 1.0,
                        mode: str = 'auto') -> float:
    """Threshold excess luminance ΔB [cd/m²], with actual background B >= 0.

    Above B_FLOOR this is Eq. 41: ΔB = F B ((R/A)^q + Cinf^q)^(1/q).
    At and below B_FLOOR the *increment*, not its ratio to actual B, is fixed
    at the value at the floor for the supplied area. This is an explicit
    continuous extension motivated by Eqs. 45–46; it does not literally
    reproduce constant contrast in Eq. 50 nor claim a fit to zero-background
    observations. In particular, ΔB is nonzero even when B is zero.

    auto/combined use the achromatic combined fit. scotopic requires
    B <= 0.03426, photopic B >= 3.4 cd/m²; the joining q must remain positive.
    These domain checks do not validate colour, adaptation or crescent shape.
    """
    A_sr = _positive_value('A_sr', A_sr)
    F = _positive_value('F', F)
    B_eff, R, Cinf, q = _threshold_components(B, mode)
    # Stable geometric combination, including very small target areas.
    x = q * (math.log(R) - math.log(A_sr))
    y = q * math.log(Cinf)
    largest = max(x, y)
    log_C = (largest + math.log1p(math.exp(min(x, y) - largest))) / q
    try:
        result = math.exp(math.log(F) + math.log(B_eff) + log_C)
    except OverflowError as exc:
        raise ValueError("Threshold berada di luar rentang numerik.") from exc
    return _positive_value('delta_B_threshold', result)


def contrast_threshold(A_sr: float, B: float, F: float = 1.0,
                       mode: str = 'auto') -> float:
    """Threshold contrast ΔB_th/B using the *actual*, strictly positive B.

    All coefficient and cutoff rules belong to increment_threshold. Below the
    floor contrast increases as 1/B, preserving a nonzero increment threshold.
    Use increment_threshold directly for a zero background.
    """
    B = _positive_value('B', B)
    return _positive_value('C_threshold', increment_threshold(A_sr, B, F, mode) / B)


def crumey_threshold(A_sr: float, B_cd: float, F: float = 1.0) -> float:
    """Kontras threshold C(A, B) — Eq. 41 (backward compatible).
    Selalu menggunakan combined form.
    """
    return contrast_threshold(A_sr, B_cd, F=F, mode='combined')


def crumey_visibility(Lt_cd: float, B_cd: float, A_sr: float,
                      F: float = 1.0) -> dict:
    """Cek visibilitas; Lt_cd adalah excess luminance objek [cd/m²]."""
    B_cd = _positive_value('B_cd', B_cd)
    delta_B_obj_cd = _nonnegative_value('Lt_cd', Lt_cd)
    C_obj = delta_B_obj_cd / B_cd
    C_th = crumey_threshold(A_sr, B_cd, F=F)
    visible = C_obj > C_th
    return {"C_obj": C_obj, "C_th": C_th, "visible": visible}


def point_source_threshold_illuminance(B: float, F: float = 1.0,
                                        mode: str = 'auto') -> float:
    """Threshold illuminance ΔI untuk point source (bintang).

    Scotopic (Eq. 32/53): ΔI = F × (r₁·B^(1/4) + r₂·B^(1/2))²
    Combined  (Eq. 34):   ΔI = F × (√(a₁B^½ + a₂B^¾ + a₃B) + a₄B^¼ + a₅B^½)²

    Catatan: ΔI = F × B_eff × R(B_eff), dengan B_eff=max(B,B_FLOOR).
    Ini limit A→0 dari increment_threshold, termasuk increment floor.

    Parameters
    ----------
    B : float   Actual background luminance [cd/m²], finite dan >= 0
    F : float   Field factor, finite dan > 0
    mode : str  Mengikuti domain increment_threshold; auto=combined.

    Returns
    -------
    float : threshold illuminance [lux]
    """
    F = _positive_value('F', F)
    B_eff, R, _, _ = _threshold_components(B, mode)
    return _positive_value('delta_I_threshold', F * B_eff * R)


def large_target_threshold_luminance(B: float, F: float = 1.0,
                                     mode: str = 'auto') -> float:
    """Large-area asymptote of increment_threshold, including its floor."""
    F = _positive_value('F', F)
    B_eff, _, Cinf, _ = _threshold_components(B, mode)
    return _positive_value('delta_B_infinite', F * B_eff * Cinf)


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 6: RICCO AREA
# ═══════════════════════════════════════════════════════════════════════════

def ricco_area_sr(B: float, mode: str = 'auto') -> float:
    """Ricco area A_R [steradian]. Eq. 22/59.
    A_R = R(B) / C∞(B)

    Target yang lebih kecil dari Ricco area tidak bisa dibedakan dari
    point source. Penting dalam astronomi: bintang samar bisa terlihat
    seperti nebula dan sebaliknya (lihat NGC di Dreyer 1971).

    Menggunakan R_combined/Cinf_combined agar valid di semua level B.
    """
    _, R, Cinf, _ = _threshold_components(B, mode)
    return R / Cinf


def ricco_radius_arcmin(B: float, mode: str = 'auto') -> float:
    """Ricco radius r_R [arcmin] = √(α_R / π)."""
    alpha_sr = ricco_area_sr(B, mode)
    alpha_arcmin2 = sr_to_arcmin2(alpha_sr)
    return math.sqrt(alpha_arcmin2 / math.pi)


def ricco_radius_approx(mu_sky: float) -> float:
    """Aproksimasi Ricco radius. Eq. 63.
    r_R ≈ 5.21·μsky − 76.2  [arcmin]
    Valid untuk 21 ≤ μsky ≤ 22, error maks 0.05 arcmin.
    """
    return 5.21 * mu_sky - 76.2


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 7: VISIBILITAS MATA TELANJANG
# ═══════════════════════════════════════════════════════════════════════════

def naked_eye_limiting_mag(mu_sky: float, F: float = 2.0,
                           mode: str = 'auto') -> float:
    """Limiting magnitude bintang dengan mata telanjang.
    Dari point-source asymptote backend threshold yang sama dengan extended.
    auto memakai combined; mode='scotopic' mereproduksi bentuk Eq. 53.

    Parameters
    ----------
    mu_sky : float  Sky surface brightness [mag/arcsec²]
    F      : float  Residual field factor (default 2.0 = nilai referensi Sec. 3.1)

    Returns
    -------
    float : limiting V-magnitude

    Contoh dari paper: untuk langit gelap μ = 21.83, F = 2 → m₀ = 6.18 mag.
    """
    B = mag_arcsec2_to_cdm2(mu_sky)
    dI = point_source_threshold_illuminance(B, F=F, mode=mode)
    return lux_to_mag(dI)


def naked_eye_limiting_mag_approx(mu_sky: float, F: float = 2.0) -> float:
    """Aproksimasi linier untuk limiting magnitude.
    Eq. 55: m₀ ≈ 0.4260·μsky − 2.3650 − 2.5 log(F)
    Valid untuk 21 < μsky < 25, error maks 0.04 mag.

    Eq. 54 (alternatif, range lebih sempit):
    m₀ ≈ 0.3834·μsky − 1.4400 − 2.5 log(F)  untuk 20 < μsky < 22.
    """
    mu_sky = _finite_value('mu_sky', mu_sky)
    F = _positive_value('F', F)
    return 0.4260 * mu_sky - 2.3650 - 2.5 * math.log10(F)


def naked_eye_surface_brightness_limit(mu_sky: float, F: float = 2.0,
                                       mode: str = 'auto') -> float:
    """Limiting surface brightness untuk target sangat besar (μ∞).
    Dari large-target asymptote backend yang sama dengan point/extended.
    mode='scotopic' memakai Eq. 56: ΔB∞ = F(k₁B^(3/4) + k₂B).
    Di bawah floor increment tetap pada nilai floor; zero point memakai Z_V.

    Returns
    -------
    float : μ∞ [mag/arcsec²]
    """
    B = mag_arcsec2_to_cdm2(mu_sky)
    dB_inf = large_target_threshold_luminance(B, F, mode)
    return cdm2_to_mag_arcsec2(dB_inf)


def naked_eye_surface_brightness_limit_approx(mu_sky: float, F: float = 2.0) -> float:
    """Aproksimasi linier. Eq. 57:
    μ∞ ≈ 0.6864·μsky + 9.9325 − 2.5 log(F)
    Valid untuk 18 < μsky < 22, error maks 0.02 mag/arcsec².
    """
    mu_sky = _finite_value('mu_sky', mu_sky)
    F = _positive_value('F', F)
    return 0.6864 * mu_sky + 9.9325 - 2.5 * math.log10(F)


def naked_eye_extended_target(alpha_arcmin2: float, mu_sky: float,
                               F: float = 2.0,
                               mode: str = 'auto') -> Dict[str, float]:
    """Visibilitas target extended dengan mata telanjang. Eqs. 58-62.

    Menggabungkan limit point-source (m₀) dan limit surface brightness (μ∞)
    melalui threshold curve yang smooth.

    Parameters
    ----------
    alpha_arcmin2 : float  Luas target pada langit [arcmin²]
    mu_sky        : float  Sky surface brightness [mag/arcsec²]
    F             : float  Field factor

    Returns
    -------
    dict :
        'm_lim'            : limiting magnitude target
        'mu_lim'           : limiting surface brightness target [mag/arcsec²]
        'm0'               : point-source limit
        'mu_inf'           : large-target surface brightness limit
        'alpha_R_arcmin2'  : Ricco area [arcmin²]
        'ricco_radius_arcmin' : Ricco radius [arcmin]
    """
    alpha_arcmin2 = _positive_value('alpha_arcmin2', alpha_arcmin2)
    B = mag_arcsec2_to_cdm2(mu_sky)
    A_sr = arcmin2_to_sr(alpha_arcmin2)
    delta_B_th = increment_threshold(A_sr, B, F, mode)
    m0 = naked_eye_limiting_mag(mu_sky, F, mode)
    mu_inf = naked_eye_surface_brightness_limit(mu_sky, F, mode)

    alpha_R_sr = ricco_area_sr(B, mode)
    alpha_R = sr_to_arcmin2(alpha_R_sr)
    r_R = math.sqrt(alpha_R / math.pi)

    # One physical luminance produces both limits, so μ=m+2.5log(A_arcsec²)
    # exactly up to floating-point precision in every regime and at the floor.
    m_lim = lux_to_mag(delta_B_th * A_sr)
    mu_lim = cdm2_to_mag_arcsec2(delta_B_th)

    return {
        'm_lim': m_lim,
        'mu_lim': mu_lim,
        'm0': m0,
        'mu_inf': mu_inf,
        'alpha_R_arcmin2': alpha_R,
        'ricco_radius_arcmin': r_R,
        'delta_B_th': delta_B_th,
        'C_th': delta_B_th / B,
    }


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 8: VISIBILITAS TELESKOPIK
# ═══════════════════════════════════════════════════════════════════════════

def _validate_telescopic_inputs(B: float, D: float, M: float,
                                p: float, Ft: float) -> Tuple[float, float, float, float, float]:
    B = _nonnegative_value('B', B)
    D = _positive_value('D', D)
    M = _positive_value('M', M)
    p = _positive_value('p', p)
    Ft = _positive_value('Ft', Ft)
    if Ft < 1:
        raise ValueError('Ft adalah 1/transmittance dan harus >= 1.')
    return B, D, M, p, Ft


def _telescopic_field_factor(F: float, FT: Optional[float], FM: float) -> float:
    F = _positive_value('F', F)
    FT = math.sqrt(2) if FT is None else _positive_value('FT', FT)
    FM = _positive_value('FM', FM)
    return _positive_value('phi', F * FT * FM)


def _telescopic_params(B: float, D: float, M: float, p: float, Ft: float):
    """Hitung parameter teleskopik internal (helper function).

    Returns
    -------
    tuple : (d, delta_min, delta_max, Ba, Ba_eff, d0)
        d          : exit pupil [m]
        delta_min   : min(d, p)
        delta_max   : max(d, p)
        Ba          : apparent background luminance [cd/m²] (Eq. 66)
        Ba_eff      : Ba di-clamp ke B_FLOOR
        d0          : exit pupil di mana background menjadi efektif nol (Eq. 70)
    """
    B, D, M, p, Ft = _validate_telescopic_inputs(B, D, M, p, Ft)
    d = _positive_value('exit pupil', D / M)
    delta_min = min(d, p)
    delta_max = max(d, p)

    # Eq. 66: Ba = (δmin/p)² × B/Ft
    Ba = (delta_min / p) ** 2 * B / Ft
    Ba_eff = max(Ba, B_FLOOR)

    # Eq. 70: d₀ = p × √(10⁻⁵ × Ft / B)
    # Exit pupil di mana Ba = B_FLOOR
    d0 = p * math.sqrt(B_FLOOR * Ft / B) if B > 0 else float('inf')

    return d, delta_min, delta_max, Ba, Ba_eff, d0


def telescopic_extended_threshold(
        A_sr: float, B: float, D: float, M: float,
        p: float = 0.007, Ft: float = 1.33,
        F: float = 2.0, FT: Optional[float] = None,
        FM: float = 1.0, mode: str = 'auto', *,
        dimming_factor: Optional[float] = None) -> Dict[str, float]:
    """One telescopic extended-source contract using sky inputs in SI units.

    The optical dimming g=(min(D/M,p)/p)^2/Ft acts equally on target and
    background: B_a=g B, ΔB_a=g ΔB; the actual apparent area is M² A.
    Optional dimming_factor in [0,1] supplies an independently computed optical
    throughput, e.g. a clipped annular exit pupil. FT defaults to sqrt(2) for
    monocular viewing; FM is an explicit field-factor assumption (Sec. 1.6.4).
    F is residual laboratory/observer/target/viewing scaling, excluding the
    explicitly modelled atmosphere, throughput, magnification and FT/FM.

    At B_a below B_FLOOR this implementation keeps actual M² A and freezes
    the increment at the floor for that area. This is a declared extension,
    differing from paper Sec. 3.3's M0-frozen extended-source cutoff. It keeps
    point and extended helpers on one threshold curve; it is not empirically
    validated for highly magnified crescents, aberrations or very wide fields.

    C_th compares sky contrast ΔB/B with threshold; delta_B_th is the excess
    sky luminance required. With zero sky B, C_th is +inf (contrast undefined)
    but increment outputs remain valid. Fully blocked throughput g=0 yields
    infinite sky-referred threshold, with no division by zero.
    """
    A_sr = _positive_value('A_sr', A_sr)
    B, D, M, p, Ft = _validate_telescopic_inputs(B, D, M, p, Ft)
    phi = _telescopic_field_factor(F, FT, FM)
    d, delta_min, delta_max, _, _, d0 = _telescopic_params(B, D, M, p, Ft)
    g = (delta_min / p) ** 2 / Ft
    if dimming_factor is not None:
        g = _nonnegative_value('dimming_factor', dimming_factor)
        if g > 1:
            raise ValueError('dimming_factor harus <= 1 untuk optik pasif.')
    M_squared = _positive_value('M_squared', M * M)
    A_app_sr = _positive_value('A_app_sr', A_sr * M_squared)
    B_a = _nonnegative_value('B_a', g * B)
    delta_B_app_th = increment_threshold(A_app_sr, B_a, phi, mode)
    delta_B_th = _positive_value('delta_B_th', delta_B_app_th / g) if g > 0 else float('inf')
    C_th = (_positive_value('C_th', delta_B_th / B)
            if B > 0 and g > 0 else float('inf'))
    return {
        'C_th': C_th,
        'delta_B_th': delta_B_th,
        'delta_B_app_th': delta_B_app_th,
        'B_a': B_a,
        'A_app_sr': A_app_sr,
        'dimming_factor': g,
        'phi': phi,
        'exit_pupil': d,
        'delta_min': delta_min,
        'delta_max': delta_max,
        'exit_pupil_cutoff': d0,
        'floor_applied': B_a <= B_FLOOR,
        **luminance_diagnostics(B_a),
    }


def telescopic_point_source_limit(
        mu_sky: float, D: float, M: float,
        p: float = 0.007, Ft: float = 1.33,
        F: float = 2.0, FT: Optional[float] = None,
        FM: float = 1.0, mode: str = 'auto') -> float:
    """Limiting magnitude bintang melalui teleskop. Eqs. 65-73.

    Parameters
    ----------
    mu_sky : float  Sky surface brightness [mag/arcsec²]
    D      : float  Diameter entrance pupil (bukaan bersih) [m]
    M      : float  Magnifikasi (perbesaran)
    p      : float  Diameter pupil mata [m] (default 7mm, muda, gelap-adapted)
    Ft     : float  1/transmittance (misal 1.33 untuk 75%) — BUKAN transmittance!
    F      : float  Naked-eye field factor (default 2.0)
    FT     : float  Telescope field factor, default √2 (koreksi monocular, Sec. 1.6.4)
    FM     : float  Magnification-dependent field factor (default 1.0)

    Returns
    -------
    float : limiting V-magnitude melalui teleskop

    Contoh dari paper (Eq. 73):
      D=0.1m, p=7mm, Ft=1.33, F=2, FT=√2, FM=1
      → mcut = 5 log(D[cm]) + 8.45 - 2.5 log(F)
             = 5 log(10) + 8.45 - 0.75 = 12.70 mag
    """
    phi = _telescopic_field_factor(F, FT, FM)
    _, D, M, p, Ft = _validate_telescopic_inputs(0.0, D, M, p, Ft)
    B = mag_arcsec2_to_cdm2(mu_sky)
    d, delta_min, delta_max, Ba, Ba_eff, d0 = _telescopic_params(B, D, M, p, Ft)
    g = (delta_min / p) ** 2 / Ft
    # ΔI_app = M² g ΔI_sky, with the same point-source asymptote as extended.
    M_squared = _positive_value('M_squared', M * M)
    flux_gain = _positive_value('apparent flux gain', g * M_squared)
    dI = _positive_value('sky delta_I_threshold', point_source_threshold_illuminance(Ba, phi, mode) / flux_gain)
    return lux_to_mag(dI)


def telescopic_point_source_limit_approx(
        mu_sky: float, D: float, M: float,
        p: float = 0.007, Ft: float = 1.33,
        F: float = 2.0, FT: Optional[float] = None,
        FM: float = 1.0) -> float:
    """Aproksimasi linier untuk limit teleskopik. Eq. 69.
    m₀ ≈ 0.426μsky − 2.365 + 5log(D/δmax) − 2.131log(δmin/p)
         − 1.435logFt − 2.5log(FM·FT·F)
    """
    _telescopic_field_factor(F, FT, FM)
    _, D, M, p, Ft = _validate_telescopic_inputs(0.0, D, M, p, Ft)
    mu_sky = _finite_value('mu_sky', mu_sky)
    if FT is None:
        FT = math.sqrt(2)
    d = D / M
    delta_min = min(d, p)
    delta_max = max(d, p)

    return (0.426 * mu_sky - 2.365
            + 5.0 * math.log10(D / delta_max)
            - 2.131 * math.log10(delta_min / p)
            - 1.435 * math.log10(Ft)
            - 2.5 * math.log10(FM * FT * F))


def telescopic_cutoff_mag(D: float, p: float = 0.007, Ft: float = 1.33,
                           F: float = 2.0, FT: Optional[float] = None,
                           FM: float = 1.0, mode: str = 'auto') -> float:
    """Magnitude limit absolut teleskop (zero-background cutoff). Eq. 72-73.
    mcut = 5 log D − 2.5 log(Z⁻¹ ζ p² Ft FM FT F)

    Ini adalah limit yang tidak bisa dilampaui seberapapun magnifikasinya.
    """
    _, D, _, p, Ft = _validate_telescopic_inputs(0.0, D, 1.0, p, Ft)
    phi = _telescopic_field_factor(F, FT, FM)
    dI_cut = point_source_threshold_illuminance(0.0, phi, mode) * (p / D) ** 2 * Ft
    return lux_to_mag(dI_cut)


def telescopic_exit_pupil_cutoff(B: float, p: float = 0.007,
                                  Ft: float = 1.33) -> float:
    """Exit pupil d₀ di mana background menjadi efektif nol. Eq. 70.
    d₀ = p × √(10⁻⁵ × Ft / B)  [m]

    Ini menandai cutoff point-source; threshold extended tetap memakai M²A.
    """
    B, _, _, p, Ft = _validate_telescopic_inputs(B, 1.0, 1.0, p, Ft)
    return p * math.sqrt(B_FLOOR * Ft / B) if B > 0 else float('inf')


def telescopic_extended_target(
        alpha_arcmin2: float, mu_sky: float, D: float, M: float,
        p: float = 0.007, Ft: float = 1.33,
        F: float = 2.0, FT: Optional[float] = None,
        FM: float = 1.0, mode: str = 'auto') -> Dict[str, float]:
    """Visibilitas target extended melalui teleskop. Eqs. 77-89.

    Menghitung threshold curve teleskopik, yang berbentuk sama dengan
    naked-eye tapi dengan asymptotes yang bergeser karena magnifikasi
    dan darkening background.

    Parameters
    ----------
    alpha_arcmin2 : float  Luas target pada langit [arcmin²]
    mu_sky, D, M, p, Ft, F, FT, FM : sama seperti telescopic_point_source_limit

    Returns
    -------
    dict :
        'm_lim'             : limiting magnitude target
        'mu_lim'            : limiting surface brightness [mag/arcsec²]
        'm0'                : point-source limit
        'mu_inf'            : large-target surface brightness limit
        'alpha_TR_arcmin2'  : telescopic Ricco area pada langit [arcmin²]
    """
    alpha_arcmin2 = _positive_value('alpha_arcmin2', alpha_arcmin2)
    B = mag_arcsec2_to_cdm2(mu_sky)
    A_sr = arcmin2_to_sr(alpha_arcmin2)
    threshold = telescopic_extended_threshold(A_sr, B, D, M, p, Ft, F, FT, FM, mode)
    Ba, g, phi = threshold['B_a'], threshold['dimming_factor'], threshold['phi']
    alpha_TR_sr = ricco_area_sr(Ba, mode) / M ** 2
    alpha_TR = sr_to_arcmin2(alpha_TR_sr)
    m0 = telescopic_point_source_limit(mu_sky, D, M, p, Ft, F, FT, FM, mode)
    mu_inf = cdm2_to_mag_arcsec2(large_target_threshold_luminance(Ba, phi, mode) / g)
    m_lim = lux_to_mag(threshold['delta_B_th'] * A_sr)
    mu_lim = cdm2_to_mag_arcsec2(threshold['delta_B_th'])

    return {
        'm_lim': m_lim,
        'mu_lim': mu_lim,
        'm0': m0,
        'mu_inf': mu_inf,
        'alpha_TR_arcmin2': alpha_TR,
        **threshold,
    }


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 9: FUNGSI VISIBILITAS SEDERHANA (API user-friendly)
# ═══════════════════════════════════════════════════════════════════════════

def visibility_margin_mag(C_obj: float, C_th: float) -> float:
    """Margin [mag]; positif hanya jika kontras melebihi threshold."""
    if C_obj > 0 and C_th > 0:
        return 2.5 * (math.log10(C_obj) - math.log10(C_th))
    return float('-inf')


def is_visible(Lt_cdm2: float, B_cdm2: float, A_sr: float,
               F: float = 2.0) -> Dict[str, float]:
    """Cek apakah target terlihat — versi sederhana dan user-friendly.

    Parameters
    ----------
    Lt_cdm2 : float  Direct/excess luminance objek, ΔB [cd/m²]
    B_cdm2  : float  Luminansi background [cd/m²]
    A_sr    : float  Luas angular target [steradian]
    F       : float  Field factor

    Returns
    -------
    dict :
        'C_object'    : kontras objek
        'C_threshold' : kontras threshold
        'visible'     : boolean
        'margin_mag'  : margin visibilitas dalam magnitude
                        (positif = terlihat, negatif = tidak)
    """
    B_cdm2 = _positive_value('B_cdm2', B_cdm2)
    delta_B_obj_cd = _nonnegative_value('Lt_cdm2', Lt_cdm2)
    C_obj = delta_B_obj_cd / B_cdm2
    C_th = contrast_threshold(A_sr, B_cdm2, F=F)
    visible = C_obj > C_th

    margin = visibility_margin_mag(C_obj, C_th)

    return {
        'C_object': C_obj,
        'C_threshold': C_th,
        'visible': visible,
        'margin_mag': margin,
    }


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 10: LUAS SABIT HILAL
# ═══════════════════════════════════════════════════════════════════════════

def crescent_area_deg2(elongation_deg: float, sd_deg: float) -> float:
    """Luas sabit [derajat²] dari elongasi; memakai geometri bersama."""
    return crescent_area(elongation_deg, sd_deg)


def crescent_area_arcmin2(elongation_deg: float, sd_deg: float) -> float:
    """Luas sabit hilal [arcmin²]."""
    return crescent_area_deg2(elongation_deg, sd_deg) * 3600.0


def crescent_area_sr(elongation_deg: float, sd_deg: float) -> float:
    """Luas sabit hilal [steradian]."""
    return arcmin2_to_sr(crescent_area_arcmin2(elongation_deg, sd_deg))


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 11: VISIBILITAS HILAL — NAKED EYE
# ═══════════════════════════════════════════════════════════════════════════

def hilal_naked_eye_visibility(
        L_hilal_nL: float,
        B_sky_nL: float,
        elongation_deg: float,
        moon_sd_deg: float,
        F: float = DEFAULT_VISUAL_FIELD_FACTOR,
        mode: str = 'auto'
) -> dict:
    """
    Visibilitas hilal mata telanjang menggunakan model Crumey.

    Pipeline:
      1. Konversi nL → cd/m² (baik L_hilal maupun B_sky)
      2. Hitung luas sabit [sr] dari elongasi dan semidiameter
      3. Hitung contrast dari increment hilal: C_obj = L_obj / B_sky
      4. Hitung Crumey threshold: C_th = contrast_threshold(A, B, F)
      5. Bandingkan: visible jika C_obj > C_th

    Parameters
    ----------
    L_hilal_nL : float
        Direct/excess luminance hilal, ΔB [nanoLambert], setelah atmosfer
    B_sky_nL : float
        Kecerahan langit di posisi hilal [nanoLambert]
    elongation_deg : float
        Separasi sudut Matahari–Bulan [derajat]
    moon_sd_deg : float
        Semidiameter bulan [derajat], tipikal ~0.25°
    F : float
        Residual visual field factor: laboratory scaling, pengamat, dan
        efek target/viewing yang belum dimodelkan. Default 2.0 adalah asumsi
        referensi, belum dikalibrasi khusus hilal. Tidak mencakup extinction,
        transmisi optik, magnifikasi, atau faktor FT/FM yang sudah eksplisit.
    mode : str
        'auto' (direkomendasikan), 'scotopic', 'photopic', 'combined'

    Returns
    -------
    dict:
        'C_obj'         : Weber contrast hilal terhadap langit
        'C_th'          : Contrast threshold Crumey (sudah × F)
        'visible'       : bool, True jika C_obj > C_th
        'margin'        : log₁₀(C_obj / C_th), positif = terlihat
        'delta_m'       : 2.5 × log₁₀(C_obj / C_th), positif = terlihat
        'L_cd'          : excess luminance hilal, ΔB [cd/m²]
        'B_cd'          : kecerahan langit [cd/m²]
        'A_sr'          : luas sabit [sr]
        'A_arcmin2'     : luas sabit [arcmin²]
        'regime'        : regime visual ('photopic'/'mesopic'/'scotopic')
        'achromatic_extrapolation' : mesopic/photopic memakai extrapolasi achromatic
    """
    # Langkah 1: Konversi nL → cd/m²
    L_hilal_nL = _nonnegative_value('L_hilal_nL', L_hilal_nL)
    B_sky_nL = _positive_value('B_sky_nL', B_sky_nL)
    F = _positive_value('F', F)
    # Validate mode/domain even for a legitimate zero-area source.
    _threshold_components(nL_to_cdm2(B_sky_nL), mode)
    delta_B_obj_cd = nL_to_cdm2(L_hilal_nL)
    L_cd = delta_B_obj_cd  # alias output untuk kompatibilitas
    B_cd = nL_to_cdm2(B_sky_nL)

    # Langkah 2: Luas sabit
    A_arcmin2 = crescent_area_arcmin2(elongation_deg, moon_sd_deg)
    A_sr = arcmin2_to_sr(A_arcmin2)

    # Langkah 3: Weber contrast
    C_obj = delta_B_obj_cd / B_cd

    # Langkah 4: Crumey threshold
    C_th = contrast_threshold(A_sr, B_cd, F=F, mode=mode) if A_sr > 0 else float('inf')

    # Langkah 5: Keputusan visibilitas
    visible = C_obj > C_th

    delta_m = visibility_margin_mag(C_obj, C_th)
    margin = delta_m / 2.5

    return {
        'C_obj': C_obj,
        'C_th': C_th,
        'visible': visible,
        'margin': margin,
        'delta_m': delta_m,
        'L_cd': L_cd,
        'B_cd': B_cd,
        'A_sr': A_sr,
        'A_arcmin2': A_arcmin2,
        **luminance_diagnostics(B_cd),
    }


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 12: VERIFIKASI — Cek terhadap nilai-nilai dari paper
# ═══════════════════════════════════════════════════════════════════════════

def _run_verification():
    """Jalankan tes verifikasi terhadap nilai-nilai yang dikutip dalam paper."""
    print("=" * 70)
    print("VERIFIKASI IMPLEMENTASI vs PAPER CRUMEY (2014)")
    print("=" * 70)
    errors = 0
    total = 0

    def check(name, computed, expected, tol=0.05, unit=""):
        nonlocal errors, total
        total += 1
        diff = abs(computed - expected)
        ok = diff <= tol
        status = "✓" if ok else "✗"
        if not ok:
            errors += 1
        print(f"  {status} {name}: computed={computed:.4f}, expected={expected:.4f}, "
              f"diff={diff:.4f} {unit}  {'OK' if ok else 'GAGAL'}")

    # --- Tes 1: S/P ratio untuk 2850K (harus ≈ 1.408) ---
    print("\n[1] S/P ratio blackbody 2850K (paper menyatakan ρ₂₈₅₀ = 1.408)")
    rho = sp_ratio_temperature(2850)
    check("ρ(2850K)", rho, 1.408, tol=0.01)

    # --- Tes 2: Color correction (Eq. 16) ---
    print("\n[2] Color correction m*−m₂₈₅₀ untuk (B−V)=0 (Eq. 16 → 0.72)")
    corr = color_correction_mag(0.0, 2850)
    check("m*−m₂₈₅₀ at c=0", corr, 0.72, tol=0.02, unit="mag")

    print("    Color correction untuk (B−V)=1.0 (Eq. 16 → 0.45)")
    corr1 = color_correction_mag(1.0, 2850)
    check("m*−m₂₈₅₀ at c=1", corr1, 0.45, tol=0.02, unit="mag")

    # --- Tes 3: Naked-eye limiting mag, dark sky (Sec. 3.1) ---
    print("\n[3] Naked-eye limit: μsky=21.83, F=2 (paper → m₀ = 6.18)")
    m0 = naked_eye_limiting_mag(21.83, F=2.0)
    check("m₀(21.83, F=2)", m0, 6.18, tol=0.05, unit="mag")

    # --- Tes 4: Naked-eye limit, F=1 (paper: m₀ = 6.93) ---
    print("\n[4] Naked-eye limit: μsky=21.83, F=1 (paper → m₀ = 6.93)")
    m0_f1 = naked_eye_limiting_mag(21.83, F=1.0)
    check("m₀(21.83, F=1)", m0_f1, 6.93, tol=0.05, unit="mag")

    # --- Tes 5: Surface brightness limit (Sec. 3.1) ---
    print("\n[5] μ∞ at μsky=21.83, F=1 (paper → 24.94)")
    mu_inf = naked_eye_surface_brightness_limit(21.83, F=1.0)
    check("μ∞(21.83, F=1)", mu_inf, 24.94, tol=0.10, unit="mag/arcsec²")

    # --- Tes 6: Ricco radius (Eq. 63) ---
    print("\n[6] Ricco radius approx at μsky=21.83 (Eq. 63 → 37.5 arcmin)")
    r_R = ricco_radius_approx(21.83)
    check("rR(21.83)", r_R, 37.5, tol=0.5, unit="arcmin")

    # --- Tes 7: Teleskop — cutoff magnitude (Eq. 73) ---
    # Paper: D=100mm, p=7mm, Ft=1.33, F=2 → N=7.69 → mcut = 5log(10) + 7.69 = 12.69
    print("\n[7] Telescopic cutoff: D=100mm, p=7mm, 75% trans, F=2 (Eq. 73 → ~12.7)")
    mcut = telescopic_cutoff_mag(D=0.1, p=0.007, Ft=1.33, F=2.0)
    check("mcut(100mm)", mcut, 12.70, tol=0.15, unit="mag")

    # --- Tes 8: Zero-background constant ξ₁ ---
    print("\n[8] Konstanta zero-bg ξ₁ (Eq. 51 → 1.150×10⁻⁴)")
    xi1_calc = (10 ** (5.0/4) * _r1 + _r2) ** 2
    check("ξ₁", xi1_calc, 1.150e-4, tol=1e-6)

    # --- Tes 9: Konstanta zero-bg ξ₂ (Eq. 52 → 1.286×10⁻¹) ---
    print("\n[9] Konstanta zero-bg ξ₂ (Eq. 52 → 1.286×10⁻¹)")
    xi2_calc = 10 ** (5.0/4) * _k1 + _k2
    check("ξ₂", xi2_calc, 1.286e-1, tol=1e-3)

    # --- Tes 10: Aproksimasi linier Eq. 55 vs eksak ---
    print("\n[10] Eq. 55 approx vs exact at μsky=21.5, F=2")
    m_exact = naked_eye_limiting_mag(21.5, F=2.0)
    m_approx = naked_eye_limiting_mag_approx(21.5, F=2.0)
    check("approx−exact", abs(m_exact - m_approx), 0.0, tol=0.05, unit="mag")

    # --- Ringkasan ---
    print(f"\n{'=' * 70}")
    print(f"HASIL: {total - errors}/{total} tes lolos")
    if errors == 0:
        print("Semua verifikasi BERHASIL!")
    else:
        print(f"PERHATIAN: {errors} tes GAGAL — periksa implementasi!")
    print("=" * 70)


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 11: DEMO PENGGUNAAN
# ═══════════════════════════════════════════════════════════════════════════

def _demo():
    """Demonstrasi penggunaan fungsi-fungsi utama."""
    print("\n" + "=" * 70)
    print("DEMO PENGGUNAAN MODEL CRUMEY (2014)")
    print("=" * 70)

    # --- Skenario 1: Mata telanjang di situs gelap ---
    mu_sky = 21.83  # langit gelap tipikal
    F = 2.0         # nilai referensi, bukan kategori kemahiran pengamat

    print(f"\n--- Skenario 1: Mata telanjang, μsky = {mu_sky} mag/arcsec² ---")
    m0 = naked_eye_limiting_mag(mu_sky, F)
    mu_inf = naked_eye_surface_brightness_limit(mu_sky, F)
    print(f"  Limiting magnitude (bintang)          : {m0:.2f} mag")
    print(f"  Limiting surface brightness (extended) : {mu_inf:.2f} mag/arcsec²")
    print(f"  Ricco radius                          : {ricco_radius_arcmin(mag_arcsec2_to_cdm2(mu_sky)):.1f} arcmin")

    # --- Skenario 2: Visibilitas M33 ---
    print(f"\n--- Skenario 2: Apakah M33 terlihat mata telanjang? ---")
    # M33: area ≈ 25.3 arcmin radius (ke isofot 25.3 mag/arcsec²)
    # tapi area efektif visual lebih kecil
    result = naked_eye_extended_target(alpha_arcmin2=1100, mu_sky=21.83, F=1.378)
    print(f"  (F dipilih = 1.378 agar M33 tepat di threshold)")
    print(f"  m_lim  = {result['m_lim']:.2f} mag")
    print(f"  μ_lim  = {result['mu_lim']:.2f} mag/arcsec²")
    print(f"  m₀     = {result['m0']:.2f} mag (stellar limit diperlukan)")

    # --- Skenario 3: Teleskop 6-inch (150mm) ---
    D = 0.15        # 6 inch
    M = 50          # magnifikasi 50×
    Ft_val = 1.05   # transmittance 95%
    print(f"\n--- Skenario 3: Teleskop {D*1000:.0f}mm, ×{M}, μsky = {mu_sky} ---")
    m_tel = telescopic_point_source_limit(mu_sky, D, M, Ft=Ft_val, F=2.0)
    mcut = telescopic_cutoff_mag(D, Ft=Ft_val, F=2.0)
    print(f"  Stellar limit at ×{M}  : {m_tel:.2f} mag")
    print(f"  Cutoff (max possible) : {mcut:.2f} mag")

    # Variasi magnifikasi
    print(f"\n  Limit vs magnifikasi:")
    for mag in [20, 50, 100, 200, 500]:
        m = telescopic_point_source_limit(mu_sky, D, mag, Ft=Ft_val, F=2.0)
        d_exit = D / mag * 1000  # mm
        print(f"    ×{mag:>4d} (exit pupil {d_exit:.2f}mm) : {m:.2f} mag")

    # --- Skenario 4: Efek polusi cahaya ---
    print(f"\n--- Skenario 4: Efek polusi cahaya pada naked-eye limit ---")
    for mu in [22.0, 21.5, 21.0, 20.5, 20.0, 19.5, 19.0]:
        m = naked_eye_limiting_mag(mu, F=2.0)
        print(f"    μsky = {mu:.1f} mag/arcsec² → limit = {m:.2f} mag")

    # --- Skenario 5: Koreksi warna bintang ---
    print(f"\n--- Skenario 5: Koreksi warna (color index) ---")
    for bv in [-0.2, 0.0, 0.5, 1.0, 1.5]:
        corr = color_correction_mag(bv, 2850)
        print(f"    (B−V) = {bv:+.1f} → Δm = {corr:+.3f} mag")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    _run_verification()
    _demo()
