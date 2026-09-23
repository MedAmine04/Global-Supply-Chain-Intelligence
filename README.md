# Global Supply Chain Intelligence

> Plateforme intelligente de pilotage de chaîne logistique mondiale :
> ingestion, transformation et analyse de données supply chain,
> prédiction des risques de retard, analyse d'incidents et de documents,
> interface décisionnelle assistée par IA.

**Statut : Phase 1 — Data Engineering (`v0.2.0`) — FR-01 à FR-09 terminés (pipeline complet + dashboard)**

## Stack (Phase 0 + 1)

- Backend : FastAPI + PostgreSQL + SQLAlchemy + Alembic
- Frontend : React (Vite)
- Conteneurisation : Docker / Docker Compose
- CI : GitHub Actions (lint, migrations, tests, build)
- Data Engineering : génération de dataset synthétique + ingestion Bronze (CLI)

Le reste de la stack cible (Spark, Kafka, Airflow, MLflow, pgvector,
Terraform, Azure...) est introduit progressivement, phase par phase.
Voir `docs/planning-semestre.md` pour le détail.

## Démarrage local

```bash
cp .env.example .env
docker compose up --build
```

- API : http://localhost:8000 (santé : http://localhost:8000/health)
- Frontend : http://localhost:5173

## Data Engineering — Ingestion Bronze (FR-01)

```bash
cd backend
alembic upgrade head                                    # crée les tables bronze_*
python -m app.scripts.generate_synthetic_data --out data/raw --scale small
python -m app.cli ingest-all --dir data/raw              # ingère tous les fichiers reconnus
# ou, fichier par fichier :
python -m app.cli ingest --entity suppliers --file data/raw/suppliers.csv
```

Le dataset synthétique inclut volontairement ~3% de valeurs "sales"
(`N/A`, vides, clés étrangères cassées) : Bronze les stocke telles
quelles, sans correction — c'est le rôle de FR-02 (Data Quality) de les
détecter et de les rapporter.

## Data Engineering — Contrôle qualité (FR-02)

`ingest` et `ingest-all` déclenchent automatiquement un contrôle qualité
après ingestion (désactivable avec `--skip-quality-check`). Pour rejouer
un contrôle sur un batch déjà ingéré :

```bash
python -m app.cli quality-check --entity orders --batch <batch_id>
```

Chaque run produit un `DATA QUALITY REPORT` (rows processed / valid /
rejected + détail par type de problème : champs requis manquants,
doublons, valeurs numériques hors plage, dates invalides, clés
étrangères invalides) et le persiste dans `data_quality_reports` pour
historique et audit. Voir ADR-003 pour la politique "reject only"
(aucune correction automatique à ce stade).

## Data Engineering — Transformation Silver (FR-03)

`ingest`/`ingest-all` enchaînent automatiquement ingestion → contrôle
qualité → transformation Silver (désactivable avec `--skip-silver`).
Pour rejouer uniquement la transformation d'un batch déjà contrôlé :

```bash
python -m app.cli transform-silver --entity orders --batch <batch_id>
```

Silver ne reprend que les lignes validées par le dernier contrôle
qualité du batch (cf. ADR-004), les type strictement (Date, Integer,
Float — plus de chaînes de caractères comme en Bronze), et les upserte
sur la clé métier (`supplier_id`, `order_id`, ...) : une ré-ingestion
corrigée met à jour la ligne existante plutôt que de créer un doublon.

## Data Engineering — Modèle dimensionnel Gold (FR-04)

```bash
python -m app.cli transform-gold
```

Reconstruit l'intégralité du star schema (dimensions `dim_supplier`,
`dim_product`, `dim_warehouse`, `dim_transport`, `dim_date`, et faits
`fact_orders`, `fact_shipments`, `fact_incidents`) depuis l'état courant
de Silver. Idempotent : relancer la commande met à jour les lignes
existantes sans créer de doublons. `fact_shipments` porte directement
`supplier_sk`/`product_sk` (dénormalisé depuis la commande associée) et
des mesures précalculées (`is_delayed`, `delay_days`) — voir ADR-005
pour la justification (besoin du futur modèle ML FR-11).

Un effet observable : une commande référençant un fournisseur ou produit
rejeté par FR-02 est automatiquement exclue de `fact_orders` (comptée en
`ignorées`) — la qualité se propage naturellement à travers les couches.

## API — Consultation Gold (FR-06) et Dashboard (FR-07/FR-08)

Endpoints exposés (voir `/docs` pour le contrat OpenAPI complet une fois
l'API lancée) :

- `GET /api/kpis/overview` — KPI globaux (commandes, expéditions, taux de
  livraison à l'heure, délai moyen, taux d'incidents)
- `GET /api/suppliers/performance` — performance par fournisseur, triée
  par taux de retard décroissant
- `GET /api/analysis/region-transport` — répartition des retards par
  région et mode de transport

Le frontend (`docker compose up` puis http://localhost:5173) affiche la
vue d'ensemble opérationnelle, le top 10 des fournisseurs à risque et la
répartition des retards par région/transport (barres colorées par
niveau de risque) — branchés sur ces endpoints, plus de données
statiques, tout vient de Gold via l'API.

## Release v0.2.0 — Data Platform (clôture Phase 1)

Ce qui est livré : pipeline Bronze → Silver → Gold complet et audité
(FR-01 à FR-05), API de consultation (FR-06), dashboard avec 3 sections
branchées sur des données réelles (FR-07 à FR-09). Voir
`docs/planning-semestre.md` pour la suite (Phase 2 — Big Data).

## Phase 2 — Big Data : Spark (premier incrément)

```bash
python -m app.cli transform-shipments-spark
```

Réimplémente la transformation `fact_shipments` (jointures + calcul de
`is_delayed`/`delay_days`) avec l'API DataFrame de Spark, en local
(`local[*]`, pas de cluster). Périmètre volontairement limité — pas de
connecteur JDBC PostgreSQL (aucun dépôt Maven accessible dans cet
environnement), extraction/écriture toujours via SQLAlchemy, Spark
utilisé pour le calcul uniquement. Voir ADR-006 pour la justification
complète et les compromis assumés.

La version Spark est testée par comparaison stricte à la version ORM de
référence sur le même scénario (`test_spark_transform_matches_orm_transform_on_same_scenario`) :
mêmes clés de substitution résolues, mêmes mesures dérivées. Un run réel
sur le dataset synthétique confirme l'équivalence (1751 créées, 139
ignorées — identique aux deux implémentations).

## Phase 2 — Big Data : Kafka (deuxième incrément)

```bash
docker compose up -d kafka   # nécessite Docker (non disponible dans l'environnement de développement)
python -m app.cli kafka-produce-status --shipment SHP-000001 --status delayed_customs
python -m app.cli kafka-consume-status --max-messages 1
```

Producer/consumer pour l'événement `shipment_status_updated`, partitionné
par `shipment_id` (ordre garanti par expédition), consumer idempotent via
une table `processed_events` (un `event_id` déjà traité n'est jamais
réappliqué — sémantique "at-least-once" de Kafka gérée explicitement).

**Contrainte d'environnement assumée et documentée (ADR-007)** : aucun
broker Kafka n'a pu être installé ni exécuté dans le sandbox de
développement (pas de Docker, pas de paquet apt pour le broker, aucun
miroir Apache accessible). La logique métier idempotente
(`apply_shipment_status_event`) est testée réellement (4 tests, dont le
test de rejeu du même événement) ; la boucle de consommation Kafka elle
-même (`run_consumer_loop`) ne l'est pas, faute de broker — à vérifier
avec `docker compose up kafka` sur une machine équipée de Docker.
Un vrai bug a été trouvé et corrigé pendant ce travail : `flush()` de
confluent-kafka ne lève pas d'exception en cas d'échec de livraison,
ce qui aurait fait "réussir" silencieusement une publication vers un
broker injoignable — voir ADR-007 pour le détail.

## Structure du repo

```text
backend/
  app/
    core/         # config, connexion DB
    routers/      # endpoints FastAPI
    services/     # logique métier
    repositories/ # accès aux données
  tests/
frontend/
  src/
infra/            # infrastructure (Terraform, à partir de la Phase 8)
docs/
  adr/            # Architecture Decision Records
.github/workflows/  # CI/CD
```

## Documentation

- Cahier des charges fonctionnel V1 : `docs/cahier-des-charges-v1.md`
- Planning du semestre, phase par phase : `docs/planning-semestre.md`
- Décisions d'architecture : `docs/adr/`

## Tests

```bash
cd backend && pytest -v
cd frontend && npm run build
```

## Definition of Done (rappel)

Une fonctionnalité n'est "done" que si : code revu, testée, documentée,
gère les erreurs/logs, fonctionne en Docker, CI verte.
