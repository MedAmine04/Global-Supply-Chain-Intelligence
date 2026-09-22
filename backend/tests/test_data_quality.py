import csv
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.models.data_quality import DataQualityReport as DataQualityReportModel
from app.services.data_quality import run_quality_check
from app.services.ingestion import ingest_file


@pytest.fixture(autouse=True)
def clean_tables():
    from app.models.bronze import BRONZE_MODELS

    db = SessionLocal()
    for model in BRONZE_MODELS.values():
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
        writer.writerow(["SUP-002", "Beta Ltd", "Germany", "N/A", "2024-02-01"])  # score invalide
        writer.writerow(["SUP-003", "", "Spain", "0.5", "2024-03-01"])  # name manquant
        writer.writerow(  # doublon d'ID
            ["SUP-001", "Acme Corp Duplicate", "France", "0.9", "2024-01-05"]
        )
        writer.writerow(["SUP-004", "Delta Inc", "Italy", "1.5", "2024-04-01"])  # score hors plage
    return file_path


@pytest.fixture
def orders_with_bad_fk_csv(tmp_path: Path) -> Path:
    file_path = tmp_path / "orders.csv"
    with file_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "order_id", "supplier_id", "product_id", "warehouse_id",
            "order_date", "quantity", "status",
        ])
        writer.writerow(["ORD-001", "SUP-999", "PRD-999", "WH-999", "2024-01-01", "10", "pending"])
    return file_path


def test_quality_check_detects_missing_required_field(suppliers_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "suppliers", suppliers_csv)
        report = run_quality_check(db, "suppliers", ingestion.batch_id)
        assert report.issues["missing_required_fields"]["name"] == 1
    finally:
        db.close()


def test_quality_check_detects_duplicate_ids(suppliers_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "suppliers", suppliers_csv)
        report = run_quality_check(db, "suppliers", ingestion.batch_id)
        assert report.issues["duplicate_ids"] == 1  # 2 lignes SUP-001 -> 1 doublon
    finally:
        db.close()


def test_quality_check_detects_invalid_numeric_range(suppliers_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "suppliers", suppliers_csv)
        report = run_quality_check(db, "suppliers", ingestion.batch_id)
        # "N/A" (non convertible) + 1.5 (hors [0,1]) = 2 valeurs invalides
        assert report.issues["invalid_numeric_fields"]["reliability_score"] == 2
    finally:
        db.close()


def test_quality_check_counts_valid_and_rejected_without_double_counting(suppliers_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "suppliers", suppliers_csv)
        report = run_quality_check(db, "suppliers", ingestion.batch_id)
        assert report.rows_processed == 5
        # SUP-001 valide, SUP-002 (score invalide), SUP-003 (name manquant),
        # SUP-001 doublon, SUP-004 (score hors plage) -> 1 valide, 4 rejetées
        assert report.rows_valid == 1
        assert report.rows_rejected == 4
        assert report.rows_valid + report.rows_rejected == report.rows_processed
    finally:
        db.close()


def test_quality_check_detects_invalid_foreign_key(orders_with_bad_fk_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "orders", orders_with_bad_fk_csv)
        report = run_quality_check(db, "orders", ingestion.batch_id)
        assert report.issues["invalid_foreign_keys"]["supplier_id"] == 1
        assert report.issues["invalid_foreign_keys"]["product_id"] == 1
        assert report.issues["invalid_foreign_keys"]["warehouse_id"] == 1
        assert report.rows_rejected == 1
    finally:
        db.close()


def test_quality_check_persists_report(suppliers_csv: Path):
    db = SessionLocal()
    try:
        ingestion = ingest_file(db, "suppliers", suppliers_csv)
        run_quality_check(db, "suppliers", ingestion.batch_id)

        persisted = (
            db.query(DataQualityReportModel)
            .filter_by(batch_id=ingestion.batch_id, entity="suppliers")
            .one()
        )
        assert persisted.rows_processed == 5
        assert persisted.rows_rejected == 4
        assert "missing_required_fields" in persisted.issues
    finally:
        db.close()


def test_quality_check_empty_batch_returns_zeroed_report():
    db = SessionLocal()
    try:
        report = run_quality_check(db, "suppliers", "batch-that-does-not-exist")
        assert report.rows_processed == 0
        assert report.rows_valid == 0
        assert report.rows_rejected == 0
    finally:
        db.close()
