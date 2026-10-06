"""
Modul perhitungan sky brightness dan koefisien ekstingsi atmosfer
berdasarkan model Schaefer (1993) / Bogan.

Modul ini diadaptasi khusus untuk project visibilitas hilal:
- Kontribusi cahaya Bulan (moonlight) DIHILANGKAN karena Bulan adalah
  objek yang diamati, bukan sumber background.
- Limiting magnitude dan Snellen ratio tidak dihitung karena tidak
  diperlukan dalam pipeline visibilitas hilal.

Output utama:
- Sky brightness dalam nanolamberts (kontribusi: dark sky + twilight/daylight)
- Koefisien ekstingsi per band fotometri [U, B, V, R, I]
- Ekstingsi sepanjang garis pandang band V [mag] dan transmisi atmosfer

Referensi:
* Schaefer, B.E. (1993) "Astronomy and the Limits of Vision"
* Implementasi asli JavaScript oleh Victor Reijs / Larry Bogan
"""

from __future__ import annotations
import math
from typing import List, Dict, Any


def transmission_from_extinction_mag(extinction_mag: float) -> float:
    """Transmisi dimensionless dari total kehilangan cahaya [mag]."""
    return 10.0 ** (-0.4 * extinction_mag)


def hitung_sky_brightness(
    month: float,
    year: float,
    altsun: float,
    azisun: float,
    humidity: float,
    temperature: float,
    latitude: float,
    elevation: float,
    alt_objek: float,
) -> Dict[str, Any]:
    """
    Hitung sky brightness dan koefisien ekstingsi atmosfer.

    Menghitung kontribusi dark sky, twilight, dan daylight terhadap
    kecerahan langit, serta koefisien ekstingsi per band fotometri.
    Kontribusi moonlight tidak disertakan (Bulan = objek pengamatan).

    Parameters
    ----------
    month : float
        Bulan pengamatan (1-12).
    year : float
        Tahun pengamatan.
    altsun : float
        Altitude toposentrik Matahari (derajat).
    azisun : float
        Selisih azimuth Matahari - objek (derajat).
    humidity : float
        Kelembaban relatif (%).
    temperature : float
        Suhu udara (°C).
    latitude : float
        Lintang pengamat (derajat).
    elevation : float
        Ketinggian pengamat di atas permukaan laut (meter).
    alt_objek : float
        Altitude toposentrik objek/hilal (derajat).

    Returns
    -------
    Dict[str, Any]
        - ``sky_brightness`` : sky brightness dalam nanolamberts
        - ``K`` : list koefisien ekstingsi per band [U, B, V, R, I]
        - ``DM`` : list total LOS extinction per band [mag]
        - ``k_v`` : koefisien ekstingsi V [mag/airmass], diagnostik
        - ``extinction_mag_v`` : total LOS extinction V [mag]
        - ``transmission_v`` : 10**(-0.4 * DM[2]), dimensionless
        - ``B`` : list sky brightness per band (picoergs)
        - ``diagnostics`` : geometry/airmass, extinction components per band,
          and night/twilight/daylight luminance components for V only
    """
    # ============================================================
    # KONSTANTA FOTOMETRI SCHAEFER/BOGAN
    # ============================================================
    WA = [0.365, 0.44, 0.55, 0.7, 0.9]        # Wavelength tengah per band (mikron)
    OZ = [0.000, 0.000, 0.031, 0.008, 0.000]   # Faktor ekstingsi ozon per band
    WT = [0.074, 0.045, 0.031, 0.020, 0.015]   # Koefisien uap air per band
    BO = [8.0e-14, 7.0e-14, 1.0e-13, 1.0e-13, 3.0e-13]  # Dark sky background per band
    MS = [-25.96, -26.09, -26.74, -27.26, -27.55]  # Solar magnitudes per band
    MO = [-10.93, -10.45, -11.05, -11.90, -12.70]  # Lunar magnitude offset (dipakai di formula daylight)

    # ============================================================
    # KONVERSI SATUAN
    # ============================================================
    RD = math.pi / 180.0

    # ============================================================
    # GEOMETRI: ELONGASI MATAHARI - OBJEK
    # ============================================================
    RS = math.degrees(
        math.acos(
            math.sin(altsun * RD) * math.sin(alt_objek * RD)
            + math.cos(altsun * RD) * math.cos(alt_objek * RD) * math.cos(azisun * RD)
        )
    )

    # ============================================================
    # ZENITH DISTANCE
    # ============================================================
    ZS = 90.0 - altsun       # Zenith distance Matahari
    Z = 90.0 - alt_objek     # Zenith distance objek
    ZZ = Z * RD              # Zenith distance objek (radian)

    # ============================================================
    # VARIABEL MUSIM & LOKASI
    # ============================================================
    LT = latitude * RD
    RA = (month - 3.0) * 30.0 * RD
    SL = 1.0 if latitude >= 0 else -1.0

    # ============================================================
    # AIRMASS
    # ============================================================
    # Gas airmass (Rayleigh scattering) - model Kasten & Young (1989)
    XG = 1.0 / (math.cos(ZZ) + 0.0286 * math.exp(-10.5 * math.cos(ZZ)))

    # Aerosol airmass
    XA = 1.0 / (math.cos(ZZ) + 0.0123 * math.exp(-24.5 * math.cos(ZZ)))

    # Ozone airmass (model spherical, lapisan ozon ~20 km)
    sinZZ = math.sin(ZZ)
    XO = 1.0 / math.sqrt(1.0 - (sinZZ / (1.0 + (20.0 / 6378.0))) ** 2)

    # ============================================================
    # EXTINCTION PER BAND FOTOMETRI [U, B, V, R, I]
    # ============================================================
    K: List[float] = [0.0] * 5
    DM: List[float] = [0.0] * 5
    B: List[float] = [0.0] * 5
    components = []

    for i in range(5):
        # KR: Rayleigh extinction
        KR = 0.1066 * math.exp(-elevation / 8200.0) * (WA[i] / 0.55) ** (-4.0)

        # KA: Aerosol extinction
        rh_fraction = max(humidity / 100.0, 0.01)
        KA = 0.1 * (WA[i] / 0.55) ** (-1.3) * math.exp(-elevation / 1500.0)
        KA *= (1.0 - 0.32 / math.log(rh_fraction)) ** 1.33
        KA *= (1.0 + 0.33 * SL * math.sin(RA))

        # KO: Ozone extinction
        KO = OZ[i] * (3.0 + 0.4 * (LT * math.cos(RA) - math.cos(3.0 * LT))) / 3.0

        # KW: Water vapour extinction
        KW = WT[i] * 0.94 * (humidity / 100.0) * math.exp(temperature / 15.0) * math.exp(-elevation / 8200.0)

        # Total extinction & differential magnitude
        K[i] = KR + KA + KO + KW
        DM[i] = KR * XG + KA * XA + KO * XO + KW * XG
        components.append({'k_R': KR, 'k_A': KA, 'k_O': KO, 'k_W': KW})

    # ============================================================
    # SKY BRIGHTNESS PER BAND
    # ============================================================
    # General airmass untuk sky brightness
    X = 1.0 / (math.cos(ZZ) + 0.025 * math.exp(-11.0 * math.cos(ZZ)))

    # Sun airmass
    XS = 1.0 / (math.cos(ZS * RD) + 0.025 * math.exp(-11.0 * math.cos(ZS * RD)))
    if ZS > 90.0:
        XS = 40.0

    for i in range(5):
        # BN: Dark night sky brightness
        BN = BO[i] * (1.0 + 0.3 * math.cos(6.283 * (year - 1992.0) / 11.0))
        BN *= (0.4 + 0.6 / math.sqrt(max(1.0 - 0.96 * (math.sin(ZZ) ** 2), 1e-6)))
        BN *= 10.0 ** (-0.4 * K[i] * X)

        # BT: Twilight brightness
        HS = 90.0 - ZS
        if K[i] == 0.0 or RS == 0.0:
            BT = 0.0
        else:
            BT = 10.0 ** (-0.4 * (MS[i] - MO[i] + 32.5 - HS - (Z / (360.0 * K[i]))))
            BT *= (100.0 / RS) * (1.0 - 10.0 ** (-0.4 * K[i] * X))

        # BD: Daylight brightness
        C4 = 10.0 ** (-0.4 * K[i] * XS)
        if RS == 0.0:
            FS = 0.0
        else:
            FS = 6.2e7 / (RS ** 2) + 10.0 ** (6.15 - RS / 40.0)
        FS += 10.0 ** 5.36 * (1.06 + (math.cos(RS * RD) ** 2))

        BD = 10.0 ** (-0.4 * (MS[i] - MO[i] + 43.27))
        BD *= (1.0 - 10.0 ** (-0.4 * K[i] * X))
        BD *= (FS * C4 + 440000.0 * (1.0 - C4))

        # Kombinasi: dark sky + min(twilight, daylight)
        # Moonlight TIDAK disertakan (Bulan = objek pengamatan)
        B[i] = (BN + min(BT, BD)) * 1.0e12
        components[i].update({'T_sky': 10.0 ** (-0.4 * K[i] * X),
                             'T_sun': C4})
        if i == 2:  # The luminance conversion is defined for V only.
            components[i].update({'B_night_nL': BN * 1.0e12 / 1.02e-3,
                                  'B_twilight_nL': BT * 1.0e12 / 1.02e-3,
                                  'B_daylight_nL': BD * 1.0e12 / 1.02e-3})

    # ============================================================
    # KONVERSI KE NANOLAMBERTS (band V, index 2)
    # ============================================================
    BL = B[2] / 1.02e-3
    dm_v = DM[2]

    return {
        "sky_brightness": BL,
        "K": K,
        "DM": DM,
        "k_v": K[2],
        "extinction_mag_v": dm_v,
        "transmission_v": transmission_from_extinction_mag(dm_v),
        "B": B,
        "diagnostics": {
            'Z': Z, 'Z_sun': ZS, 'separation_sky_deg': RS,
            'X_G': XG, 'X_A': XA, 'X_O': XO, 'X_sky': X, 'X_sun': XS,
            'bands': dict(zip(('U', 'B', 'V', 'R', 'I'), components)),
        },
    }


__all__ = ["hitung_sky_brightness", "transmission_from_extinction_mag"]


# -----------------------------------------------------------------------------
# Command-line interface
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Hitung sky brightness dan ekstingsi atmosfer (model Schaefer 1993)"
    )
    parser.add_argument("--month", type=float, default=7, help="Bulan pengamatan (1-12)")
    parser.add_argument("--year", type=float, default=2022, help="Tahun pengamatan")
    parser.add_argument("--altsun", type=float, default=-0.3, help="Altitude Matahari (°)")
    parser.add_argument("--azisun", type=float, default=5.037, help="Selisih azimuth Matahari-objek (°)")
    parser.add_argument("--humidity", type=float, default=80.73, help="Kelembaban relatif (%%)")
    parser.add_argument("--temperature", type=float, default=25.27, help="Suhu udara (°C)")
    parser.add_argument("--latitude", type=float, default=-7.0, help="Lintang pengamat (°)")
    parser.add_argument("--elevation", type=float, default=89, help="Ketinggian pengamat (m)")
    parser.add_argument("--alt-objek", type=float, default=4.1, dest="alt_objek", help="Altitude objek/hilal (°)")

    args = parser.parse_args()

    result = hitung_sky_brightness(
        month=args.month,
        year=args.year,
        altsun=args.altsun,
        azisun=args.azisun,
        humidity=args.humidity,
        temperature=args.temperature,
        latitude=args.latitude,
        elevation=args.elevation,
        alt_objek=args.alt_objek,
    )

    print(json.dumps(result, indent=2))
