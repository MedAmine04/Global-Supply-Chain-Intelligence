"""Consumer Kafka (Phase 2).

Deux fonctions séparées volontairement :
- `apply_shipment_status_event` : la logique métier + l'idempotence, pure
  fonction de (session DB, événement) -> résultat. Ne dépend d'aucune
  API Kafka : testable sans broker réel (cf. tests/test_kafka_consumer.py).
- `run_consumer_loop` : la boucle de polling Kafka elle-même, qui
  délègue chaque message à `apply_shipment_status_event`. C'est la seule
  partie qui nécessite un vrai broker et n'a donc pas pu être exécutée
  dans ce sandbox (cf. ADR-007) — sa correction repose sur celle de
  `apply_shipment_status_event`, qui elle est testée.

Idempotence : Kafka ne garantit qu'une livraison "at-least-once" côté
consumer (redémarrage, rebalance de partition, retry applicatif peuvent
tous causer une redélivraison). `apply_shipment_status_event` vérifie
`event_id` contre `processed_events` avant d'appliquer quoi que ce soit :
un événement déjà traité est un no-op, jamais réappliqué.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.events.schemas import ShipmentStatusUpdated
from app.models.events import ProcessedEvent
from app.models.gold import FactShipment

logger = logging.getLogger(__name__)


@dataclass
class EventProcessingResult:
    event_id: str
    applied: bool  # False si déjà traité (idempotence) ou shipment inconnu
    reason: str | None = None


def apply_shipment_status_event(db: Session, event: ShipmentStatusUpdated) -> EventProcessingResult:
    already_processed = db.query(ProcessedEvent).filter_by(event_id=event.event_id).first()
    if already_processed:
        return EventProcessingResult(event.event_id, applied=False, reason="already_processed")

    shipment = db.query(FactShipment).filter_by(shipment_id=event.shipment_id).first()
    if shipment is None:
        # On enregistre quand même l'event_id comme traité : un shipment
        # inconnu aujourd'hui ne doit pas faire retraiter cet événement
        # indéfiniment à chaque nouveau poll — cf. ADR-007 pour la
        # discussion de ce choix (vs. dead-letter queue, hors périmètre
        # à ce stade).
        db.add(ProcessedEvent(event_id=event.event_id, topic="shipment_status_updated"))
        db.commit()
        return EventProcessingResult(event.event_id, applied=False, reason="unknown_shipment")

    shipment.status = event.new_status
    db.add(ProcessedEvent(event_id=event.event_id, topic="shipment_status_updated"))
    db.commit()

    return EventProcessingResult(event.event_id, applied=True)


def run_consumer_loop(
    db_session_factory, max_messages: int | None = None, timeout: float = 5.0
) -> int:
    """Boucle de consommation réelle. Nécessite un broker Kafka
    accessible (cf. docstring module) — non exécutée dans ce sandbox."""
    from confluent_kafka import Consumer

    settings = get_settings()
    consumer = Consumer({
        "bootstrap.servers": settings.kafka_bootstrap_servers,
        "group.id": "gsci-shipment-status-consumer",
        "auto.offset.reset": "earliest",
    })
    consumer.subscribe([settings.kafka_shipment_status_topic])

    processed_count = 0
    try:
        while max_messages is None or processed_count < max_messages:
            msg = consumer.poll(timeout=timeout)
            if msg is None:
                break
            if msg.error():
                logger.error("Erreur consumer Kafka: %s", msg.error())
                continue

            event = ShipmentStatusUpdated.from_json(msg.value())
            db = db_session_factory()
            try:
                result = apply_shipment_status_event(db, event)
                logger.info("Événement %s traité (applied=%s)", result.event_id, result.applied)
            finally:
                db.close()

            consumer.commit(msg)
            processed_count += 1
    finally:
        consumer.close()

    return processed_count
