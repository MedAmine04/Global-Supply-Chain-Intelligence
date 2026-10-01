"""Tests du module RAG (Phase 7).

Récupération lexicale (TF-IDF), pas sémantique — mêmes limites et même
choix que pour la recherche d'incidents (ADR-010), documentées dans
ADR-013. Ces tests vérifient que les bonnes sections sont retrouvées
pour des questions directement liées à leur contenu, pas une
compréhension fine du langage.
"""

from app.rag.retrieval import load_and_chunk_corpus, retrieve_relevant_chunks


def test_corpus_loads_with_sections():
    chunks = load_and_chunk_corpus()
    assert len(chunks) > 5
    assert all(c.text for c in chunks)
    assert all(c.section and not c.section.startswith("#") for c in chunks)


def test_retrieve_finds_late_delivery_penalty_section():
    hits = retrieve_relevant_chunks("What happens if a supplier delivers more than five days late?")
    assert hits
    assert "Late Delivery Penalties" in hits[0].section
    assert hits[0].source == "supplier_contract_template.md"


def test_retrieve_finds_warehouse_congestion_definition():
    hits = retrieve_relevant_chunks("how is warehouse congestion defined")
    assert hits
    assert hits[0].section == "Warehouse Congestion"


def test_retrieve_empty_query_returns_nothing():
    assert retrieve_relevant_chunks("   ") == []


def test_retrieve_respects_limit():
    hits = retrieve_relevant_chunks("delivery supplier shipment", limit=2)
    assert len(hits) <= 2
