import csv
from pathlib import Path

import pytest

from app.core.database import SessionLocal
from app.services.ingestion import UnknownEntityError, ingest_directory, ingest_file


@pytest.fixture(autouse=True)
def clean_bronze_tables():
    """Vide les tables Bronze avant/après chaque test pour l'isolation.

    On ne recrée pas tout le schéma (les migrations Alembic s'en chargent
    déjà en CI/local) : on tronque juste les tables utilisées par ces tests.
    """
    from app.models.bronze import BRONZE_MODELS

    db = SessionLocal()
    for model in BRONZE_MODELS.values():
        db.query(model).delete()
    db.commit()
    db.close()
    yield


@pytest.fixture
def suppliers_csv(tmp_path: Path) -> Path:
    file_path = tmp_path / "suppliers.csv"
    with file_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["supplier_id", "name", "country", "reliability_score", "created_at"])
        writer.writerow(["SUP-001", "Acme Corp", "France", "0.87", "2024-01-01"])
        writer.writerow(["SUP-002", "Beta Ltd", "Germany", "N/A", "2024-02-01"])
        writer.writerow(["SUP-003", "Gamma Inc", "Spain", "", "2024-03-01"])
    return file_path


def test_ingest_file_loads_all_rows(suppliers_csv: Path):
    db = SessionLocal()
    try:
        result = ingest_file(db, "suppliers", suppliers_csv)
        assert result.success
        assert result.rows_read == 3
        assert result.rows_ingested == 3
    finally:
        db.close()


def test_ingest_file_preserves_dirty_values_unchanged(suppliers_csv: Path):
    """Bronze ne doit ni corriger ni rejeter les valeurs sales : il les stocke telles quelles."""
    from app.models.bronze import BronzeSupplier

    db = SessionLocal()
    try:
        ingest_file(db, "suppliers", suppliers_csv)
        rows = {r.supplier_id: r.reliability_score for r in db.query(BronzeSupplier).all()}
        assert rows["SUP-001"] == "0.87"
        assert rows["SUP-002"] == "N/A"  # valeur "sale" préservée telle quelle
        assert rows["SUP-003"] is None  # cellule vide -> None, pas une chaîne vide
    finally:
        db.close()


def test_ingest_file_records_traceability_metadata(suppliers_csv: Path):
    from app.models.bronze import BronzeSupplier

    db = SessionLocal()
    try:
        result = ingest_file(db, "suppliers", suppliers_csv)
        row = db.query(BronzeSupplier).filter_by(supplier_id="SUP-001").one()
        assert row.batch_id == result.batch_id
        assert str(suppliers_csv) in row.source_file
        assert row.row_number == 1
        assert row.ingested_at is not None
    finally:
        db.close()


def test_ingest_file_unknown_entity_raises(suppliers_csv: Path):
    db = SessionLocal()
    try:
        with pytest.raises(UnknownEntityError):
            ingest_file(db, "not_an_entity", suppliers_csv)
    finally:
        db.close()


def test_ingest_directory_only_ingests_recognized_files(tmp_path: Path, suppliers_csv: Path):
    # Copie le fichier suppliers dans tmp_path (déjà présent car fixture),
    # et vérifie qu'un fichier non reconnu est simplement ignoré.
    (tmp_path / "random_notes.csv").write_text("not,a,real,entity\n")

    db = SessionLocal()
    try:
        results = ingest_directory(db, tmp_path)
        entities = {r.entity for r in results}
        assert entities == {"suppliers"}
    finally:
        db.close()
