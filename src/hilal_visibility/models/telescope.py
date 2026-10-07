"""
Optical surface-brightness transfer for visual telescopic extended sources.

The fallback age/pupil relation and historical diagnostic factors are retained
from the Schaefer implementation. Active source/background transfer uses a
centred annular pupil geometry; this excludes diffraction and pupil decentring.

For an extended source, the same optical factor g dims excess luminance and
sky background. Monocular sensitivity is applied by the Crumey threshold API.
"""

import math


class TelescopeVisibilityModel:
    """
    Model koreksi visibilitas teleskop berdasarkan Schaefer (1990).
    
    Faktor-faktor yang dihitung:
    - Fb: Faktor Binokular (sensitivitas 2 mata vs 1 mata)
    - Ft: Faktor Transmisi Teleskop
    - Fp: Faktor Pupil
    - Fa: Faktor Bukaan (Aperture)
    - Fm: Faktor Magnifikasi (untuk sky brightness)
    - Fr: Faktor Resolusi (untuk extended source)
    """
    
    def __init__(self):
        """
        Inisialisasi model dengan konstanta-konstanta default.
        """
        # [cite_start]1. Fb: Faktor Binokular (Binocular Factor) [cite: 267]
        # Sensitivitas 2 mata vs 1 mata (teleskop monokular).
        self.Fb = math.sqrt(2)
    
    def calculate_pupil_diameter(self, age: float) -> float:
        """
        Menghitung estimasi pupil gelap berdasarkan usia, bukan adaptasi senja.
        Ini bukan model sensitivitas mata yang terkalibrasi terhadap usia.
        
        Parameters:
        -----------
        age : float
            Usia pengamat (dalam tahun)
            
        Returns:
        --------
        float
            Diameter pupil mata (dalam mm)
            
        Formula:
        --------
        De = 7 * exp(-0.5 * (age/100)^2)
        """
        if not math.isfinite(age) or age < 0:
            raise ValueError("Usia harus non-negatif dan finite")
        exponent = -0.5 * (age / 100.0) ** 2
        diameter = 7.0 * math.exp(exponent)
        if diameter == 0:
            raise ValueError("Usia menghasilkan diameter pupil nol")
        return diameter
    
    def calculate_factors(
        self,
        D: float,
        Ds: float,
        M: float,
        De: float = None,
        age: float = 22,
        t1: float = 0.95,
        n: int = 6,
        theta: float = 3.0
    ) -> dict:
        """
        Menghitung variabel-variabel koreksi optik teleskop.
        
        Parameters:
        -----------
        D     : float
            Aperture/Diameter teleskop (dalam mm)
        Ds    : float
            Diameter halangan cermin sekunder (dalam mm)
            Untuk refraktor, gunakan Ds = 0
        M     : float
            Magnifikasi / Perbesaran
        De    : float, optional
            Diameter pupil mata pengamat (dalam mm)
            Jika None, dihitung dari usia pengamat
        age   : float, default=22
            Usia untuk estimasi pupil saja, digunakan jika De tidak diberikan
        t1    : float, default=0.95
            Transmisi per permukaan optik (0-1)
        n     : int, default=6
            Jumlah permukaan optik (lensa/cermin)   
        theta : float, default=3.0
            Ukuran seeing disk (dalam detik busur / arcseconds)
        
        Returns:
        --------
        dict
            Dictionary berisi nilai-nilai faktor koreksi:
            - Fb: Faktor Binokular
            - Ft: Faktor Transmisi Teleskop  
            - Fp: Faktor Pupil
            - Fa: Faktor Bukaan
            - Fm: Faktor Magnifikasi (untuk sky brightness)
            - Fr: Faktor Resolusi (untuk extended source)
            - surface_brightness_factor: optical g for sky AND target excess
            - FB, FI: compatibility aliases for g
            - optically_blocked: pupil lies inside the secondary shadow
            Other factors are retained as historical diagnostic components.
        """
        # Domain optik: invalid inputs must not silently become a different setup.
        if not math.isfinite(D) or D <= 0:
            raise ValueError("Diameter teleskop harus positif dan finite")
        if not math.isfinite(M) or M <= 0:
            raise ValueError("Magnifikasi harus positif dan finite")
        if not math.isfinite(Ds) or not (0 <= Ds < D):
            raise ValueError("Obstruksi harus memenuhi 0 <= Ds < D")
        if not math.isfinite(t1) or not (0 < t1 <= 1):
            raise ValueError("Transmisi t1 harus antara 0 dan 1")
        if isinstance(n, bool) or not math.isfinite(n) or n < 0 or int(n) != n:
            raise ValueError("Jumlah permukaan harus bilangan bulat non-negatif")
        if not math.isfinite(age) or age < 0:
            raise ValueError("Usia harus non-negatif dan finite")
        if not math.isfinite(theta) or theta < 0:
            raise ValueError("Seeing harus non-negatif dan finite")
        
        # Hitung diameter pupil jika tidak diberikan
        if De is None:
            De = self.calculate_pupil_diameter(age)
        if not math.isfinite(De) or De <= 0:
            raise ValueError("Diameter pupil harus positif dan finite")
        
        # --- Faktor-faktor individu ---
        
        # [cite_start]2. (Ds/D)^2: Fraksi Kehilangan Cahaya Obstruksi [cite: 282]
        # Untuk refraktor (Ds = 0), tidak ada obstruksi cermin sekunder → (Ds/D)^2 = 0
        # Untuk reflektor (Ds > 0), terdapat obstruksi cermin sekunder → (Ds/D)^2 > 0
        obstruction_fraction = (Ds / D) ** 2
        
        # [cite_start]3. Ft: Faktor Transmisi Teleskop [cite: 287]
        # Rumus: Ft = 1 / (t1^n * (1 - (Ds/D)^2))
        transmission = t1 ** int(n)
        if transmission == 0:
            raise ValueError("Transmisi total mengalami underflow; periksa t1 dan n")
        Ft = 1.0 / (transmission * (1.0 - obstruction_fraction))
        
        # [cite_start]4. Fp: Faktor Pupil [cite: 300-302]
        # Exit pupil teleskop = D / M
        # Jika De < exit_pupil, maka Fp = (D / (M * De))^2, else 1.0
        exit_pupil_telescope = D / M
        secondary_exit_pupil = Ds / M
        # Geometri pupil annular terpusat, tanpa difraksi/desentrasi. Ketika
        # exit pupil melampaui pupil mata, bayangan sekunder ikut terpotong.
        admitted_diameter = min(exit_pupil_telescope, De)
        admitted_area = max(admitted_diameter**2 - secondary_exit_pupil**2, 0.0)
        full_exit_area = exit_pupil_telescope**2 - secondary_exit_pupil**2
        admitted_fraction = admitted_area / full_exit_area
        Fp = 1.0 / admitted_fraction if admitted_fraction > 0 else float('inf')
        surface_factor = transmission * admitted_area / De**2
        
        # [cite_start]5. Fa: Faktor Bukaan (Aperture Factor) [cite: 307]
        # Rumus: Fa = (De / D)^2
        Fa = (De / D) ** 2
        
        # [cite_start]6. Fm: Faktor Magnifikasi Latar Belakang [cite: 309]
        # Pengurangan brightness langit akibat perbesaran.
        # Rumus: Fm = 1/M^2
        Fm = 1.0 / (M ** 2)
        
        # [cite_start]7. Fr: Faktor Resolusi Mata [cite: 319-320]
        # Rumus: Fr = sqrt(2 * theta * M / 900) jika > 900", else 1.0
        apparent_size = 2.0 * theta * M
        if apparent_size > 900:
            Fr = math.sqrt(apparent_size / 900.0)
        else:
            Fr = 1.0
        
        # --- Faktor gabungan ---
        
        # Extended source: optical throughput dims target and background equally.
        # Monocular sensitivity belongs on the visual threshold, never in g.
        # Fb/Fa/Fm/Fr are retained as historical diagnostic components only.
        FB = FI = surface_factor
        
        return {
            "Fb": self.Fb,
            "Ft": Ft,
            "Fp": Fp,
            "Fa": Fa,
            "Fm": Fm,
            "Fr": Fr,
            "FB": FB,
            "FI": FI,
            "De": De,
            "exit_pupil": exit_pupil_telescope,
            "obstruction_fraction": obstruction_fraction,
            "transmission": transmission,
            "secondary_exit_pupil": secondary_exit_pupil,
            "admitted_pupil_fraction": admitted_fraction,
            "surface_brightness_factor": surface_factor,
            "optically_blocked": admitted_area == 0,
        }
    
    def apply_corrections(
        self,
        B_0: float,
        I_0: float,
        D: float,
        Ds: float,
        M: float,
        De: float = None,
        age: float = 30,
        t1: float = 0.95,
        n: int = 4,
        theta: float = 2.0
    ) -> dict:
        """
        Menerapkan koreksi teleskop pada sky brightness dan luminansi hilal.
        
        Parameters:
        -----------
        B_0 : float
            Sky brightness asli (naked-eye) dalam nL (nanoLambert)
        I_0 : float
            Luminansi hilal asli (naked-eye) dalam nL
        D   : float
            Aperture/Diameter teleskop (dalam mm)
        Ds  : float
            Diameter halangan cermin sekunder (dalam mm)
        M   : float
            Magnifikasi / Perbesaran
        De  : float, optional
            Diameter pupil mata pengamat (dalam mm)
        age : float, default=30
            Usia pengamat (dalam tahun)
        t1  : float, default=0.95
            Transmisi per permukaan optik
        n   : int, default=4
            Jumlah permukaan optik
        theta : float, default=2.0
            Ukuran seeing disk (dalam arcseconds)
        
        Returns:
        --------
        dict
            Dictionary berisi:
            - B_eff: Sky brightness terkoreksi
            - I_eff: Luminansi hilal terkoreksi
            - delta_m: Kontras magnitude (visibilitas)
            - factors: Dictionary faktor-faktor koreksi
        """
        if not math.isfinite(B_0) or B_0 <= 0:
            raise ValueError("Sky brightness harus positif dan finite")
        if not math.isfinite(I_0) or I_0 < 0:
            raise ValueError("Luminansi excess harus non-negatif dan finite")
        # Hitung faktor-faktor koreksi
        factors = self.calculate_factors(D, Ds, M, De, age, t1, n, theta)
        
        FB = factors["FB"]
        FI = factors["FI"]
        
        # Identical optical surface-brightness factor for target and sky.
        # delta_m below describes excess/background contrast, not a detection
        # decision; use the Crumey threshold API for visibility.
        B_eff = B_0 * FB
        I_eff = I_0 * FI
        
        # Hitung delta_m (kontras magnitude)
        # delta_m = 2.5 * log10(I_eff / B_eff)
        if I_eff > 0 and B_eff > 0:
            delta_m = 2.5 * math.log10(I_eff / B_eff)
        else:
            delta_m = float('-inf')
        
        return {
            "B_0": B_0,
            "I_0": I_0,
            "B_eff": B_eff,
            "I_eff": I_eff,
            "delta_m": delta_m,
            "factors": factors
        }


# --- Fungsi-fungsi utilitas untuk kompatibilitas ---

def extended_surface_correction_factor(
    B: float,
    aperture: float,
    magnification: float,
    central_obstruction: float,
    transmission_per_surface: float,
    n_surfaces: int,
    age: float,
    colour_index: float = 0.0
) -> float:
    """
    Menghitung faktor koreksi gabungan untuk extended source.
    
    Fungsi ini merupakan wrapper untuk kompatibilitas dengan
    kode yang sudah ada.
    
    Parameters:
    -----------
    B : float
        Sky brightness (tidak digunakan, untuk kompatibilitas)
    aperture : float
        Diameter teleskop (mm)
    magnification : float
        Perbesaran teleskop
    central_obstruction : float
        Diameter obstruksi sekunder (mm)
    transmission_per_surface : float
        Transmisi per permukaan optik (0-1)
    n_surfaces : int
        Jumlah permukaan optik
    age : float
        Usia pengamat (tahun)
    colour_index : float
        Indeks warna (tidak digunakan, untuk kompatibilitas)
    
    Returns:
    --------
    float
        Faktor koreksi total untuk extended source
    """
    model = TelescopeVisibilityModel()
    factors = model.calculate_factors(
        D=aperture,
        Ds=central_obstruction,
        M=magnification,
        age=age,
        t1=transmission_per_surface,
        n=n_surfaces
    )
    return factors["surface_brightness_factor"]


def calculate_telescope_visibility(
    B_sky: float,
    L_hilal: float,
    aperture: float,
    magnification: float,
    central_obstruction: float = 0.0,
    transmission: float = 0.95,
    n_surfaces: int = 6,
    age: float = 22,
    seeing: float = 3.0
) -> dict:
    """
    Fungsi praktis untuk menghitung visibilitas hilal dengan teleskop.
    
    Parameters:
    -----------
    B_sky : float
        Kecerahan langit (nL)
    L_hilal : float
        Luminansi hilal (nL)
    aperture : float
        Diameter teleskop (mm)
    magnification : float
        Perbesaran teleskop
    central_obstruction : float
        Diameter obstruksi sekunder (mm), default 0 untuk refraktor
    transmission : float
        Transmisi per permukaan optik, default 0.95
    n_surfaces : int
        Jumlah permukaan optik, default 6
    age : float
        Usia pengamat (tahun), default 22
    seeing : float
        Ukuran seeing disk (arcseconds), default 3.0
    
    Returns:
    --------
    dict
        Hasil perhitungan visibilitas dengan teleskop
    """
    model = TelescopeVisibilityModel()
    return model.apply_corrections(
        B_0=B_sky,
        I_0=L_hilal,
        D=aperture,
        Ds=central_obstruction,
        M=magnification,
        age=age,
        t1=transmission,
        n=n_surfaces,
        theta=seeing
    )


# --- Contoh Penggunaan ---
if __name__ == "__main__":
    print("=" * 60)
    print("KOREKSI VISIBILITAS TELESKOP (Model Schaefer 1990)")
    print("=" * 60)
    
    # Inisialisasi model
    model = TelescopeVisibilityModel()
    
    # --- Contoh 1: Hitung faktor-faktor koreksi ---
    print("\n[1] Contoh perhitungan faktor koreksi teleskop refraktor:")
    print("-" * 60)
    
    # Parameter teleskop refraktor
    D_val = 100.0      # Diameter teleskop 150 mm
    Ds_val = 0.0       # Diameter sekunder 0 mm (refraktor)
    M_val = 50.0       # Perbesaran 50x
    age_val = 22       # Usia pengamat 22 tahun
    t1_val = 0.95      # Transmisi per lensa/cermin 95%
    n_val = 6          # 6 permukaan optik (2 lensa objektif + 2 eyepiece)
    theta_val = 3.0    # Seeing 3 detik busur
    
    # Hitung faktor
    factors = model.calculate_factors(
        D=D_val, Ds=Ds_val, M=M_val, 
        age=age_val, t1=t1_val, n=n_val, theta=theta_val
    )
    
    print(f"Parameter Teleskop:")
    print(f"  Diameter (D)         : {D_val} mm")
    print(f"  Obstruksi (Ds)       : {Ds_val} mm")
    print(f"  Perbesaran (M)       : {M_val}x")
    print(f"  Transmisi (t1)       : {t1_val}")
    print(f"  Jumlah permukaan (n) : {n_val}")
    print(f"  Seeing (theta)       : {theta_val} arcsec")
    print(f"\nParameter Pengamat:")
    print(f"  Usia                 : {age_val} tahun")
    print(f"  Diameter pupil (De)  : {factors['De']:.2f} mm")
    print(f"  Exit pupil teleskop  : {factors['exit_pupil']:.2f} mm")
    
    print(f"\nFaktor-faktor Koreksi:")
    print(f"  Fb (Binokular)       : {factors['Fb']:.4f}")
    print(f"  Ft (Transmisi)       : {factors['Ft']:.4f}")
    print(f"  Fp (Pupil)           : {factors['Fp']:.4f}")
    print(f"  Fa (Aperture)        : {factors['Fa']:.6f}")
    print(f"  Fm (Magnifikasi)     : {factors['Fm']:.6f}")
    print(f"  Fr (Resolusi)        : {factors['Fr']:.4f}")
    
    print(f"\nFaktor Gabungan:")
    print(f"  FB (untuk sky)       : {factors['FB']:.6e}")
    print(f"  FI (untuk hilal)     : {factors['FI']:.6e}")
    
    # --- Contoh 2: Terapkan koreksi pada data aktual ---
    print("\n" + "=" * 60)
    print("[2] Contoh penerapan koreksi pada sky brightness dan luminansi hilal:")
    print("-" * 60)
    
    # Contoh nilai (dalam nanoLambert)
    B_sky = 1000.0    # Sky brightness
    L_hilal = 118189.4561   # Luminansi hilal
    
    result = model.apply_corrections(
        B_0=B_sky, I_0=L_hilal,
        D=D_val, Ds=Ds_val, M=M_val,
        age=age_val, t1=t1_val, n=n_val, theta=theta_val
    )
    

    print(f"Nilai Awal (Naked-eye):")
    print(f"  Sky Brightness (B_0) : {result['B_0']:.2f} nL")
    print(f"  Luminansi Hilal (I_0): {result['I_0']:.2f} nL")
    
    print("\nNilai Terkoreksi (Teleskop):")
    print(f"  B_eff = B_0 * FB     : {result['B_eff']:.4e} nL")
    print(f"  I_eff = I_0 * FI     : {result['I_eff']:.4e} nL")
    
    print("\nVisibilitas:")
    print(f"  Delta m = 2.5*log(I_eff/B_eff) = {result['delta_m']:.4f} mag")
    
    print("\n" + "=" * 60)
