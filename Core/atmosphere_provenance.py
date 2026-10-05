"""Persist raw atmospheric inputs beside CSV and XLSX calculation results."""

import json
from pathlib import Path


def atmosphere_audit_record(name, source, success, hasil=None, error=None):
    hasil = hasil or {}
    return {
        "name": name,
        "source": source,
        "status": "valid" if success else "invalid",
        "error": error,
        "bias_correction_applied": source != "manual",
        "bias_t_celsius": hasil.get("bias_t", 0.0),
        "bias_rh_percentage_points": hasil.get("bias_rh", 0.0),
        "windows": hasil.get("atmosphere_provenance", []),
    }


def save_atmosphere_provenance(filepath, observations):
    """Write <result filename>.atmosphere.json; retain output extension in name.

    Separate CSV and XLSX sidecars cannot overwrite each other's audit records.
    Invalid observations carry their error and no synthetic meteorological data.
    """
    path = Path(str(filepath) + ".atmosphere.json")
    payload = {"schema_version": 1, "observations": list(observations)}
    content = json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2)
    path.write_text(content + "\n", encoding="utf-8")
    return str(path)
