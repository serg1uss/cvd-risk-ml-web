from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from .services.counterfactual import search_counterfactuals
from .services.model_service import ModelService, ModelConfig
from .services.validators import validate_quick_form

bp = Blueprint("main", __name__)

BASE_DIR = Path(__file__).resolve().parent.parent  # project root
MODEL_PATH = BASE_DIR / "model" / "cvd_catboost_truncated_6f.cbm"

# UI collects these 6 inputs. If the model expects BMI, it will be derived server-side.
CLASS_NAMES = ["HIGH", "INTERMEDIARY", "LOW"]

model_service = ModelService(
    ModelConfig(
        model_path=MODEL_PATH,
        feature_order=None,          # use feature names embedded in the model
        class_names=CLASS_NAMES,
    )
)

_POPULATION_STATS_PATH = BASE_DIR / "model" / "population_stats.json"
_RISK_RANK = {"LOW": 0, "INTERMEDIARY": 1, "HIGH": 2}
_RISK_DISPLAY = {"LOW": "Low", "INTERMEDIARY": "Medium", "HIGH": "High"}

_population_stats_cache = None


def _load_population_stats():
    global _population_stats_cache
    if _population_stats_cache is not None:
        return _population_stats_cache
    try:
        if _POPULATION_STATS_PATH.exists():
            with open(_POPULATION_STATS_PATH, "r", encoding="utf-8") as f:
                _population_stats_cache = json.load(f) or {}
        else:
            _population_stats_cache = {}
    except Exception:
        _population_stats_cache = {}
    return _population_stats_cache


def _age_band(age):
    try:
        a = int(age)
    except (TypeError, ValueError):
        return None
    if a < 30:
        return "20-29"
    if a < 40:
        return "30-39"
    if a < 50:
        return "40-49"
    if a < 60:
        return "50-59"
    return "60+"


def _population_context(age, pred_class_name):
    stats = _load_population_stats()
    if not stats:
        return None
    band = _age_band(age)
    pred = (pred_class_name or "").upper()
    bands = stats.get("by_age_band") or {}
    band_stats = bands.get(band) if band else None
    if not band_stats:
        band_stats = stats.get("overall")
    if not band_stats:
        return None
    pct = band_stats.get(pred)
    if pct is None:
        return None

    pct_int = round(pct * 100)
    label_word = {"LOW": "low", "INTERMEDIARY": "moderate", "HIGH": "high"}.get(pred, pred.lower())
    band_label = f"the {band} age group" if band else "this group"

    all_pcts = list(band_stats.values())
    framing = None
    if all_pcts:
        if pct >= max(all_pcts) - 1e-9:
            framing = "the most common prediction in this group"
        elif pct <= min(all_pcts) + 1e-9:
            framing = "less common at this age"

    base = f"In {band_label}, the model predicts {label_word} risk for about {pct_int}% of profiles."
    if framing:
        base += f" That's {framing}."
    return base


def _is_borderline(proba_list):
    if not proba_list or len(proba_list) < 2:
        return False
    ps = sorted([item.get("p", 0.0) for item in proba_list], reverse=True)
    return (ps[0] - ps[1]) < 0.10


def _compute_gap(proba_list, pred_class_name):
    if not proba_list:
        return None
    pred = (pred_class_name or "").upper()
    by_name = {(p.get("class") or "").upper(): p.get("p", 0.0) for p in proba_list}
    if pred not in by_name:
        return None

    pred_p = by_name[pred]
    pred_rank = _RISK_RANK.get(pred, 1)

    if pred_rank == 0:
        next_name = "INTERMEDIARY"
    elif pred_rank == 2:
        next_name = "INTERMEDIARY"
    else:
        low_p = by_name.get("LOW", 0.0)
        high_p = by_name.get("HIGH", 0.0)
        next_name = "LOW" if low_p >= high_p else "HIGH"

    next_p = by_name.get(next_name)
    if next_p is None:
        return None

    gap_pp = (pred_p - next_p) * 100
    if gap_pp < 5:
        severity = "warning"
    elif gap_pp < 15:
        severity = "normal"
    else:
        severity = "firm"

    return {
        "gap_pp": gap_pp,
        "next_label": _RISK_DISPLAY.get(next_name, next_name),
        "severity": severity,
    }


def _compare_to_reference(input_data, bmi):
    rows = []

    smoking = (input_data.get("Smoking Status") or "").upper()
    rows.append({
        "label": "Smoking",
        "user": "No" if smoking == "N" else "Yes",
        "ideal": "No",
        "marker": "match" if smoking == "N" else "miss",
    })

    activity = input_data.get("Physical Activity Level") or ""
    if activity == "High":
        activity_marker = "match"
    elif activity == "Moderate":
        activity_marker = "partial"
    else:
        activity_marker = "miss"
    rows.append({
        "label": "Activity",
        "user": activity or "—",
        "ideal": "High",
        "marker": activity_marker,
    })

    if bmi is not None:
        if 18.5 <= bmi < 25:
            bmi_marker = "match"
        elif 25 <= bmi < 30:
            bmi_marker = "partial"
        else:
            bmi_marker = "miss"
        bmi_disp = f"{bmi:.1f}"
    else:
        bmi_marker = "unknown"
        bmi_disp = "—"
    rows.append({
        "label": "BMI",
        "user": bmi_disp,
        "ideal": "18.5–25",
        "marker": bmi_marker,
    })

    family = (input_data.get("Family History of CVD") or "").upper()
    rows.append({
        "label": "Family history",
        "user": "No" if family == "N" else "Yes",
        "ideal": "No",
        "marker": "match" if family == "N" else "partial",
    })

    return rows


# Tie-break order when two factors share the same concern/strength score:
# smoking is treated as most impactful, family history (non-modifiable) as least.
_FACTOR_PRIORITY = ("smoking", "bmi", "activity", "family")

_WEAK_FACTOR_PHRASES = {
    "smoking": "smoking",
    "bmi_high": "your weight",
    "bmi_over": "your weight",
    "bmi_under": "nutrition and body weight",
    "activity": "your physical activity level",
    "family": "regular cardiovascular check-ins",
}

_WEAK_FACTOR_ACTIONS = {
    "smoking": "exploring smoking cessation",
    "bmi_high": "working toward a healthier weight",
    "bmi_over": "addressing your weight",
    "bmi_under": "building a balanced nutrition plan",
    "activity": "adding regular physical activity",
    "family": "regular cardiovascular check-ins",
}

_STRONG_HABIT_PHRASES = {
    "smoking": "your non-smoking habits",
    "activity_high": "your active lifestyle",
    "activity_moderate": "your regular activity",
    "bmi": "a healthy weight range",
    "family": "your overall risk profile",
}

_SENTENCE_TEMPLATES = {
    "LOW_WEAK": "Your estimated risk is low, though paying attention to {phrase} can help keep it that way.",
    "LOW_STRONG": "Your estimated risk is low - keeping up {phrase} is a good way to stay on track.",
    "LOW_GENERIC": "Your estimated risk is low - maintaining balanced lifestyle habits can help keep it that way.",
    "INTERMEDIARY_WEAK": "Your estimated risk is moderate - small, steady changes around {phrase} may help over time.",
    "INTERMEDIARY_GENERIC": "Your estimated risk is moderate - a brief check-in with a healthcare professional may help clarify next steps.",
    "HIGH_WEAK": "Your estimated risk is higher - {phrase} could be the most impactful next step, ideally alongside a healthcare professional.",
    "HIGH_GENERIC": "Your estimated risk is higher - a conversation with a healthcare professional is the most useful next step.",
}

_FACTOR_DESCRIPTORS = {
    "smoking": "current smoking",
    "bmi_high": "an elevated BMI",
    "bmi_over": "a slightly elevated BMI",
    "bmi_under": "a low BMI",
    "activity": "limited physical activity",
    "family": "a family history of CVD",
}

_STRENGTH_DESCRIPTORS = {
    "smoking": "not smoking",
    "activity_high": "an active lifestyle",
    "activity_moderate": "regular physical activity",
    "bmi": "a healthy BMI",
    "family": "no known family history",
}

_EXPLANATION_TEMPLATES = {
    "RAISED_BY": "This estimate is driven mainly by {factors}.",
    "NO_STANDOUT_RAISED": "No single strong risk factor stands out - the estimate reflects the overall profile.",
    "LOW_WATCH": "Areas worth watching even at this level: {factors}.",
    "LOW_CONTRIBUTORS": "Key contributors to this estimate include {factors}.",
}


def _score_concerns(input_data, bmi):
    concerns = []

    smoking = (input_data.get("Smoking Status") or "").upper()
    if smoking == "Y":
        concerns.append(("smoking", 3, "smoking"))

    if bmi is not None:
        if bmi >= 30:
            concerns.append(("bmi", 3, "bmi_high"))
        elif bmi >= 25:
            concerns.append(("bmi", 2, "bmi_over"))
        elif bmi < 18.5:
            concerns.append(("bmi", 2, "bmi_under"))

    activity = (input_data.get("Physical Activity Level") or "").lower()
    if activity == "low":
        concerns.append(("activity", 2, "activity"))

    family = (input_data.get("Family History of CVD") or "").upper()
    if family == "Y":
        concerns.append(("family", 1, "family"))

    return concerns


def _score_strengths(input_data, bmi):
    strengths = []

    smoking = (input_data.get("Smoking Status") or "").upper()
    if smoking == "N":
        strengths.append(("smoking", 3, "smoking"))

    activity = (input_data.get("Physical Activity Level") or "").lower()
    if activity == "high":
        strengths.append(("activity", 3, "activity_high"))
    elif activity == "moderate":
        strengths.append(("activity", 2, "activity_moderate"))

    if bmi is not None and 18.5 <= bmi < 25:
        strengths.append(("bmi", 2, "bmi"))

    family = (input_data.get("Family History of CVD") or "").upper()
    if family == "N":
        strengths.append(("family", 1, "family"))

    return strengths


def _sort_factors(items):
    priority_index = {name: i for i, name in enumerate(_FACTOR_PRIORITY)}
    return sorted(items, key=lambda x: (-x[1], priority_index.get(x[0], len(_FACTOR_PRIORITY))))


def _pick_top(items):
    if not items:
        return None
    return _sort_factors(items)[0]


def _join_factors(fragments):
    if not fragments:
        return ""
    if len(fragments) == 1:
        return fragments[0]
    if len(fragments) == 2:
        return f"{fragments[0]} and {fragments[1]}"
    return ", ".join(fragments[:-1]) + f", and {fragments[-1]}"


def _compose_explanation(risk_key, concerns, strengths):
    sorted_concerns = _sort_factors(concerns)

    if risk_key in ("HIGH", "INTERMEDIARY"):
        notable = [c for c in sorted_concerns if c[1] >= 2]
        if not notable:
            notable = [c for c in sorted_concerns if c[1] >= 1][:1]
        if notable:
            fragments = [_FACTOR_DESCRIPTORS[c[2]] for c in notable[:2]]
            return _EXPLANATION_TEMPLATES["RAISED_BY"].format(factors=_join_factors(fragments))
        return _EXPLANATION_TEMPLATES["NO_STANDOUT_RAISED"]

    notable_concerns = [c for c in sorted_concerns if c[1] >= 2]
    if notable_concerns:
        fragments = [_FACTOR_DESCRIPTORS[c[2]] for c in notable_concerns[:2]]
        return _EXPLANATION_TEMPLATES["LOW_WATCH"].format(factors=_join_factors(fragments))

    sorted_strengths = _sort_factors(strengths)
    if sorted_strengths:
        fragments = [_STRENGTH_DESCRIPTORS[s[2]] for s in sorted_strengths[:2]]
        return _EXPLANATION_TEMPLATES["LOW_CONTRIBUTORS"].format(factors=_join_factors(fragments))

    return None


def build_recommendations(pred_class_name, input_data, bmi):
    risk_key = (pred_class_name or "").upper()
    if risk_key == "INTERMEDIARY":
        risk_label = "Medium"
        accent = "warning"
    elif risk_key == "HIGH":
        risk_label = "High"
        accent = "danger"
    else:
        risk_key = "LOW"
        risk_label = "Low"
        accent = "success"

    concerns = _score_concerns(input_data, bmi)
    strengths = _score_strengths(input_data, bmi)
    explanation = _compose_explanation(risk_key, concerns, strengths)

    if risk_key == "HIGH":
        top = _pick_top(concerns)
        if top:
            sentence = _SENTENCE_TEMPLATES["HIGH_WEAK"].format(phrase=_WEAK_FACTOR_ACTIONS[top[2]])
        else:
            sentence = _SENTENCE_TEMPLATES["HIGH_GENERIC"]
    elif risk_key == "INTERMEDIARY":
        top = _pick_top(concerns)
        if top:
            sentence = _SENTENCE_TEMPLATES["INTERMEDIARY_WEAK"].format(phrase=_WEAK_FACTOR_PHRASES[top[2]])
        else:
            sentence = _SENTENCE_TEMPLATES["INTERMEDIARY_GENERIC"]
    else:
        # For LOW, only soft-warn if there's a meaningfully concerning factor (score >= 2);
        # family history alone (score 1) should not override the "low risk" framing.
        notable = [c for c in concerns if c[1] >= 2]
        top_concern = _pick_top(notable)
        if top_concern:
            sentence = _SENTENCE_TEMPLATES["LOW_WEAK"].format(phrase=_WEAK_FACTOR_PHRASES[top_concern[2]])
        else:
            top_strength = _pick_top(strengths)
            if top_strength:
                sentence = _SENTENCE_TEMPLATES["LOW_STRONG"].format(phrase=_STRONG_HABIT_PHRASES[top_strength[2]])
            else:
                sentence = _SENTENCE_TEMPLATES["LOW_GENERIC"]

    return {
        "risk_label": risk_label,
        "accent": accent,
        "sentence": sentence,
        "explanation": explanation,
    }


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/quick-test")
def quick_test():
    defaults = {
        "Age": "",
        "Height (cm)": "",
        "Weight (kg)": "",
        "Physical Activity Level": "Moderate",
        "Smoking Status": "N",
        "Family History of CVD": "N",
    }
    return render_template("quick_test.html", form=defaults, errors={})


@bp.post("/predict")
def predict():
    clean, errors = validate_quick_form(request.form)

    if errors:
        form = dict(request.form)
        return render_template("quick_test.html", form=form, errors=errors), 400

    result = model_service.predict(clean)

    height_m = clean["Height (cm)"] / 100.0
    bmi = clean["Weight (kg)"] / (height_m *
                                  height_m) if height_m > 0 else None

    recommendations = build_recommendations(result.get("pred_class_name"), clean, bmi)
    gap = _compute_gap(result.get("proba"), result.get("pred_class_name"))
    comparison = _compare_to_reference(clean, bmi)
    borderline = _is_borderline(result.get("proba") or [])
    population_phrase = _population_context(clean.get("Age"), result.get("pred_class_name"))

    try:
        counterfactuals = search_counterfactuals(clean, result.get("pred_class_name"), model_service)
    except Exception:
        counterfactuals = []

    shap_max_abs = 0.0
    if result.get("shap_top"):
        shap_max_abs = max((abs(c["contribution"]) for c in result["shap_top"][:3]), default=0.0)

    return render_template(
        "result.html",
        input_data=clean,
        bmi=bmi,
        result=result,
        recommendations=recommendations,
        gap=gap,
        comparison=comparison,
        borderline=borderline,
        population_phrase=population_phrase,
        counterfactuals=counterfactuals,
        shap_max_abs=shap_max_abs,
    )


@bp.post("/api/predict")
def api_predict():
    payload = request.get_json(silent=True) or {}
    # Validator expects strings (uses .strip()); JSON may bring numbers, so coerce.
    payload_str = {k: ("" if v is None else str(v)) for k, v in payload.items()}
    clean, errors = validate_quick_form(payload_str)
    if errors:
        return jsonify({"errors": errors}), 400

    result = model_service.predict(clean)
    return jsonify({
        "pred_class_name": result.get("pred_class_name"),
        "pred_confidence": result.get("pred_confidence"),
        "proba": result.get("proba"),
    })


@bp.get("/history")
def history():
    return render_template("history.html")


@bp.get("/research")
def research():
    return render_template("research.html")


@bp.get("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@bp.get("/about")
def about():
    return render_template("about.html")


@bp.get("/full-version")
def full_version():
    return render_template("full_version.html")
