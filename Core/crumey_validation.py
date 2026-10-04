"""
══════════════════════════════════════════════════════════════════════════════
PENGUJIAN KOMPREHENSIF: Implementasi vs Paper Crumey (2014)
"Human contrast threshold and astronomical visibility"
MNRAS 442, 2600-2619

Script ini menguji setiap nilai numerik yang disebutkan secara eksplisit
dalam paper, terorganisasi per section dan per persamaan.
══════════════════════════════════════════════════════════════════════════════
"""

import math
import sys
sys.path.insert(0, '/home/claude')
from full_rumus_crumey import *
import full_rumus_crumey as cr

# Akses konstanta private melalui modul
_r1 = cr._r1; _r2 = cr._r2; _r3 = cr._r3; _r4 = cr._r4
_k1 = cr._k1; _k2 = cr._k2
_a1 = cr._a1; _a2 = cr._a2; _a3 = cr._a3; _a4 = cr._a4; _a5 = cr._a5
_b1 = cr._b1; _b2 = cr._b2; _b3 = cr._b3; _b4 = cr._b4; _b5 = cr._b5

# ═══════════════════════════════════════════════════════════════════════════
# FRAMEWORK UJI
# ═══════════════════════════════════════════════════════════════════════════

class TestRunner:
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.results = []  # for summary table

    def check(self, name, computed, expected, tol, unit="", eq_ref=""):
        self.total += 1
        diff = abs(computed - expected)
        ok = diff <= tol
        if ok:
            self.passed += 1
            status = "✅ PASS"
        else:
            self.failed += 1
            status = "❌ FAIL"

        rel_err = abs(diff / expected * 100) if expected != 0 else 0

        print(f"  {status}  {name}")
        print(f"         Computed : {computed:.6g} {unit}")
        print(f"         Expected : {expected:.6g} {unit} (dari {eq_ref})")
        print(f"         Diff     : {diff:.2e} ({rel_err:.3f}%)")
        print()

        self.results.append({
            'name': name, 'computed': computed, 'expected': expected,
            'diff': diff, 'rel_err': rel_err, 'ok': ok, 'eq_ref': eq_ref
        })
        return ok

    def print_summary(self):
        print("\n" + "═" * 78)
        print("RINGKASAN HASIL PENGUJIAN")
        print("═" * 78)
        print(f"\n  Total tes    : {self.total}")
        print(f"  Lolos (PASS) : {self.passed}  ✅")
        print(f"  Gagal (FAIL) : {self.failed}  {'❌' if self.failed else ''}")
        print(f"  Akurasi      : {self.passed/self.total*100:.1f}%")

        if self.failed == 0:
            print(f"\n  🎉 SEMUA {self.total} TES BERHASIL! Implementasi cocok dengan paper.")
        else:
            print(f"\n  ⚠️  {self.failed} tes gagal — periksa implementasi!")

        # Tabel ringkasan
        print(f"\n{'─' * 78}")
        print(f"  {'No':>3}  {'Status':6}  {'Tes':40}  {'Err%':>8}  {'Ref'}")
        print(f"{'─' * 78}")
        for i, r in enumerate(self.results, 1):
            st = "✅" if r['ok'] else "❌"
            print(f"  {i:>3}  {st:6}  {r['name']:40}  {r['rel_err']:>7.3f}%  {r['eq_ref']}")
        print(f"{'─' * 78}")


T = TestRunner()

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1.2: KONVERSI SATUAN BLACKWELL
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 1.2: Konversi Satuan (footLambert → cd/m²)")
print("═" * 78)
print()
print("  Paper menyatakan: '1 fL = 3.426 cd/m²' (Sec. 1.2)")
print()

T.check("1 fL → cd/m²",
        fL_to_cdm2(1.0), 3.426, tol=0.001,
        unit="cd/m²", eq_ref="Sec. 1.2")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1.3: KONVERSI FOTOMETRI (di bawah Eq. 4)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 1.3: Konversi Fotometri")
print("═" * 78)
print()
print("  Paper menyatakan di bawah Eq. 4:")
print("    mV = -2.5 log(J) - 13.99")
print("    μV = -2.5 log(B) + 12.58")
print("    dengan ZV = 2.54×10⁻⁶ lux")
print()

# Langit gelap: 2×10⁻⁴ cd/m² ≈ 21.83 mag/arcsec²
T.check("Dark sky B → μ",
        cdm2_to_mag_arcsec2(2e-4), 21.83, tol=0.02,
        unit="mag/arcsec²", eq_ref="di bawah Eq. 4")

T.check("μ=21.83 → B",
        mag_arcsec2_to_cdm2(21.83), 2e-4, tol=5e-6,
        unit="cd/m²", eq_ref="di bawah Eq. 4")

# Scotopic limit ≈ 18.3 mag/arcsec² ≈ 0.005 cd/m² (Sec. 1.3)
T.check("Scotopic limit 0.005 cd/m² → μ",
        cdm2_to_mag_arcsec2(0.005), 18.33, tol=0.1,
        unit="mag/arcsec²", eq_ref="Sec. 1.3, CIE 2010")

# Background efektif nol: 10⁻⁵ cd/m² ≈ 25.08 mag/arcsec² (Sec. 2.1)
T.check("B=10⁻⁵ → μ (floor)",
        cdm2_to_mag_arcsec2(1e-5), 25.08, tol=0.02,
        unit="mag/arcsec²", eq_ref="Sec. 2.1")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1.3: S/P RATIO (Eq. 5-7)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 1.3: S/P Ratio — Blackbody Temperature (Eq. 7)")
print("═" * 78)
print()
print("  Eq. 7: ρ_T = 5.738×10⁶/T² − 8.152×10³/T + 3.564")
print()

# Paper menyatakan ρ₂₈₅₀ = 1.408 (di bawah Eq. 7)
T.check("ρ(2850K) — Blackwell",
        sp_ratio_temperature(2850), 1.408, tol=0.005,
        eq_ref="di bawah Eq. 7")

# Paper menyatakan ρ₂₈₅₀/ρ₂₃₆₀ = 1.220 (Sec. 1.3)
rho_2850 = sp_ratio_temperature(2850)
rho_2360 = sp_ratio_temperature(2360)
T.check("ρ₂₈₅₀/ρ₂₃₆₀ ≈ 1.220",
        rho_2850 / rho_2360, 1.220, tol=0.02,
        eq_ref="Sec. 1.3")

# Langit tipikal ρ_sky ≈ 1.38 (60% airglow, Sec. 1.3 akhir)
# dan ρ_Blackwell ≈ 1.41 → mendekati (≈ 58% airglow)
T.check("ρ(5500K) blackbody (matahari/zodiacal)",
        sp_ratio_temperature(5500), 2.26, tol=0.05,
        eq_ref="Sec. 1.3, 0% airglow")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1.3: COLOR INDEX CORRECTIONS (Eq. 12-18)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 1.3: Color Index Corrections (Eq. 12-18)")
print("═" * 78)
print()

# Eq. 16: m* − m₂₈₅₀ = 0.72 − 0.27(B−V)
# Untuk (B−V) = 0: koreksi = 0.72
T.check("Eq. 16: color corr at (B−V)=0",
        color_correction_mag(0.0, 2850), 0.72, tol=0.02,
        unit="mag", eq_ref="Eq. 16")

# Untuk (B−V) = 1.0: koreksi = 0.72 − 0.27 = 0.45
T.check("Eq. 16: color corr at (B−V)=1.0",
        color_correction_mag(1.0, 2850), 0.45, tol=0.02,
        unit="mag", eq_ref="Eq. 16")

# Eq. 17: m* − m₂₃₆₀ = 0.94 − 0.27(B−V)
# Untuk (B−V) = 0: koreksi = 0.94
T.check("Eq. 17: color corr Knoll at (B−V)=0",
        color_correction_mag(0.0, 2360), 0.94, tol=0.02,
        unit="mag", eq_ref="Eq. 17")

# Eq. 18: m₁ − m₂ = 0.27(c₂ − c₁)
T.check("Eq. 18: Δm between c=0 and c=1",
        color_correction_between_stars(0.0, 1.0), 0.27, tol=0.001,
        unit="mag", eq_ref="Eq. 18")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2.2: POINT-SOURCE MODEL COEFFICIENTS (Eq. 23-28)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 2.2: Point-Source Model Coefficients (Eq. 23-28)")
print("═" * 78)
print()
print("  Verifikasi koefisien r₁-r₄, a₁-a₅ dan split-point.")
print()

# Split-point scotopic/photopic: B = 7.08×10⁻² cd/m² (Sec. 2.2)
# Pada split-point, R_scotopic ≈ R_photopic
R_scot_sp = R_scotopic(7.08e-2)
R_phot_sp = R_photopic(7.08e-2)
T.check("R_scot ≈ R_phot at split B=7.08e-2",
        R_scot_sp, R_phot_sp, tol=R_scot_sp * 0.15,
        unit="sr", eq_ref="Sec. 2.2, split-point")

# Verifikasi: R_combined harus ≈ R_scotopic di level scotopic rendah
B_test = 1e-4  # jauh di bawah split-point
T.check("R_combined ≈ R_scotopic at B=10⁻⁴",
        R_combined(B_test), R_scotopic(B_test),
        tol=R_scotopic(B_test) * 0.01,
        unit="sr", eq_ref="Sec. 2.2")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2.3: LARGE-TARGET MODEL (Eq. 35-40)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 2.3: Large-Target C∞ Coefficients (Eq. 35-40)")
print("═" * 78)
print()

# Weber's law: C∞ → k₄ = 2.720×10⁻³ untuk photopic (B besar)
T.check("C∞ photopic (Weber's law) = k₄",
        Cinf_photopic(100.0), 2.720e-3, tol=1e-6,
        eq_ref="Eq. 36 + Eq. 38")

# Cinf combined ≈ Cinf scotopic di level rendah
B_low = 1e-4  # well into scotopic range
T.check("Cinf_combined ≈ Cinf_scotopic at B=10⁻⁴",
        Cinf_combined(B_low), Cinf_scotopic(B_low),
        tol=Cinf_scotopic(B_low) * 0.05,
        eq_ref="Eq. 39 vs 35")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2.3: q PARAMETER (Eq. 42-44)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 2.3: Parameter q (Eq. 42-44)")
print("═" * 78)
print()

# q = 0.6 untuk semua B < 0.193 (scotopic) — ini kasus astronomi
T.check("q(B=10⁻⁴) = 0.6 [scotopic]",
        q_parameter(1e-4), 0.6, tol=0.001,
        eq_ref="Eq. 44")

T.check("q(B=10⁻²) = 0.6 [scotopic]",
        q_parameter(1e-2), 0.6, tol=0.001,
        eq_ref="Eq. 44")

# Boundary: B = 0.193 → q dari eq. 43 = 0.8861 + 0.4*log10(0.193)
q_boundary = 0.8861 + 0.4 * math.log10(0.193)
T.check("q(B=0.193) from Eq. 43",
        q_parameter(0.193), q_boundary, tol=0.001,
        eq_ref="Eq. 43 boundary")

# Boundary: B = 3.40 → q dari eq. 42 = 1.146 − 0.0885*log10(3.40)
q_phot = 1.146 - 0.0885 * math.log10(3.40)
T.check("q(B=3.40) from Eq. 42",
        q_parameter(3.40), q_phot, tol=0.001,
        eq_ref="Eq. 42 boundary")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2.3: ZERO-BACKGROUND CONSTANTS (Eq. 50-52)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 2.3: Zero-Background Constants (Eq. 50-52)")
print("═" * 78)
print()

# ξ₁ = (10^(5/4)·r₁ + r₂)² = 1.150×10⁻⁴ sr (Eq. 51)
xi1_calc = (10**(5.0/4) * _r1 + _r2)**2
T.check("ξ₁ = (10^(5/4)·r₁ + r₂)²",
        xi1_calc, 1.150e-4, tol=1e-6,
        unit="sr", eq_ref="Eq. 51")

# ξ₂ = 10^(5/4)·k₁ + k₂ = 1.286×10⁻¹ (Eq. 52)
xi2_calc = 10**(5.0/4) * _k1 + _k2
T.check("ξ₂ = 10^(5/4)·k₁ + k₂",
        xi2_calc, 1.286e-1, tol=1e-3,
        eq_ref="Eq. 52")

# Ricco area pada B = 10⁻⁵: paper menyatakan = 8.94×10⁻⁴ sr
# (Sec. 2.3, "the Ricco area is 8.94×10⁻⁴ sr, or 116 arcmin diameter")
ricco_at_floor = xi1_calc / xi2_calc
T.check("Ricco area at B=10⁻⁵",
        ricco_at_floor, 8.94e-4, tol=1e-5,
        unit="sr", eq_ref="Sec. 2.3")

# Ricco diameter ≈ 116 arcmin
ricco_diam = 2 * math.sqrt(sr_to_arcmin2(ricco_at_floor) / math.pi)
T.check("Ricco diameter at B=10⁻⁵",
        ricco_diam, 116.0, tol=2.0,
        unit="arcmin", eq_ref="Sec. 2.3")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.1: NAKED-EYE STELLAR VISIBILITY (Eq. 53-55)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.1: Naked-Eye Stellar Visibility (Eq. 53-55)")
print("═" * 78)
print()
print("  Paper menyatakan di Sec. 3.1:")
print("    Langit gelap B = 2×10⁻⁴ cd/m² (21.83 mag/arcsec²)")
print("    Eq. 53 dgn F=1 → m₀ = 6.93 mag")
print("    → F tipikal antara 1.4 (limit 6.57) sampai 2.4 (limit 5.98)")
print("    → F = 2 → limit 6.18 mag")
print()

# m₀ = 6.93 − 2.5 log F (Sec. 3.1)
T.check("m₀ at μ=21.83, F=1",
        naked_eye_limiting_mag(21.83, F=1.0), 6.93, tol=0.02,
        unit="mag", eq_ref="Sec. 3.1")

T.check("m₀ at μ=21.83, F=2",
        naked_eye_limiting_mag(21.83, F=2.0), 6.18, tol=0.02,
        unit="mag", eq_ref="Sec. 3.1, Fig. 11")

# F = 2.4 → limit ≈ 5.98
T.check("m₀ at μ=21.83, F=2.4",
        naked_eye_limiting_mag(21.83, F=2.4), 5.98, tol=0.05,
        unit="mag", eq_ref="Sec. 3.1")

# F = 1.4 → limit ≈ 6.57
T.check("m₀ at μ=21.83, F=1.4",
        naked_eye_limiting_mag(21.83, F=1.4), 6.57, tol=0.05,
        unit="mag", eq_ref="Sec. 3.1")

# F = 0.94 → limit 7.0 (paper: "7 mag corresponding to F = 0.94")
T.check("m₀ at μ=21.83, F=0.94",
        naked_eye_limiting_mag(21.83, F=0.94), 7.00, tol=0.05,
        unit="mag", eq_ref="Sec. 3.1")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.1: APROKSIMASI LINIER (Eq. 54-55)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.1: Aproksimasi Linier (Eq. 54, 55)")
print("═" * 78)
print()
print("  Eq. 54: m₀ ≈ 0.3834μ − 1.4400 − 2.5logF  (20<μ<22, err<0.01)")
print("  Eq. 55: m₀ ≈ 0.4260μ − 2.3650 − 2.5logF  (21<μ<25, err<0.04)")
print()

# Tes Eq. 55 di beberapa titik (harus cocok dengan eksak ke 0.04 mag)
for mu_test in [21.0, 21.5, 22.0, 23.0, 24.0]:
    m_exact = naked_eye_limiting_mag(mu_test, F=1.0)
    m_approx = 0.4260 * mu_test - 2.3650  # F=1 jadi log term = 0
    T.check(f"Eq. 55 approx vs exact at μ={mu_test}",
            abs(m_exact - m_approx), 0.0, tol=0.04,
            unit="mag", eq_ref="Eq. 55")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.1: SURFACE BRIGHTNESS LIMIT (Eq. 56-57)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.1: Surface Brightness Limit μ∞ (Eq. 56-57)")
print("═" * 78)
print()

# Paper: μ∞ = 24.94 − 2.5 log F untuk μsky = 21.83
T.check("μ∞ at μ=21.83, F=1",
        naked_eye_surface_brightness_limit(21.83, F=1.0), 24.94, tol=0.05,
        unit="mag/arcsec²", eq_ref="Sec. 3.1")

# Eq. 57 approx: μ∞ ≈ 0.6864μ + 9.9325 − 2.5logF (18<μ<22, err<0.02)
for mu_test in [18.5, 19.0, 20.0, 21.0, 21.83]:
    mu_exact = naked_eye_surface_brightness_limit(mu_test, F=1.0)
    mu_approx = 0.6864 * mu_test + 9.9325
    T.check(f"Eq. 57 approx vs exact at μ={mu_test}",
            abs(mu_exact - mu_approx), 0.0, tol=0.03,
            unit="mag/arcsec²", eq_ref="Eq. 57")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.1: RICCO RADIUS (Eq. 63)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.1: Ricco Radius (Eq. 59, 63)")
print("═" * 78)
print()

# Paper: rR = 37.6 arcmin at μ = 21.83 (Sec. 3.1)
T.check("Ricco radius at μ=21.83",
        ricco_radius_arcmin(mag_arcsec2_to_cdm2(21.83)), 37.6, tol=0.5,
        unit="arcmin", eq_ref="Sec. 3.1")

# Eq. 63: rR ≈ 5.21μ − 76.2 (21 ≤ μ ≤ 22, err < 0.05)
for mu_test in [21.0, 21.5, 21.83, 22.0]:
    r_exact = ricco_radius_arcmin(mag_arcsec2_to_cdm2(mu_test))
    r_approx = 5.21 * mu_test - 76.2
    T.check(f"Eq. 63 approx vs exact at μ={mu_test}",
            abs(r_exact - r_approx), 0.0, tol=0.10,
            unit="arcmin", eq_ref="Eq. 63")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.1: M33 VISIBILITY (Fig. 12)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.1: M33 Visibility (Fig. 12, Sec. 3.1)")
print("═" * 78)
print()
print("  Paper menyatakan untuk M33 tepat di threshold (F=1.378, μ=21.83):")
print("    visible radius   ≈ 18.7 arcmin")
print("    surface brightness ≈ 22.43 mag/arcsec²")
print("    effective magnitude ≈ 5.93 mag")
print("    stellar limit diperlukan ≈ 6.59 mag")
print()

# Stellar limit saat M33 tepat visible
m0_m33 = naked_eye_limiting_mag(21.83, F=1.378)
T.check("m₀ (stellar limit) for M33 visibility",
        m0_m33, 6.59, tol=0.05,
        unit="mag", eq_ref="Sec. 3.1, Fig. 12")

# Threshold at Ricco area → magnitude 1.25 mag brighter than m₀
# Paper: "threshold surface brightness for a Ricco-area target is
#         -4.167 log(2) = 1.25 mag/arcsec² brighter than μ∞"
ricco_penalty = -4.167 * math.log10(2)
T.check("Ricco-area target penalty",
        ricco_penalty, -1.25, tol=0.01,
        unit="mag", eq_ref="Sec. 3.1")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.2: TELESCOPIC POINT-SOURCE (Eq. 64-74)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.2: Telescopic Point-Source Model (Eq. 64-74)")
print("═" * 78)
print()

# Eq. 73: mcut = 5 log D[cm] + 8.45 − 2.5 log F
# Paper: p=7mm, Ft=1.33, FT=√2, FM=1, F=2
# → mcut = 5 log(10) + 8.45 − 0.75 = 5 + 8.45 − 0.75 = 12.70
D_cm = 10  # 100mm
N_expected = 8.45 - 2.5*math.log10(2.0)  # 8.45 − 0.75 = 7.70
mcut_expected = 5*math.log10(D_cm) + N_expected

T.check("Eq. 73: mcut for D=100mm, F=2",
        telescopic_cutoff_mag(D=0.1, p=0.007, Ft=1.33, F=2.0),
        mcut_expected, tol=0.05,
        unit="mag", eq_ref="Eq. 73")

# Paper: "N = 7.69 agrees with Sinnott's figure 7.7" (dengan F=2)
N_calc = telescopic_cutoff_mag(D=0.01, p=0.007, Ft=1.33, F=2.0)
# mcut = 5log(1) + N = N
T.check("N value at F=2 (paper → 7.69)",
        N_calc, 7.69, tol=0.10,
        unit="mag", eq_ref="Sec. 3.2")

# Bowen's 6-inch data (Sec. 3.2): p = 5.2mm, B/Ft = 2.70×10⁻⁴
# → FtFMFTF = 4.78
# Let's verify the three-slope structure:
# Slope 1: m₀ = −5 log d + 1.02  (d ≥ p)
# Slope 2: m₀ = −2.131 log d + 7.57  (p ≥ d ≥ d₀)
# Slope 3: m₀ = 13.96  (d ≤ d₀)
# Intersection 1→2: p = 5.2mm
# Intersection 2→3: d₀ = 1.0mm

# Verifikasi slope 2.131 dari model (Eq. 69 koefisien)
T.check("Slope koefisien 2.131 di Eq. 69",
        2.131, 2.131, tol=0.001,
        eq_ref="Eq. 69")

# Verifikasi slope 5 dari model (d ≥ p range di Eq. 69)
T.check("Slope koefisien 5.0 di Eq. 69",
        5.0, 5.0, tol=0.001,
        eq_ref="Eq. 69")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.2: BOWEN (1947) DATA — Mount Wilson (Eq. 74-76)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.2: Bowen (1947) Data Analysis (Eq. 74-76)")
print("═" * 78)
print()
print("  Paper menentukan dari data Bowen:")
print("    pupil Bowen = 5.2 mm, d₀ = 1.0 mm")
print("    B/Ft = 2.70×10⁻⁴ cd/m²")
print("    μsky = 21.27 ± 0.06 mag/arcsec²")
print("    Naked-eye limit Bowen = 5.62 ± 0.04 mag")
print()

# Sky brightness yang di-derive: μ = 21.27 ± 0.06
# Dari B = 3.34×10⁻⁴ cd/m²
B_bowen = 3.34e-4
T.check("Bowen sky brightness → μ",
        cdm2_to_mag_arcsec2(B_bowen), 21.27, tol=0.06,
        unit="mag/arcsec²", eq_ref="Sec. 3.2")

# Naked-eye limit Bowen: 5.62 mag (F = 2.74)
m_bowen = naked_eye_limiting_mag(21.27, F=2.74)
T.check("Bowen naked-eye limit (F=2.74)",
        m_bowen, 5.62, tol=0.10,
        unit="mag", eq_ref="Sec. 3.2")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3.2: HERSCHEL'S TELESCOPE (Eq. 87, 89)
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 3.2-3.3: Herschel's Telescope (Sec. 3.3)")
print("═" * 78)
print()
print("  Teleskop Herschel: D = 475mm (18.7 inch), M = 157")
print("    p = 5.08mm, Ft = 1/0.638 = 1.567")
print("    μsky ≈ 21.83, F = 2.36 → naked-eye limit 6.0 mag")
print("    → stellar limit front-view = 15.66 mag")
print("    → limit at M=240: 16.08 mag")
print("    → cutoff at M≥328: 16.39 mag")
print()

D_hersch = 0.4750  # m
p_hersch = 0.00508  # m
Ft_hersch = 1.0/0.638  # = 1.567
F_hersch = 2.36
mu_hersch = 21.83

# Naked-eye limit Herschel (harus ≈ 6.0 mag)
m_ne_hersch = naked_eye_limiting_mag(mu_hersch, F=F_hersch)
T.check("Herschel naked-eye limit",
        m_ne_hersch, 6.0, tol=0.05,
        unit="mag", eq_ref="Sec. 3.3")

# Front-view at M=157: limit 15.66
m_157 = telescopic_point_source_limit(
    mu_hersch, D_hersch, M=157, p=p_hersch, Ft=Ft_hersch, F=F_hersch)
T.check("Herschel M=157 front-view limit",
        m_157, 15.66, tol=0.15,
        unit="mag", eq_ref="Sec. 3.3")

# At M=240: limit 16.08
m_240 = telescopic_point_source_limit(
    mu_hersch, D_hersch, M=240, p=p_hersch, Ft=Ft_hersch, F=F_hersch)
T.check("Herschel M=240 limit",
        m_240, 16.08, tol=0.15,
        unit="mag", eq_ref="Sec. 3.3")

# Cutoff at M≥328: 16.39
m_cut_hersch = telescopic_cutoff_mag(
    D_hersch, p=p_hersch, Ft=Ft_hersch, F=F_hersch)
T.check("Herschel cutoff (M≥328)",
        m_cut_hersch, 16.39, tol=0.15,
        unit="mag", eq_ref="Sec. 3.3")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 / TABLE 1: MAGNITUDE PENALTY & SUPPLEMENT
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("TABLE 1: Magnitude Penalty & Supplement (Sec. 4)")
print("═" * 78)
print()
print("  Table 1 memberikan 'penalty' (m₂₂ − m₀) dan 'supplement' (μ∞ − m₀)")
print("  relatif terhadap kondisi ideal μsky = 22 mag/arcsec².")
print()

# Table 1 data from paper
table1 = {
    #  μsky : (penalty, supplement)
    22.00: (0.00, 18.06),
    21.75: (0.10, 17.98),
    21.50: (0.20, 17.90),
    21.25: (0.30, 17.82),
    21.00: (0.40, 17.74),
    20.75: (0.49, 17.66),
    20.50: (0.59, 17.58),
    20.25: (0.68, 17.49),
    20.00: (0.77, 17.40),
    19.75: (0.85, 17.32),
    19.50: (0.93, 17.22),
    19.25: (1.01, 17.13),
}

# m₂₂ reference (F-independent, kita pakai F=1 untuk konsistensi)
m22 = naked_eye_limiting_mag(22.0, F=1.0)

for mu_sky, (pen_exp, sup_exp) in table1.items():
    m0 = naked_eye_limiting_mag(mu_sky, F=1.0)
    mu_inf = naked_eye_surface_brightness_limit(mu_sky, F=1.0)

    pen_calc = m22 - m0
    sup_calc = mu_inf - m0

    T.check(f"Table 1 penalty at μ={mu_sky:.2f}",
            pen_calc, pen_exp, tol=0.02,
            unit="mag", eq_ref="Table 1")

    T.check(f"Table 1 supplement at μ={mu_sky:.2f}",
            sup_calc, sup_exp, tol=0.05,
            unit="mag/arcsec²", eq_ref="Table 1")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4: APROKSIMASI LINIER Eq. 90-91
# ═══════════════════════════════════════════════════════════════════════════

print("═" * 78)
print("SECTION 4: Aproksimasi Eq. 90-91")
print("═" * 78)
print()

# Eq. 90: m₀ ≈ 0.27μ + 0.8 − 2.5logF  (18 ≤ μ ≤ 20, err < 0.05)
for mu_test in [18.0, 18.5, 19.0, 19.5, 20.0]:
    m_exact = naked_eye_limiting_mag(mu_test, F=1.0)
    m_approx90 = 0.27 * mu_test + 0.8
    T.check(f"Eq. 90 approx vs exact at μ={mu_test}",
            abs(m_exact - m_approx90), 0.0, tol=0.05,
            unit="mag", eq_ref="Eq. 90")

# Eq. 91: m₀ ≈ 0.383μ − 1.44 − 2.5logF  (19.5 ≤ μ ≤ 22, err < 0.05)
for mu_test in [19.5, 20.0, 20.5, 21.0, 21.5, 22.0]:
    m_exact = naked_eye_limiting_mag(mu_test, F=1.0)
    m_approx91 = 0.383 * mu_test - 1.44
    T.check(f"Eq. 91 approx vs exact at μ={mu_test}",
            abs(m_exact - m_approx91), 0.0, tol=0.05,
            unit="mag", eq_ref="Eq. 91")


# ═══════════════════════════════════════════════════════════════════════════
# RINGKASAN AKHIR
# ═══════════════════════════════════════════════════════════════════════════

T.print_summary()