"""Tests du module Computer Vision (Phase 5).

Pas de test qui entraîne le CNN complet (3000 images, ~4 min) dans la
suite standard : `test_training_pipeline_learns_real_signal` fait un
entraînement réduit (400 images, peu d'epochs) — un vrai garde-fou
contre une régression du bug d'instabilité rencontré pendant le
développement (cf. ADR-011), pas une mesure de performance définitive.
"""

import numpy as np
import pytest

from app.cv.model import build_cnn
from app.cv.synthetic import IMAGE_SIZE, generate_dataset, render_package


def test_render_package_shape_and_dtype():
    rng = np.random.default_rng(0)
    img = render_package(rng, damaged=False)
    assert img.shape == (IMAGE_SIZE, IMAGE_SIZE, 3)
    assert img.dtype == np.uint8


def test_render_package_same_seed_is_deterministic():
    img1 = render_package(np.random.default_rng(42), damaged=True)
    img2 = render_package(np.random.default_rng(42), damaged=True)
    assert np.array_equal(img1, img2)


def test_generate_dataset_is_balanced_and_shaped():
    images, labels = generate_dataset(200, seed=1, damaged_fraction=0.5)
    assert images.shape == (200, IMAGE_SIZE, IMAGE_SIZE, 3)
    assert 0.35 < labels.mean() < 0.65  # ~50%, tolérance pour l'aléatoire


def test_build_cnn_output_shape():
    model = build_cnn()
    dummy = np.zeros((3, IMAGE_SIZE, IMAGE_SIZE, 3), dtype=np.uint8)
    output = model(dummy, training=False)
    assert output.shape == (3, 1)
    assert np.all((output.numpy() >= 0) & (output.numpy() <= 1))  # sigmoïde


@pytest.mark.slow
def test_training_pipeline_learns_real_signal(tmp_path, monkeypatch):
    """Garde-fou : un entraînement à l'échelle recommandée doit nettement
    dépasser le hasard. Ce test aurait échoué avec le premier modèle
    (sans seed fixée ni LR scheduler), resté bloqué à ~50% de recall/
    precision malgré un entraînement complet (cf. ADR-011).

    N'utilise PAS une échelle réduite pour aller plus vite : découvert
    en écrivant ce test, le pipeline devient instable (collapse vers
    "toujours normal") en dessous d'environ 3000 images — une vraie
    limite du pipeline à ce stade (cf. ADR-011), pas un choix arbitraire
    de paramètres de test. ~4 minutes d'exécution, volontairement exclu
    de la suite rapide (`pytest -m "not slow"`)."""
    from app.ml import train as ml_train_module

    monkeypatch.setattr(ml_train_module, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(ml_train_module, "MLRUNS_DIR", tmp_path / "mlruns")
    import app.cv.train as cv_train_module

    monkeypatch.setattr(cv_train_module, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(cv_train_module, "MODEL_PATH", tmp_path / "damage_classifier.keras")

    from app.cv.train import train_damage_classifier

    result = train_damage_classifier(n_samples=3000, epochs=50)
    assert result.f1 > 0.6  # très nettement au-dessus du hasard (F1 ~0.33-0.5)
