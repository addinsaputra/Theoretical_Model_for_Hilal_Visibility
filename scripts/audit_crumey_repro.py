"""Read-only probes of the active, repaired Crumey implementation.

The audit document records the pre-repair baseline. These current-code probes
complement tests; neither numerical agreement nor probes validate human hilal
visibility against CCD observations.
"""

import _bootstrap  # noqa: F401
import ast
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import hilal_visibility.models.crumey as crumey
from hilal_visibility.models.telescope import TelescopeVisibilityModel
from hilal_visibility.calculator import HilalVisibilityCalculator


def emit(case, **values):
    print(json.dumps({"case": case, **values}, ensure_ascii=False))


source_path = ROOT / "src" / "hilal_visibility" / "calculator.py"
tree = ast.parse(source_path.read_text(encoding="utf-8-sig"))
original_class = next(
    node for node in tree.body
    if isinstance(node, ast.ClassDef) and node.name == "HilalVisibilityCalculator"
)
# This method needs no location, weather or ephemeris calculation.
probe = object.__new__(HilalVisibilityCalculator)

for method_name, callee in (
    ("hitung_visibilitas_pada_waktu", "hitung_visibilitas_teleskop"),
    ("jalankan_perhitungan_lengkap", "cari_visibilitas_optimal"),
):
    method = next(n for n in original_class.body
                  if isinstance(n, ast.FunctionDef) and n.name == method_name)
    call = next(n for n in ast.walk(method)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == callee)
    emit("optimal_parameter_forwarding", caller=method_name, callee=callee,
         line=call.lineno, keyword_names=[k.arg for k in call.keywords])

position = {"elongation": 8.0, "moon_semidiameter": .26}
for name, options in (
    ("default", {}),
    ("custom", {"transmission": .7, "n_surfaces": 10,
                "central_obstruction": 40, "observer_age": 70}),
):
    values = probe.hitung_visibilitas_teleskop(
        10, 1000, position, aperture=100, magnification=50, **options
    )
    emit("optical_parameters", configuration=name, C_obj=values[2],
         C_th=values[3], delta_m=values[4])

for background in (1e-5, 1e-7):
    threshold = crumey.contrast_threshold(crumey.arcmin2_to_sr(10), background)
    emit("background_floor", B_cd_m2=background, C_th=threshold,
         implicit_increment_threshold=background * threshold)

try:
    values = crumey.telescopic_extended_target(
        10, crumey.cdm2_to_mag_arcsec2(100), .1, 50
    )
    emit("twilight_extended_helper", result=values)
except (TypeError, ValueError) as error:
    emit("twilight_extended_helper", error=f"{type(error).__name__}: {error}")

for name, values in (
    ("naked_eye", crumey.naked_eye_extended_target(
        10, crumey.cdm2_to_mag_arcsec2(.01), F=2)),
    ("telescope_below_floor", crumey.telescopic_extended_target(
        10, crumey.cdm2_to_mag_arcsec2(1e-4), .066, 100)),
):
    emit("magnitude_surface_brightness_identity", helper=name,
         m_lim=values["m_lim"], mu_lim=values["mu_lim"],
         residual_mag=values["mu_lim"] - values["m_lim"]
         - 2.5 * math.log10(3600 * 10))

position = {"elongation": 10.0, "moon_semidiameter": .25}
for age in (22, 65):
    values = probe.hitung_visibilitas_teleskop(
        crumey.cdm2_to_nL(.01), crumey.cdm2_to_nL(1), position,
        aperture=66, magnification=50, observer_age=age
    )
    emit("age_with_fixed_field_factor", age=age, C_th=values[3], delta_m=values[4])

factors = TelescopeVisibilityModel().calculate_factors(D=200, Ds=80, M=10)
scalar = (min(factors["exit_pupil"], factors["De"]) / factors["De"]) ** 2 / factors["Ft"]
annular = .95 ** 6 * max(min(200 / 10, factors["De"]) ** 2 - (80 / 10) ** 2, 0) / factors["De"] ** 2
emit("clipped_annular_pupil", eye_pupil_mm=factors["De"],
     secondary_shadow_mm=80 / 10, scalar_transmission=scalar,
     centered_annular_transmission=annular,
     active_transmission=factors["surface_brightness_factor"])
