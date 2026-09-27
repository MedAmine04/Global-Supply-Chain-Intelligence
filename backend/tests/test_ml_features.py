"""Tests de app/ml/features.py — la garantie la plus importante de ce
module est l'absence de fuite temporelle (cf. docstring du module) :
une feature "historique" ne doit jamais utiliser l'expédition courante
ni une expédition future du même fournisseur."""

from app.core.database import SessionLocal
from app.ml.features import build_feature_dataset
from tests.conftest import load_to_silver


def _build_two_shipments_same_supplier(db):
    """Deux expéditions du même fournisseur, la première en retard, la
    seconde à l'heure — pour vérifier explicitement que la feature
    historique de la seconde reflète le résultat de la première, jamais
    le sien propre."""
    from app.services.gold_transform import transform_gold

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
         "quantity": "30", "status": "delivered"},
    ])
    load_to_silver(db, "shipments", [
        # Expédition 1 (ship_date la plus ancienne) : EN RETARD
        {"shipment_id": "SHP-001", "order_id": "ORD-001", "warehouse_id": "WH-001",
         "transport_mode": "air", "origin": "Paris", "destination": "Berlin",
         "ship_date": "2024-01-02", "expected_delivery_date": "2024-01-10",
         "actual_delivery_date": "2024-01-20", "distance_km": "1200"},
        # Expédition 2 (ship_date plus récente, même fournisseur) : À L'HEURE
        {"shipment_id": "SHP-002", "order_id": "ORD-002", "warehouse_id": "WH-001",
         "transport_mode": "air", "origin": "Paris", "destination": "Berlin",
         "ship_date": "2024-02-02", "expected_delivery_date": "2024-02-10",
         "actual_delivery_date": "2024-02-09", "distance_km": "1200"},
    ])
    transform_gold(db)


def test_first_shipment_has_no_prior_history():
    db = SessionLocal()
    try:
        _build_two_shipments_same_supplier(db)
        dataset = build_feature_dataset(db, only_undelivered=False)
        row = dataset.df[dataset.df["shipment_id"] == "SHP-001"].iloc[0]

        assert row["supplier_prior_shipment_count"] == 0
        assert pd_isna(row["supplier_delay_rate"])
    finally:
        db.close()


def test_second_shipment_reflects_first_shipment_outcome_not_its_own():
    """LE test critique anti-fuite : SHP-002 est à l'heure, mais son
    supplier_delay_rate doit refléter SHP-001 (en retard), donc valoir
    1.0 — pas 0.0 (ce que donnerait une fuite incluant SHP-002 lui-même
    ou une moyenne mal calculée)."""
    db = SessionLocal()
    try:
        _build_two_shipments_same_supplier(db)
        dataset = build_feature_dataset(db, only_undelivered=False)
        row = dataset.df[dataset.df["shipment_id"] == "SHP-002"].iloc[0]

        assert row["supplier_prior_shipment_count"] == 1
        # reflète SHP-001 (en retard), pas SHP-002 (à l'heure)
        assert row["supplier_delay_rate"] == 1.0
    finally:
        db.close()


def test_feature_dataset_has_expected_columns():
    from app.ml.features import FEATURE_COLUMNS

    db = SessionLocal()
    try:
        _build_two_shipments_same_supplier(db)
        dataset = build_feature_dataset(db, only_undelivered=False)
        for col in FEATURE_COLUMNS:
            assert col in dataset.df.columns
        assert "is_delayed" in dataset.df.columns
        assert dataset.has_target is True
    finally:
        db.close()


def test_only_undelivered_mode_excludes_delivered_shipments():
    db = SessionLocal()
    try:
        _build_two_shipments_same_supplier(db)
        # Les deux expéditions du scénario sont déjà livrées ; en mode
        # only_undelivered, aucune ne doit apparaître.
        dataset = build_feature_dataset(db, only_undelivered=True)
        assert dataset.df.empty or "SHP-001" not in dataset.df["shipment_id"].values
        assert dataset.has_target is False
    finally:
        db.close()


def pd_isna(value) -> bool:
    import pandas as pd
    return bool(pd.isna(value))
