"""Schéma de l'événement métier shipment_status_updated (Phase 2).

Un seul type d'événement à ce stade, volontairement : le blueprint cite
cet événement comme exemple de flux temps réel ("un vrai flux
d'événements... avec producer et consumer"). Étendre à d'autres types
d'événements (incident déclaré, commande créée) suivra le même schéma,
pas besoin de généraliser prématurément avant d'en avoir un deuxième
cas réel.
"""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ShipmentStatusUpdated(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    shipment_id: str
    previous_status: str | None
    new_status: str
    emitted_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> "ShipmentStatusUpdated":
        return cls.model_validate_json(raw)
