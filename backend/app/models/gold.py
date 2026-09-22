"""Modèles de la couche Gold : star schema (faits + dimensions).

Convention : chaque dimension a une clé de substitution technique (`*_sk`,
autoincrement) utilisée par les faits, distincte de l'identifiant métier
(`supplier_id`, etc.) conservé pour traçabilité. Exception : `dim_date`
utilise directement la date comme clé — ajouter une clé de substitution
entière (YYYYMMDD) n'apporterait rien à l'échelle de ce projet et
complexifierait la lecture sans bénéfice réel (cf. ADR-005).
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

class DimSupplier(Base):
    __tablename__ = "dim_supplier"

    supplier_sk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    reliability_score: Mapped[float | None] = mapped_column(Float)


class DimProduct(Base):
    __tablename__ = "dim_product"

    product_sk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(Float)


class DimWarehouse(Base):
    __tablename__ = "dim_warehouse"

    warehouse_sk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    warehouse_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    capacity: Mapped[int | None] = mapped_column(Integer)


class DimTransport(Base):
    __tablename__ = "dim_transport"

    transport_sk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transport_mode: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)


class DimDate(Base):
    """Dimension date. `date` est directement la clé (cf. docstring module)."""

    __tablename__ = "dim_date"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=lundi ... 6=dimanche
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)


# ---------------------------------------------------------------------------
# Faits
# ---------------------------------------------------------------------------

class GoldLoadMixin:
    gold_loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    gold_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FactOrder(GoldLoadMixin, Base):
    __tablename__ = "fact_orders"

    order_sk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    supplier_sk: Mapped[int] = mapped_column(
        ForeignKey("dim_supplier.supplier_sk"), nullable=False
    )
    product_sk: Mapped[int] = mapped_column(
        ForeignKey("dim_product.product_sk"), nullable=False
    )
    warehouse_sk: Mapped[int] = mapped_column(
        ForeignKey("dim_warehouse.warehouse_sk"), nullable=False
    )
    order_date: Mapped[date | None] = mapped_column(ForeignKey("dim_date.date"))

    quantity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), nullable=False)


class FactShipment(GoldLoadMixin, Base):
    """Fait au niveau expédition — dénormalise supplier/product depuis la
    commande associée, pour permettre l'analyse de risque par fournisseur
    directement sur les expéditions (cf. FR-11, feature `supplier_delay_rate`)
    sans jointure systématique via fact_orders (cf. ADR-005)."""

    __tablename__ = "fact_shipments"

    shipment_sk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(100), nullable=False)

    supplier_sk: Mapped[int] = mapped_column(
        ForeignKey("dim_supplier.supplier_sk"), nullable=False
    )
    product_sk: Mapped[int] = mapped_column(
        ForeignKey("dim_product.product_sk"), nullable=False
    )
    warehouse_sk: Mapped[int] = mapped_column(
        ForeignKey("dim_warehouse.warehouse_sk"), nullable=False
    )
    transport_sk: Mapped[int] = mapped_column(
        ForeignKey("dim_transport.transport_sk"), nullable=False
    )

    ship_date: Mapped[date | None] = mapped_column(ForeignKey("dim_date.date"))
    expected_delivery_date: Mapped[date | None] = mapped_column(ForeignKey("dim_date.date"))
    actual_delivery_date: Mapped[date | None] = mapped_column(ForeignKey("dim_date.date"))

    distance_km: Mapped[float | None] = mapped_column(Float)

    # Mesures dérivées, calculées une fois ici plutôt que recalculées à
    # chaque requête analytique (cf. ADR-005).
    is_delayed: Mapped[bool | None] = mapped_column(Boolean)
    delay_days: Mapped[int | None] = mapped_column(Integer)


class FactIncident(GoldLoadMixin, Base):
    __tablename__ = "fact_incidents"

    incident_sk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    shipment_id: Mapped[str] = mapped_column(String(100), nullable=False)

    incident_type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(50))
    incident_date: Mapped[date | None] = mapped_column(ForeignKey("dim_date.date"))
