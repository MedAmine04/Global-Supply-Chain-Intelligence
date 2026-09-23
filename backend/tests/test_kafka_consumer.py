"""Tests de `apply_shipment_status_event` (Phase 2 — Kafka).

IMPORTANT : ces tests valident la logique métier + idempotence de
`apply_shipment_status_event`, PAS une intégration avec un broker Kafka
réel. Aucun broker n'a pu être installé/exécuté dans ce sandbox
(cf. ADR-007) — `run_consumer_loop` (qui, elle, parle réellement à
Kafka) n'est donc pas testée ici. C'est une limite assumée et
documentée, pas cachée : appeler `apply_shipment_status_event`
directement avec un événement construit à la main est un test honnête
de notre propre code, pas une simulation déguisée d'un broker.
"""

import pytest

from app.core.database import SessionLocal
from app.events.schemas import ShipmentStatusUpdated
from app.models.events import ProcessedEvent
from app.services.kafka_consumer import apply_shipment_status_event


@pytest.fixture(autouse=True)
def clean_events_table():
    db = SessionLocal()
    db.query(ProcessedEvent).delete()
    db.commit()
    db.close()
    yield


def test_apply_event_updates_shipment_status(full_supply_chain_scenario):
    """full_supply_chain_scenario (conftest) prépare SHP-001 en Silver,
    mais pas encore en Gold : on construit donc aussi le fait Gold ici
    pour avoir un FactShipment à mettre à jour."""
    from app.services.gold_transform import transform_gold

    db = SessionLocal()
    try:
        transform_gold(db)

        event = ShipmentStatusUpdated(
            shipment_id="SHP-001", previous_status=None, new_status="delayed_customs"
        )
        result = apply_shipment_status_event(db, event)

        assert result.applied is True
        from app.models.gold import FactShipment
        shipment = db.query(FactShipment).filter_by(shipment_id="SHP-001").one()
        assert shipment.status == "delayed_customs"
    finally:
        db.close()


def test_apply_event_is_idempotent_on_replay(full_supply_chain_scenario):
    """Le coeur de la garantie Kafka 'at-least-once' + idempotence :
    rejouer le même event_id ne doit PAS réappliquer le changement une
    deuxième fois (même si un troisième événement, différent, changeait
    entre-temps le statut)."""
    from app.services.gold_transform import transform_gold

    db = SessionLocal()
    try:
        transform_gold(db)

        event = ShipmentStatusUpdated(
            shipment_id="SHP-001", previous_status=None, new_status="delayed_customs"
        )

        first = apply_shipment_status_event(db, event)
        assert first.applied is True

        # Rejouer EXACTEMENT le même événement (même event_id) — scénario
        # réel : rebalance de partition Kafka, redémarrage du consumer
        # avant commit de l'offset, etc.
        second = apply_shipment_status_event(db, event)
        assert second.applied is False
        assert second.reason == "already_processed"

        assert db.query(ProcessedEvent).filter_by(event_id=event.event_id).count() == 1
    finally:
        db.close()


def test_apply_event_unknown_shipment_is_recorded_but_not_applied(full_supply_chain_scenario):
    db = SessionLocal()
    try:
        event = ShipmentStatusUpdated(
            shipment_id="SHP-DOES-NOT-EXIST", previous_status=None, new_status="delivered"
        )
        result = apply_shipment_status_event(db, event)

        assert result.applied is False
        assert result.reason == "unknown_shipment"
        # L'event_id est quand même marqué traité, pour ne pas le
        # retraiter indéfiniment à chaque poll (cf. docstring du service).
        assert db.query(ProcessedEvent).filter_by(event_id=event.event_id).first() is not None
    finally:
        db.close()


def test_event_schema_round_trip_serialization():
    event = ShipmentStatusUpdated(
        shipment_id="SHP-001", previous_status="in_transit", new_status="delivered"
    )
    raw = event.to_json()
    restored = ShipmentStatusUpdated.from_json(raw)

    assert restored.event_id == event.event_id
    assert restored.shipment_id == "SHP-001"
    assert restored.previous_status == "in_transit"
    assert restored.new_status == "delivered"
