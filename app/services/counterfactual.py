from __future__ import annotations

from itertools import product
from typing import Any, Dict, List


_RISK_RANK = {"LOW": 0, "INTERMEDIARY": 1, "HIGH": 2}
_ACTIVITY_ORDER = ("Low", "Moderate", "High")
_COST = {"weight": 0.5, "activity": 1.0, "smoking": 2.0}


def _activity_options(current: str) -> List[str]:
    if current not in _ACTIVITY_ORDER:
        return [current]
    idx = _ACTIVITY_ORDER.index(current)
    return list(_ACTIVITY_ORDER[idx:])


def _smoking_options(current: str) -> List[str]:
    if current == "Y":
        return ["Y", "N"]
    return ["N"]


def _weight_options(current_weight: float) -> List[float]:
    deltas = (-10, -6, -3, 0, 3)
    options = []
    for d in deltas:
        v = current_weight + d
        if 40 <= v <= 200:
            options.append(round(v, 1))
    return options


def _cost(orig: Dict[str, Any], cand: Dict[str, Any]) -> float:
    c = abs(cand["weight"] - orig["weight"]) * _COST["weight"]
    if cand["activity"] != orig["activity"]:
        c += _COST["activity"]
    if cand["smoking"] != orig["smoking"]:
        c += _COST["smoking"]
    return c


def _describe(orig: Dict[str, Any], cand: Dict[str, Any]) -> str:
    parts = []
    delta = cand["weight"] - orig["weight"]
    if abs(delta) >= 1:
        if delta < 0:
            parts.append(f"lose about {abs(delta):.0f} kg")
        else:
            parts.append(f"gain about {delta:.0f} kg")
    if cand["activity"] != orig["activity"]:
        parts.append(f"switch to {cand['activity'].lower()} activity")
    if cand["smoking"] != orig["smoking"] and cand["smoking"] == "N":
        parts.append("stop smoking")

    if not parts:
        return "no specific change"
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def search_counterfactuals(input_data: Dict[str, Any], current_class: str,
                           model_service, max_results: int = 2) -> List[Dict[str, Any]]:
    current_rank = _RISK_RANK.get((current_class or "").upper(), 0)
    if current_rank == 0:
        return []

    try:
        orig_weight = float(input_data["Weight (kg)"])
    except (KeyError, TypeError, ValueError):
        return []

    orig = {
        "weight": orig_weight,
        "activity": input_data.get("Physical Activity Level"),
        "smoking": input_data.get("Smoking Status"),
    }

    weights = _weight_options(orig["weight"])
    activities = _activity_options(orig["activity"])
    smokings = _smoking_options(orig["smoking"])

    payloads = []
    metas = []
    for w, a, s in product(weights, activities, smokings):
        if w == orig["weight"] and a == orig["activity"] and s == orig["smoking"]:
            continue
        payload = dict(input_data)
        payload["Weight (kg)"] = w
        payload["Physical Activity Level"] = a
        payload["Smoking Status"] = s
        payloads.append(payload)
        metas.append({"weight": w, "activity": a, "smoking": s})

    if not payloads:
        return []

    try:
        preds = model_service.predict_batch(payloads)
    except Exception:
        return []

    results = []
    for meta, pred in zip(metas, preds):
        pred_name = (pred.get("pred_class_name") or "").upper()
        pred_rank = _RISK_RANK.get(pred_name, current_rank)
        if pred_rank >= current_rank:
            continue

        new_orig_class_p = None
        for p in pred.get("proba") or []:
            if (p.get("class") or "").upper() == (current_class or "").upper():
                new_orig_class_p = p.get("p")
                break

        results.append({
            "description": _describe(orig, meta),
            "new_class": pred.get("pred_class_name"),
            "new_class_p": pred.get("pred_confidence"),
            "original_class_p_new": new_orig_class_p,
            "cost": _cost(orig, meta),
        })

    results.sort(key=lambda r: r["cost"])

    seen = set()
    dedup = []
    for r in results:
        if r["description"] in seen:
            continue
        seen.add(r["description"])
        dedup.append(r)

    return dedup[:max_results]
