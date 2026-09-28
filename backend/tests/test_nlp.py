"""Tests du module NLP (Phase 4).

Les scores du classifieur sont mesurés sur du texte généré par gabarits :
ces tests vérifient que le pipeline fonctionne (le classifieur bat
nettement le baseline, l'enrichissement est idempotent), pas qu'il
généraliserait à de vrais textes d'incidents (cf. ADR-010).
"""

import random

import pytest

from app.core.database import SessionLocal
from app.models.incident_insights import IncidentInsight
from app.models.silver import SilverIncident
from app.nlp import classify, enrich
from app.nlp.classify import train_incident_classifier
from app.nlp.enrich import ClassifierNotTrainedError, enrich_incidents
from app.nlp.extract import (
    extract_duration_days,
    extract_location,
    extract_shipment_ref,
)
from app.nlp.search import search_incidents
from app.nlp.text import normalize_text
from app.scripts.generate_synthetic_data import INCIDENT_TYPES, _incident_description


def test_normalize_text_masks_shipment_id_and_lowercases():
    assert normalize_text("Shipment SHP-0000123 Delayed") == "shipment shpid delayed"
    assert normalize_text(None) == ""


@pytest.mark.parametrize("text,expected", [
    ("delayed for three days", 3),
    ("waited 5 days at the border", 5),
    ("held for one day", 1),
    ("goods were damaged", None),
])
def test_extract_duration_days(text, expected):
    assert extract_duration_days(text) == expected


def test_extract_shipment_ref():
    assert extract_shipment_ref("Shipment SHP-0000123 was late") == "SHP-0000123"
    assert extract_shipment_ref("no id here") is None


def test_extract_location_finds_real_city():
    assert extract_location("Customs held the goods in Rotterdam for two days.") == "Rotterdam"


def _add_incidents(db, n_per_type: int = 12) -> None:
    random.seed(7)
    count = 0
    for incident_type in INCIDENT_TYPES:
        for _ in range(n_per_type):
            count += 1
            db.add(SilverIncident(
                source_batch_id="test", incident_id=f"INC-{count:05d}",
                shipment_id=f"SHP-{count:07d}", incident_type=incident_type,
                description=_incident_description(incident_type, f"SHP-{count:07d}"),
                incident_date=None, severity="low",
            ))
    db.commit()


@pytest.fixture
def temp_classifier_path(tmp_path, monkeypatch):
    path = tmp_path / "incident_classifier.joblib"
    monkeypatch.setattr(classify, "CLASSIFIER_PATH", path)
    monkeypatch.setattr(enrich, "CLASSIFIER_PATH", path)
    monkeypatch.setattr(classify, "MLRUNS_DIR", tmp_path / "mlruns")
    return path


def test_classifier_beats_majority_baseline(temp_classifier_path):
    db = SessionLocal()
    try:
        _add_incidents(db)
        result = train_incident_classifier(db)
        assert result.accuracy > result.baseline_accuracy + 0.3
        assert temp_classifier_path.exists()
    finally:
        db.close()


def test_classifier_refuses_tiny_dataset(temp_classifier_path):
    db = SessionLocal()
    try:
        with pytest.raises(ValueError):
            train_incident_classifier(db)
    finally:
        db.close()


def test_enrich_requires_trained_classifier(temp_classifier_path):
    db = SessionLocal()
    try:
        with pytest.raises(ClassifierNotTrainedError):
            enrich_incidents(db)
    finally:
        db.close()


def test_enrich_is_idempotent(temp_classifier_path):
    db = SessionLocal()
    try:
        _add_incidents(db)
        train_incident_classifier(db)
        first = enrich_incidents(db)
        enrich_incidents(db)
        assert first.incidents_enriched == 6 * 12
        assert db.query(IncidentInsight).count() == 6 * 12
    finally:
        db.close()


def test_search_ranks_matching_type_first():
    db = SessionLocal()
    try:
        _add_incidents(db)
        hits = search_incidents(db, "storm heavy snow", limit=3)
        assert hits and all(h.incident_type == "WEATHER" for h in hits)
        assert search_incidents(db, "   ") == []
    finally:
        db.close()
