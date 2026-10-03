# Global Supply Chain Intelligence

> Plateforme intelligente de pilotage de chaîne logistique mondiale :
> ingestion, transformation et analyse de données supply chain,
> prédiction des risques de retard, analyse d'incidents et de documents,
> interface décisionnelle assistée par IA.

**Statut : `v1.0.0` — Phases 0 à 8 terminées** (Foundation, Data Engineering,
Big Data, Machine Learning, NLP, Computer Vision, AI Copilot, RAG,
Production). Voir `docs/planning-semestre.md` pour le détail phase par
phase et `docs/adr/` pour les décisions d'architecture (14 ADR).

## Stack

- Backend : FastAPI + PostgreSQL + SQLAlchemy + Alembic
- Frontend : React (Vite)
- Conteneurisation : Docker / Docker Compose
- CI : GitHub Actions (lint, migrations, tests, build, audit de dépendances)
- Data Engineering : génération de dataset synthétique + pipeline Bronze/Silver/Gold (CLI)
- Big Data : Spark (PySpark), Kafka, Airflow
- Machine Learning : scikit-learn/XGBoost + MLflow (tracking local)
- NLP : classification TF-IDF + NER hybride (regex/règles/spaCy) + recherche lexicale
- Computer Vision : CNN (TensorFlow-CPU) sur images synthétiques
- AI Copilot : Anthropic (tool-use, outils whitelistés)
- RAG : retrieval lexical TF-IDF sur corpus de documents internes
- Observabilité : Prometheus + Grafana ; sécurité : pip-audit, conteneurs non-root

Certains choix (TensorFlow-CPU plutôt que PyTorch, TF-IDF plutôt que des
embeddings, données synthétiques plutôt que des datasets externes,
Anthropic plutôt que Gemini) sont des substitutions documentées,
imposées par les contraintes réseau/matériel de l'environnement de
développement — voir les ADR correspondants pour la justification et ce
qui a été vérifié en conditions réelles.

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

## Phase 2 — Big Data : Airflow (troisième incrément, clôture Phase 2)

```bash
cd airflow
export AIRFLOW_HOME=$(pwd)
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="postgresql+psycopg2://gsci:gsci@localhost:5432/airflow_metadata"
.venv/bin/airflow dags test gsci_bronze_silver_gold 2024-01-01
```

DAG `gsci_bronze_silver_gold` (voir `airflow/dags/gsci_pipeline_dag.py`)
remplaçant l'orchestration CLI manuelle : 6 tâches d'ingestion (une par
entité, dépendances reflétant les contraintes FK réelles : orders après
suppliers/products/warehouses, shipments après orders, incidents après
shipments) puis `transform_gold`.

**Contrairement à Kafka, ce composant a pu être vérifié par une vraie
exécution** (pip + venv, pas besoin de Docker) — voir ADR-008 pour le
détail complet, incluant :
- un run de succès complet (7/7 tâches, données Gold identiques au CLI
  direct) ;
- un run d'échec contrôlé (fichier source absent) démontrant le retry
  automatique puis le blocage correct des tâches en aval
  (`upstream_failed`) sans affecter les tâches indépendantes.

Environnement Python séparé du backend (`airflow/.venv`, voir
`airflow/README.md`) pour éviter tout conflit de dépendances avec
FastAPI — le DAG appelle le CLI du backend en sous-processus
(`BashOperator`), jamais par import direct (révision assumée du plan
initial d'ADR-002, justifiée dans ADR-008).

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


## Phase 3 — Machine Learning : prédiction de retard (FR-11, FR-12, FR-13)

```bash
cd backend
python -m app.cli train-model     # entraîne et compare 3 modèles, suivi MLflow local
python -m app.cli predict-risk    # score les expéditions non livrées
# puis : GET /api/predictions/at-risk?limit=20
```

Compare Logistic Regression, Random Forest et XGBoost sur un **split
temporel** (les 80% d'expéditions les plus anciennes pour l'entraînement,
les 20% les plus récentes pour le test), avec suivi des expériences via
MLflow en mode fichier local (`backend/mlruns/`, pas de serveur requis).

**Garde-fous anti-leakage, testés** : aucune feature n'utilise une
information postérieure au départ de l'expédition (le taux de retard
historique d'un fournisseur n'inclut jamais l'expédition courante ni
les suivantes), et la valeur de repli du cold start est calculée sur le
seul jeu d'entraînement.

**Résultats (ROC-AUC 0.57 pour le meilleur modèle) volontairement
modestes et assumés** : le dataset synthétique contient un signal réel
mais modéré. Le premier entraînement avait donné ROC-AUC ~0.49 (aucun
signal, générateur de retards purement aléatoire), ce qui a conduit à
corriger le générateur — voir ADR-009 pour le parcours complet, les
trois bugs rencontrés, et ce que ces chiffres valident (le pipeline
retrouve un signal injecté) et ne valident pas (la performance sur des
retards réels).

## Phase 4 — NLP : incidents (classification, extraction, recherche)

```bash
cd backend
python -m app.cli train-incident-classifier   # TF-IDF + LogReg vs baseline
python -m app.cli enrich-incidents            # type prédit + durée, lieu, référence
python -m app.cli search-incidents --query "storm snow"
```

Classifieur de type d'incident : accuracy 0.93 contre 0.18 pour le
baseline, **mesurée sur du texte généré par gabarits** — elle valide le
pipeline, pas la généralisation à de vrais rapports (ADR-010).

**Limites assumées** : Hugging Face est inaccessible depuis
l'environnement de développement, donc pas de transformers ni
d'embeddings. La "recherche" est lexicale (TF-IDF), pas sémantique ; les
embeddings et le sentiment ne sont pas implémentés. Les descriptions
d'incidents du générateur étaient du texte aléatoire sans lien avec le
type : corrigé avant l'entraînement (même piège que pour les retards).

## Phase 5 — Computer Vision : détection de dommages sur colis

```bash
cd backend
python -m app.cli train-damage-classifier         # ~3 min, 3000 images synthétiques
python -m app.cli score-images --folder <dossier>  # images .jpg/.png, normal/damaged pour ré-entraîner
```

CNN maison (TensorFlow, sans transfer learning) sur des **images
synthétiques générées avec OpenCV** — aucun dataset réel ni poids
pré-entraîné n'est accessible depuis l'environnement de développement
(`kaggle.com`, `zenodo.org`, `download.pytorch.org` → 403, ADR-011).

**Pipeline instable, corrigé en trois temps documentés dans ADR-011** :
surapprentissage (corrigé par augmentation légère), puis instabilité
d'entraînement sans seed fixée (corrigée par seed + LR scheduler +
early stopping), puis découverte que le modèle collapse de façon
fiable en dessous d'~3000 images — pas un problème de nombre d'epochs.
Résultat final : F1 ~0.80-0.87 sur un split 80/20 stratifié.

**Non intégré au score de risque Gold** : les images synthétiques ne
sont pas liées à un `shipment_id` réel du dataset — c'est un flux de
scoring à part (`app/cv/dataset.py` permet de brancher de vraies photos
via `--image-folder`), le lien avec une expédition précise nécessitera
un vrai stockage de fichiers (Phase 6/7).

## Phase 6 — AI Copilot

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # requis, non configuré dans cet environnement de dev
python -m app.cli ask-copilot "Quels fournisseurs ont le plus de retards ?"
# ou : POST /api/copilot/ask {"question": "..."}
```

4 outils (KPI, performance fournisseurs, expéditions à risque,
recherche d'incidents) appelant directement les services déjà testés —
le modèle ne voit jamais la base de données ni ne génère de SQL,
il ne peut agir qu'au travers de ces outils. Chaque réponse inclut
les données réellement utilisées (`tool_calls`), affichées en repli
dans le dashboard.

**Non vérifié en direct dans cet environnement** : ni Gemini
(`generativelanguage.googleapis.com` bloqué par le pare-feu du sandbox,
vérifié) ni Anthropic (pas de clé disponible ici) n'ont pu être appelés
réellement. Ce qui est testé : la couche `dispatch_tool_call` (7 tests,
contre les vraies données) et le comportement d'erreur sans clé — voir
ADR-012 pour le détail, y compris un incident de sécurité mineur
(clé API partagée dans le chat, jamais persistée, révocation
recommandée).

## Phase 7 — RAG : documents internes

Corpus synthétique (`backend/docs_corpus/`, 3 documents : contrat
fournisseur, politique de transport, politique qualité des données),
récupération lexicale TF-IDF (mêmes limites que la recherche
d'incidents, ADR-010), exposée au Copilot via l'outil `search_documents`
avec citation de la section source. Un vrai bug de récupération trouvé
et corrigé pendant le développement (titres de section non indexés,
faussant le classement) — voir ADR-013.

## Phase 8 — Production : observabilité, sécurité, infrastructure

```bash
curl http://localhost:8000/metrics   # métriques Prometheus (compteurs, latence)
cd backend && pip-audit -r requirements.txt
```

**Observabilité vérifiée en direct** : middleware Prometheus testé
contre un vrai serveur (requêtes réelles, format de métriques confirmé)
+ test automatisé. Services `prometheus`/`grafana` dans
`docker-compose.yml` (dashboard provisionné automatiquement), non
démarrés ici faute de Docker.

**Audit de sécurité réel, pas un scan ignoré** : 86 vulnérabilités
trouvées par `pip-audit`, analysées une par une. `starlette` mis à jour
(0.38.6 → 0.48.0, plafond vérifié même avec la dernière version de
FastAPI) ; les 6 restantes confirmées non exploitables par `grep` sur
le code réel (aucun `FileResponse`, `StaticFiles`, `HTTPEndpoint`, ni
formulaire dans ce projet). Les 63 vulnérabilités `mlflow` concernent
exclusivement `mlflow server`, jamais démarré ici (tracking local par
fichiers uniquement) — non corrigées, exposition nulle justifiée et
documentée, pas ignorée. Détail complet dans ADR-014.

Conteneurs Docker en utilisateur non-root (`USER app`/`USER node`),
non vérifié par un build réel (pas de Docker ici). Infrastructure Azure
en Terraform (`infra/terraform/`), écrite mais non appliquée (ni
Terraform ni accès Azure disponibles ici, vérifié).

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
