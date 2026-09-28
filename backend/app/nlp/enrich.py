"""Enrichissement des incidents : type prédit + entités extraites."""

from dataclasses import dataclass

import joblib
from sqlalchemy.orm import Session

from app.models.incident_insights import IncidentInsight
from app.models.silver import SilverIncident
from app.nlp.classify import CLASSIFIER_PATH
from app.nlp.extract import extract_entities
from app.nlp.text import normalize_text


class ClassifierNotTrainedError(RuntimeError):
    pass


@dataclass
class EnrichmentResult:
    incidents_enriched: int
    with_duration: int
    with_location: int


def enrich_incidents(db: Session) -> EnrichmentResult:
    if not CLASSIFIER_PATH.exists():
        raise ClassifierNotTrainedError(
            f"Aucun classifieur trouvé ({CLASSIFIER_PATH}). "
            "Exécutez `python -m app.cli train-incident-classifier` d'abord."
        )
    pipeline = joblib.load(CLASSIFIER_PATH)

    incidents = db.query(SilverIncident).filter(SilverIncident.description.isnot(None)).all()
    if not incidents:
        return EnrichmentResult(0, 0, 0)

    texts = [normalize_text(i.description) for i in incidents]
    probabilities = pipeline.predict_proba(texts)
    classes = pipeline.classes_

    existing = {r.incident_id: r for r in db.query(IncidentInsight).all()}
    with_duration = with_location = 0
    for incident, proba in zip(incidents, probabilities, strict=True):
        entities = extract_entities(incident.description)
        best = int(proba.argmax())
        values = dict(
            predicted_type=str(classes[best]),
            type_confidence=round(float(proba[best]), 4),
            duration_days=entities.duration_days,
            location=entities.location,
            shipment_ref=entities.shipment_ref,
        )
        with_duration += entities.duration_days is not None
        with_location += entities.location is not None
        row = existing.get(incident.incident_id)
        if row:
            for k, v in values.items():
                setattr(row, k, v)
        else:
            db.add(IncidentInsight(incident_id=incident.incident_id, **values))
    db.commit()
    return EnrichmentResult(len(incidents), with_duration, with_location)
