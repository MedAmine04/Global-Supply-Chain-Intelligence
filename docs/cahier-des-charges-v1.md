# Cahier des Charges Fonctionnel — V1
## Global Supply Chain Intelligence

> Ce document fige le périmètre fonctionnel de la **V1 (MVP)** du projet. Il servira de base à l'architecture technique détaillée et au backlog GitHub (issues, milestones, releases `v0.1.0` → `v0.4.0`).

---

## 1. Objectif du document

Définir précisément :
- les fonctionnalités attendues, numérotées `FR-XX` ;
- les parcours utilisateurs associés ;
- les données consommées/produites par chaque fonctionnalité ;
- ce qui est **MVP**, **Avancé** (post-V1) ou **Hors périmètre**.

Règle : une fonctionnalité qui n'a pas de FR n'existe pas pour l'équipe de dev.

---

## 2. Rappel des personas (issus du blueprint)

| Persona | Besoin principal |
|---|---|
| Supply Chain Manager | Suivre la performance, identifier les risques |
| Data Analyst | Explorer, filtrer, exporter les données |
| Data Engineer | Surveiller les pipelines et la qualité des données |
| AI User | Poser des questions en langage naturel |
| Operations | Analyser incidents, dommages, problèmes transport |

---

## 3. Portée de la V1

La V1 correspond aux releases **v0.1.0 à v0.4.0** du blueprint : Foundation, Data Platform, Big Data (partiel), Predictive Analytics (baseline). NLP, Computer Vision, AI Copilot, RAG et Production sont classés **Avancé** et traités dans le cahier des charges V2.

---

## 4. Fonctionnalités — Data Platform

### FR-01 — Ingestion batch des fichiers sources
**Description** : Le système ingère des fichiers (CSV/Parquet) représentant suppliers, products, orders, shipments, warehouses, incidents, dans la couche Bronze.
**Parcours** : Data Engineer dépose un fichier → pipeline détecte le fichier → ingestion automatique → log de traçabilité.
**Données** : fichiers source → table `bronze.*` (données brutes, non modifiées).
**Statut** : MVP.

### FR-02 — Contrôle qualité des données (Data Quality Report)
**Description** : Après ingestion, chaque batch est validé (schéma, nulls, doublons, dates, clés étrangères) et un rapport est généré.
**Parcours** : Data Engineer consulte le rapport de qualité après chaque run.
**Données** : entrée = table Bronze ; sortie = `DATA QUALITY REPORT` (rows processed, valid, rejected, motifs de rejet).
**Statut** : MVP.

### FR-03 — Transformation Bronze → Silver
**Description** : Nettoyage, typage, déduplication, validation des données rejetées ou corrigées.
**Parcours** : automatique, déclenché après FR-02.
**Données** : `bronze.*` → `silver.*`.
**Statut** : MVP.

### FR-04 — Transformation Silver → Gold (modèle dimensionnel)
**Description** : Construction du star schema : `fact_orders`, `fact_shipments`, `fact_inventory`, `fact_incidents` et dimensions (`dim_supplier`, `dim_product`, `dim_customer`, `dim_warehouse`, `dim_date`, `dim_location`, `dim_transport`).
**Parcours** : automatique.
**Données** : `silver.*` → `gold.*` (PostgreSQL).
**Statut** : MVP.

### FR-05 — Orchestration des pipelines
**Description** : Enchaînement Bronze → Silver → Gold planifié et rejouable, avec historique des exécutions.
**Parcours** : Data Engineer déclenche ou consulte l'historique d'un run.
**Données** : métadonnées d'exécution (statut, durée, erreurs).
**Statut** : MVP (orchestrateur simple type cron/script) ; **Avancé** = Airflow.

### FR-06 — API de consultation des données Gold
**Description** : Endpoints FastAPI exposant les KPI et données agrégées (shipments, suppliers, orders) avec filtres (date, région, fournisseur).
**Parcours** : Frontend interroge l'API pour peupler le dashboard.
**Données** : `gold.*` → JSON.
**Statut** : MVP.

---

## 5. Fonctionnalités — Dashboard / Analytics

### FR-07 — Vue d'ensemble opérationnelle
**Description** : Affichage des KPI globaux : total orders, total shipments, on-time delivery rate, average delay, incident rate.
**Parcours** : Supply Chain Manager ouvre le dashboard.
**Données** : `fact_shipments`, `fact_orders`, `fact_incidents`.
**Statut** : MVP.

### FR-08 — Analyse par fournisseur
**Description** : Tableau/graphique comparant les fournisseurs (taux de retard, incidents, fiabilité).
**Parcours** : Data Analyst filtre par fournisseur ou trie par risque.
**Données** : `dim_supplier` + agrégations `fact_shipments`.
**Statut** : MVP.

### FR-09 — Analyse par région / transport
**Description** : Répartition des retards et incidents par région et par mode de transport.
**Parcours** : Operations identifie les zones à problème.
**Données** : `dim_location`, `dim_transport`, `fact_incidents`.
**Statut** : MVP.

### FR-10 — Export des données filtrées
**Description** : Export CSV des données affichées après filtrage.
**Parcours** : Data Analyst exporte un extrait pour analyse externe.
**Données** : résultat de requête filtrée → fichier CSV.
**Statut** : Avancé (post-V1).

---

## 6. Fonctionnalités — Machine Learning (baseline)

### FR-11 — Prédiction de retard d'expédition
**Description** : Modèle prédisant `delayed = 0/1` par shipment à partir de features (historique fournisseur, distance, mode de transport, saison, congestion entrepôt, incidents précédents).
**Parcours** : le score est calculé en batch et exposé via API.
**Données** : `gold.*` (features) → table `predictions` (probabilité, classe).
**Statut** : MVP (modèle baseline : Logistic Regression puis Random Forest/XGBoost en comparaison).

### FR-12 — Suivi des expérimentations ML
**Description** : Chaque entraînement (paramètres, métriques, modèle) est tracé.
**Parcours** : Data Engineer/ML compare les runs.
**Données** : métriques (Precision, Recall, F1, ROC-AUC) et artefacts modèle.
**Statut** : MVP (log simple) ; **Avancé** = MLflow avec Model Registry.

### FR-13 — Affichage des expéditions à risque
**Description** : Liste/carte des shipments classés par risque de retard prédit.
**Parcours** : Supply Chain Manager consulte la liste triée par probabilité de retard.
**Données** : table `predictions` jointe à `fact_shipments`.
**Statut** : MVP.

### FR-14 — Explicabilité des prédictions (facteurs contributifs)
**Description** : Pour chaque shipment à risque, afficher les facteurs principaux (ex. historique fournisseur, distance, incidents).
**Parcours** : Supply Chain Manager clique sur un shipment à risque et voit le détail.
**Données** : sortie du modèle + valeurs SHAP.
**Statut** : Avancé (post-V1).

---

## 7. Fonctionnalités — Fondations techniques

### FR-15 — Authentification utilisateur
**Description** : Connexion par email/mot de passe, gestion de session.
**Parcours** : tout utilisateur se connecte avant d'accéder au dashboard.
**Données** : table `users` (email, hash mot de passe, rôle).
**Statut** : MVP.

### FR-16 — Gestion des rôles (RBAC basique)
**Description** : Distinction Manager / Analyst / Engineer avec accès différenciés (ex. seul l'Engineer voit les rapports de qualité).
**Parcours** : l'interface adapte les menus visibles selon le rôle.
**Données** : champ `role` sur `users`.
**Statut** : Avancé (post-V1) ; V1 = un seul rôle générique.

### FR-17 — Pipeline CI (lint, tests, build)
**Description** : À chaque Pull Request, exécution automatique des tests backend/frontend et build Docker.
**Parcours** : Data/Software Engineer ouvre une PR → CI s'exécute → statut visible sur GitHub.
**Données** : logs CI, rapport de couverture de tests.
**Statut** : MVP.

### FR-18 — Conteneurisation de l'environnement de dev
**Description** : `docker-compose` permettant de lancer API, base de données et frontend en local en une commande.
**Parcours** : tout développeur clone le repo et lance l'environnement.
**Données** : N/A (infrastructure).
**Statut** : MVP.

### FR-19 — Journalisation applicative (logs)
**Description** : Logs structurés côté API (requêtes, erreurs, durée des traitements ML/pipeline).
**Parcours** : Data Engineer diagnostique un incident via les logs.
**Données** : fichiers/flux de logs.
**Statut** : MVP (basique) ; **Avancé** = Prometheus + Grafana.

---

## 8. Hors périmètre V1 (rappel, traité en V2+)

| Domaine | Fonctionnalités concernées | Release cible |
|---|---|---|
| Big Data temps réel | Kafka, streaming | v0.3.0 |
| NLP | Classification d'incidents, NER, recherche sémantique | v0.5.0 |
| Computer Vision | Détection de dommages sur images colis | v0.6.0 |
| AI Copilot | Questions en langage naturel, orchestration LLM | v0.7.0 |
| RAG | Recherche documentaire (contrats, politiques), citations de sources | v0.8.0 |
| Production | Monitoring complet, sécurité avancée, déploiement Azure/Terraform | v0.9.0 |
| Explicabilité SHAP | Détail des facteurs de risque par expédition | v0.4.x (avancé) |
| Export de données | Export CSV filtré | v0.4.x (avancé) |
| RBAC complet | Rôles différenciés par persona | v0.9.0 |

---

## 9. Définition du "Done" pour chaque FR (V1)

Une FR n'est considérée terminée que si :
- [ ] code implémenté et revu (Pull Request mergée) ;
- [ ] tests unitaires associés ;
- [ ] documentation (README ou docstring) à jour ;
- [ ] logs/erreurs gérés ;
- [ ] fonctionne dans l'environnement Docker local ;
- [ ] CI verte.

---

## 10. Prochaines étapes

1. Convertir chaque FR en issue GitHub, regroupées en milestones `v0.1.0` → `v0.4.0`.
2. Rédiger les ADR correspondant aux choix déjà actés dans cette V1 (PostgreSQL, FastAPI, modèle dimensionnel, baseline ML).
3. Démarrer l'architecture technique détaillée de la couche Data Platform (FR-01 à FR-06).
