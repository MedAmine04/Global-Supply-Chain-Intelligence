"""Service d'ingestion Bronze (FR-01).

Rôle unique : prendre un fichier source (CSV) et le charger tel quel
dans la table Bronze correspondante, avec les métadonnées de traçabilité
(source_file, batch_id, row_number, ingested_at). Aucune validation,
aucune transformation métier ici — c'est le rôle de FR-02 (Data Quality)
et FR-03 (Silver).
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

from app.models.bronze import BRONZE_MODELS


class UnknownEntityError(ValueError):
    """Levée quand l'entité demandée n'a pas de table Bronze correspondante."""


@dataclass
class IngestionResult:
    entity: str
    source_file: str
    batch_id: str
    rows_read: int
    rows_ingested: int
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.rows_ingested == self.rows_read and not self.errors


def ingest_file(db: Session, entity: str, file_path: Path) -> IngestionResult:
    """Ingère un fichier CSV dans la table Bronze de l'entité donnée.

    Chaque appel constitue un "batch" (identifié par un UUID), ce qui
    permet de tracer et, si besoin, de rejouer ou d'auditer un run
    d'ingestion précis.
    """
    if entity not in BRONZE_MODELS:
        raise UnknownEntityError(
            f"Entité inconnue : '{entity}'. Entités valides : {list(BRONZE_MODELS)}"
        )

    model = BRONZE_MODELS[entity]
    batch_id = str(uuid.uuid4())
    result = IngestionResult(
        entity=entity, source_file=str(file_path), batch_id=batch_id, rows_read=0, rows_ingested=0
    )

    # keep_default_na=False + na_values=[""] : on ne veut pas que pandas
    # transforme silencieusement des chaînes comme "N/A" en NaN typé —
    # on garde le contrôle explicite de ce qui est considéré manquant,
    # car ce sont justement ces valeurs "sales" que FR-02 doit détecter.
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False, na_values=[""])
    result.rows_read = len(df)

    valid_columns = {c.name for c in model.__table__.columns} - {
        "id", "source_file", "batch_id", "row_number", "ingested_at"
    }

    objects = []
    for row_number, row in enumerate(df.to_dict(orient="records"), start=1):
        payload = {k: v for k, v in row.items() if k in valid_columns}
        # pandas renvoie NaN (float) pour les cellules vides malgré na_values=[""] ;
        # on normalise explicitement en None pour rester cohérent avec le
        # modèle "valeur manquante" attendu en aval par FR-02.
        payload = {k: (None if pd.isna(v) else v) for k, v in payload.items()}
        objects.append(
            model(
                source_file=str(file_path),
                batch_id=batch_id,
                row_number=row_number,
                **payload,
            )
        )

    try:
        db.bulk_save_objects(objects)
        db.commit()
        result.rows_ingested = len(objects)
    except Exception as exc:  # noqa: BLE001 - on veut capturer et reporter, pas juste logguer
        db.rollback()
        result.errors.append(str(exc))

    return result


def ingest_directory(db: Session, directory: Path) -> list[IngestionResult]:
    """Ingère tous les fichiers `<entité>.csv` reconnus d'un dossier.

    Utilisé par le CLI (`app.cli ingest-all`) qui simule le rôle du futur
    orchestrateur (Airflow, Phase 2) : scanner un dossier de dépôt et
    ingérer chaque fichier reconnu.
    """
    results = []
    for entity, _model in BRONZE_MODELS.items():
        file_path = directory / f"{entity}.csv"
        if file_path.exists():
            results.append(ingest_file(db, entity, file_path))
    return results
