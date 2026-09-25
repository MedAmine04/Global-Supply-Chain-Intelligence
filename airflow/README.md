# Orchestration Airflow (Phase 2)

Remplace l'orchestration CLI manuelle (ADR-002) par un vrai DAG Airflow,
avec dépendances, retries et visibilité par tâche.

## Installation (environnement séparé du backend, cf. ADR-008)

```bash
cd airflow
python3 -m venv .venv
.venv/bin/pip install "apache-airflow[postgres]==2.10.3" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.3/constraints-3.12.txt"
.venv/bin/pip install pytest
```

## Configuration

```bash
export AIRFLOW_HOME=$(pwd)              # depuis le dossier airflow/
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="postgresql+psycopg2://gsci:gsci@localhost:5432/airflow_metadata"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__DAGS_FOLDER=$(pwd)/dags

# Créer la base de métadonnées (une fois) :
psql -U gsci -h localhost -c "CREATE DATABASE airflow_metadata;"
.venv/bin/airflow db migrate
```

## Lancer le DAG

Sans webserver/scheduler (suffisant pour développer et vérifier un DAG) :

```bash
.venv/bin/airflow dags test gsci_bronze_silver_gold 2024-01-01
```

Avec l'interface web (nécessite un utilisateur admin) :

```bash
.venv/bin/airflow users create --username admin --password admin \
  --firstname A --lastname D --role Admin --email admin@example.com
.venv/bin/airflow webserver --port 8080 &
.venv/bin/airflow scheduler &
```

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

Tests structurels uniquement (parsing du DAG, nombre de tâches,
dépendances) — le comportement d'exécution réel (succès et échec) a été
vérifié manuellement via `airflow dags test`, voir ADR-008 pour le détail
des deux runs observés (un succès complet, un échec contrôlé avec retry
et blocage correct des tâches en aval).

## Pourquoi un environnement séparé du backend ?

Airflow épingle des versions de SQLAlchemy/Flask/etc. qui entreraient en
conflit avec celles utilisées par FastAPI si installées dans le même
environnement Python. Le DAG appelle le CLI du backend
(`python -m app.cli ...`) via `BashOperator`, en sous-processus avec le
Python du backend — les deux environnements communiquent par
sous-processus, jamais par import direct. Voir ADR-008.
