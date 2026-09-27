"""Service analytics (FR-06).

Rôle : transformer les lignes brutes du repository en réponses
présentables (pourcentages calculés et arrondis, tri, valeurs par
défaut). Ne contient aucune requête SQL — c'est le rôle exclusif du
repository (cf. app/repositories/README.md).
"""

from sqlalchemy.orm import Session

from app.repositories import analytics as repo
from app.schemas.analytics import (
    AtRiskShipment,
    OverviewKPIs,
    RegionTransportBreakdown,
    SupplierPerformance,
)


def _rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(100 * numerator / denominator, 2)


def get_overview_kpis(db: Session) -> OverviewKPIs:
    total_orders = repo.count_orders(db)
    total_shipments = repo.count_shipments(db)
    delivered, delayed, avg_delay = repo.delivered_shipments_stats(db)
    shipments_with_incident = repo.count_shipments_with_incident(db)

    return OverviewKPIs(
        total_orders=total_orders,
        total_shipments=total_shipments,
        delivered_shipments=delivered,
        on_time_delivery_rate=_rate(delivered - delayed, delivered),
        average_delay_days=round(avg_delay, 2) if avg_delay is not None else None,
        incident_rate=_rate(shipments_with_incident, total_shipments),
    )


def get_supplier_performance(db: Session) -> list[SupplierPerformance]:
    rows = repo.supplier_performance(db)
    results = [
        SupplierPerformance(
            supplier_id=supplier_id,
            name=name,
            country=country,
            total_shipments=total,
            delayed_shipments=delayed,
            delay_rate=_rate(delayed, total),
            incident_count=incident_count,
        )
        for supplier_id, name, country, total, delayed, incident_count in rows
    ]
    # Tri par taux de retard décroissant : le cas d'usage principal
    # (persona Supply Chain Manager) est "quels fournisseurs sont les plus
    # à risque", pas un ordre alphabétique.
    return sorted(results, key=lambda r: r.delay_rate, reverse=True)


def get_region_transport_breakdown(db: Session) -> list[RegionTransportBreakdown]:
    rows = repo.region_transport_breakdown(db)
    results = [
        RegionTransportBreakdown(
            region=region,
            transport_mode=transport_mode,
            total_shipments=total,
            delayed_shipments=delayed,
            delay_rate=_rate(delayed, total),
        )
        for region, transport_mode, total, delayed in rows
    ]
    return sorted(results, key=lambda r: r.delay_rate, reverse=True)


def get_at_risk_shipments(db: Session, limit: int = 20) -> list[AtRiskShipment]:
    rows = repo.at_risk_shipments(db, limit=limit)
    return [
        AtRiskShipment(
            shipment_id=shipment_id,
            supplier_name=supplier_name,
            warehouse_name=warehouse_name,
            transport_mode=transport_mode,
            probability=probability,
            predicted_label=predicted_label,
            model_name=model_name,
        )
        for (
            shipment_id, supplier_name, warehouse_name, transport_mode,
            probability, predicted_label, model_name,
        ) in rows
    ]
