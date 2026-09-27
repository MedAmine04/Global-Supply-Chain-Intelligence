"""Entraînement du modèle de prédiction de retard (FR-11).

Split TEMPOREL, pas aléatoire : les expéditions les plus anciennes
servent à l'entraînement, les plus récentes au test. Un split aléatoire
mélangerait passé et futur dans les deux ensembles, ce qui masquerait
artificiellement les erreurs qu'un vrai déploiement rencontrerait
(prédire l'avenir avec un modèle qui n'a vu que le passé). C'est un
choix aussi important que les features elles-mêmes pour la validité du
modèle (cf. ADR-009).
"""

import json
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sqlalchemy.orm import Session
from xgboost import XGBClassifier

from app.ml.features import FEATURE_COLUMNS, TARGET_COLUMN, build_feature_dataset

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"
MLRUNS_DIR = Path(__file__).resolve().parent.parent.parent / "mlruns"

NUMERIC_FEATURES = [
    "distance_km", "quantity", "warehouse_capacity", "day_of_week",
    "supplier_delay_rate", "supplier_prior_shipment_count", "previous_incidents_count",
]
CATEGORICAL_FEATURES = ["transport_mode", "season"]

TEST_SET_FRACTION = 0.2  # les 20% d'expéditions les plus récentes


@dataclass
class ModelMetrics:
    model_name: str
    precision: float
    recall: float
    f1: float
    roc_auc: float
    confusion_matrix: list[list[int]]
    train_size: int
    test_size: int


@dataclass
class TrainingResult:
    metrics_by_model: dict[str, ModelMetrics] = field(default_factory=dict)
    best_model_name: str | None = None
    model_path: Path | None = None


def _build_preprocessor() -> ColumnTransformer:
    return ColumnTransformer([
        ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])


def _temporal_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("ship_date").reset_index(drop=True)
    cutoff_idx = int(len(df) * (1 - TEST_SET_FRACTION))
    return df.iloc[:cutoff_idx].copy(), df.iloc[cutoff_idx:].copy()


def _fill_cold_start(train: pd.DataFrame, test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Une expédition sans historique fournisseur antérieur (le tout
    premier envoi d'un fournisseur, ou un fournisseur nouvellement
    ingéré) a `supplier_delay_rate` = NaN. On la remplace par la moyenne
    du seul ensemble d'entraînement — jamais celle du test, qui serait
    une fuite d'information sur des données que le modèle ne verra qu'à
    l'évaluation."""
    fallback_rate = train[TARGET_COLUMN].mean()
    train = train.copy()
    test = test.copy()
    train["supplier_delay_rate"] = train["supplier_delay_rate"].fillna(fallback_rate)
    test["supplier_delay_rate"] = test["supplier_delay_rate"].fillna(fallback_rate)
    return train, test


def _evaluate(
    model_name: str, pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series
) -> ModelMetrics:
    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]

    roc_auc = (
        round(float(roc_auc_score(y_test, y_proba)), 4)
        if len(set(y_test)) > 1
        else float("nan")
    )

    return ModelMetrics(
        model_name=model_name,
        precision=round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
        recall=round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
        f1=round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
        roc_auc=roc_auc,
        confusion_matrix=confusion_matrix(y_test, y_pred).tolist(),
        train_size=0,  # rempli par l'appelant
        test_size=len(y_test),
    )


def train_and_compare_models(db: Session) -> TrainingResult:
    dataset = build_feature_dataset(db, only_undelivered=False)
    df = dataset.df.dropna(subset=[TARGET_COLUMN])

    if len(df) < 20:
        raise ValueError(
            f"Dataset trop petit pour entraîner ({len(df)} lignes) — "
            "au moins 20 expéditions livrées sont nécessaires."
        )

    train_df, test_df = _temporal_split(df)
    train_df, test_df = _fill_cold_start(train_df, test_df)

    X_train, y_train = train_df[FEATURE_COLUMNS], train_df[TARGET_COLUMN].astype(int)
    X_test, y_test = test_df[FEATURE_COLUMNS], test_df[TARGET_COLUMN].astype(int)

    # class_weight="balanced" (et l'équivalent scale_pos_weight pour XGBoost)
    # sur les trois modèles : environ 21% de retards seulement dans le
    # dataset (cf. taux injecté par le générateur), donc sans rééquilibrage
    # un modèle peut atteindre un bon ROC-AUC tout en prédisant presque
    # toujours "pas de retard" au seuil 0.5 — observé concrètement lors
    # d'un premier entraînement (RandomForest : ROC-AUC correct mais
    # rappel de 0.007, cf. ADR-009) avant cette correction.
    positive_rate = y_train.mean()
    scale_pos_weight = (1 - positive_rate) / positive_rate if positive_rate > 0 else 1.0

    models = {
        "logistic_regression": LogisticRegression(max_iter=1000, class_weight="balanced"),
        "random_forest": RandomForestClassifier(
            n_estimators=200, max_depth=8, random_state=42, class_weight="balanced"
        ),
        "xgboost": XGBClassifier(
            n_estimators=200, max_depth=4, eval_metric="logloss", random_state=42,
            scale_pos_weight=scale_pos_weight,
        ),
    }

    mlflow.set_tracking_uri(f"file://{MLRUNS_DIR}")
    mlflow.set_experiment("shipment_delay_prediction")

    result = TrainingResult()
    best_roc_auc = -1.0

    for name, estimator in models.items():
        pipeline = Pipeline([
            ("preprocess", _build_preprocessor()),
            ("model", estimator),
        ])

        with mlflow.start_run(run_name=name):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pipeline.fit(X_train, y_train)

            metrics = _evaluate(name, pipeline, X_test, y_test)
            metrics.train_size = len(X_train)

            mlflow.log_params({"model": name, "train_size": len(X_train), "test_size": len(X_test)})
            mlflow.log_metrics({
                "precision": metrics.precision,
                "recall": metrics.recall,
                "f1": metrics.f1,
                "roc_auc": metrics.roc_auc,
            })
            mlflow.sklearn.log_model(pipeline, artifact_path="model")

        result.metrics_by_model[name] = metrics

        if not np.isnan(metrics.roc_auc) and metrics.roc_auc > best_roc_auc:
            best_roc_auc = metrics.roc_auc
            result.best_model_name = name
            MODELS_DIR.mkdir(exist_ok=True)
            model_path = MODELS_DIR / "shipment_delay_model.joblib"
            joblib.dump(pipeline, model_path)
            result.model_path = model_path

    if result.best_model_name:
        metadata = {
            "model_name": result.best_model_name,
            "roc_auc": best_roc_auc,
            "trained_at": datetime.now(UTC).isoformat(),
            "train_size": result.metrics_by_model[result.best_model_name].train_size,
            "test_size": result.metrics_by_model[result.best_model_name].test_size,
        }
        (MODELS_DIR / "model_metadata.json").write_text(json.dumps(metadata, indent=2))

    return result
