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
    db.commit()
    db.close()
    yield


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
