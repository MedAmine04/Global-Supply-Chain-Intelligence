"""Outils exposés au Copilot IA (Phase 6).

Chaque outil appelle directement les services déjà écrits et testés
(analytics, ml_predict, nlp.search) — le Copilot ne recalcule ni
n'invente jamais un chiffre, il ne fait que choisir quel outil appeler
et mettre en forme sa réponse à partir du résultat réel (cf. principe
du blueprint : "L'IA ne doit pas inventer les chiffres").
"""

from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_overview_kpis",
        "description": (
            "KPI globaux de la supply chain : commandes, expéditions, "
            "taux de livraison à l'heure, délai moyen, taux d'incidents."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_supplier_performance",
        "description": "Performance par fournisseur, triée par taux de retard décroissant.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Nombre de fournisseurs (défaut 10)"}
            },
        },
    },
    {
        "name": "get_at_risk_shipments",
        "description": (
            "Expéditions en cours les plus à risque de retard, "
            "selon le modèle de prédiction ML (probabilité décroissante)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Nombre d'expéditions (défaut 10)"}
            },
        },
    },
    {
        "name": "search_documents",
        "description": (
            "Recherche dans les documents internes (contrats fournisseurs, "
            "politique de transport, politique qualité des données) pour "
            "répondre à une question contractuelle ou de politique interne."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question ou termes de recherche"},
                "limit": {"type": "integer", "description": "Nombre de passages (défaut 3)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_incidents",
        "description": "Recherche textuelle dans les descriptions d'incidents logistiques.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Termes de recherche"},
                "limit": {"type": "integer", "description": "Nombre de résultats (défaut 5)"},
            },
            "required": ["query"],
        },
    },
]


class UnknownToolError(ValueError):
    pass


def dispatch_tool_call(db: Session, tool_name: str, tool_input: dict) -> Any:
    """Exécute l'outil demandé et retourne un résultat JSON-sérialisable.

    Aucune logique métier ici : chaque branche appelle une fonction déjà
    testée ailleurs (services/analytics.py, services/ml_predict.py,
    nlp/search.py) — ce module ne fait que le pont entre le nom d'outil
    choisi par le LLM et l'appel réel."""
    if tool_name == "get_overview_kpis":
        from app.services.analytics import get_overview_kpis

        return get_overview_kpis(db).model_dump()

    if tool_name == "get_supplier_performance":
        from app.services.analytics import get_supplier_performance

        limit = tool_input.get("limit", 10)
        return [s.model_dump() for s in get_supplier_performance(db)[:limit]]

    if tool_name == "get_at_risk_shipments":
        from app.services.analytics import get_at_risk_shipments

        limit = tool_input.get("limit", 10)
        return [s.model_dump() for s in get_at_risk_shipments(db, limit=limit)]

    if tool_name == "search_incidents":
        from app.nlp.search import search_incidents

        hits = search_incidents(db, tool_input["query"], limit=tool_input.get("limit", 5))
        return [asdict(h) for h in hits]

    if tool_name == "search_documents":
        from app.rag.retrieval import retrieve_relevant_chunks

        hits = retrieve_relevant_chunks(tool_input["query"], limit=tool_input.get("limit", 3))
        return [asdict(h) for h in hits]

    raise UnknownToolError(f"Outil inconnu : '{tool_name}'")
