from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.analytics import (
    AtRiskShipment,
    OverviewKPIs,
    RegionTransportBreakdown,
    SupplierPerformance,
)
from app.services import analytics as service

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/kpis/overview", response_model=OverviewKPIs)
def kpis_overview(db: Session = Depends(get_db)) -> OverviewKPIs:
    """KPI globaux (FR-07) : total orders/shipments, taux de livraison à
    l'heure, délai moyen, taux d'incidents."""
    return service.get_overview_kpis(db)


@router.get("/suppliers/performance", response_model=list[SupplierPerformance])
def suppliers_performance(db: Session = Depends(get_db)) -> list[SupplierPerformance]:
    """Performance par fournisseur (FR-08), triée par taux de retard décroissant."""
    return service.get_supplier_performance(db)


@router.get("/analysis/region-transport", response_model=list[RegionTransportBreakdown])
def region_transport(db: Session = Depends(get_db)) -> list[RegionTransportBreakdown]:
    """Répartition région × mode de transport (FR-09), triée par taux de retard."""
    return service.get_region_transport_breakdown(db)


@router.get("/predictions/at-risk", response_model=list[AtRiskShipment])
def predictions_at_risk(limit: int = 20, db: Session = Depends(get_db)) -> list[AtRiskShipment]:
    """Expéditions les plus à risque de retard (FR-13), triées par
    probabilité décroissante. Nécessite un modèle entraîné
    (`python -m app.cli train-model`) et scoré
    (`python -m app.cli predict-risk`) au préalable."""
    return service.get_at_risk_shipments(db, limit=limit)
