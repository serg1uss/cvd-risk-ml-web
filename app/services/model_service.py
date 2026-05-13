from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, Pool


@dataclass(frozen=True)
class ModelConfig:
    model_path: Path
    # Если None — берём фичи прямо из модели (РЕКОМЕНДУЕТСЯ)
    feature_order: Optional[List[str]] = None
    # Имена классов для UI (например ["LOW","MEDIUM","HIGH"])
    class_names: Optional[List[str]] = None


class ModelService:
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg
        self.model = CatBoostClassifier()
        self.model.load_model(str(cfg.model_path))

        # Берём реальные фичи из модели → больше не будет ошибок несовпадения
        model_features = list(getattr(self.model, "feature_names_", []) or [])
        self.feature_order: List[str] = cfg.feature_order or model_features

        if not self.feature_order:
            raise RuntimeError(
                "Cannot determine feature names from the CatBoost model."
            )

        self.class_names = cfg.class_names

        # print("MODEL CLASSES:", getattr(self.model, "classes_", None))
        # print("MODEL FEATURES:", getattr(self.model, "feature_names_", None))

    def _augment_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Добавляет производные признаки, если модель их ожидает.
        Сейчас поддерживается BMI.
        """
        augmented = dict(payload)

        if "BMI" in self.feature_order and "BMI" not in augmented:
            try:
                h_cm = float(augmented.get("Height (cm)"))
                w_kg = float(augmented.get("Weight (kg)"))
                h_m = h_cm / 100.0
                if h_m > 0:
                    augmented["BMI"] = w_kg / (h_m * h_m)
            except Exception:
                pass

        return augmented

    def predict(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._augment_payload(payload)

        row = {f: payload.get(f) for f in self.feature_order}
        X = pd.DataFrame([row], columns=self.feature_order)

        # --- PREDICT CLASS ---
        pred = self.model.predict(X, prediction_type="Class")
        pred_value = pred[0][0] if hasattr(pred[0], "__len__") else pred[0]

        pred_class_idx = None

        # CatBoost может вернуть строку ("LOW") или индекс
        if isinstance(pred_value, (str, bytes)):
            class_label = str(pred_value).strip()
            class_label_upper = class_label.upper()

            if self.class_names:
                upper_names = [str(c).upper() for c in self.class_names]
                if class_label_upper in upper_names:
                    pred_class_idx = upper_names.index(class_label_upper)
                    pred_class_name = self.class_names[pred_class_idx]
                else:
                    pred_class_name = class_label
            else:
                pred_class_name = class_label
        else:
            pred_class_idx = int(pred_value)
            if self.class_names and 0 <= pred_class_idx < len(self.class_names):
                pred_class_name = self.class_names[pred_class_idx]
            else:
                pred_class_name = str(pred_class_idx)

        # --- PROBABILITIES ---
        proba = None
        try:
            proba_arr = self.model.predict_proba(X)[0]
            proba = [float(x) for x in proba_arr]
        except Exception:
            proba = None

        result = {
            "pred_class_idx": pred_class_idx,
            "pred_class_name": pred_class_name,
            "used_features": self.feature_order,
        }

        if proba:
            if self.class_names and len(proba) == len(self.class_names):
                result["proba"] = [
                    {"class": self.class_names[i], "p": proba[i]}
                    for i in range(len(proba))
                ]
            else:
                result["proba"] = [
                    {"class": str(i), "p": proba[i]}
                    for i in range(len(proba))
                ]

            if pred_class_idx is not None and pred_class_idx < len(proba):
                result["pred_confidence"] = proba[pred_class_idx]
            else:
                result["pred_confidence"] = max(proba)
        else:
            result["proba"] = None
            result["pred_confidence"] = None

        result["shap_top"] = self._compute_shap(X, pred_class_idx, payload)

        return result

    def _compute_shap(self, X: pd.DataFrame, pred_class_idx: Optional[int],
                     payload: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        try:
            shap_values = self.model.get_feature_importance(Pool(X), type="ShapValues")
        except Exception:
            return None
        try:
            arr = np.asarray(shap_values)
        except Exception:
            return None

        if arr.ndim == 3:
            class_idx = pred_class_idx if (pred_class_idx is not None and 0 <= pred_class_idx < arr.shape[1]) else 0
            row = arr[0, class_idx, :-1]
        elif arr.ndim == 2:
            row = arr[0, :-1]
        else:
            return None

        if row.shape[0] != len(self.feature_order):
            return None

        contributions = []
        for i, feat in enumerate(self.feature_order):
            value = payload.get(feat)
            contributions.append({
                "feature": feat,
                "value": value,
                "contribution": float(row[i]),
            })
        contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)
        return contributions

    def predict_batch(self, payloads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not payloads:
            return []
        augmented = [self._augment_payload(p) for p in payloads]
        rows = [{f: a.get(f) for f in self.feature_order} for a in augmented]
        X = pd.DataFrame(rows, columns=self.feature_order)

        preds_raw = self.model.predict(X, prediction_type="Class")
        try:
            proba_arr = self.model.predict_proba(X)
        except Exception:
            proba_arr = None

        results = []
        for i in range(len(payloads)):
            pred_value = preds_raw[i]
            if hasattr(pred_value, "__len__") and not isinstance(pred_value, (str, bytes)):
                pred_value = pred_value[0]

            pred_class_idx = None
            if isinstance(pred_value, (str, bytes)):
                class_label = str(pred_value).strip()
                class_label_upper = class_label.upper()
                if self.class_names:
                    upper_names = [str(c).upper() for c in self.class_names]
                    if class_label_upper in upper_names:
                        pred_class_idx = upper_names.index(class_label_upper)
                        pred_class_name = self.class_names[pred_class_idx]
                    else:
                        pred_class_name = class_label
                else:
                    pred_class_name = class_label
            else:
                pred_class_idx = int(pred_value)
                if self.class_names and 0 <= pred_class_idx < len(self.class_names):
                    pred_class_name = self.class_names[pred_class_idx]
                else:
                    pred_class_name = str(pred_class_idx)

            entry: Dict[str, Any] = {
                "pred_class_idx": pred_class_idx,
                "pred_class_name": pred_class_name,
            }

            if proba_arr is not None:
                proba_row = [float(x) for x in proba_arr[i]]
                if self.class_names and len(proba_row) == len(self.class_names):
                    entry["proba"] = [
                        {"class": self.class_names[j], "p": proba_row[j]}
                        for j in range(len(proba_row))
                    ]
                else:
                    entry["proba"] = [
                        {"class": str(j), "p": proba_row[j]}
                        for j in range(len(proba_row))
                    ]
                if pred_class_idx is not None and pred_class_idx < len(proba_row):
                    entry["pred_confidence"] = proba_row[pred_class_idx]
                else:
                    entry["pred_confidence"] = max(proba_row)
            else:
                entry["proba"] = None
                entry["pred_confidence"] = None

            results.append(entry)

        return results
