"""Service de Data Quality (FR-02).

Contrôle, pour un batch d'ingestion Bronze donné :
- champs requis présents (schéma) ;
- identifiants dupliqués au sein du batch ;
- champs numériques dans une plage valide ;
- dates valides ;
- clés étrangères valides (référence vers une autre table Bronze déjà
  ingérée — au sens large, puisque Bronze n'a pas de contrainte FK en
  base par construction, cf. ADR-002).

Une ligne peut cumuler plusieurs problèmes : elle n'est comptée qu'une
seule fois dans `rows_rejected`, mais chaque problème est compté dans le
détail `issues` pour permettre un vrai diagnostic (pas juste "12 579
lignes rejetées" sans savoir pourquoi).
"""

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.bronze import BRONZE_MODELS
from app.models.data_quality import DataQualityReport as DataQualityReportModel

# Règles déclaratives par entité. Pas de magie : chaque règle est un
# contrôle explicite et testable indépendamment des autres.
ENTITY_RULES: dict[str, dict] = {
    "suppliers": {
        "required_fields": ["supplier_id", "name", "country"],
        "numeric_fields": {"reliability_score": (0.0, 1.0)},
        "date_fields": [],
        "foreign_keys": {},
    },
    "products": {
        "required_fields": ["product_id", "name", "category"],
        "numeric_fields": {"unit_cost": (0.0, None)},
        "date_fields": [],
        "foreign_keys": {},
    },
    "warehouses": {
        "required_fields": ["warehouse_id", "name", "country", "region"],
        "numeric_fields": {"capacity": (1, None)},
        "date_fields": [],
        "foreign_keys": {},
    },
    "orders": {
        "required_fields": [
            "order_id", "supplier_id", "product_id", "warehouse_id",
            "order_date", "quantity", "status",
        ],
        "numeric_fields": {"quantity": (1, None)},
        "date_fields": ["order_date"],
        "foreign_keys": {
            "supplier_id": ("bronze_suppliers", "supplier_id"),
            "product_id": ("bronze_products", "product_id"),
            "warehouse_id": ("bronze_warehouses", "warehouse_id"),
        },
    },
    "shipments": {
        "required_fields": [
            "shipment_id", "order_id", "warehouse_id", "transport_mode",
            "ship_date", "expected_delivery_date",
        ],
        "numeric_fields": {"distance_km": (0, None)},
        "date_fields": ["ship_date", "expected_delivery_date"],
        "foreign_keys": {
            "order_id": ("bronze_orders", "order_id"),
            "warehouse_id": ("bronze_warehouses", "warehouse_id"),
        },
    },
    "incidents": {
        "required_fields": ["incident_id", "shipment_id", "incident_type", "incident_date"],
        "numeric_fields": {},
        "date_fields": ["incident_date"],
        "foreign_keys": {
            "shipment_id": ("bronze_shipments", "shipment_id"),
        },
    },
}

ID_FIELDS = {
    "suppliers": "supplier_id",
    "products": "product_id",
    "warehouses": "warehouse_id",
    "orders": "order_id",
    "shipments": "shipment_id",
    "incidents": "incident_id",
}


@dataclass
class DataQualityReport:
    entity: str
    batch_id: str
    rows_processed: int
    rows_valid: int
    rows_rejected: int
    issues: dict = field(default_factory=dict)

    def print_summary(self) -> str:
        lines = [
            "DATA QUALITY REPORT",
            "",
            f"Entity: {self.entity}",
            f"Batch: {self.batch_id}",
            f"Rows processed: {self.rows_processed}",
            "",
            f"Valid: {self.rows_valid}",
            f"Rejected: {self.rows_rejected}",
            "",
        ]
        for issue_name, detail in self.issues.items():
            if isinstance(detail, dict):
                total = sum(detail.values())
                lines.append(f"{issue_name}: {total}")
                for k, v in detail.items():
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append(f"{issue_name}: {detail}")
        return "\n".join(lines)


def _is_valid_date(value: str | None) -> bool:
    if value is None:
        return False
    try:
        datetime.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def _is_valid_numeric(value: str | None, bounds: tuple) -> bool:
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    low, high = bounds
    if low is not None and number < low:
        return False
    if high is not None and number > high:
        return False
    return True


def run_quality_check(db: Session, entity: str, batch_id: str) -> DataQualityReport:
    if entity not in ENTITY_RULES:
        raise ValueError(f"Entité inconnue : '{entity}'. Entités valides : {list(ENTITY_RULES)}")

    rules = ENTITY_RULES[entity]
    model = BRONZE_MODELS[entity]
    id_field = ID_FIELDS[entity]

    rows = db.query(model).filter(model.batch_id == batch_id).all()
    df = pd.DataFrame([{c.name: getattr(r, c.name) for c in model.__table__.columns} for r in rows])

    rows_processed = len(df)
    issues: dict = {
        "missing_required_fields": {},
        "duplicate_ids": 0,
        "invalid_numeric_fields": {},
        "invalid_dates": {},
        "invalid_foreign_keys": {},
    }
    rejected_row_ids: set[int] = set()  # index interne (id Bronze) des lignes rejetées

    if rows_processed == 0:
        return DataQualityReport(entity, batch_id, 0, 0, 0, issues)

    # 1. Champs requis présents (non null, non vide)
    for required in rules["required_fields"]:
        missing_mask = df[required].isna() | (df[required].astype(str).str.strip() == "")
        count = int(missing_mask.sum())
        if count:
            issues["missing_required_fields"][required] = count
            rejected_row_ids.update(df.loc[missing_mask, "id"].tolist())

    # 2. Doublons d'identifiant au sein du batch
    duplicate_mask = df.duplicated(subset=[id_field], keep="first")
    dup_count = int(duplicate_mask.sum())
    if dup_count:
        issues["duplicate_ids"] = dup_count
        rejected_row_ids.update(df.loc[duplicate_mask, "id"].tolist())

    # 3. Champs numériques dans la plage attendue
    for field_name, bounds in rules["numeric_fields"].items():
        invalid_mask = ~df[field_name].apply(lambda v, b=bounds: _is_valid_numeric(v, b))
        count = int(invalid_mask.sum())
        if count:
            issues["invalid_numeric_fields"][field_name] = count
            rejected_row_ids.update(df.loc[invalid_mask, "id"].tolist())

    # 4. Dates valides (format ISO)
    for field_name in rules["date_fields"]:
        invalid_mask = ~df[field_name].apply(_is_valid_date)
        count = int(invalid_mask.sum())
        if count:
            issues["invalid_dates"][field_name] = count
            rejected_row_ids.update(df.loc[invalid_mask, "id"].tolist())

    # 5. Clés étrangères : la valeur référencée doit exister dans la table Bronze cible
    # (au sens large : "a déjà été vue dans un batch précédent ou celui-ci").
    for field_name, (target_table, target_column) in rules["foreign_keys"].items():
        known_values = {
            row[0]
            for row in db.execute(text(f"SELECT DISTINCT {target_column} FROM {target_table}"))
        }
        invalid_mask = ~df[field_name].isin(known_values)
        count = int(invalid_mask.sum())
        if count:
            issues["invalid_foreign_keys"][field_name] = count
            rejected_row_ids.update(df.loc[invalid_mask, "id"].tolist())

    rows_rejected = len(rejected_row_ids)
    rows_valid = rows_processed - rows_rejected

    report = DataQualityReport(
        entity=entity,
        batch_id=batch_id,
        rows_processed=rows_processed,
        rows_valid=rows_valid,
        rows_rejected=rows_rejected,
        issues=issues,
    )

    db.add(
        DataQualityReportModel(
            entity=entity,
            batch_id=batch_id,
            rows_processed=rows_processed,
            rows_valid=rows_valid,
            rows_rejected=rows_rejected,
            issues=issues,
            rejected_row_ids=sorted(rejected_row_ids),
        )
    )
    db.commit()

    return report
