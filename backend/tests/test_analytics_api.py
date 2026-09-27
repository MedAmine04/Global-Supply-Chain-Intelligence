from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.services.gold_transform import transform_gold

client = TestClient(app)


def _run_gold():
    db = SessionLocal()
    try:
        transform_gold(db)
    finally:
        db.close()


def test_overview_kpis_reflect_scenario(full_supply_chain_scenario):
    _run_gold()
    response = client.get("/api/kpis/overview")
    assert response.status_code == 200
    body = response.json()

    assert body["total_orders"] == 1
    assert body["total_shipments"] == 1
    assert body["delivered_shipments"] == 1
    assert body["on_time_delivery_rate"] == 0.0  # la seule expédition est en retard
    assert body["average_delay_days"] == 5.0
    assert body["incident_rate"] == 100.0  # 1 expédition, 1 incident dessus


def test_overview_kpis_empty_database_returns_zeros():
    response = client.get("/api/kpis/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["total_orders"] == 0
    assert body["on_time_delivery_rate"] == 0.0
    assert body["average_delay_days"] is None


def test_supplier_performance_reflects_scenario(full_supply_chain_scenario):
    _run_gold()
    response = client.get("/api/suppliers/performance")
    assert response.status_code == 200
    body = response.json()

    assert len(body) == 1
    supplier = body[0]
    assert supplier["supplier_id"] == "SUP-001"
    assert supplier["total_shipments"] == 1
    assert supplier["delayed_shipments"] == 1
    assert supplier["delay_rate"] == 100.0
    assert supplier["incident_count"] == 1


def test_region_transport_breakdown_reflects_scenario(full_supply_chain_scenario):
    _run_gold()
    response = client.get("/api/analysis/region-transport")
    assert response.status_code == 200
    body = response.json()

    assert len(body) == 1
    assert body[0]["region"] == "EMEA"
    assert body[0]["transport_mode"] == "air"
    assert body[0]["total_shipments"] == 1
    assert body[0]["delayed_shipments"] == 1


def test_at_risk_predictions_endpoint_returns_scored_shipments(
    full_supply_chain_scenario, dummy_model
):
    from app.services.ml_predict import predict_at_risk_shipments

    _run_gold()

    # Le scénario partagé (SHP-001) est déjà livré, donc jamais scoré ;
    # ce test porte sur le câblage API -> service -> repository, pas sur
    # la présence de résultats (déjà couvert par test_ml_predict.py).
    db = SessionLocal()
    try:
        predict_at_risk_shipments(db)
    finally:
        db.close()

    response = client.get("/api/predictions/at-risk?limit=5")
    assert response.status_code == 200
    assert response.json() == []  # aucune expédition en cours dans ce scénario
