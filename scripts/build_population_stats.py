"""Recompute model/population_stats.json from a training CSV.

Usage:
    python scripts/build_population_stats.py path/to/train.csv

The CSV must have an age column and a risk-label column. Adjust LABEL_COLUMN /
AGE_COLUMN below to match your training data if they differ.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd


LABEL_COLUMN = "Risk_Category"
AGE_COLUMN = "Age"
CLASS_NAMES = ["LOW", "INTERMEDIARY", "HIGH"]
BANDS = [
    ("20-29", 20, 29),
    ("30-39", 30, 39),
    ("40-49", 40, 49),
    ("50-59", 50, 59),
    ("60+", 60, 200),
]


def main(csv_path: str) -> None:
    df = pd.read_csv(csv_path)
    if LABEL_COLUMN not in df.columns:
        raise SystemExit(f"Column '{LABEL_COLUMN}' not in CSV. Edit LABEL_COLUMN in this script.")
    if AGE_COLUMN not in df.columns:
        raise SystemExit(f"Column '{AGE_COLUMN}' not in CSV. Edit AGE_COLUMN in this script.")

    df = df.dropna(subset=[LABEL_COLUMN, AGE_COLUMN]).copy()
    df[LABEL_COLUMN] = df[LABEL_COLUMN].astype(str).str.upper()

    def class_shares(sub: pd.DataFrame) -> dict:
        counts = sub[LABEL_COLUMN].value_counts(normalize=True).to_dict()
        return {c: round(float(counts.get(c, 0.0)), 4) for c in CLASS_NAMES}

    by_age_band = {}
    for label, lo, hi in BANDS:
        band_df = df[(df[AGE_COLUMN] >= lo) & (df[AGE_COLUMN] <= hi)]
        if not band_df.empty:
            by_age_band[label] = class_shares(band_df)

    payload = {
        "_note": f"Generated from {csv_path}",
        "by_age_band": by_age_band,
        "overall": class_shares(df),
    }

    out_path = Path(__file__).resolve().parent.parent / "model" / "population_stats.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/build_population_stats.py <path/to/train.csv>")
        sys.exit(1)
    main(sys.argv[1])
