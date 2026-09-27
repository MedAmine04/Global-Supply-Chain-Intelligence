"""Tests de app/ml/train.py.

Pas de test qui entraîne les 3 vrais modèles sur un dataset complet ici
(trop lent pour la suite de tests, et la qualité prédictive n'est de
toute façon pas quelque chose qu'un test unitaire peut figer sans
dataset de référence stable). On teste à la place les deux mécanismes
qui, s'ils étaient cassés, invalideraient silencieusement le modèle :
le split temporel et le traitement du cold start.
"""

import pandas as pd

from app.ml.train import TEST_SET_FRACTION, _fill_cold_start, _temporal_split


def test_temporal_split_keeps_oldest_rows_in_train():
    df = pd.DataFrame({
        "ship_date": pd.date_range("2024-01-01", periods=10, freq="D"),
        "value": range(10),
    })
    train, test = _temporal_split(df)

    assert len(test) == int(10 * TEST_SET_FRACTION)
    assert train["ship_date"].max() < test["ship_date"].min()


def test_fill_cold_start_uses_train_mean_not_test_mean():
    """Le point critique anti-fuite : la valeur de repli pour un
    fournisseur sans historique doit venir de train, jamais de test."""
    train = pd.DataFrame({
        "supplier_delay_rate": [0.1, 0.1, None],
        "is_delayed": [0, 0, 1],  # moyenne train = 1/3
    })
    test = pd.DataFrame({
        "supplier_delay_rate": [None],
        "is_delayed": [1],  # moyenne test = 1.0 — ne doit PAS être utilisée
    })

    train_filled, test_filled = _fill_cold_start(train, test)

    expected_fallback = train["is_delayed"].mean()
    assert train_filled["supplier_delay_rate"].iloc[2] == expected_fallback
    assert test_filled["supplier_delay_rate"].iloc[0] == expected_fallback
    assert expected_fallback != 1.0  # sinon le test ne prouverait rien
