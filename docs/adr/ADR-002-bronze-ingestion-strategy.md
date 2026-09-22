# ADR-002 — Ingestion Bronze en CLI batch synchrone (avant Airflow)

## Contexte
FR-01 exige d'ingérer des fichiers sources (CSV) dans une couche Bronze
immuable. Le blueprint final prévoit Airflow comme orchestrateur (Phase 2),
mais celui-ci n'est pas encore introduit à ce stade du projet.

## Problème
Comment déclencher et tracer une ingestion Bronze en Phase 1, sans
dépendre d'un orchestrateur qui n'existe pas encore, tout en posant des
bases (traçabilité, granularité par batch) qui n'auront pas besoin
d'être repensées quand Airflow arrivera ?

## Options considérées
1. **Script ad hoc lancé à la main**, sans structure ni traçabilité.
2. **CLI structuré (`app.cli ingest` / `ingest-all`)**, avec service
   d'ingestion découplé du déclenchement.
3. **Introduire Airflow dès maintenant**, en avance sur le planning
   (Phase 2 prévue plus tard).

## Décision
Option 2 : un CLI (`app/cli.py`) qui appelle un service d'ingestion
(`app/services/ingestion.py`) totalement indépendant de la façon dont il
est déclenché.

## Justification
- Le service d'ingestion ne connaît ni CLI ni Airflow ni FastAPI : il
  prend une session DB, une entité, un chemin de fichier, et retourne un
  résultat structuré (`IngestionResult`). Quand Airflow sera introduit en
  Phase 2, un `PythonOperator` appellera directement `ingest_file()` /
  `ingest_directory()` sans aucune réécriture de la logique métier.
- Chaque appel génère un `batch_id` (UUID) et trace `source_file` /
  `row_number` / `ingested_at` par ligne : la granularité de traçabilité
  attendue d'un vrai pipeline est là dès la Phase 1, pas ajoutée après
  coup.
- Introduire Airflow maintenant (option 3) aurait ajouté de la complexité
  d'infrastructure avant d'avoir un pipeline Bronze/Silver/Gold complet à
  orchestrer — contraire à la règle du projet de ne pas activer une
  techno avant d'avoir une vraie raison de l'utiliser.

## Compromis / Trade-offs
- Pas de reprise automatique en cas d'échec partiel, pas de planification
  (cron), pas de vue d'ensemble multi-pipelines : c'est exactement ce
  qu'Airflow apportera en Phase 2 (ADR à venir).
- L'ingestion est synchrone : acceptable au volume actuel (dataset
  synthétique "small"/"medium"), à réévaluer si le volume augmente
  significativement avant la Phase 2.

## Conséquences
- Le service d'ingestion doit rester strictement indépendant de son mode
  de déclenchement (pas d'`argparse`, pas de FastAPI `Request` dans
  `app/services/ingestion.py`).
- FR-05 (Orchestration) en Phase 1 se limite à ce CLI ; la bascule vers
  Airflow (Phase 2) fera l'objet d'un ADR dédié.
