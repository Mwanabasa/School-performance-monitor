"""Scikit-learn failure-risk classification model."""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from django.conf import settings
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .features import FEATURE_COLUMNS, build_training_frame


def _ensure_model_dir() -> Path:
    path = Path(settings.ML_MODEL_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _heuristic_probability(row: pd.Series) -> float:
    """Fallback risk estimate when no trained model is available."""
    avg = float(row.get('avg_score', 50))
    attendance = float(row.get('attendance_rate', 1.0))
    slope = float(row.get('trend_slope', 0.0))
    midterm = float(row.get('midterm_score', avg))
    recent = float(row.get('recent_avg', avg))

    # Lower scores / attendance => higher failure probability
    score_risk = max(0.0, min(1.0, (60 - avg) / 60))
    attendance_risk = max(0.0, min(1.0, (0.85 - attendance) / 0.85))
    trend_risk = max(0.0, min(1.0, (-slope) / 15))
    midterm_risk = max(0.0, min(1.0, (50 - midterm) / 50))
    recent_risk = max(0.0, min(1.0, (55 - recent) / 55))

    probability = (
        0.35 * score_risk
        + 0.20 * attendance_risk
        + 0.20 * trend_risk
        + 0.15 * midterm_risk
        + 0.10 * recent_risk
    )
    return float(np.clip(probability, 0.02, 0.98))


class RiskModel:
    feature_version = 3

    def __init__(self):
        self.pipeline: Pipeline | None = None
        self.metrics: dict = {}
        self.model_path = Path(settings.ML_MODEL_PATH)

    def load(self) -> bool:
        self.pipeline = None
        if not self.model_path.exists():
            return False

        payload = joblib.load(self.model_path)
        if payload.get('feature_version') != self.feature_version:
            self.metrics = {
                'status': 'stale_model',
                'message': 'Model features changed; retrain the model to continue.',
            }
            return False

        self.pipeline = payload['pipeline']
        self.metrics = payload.get('metrics', {})
        return True

    def save(self) -> None:
        _ensure_model_dir()
        joblib.dump(
            {
                'pipeline': self.pipeline,
                'metrics': self.metrics,
                'feature_version': self.feature_version,
            },
            self.model_path,
        )

    def train(self, min_samples: int = 12) -> dict:
        self.pipeline = None
        self.metrics = {}
        X, y = build_training_frame()
        if len(X) < min_samples or y.nunique() < 2:
            # Generate synthetic training data from current cohort + heuristic labels
            from .features import build_feature_frame

            frame = build_feature_frame()
            if frame.empty:
                self.metrics = {
                    'status': 'insufficient_data',
                    'samples': 0,
                    'message': 'Add student assessments (including end-of-term) to train the model.',
                }
                return self.metrics

            X = frame[FEATURE_COLUMNS]
            # Pseudo-labels from heuristic for bootstrap training
            y = X.apply(lambda r: 1 if _heuristic_probability(r) >= 0.5 else 0, axis=1)
            if y.nunique() < 2:
                y = (X['avg_score'] < settings.PASS_MARK).astype(int)
            source = 'bootstrap_heuristic'
        else:
            source = 'historical_endterm'

        if len(X) < 4 or y.nunique() < 2:
            self.metrics = {
                'status': 'insufficient_data',
                'samples': int(len(X)),
                'message': 'Need more varied student outcomes to train.',
            }
            return self.metrics

        test_size = 0.25 if len(X) >= 8 else 0.2
        try:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=42, stratify=y if y.value_counts().min() >= 2 else None
            )
        except ValueError:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=test_size, random_state=42
            )

        candidates = {
            'logistic': Pipeline(
                [
                    ('scaler', StandardScaler()),
                    ('clf', LogisticRegression(max_iter=1000, class_weight='balanced')),
                ]
            ),
            'random_forest': Pipeline(
                [
                    (
                        'clf',
                        RandomForestClassifier(
                            n_estimators=120,
                            max_depth=5,
                            random_state=42,
                            class_weight='balanced',
                        ),
                    )
                ]
            ),
            'gradient_boosting': Pipeline(
                [
                    (
                        'clf',
                        GradientBoostingClassifier(random_state=42),
                    )
                ]
            ),
        }

        best_name = None
        best_score = -1.0
        best_pipeline = None
        details = {}

        for name, pipe in candidates.items():
            pipe.fit(X_train, y_train)
            proba = pipe.predict_proba(X_test)[:, 1]
            preds = (proba >= 0.5).astype(int)
            acc = float(accuracy_score(y_test, preds))
            try:
                auc = float(roc_auc_score(y_test, proba))
            except ValueError:
                auc = acc
            details[name] = {'accuracy': round(acc, 3), 'roc_auc': round(auc, 3)}
            score = 0.5 * acc + 0.5 * auc
            if score > best_score:
                best_score = score
                best_name = name
                best_pipeline = pipe

        # Retrain best model on all data
        best_pipeline.fit(X, y)
        self.pipeline = best_pipeline
        self.metrics = {
            'status': 'trained',
            'samples': int(len(X)),
            'positives': int(y.sum()),
            'negatives': int((1 - y).sum()),
            'best_model': best_name,
            'source': source,
            'candidates': details,
        }
        self.save()
        return self.metrics

    def predict_proba(self, features: pd.DataFrame | dict) -> float:
        if isinstance(features, dict):
            frame = pd.DataFrame([features])[FEATURE_COLUMNS]
        else:
            frame = features[FEATURE_COLUMNS]

        if self.pipeline is None and not self.load():
            return _heuristic_probability(frame.iloc[0])

        proba = float(self.pipeline.predict_proba(frame)[0][1])
        return float(np.clip(proba, 0.01, 0.99))


risk_model = RiskModel()
