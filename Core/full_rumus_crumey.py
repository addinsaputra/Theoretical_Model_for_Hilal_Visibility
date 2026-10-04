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

from crescent_geometry import crescent_area


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 1: KONSTANTA
# ═══════════════════════════════════════════════════════════════════════════

# --- Zero-point fotometri ---
Z_V = 2.54e-6  # V-band illuminance zero-point [lux] (Cox 1999, di bawah eq. 4)

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
    return Z_V * 10.0 ** (-0.4 * m_V)


def lux_to_mag(I_lux: float) -> float:
    """Illuminance [lux] → V-magnitude.
    m_V = -2.5 log(J) - 13.99  (di bawah eq. 4)
    """
    if I_lux <= 0:
        return float('inf')
    return -2.5 * math.log10(I_lux) - 13.99


def cdm2_to_mag_arcsec2(B: float) -> float:
    """Luminance [cd/m²] → surface brightness [mag/arcsec²].
    μ_V = -2.5 log(B) + 12.58  (di bawah eq. 4)
    """
    if B <= 0:
        return float('inf')
    return -2.5 * math.log10(B) + 12.58


def mag_arcsec2_to_cdm2(mu: float) -> float:
    """Surface brightness [mag/arcsec²] → luminance [cd/m²].
    B = 10^((12.58 - μ) / 2.5)
    """
    return 10.0 ** ((12.58 - mu) / 2.5)


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

    Return: koreksi (positif = bintang terlihat lebih redup secara scotopic
                      dibanding sumber lab pada luminansi photopic yang sama)
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
    return (_r1 * B ** (-0.25) + _r2) ** 2


def R_photopic(B: float) -> float:
    """R photopic sederhana. Eq. 24 + Eq. 27.
    R = (r₃·B⁻¹/⁴ + r₄)²
    Valid untuk B ≳ 7×10⁻² cd/m².
    """
    return (_r3 * B ** (-0.25) + _r4) ** 2


def R_combined(B: float) -> float:
    """R combined (full-range hyperbola). Eq. 25 + Eq. 28.
    R = (√(a₁B⁻¹/² + a₂B⁻¹/⁴ + a₃) + a₄B⁻¹/⁴ + a₅)²
    Menangani transisi scotopic-photopic secara smooth.
    """
    inner_sq = _a1 * B ** (-0.5) + _a2 * B ** (-0.25) + _a3
    inner = math.sqrt(max(inner_sq, 0.0))
    return (inner + _a4 * B ** (-0.25) + _a5) ** 2


# --- C∞(B): threshold kontras untuk target sangat besar ---

def Cinf_scotopic(B: float) -> float:
    """C∞ scotopic sederhana. Eq. 35 + Eq. 37.
    C∞ = k₁·B⁻¹/⁴ + k₂
    """
    return _k1 * B ** (-0.25) + _k2


def Cinf_photopic(B: float) -> float:
    """C∞ photopic = konstan (Weber's law). Eq. 36 + Eq. 38.
    C∞ = k₄ = 2.720×10⁻³
    """
    return _k4


def Cinf_combined(B: float) -> float:
    """C∞ combined (full-range hyperbola). Eq. 39 + Eq. 40.
    C∞ = √(b₁B⁻¹/² + b₂B⁻¹/⁴ + b₃) + b₄B⁻¹/⁴ + b₅
    """
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
    logB = math.log10(B)
    if B >= 3.40:
        return 1.146 - 0.0885 * logB
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

def contrast_threshold(A_sr: float, B: float, F: float = 1.0,
                       mode: str = 'auto') -> float:
    """Hitung kontras threshold C(A, B) sesuai model Crumey.

    Ini adalah persamaan utama model: Eq. 41 (general) dan Eq. 47 (scotopic).
    C = F × ((R/A)^q + C∞^q)^(1/q)

    Parameters
    ----------
    A_sr : float
        Luas angular target [steradian]. Harus > 0.
    B : float
        Luminansi background [cd/m²]. Harus > 0.
    F : float
        Overall field factor (default 1.0 = kondisi lab ideal).
        Untuk pengamatan nyata, paper menyarankan F ≈ 2 (Sec. 3.1).
        F mencakup: laboratory scaling, personal factor, age factor, dll.
    mode : str
        'scotopic'  : bentuk sederhana (Eq. 47) — R_scotopic + Cinf_scotopic
                      + q=0.6. PERHATIAN: R_scotopic/Cinf_scotopic hanya akurat
                      untuk B ≲ 0.05 cd/m²; di atasnya divergen dari combined.
        'photopic'  : gunakan bentuk photopic
        'combined'  : bentuk combined (Eq. 41) — R_combined + Cinf_combined
                      + q(B). Valid di semua level luminansi, termasuk scotopic
                      (karena q(B<0.193)=0.6 dan hyperbola asimptotik ke branch
                      scotopic).
        'auto'      : gunakan combined (Eq. 41) untuk semua B.

    Returns
    -------
    float : kontras threshold (dimensionless)
    """
    if A_sr <= 0:
        raise ValueError("Luas angular A harus > 0.")
    if B <= 0:
        raise ValueError("Luminansi background B harus > 0.")

    # Clamp ke background floor untuk menangani zero-background
    B_eff = max(B, B_FLOOR)

    if mode == 'auto':
        mode = 'combined'

    # Zero-background: Eq. 50-52 — berlaku untuk semua mode
    # Pada B ≤ B_FLOOR, R dan C∞ diganti konstanta limit (ξ₁, ξ₂)
    if B_eff <= B_FLOOR:
        C = ((_XI1 / A_sr) ** 0.6 + _XI2 ** 0.6) ** (5.0 / 3.0)
        return F * C

    if mode == 'scotopic':
        # Scotopic normal: Eq. 47
        # C = ((R/A)^(3/5) + C∞^(3/5))^(5/3)  dengan q = 0.6
        R = R_scotopic(B_eff)
        Cinf = Cinf_scotopic(B_eff)
        C = ((R / A_sr) ** 0.6 + Cinf ** 0.6) ** (5.0 / 3.0)

    elif mode == 'photopic':
        R = R_photopic(B_eff)
        Cinf = Cinf_photopic(B_eff)
        q = q_parameter(B_eff)
        C = ((R / A_sr) ** q + Cinf ** q) ** (1.0 / q)

    else:  # combined
        R = R_combined(B_eff)
        Cinf = Cinf_combined(B_eff)
        q = q_parameter(B_eff)
        C = ((R / A_sr) ** q + Cinf ** q) ** (1.0 / q)

    return F * C


def crumey_threshold(A_sr: float, B_cd: float, F: float = 1.0) -> float:
    """Kontras threshold C(A, B) — Eq. 41 (backward compatible).
    Selalu menggunakan combined form.
    """
    return contrast_threshold(A_sr, B_cd, F=F, mode='combined')


def crumey_visibility(Lt_cd: float, B_cd: float, A_sr: float,
                      F: float = 1.0) -> dict:
    """Cek visibilitas; Lt_cd adalah excess luminance objek [cd/m²]."""
    if B_cd <= 0:
        raise ValueError("B must be positive.")
    delta_B_obj_cd = Lt_cd
    C_obj = delta_B_obj_cd / B_cd
    C_th = crumey_threshold(A_sr, B_cd, F=F)
    visible = C_obj > C_th
    return {"C_obj": C_obj, "C_th": C_th, "visible": visible}


def point_source_threshold_illuminance(B: float, F: float = 1.0,
                                        mode: str = 'auto') -> float:
    """Threshold illuminance ΔI untuk point source (bintang).

    Scotopic (Eq. 32/53): ΔI = F × (r₁·B^(1/4) + r₂·B^(1/2))²
    Combined  (Eq. 34):   ΔI = F × (√(a₁B^½ + a₂B^¾ + a₃B) + a₄B^¼ + a₅B^½)²

    Catatan: ΔI = B × R, karena untuk point source C = R/A dan ΔI = A × ΔB = A × B × C.
    Tapi karena R = C×A dan ΔI = A×B×C = B×R, kita bisa hitung langsung.

    Parameters
    ----------
    B : float   Background luminance [cd/m²]
    F : float   Field factor
    mode : str  'scotopic' (Eq. 32, akurat B ≲ 0.05), 'combined' (Eq. 34,
                valid semua B), atau 'auto' (= combined)

    Returns
    -------
    float : threshold illuminance [lux]
    """
    B_eff = max(B, B_FLOOR) if B > 0 else B_FLOOR

    if mode == 'auto':
        mode = 'combined'

    # Zero-background: ΔI = F × ζ (Eq. 51/71) — berlaku untuk semua mode
    if B_eff <= B_FLOOR:
        return F * _ZETA

    if mode == 'scotopic':
        # Eq. 32: ΔI = (r₁·B^¼ + r₂·B^½)²
        dI = (_r1 * B_eff ** 0.25 + _r2 * B_eff ** 0.5) ** 2

    elif mode == 'combined':
        # Eq. 34: ΔI = (√(a₁B^½ + a₂B^¾ + a₃B) + a₄B^¼ + a₅B^½)²
        inner_sq = _a1 * B_eff**0.5 + _a2 * B_eff**0.75 + _a3 * B_eff
        inner = math.sqrt(max(inner_sq, 0.0))
        dI = (inner + _a4 * B_eff**0.25 + _a5 * B_eff**0.5) ** 2

    else:
        raise ValueError(f"Mode tidak dikenal: {mode}")

    return F * dI


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 6: RICCO AREA
# ═══════════════════════════════════════════════════════════════════════════

def ricco_area_sr(B: float) -> float:
    """Ricco area A_R [steradian]. Eq. 22/59.
    A_R = R(B) / C∞(B)

    Target yang lebih kecil dari Ricco area tidak bisa dibedakan dari
    point source. Penting dalam astronomi: bintang samar bisa terlihat
    seperti nebula dan sebaliknya (lihat NGC di Dreyer 1971).

    Menggunakan R_combined/Cinf_combined agar valid di semua level B.
    """
    B_eff = max(B, B_FLOOR)
    if B_eff <= B_FLOOR:
        # Zero-background limit: A_R = ξ₁ / ξ₂
        return _XI1 / _XI2
    R = R_combined(B_eff)
    Cinf = Cinf_combined(B_eff)
    if Cinf <= 0:
        return float('inf')
    return R / Cinf


def ricco_radius_arcmin(B: float) -> float:
    """Ricco radius r_R [arcmin] = √(α_R / π)."""
    alpha_sr = ricco_area_sr(B)
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

def naked_eye_limiting_mag(mu_sky: float, F: float = 2.0) -> float:
    """Limiting magnitude bintang dengan mata telanjang.
    Dihitung dari Eq. 53 (eksak).

    Parameters
    ----------
    mu_sky : float  Sky surface brightness [mag/arcsec²]
    F      : float  Field factor (default 2.0 = pengamat tipikal, lihat Sec. 3.1)

    Returns
    -------
    float : limiting V-magnitude

    Contoh dari paper: untuk langit gelap μ = 21.83, F = 2 → m₀ = 6.18 mag.
    """
    B = mag_arcsec2_to_cdm2(mu_sky)
    dI = point_source_threshold_illuminance(B, F=F, mode='scotopic')
    return lux_to_mag(dI)


def naked_eye_limiting_mag_approx(mu_sky: float, F: float = 2.0) -> float:
    """Aproksimasi linier untuk limiting magnitude.
    Eq. 55: m₀ ≈ 0.4260·μsky − 2.3650 − 2.5 log(F)
    Valid untuk 21 < μsky < 25, error maks 0.04 mag.

    Eq. 54 (alternatif, range lebih sempit):
    m₀ ≈ 0.3834·μsky − 1.4400 − 2.5 log(F)  untuk 20 < μsky < 22.
    """
    return 0.4260 * mu_sky - 2.3650 - 2.5 * math.log10(F)


def naked_eye_surface_brightness_limit(mu_sky: float, F: float = 2.0) -> float:
    """Limiting surface brightness untuk target sangat besar (μ∞).
    Dari Eq. 56: ΔB∞ = F × (k₁·B^(3/4) − k₂·B) [note: k₂ negatif!]
    Lalu μ∞ = -2.5 log(ΔB∞) + 12.58.

    Returns
    -------
    float : μ∞ [mag/arcsec²]
    """
    B = mag_arcsec2_to_cdm2(mu_sky)
    B_eff = max(B, B_FLOOR)
    # ΔB∞ = F × C∞ × B = F × (k₁·B⁻¹/⁴ + k₂) × B = F × (k₁·B³/⁴ + k₂·B)
    Cinf = Cinf_scotopic(B_eff)
    dB_inf = F * Cinf * B
    return cdm2_to_mag_arcsec2(dB_inf)


def naked_eye_surface_brightness_limit_approx(mu_sky: float, F: float = 2.0) -> float:
    """Aproksimasi linier. Eq. 57:
    μ∞ ≈ 0.6864·μsky + 9.9325 − 2.5 log(F)
    Valid untuk 18 < μsky < 22, error maks 0.02 mag/arcsec².
    """
    return 0.6864 * mu_sky + 9.9325 - 2.5 * math.log10(F)


def naked_eye_extended_target(alpha_arcmin2: float, mu_sky: float,
                               F: float = 2.0) -> Dict[str, float]:
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
    B = mag_arcsec2_to_cdm2(mu_sky)
    B_eff = max(B, B_FLOOR)

    m0 = naked_eye_limiting_mag(mu_sky, F)
    mu_inf = naked_eye_surface_brightness_limit(mu_sky, F)

    alpha_R_sr = ricco_area_sr(B_eff)
    alpha_R = sr_to_arcmin2(alpha_R_sr)
    r_R = math.sqrt(alpha_R / math.pi)

    q = 0.6  # scotopic
    alpha = alpha_arcmin2

    # Eq. 62: mlim = m₀ − (2.5/q) × log₁₀((α/αR)^q + 1)
    m_lim = m0 - (2.5 / q) * math.log10((alpha / alpha_R) ** q + 1)

    # Eq. 60: μlim = μ∞ − (2.5/q) × log₁₀((αR/α)^q + 1)
    mu_lim = mu_inf - (2.5 / q) * math.log10((alpha_R / alpha) ** q + 1)

    return {
        'm_lim': m_lim,
        'mu_lim': mu_lim,
        'm0': m0,
        'mu_inf': mu_inf,
        'alpha_R_arcmin2': alpha_R,
        'ricco_radius_arcmin': r_R,
    }


# ═══════════════════════════════════════════════════════════════════════════
# BAGIAN 8: VISIBILITAS TELESKOPIK
# ═══════════════════════════════════════════════════════════════════════════

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
    d = D / M                          # exit pupil
    delta_min = min(d, p)
    delta_max = max(d, p)

    # Eq. 66: Ba = (δmin/p)² × B/Ft
    Ba = (delta_min / p) ** 2 * B / Ft
    Ba_eff = max(Ba, B_FLOOR)

    # Eq. 70: d₀ = p × √(10⁻⁵ × Ft / B)
    # Exit pupil di mana Ba = B_FLOOR
    d0 = p * math.sqrt(B_FLOOR * Ft / B) if B > 0 else float('inf')

    return d, delta_min, delta_max, Ba, Ba_eff, d0


def telescopic_point_source_limit(
        mu_sky: float, D: float, M: float,
        p: float = 0.007, Ft: float = 1.33,
        F: float = 2.0, FT: Optional[float] = None,
        FM: float = 1.0) -> float:
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
    if FT is None:
        FT = math.sqrt(2)

    phi = FT * FM * F  # total field factor (Sec. 3.2)

    B = mag_arcsec2_to_cdm2(mu_sky)
    d, delta_min, delta_max, Ba, Ba_eff, d0 = _telescopic_params(B, D, M, p, Ft)

    if Ba <= B_FLOOR:
        # Zero-background cutoff: Eq. 71-72
        # Icut = ζ × (p/D)² × Ft × φ
        # Di sini δmax = p karena d < d₀ ≤ p (biasanya)
        dI_cut = _ZETA * (p / D) ** 2 * Ft * phi
        return lux_to_mag(dI_cut)

    # Kasus normal: Eq. 68
    # ΔI = (δmax/D)² × Ft × φ × (r₁·Ba^¼ + r₂·Ba^½)²
    dI = (delta_max / D) ** 2 * Ft * phi * (_r1 * Ba_eff**0.25 + _r2 * Ba_eff**0.5) ** 2

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
                           FM: float = 1.0) -> float:
    """Magnitude limit absolut teleskop (zero-background cutoff). Eq. 72-73.
    mcut = 5 log D − 2.5 log(Z⁻¹ ζ p² Ft FM FT F)

    Ini adalah limit yang tidak bisa dilampaui seberapapun magnifikasinya.
    """
    if FT is None:
        FT = math.sqrt(2)
    phi = FT * FM * F
    dI_cut = _ZETA * (p / D) ** 2 * Ft * phi
    return lux_to_mag(dI_cut)


def telescopic_exit_pupil_cutoff(B: float, p: float = 0.007,
                                  Ft: float = 1.33) -> float:
    """Exit pupil d₀ di mana background menjadi efektif nol. Eq. 70.
    d₀ = p × √(10⁻⁵ × Ft / B)  [m]

    Untuk d < d₀, magnifikasi lebih lanjut tidak meningkatkan threshold.
    """
    return p * math.sqrt(B_FLOOR * Ft / B)


def telescopic_extended_target(
        alpha_arcmin2: float, mu_sky: float, D: float, M: float,
        p: float = 0.007, Ft: float = 1.33,
        F: float = 2.0, FT: Optional[float] = None,
        FM: float = 1.0) -> Dict[str, float]:
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
    if FT is None:
        FT = math.sqrt(2)

    phi = FT * FM * F

    B = mag_arcsec2_to_cdm2(mu_sky)
    d, delta_min, delta_max, Ba, Ba_eff, d0 = _telescopic_params(B, D, M, p, Ft)

    # Hitung threshold di apparent background (Eq. 78-80)
    Ra = R_scotopic(Ba_eff)
    Ca = Cinf_scotopic(Ba_eff)
    q = 0.6  # scotopic

    # Eq. 81: telescopic Ricco area pada langit [sr]
    # ATR = Ra / (M² × Ca)
    alpha_TR_sr = Ra / (M ** 2 * Ca)
    alpha_TR = sr_to_arcmin2(alpha_TR_sr)

    # Point-source limit
    m0 = telescopic_point_source_limit(mu_sky, D, M, p, Ft, F, FT, FM)

    # Eq. 86: large-target surface brightness limit
    # μ∞ = μsky − 2.5 log(φ × Ca)
    mu_inf = cdm2_to_mag_arcsec2(phi * Ca * B)

    alpha = alpha_arcmin2

    # Eq. 88: mlim = m₀ − (2.5/q) × log₁₀((α/αTR)^q + 1)
    m_lim = m0 - (2.5 / q) * math.log10((alpha / alpha_TR) ** q + 1)

    # Eq. 84: μlim = μ∞ − (2.5/q) × log₁₀((αTR/α)^q + 1)
    mu_lim = mu_inf - (2.5 / q) * math.log10((alpha_TR / alpha) ** q + 1)

    return {
        'm_lim': m_lim,
        'mu_lim': mu_lim,
        'm0': m0,
        'mu_inf': mu_inf,
        'alpha_TR_arcmin2': alpha_TR,
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
    if B_cdm2 <= 0:
        raise ValueError("Background luminance harus > 0.")

    delta_B_obj_cd = Lt_cdm2
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
        F: float = 2.5,
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
        Field factor untuk pengamatan hilal (default 2.5).
        Panduan: 2.0 (pengamat mahir), 2.5 (tipikal), 3.0+ (pemula)
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
    """
    # Langkah 1: Konversi nL → cd/m²
    delta_B_obj_cd = nL_to_cdm2(L_hilal_nL)
    L_cd = delta_B_obj_cd  # alias output untuk kompatibilitas
    B_cd = nL_to_cdm2(B_sky_nL)

    if B_cd <= 0:
        return {
            'C_obj': float('nan'), 'C_th': float('nan'),
            'visible': False, 'margin': float('-inf'), 'delta_m': float('-inf'),
            'L_cd': L_cd, 'B_cd': B_cd,
            'A_sr': 0, 'A_arcmin2': 0,
            'regime': 'unknown',
        }

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

    # Regime visual
    if B_cd > 5.0:
        regime = 'photopic'
    elif B_cd > 0.005:
        regime = 'mesopic'
    else:
        regime = 'scotopic'

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
        'regime': regime,
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
    F = 2.0         # pengamat tipikal

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
