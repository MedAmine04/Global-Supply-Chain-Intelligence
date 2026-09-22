# ADR-001 — PostgreSQL comme base de données opérationnelle

## Contexte
Le projet a besoin d'une base de données relationnelle pour stocker les
couches Gold (modèle dimensionnel), les métadonnées applicatives
(utilisateurs, runs de pipeline) et, à terme, les embeddings pour le RAG.

## Problème
Quelle base de données utiliser comme socle transverse du projet, sachant
qu'elle doit supporter à la fois un modèle relationnel classique (star
schema) et, plus tard, une recherche vectorielle (RAG) ?

## Options considérées
1. **PostgreSQL** — relationnel, mature, extension `pgvector` disponible.
2. **MongoDB** — document-oriented, flexible mais mal adapté à un modèle
   dimensionnel en étoile et aux jointures analytiques.
3. **MySQL** — relationnel, mais écosystème d'extensions analytiques et
   vectorielles moins riche que PostgreSQL.

## Décision
PostgreSQL.

## Justification
- Le modèle métier (fact/dim tables) est intrinsèquement relationnel :
  PostgreSQL est le choix naturel pour un star schema.
- `pgvector` permet de rester sur une seule base de données pour
  l'analytique classique et le RAG (Phase 7), évitant d'introduire une
  base vectorielle séparée (Pinecone, Weaviate) et sa complexité
  opérationnelle supplémentaire.
- Écosystème Python mature (SQLAlchemy, psycopg, Alembic) qui s'intègre
  proprement avec FastAPI.
- Disponible nativement sur Azure (Azure Database for PostgreSQL),
  cohérent avec la cible cloud du projet.

## Compromis / Trade-offs
- PostgreSQL n'est pas un moteur analytique columnar : pour de très gros
  volumes analytiques, un data warehouse dédié (BigQuery, Snowflake)
  serait plus performant. Accepté pour ce projet : le volume synthétique
  reste dans une plage où PostgreSQL est largement suffisant, et l'objectif
  pédagogique porte davantage sur la modélisation et le pipeline que sur
  l'optimisation de moteur analytique à très grande échelle.
- `pgvector` est moins performant qu'une base vectorielle dédiée sur de
  très gros volumes d'embeddings. Accepté : le volume de documents pour
  le RAG (Phase 7) reste modeste.

## Conséquences
- Toute évolution future vers un vrai data warehouse (Phase Big Data)
  devra être justifiée par un nouvel ADR si le volume le justifie
  réellement, plutôt que changée par défaut.
- Les migrations de schéma sont gérées via Alembic dès la Phase 0.
