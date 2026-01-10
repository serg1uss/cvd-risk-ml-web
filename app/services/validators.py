from __future__ import annotations

from typing import Dict, Any, Tuple


def validate_quick_form(form: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    errors: Dict[str, str] = {}
    data: Dict[str, Any] = {}

    def get_float(key: str, min_v=None, max_v=None):
        raw = form.get(key, "").strip()
        if raw == "":
            errors[key] = "Required"
            return None
        try:
            val = float(raw)
        except ValueError:
            errors[key] = "Must be a number"
            return None
        if min_v is not None and val < min_v:
            errors[key] = f"Must be ≥ {min_v}"
            return None
        if max_v is not None and val > max_v:
            errors[key] = f"Must be ≤ {max_v}"
            return None
        return val

    def get_int(key: str, min_v=None, max_v=None):
        raw = form.get(key, "").strip()
        if raw == "":
            errors[key] = "Required"
            return None
        try:
            val = int(raw)
        except ValueError:
            errors[key] = "Must be an integer"
            return None
        if min_v is not None and val < min_v:
            errors[key] = f"Must be ≥ {min_v}"
            return None
        if max_v is not None and val > max_v:
            errors[key] = f"Must be ≤ {max_v}"
            return None
        return val

    age = get_int("Age", 1, 120)
    height = get_float("Height (cm)", 50, 250)
    weight = get_float("Weight (kg)", 20, 300)

    pal = form.get("Physical Activity Level", "").strip()
    smoke = form.get("Smoking Status", "").strip()
    fh = form.get("Family History of CVD", "").strip()

    allowed_pal = {"Low", "Moderate", "High"}
    allowed_yn = {"Y", "N"}

    if pal not in allowed_pal:
        errors["Physical Activity Level"] = "Choose an option"
    if smoke not in allowed_yn:
        errors["Smoking Status"] = "Choose Y or N"
    if fh not in allowed_yn:
        errors["Family History of CVD"] = "Choose Y or N"

    if not errors:
        data["Age"] = age
        data["Height (cm)"] = height
        data["Weight (kg)"] = weight
        data["Physical Activity Level"] = pal
        data["Smoking Status"] = smoke
        data["Family History of CVD"] = fh

    return data, errors
