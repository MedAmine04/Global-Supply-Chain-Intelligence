"""Tests structurels du DAG GSCI.

Complémentaires, pas redondants, avec la vérification déjà faite
manuellement (`airflow dags test`, deux fois : un run complet réussi et
un run en échec contrôlé — voir ADR-008 pour le détail et les logs
observés). Ces tests-ci vérifient que la STRUCTURE du DAG reste correcte
dans le temps (pas d'erreur de parsing, bon nombre de tâches, bonnes
dépendances) — utile en CI pour attraper une régression sans devoir
relancer un vrai pipeline à chaque fois.

Nécessitent le venv Airflow dédié (../.venv), pas le venv/environnement
du backend :
    cd airflow && .venv/bin/python -m pytest tests/ -v
"""

import os

os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
os.environ.setdefault(
    "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN",
    "postgresql+psycopg2://gsci:gsci@localhost:5432/airflow_metadata",
)

from airflow.models import DagBag  # noqa: E402

DAGS_FOLDER = os.path.join(os.path.dirname(__file__), "..", "dags")


def _load_dagbag() -> DagBag:
    return DagBag(dag_folder=DAGS_FOLDER, include_examples=False)


def test_dagbag_has_no_import_errors():
    dagbag = _load_dagbag()
    assert dagbag.import_errors == {}


def test_gsci_dag_is_present():
    dagbag = _load_dagbag()
    assert "gsci_bronze_silver_gold" in dagbag.dags


def test_gsci_dag_has_expected_task_count():
    dagbag = _load_dagbag()
    dag = dagbag.dags["gsci_bronze_silver_gold"]
    assert len(dag.tasks) == 7  # 6 entités + transform_gold


def test_gold_task_depends_on_every_ingest_task():
    """transform_gold doit être en aval de TOUTES les tâches d'ingestion
    (directement ou via la chaîne orders -> shipments -> incidents) —
    sinon Gold pourrait tourner avant que Silver soit complet."""
    dagbag = _load_dagbag()
    dag = dagbag.dags["gsci_bronze_silver_gold"]
    gold_task = dag.get_task("transform_gold")

    upstream_ids = {t.task_id for t in gold_task.upstream_list}
    for entity in ["suppliers", "products", "warehouses", "orders", "shipments", "incidents"]:
        # get_flat_relative_ids couvre les dépendances transitives, pas
        # seulement directes (shipments/incidents ne sont pas en amont
        # direct de gold, mais le sont via la chaîne orders->shipments->incidents)
        all_upstream = gold_task.get_flat_relative_ids(upstream=True)
        assert f"ingest_{entity}" in all_upstream | upstream_ids


def test_orders_depends_on_suppliers_products_warehouses():
    """L'ordre de dépendance doit refléter les contraintes FK réelles :
    une commande ne peut être ingérée avant que fournisseur/produit/
    entrepôt existent (cf. FR-02, validation des clés étrangères)."""
    dagbag = _load_dagbag()
    dag = dagbag.dags["gsci_bronze_silver_gold"]
    orders_task = dag.get_task("ingest_orders")

    upstream_ids = {t.task_id for t in orders_task.upstream_list}
    assert upstream_ids == {"ingest_suppliers", "ingest_products", "ingest_warehouses"}


def test_shipments_depends_only_on_orders():
    dagbag = _load_dagbag()
    dag = dagbag.dags["gsci_bronze_silver_gold"]
    shipments_task = dag.get_task("ingest_shipments")

    upstream_ids = {t.task_id for t in shipments_task.upstream_list}
    assert upstream_ids == {"ingest_orders"}
