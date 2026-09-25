"""DAG d'orchestration du pipeline GSCI (Phase 2 — remplace l'orchestration
CLI manuelle prévue par ADR-002).

Topologie des dépendances : reflète l'ordre métier réel (une commande a
besoin d'un fournisseur/produit/entrepôt existant, une expédition a
besoin d'une commande, un incident a besoin d'une expédition) — pas un
simple fan-out/fan-in arbitraire.

    suppliers  ─┐
    products   ─┼─→ orders ─→ shipments ─→ incidents ─┐
    warehouses ─┘                                      ├─→ gold
    (suppliers, products, warehouses aussi requis) ─────┘

Chaque tâche entité appelle `python -m app.cli ingest --entity ... `,
qui enchaîne déjà ingestion Bronze -> contrôle qualité -> transformation
Silver pour cette entité (logique déjà écrite et testée en Phase 1, non
dupliquée ici). `gold` appelle `transform-gold`, qui reconstruit tout le
star schema depuis l'état courant de Silver (cf. ADR-005).

Exécuté via BashOperator plutôt que PythonOperator (cf. ADR-008) : le
CLI reste l'interface officielle du pipeline (ADR-002), et ça évite
d'installer les dépendances lourdes du backend (pyspark, confluent-
kafka...) dans l'environnement Airflow, qui n'a besoin d'aucune d'elles
pour orchestrer.
"""

from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator

# Chemin calculé relativement à ce fichier plutôt qu'en dur, pour que le
# DAG fonctionne quel que soit l'endroit où le repo est cloné (ici :
# airflow/dags/gsci_pipeline_dag.py -> ../../backend).
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent / "backend"
DATA_DIR = BACKEND_DIR / "data" / "raw"
DATABASE_URL = "postgresql+psycopg://gsci:gsci@localhost:5432/gsci"

BASH_ENV_PREFIX = f"cd {BACKEND_DIR} && DATABASE_URL={DATABASE_URL} python3 -m app.cli"

default_args = {
    "owner": "data-engineering",
    "retries": 1,
    "retry_delay": timedelta(seconds=10),
}

with DAG(
    dag_id="gsci_bronze_silver_gold",
    description="Pipeline complet Bronze -> Silver -> Gold (FR-01 à FR-04)",
    default_args=default_args,
    schedule=None,  # déclenchement manuel à ce stade ; un schedule cron viendra une fois le besoin métier confirmé
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["gsci", "phase2", "data-engineering"],
) as dag:

    def _ingest_task(entity: str) -> BashOperator:
        return BashOperator(
            task_id=f"ingest_{entity}",
            bash_command=f"{BASH_ENV_PREFIX} ingest --entity {entity} --file {DATA_DIR}/{entity}.csv",
        )

    suppliers = _ingest_task("suppliers")
    products = _ingest_task("products")
    warehouses = _ingest_task("warehouses")
    orders = _ingest_task("orders")
    shipments = _ingest_task("shipments")
    incidents = _ingest_task("incidents")

    gold = BashOperator(
        task_id="transform_gold",
        bash_command=f"{BASH_ENV_PREFIX} transform-gold",
    )

    [suppliers, products, warehouses] >> orders >> shipments >> incidents >> gold
