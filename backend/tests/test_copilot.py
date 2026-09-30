"""Tests du Copilot IA (Phase 6).

IMPORTANT : ces tests valident `dispatch_tool_call` — la couche qui
exécute réellement les outils contre les vraies données — PAS un appel
LLM réel. Aucune clé ANTHROPIC_API_KEY n'était disponible dans
l'environnement de développement (api.anthropic.com est cependant
atteignable, contrairement à generativelanguage.googleapis.com/Gemini,
bloqué par le pare-feu réseau de ce sandbox — vérifié explicitement,
cf. ADR-012). `ask_copilot` (la boucle qui appelle réellement le
modèle) n'est donc testée que pour son comportement d'erreur sans clé.
"""

import pytest

from app.copilot.agent import MissingApiKeyError, ask_copilot
from app.copilot.tools import TOOL_SCHEMAS, UnknownToolError, dispatch_tool_call
from app.core.database import SessionLocal
from app.services.gold_transform import transform_gold


def test_tool_schemas_are_well_formed():
    names = {t["name"] for t in TOOL_SCHEMAS}
    assert names == {
        "get_overview_kpis", "get_supplier_performance",
        "get_at_risk_shipments", "search_incidents",
    }
    for tool in TOOL_SCHEMAS:
        assert "description" in tool and tool["description"]
        assert tool["input_schema"]["type"] == "object"


def test_dispatch_unknown_tool_raises():
    db = SessionLocal()
    try:
        with pytest.raises(UnknownToolError):
            dispatch_tool_call(db, "not_a_real_tool", {})
    finally:
        db.close()


def test_dispatch_overview_kpis_returns_real_data(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        transform_gold(db)
        result = dispatch_tool_call(db, "get_overview_kpis", {})
        assert result["total_shipments"] == 1
        assert "on_time_delivery_rate" in result
    finally:
        db.close()


def test_dispatch_supplier_performance_respects_limit(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        transform_gold(db)
        result = dispatch_tool_call(db, "get_supplier_performance", {"limit": 1})
        assert len(result) <= 1
        if result:
            assert result[0]["supplier_id"] == "SUP-001"
    finally:
        db.close()


def test_dispatch_at_risk_shipments_returns_list(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        transform_gold(db)
        result = dispatch_tool_call(db, "get_at_risk_shipments", {"limit": 5})
        assert isinstance(result, list)  # SHP-001 déjà livrée : liste vide attendue ici
    finally:
        db.close()


def test_dispatch_search_incidents_uses_query():
    db = SessionLocal()
    try:
        result = dispatch_tool_call(db, "search_incidents", {"query": "storm", "limit": 3})
        assert isinstance(result, list)
    finally:
        db.close()


def test_ask_copilot_raises_clear_error_without_api_key(monkeypatch):
    from app.copilot import agent as agent_module

    monkeypatch.setattr(agent_module, "get_settings", lambda: type(
        "S", (), {"anthropic_api_key": None}
    )())
    db = SessionLocal()
    try:
        with pytest.raises(MissingApiKeyError):
            ask_copilot(db, "Quels fournisseurs sont à risque ?")
    finally:
        db.close()
