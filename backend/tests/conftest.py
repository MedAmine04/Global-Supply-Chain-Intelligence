import csv
import tempfile
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.services.data_quality import run_quality_check
from app.services.ingestion import ingest_file
from app.services.silver_transform import transform_batch_to_silver


def load_to_silver(db, entity: str, rows: list[dict]) -> None:
    """Fait passer des lignes par tout le pipeline Bronze -> Quality ->
    Silver, pour préparer des fixtures Gold/API sans dupliquer la logique
    des couches précédentes dans chaque fichier de test."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        path = Path(f.name)

    ingestion = ingest_file(db, entity, path)
    run_quality_check(db, entity, ingestion.batch_id)
    transform_batch_to_silver(db, entity, ingestion.batch_id)
    path.unlink()


@pytest.fixture(scope="session")
def spark_session():
    """SparkSession partagée pour toute la suite de tests : la démarrer
    coûte 2-3 secondes, la recréer par test ralentirait inutilement toute
    la suite."""
    from app.services.spark_transform import get_spark

    session = get_spark()
    yield session
    session.stop()


@pytest.fixture(autouse=True)
def clean_all_tables():
    from app.models.bronze import BRONZE_MODELS
    from app.models.data_quality import DataQualityReport as DataQualityReportModel
    from app.models.gold import (
        DimDate,
        DimProduct,
        DimSupplier,
        DimTransport,
        DimWarehouse,
        FactIncident,
        FactOrder,
        FactShipment,
    )
    from app.models.silver import SILVER_MODELS

    db = SessionLocal()
    for model in [FactIncident, FactShipment, FactOrder]:
        db.query(model).delete()
    for model in [DimSupplier, DimProduct, DimWarehouse, DimTransport, DimDate]:
        db.query(model).delete()
    for model in BRONZE_MODELS.values():
        db.query(model).delete()
    for model in SILVER_MODELS.values():
        db.query(model).delete()
    db.query(DataQualityReportModel).delete()
    from app.models.incident_insights import IncidentInsight

    db.query(IncidentInsight).delete()
    db.commit()
    db.close()
    yield


def _select_no_columns(df):
    """Fonction nommée au niveau MODULE (ni lambda, ni fonction imbriquée
    dans une fixture) : joblib/pickle ne sait sérialiser que des objets
    accessibles par leur nom qualifié depuis le module — nécessaire
    puisque le pipeline factice de `dummy_model` est sauvegardé sur
    disque comme le serait un vrai modèle."""
    return df[[]]


@pytest.fixture
def dummy_model(tmp_path, monkeypatch):
    """Un pipeline scikit-learn factice mais valide (respecte l'interface
    predict/predict_proba attendue), prédisant toujours "pas de retard" —
    suffisant pour tester le câblage du scoring ML sans entraîner un
    vrai modèle à chaque test (trop lent, redondant avec test_ml_train.py)."""
    import json

    import joblib
    import pandas as pd
    from sklearn.dummy import DummyClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import FunctionTransformer

    from app.ml.features import FEATURE_COLUMNS
    from app.services import ml_predict

    pipeline = Pipeline([
        ("identity", FunctionTransformer(_select_no_columns)),
        ("model", DummyClassifier(strategy="constant", constant=0)),
    ])
    dummy_X = pd.DataFrame({c: [0, 1] for c in FEATURE_COLUMNS})
    pipeline.fit(dummy_X[[]], [0, 1])

    model_path = tmp_path / "shipment_delay_model.joblib"
    joblib.dump(pipeline, model_path)
    (tmp_path / "model_metadata.json").write_text(
        json.dumps({"model_name": "dummy_test_model"})
    )

    monkeypatch.setattr(ml_predict, "MODEL_PATH", model_path)
    monkeypatch.setattr(ml_predict, "METADATA_PATH", tmp_path / "model_metadata.json")
    return pipeline


@pytest.fixture
def full_supply_chain_scenario():
    """Un scénario minimal mais complet : 1 supplier, 1 product, 1
    warehouse, 1 order, 1 shipment en retard, 1 incident."""
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
             "warehouse_id": "WH-001", "order_date": "2024-03-01",
             "quantity": "50", "status": "delivered"},
        ])
        load_to_silver(db, "shipments", [
            {"shipment_id": "SHP-001", "order_id": "ORD-001", "warehouse_id": "WH-001",
             "transport_mode": "air", "origin": "Paris", "destination": "Berlin",
             "ship_date": "2024-03-02", "expected_delivery_date": "2024-03-10",
             "actual_delivery_date": "2024-03-15", "distance_km": "1200"},
        ])
        load_to_silver(db, "incidents", [
            {"incident_id": "INC-001", "shipment_id": "SHP-001", "incident_type": "CUSTOMS_DELAY",
             "description": "Customs held the shipment.", "incident_date": "2024-03-08",
             "severity": "medium"},
        ])
    finally:
        db.close()
