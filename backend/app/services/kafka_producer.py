"""Producer Kafka (Phase 2).

Publie un événement `ShipmentStatusUpdated` sur le topic configuré.
Partitionné par `shipment_id` (clé du message) : Kafka garantit l'ordre
des messages au sein d'une même partition, donc tous les événements
d'une même expédition arrivent dans l'ordre chez un même consumer — sans
cette clé, deux mises à jour du même shipment pourraient être traitées
dans le désordre par des consumers différents.

NOTE D'ENVIRONNEMENT (cf. ADR-007) : ce module n'a pas pu être testé
contre un broker Kafka réel dans le sandbox de développement (ni Docker,
ni paquet apt, ni miroir Apache accessible sur le réseau restreint de cet
environnement). Le code suit l'API standard de `confluent-kafka` et le
`docker-compose.yml` fournit un vrai broker Kafka (image `apache/kafka`,
mode KRaft) : à vérifier de bout en bout avec `docker compose up` sur une
machine avec Docker.
"""

import logging

from confluent_kafka import KafkaException, Producer

from app.core.config import get_settings
from app.events.schemas import ShipmentStatusUpdated

logger = logging.getLogger(__name__)

_producer: Producer | None = None


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        settings = get_settings()
        _producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
    return _producer


def _delivery_callback(err, msg) -> None:
    if err is not None:
        logger.error("Échec de livraison Kafka pour %s: %s", msg.key(), err)


def publish_shipment_status_updated(
    shipment_id: str, previous_status: str | None, new_status: str
) -> ShipmentStatusUpdated:
    """Construit et publie l'événement. Retourne l'événement publié
    (utile pour les tests et pour logger l'event_id généré)."""
    settings = get_settings()
    event = ShipmentStatusUpdated(
        shipment_id=shipment_id, previous_status=previous_status, new_status=new_status
    )

    producer = get_producer()
    try:
        producer.produce(
            topic=settings.kafka_shipment_status_topic,
            key=shipment_id.encode("utf-8"),
            value=event.to_json().encode("utf-8"),
            callback=_delivery_callback,
        )
        remaining = producer.flush(timeout=10)
        if remaining > 0:
            # flush() ne lève pas d'exception en cas d'échec de livraison
            # (les erreurs partent dans le callback) ; un flush() qui
            # retourne >0 signifie qu'au moins un message n'a jamais été
            # livré (broker injoignable, timeout...) — vérifié
            # explicitement pour ne pas retourner un succès silencieux.
            raise KafkaException(
                f"{remaining} message(s) non livré(s) (broker injoignable ou timeout)"
            )
    except KafkaException as exc:
        logger.error("Impossible de publier l'événement %s: %s", event.event_id, exc)
        raise

    return event
