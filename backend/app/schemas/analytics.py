from pydantic import BaseModel, ConfigDict, Field


class OverviewKPIs(BaseModel):
    total_orders: int
    total_shipments: int
    delivered_shipments: int = Field(description="Expéditions avec une date de livraison connue")
    on_time_delivery_rate: float = Field(description="Pourcentage, 0-100")
    average_delay_days: float | None = Field(
        description="Moyenne (actual - expected) en jours ; négatif = en avance en moyenne"
    )
    incident_rate: float = Field(description="Pourcentage d'expéditions ayant au moins un incident")


class SupplierPerformance(BaseModel):
    supplier_id: str
    name: str
    country: str
    total_shipments: int
    delayed_shipments: int
    delay_rate: float = Field(description="Pourcentage, 0-100")
    incident_count: int


class RegionTransportBreakdown(BaseModel):
    region: str
    transport_mode: str
    total_shipments: int
    delayed_shipments: int
    delay_rate: float = Field(description="Pourcentage, 0-100")


class AtRiskShipment(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    shipment_id: str
    supplier_name: str
    warehouse_name: str
    transport_mode: str
    probability: float = Field(description="Probabilité de retard, 0-1")
    predicted_label: int
    model_name: str
