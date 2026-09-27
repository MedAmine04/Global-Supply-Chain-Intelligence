"""Tests de app/services/ml_predict.py.

N'entraîne pas de vrai modèle à chaque test (trop lent, et redondant
avec test_ml_train.py qui teste déjà l'entraînement) : la fixture
`dummy_model` (conftest.py) fournit un pipeline scikit-learn minimal et
déterministe, pour tester uniquement la logique de scoring (chargement,
application aux expéditions non livrées, upsert en base) — pas la
qualité prédictive du modèle.
"""

import pytest

from app.core.database import SessionLocal
from app.models.predictions import ShipmentDelayPrediction
from app.services import ml_predict
from app.services.ml_predict import ModelNotTrainedError, predict_at_risk_shipments
from tests.conftest import load_to_silver


@pytest.fixture(autouse=True)
def clean_predictions_table():
    db = SessionLocal()
    db.query(ShipmentDelayPrediction).delete()
    db.commit()
    db.close()
    yield


def test_predict_raises_if_model_not_trained(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_predict, "MODEL_PATH", tmp_path / "does_not_exist.joblib")
    db = SessionLocal()
    try:
        with pytest.raises(ModelNotTrainedError):
            predict_at_risk_shipments(db)
    finally:
        db.close()


def test_predict_scores_only_undelivered_shipments(dummy_model):
    from app.services.gold_transform import transform_gold

    db = SessionLocal()
    try:
        load_to_silver(db, "suppliers", [
            {"supplier_id": "SUP-001", "name": "Acme", "country": "France",
             "reliability_score": "0.9", "created_at": "2024-01-01"},
        ])
        load_to_silver(db, "products", [
            {"product_id": "PRD-001", "name": "Widget", "category": "electronics",
             "unit_cost": "10.0"},
        ])
        load_to_silver(db, "warehouses", [
            {"warehouse_id": "WH-001", "name": "Paris DC", "country": "France",
             "region": "EMEA", "capacity": "10000"},
        ])
        load_to_silver(db, "orders", [
            {"order_id": "ORD-001", "supplier_id": "SUP-001", "product_id": "PRD-001",
             "warehouse_id": "WH-001", "order_date": "2024-01-01",
             "quantity": "50", "status": "delivered"},
            {"order_id": "ORD-002", "supplier_id": "SUP-001", "product_id": "PRD-001",
             "warehouse_id": "WH-001", "order_date": "2024-02-01",
             "quantity": "30", "status": "shipped"},
        ])
        load_to_silver(db, "shipments", [
            # Livrée (résultat connu) : ne doit PAS être scorée.
            {"shipment_id": "SHP-001", "order_id": "ORD-001", "warehouse_id": "WH-001",
             "transport_mode": "air", "origin": "Paris", "destination": "Berlin",
             "ship_date": "2024-01-02", "expected_delivery_date": "2024-01-10",
             "actual_delivery_date": "2024-01-15", "distance_km": "1200"},
            # En cours (pas de date de livraison réelle) : doit être scorée.
            {"shipment_id": "SHP-002", "order_id": "ORD-002", "warehouse_id": "WH-001",
             "transport_mode": "air", "origin": "Paris", "destination": "Berlin",
             "ship_date": "2024-02-02", "expected_delivery_date": "2024-02-10",
             "actual_delivery_date": "", "distance_km": "1200"},
        ])
        transform_gold(db)

        result = predict_at_risk_shipments(db)

        assert result.shipments_scored == 1
        predicted_ids = {p.shipment_id for p in db.query(ShipmentDelayPrediction).all()}
        assert predicted_ids == {"SHP-002"}

        prediction = db.query(ShipmentDelayPrediction).filter_by(shipment_id="SHP-002").one()
        assert prediction.model_name == "dummy_test_model"
        assert 0.0 <= prediction.probability <= 1.0
    finally:
        db.close()


def test_predict_upserts_without_duplicating_on_rerun(dummy_model):
    from app.services.gold_transform import transform_gold

    db = SessionLocal()
    try:
        load_to_silver(db, "suppliers", [
            {"supplier_id": "SUP-001", "name": "Acme", "country": "France",
             "reliability_score": "0.9", "created_at": "2024-01-01"},
        ])
        load_to_silver(db, "products", [
            {"product_id": "PRD-001", "name": "Widget", "category": "electronics",
             "unit_cost": "10.0"},
        ])
        load_to_silver(db, "warehouses", [
            {"warehouse_id": "WH-001", "name": "Paris DC", "country": "France",
             "region": "EMEA", "capacity": "10000"},
        ])
        load_to_silver(db, "orders", [
            {"order_id": "ORD-001", "supplier_id": "SUP-001", "product_id": "PRD-001",
             "warehouse_id": "WH-001", "order_date": "2024-02-01",
             "quantity": "30", "status": "shipped"},
        ])
        load_to_silver(db, "shipments", [
            {"shipment_id": "SHP-001", "order_id": "ORD-001", "warehouse_id": "WH-001",
             "transport_mode": "air", "origin": "Paris", "destination": "Berlin",
             "ship_date": "2024-02-02", "expected_delivery_date": "2024-02-10",
             "actual_delivery_date": "", "distance_km": "1200"},
        ])
        transform_gold(db)

        predict_at_risk_shipments(db)
        predict_at_risk_shipments(db)

        assert db.query(ShipmentDelayPrediction).count() == 1
    finally:
        db.close()
