import csv
from datetime import date
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.models.data_quality import DataQualityReport as DataQualityReportModel
from app.models.gold import DimDate, DimSupplier, FactOrder, FactShipment
from app.services.data_quality import run_quality_check
from app.services.gold_transform import transform_gold
from app.services.ingestion import ingest_file
from app.services.silver_transform import transform_batch_to_silver


@pytest.fixture(autouse=True)
def clean_all_tables():
    from app.models.bronze import BRONZE_MODELS
    from app.models.gold import (
        DimProduct,
        DimTransport,
        DimWarehouse,
        FactIncident,
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


def _load_to_silver(db, entity: str, rows: list[dict]) -> None:
    """Petit helper : écrit un CSV temporaire et le fait passer par tout
    le pipeline Bronze -> Quality -> Silver, pour préparer les fixtures
    Gold sans dupliquer la logique des couches précédentes."""
    import tempfile

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


@pytest.fixture
def full_supply_chain_scenario():
    """Un scénario minimal mais complet : 1 supplier, 1 product, 1
    warehouse, 1 order, 1 shipment en retard, 1 incident."""
    db = SessionLocal()
    try:
        _load_to_silver(db, "suppliers", [
            {"supplier_id": "SUP-001", "name": "Acme", "country": "France",
             "reliability_score": "0.9", "created_at": "2024-01-01"},
        ])
        _load_to_silver(db, "products", [
            {"product_id": "PRD-001", "name": "Widget", "category": "electronics",
             "unit_cost": "10.0"},
        ])
        _load_to_silver(db, "warehouses", [
            {"warehouse_id": "WH-001", "name": "Paris DC", "country": "France",
             "region": "EMEA", "capacity": "10000"},
        ])
        _load_to_silver(db, "orders", [
            {"order_id": "ORD-001", "supplier_id": "SUP-001", "product_id": "PRD-001",
             "warehouse_id": "WH-001", "order_date": "2024-03-01",
             "quantity": "50", "status": "delivered"},
        ])
        _load_to_silver(db, "shipments", [
            {"shipment_id": "SHP-001", "order_id": "ORD-001", "warehouse_id": "WH-001",
             "transport_mode": "air", "origin": "Paris", "destination": "Berlin",
             "ship_date": "2024-03-02", "expected_delivery_date": "2024-03-10",
             "actual_delivery_date": "2024-03-15", "distance_km": "1200"},
        ])
        _load_to_silver(db, "incidents", [
            {"incident_id": "INC-001", "shipment_id": "SHP-001", "incident_type": "CUSTOMS_DELAY",
             "description": "Customs held the shipment.", "incident_date": "2024-03-08",
             "severity": "medium"},
        ])
    finally:
        db.close()


def test_gold_transform_creates_dimensions_and_facts(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        result = transform_gold(db)

        assert result.tables["dim_supplier"]["created"] == 1
        assert result.tables["fact_orders"]["created"] == 1
        assert result.tables["fact_shipments"]["created"] == 1
        assert result.tables["fact_incidents"]["created"] == 1
        assert result.tables["fact_orders"]["skipped"] == 0
    finally:
        db.close()


def test_gold_transform_computes_delay_correctly(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        transform_gold(db)
        shipment = db.query(FactShipment).filter_by(shipment_id="SHP-001").one()
        assert shipment.is_delayed is True
        assert shipment.delay_days == 5  # 2024-03-15 - 2024-03-10
    finally:
        db.close()


def test_gold_transform_populates_dim_date_covering_all_dates(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        transform_gold(db)
        assert db.query(DimDate).filter_by(date=date(2024, 3, 1)).first() is not None
        assert db.query(DimDate).filter_by(date=date(2024, 3, 15)).first() is not None
    finally:
        db.close()


def test_gold_transform_is_idempotent_on_second_run(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        transform_gold(db)
        result2 = transform_gold(db)

        assert result2.tables["dim_supplier"]["created"] == 0
        assert result2.tables["dim_supplier"]["updated"] == 1
        assert result2.tables["fact_orders"]["created"] == 0
        assert result2.tables["fact_orders"]["updated"] == 1

        assert db.query(FactOrder).count() == 1  # pas de doublon
        assert db.query(DimSupplier).count() == 1
    finally:
        db.close()


def test_gold_transform_skips_order_with_dimension_not_yet_loaded():
    """Un ordre dont le fournisseur n'existe pas (encore) en Silver doit
    être ignoré (skipped), pas planter tout le run."""
    db = SessionLocal()
    try:
        _load_to_silver(db, "warehouses", [
            {"warehouse_id": "WH-001", "name": "Paris DC", "country": "France",
             "region": "EMEA", "capacity": "10000"},
        ])
        result = transform_gold(db)
        assert result.tables["fact_orders"] == {"created": 0, "updated": 0, "skipped": 0}
    finally:
        db.close()
