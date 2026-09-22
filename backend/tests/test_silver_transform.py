import csv
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.models.data_quality import DataQualityReport as DataQualityReportModel
from app.models.silver import SilverOrder, SilverSupplier
from app.services.data_quality import run_quality_check
from app.services.ingestion import ingest_file
from app.services.silver_transform import QualityCheckMissingError, transform_batch_to_silver


@pytest.fixture(autouse=True)
def clean_tables():
    from app.models.bronze import BRONZE_MODELS
    from app.models.silver import SILVER_MODELS

    db = SessionLocal()
    for model in BRONZE_MODELS.values():
        db.query(model).delete()
    for model in SILVER_MODELS.values():
        db.query(model).delete()
    db.query(DataQualityReportModel).delete()
    db.commit()
    db.close()
    yield


@pytest.fixture
def suppliers_csv(tmp_path: Path) -> Path:
    file_path = tmp_path / "suppliers.csv"
    with file_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["supplier_id", "name", "country", "reliability_score", "created_at"])
        writer.writerow(["SUP-001", "Acme Corp", "France", "0.87", "2024-01-01"])  # valide
        writer.writerow(["SUP-002", "Beta Ltd", "Germany", "N/A", "2024-02-01"])  # rejetée en FR-02
    return file_path


@pytest.fixture
def orders_csv_with_valid_fks(tmp_path: Path) -> Path:
    """Ingère les entités référencées (supplier/product/warehouse) pour que
    la validation FK de FR-02 n'écarte pas la commande à tort, puisque le
    test porte sur le typage Silver, pas sur les FK."""
    db = SessionLocal()
    try:
        sup_file = tmp_path / "suppliers.csv"
        with sup_file.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["supplier_id", "name", "country", "reliability_score", "created_at"])
            w.writerow(["SUP-001", "Acme Corp", "France", "0.9", "2024-01-01"])
        ingest_file(db, "suppliers", sup_file)

        prod_file = tmp_path / "products.csv"
        with prod_file.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["product_id", "name", "category", "unit_cost"])
            w.writerow(["PRD-001", "Widget", "electronics", "10.0"])
        ingest_file(db, "products", prod_file)

        wh_file = tmp_path / "warehouses.csv"
        with wh_file.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["warehouse_id", "name", "country", "region", "capacity"])
            w.writerow(["WH-001", "Paris DC", "France", "EMEA", "10000"])
        ingest_file(db, "warehouses", wh_file)
    finally:
        db.close()

    file_path = tmp_path / "orders.csv"
    with file_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "order_id", "supplier_id", "product_id", "warehouse_id",
            "order_date", "quantity", "status",
        ])
        writer.writerow(
            ["ORD-001", "SUP-001", "PRD-001", "WH-001", "2024-03-15", "42", "delivered"]
        )
    return file_path


def test_transform_requires_prior_quality_check(suppliers_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "suppliers", suppliers_csv)
        with pytest.raises(QualityCheckMissingError):
            transform_batch_to_silver(db, "suppliers", ingestion.batch_id)
    finally:
        db.close()


def test_transform_skips_rows_rejected_by_quality_check(suppliers_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "suppliers", suppliers_csv)
        run_quality_check(db, "suppliers", ingestion.batch_id)
        result = transform_batch_to_silver(db, "suppliers", ingestion.batch_id)

        assert result.rows_considered == 2
        assert result.rows_skipped_invalid == 1  # SUP-002 (reliability_score invalide)
        assert result.rows_created == 1

        silver_ids = {s.supplier_id for s in db.query(SilverSupplier).all()}
        assert silver_ids == {"SUP-001"}
    finally:
        db.close()


def test_transform_casts_types_correctly(orders_csv_with_valid_fks: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "orders", orders_csv_with_valid_fks)
        run_quality_check(db, "orders", ingestion.batch_id)
        transform_batch_to_silver(db, "orders", ingestion.batch_id)

        order = db.query(SilverOrder).filter_by(order_id="ORD-001").one()
        assert order.quantity == 42
        assert isinstance(order.quantity, int)
        assert order.order_date.isoformat() == "2024-03-15"
    finally:
        db.close()


def test_transform_upserts_on_second_run_without_duplicating(suppliers_csv: Path, tmp_path: Path):
    db = SessionLocal()
    try:
        ingestion1 = ingest_file(db, "suppliers", suppliers_csv)
        run_quality_check(db, "suppliers", ingestion1.batch_id)
        transform_batch_to_silver(db, "suppliers", ingestion1.batch_id)

        # Deuxième ingestion : la valeur de SUP-001 change (correction amont).
        updated_csv = tmp_path / "suppliers_v2.csv"
        with updated_csv.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["supplier_id", "name", "country", "reliability_score", "created_at"])
            writer.writerow(["SUP-001", "Acme Corp", "France", "0.99", "2024-01-01"])

        ingestion2 = ingest_file(db, "suppliers", updated_csv)
        run_quality_check(db, "suppliers", ingestion2.batch_id)
        result2 = transform_batch_to_silver(db, "suppliers", ingestion2.batch_id)

        assert result2.rows_created == 0
        assert result2.rows_updated == 1

        all_suppliers = db.query(SilverSupplier).filter_by(supplier_id="SUP-001").all()
        assert len(all_suppliers) == 1  # pas de doublon
        assert all_suppliers[0].reliability_score == 0.99
    finally:
        db.close()


def test_transform_unknown_entity_raises():
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            transform_batch_to_silver(db, "not_an_entity", "whatever")
    finally:
        db.close()
