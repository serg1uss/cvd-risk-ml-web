from __future__ import annotations

from pathlib import Path

from flask import Blueprint, render_template, request

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


def _pick_top(items):
    if not items:
        return None
    priority_index = {name: i for i, name in enumerate(_FACTOR_PRIORITY)}
    return max(items, key=lambda x: (x[1], -priority_index.get(x[0], len(_FACTOR_PRIORITY))))


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
            top_strength = _pick_top(_score_strengths(input_data, bmi))
            if top_strength:
                sentence = _SENTENCE_TEMPLATES["LOW_STRONG"].format(phrase=_STRONG_HABIT_PHRASES[top_strength[2]])
            else:
                sentence = _SENTENCE_TEMPLATES["LOW_GENERIC"]

    return {
        "risk_label": risk_label,
        "accent": accent,
        "sentence": sentence,
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

    return render_template("result.html", input_data=clean, bmi=bmi, result=result, recommendations=recommendations)


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
