"""Repository analytics (FR-06).

Rôle strict : traduire une question en requête SQLAlchemy sur les tables
Gold, et retourner des lignes brutes (tuples/Row). Aucun calcul de
pourcentage, aucun arrondi, aucune règle métier ici — c'est le rôle de
`app/services/analytics.py` (cf. repositories/README.md, Phase 0).
"""

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.gold import (
    DimSupplier,
    DimTransport,
    DimWarehouse,
    FactIncident,
    FactOrder,
    FactShipment,
)


def count_orders(db: Session) -> int:
    return db.query(func.count(FactOrder.order_sk)).scalar() or 0


def count_shipments(db: Session) -> int:
    return db.query(func.count(FactShipment.shipment_sk)).scalar() or 0


def delivered_shipments_stats(db: Session) -> tuple[int, int, float | None]:
    """Retourne (total_livrées, en_retard, délai_moyen_en_jours) parmi les
    expéditions ayant une date de livraison réelle connue."""
    row = (
        db.query(
            func.count(FactShipment.shipment_sk),
            func.sum(case((FactShipment.is_delayed.is_(True), 1), else_=0)),
            func.avg(FactShipment.delay_days),
        )
        .filter(FactShipment.actual_delivery_date.isnot(None))
        .one()
    )
    total, delayed, avg_delay = row
    return total or 0, delayed or 0, float(avg_delay) if avg_delay is not None else None


def count_shipments_with_incident(db: Session) -> int:
    return (
        db.query(func.count(func.distinct(FactIncident.shipment_id)))
        .scalar()
        or 0
    )


def supplier_performance(db: Session) -> list[tuple]:
    """Une ligne par fournisseur : (supplier_id, name, country,
    total_shipments, delayed_shipments, incident_count)."""
    incident_counts = (
        db.query(
            FactShipment.supplier_sk.label("supplier_sk"),
            func.count(func.distinct(FactIncident.incident_id)).label("incident_count"),
        )
        .join(FactIncident, FactIncident.shipment_id == FactShipment.shipment_id)
        .group_by(FactShipment.supplier_sk)
        .subquery()
    )

    return (
        db.query(
            DimSupplier.supplier_id,
            DimSupplier.name,
            DimSupplier.country,
            func.count(FactShipment.shipment_sk),
            func.sum(case((FactShipment.is_delayed.is_(True), 1), else_=0)),
            func.coalesce(incident_counts.c.incident_count, 0),
        )
        .join(FactShipment, FactShipment.supplier_sk == DimSupplier.supplier_sk)
        .outerjoin(incident_counts, incident_counts.c.supplier_sk == DimSupplier.supplier_sk)
        .group_by(
            DimSupplier.supplier_id,
            DimSupplier.name,
            DimSupplier.country,
            incident_counts.c.incident_count,
        )
        .all()
    )


def region_transport_breakdown(db: Session) -> list[tuple]:
    """Une ligne par (région, mode de transport) : (region, transport_mode,
    total_shipments, delayed_shipments)."""
    return (
        db.query(
            DimWarehouse.region,
            DimTransport.transport_mode,
            func.count(FactShipment.shipment_sk),
            func.sum(case((FactShipment.is_delayed.is_(True), 1), else_=0)),
        )
        .join(DimWarehouse, DimWarehouse.warehouse_sk == FactShipment.warehouse_sk)
        .join(DimTransport, DimTransport.transport_sk == FactShipment.transport_sk)
        .group_by(DimWarehouse.region, DimTransport.transport_mode)
        .all()
    )


def at_risk_shipments(db: Session, limit: int = 20) -> list[tuple]:
    """Une ligne par expédition à risque, triée par probabilité de retard
    décroissante : (shipment_id, supplier_name, warehouse_name,
    transport_mode, probability, predicted_label, model_name)."""
    from app.models.predictions import ShipmentDelayPrediction

    return (
        db.query(
            ShipmentDelayPrediction.shipment_id,
            DimSupplier.name,
            DimWarehouse.name,
            DimTransport.transport_mode,
            ShipmentDelayPrediction.probability,
            ShipmentDelayPrediction.predicted_label,
            ShipmentDelayPrediction.model_name,
        )
        .join(FactShipment, FactShipment.shipment_id == ShipmentDelayPrediction.shipment_id)
        .join(DimSupplier, DimSupplier.supplier_sk == FactShipment.supplier_sk)
        .join(DimWarehouse, DimWarehouse.warehouse_sk == FactShipment.warehouse_sk)
        .join(DimTransport, DimTransport.transport_sk == FactShipment.transport_sk)
        .order_by(ShipmentDelayPrediction.probability.desc())
        .limit(limit)
        .all()
    )
