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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
