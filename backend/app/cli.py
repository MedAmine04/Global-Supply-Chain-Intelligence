"""CLI d'ingestion Bronze.

Usage:
    python -m app.cli ingest-all --dir data/raw
    python -m app.cli ingest --entity suppliers --file data/raw/suppliers.csv

En Phase 2, ce rôle de déclenchement sera repris par un DAG Airflow ;
en attendant, ce CLI est la façon "officielle" de lancer une ingestion,
plutôt qu'un script ad hoc lancé à la main sans traçabilité.
"""

import argparse
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.services.data_quality import run_quality_check
from app.services.gold_transform import transform_gold
from app.services.ingestion import IngestionResult, ingest_directory, ingest_file
from app.services.silver_transform import transform_batch_to_silver
from app.services.spark_transform import transform_fact_shipments_spark


def _print_result(result: IngestionResult) -> None:
    status = "OK" if result.success else "ERREUR"
    print(
        f"[{status}] {result.entity:<12} "
        f"lues={result.rows_read:<6} ingérées={result.rows_ingested:<6} "
        f"batch={result.batch_id}"
    )
    for err in result.errors:
        print(f"    -> {err}")


def _print_silver_result(result) -> None:
    cast_warning = (
        f" | ATTENTION erreurs_de_cast={result.rows_cast_errors}"
        if result.rows_cast_errors
        else ""
    )
    print(
        f"    Silver: considérées={result.rows_considered:<6} "
        f"ignorées(invalides)={result.rows_skipped_invalid:<6} "
        f"créées={result.rows_created:<6} mises_à_jour={result.rows_updated:<6}"
        + cast_warning
    )


def cmd_ingest(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = ingest_file(db, args.entity, Path(args.file))
        _print_result(result)
        if result.success and not args.skip_quality_check:
            report = run_quality_check(db, args.entity, result.batch_id)
            print()
            print(report.print_summary())
            if not args.skip_silver:
                silver_result = transform_batch_to_silver(db, args.entity, result.batch_id)
                print()
                _print_silver_result(silver_result)
        return 0 if result.success else 1
    finally:
        db.close()


def cmd_ingest_all(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        results = ingest_directory(db, Path(args.dir))
        if not results:
            print(f"Aucun fichier reconnu dans {args.dir}")
            return 1
        for result in results:
            _print_result(result)
            if result.success and not args.skip_quality_check:
                report = run_quality_check(db, result.entity, result.batch_id)
                print()
                print(report.print_summary())
                if not args.skip_silver:
                    silver_result = transform_batch_to_silver(db, result.entity, result.batch_id)
                    print()
                    _print_silver_result(silver_result)
                print()
        return 0 if all(r.success for r in results) else 1
    finally:
        db.close()


def cmd_quality_check(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        report = run_quality_check(db, args.entity, args.batch)
        print(report.print_summary())
        return 0
    finally:
        db.close()


def cmd_transform_silver(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = transform_batch_to_silver(db, args.entity, args.batch)
        print(f"Silver transform — {result.entity} / batch {result.batch_id}")
        _print_silver_result(result)
        return 0
    finally:
        db.close()


def cmd_transform_gold(args: argparse.Namespace) -> int:  # noqa: ARG001 - signature uniforme du CLI
    db = SessionLocal()
    try:
        result = transform_gold(db)
        print(result.print_summary())
        return 0
    finally:
        db.close()


def cmd_transform_shipments_spark(args: argparse.Namespace) -> int:  # noqa: ARG001
    db = SessionLocal()
    try:
        result = transform_fact_shipments_spark(db)
        print(
            f"Spark fact_shipments: considérées={result.rows_considered} "
            f"ignorées={result.rows_skipped_invalid} créées={result.rows_created} "
            f"mises_à_jour={result.rows_updated}"
        )
        return 0
    finally:
        db.close()


def cmd_kafka_produce(args: argparse.Namespace) -> int:
    from app.services.kafka_producer import publish_shipment_status_updated

    event = publish_shipment_status_updated(args.shipment, args.previous_status, args.status)
    print(f"Événement publié: {event.event_id} ({args.shipment} -> {args.status})")
    return 0


def cmd_kafka_consume(args: argparse.Namespace) -> int:
    from app.services.kafka_consumer import run_consumer_loop

    count = run_consumer_loop(SessionLocal, max_messages=args.max_messages, timeout=args.timeout)
    print(f"{count} événement(s) traité(s)")
    return 0


def cmd_train_model(args: argparse.Namespace) -> int:  # noqa: ARG001
    from app.ml.train import train_and_compare_models

    db = SessionLocal()
    try:
        result = train_and_compare_models(db)
        print(f"Meilleur modèle : {result.best_model_name}\n")
        for name, m in result.metrics_by_model.items():
            print(
                f"{name:<20} precision={m.precision:<7} recall={m.recall:<7} "
                f"f1={m.f1:<7} roc_auc={m.roc_auc:<7} "
                f"(train={m.train_size}, test={m.test_size})"
            )
        print(f"\nModèle sauvegardé : {result.model_path}")
        return 0
    finally:
        db.close()


def cmd_predict_risk(args: argparse.Namespace) -> int:  # noqa: ARG001
    from app.services.ml_predict import ModelNotTrainedError, predict_at_risk_shipments

    db = SessionLocal()
    try:
        try:
            result = predict_at_risk_shipments(db)
        except ModelNotTrainedError as exc:
            print(f"Erreur: {exc}")
            return 1
        print(
            f"{result.shipments_scored} expédition(s) scorée(s), "
            f"{result.high_risk_count} à risque élevé (probabilité >= 0.5)"
        )
        return 0
    finally:
        db.close()


def cmd_train_incident_classifier(args: argparse.Namespace) -> int:  # noqa: ARG001
    from app.nlp.classify import train_incident_classifier

    db = SessionLocal()
    try:
        r = train_incident_classifier(db)
        print(f"Baseline (classe majoritaire) : accuracy={r.baseline_accuracy}")
        print(f"TF-IDF + LogReg               : accuracy={r.accuracy} macro_f1={r.macro_f1}")
        print(f"(train={r.train_size}, test={r.test_size})\n")
        for label, m in r.per_class.items():
            print(
                f"  {label:<15} precision={m['precision']:.2f} "
                f"recall={m['recall']:.2f} support={int(m['support'])}"
            )
        return 0
    finally:
        db.close()


def cmd_enrich_incidents(args: argparse.Namespace) -> int:  # noqa: ARG001
    from app.nlp.enrich import ClassifierNotTrainedError, enrich_incidents

    db = SessionLocal()
    try:
        try:
            r = enrich_incidents(db)
        except ClassifierNotTrainedError as exc:
            print(f"Erreur: {exc}")
            return 1
        print(
            f"{r.incidents_enriched} incident(s) enrichi(s) "
            f"(durée trouvée: {r.with_duration}, lieu trouvé: {r.with_location})"
        )
        return 0
    finally:
        db.close()


def cmd_search_incidents(args: argparse.Namespace) -> int:
    from app.nlp.search import search_incidents

    db = SessionLocal()
    try:
        for hit in search_incidents(db, args.query, limit=args.limit):
            print(f"[{hit.score:.2f}] {hit.incident_id} ({hit.incident_type}) {hit.description}")
        return 0
    finally:
        db.close()


def cmd_train_damage_classifier(args: argparse.Namespace) -> int:
    from app.cv.train import train_damage_classifier

    folder = Path(args.image_folder) if args.image_folder else None
    r = train_damage_classifier(n_samples=args.n_samples, epochs=args.epochs, image_folder=folder)
    print(f"precision={r.precision} recall={r.recall} f1={r.f1}")
    print(f"confusion_matrix={r.confusion_matrix}")
    print(f"(train={r.train_size}, test={r.test_size})")
    print(f"Modèle sauvegardé : {r.model_path}")
    return 0


def cmd_score_images(args: argparse.Namespace) -> int:
    from app.cv.predict import DamageModelNotTrainedError, predict_damage_from_folder

    try:
        results = predict_damage_from_folder(Path(args.folder))
    except DamageModelNotTrainedError as exc:
        print(f"Erreur: {exc}")
        return 1
    if not results:
        print(f"Aucune image trouvée dans {args.folder}")
        return 1
    for name, pred in sorted(results.items()):
        label = "ENDOMMAGÉ" if pred.is_damaged else "normal"
        print(f"{name:<30} probabilité={pred.probability:<7} [{label}]")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_ingest = subparsers.add_parser("ingest", help="Ingère un seul fichier")
    p_ingest.add_argument("--entity", required=True, choices=[
        "suppliers", "products", "warehouses", "orders", "shipments", "incidents"
    ])
    p_ingest.add_argument("--file", required=True)
    p_ingest.add_argument("--skip-quality-check", action="store_true")
    p_ingest.add_argument("--skip-silver", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

    p_all = subparsers.add_parser(
        "ingest-all", help="Ingère tous les fichiers reconnus d'un dossier"
    )
    p_all.add_argument("--dir", default="data/raw")
    p_all.add_argument("--skip-quality-check", action="store_true")
    p_all.add_argument("--skip-silver", action="store_true")
    p_all.set_defaults(func=cmd_ingest_all)

    p_quality = subparsers.add_parser(
        "quality-check", help="Rejoue un contrôle qualité sur un batch déjà ingéré"
    )
    p_quality.add_argument("--entity", required=True, choices=[
        "suppliers", "products", "warehouses", "orders", "shipments", "incidents"
    ])
    p_quality.add_argument("--batch", required=True, help="batch_id retourné par l'ingestion")
    p_quality.set_defaults(func=cmd_quality_check)

    p_silver = subparsers.add_parser(
        "transform-silver", help="Rejoue la transformation Silver sur un batch déjà contrôlé"
    )
    p_silver.add_argument("--entity", required=True, choices=[
        "suppliers", "products", "warehouses", "orders", "shipments", "incidents"
    ])
    p_silver.add_argument("--batch", required=True)
    p_silver.set_defaults(func=cmd_transform_silver)

    p_gold = subparsers.add_parser(
        "transform-gold",
        help="Reconstruit les tables Gold (dimensions + faits) depuis l'état courant de Silver",
    )
    p_gold.set_defaults(func=cmd_transform_gold)

    p_gold_spark = subparsers.add_parser(
        "transform-shipments-spark",
        help="Réimplémentation Spark de la transformation fact_shipments (Phase 2)",
    )
    p_gold_spark.set_defaults(func=cmd_transform_shipments_spark)

    p_kproduce = subparsers.add_parser(
        "kafka-produce-status",
        help="Publie un événement shipment_status_updated (nécessite un broker Kafka accessible)",
    )
    p_kproduce.add_argument("--shipment", required=True)
    p_kproduce.add_argument("--status", required=True)
    p_kproduce.add_argument("--previous-status", default=None)
    p_kproduce.set_defaults(func=cmd_kafka_produce)

    p_kconsume = subparsers.add_parser(
        "kafka-consume-status",
        help="Consomme les événements shipment_status_updated (broker Kafka requis)",
    )
    p_kconsume.add_argument("--max-messages", type=int, default=None)
    p_kconsume.add_argument("--timeout", type=float, default=5.0)
    p_kconsume.set_defaults(func=cmd_kafka_consume)

    p_train = subparsers.add_parser(
        "train-model", help="Entraîne et compare les modèles de prédiction de retard (FR-11)"
    )
    p_train.set_defaults(func=cmd_train_model)

    p_predict = subparsers.add_parser(
        "predict-risk", help="Score les expéditions en cours avec le modèle entraîné (FR-13)"
    )
    p_predict.set_defaults(func=cmd_predict_risk)

    p_tic = subparsers.add_parser(
        "train-incident-classifier", help="Entraîne le classifieur de type d'incident (NLP)"
    )
    p_tic.set_defaults(func=cmd_train_incident_classifier)

    p_enrich = subparsers.add_parser(
        "enrich-incidents", help="Type prédit + entités extraites pour chaque incident"
    )
    p_enrich.set_defaults(func=cmd_enrich_incidents)

    p_search = subparsers.add_parser("search-incidents", help="Recherche textuelle d'incidents")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=5)
    p_search.set_defaults(func=cmd_search_incidents)

    p_cvtrain = subparsers.add_parser(
        "train-damage-classifier", help="Entraîne le CNN de détection de dommages (Phase 5)"
    )
    p_cvtrain.add_argument("--n-samples", type=int, default=3000)
    p_cvtrain.add_argument("--epochs", type=int, default=50)
    p_cvtrain.add_argument(
        "--image-folder", default=None, help="Photos réelles (normal/, damaged/)"
    )
    p_cvtrain.set_defaults(func=cmd_train_damage_classifier)

    p_cvscore = subparsers.add_parser("score-images", help="Score un dossier d'images de colis")
    p_cvscore.add_argument("--folder", required=True)
    p_cvscore.set_defaults(func=cmd_score_images)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
