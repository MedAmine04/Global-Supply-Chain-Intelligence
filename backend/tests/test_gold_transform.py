from datetime import date

from app.core.database import SessionLocal
from app.models.gold import DimDate, DimSupplier, FactOrder, FactShipment
from app.services.gold_transform import transform_gold
from tests.conftest import load_to_silver


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
        load_to_silver(db, "warehouses", [
            {"warehouse_id": "WH-001", "name": "Paris DC", "country": "France",
             "region": "EMEA", "capacity": "10000"},
        ])
        result = transform_gold(db)
        assert result.tables["fact_orders"] == {"created": 0, "updated": 0, "skipped": 0}
    finally:
        db.close()
