"""Entraînement du classifieur de dommages (Phase 5).

Split aléatoire stratifié (images indépendantes, pas de dimension
temporelle comme pour les expéditions — cf. ADR-009 pour ce cas-là).
Dataset synthétique par défaut ; `image_folder` permet d'entraîner sur
de vraies photos (cf. app/cv/dataset.py) sans changer le reste.
"""

from dataclasses import dataclass
from pathlib import Path

import mlflow
import tensorflow as tf
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

from app.cv.model import build_cnn
from app.cv.synthetic import generate_dataset
from app.ml.train import MLRUNS_DIR, MODELS_DIR

MODEL_PATH = MODELS_DIR / "damage_classifier.keras"


@dataclass
class DamageTrainingResult:
    precision: float
    recall: float
    f1: float
    confusion_matrix: list
    train_size: int
    test_size: int
    model_path: Path


def train_damage_classifier(
    n_samples: int = 1200, epochs: int = 12, image_folder: Path | None = None, seed: int = 42,
) -> DamageTrainingResult:
    if image_folder is not None:
        from app.cv.dataset import load_image_folder

        images, labels = load_image_folder(image_folder)
    else:
        images, labels = generate_dataset(n_samples, seed=seed)

    # Seed fixée sur l'initialisation des poids : sans ça, deux runs sur
    # les mêmes données peuvent converger vers des optima très différents
    # (observé concrètement : un run à val_accuracy ~0.89, un autre quasi
    # aléatoire, cf. ADR-011) — la reproductibilité n'est pas cosmétique
    # ici, c'est ce qui permet de documenter un résultat de confiance.
    tf.random.set_seed(seed)

    X_train, X_test, y_train, y_test = train_test_split(
        images, labels, test_size=0.2, random_state=seed, stratify=labels
    )

    model = build_cnn()
    mlflow.set_tracking_uri(f"file://{MLRUNS_DIR}")
    mlflow.set_experiment("package_damage_classification")

    with mlflow.start_run(run_name="cnn_synthetic"):
        early_stop = tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=8, restore_best_weights=True
        )
        reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=3, min_lr=1e-5
        )
        model.fit(
            X_train, y_train, validation_split=0.15, epochs=epochs,
            batch_size=32, verbose=0, callbacks=[early_stop, reduce_lr],
        )
        y_proba = model.predict(X_test, verbose=0).ravel()
        y_pred = (y_proba >= 0.5).astype(int)

        precision = float(precision_score(y_test, y_pred, zero_division=0))
        recall = float(recall_score(y_test, y_pred, zero_division=0))
        f1 = float(f1_score(y_test, y_pred, zero_division=0))

        source = "synthetic" if image_folder is None else str(image_folder)
        mlflow.log_params({"n_samples": len(images), "epochs": epochs, "source": source})
        mlflow.log_metrics({"precision": precision, "recall": recall, "f1": f1})

    MODELS_DIR.mkdir(exist_ok=True)
    model.save(MODEL_PATH)

    return DamageTrainingResult(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        confusion_matrix=confusion_matrix(y_test, y_pred).tolist(),
        train_size=len(X_train),
        test_size=len(X_test),
        model_path=MODEL_PATH,
    )
