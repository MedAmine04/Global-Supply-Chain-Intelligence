"""Extraction d'entités des descriptions d'incidents (NER hybride).

- Référence d'expédition : expression régulière (format d'ID connu, plus
  fiable qu'un modèle statistique sur un identifiant métier).
- Durée : règle sur "<nombre|mot> day(s)" — un modèle NER général
  (spaCy) détecte bien "three days" comme DATE, mais ne fournit pas la
  valeur numérique ; on la calcule donc par règle.
- Lieu : entités GPE/LOC/FAC de spaCy (`en_core_web_sm`).
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from app.nlp.text import SHIPMENT_ID_PATTERN

WORD_TO_NUMBER = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
DURATION_PATTERN = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven)\s+days?\b", re.IGNORECASE
)


@dataclass
class ExtractedEntities:
    shipment_ref: str | None
    duration_days: int | None
    location: str | None


@lru_cache(maxsize=1)
def _nlp():
    import spacy

    return spacy.load("en_core_web_sm", disable=["lemmatizer", "parser"])


def extract_duration_days(text: str) -> int | None:
    match = DURATION_PATTERN.search(text or "")
    if not match:
        return None
    token = match.group(1).lower()
    return int(token) if token.isdigit() else WORD_TO_NUMBER[token]


def extract_shipment_ref(text: str) -> str | None:
    match = SHIPMENT_ID_PATTERN.search(text or "")
    return match.group(0) if match else None


def extract_location(text: str) -> str | None:
    doc = _nlp()(text or "")
    for ent in doc.ents:
        if ent.label_ in ("GPE", "LOC", "FAC"):
            return ent.text
    return None


def extract_entities(text: str) -> ExtractedEntities:
    return ExtractedEntities(
        shipment_ref=extract_shipment_ref(text),
        duration_days=extract_duration_days(text),
        location=extract_location(text),
    )
