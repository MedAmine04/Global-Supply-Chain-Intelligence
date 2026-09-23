# ADR-006 — Spark pour fact_shipments, sans connecteur JDBC PostgreSQL

## Contexte
Le planning Phase 2 (Big Data) demande une vraie utilisation de Spark,
pas une simple dépendance ajoutée sans usage réel : "réécriture d'au
moins une transformation Silver→Gold en Spark, avec justification".

## Problème
Comment introduire Spark utilement dans un projet dont le stockage
Bronze/Silver/Gold est PostgreSQL (ADR-001), sans disposer d'un accès
réseau à un dépôt Maven pour récupérer un driver JDBC PostgreSQL
(l'environnement de développement restreint l'accès réseau à un
ensemble limité de domaines qui n'inclut pas les dépôts Maven), et sans
sur-investir dans une infrastructure de data lake (MinIO, Parquet) que
le planning ne prévoit qu'en parallèle, pas comme préalable à Spark ?

## Options considérées
1. **Spark + JDBC direct vers PostgreSQL** (lecture Silver, écriture
   Gold) — solution la plus "propre" architecturalement, mais bloquée
   par l'absence de driver JDBC téléchargeable dans cet environnement.
2. **Introduire MinIO + Parquet dès maintenant** pour que Spark lise/
   écrive des fichiers plutôt que PostgreSQL — cohérent à terme, mais
   anticipe une brique (MinIO) que le planning traite en parallèle de
   Kafka/Airflow, pas comme prérequis de Spark.
3. **Spark pour le calcul uniquement**, extraction Silver et écriture
   Gold via SQLAlchemy (comme le reste du projet), Spark intervenant
   entre les deux pour les jointures et le calcul des mesures dérivées.

## Décision
Option 3, avec un périmètre volontairement limité à `fact_shipments` (le
fait le plus complexe : 4 jointures de dimensions + mesures dérivées),
plutôt que de réécrire tout `transform_gold` en Spark.

## Justification
- Une contrainte d'environnement réelle (pas de dépôt Maven accessible)
  ne doit pas bloquer l'apprentissage de Spark : Spark reste utile pour
  le calcul distribué/parallèle même sans lire/écrire directement une
  base via JDBC — beaucoup de pipelines réels combinent Spark pour le
  calcul et un ORM/service applicatif pour l'écriture finale vers un
  système transactionnel.
- Limiter la réécriture à `fact_shipments` évite de dupliquer tout
  `gold_transform.py` en deux implémentations à maintenir en parallèle
  sans bénéfice pédagogique supplémentaire : une seule transformation
  suffit à démontrer l'API DataFrame (jointures, `when`/`otherwise`,
  `datediff`) et le point est fait.
- **La correction a été vérifiée, pas supposée** : un test compare
  explicitement le résultat de la version Spark à celui de la version
  ORM sur le même scénario (`test_spark_transform_matches_orm_transform_on_same_scenario`)
  et vérifie l'égalité stricte des mesures dérivées et des clés de
  substitution résolues.

## Compromis / Trade-offs
- Le passage par pandas comme pont entre SQLAlchemy et Spark
  (`spark.createDataFrame(pandas_df)`) n'a de sens qu'aux volumes de
  développement : à volume réel de production (millions de lignes), ce
  pont deviendrait le goulot d'étranglement que Spark est censé
  éliminer. Ce choix est donc assumé comme démonstratif/pédagogique à ce
  stade, pas comme l'architecture cible de la Phase 8 (Production).
- Un vrai déploiement viserait soit un connecteur JDBC (si l'environnement
  réseau le permet), soit une bascule vers un data lake Parquet une fois
  MinIO introduit — à trancher par un futur ADR quand cette brique sera
  abordée sérieusement, pas décidé prématurément ici.
- Un piège rencontré et corrigé pendant l'implémentation : la conversion
  pandas -> Spark échoue silencieusement (`IndexError`) sur un DataFrame
  pandas vide sans schéma. Corrigé en construisant les petites dimensions
  (`dim_supplier`, `dim_warehouse`, `dim_transport`) avec un schéma Spark
  explicite plutôt que via l'inférence pandas — capturé par
  `test_spark_transform_skips_shipment_with_missing_dimension`.

## Conséquences
- Kafka et Airflow (prochaines briques de la Phase 2) devront chacun
  faire l'objet du même exercice : justifier leur périmètre réel compte
  tenu des contraintes de cet environnement, plutôt que d'être ajoutés
  comme des dépendances symboliques.
- Le CLI expose `transform-shipments-spark` comme commande séparée de
  `transform-gold` (ORM) : les deux coexistent, la version Spark n'a pas
  vocation à remplacer la version ORM à ce stade, seulement à démontrer
  et tester l'équivalence.
