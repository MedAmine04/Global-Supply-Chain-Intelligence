"""Scoring d'images de colis avec le modèle entraîné (Phase 5)."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tensorflow as tf

from app.cv.train import MODEL_PATH


class DamageModelNotTrainedError(RuntimeError):
    pass


@dataclass
class DamagePrediction:
    probability: float
    is_damaged: bool


def load_model() -> tf.keras.Model:
    if not MODEL_PATH.exists():
        raise DamageModelNotTrainedError(
            f"Aucun modèle entraîné trouvé ({MODEL_PATH}). "
            "Exécutez `python -m app.cli train-damage-classifier` d'abord."
        )
    return tf.keras.models.load_model(MODEL_PATH)


def predict_damage(model: tf.keras.Model, images: np.ndarray) -> list[DamagePrediction]:
    probabilities = model.predict(images, verbose=0).ravel()
    return [
        DamagePrediction(probability=round(float(p), 4), is_damaged=bool(p >= 0.5))
        for p in probabilities
    ]


def predict_damage_from_folder(folder: Path) -> dict[str, DamagePrediction]:
    import cv2

    from app.cv.synthetic import IMAGE_SIZE

    model = load_model()
    paths = sorted(
        p for p in folder.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
    )
    if not paths:
        return {}

    images = np.stack([cv2.resize(cv2.imread(str(p)), (IMAGE_SIZE, IMAGE_SIZE)) for p in paths])
    predictions = predict_damage(model, images)
    return {p.name: pred for p, pred in zip(paths, predictions, strict=True)}
