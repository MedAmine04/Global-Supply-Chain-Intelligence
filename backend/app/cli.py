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
from app.services.ingestion import IngestionResult, ingest_directory, ingest_file


def _print_result(result: IngestionResult) -> None:
    status = "OK" if result.success else "ERREUR"
    print(
        f"[{status}] {result.entity:<12} "
        f"lues={result.rows_read:<6} ingérées={result.rows_ingested:<6} "
        f"batch={result.batch_id}"
    )
    for err in result.errors:
        print(f"    -> {err}")


def cmd_ingest(args: argparse.Namespace) -> int:
    db = SessionLocal()
    try:
        result = ingest_file(db, args.entity, Path(args.file))
        _print_result(result)
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
        return 0 if all(r.success for r in results) else 1
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
    p_ingest.set_defaults(func=cmd_ingest)

    p_all = subparsers.add_parser(
        "ingest-all", help="Ingère tous les fichiers reconnus d'un dossier"
    )
    p_all.add_argument("--dir", default="data/raw")
    p_all.set_defaults(func=cmd_ingest_all)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
