"""Service de transformation Silver -> Gold (FR-04).

Contrairement à Bronze -> Silver (qui opère batch par batch), Gold
transforme l'intégralité du contenu courant de Silver à chaque run
(cf. ADR-005) : les faits dénormalisent des colonnes de plusieurs
dimensions (ex. `fact_shipments` porte `supplier_sk` ET `product_sk`),
et Silver étant déjà déduplié, un run complet est à la fois plus simple
à raisonner et suffisant aux volumes de développement.

Ordre d'exécution obligatoire : dimensions d'abord (elles n'ont pas de
dépendances), puis faits (qui résolvent leurs clés étrangères via les
dimensions).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.gold import (
    DimDate,
    DimProduct,
    DimSupplier,
    DimTransport,
    DimWarehouse,
    FactIncident,
    FactOrder,
    FactShipment,
)
from app.models.silver import (
    SilverIncident,
    SilverOrder,
    SilverProduct,
    SilverShipment,
    SilverSupplier,
    SilverWarehouse,
)

TRANSPORT_MODES = ["road", "sea", "air", "rail"]


@dataclass
class GoldTransformResult:
    tables: dict[str, dict[str, int]] = field(default_factory=dict)

    def print_summary(self) -> str:
        lines = ["GOLD TRANSFORM REPORT", ""]
        for table, counts in self.tables.items():
            lines.append(
                f"{table:<16} créées={counts['created']:<6} "
                f"mises_à_jour={counts['updated']:<6} ignorées={counts.get('skipped', 0)}"
            )
        return "\n".join(lines)


def _upsert(db: Session, model, natural_key: str, natural_value, **payload) -> tuple[object, bool]:
    """Upsert générique sur une colonne de clé naturelle. Retourne (objet, created?)."""
    existing = db.query(model).filter(getattr(model, natural_key) == natural_value).first()
    if existing:
        for k, v in payload.items():
            setattr(existing, k, v)
        return existing, False
    obj = model(**{natural_key: natural_value}, **payload)
    db.add(obj)
    db.flush()  # nécessaire pour obtenir la clé de substitution générée
    return obj, True


def transform_dim_date(db: Session, start: date, end: date) -> dict[str, int]:
    """Peuple dim_date pour la plage [start, end] si les dates n'y sont pas déjà."""
    existing_dates = {d[0] for d in db.query(DimDate.date).all()}
    created = 0
    current = start
    while current <= end:
        if current not in existing_dates:
            db.add(
                DimDate(
                    date=current,
                    year=current.year,
                    month=current.month,
                    day=current.day,
                    quarter=(current.month - 1) // 3 + 1,
                    day_of_week=current.weekday(),
                    is_weekend=current.weekday() >= 5,
                )
            )
            created += 1
        current += timedelta(days=1)
    db.commit()
    return {"created": created, "updated": 0}


def transform_dim_supplier(db: Session) -> dict[str, int]:
    created = updated = 0
    for s in db.query(SilverSupplier).all():
        _, was_created = _upsert(
            db, DimSupplier, "supplier_id", s.supplier_id,
            name=s.name, country=s.country, reliability_score=s.reliability_score,
        )
        created += was_created
        updated += not was_created
    db.commit()
    return {"created": created, "updated": updated}


def transform_dim_product(db: Session) -> dict[str, int]:
    created = updated = 0
    for p in db.query(SilverProduct).all():
        _, was_created = _upsert(
            db, DimProduct, "product_id", p.product_id,
            name=p.name, category=p.category, unit_cost=p.unit_cost,
        )
        created += was_created
        updated += not was_created
    db.commit()
    return {"created": created, "updated": updated}


def transform_dim_warehouse(db: Session) -> dict[str, int]:
    created = updated = 0
    for w in db.query(SilverWarehouse).all():
        _, was_created = _upsert(
            db, DimWarehouse, "warehouse_id", w.warehouse_id,
            name=w.name, country=w.country, region=w.region, capacity=w.capacity,
        )
        created += was_created
        updated += not was_created
    db.commit()
    return {"created": created, "updated": updated}


def transform_dim_transport(db: Session) -> dict[str, int]:
    """Dimension statique (4 valeurs connues) plutôt que dérivée dynamiquement
    de Silver : le domaine de valeurs (road/sea/air/rail) est fixe et connu
    à l'avance, une dimension dérivée n'apporterait rien ici."""
    created = 0
    for mode in TRANSPORT_MODES:
        _, was_created = _upsert(db, DimTransport, "transport_mode", mode)
        created += was_created
    db.commit()
    return {"created": created, "updated": 0}


def transform_fact_orders(db: Session) -> dict[str, int]:
    supplier_sk = {s.supplier_id: s.supplier_sk for s in db.query(DimSupplier).all()}
    product_sk = {p.product_id: p.product_sk for p in db.query(DimProduct).all()}
    warehouse_sk = {w.warehouse_id: w.warehouse_sk for w in db.query(DimWarehouse).all()}

    created = updated = skipped = 0
    for o in db.query(SilverOrder).all():
        if (
            o.supplier_id not in supplier_sk
            or o.product_id not in product_sk
            or o.warehouse_id not in warehouse_sk
        ):
            # Ne devrait pas arriver si les dimensions ont été transformées
            # avant les faits (ordre imposé par transform_gold) ; on
            # protège quand même plutôt que de planter tout le run.
            skipped += 1
            continue

        _, was_created = _upsert(
            db, FactOrder, "order_id", o.order_id,
            supplier_sk=supplier_sk[o.supplier_id],
            product_sk=product_sk[o.product_id],
            warehouse_sk=warehouse_sk[o.warehouse_id],
            order_date=o.order_date,
            quantity=o.quantity,
            status=o.status,
        )
        created += was_created
        updated += not was_created
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def transform_fact_shipments(db: Session) -> dict[str, int]:
    orders_by_id = {o.order_id: o for o in db.query(SilverOrder).all()}
    supplier_sk = {s.supplier_id: s.supplier_sk for s in db.query(DimSupplier).all()}
    product_sk = {p.product_id: p.product_sk for p in db.query(DimProduct).all()}
    warehouse_sk = {w.warehouse_id: w.warehouse_sk for w in db.query(DimWarehouse).all()}
    transport_sk = {t.transport_mode: t.transport_sk for t in db.query(DimTransport).all()}

    created = updated = skipped = 0
    for sh in db.query(SilverShipment).all():
        order = orders_by_id.get(sh.order_id)
        if (
            order is None
            or order.supplier_id not in supplier_sk
            or order.product_id not in product_sk
            or sh.warehouse_id not in warehouse_sk
            or sh.transport_mode not in transport_sk
        ):
            skipped += 1
            continue

        is_delayed = None
        delay_days = None
        if sh.actual_delivery_date and sh.expected_delivery_date:
            delay_days = (sh.actual_delivery_date - sh.expected_delivery_date).days
            is_delayed = delay_days > 0

        _, was_created = _upsert(
            db, FactShipment, "shipment_id", sh.shipment_id,
            order_id=sh.order_id,
            supplier_sk=supplier_sk[order.supplier_id],
            product_sk=product_sk[order.product_id],
            warehouse_sk=warehouse_sk[sh.warehouse_id],
            transport_sk=transport_sk[sh.transport_mode],
            ship_date=sh.ship_date,
            expected_delivery_date=sh.expected_delivery_date,
            actual_delivery_date=sh.actual_delivery_date,
            distance_km=sh.distance_km,
            is_delayed=is_delayed,
            delay_days=delay_days,
        )
        created += was_created
        updated += not was_created
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def transform_fact_incidents(db: Session) -> dict[str, int]:
    known_shipments = {s.shipment_id for s in db.query(SilverShipment).all()}

    created = updated = skipped = 0
    for inc in db.query(SilverIncident).all():
        if inc.shipment_id not in known_shipments:
            skipped += 1
            continue
        _, was_created = _upsert(
            db, FactIncident, "incident_id", inc.incident_id,
            shipment_id=inc.shipment_id,
            incident_type=inc.incident_type,
            severity=inc.severity,
            incident_date=inc.incident_date,
        )
        created += was_created
        updated += not was_created
    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def _silver_date_range(db: Session) -> tuple[date, date] | None:
    """Détermine la plage de dates à couvrir par dim_date à partir du
    contenu réel de Silver, avec une marge de 7 jours de chaque côté."""
    candidates = []
    for model, columns in [
        (SilverOrder, ["order_date"]),
        (SilverShipment, ["ship_date", "expected_delivery_date", "actual_delivery_date"]),
        (SilverIncident, ["incident_date"]),
    ]:
        for col in columns:
            values = [v[0] for v in db.query(getattr(model, col)).all() if v[0] is not None]
            candidates.extend(values)

    if not candidates:
        return None
    return min(candidates) - timedelta(days=7), max(candidates) + timedelta(days=7)


def transform_gold(db: Session) -> GoldTransformResult:
    """Orchestre le run Gold complet : dimensions puis faits, dans cet ordre strict."""
    result = GoldTransformResult()

    date_range = _silver_date_range(db)
    if date_range:
        result.tables["dim_date"] = transform_dim_date(db, *date_range)
    else:
        result.tables["dim_date"] = {"created": 0, "updated": 0}

    result.tables["dim_supplier"] = transform_dim_supplier(db)
    result.tables["dim_product"] = transform_dim_product(db)
    result.tables["dim_warehouse"] = transform_dim_warehouse(db)
    result.tables["dim_transport"] = transform_dim_transport(db)

    result.tables["fact_orders"] = transform_fact_orders(db)
    result.tables["fact_shipments"] = transform_fact_shipments(db)
    result.tables["fact_incidents"] = transform_fact_incidents(db)

    return result
