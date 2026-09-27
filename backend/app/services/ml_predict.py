"""Scoring des expéditions non livrées (FR-13).

Charge le modèle sauvegardé par `train.py` (le meilleur des trois par
ROC-AUC) et l'applique aux expéditions en cours — celles sans date de
livraison réelle connue, donc sans résultat (`is_delayed`) à prédire.
"""

import json
from dataclasses import dataclass

import joblib
import pandas as pd
from sqlalchemy.orm import Session

from app.ml.features import FEATURE_COLUMNS, build_feature_dataset
from app.ml.train import MODELS_DIR
from app.models.predictions import ShipmentDelayPrediction

MODEL_PATH = MODELS_DIR / "shipment_delay_model.joblib"
METADATA_PATH = MODELS_DIR / "model_metadata.json"


class ModelNotTrainedError(RuntimeError):
    """Levée si `predict_at_risk_shipments` est appelé avant tout entraînement."""


@dataclass
class ScoringResult:
    shipments_scored: int
    high_risk_count: int  # probability >= 0.5


def _current_model_name() -> str:
    if METADATA_PATH.exists():
        return json.loads(METADATA_PATH.read_text()).get("model_name", "unknown")
    return "unknown"


def predict_at_risk_shipments(db: Session) -> ScoringResult:
    if not MODEL_PATH.exists():
        raise ModelNotTrainedError(
            f"Aucun modèle entraîné trouvé ({MODEL_PATH}). "
            "Exécutez `python -m app.cli train-model` d'abord."
        )

    pipeline = joblib.load(MODEL_PATH)
    model_name = _current_model_name()

    dataset = build_feature_dataset(db, only_undelivered=True)
    if dataset.df.empty:
        db.query(ShipmentDelayPrediction).delete()
        db.commit()
        return ScoringResult(shipments_scored=0, high_risk_count=0)

    # Même piège de cold start qu'à l'entraînement (cf. train.py) : une
    # expédition d'un fournisseur sans historique connu n'a pas de
    # supplier_delay_rate calculable. On utilise ici le taux moyen
    # observé sur l'ensemble des expéditions déjà livrées (la meilleure
    # estimation disponible en production, faute d'un ensemble
    # d'entraînement à disposition à ce stade du pipeline).
    delivered = build_feature_dataset(db, only_undelivered=False)
    fallback_rate = (
        delivered.df["is_delayed"].mean() if not delivered.df.empty else 0.2
    )

    X = dataset.df[FEATURE_COLUMNS].copy()
    X["supplier_delay_rate"] = X["supplier_delay_rate"].fillna(fallback_rate)

    probabilities = pipeline.predict_proba(X)[:, 1]
    predictions = pipeline.predict(X)

    db.query(ShipmentDelayPrediction).delete()
    for shipment_id, proba, label in zip(
        dataset.df["shipment_id"], probabilities, predictions, strict=True
    ):
        db.add(
            ShipmentDelayPrediction(
                shipment_id=shipment_id,
                probability=round(float(proba), 4),
                predicted_label=int(label),
                model_name=model_name,
            )
        )
    db.commit()

    high_risk = int((pd.Series(probabilities) >= 0.5).sum())
    return ScoringResult(shipments_scored=len(dataset.df), high_risk_count=high_risk)
