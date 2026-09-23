"""Table de traçabilité des événements Kafka consommés (Phase 2).

Kafka garantit au mieux une livraison "at-least-once" côté consumer (un
même message peut être relivré après un redémarrage, un rebalance de
partition, ou un retry applicatif). Sans dédoublonnage explicite, un
même événement pourrait être appliqué deux fois — par exemple mettre à
jour deux fois le statut d'une expédition, ou déclencher deux fois une
alerte. Cette table rend le traitement idempotent : un `event_id` déjà
présent ici n'est plus jamais réappliqué (cf. ADR-007).
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
