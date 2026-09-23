from app.core.database import SessionLocal
from app.models.gold import FactShipment
from app.services.gold_transform import (
    transform_dim_date,
    transform_dim_supplier,
    transform_dim_transport,
    transform_dim_warehouse,
)
from app.services.gold_transform import (
    transform_dim_product as orm_transform_dim_product,
)
from app.services.gold_transform import (
    transform_fact_shipments as orm_transform_fact_shipments,
)
from app.services.spark_transform import transform_fact_shipments_spark


def _build_dimensions(db):
    """Prépare les dimensions (préalable commun aux deux implémentations
    de fact_shipments, ORM et Spark) sans dupliquer gold_transform."""
    from datetime import date

    transform_dim_date(db, date(2024, 1, 1), date(2024, 12, 31))
    transform_dim_supplier(db)
    orm_transform_dim_product(db)
    transform_dim_warehouse(db)
    transform_dim_transport(db)


def test_spark_transform_matches_orm_transform_on_same_scenario(
    full_supply_chain_scenario, spark_session
):
    """La garantie la plus importante de ce module : les deux
    implémentations (ORM Python pur vs Spark DataFrame API) doivent
    produire un résultat strictement identique sur les mêmes données."""
    db = SessionLocal()
    try:
        _build_dimensions(db)
        orm_result = orm_transform_fact_shipments(db)
        orm_shipment = db.query(FactShipment).filter_by(shipment_id="SHP-001").one()
        orm_snapshot = {
            "is_delayed": orm_shipment.is_delayed,
            "delay_days": orm_shipment.delay_days,
            "supplier_sk": orm_shipment.supplier_sk,
            "warehouse_sk": orm_shipment.warehouse_sk,
            "transport_sk": orm_shipment.transport_sk,
        }

        db.query(FactShipment).delete()
        db.commit()

        spark_result = transform_fact_shipments_spark(db)
        spark_shipment = db.query(FactShipment).filter_by(shipment_id="SHP-001").one()

        assert orm_result["created"] == spark_result.rows_created
        assert orm_result["skipped"] == spark_result.rows_skipped_invalid
        assert spark_shipment.is_delayed == orm_snapshot["is_delayed"]
        assert spark_shipment.delay_days == orm_snapshot["delay_days"]
        assert spark_shipment.supplier_sk == orm_snapshot["supplier_sk"]
        assert spark_shipment.warehouse_sk == orm_snapshot["warehouse_sk"]
        assert spark_shipment.transport_sk == orm_snapshot["transport_sk"]
    finally:
        db.close()


def test_spark_transform_computes_delay_correctly(full_supply_chain_scenario, spark_session):
    db = SessionLocal()
    try:
        _build_dimensions(db)
        transform_fact_shipments_spark(db)
        shipment = db.query(FactShipment).filter_by(shipment_id="SHP-001").one()
        assert shipment.is_delayed is True
        assert shipment.delay_days == 5  # 2024-03-15 - 2024-03-10
    finally:
        db.close()


def test_spark_transform_skips_shipment_with_missing_dimension(spark_session):
    """Une expédition dont le warehouse n'a pas encore de dimension Gold
    doit être ignorée, pas faire planter le job Spark."""
    from tests.conftest import load_to_silver

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
        # Dimensions volontairement NON construites : aucun dim_supplier/
        # dim_warehouse/dim_transport en base.
        result = transform_fact_shipments_spark(db)
        assert result.rows_created == 0
        assert result.rows_skipped_invalid == 1
    finally:
        db.close()


def test_spark_transform_empty_silver_returns_zeroed_result(spark_session):
    db = SessionLocal()
    try:
        result = transform_fact_shipments_spark(db)
        assert result.rows_considered == 0
        assert result.rows_created == 0
    finally:
        db.close()
