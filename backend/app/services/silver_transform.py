"""Service de transformation Bronze -> Silver (FR-03).

Principe (cf. ADR-004) : Silver ne reprend QUE les lignes d'un batch qui
ont été validées par le dernier contrôle qualité (FR-02) de ce batch — un
contrôle qualité doit donc avoir été exécuté avant de transformer un
batch, sinon on lève une erreur explicite plutôt que de deviner.

Chaque ligne valide est :
1. typée strictement (Date, Integer, Float) — c'est ce qui distingue
   Silver de Bronze ;
2. upsertée dans la table Silver, sur la clé métier (`supplier_id`,
   `order_id`, ...) — pas de doublon possible en Silver, contrairement à
   Bronze qui est insert-only.
"""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.models.bronze import BRONZE_MODELS
from app.models.data_quality import DataQualityReport as DataQualityReportModel
from app.models.silver import SILVER_MODELS, SILVER_NATURAL_KEY
from app.services.data_quality import ENTITY_RULES

# Type cible par champ numérique (int vs float) — ENTITY_RULES ne précise
# que les bornes de validation, pas le type Python cible, donc on le
# déclare séparément ici plutôt que de surcharger le rôle de ENTITY_RULES.
NUMERIC_TYPES: dict[str, dict[str, type]] = {
    "suppliers": {"reliability_score": float},
    "products": {"unit_cost": float},
    "warehouses": {"capacity": int},
    "orders": {"quantity": int},
    "shipments": {"distance_km": float},
    "incidents": {},
}


class QualityCheckMissingError(RuntimeError):
    """Levée quand on tente une transformation Silver sans contrôle qualité préalable."""


@dataclass
class SilverTransformResult:
    entity: str
    batch_id: str
    rows_considered: int
    rows_skipped_invalid: int
    rows_created: int
    rows_updated: int
    rows_cast_errors: int


def _cast_value(raw_value, target_type):
    """Convertit une valeur Bronze (str) vers son type Silver cible.

    Retourne None si la valeur est absente ou non convertible : à ce
    stade, une valeur non convertible n'est censée exister que si la
    ligne n'a *pas* été détectée par FR-02 (cas non couvert par les
    règles actuelles) ; on ne fait pas planter tout le batch pour ça,
    mais on le compte pour rester visible plutôt que silencieux.
    """
    if raw_value is None:
        return None
    try:
        if target_type is date:
            return datetime.fromisoformat(str(raw_value)).date()
        return target_type(raw_value)
    except (TypeError, ValueError):
        return None


def transform_batch_to_silver(db: Session, entity: str, batch_id: str) -> SilverTransformResult:
    if entity not in SILVER_MODELS:
        raise ValueError(f"Entité inconnue : '{entity}'. Entités valides : {list(SILVER_MODELS)}")

    report = (
        db.query(DataQualityReportModel)
        .filter_by(entity=entity, batch_id=batch_id)
        .order_by(DataQualityReportModel.generated_at.desc())
        .first()
    )
    if report is None:
        raise QualityCheckMissingError(
            f"Aucun contrôle qualité trouvé pour entity='{entity}' batch='{batch_id}'. "
            "Exécutez `quality-check` avant la transformation Silver (cf. ADR-004)."
        )

    bronze_model = BRONZE_MODELS[entity]
    silver_model = SILVER_MODELS[entity]
    natural_key = SILVER_NATURAL_KEY[entity]
    rejected_ids = set(report.rejected_row_ids)

    bronze_rows = db.query(bronze_model).filter(bronze_model.batch_id == batch_id).all()
    valid_rows = [r for r in bronze_rows if r.id not in rejected_ids]

    date_fields = set(ENTITY_RULES[entity]["date_fields"])
    numeric_types = NUMERIC_TYPES[entity]

    silver_columns = {c.name for c in silver_model.__table__.columns} - {
        "id", "source_batch_id", "silver_loaded_at", "silver_updated_at"
    }

    rows_created = 0
    rows_updated = 0
    rows_cast_errors = 0

    for bronze_row in valid_rows:
        payload = {}
        cast_failed = False
        for column in silver_columns:
            raw_value = getattr(bronze_row, column, None)
            if column in date_fields:
                value = _cast_value(raw_value, date)
            elif column in numeric_types:
                value = _cast_value(raw_value, numeric_types[column])
            else:
                value = raw_value
            if raw_value is not None and value is None:
                cast_failed = True
            payload[column] = value

        if cast_failed:
            rows_cast_errors += 1

        natural_value = payload[natural_key]
        existing = (
            db.query(silver_model)
            .filter(getattr(silver_model, natural_key) == natural_value)
            .first()
        )
        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
            existing.source_batch_id = batch_id
            rows_updated += 1
        else:
            db.add(silver_model(source_batch_id=batch_id, **payload))
            rows_created += 1

    db.commit()

    return SilverTransformResult(
        entity=entity,
        batch_id=batch_id,
        rows_considered=len(bronze_rows),
        rows_skipped_invalid=len(bronze_rows) - len(valid_rows),
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_cast_errors=rows_cast_errors,
    )
