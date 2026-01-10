# CVD Risk ML Web App (Flask + CatBoost)

## What this is
A multi-page Flask website for a diploma project, including:
- Home (title page)
- Quick Test (6-feature prediction)
- Research Results (placeholders for your images/metrics)
- About
- Full version

## Model
Put your CatBoost model file here:
`model/cvd_catboost_truncated_6f.cbm`

## Run locally
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

Open: http://127.0.0.1:5000

## Notes
- Activity: Low / Moderate / High
- Smoking: Y / N
- Family history: Y / N
- Height in cm, weight in kg
