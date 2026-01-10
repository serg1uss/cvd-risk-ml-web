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


def build_recommendations(pred_class_name, input_data, bmi):
    risk_key = (pred_class_name or "").upper()
    if risk_key == "INTERMEDIARY":
        risk_label = "Medium"
        accent = "warning"
        headline = "Moderate estimated risk - small, steady changes may help."
    elif risk_key == "HIGH":
        risk_label = "High"
        accent = "danger"
        headline = "Higher estimated risk - consider a proactive lifestyle review."
    else:
        risk_label = "Low"
        accent = "success"
        headline = "Low estimated risk - focus on maintaining healthy habits."

    items = []

    activity = (input_data.get("Physical Activity Level") or "").lower()
    if activity == "low":
        items.append("Consider adding regular, moderate activity (for example, walking) as tolerated.")
    elif activity == "moderate":
        items.append("Maintaining consistent moderate activity may help support cardiovascular health.")
    elif activity == "high":
        items.append("Sustaining balanced high activity with adequate rest may help maintain fitness.")

    smoking = (input_data.get("Smoking Status") or "").upper()
    if smoking == "Y":
        items.append("If you smoke, consider exploring cessation resources; reducing exposure may help.")
    elif smoking == "N":
        items.append("Maintaining non-smoking habits may help protect cardiovascular health.")

    family = (input_data.get("Family History of CVD") or "").upper()
    if family == "Y":
        items.append("With a family history present, consider regular wellness check-ins for general guidance.")
    elif family == "N":
        items.append("Without known family history, focus on modifiable lifestyle factors.")

    if bmi is not None:
        if bmi < 18.5:
            items.append("If your BMI is below range, consider balanced nutrition to support overall health.")
        elif bmi < 25:
            items.append("Maintaining your current weight range may help support cardiovascular health.")
        elif bmi < 30:
            items.append("If your BMI is elevated, small, sustainable changes may help over time.")
        else:
            items.append("If your BMI is high, gradual lifestyle adjustments may help improve overall health.")

    items.append("This is an educational estimate; consider discussing results with a healthcare professional if you have concerns.")

    if len(items) < 3:
        items.append("Consider balanced meals and consistent sleep to support general well-being.")
    if len(items) < 3:
        items.append("Managing stress and staying hydrated may help overall wellness.")

    items = items[:5]

    return {
        "risk_label": risk_label,
        "accent": accent,
        "headline": headline,
        "items": items,
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
