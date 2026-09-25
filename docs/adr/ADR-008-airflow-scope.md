# ADR-008 — Airflow : environnement dédié, BashOperator, vérifié par exécution réelle

## Contexte
Le planning Phase 2 demande de remplacer l'orchestration CLI manuelle
(ADR-002) par de "vrais DAGs avec dépendances, retries, alerting en cas
d'échec". ADR-002 anticipait déjà cette transition : "quand Airflow sera
introduit... un PythonOperator appellera directement `ingest_file()` /
`ingest_directory()` sans aucune réécriture de la logique métier".

## Décisions

### 1. Environnement Python séparé (`airflow/.venv`, pas `backend/requirements.txt`)
Airflow est installé dans un venv dédié sous `airflow/`, avec son propre
`requirements.txt`, plutôt que dans l'environnement du backend.

**Justification** : Airflow épingle des versions précises de
dépendances transverses (SQLAlchemy, Flask, etc.) via son fichier de
contraintes officiel. Les installer dans le même environnement que
FastAPI/SQLAlchemy du backend risquerait de downgrader ou d'entrer en
conflit avec les versions dont le backend a besoin. Un venv séparé
élimine ce risque par construction, au prix d'une installation en deux
temps.

### 2. BashOperator (pas PythonOperator), contrairement au plan initial d'ADR-002
Chaque tâche du DAG appelle `python -m app.cli ...` en sous-processus,
plutôt que d'importer `ingest_file()` / `run_quality_check()` etc.
directement dans du code Python exécuté par Airflow.

**Justification (révision assumée d'ADR-002)** : un `PythonOperator`
importerait le code du backend dans le processus Airflow lui-même, ce
qui nécessiterait d'installer TOUTES les dépendances du backend
(FastAPI, SQLAlchemy, pandas, **PySpark, confluent-kafka**) dans le venv
Airflow — exactement le risque de conflit de versions que la décision 1
cherche à éviter, et une installation bien plus lourde que nécessaire
pour un simple rôle d'orchestration. Le CLI reste l'interface officielle
du pipeline (ADR-002) ; Airflow l'appelle comme le ferait un humain en
ligne de commande, ce qui est finalement plus proche de l'esprit
"orchestrateur découplé de la logique métier" que l'import direct.

### 3. Topologie du DAG reflète les contraintes métier réelles, pas un simple fan-out/fan-in
```
suppliers  ─┐
products   ─┼─→ orders ─→ shipments ─→ incidents ─┐
warehouses ─┘                                      ├─→ transform_gold
                    (+ suppliers, products, warehouses) ─┘
```
**Justification** : une commande référence un fournisseur/produit/
entrepôt (validé par FK en FR-02) ; une expédition référence une
commande ; un incident référence une expédition. Faire dépendre chaque
tâche de ses vraies dépendances de données (pas d'un ordre arbitraire)
est ce qui rend le DAG utile — une vraie panne amont bloque
correctement les tâches qui en dépendent (vérifié ci-dessous), plutôt
que de laisser une tâche aval échouer plus tard pour une raison qui
aurait pu être détectée immédiatement en amont.

### 4. Métadonnées Airflow sur PostgreSQL (pas SQLite)
Cohérent avec ADR-001 (PostgreSQL comme base opérationnelle du projet),
une base `airflow_metadata` dédiée est créée sur la même instance
PostgreSQL plutôt que d'utiliser le SQLite par défaut d'Airflow (qui ne
supporte de toute façon que l'exécuteur séquentiel, inadapté même à un
usage de développement un peu sérieux).

## Vérification réelle effectuée (contrairement à Kafka, ADR-007)
Contrairement à Kafka (bloqué par l'absence totale de broker
installable), **Airflow a pu être installé et exécuté réellement** dans
ce sandbox (pip + venv, pas besoin de Docker). Deux runs complets ont
été observés :

1. **Run de succès** (`airflow dags test gsci_bronze_silver_gold
   2024-01-01`) : les 7 tâches passent à `success` dans l'ordre de
   dépendance correct ; les données Gold produites (4530 commandes,
   1751 expéditions) sont strictement identiques à celles obtenues par
   le CLI direct — l'orchestrateur ne change pas le résultat, seulement
   la façon dont il est déclenché et supervisé.
2. **Run d'échec contrôlé** (fichier `suppliers.csv` temporairement
   absent) : `ingest_suppliers` échoue avec `FileNotFoundError`, passe
   en `UP_FOR_RETRY`, retente après le délai configuré, échoue à
   nouveau, finit en `FAILED`. Les tâches en aval
   (`ingest_orders`, `ingest_shipments`, `ingest_incidents`,
   `transform_gold`) sont toutes marquées `upstream_failed` — jamais
   exécutées — tandis que `ingest_products` et `ingest_warehouses`
   (indépendantes) ont réussi normalement. Comportement de
   dépendance/retry vérifié, pas supposé.

Des tests structurels automatisés (`airflow/tests/test_dag_structure.py`,
6 tests) complètent cette vérification manuelle pour détecter une
régression future (erreur de parsing, dépendance cassée) sans avoir à
rejouer un run complet à chaque fois.

## Compromis / Trade-offs
- Le chemin vers le backend est résolu relativement au fichier DAG
  (`Path(__file__).resolve().parent.parent.parent / "backend"`), pas
  configuré via une Airflow Variable : suffisant tant que DAGs et
  backend restent dans le même repo avec cette structure relative fixe ;
  à revoir si le déploiement sépare un jour ces deux composants.
- Pas de schedule cron actif (`schedule=None`, déclenchement manuel) :
  le blueprint ne précise pas encore de fréquence métier réelle
  (quotidien ? horaire ?) — l'ajouter sans cette information serait une
  décision arbitraire non justifiée.
- `DATABASE_URL` du backend est actuellement codé en dur dans le DAG
  (pas lu depuis une Airflow Connection) : acceptable en développement,
  à corriger avant tout déploiement partagé (cf. Phase 8, sécurité).

## Conséquences
- Le CLI (`app/cli.py`) reste la seule interface testée unitairement
  (Phase 1) ; Airflow orchestre cette interface plutôt que de la
  contourner — aucune logique métier n'existe uniquement "côté DAG".
- La Phase 2 (Spark, Kafka, Airflow) est maintenant complète avec, pour
  chaque brique, une évaluation honnête de ce qui a pu être vérifié
  dans cet environnement contraint et ce qui ne l'a pas pu (ADR-006,
  ADR-007, ADR-008) — Airflow est la brique la mieux vérifiée des
  trois, Kafka la moins bien.
