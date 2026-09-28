"""Prétraitement partagé des descriptions d'incidents (Phase 4)."""

import re

SHIPMENT_ID_PATTERN = re.compile(r"\bSHP-\d+\b")


def normalize_text(text: str | None) -> str:
    """Minuscule + remplacement des identifiants d'expédition par un jeton
    neutre : l'identifiant exact ("SHP-0000123") est un bruit unique par
    incident, pas un indice du type d'incident — le laisser dans le texte
    ferait apprendre au classifieur des identifiants par cœur."""
    if not text:
        return ""
    return SHIPMENT_ID_PATTERN.sub("shpid", text).lower()
