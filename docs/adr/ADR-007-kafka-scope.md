# ADR-007 — Kafka : consumer idempotent, contrainte d'environnement assumée

## Contexte
Le planning Phase 2 demande "un vrai flux d'événements (ex.
`shipment_status_updated`) avec producer et consumer, gestion des
erreurs, idempotence", avec la consigne explicite de ne pas se contenter
d'un Kafka "hello world" à un seul message, mais d'implémenter une vraie
sémantique de livraison.

## Contrainte d'environnement (à traiter honnêtement, pas à contourner)
Kafka nécessite un broker qui tourne en continu. Dans le sandbox de
développement utilisé pour écrire ce code :
- **pas de Docker** (`docker: not found`) — impossible de lancer le
  broker via `docker-compose` comme prévu pour l'environnement cible ;
- **pas de paquet apt pour le broker Kafka** lui-même (seulement des
  bibliothèques clientes : `python3-kafka`, `librdkafka`, `kcat`) ;
- **aucun miroir Apache accessible** sur le réseau restreint de cet
  environnement pour télécharger le tarball du broker.

Vérifié explicitement plutôt que supposé : une tentative de connexion
réelle à `localhost:9092` avec `confluent-kafka` confirme `Connection
refused` et `flush()` retournant des messages non livrés.

## Décision
1. Écrire le code producer/consumer complet et correct, suivant l'API
   standard `confluent-kafka`, avec un vrai service Kafka déclaré dans
   `docker-compose.yml` (image `apache/kafka`, mode KRaft, un seul
   nœud) — fonctionnel sur toute machine avec Docker, donc chez le
   développeur final.
2. Séparer strictement la logique métier idempotente
   (`apply_shipment_status_event`, pure fonction session+événement) de
   la boucle de polling Kafka (`run_consumer_loop`), pour que la partie
   qui peut être testée sans broker (la logique) le soit réellement,
   sans dépendre de la partie qui ne peut pas l'être ici.
3. Documenter explicitement, dans le code et ce ADR, ce qui a été
   vérifié dans ce sandbox et ce qui ne l'a pas été — jamais présenter
   une exécution partielle comme une validation complète.

## Ce qui a été vérifié ici (avec un vrai run, pas supposé)
- `apply_shipment_status_event` : mise à jour du statut, idempotence sur
  rejeu du même `event_id` (4 tests, dont
  `test_apply_event_is_idempotent_on_replay`), gestion d'un shipment
  inconnu.
- Sérialisation/désérialisation JSON de l'événement (round-trip).
- **Un vrai bug trouvé et corrigé grâce à cette vérification** :
  `producer.flush()` de `confluent-kafka` ne lève PAS d'exception en cas
  d'échec de livraison (les erreurs partent uniquement dans le
  callback) — le code initial aurait donc silencieusement "réussi" à
  publier un événement même sans broker joignable. Corrigé en vérifiant
  explicitement la valeur de retour de `flush()` (nombre de messages
  encore en attente) et en levant une exception si elle est non nulle.
  Reproduit et confirmé : `Connection refused` sur `localhost:9092`
  déclenche maintenant bien une `KafkaException`, alors que l'ancien
  code retournait un faux succès.

## Ce qui n'a PAS été vérifié ici
- `run_consumer_loop` (la boucle de polling Kafka réelle) : nécessite un
  broker vivant, non disponible dans ce sandbox. Sa correction repose
  sur celle de `apply_shipment_status_event` (testée) et sur l'usage
  standard de l'API `confluent-kafka.Consumer` (non testé ici).
- Le comportement réel de partitionnement/ordre des messages par clé
  `shipment_id`, le rebalance de partition, ou la latence de bout en
  bout producer -> broker -> consumer.
- Le service `kafka` du `docker-compose.yml` (démarrage, healthcheck,
  connectivité) n'a pas pu être testé faute de Docker disponible ici.

**Pour vérifier ces points**, sur une machine avec Docker :
```bash
docker compose up -d kafka
python -m app.cli kafka-produce-status --shipment SHP-000001 --status delayed_customs
python -m app.cli kafka-consume-status --max-messages 1
```

## Décisions de conception
- **Clé de partition = `shipment_id`** : garantit que tous les
  événements d'une même expédition sont lus dans l'ordre par un même
  consumer (Kafka ne garantit l'ordre qu'au sein d'une partition).
- **Idempotence via table `processed_events`** plutôt que via une
  configuration "exactly-once" native de Kafka (transactions
  producer/consumer) : plus simple à raisonner et à tester, suffisant
  pour ce cas d'usage (un seul consumer group), et cohérent avec le
  reste du projet qui privilégie des mécanismes explicites et lisibles
  (cf. ADR-003, "reject only") à des garanties implicites de
  l'infrastructure.
- **Un événement pour un shipment inconnu est marqué "traité" quand
  même** (pas de retry indéfini) plutôt que routé vers une dead-letter
  queue : une DLQ est un vrai pattern de production, mais son absence
  ici est un choix de périmètre assumé (pas d'usage réel de DLQ à
  démontrer avec les volumes actuels), pas un oubli.

## Compromis / Trade-offs
- Sans broker testable ici, un bug dans `run_consumer_loop` lui-même
  (pas dans la logique qu'elle appelle) pourrait passer inaperçu
  jusqu'à la première exécution réelle chez le développeur. C'est le
  risque assumé de cette contrainte d'environnement, réduit autant que
  possible en gardant cette fonction aussi fine que possible (peu de
  logique propre, l'essentiel délégué à `apply_shipment_status_event`).

## Conséquences
- Kafka, comme Spark (ADR-006), reste correctement scopé : un seul type
  d'événement, un seul topic, pas de sur-ingénierie (schema registry,
  DLQ, exactly-once transactionnel) avant qu'un besoin réel ne le
  justifie.
- Airflow (prochaine brique Phase 2) devra faire le même exercice de
  vérification honnête des contraintes d'environnement avant
  implémentation.
