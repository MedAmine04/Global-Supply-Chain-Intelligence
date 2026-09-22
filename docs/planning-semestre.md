# Planning du semestre — Global Supply Chain Intelligence

> Objectif : profondeur et qualité sur chaque brique, pas vitesse. Une brique n'est ouverte que quand la précédente est terminée (code + tests + doc + ADR).

---

## Vue d'ensemble

| Phase | Contenu | Release | Durée réaliste (en profondeur) |
|---|---|---|---|
| 0 | Foundation | v0.1.0 | 1,5 – 2 semaines |
| 1 | Data Engineering (Bronze/Silver/Gold, Data Quality) | v0.2.0 | 3 – 4 semaines |
| 2 | Big Data (Spark, Kafka, Airflow) | v0.3.0 | 4 – 5 semaines |
| 3 | Machine Learning (prédiction + explicabilité) | v0.4.0 | 3 – 4 semaines |
| 4 | NLP (incidents) | v0.5.0 | 2 – 3 semaines |
| 5 | Computer Vision (dommages) | v0.6.0 | 2 – 3 semaines |
| 6 | AI Copilot (LLM + outils) | v0.7.0 | 2 – 3 semaines |
| 7 | RAG (documents) | v0.8.0 | 2 semaines |
| 8 | Production (CI/CD, Terraform, Azure, monitoring, sécurité) | v0.9.0 | 3 – 4 semaines |
| — | Buffer / polish / démo / documentation finale | v1.0.0 | 1,5 – 2 semaines |

**Total : ~25 – 30 semaines de travail réel.** Sur un semestre de ~15-16 semaines calendaires, ça implique soit un rythme soutenu (10-15h/semaine minimum), soit d'accepter que certaines briques avancées (CV, RAG) glissent après la soutenance et continuent en autonome. C'est un point à trancher avec ton encadrant : mieux vaut annoncer un périmètre réaliste et le tenir, que promettre le tout et livrer à moitié.

---

## Phase 0 — Foundation (v0.1.0)

**Objectif d'apprentissage** : structurer un repo comme un vrai projet d'ingénierie logicielle, pas comme un notebook.

- Initialisation du repo : structure `backend/`, `frontend/`, `infra/`, `docs/`, `.github/`.
- `docker-compose.yml` : API + PostgreSQL + Frontend, réseau partagé, volumes.
- FastAPI : squelette avec un endpoint de santé (`/health`), configuration par variables d'environnement (`.env`), structure en couches (routers / services / repositories) — pas tout dans `main.py`.
- PostgreSQL : premier schéma minimal (`users`, table technique de migration).
- React : squelette Vite, appel à `/health` pour prouver la liaison frontend-backend.
- CI GitHub Actions : lint (`ruff`/`flake8` + `eslint`), tests (`pytest` vide), build Docker.
- Premier ADR : "Pourquoi PostgreSQL plutôt que MongoDB pour ce projet" — même si la réponse te semble évidente, l'exercice de l'écrire proprement compte.

**Point de complexité à ne pas éviter** : configure de vraies migrations de schéma (Alembic) dès le départ. Beaucoup de projets étudiants gèrent le schéma "à la main" et le regrettent dès la phase 1.

**Critère de sortie de phase** : `docker-compose up` lance tout, `/health` répond, CI verte sur une PR de test.

---

## Phase 1 — Data Engineering (v0.2.0)

**Objectif d'apprentissage** : construire un vrai pipeline ETL avec gouvernance de la qualité, pas juste un script qui charge un CSV.

- Génération du dataset synthétique (volume réduit mais réaliste : ex. 50k suppliers → shipments, avec dépendances cohérentes entre tables).
- Ingestion Bronze : format brut, immuable, horodaté.
- Data Quality : implémente de vraies règles (schéma, nulls, doublons, clés étrangères, plages de valeurs) avec un vrai rapport structuré, pas un simple `print`.
- Silver : nettoyage, typage strict, déduplication documentée (quelle règle de dédoublonnage, pourquoi).
- Gold : modèle dimensionnel complet (star schema), avec un vrai travail de modélisation — documente pourquoi chaque dimension existe.
- Orchestration simple (scripts séquencés + logs), sans Airflow pour l'instant.
- ADR : "Choix du modèle dimensionnel" + "Stratégie de gestion des données invalides (reject vs correct)".

**Point de complexité à ne pas éviter** : gère les cas de données partiellement invalides avec une vraie politique (rejet, quarantaine, ou correction automatique documentée) plutôt que de tout accepter.

**Critère de sortie de phase** : un run complet Bronze→Silver→Gold sur le dataset synthétique, rapport de qualité généré, dashboard minimal branché sur `gold.*` via l'API.

---

## Phase 2 — Big Data (v0.3.0)

**Objectif d'apprentissage** : comprendre le traitement distribué et le streaming, pas juste les activer.

- Spark (PySpark) : réécriture d'au moins une transformation Silver→Gold en Spark, avec justification (volume, parallélisation) — même si le volume ne l'exige pas techniquement, l'objectif est l'apprentissage du framework.
- Kafka : un vrai flux d'événements (ex. `shipment_status_updated`) avec producer et consumer, gestion des erreurs, idempotence.
- Airflow : migration de l'orchestration simple vers de vrais DAGs avec dépendances, retries, alerting en cas d'échec.
- ADR : "Pourquoi Kafka plutôt qu'un simple polling", "Pourquoi Airflow plutôt que cron".

**Point de complexité à ne pas éviter** : ne fais pas un Kafka "hello world" à un seul message. Implémente une vraie sémantique de livraison (at-least-once avec gestion des doublons côté consumer) — c'est ce qui prouve que tu comprends le sujet.

**Critère de sortie de phase** : un événement produit par Kafka déclenche une mise à jour visible dans le dashboard ; un DAG Airflow orchestre le pipeline complet et est visible dans l'UI Airflow.

---

## Phase 3 — Machine Learning (v0.4.0)

**Objectif d'apprentissage** : cycle de vie ML complet, pas juste `.fit()` / `.predict()`.

- Feature engineering documenté (pourquoi chaque feature, comment elle est calculée).
- Baseline (Logistic Regression) puis comparaison rigoureuse (Random Forest, XGBoost) avec métriques complètes (Precision/Recall/F1/ROC-AUC/matrice de confusion).
- MLflow : tracking réel des expériences, Model Registry, versionning des modèles.
- Explicabilité SHAP : facteurs contributifs affichés par shipment, pas juste un score brut.
- Tests ML : schéma d'entrée, seuil de performance minimal en CI (le pipeline échoue si le modèle régresse).
- ADR : "Choix du modèle final et compromis performance/explicabilité".

**Critère de sortie de phase** : API `/predictions/{shipment_id}` retourne probabilité + facteurs contributifs, visible dans le dashboard.

---

## Phase 4 — NLP (v0.5.0)

- Preprocessing texte, classification des incidents (type, sévérité), NER (extraction shipment ID, durée, cause).
- Embeddings + recherche sémantique sur les incidents.
- ADR : choix du modèle NLP (from scratch vs pré-entraîné) et justification du compromis coût/performance.

## Phase 5 — Computer Vision (v0.6.0)

- Dataset d'images (réel ou synthétique documenté comme tel), modèle de classification dommage/normal, intégration du signal dans le score de risque global.

## Phase 6 — AI Copilot (v0.7.0)

- Orchestration LLM + appels outils (function calling) vers l'API analytics/ML, pas de réponses inventées : chaque affirmation doit être traçable à une donnée réelle.

## Phase 7 — RAG (v0.8.0)

- Parsing/chunking de documents, embeddings, pgvector, retrieval, réponse avec sources citées.

## Phase 8 — Production (v0.9.0)

- CI/CD complet, Terraform pour l'infra Azure, déploiement réel (même limité par les crédits étudiants), Prometheus/Grafana, durcissement sécurité (secrets, scan de dépendances, rate limiting).

---

## Règles de fonctionnement pour tout le semestre

1. Une brique = un ADR minimum avant de coder (force la réflexion sur les alternatives).
2. Pas de nouvelle Phase ouverte tant que le "Critère de sortie de phase" précédent n'est pas atteint.
3. Chaque Phase se termine par une mise à jour du README et une release Git taguée.
4. Revue hebdomadaire courte : qu'est-ce qui est vraiment fini (testé + documenté) vs juste "ça marche sur ma machine".

---

## Prochaine étape immédiate

On attaque la Phase 0 maintenant : structure du repo, `docker-compose.yml`, squelette FastAPI, squelette React, PostgreSQL, CI GitHub Actions.
