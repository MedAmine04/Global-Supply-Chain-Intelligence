"""Recherche textuelle d'incidents (TF-IDF + similarité cosinus).

À NE PAS présenter comme une recherche sémantique par embeddings : c'est
une recherche lexicale pondérée (les mots de la requête doivent
apparaître dans les textes, avec leurs bigrammes). Les modèles
d'embeddings (sentence-transformers) sont hébergés sur Hugging Face,
inaccessible depuis l'environnement de développement (cf. ADR-010) ;
l'interface (`search_incidents`) est prévue pour être remplacée par une
implémentation à base d'embeddings/pgvector sans changer les appelants.
"""

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from app.models.silver import SilverIncident
from app.nlp.text import normalize_text


@dataclass
class IncidentSearchHit:
    incident_id: str
    shipment_id: str
    incident_type: str
    description: str
    score: float


def search_incidents(db: Session, query: str, limit: int = 5) -> list[IncidentSearchHit]:
    incidents = db.query(SilverIncident).filter(SilverIncident.description.isnot(None)).all()
    if not incidents or not query.strip():
        return []

    corpus = [normalize_text(i.description) for i in incidents]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    matrix = vectorizer.fit_transform(corpus)
    scores = cosine_similarity(vectorizer.transform([normalize_text(query)]), matrix).ravel()

    ranked = sorted(range(len(incidents)), key=lambda idx: scores[idx], reverse=True)[:limit]
    return [
        IncidentSearchHit(
            incident_id=incidents[i].incident_id,
            shipment_id=incidents[i].shipment_id,
            incident_type=incidents[i].incident_type,
            description=incidents[i].description,
            score=round(float(scores[i]), 4),
        )
        for i in ranked
        if scores[i] > 0
    ]
