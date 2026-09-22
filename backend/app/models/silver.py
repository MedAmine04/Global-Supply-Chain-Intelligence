"""Modèles de la couche Silver.

Contrairement à Bronze (colonnes brutes non typées), Silver contient des
colonnes réellement typées (Date, Float, Integer) : le typage strict est
justement ce qui distingue Silver de Bronze (cf. FR-03).

Chaque table Silver est dédupliquée par construction : l'identifiant
métier (`supplier_id`, `order_id`, ...) est une contrainte UNIQUE, et le
service de transformation fait un upsert (update si l'ID existe déjà,
insert sinon) plutôt que d'accumuler des doublons comme en Bronze.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SilverIngestionMixin:
    """Colonnes de traçabilité communes à toutes les tables Silver."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    silver_loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    silver_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SilverSupplier(SilverIngestionMixin, Base):
    __tablename__ = "silver_suppliers"

    supplier_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    reliability_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[date | None] = mapped_column(Date)


class SilverProduct(SilverIngestionMixin, Base):
    __tablename__ = "silver_products"

    product_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_cost: Mapped[float | None] = mapped_column(Float)


class SilverWarehouse(SilverIngestionMixin, Base):
    __tablename__ = "silver_warehouses"

    warehouse_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    capacity: Mapped[int | None] = mapped_column(Integer)


class SilverOrder(SilverIngestionMixin, Base):
    __tablename__ = "silver_orders"

    order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(100), nullable=False)
    product_id: Mapped[str] = mapped_column(String(100), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(String(100), nullable=False)
    order_date: Mapped[date | None] = mapped_column(Date)
    quantity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(50), nullable=False)


class SilverShipment(SilverIngestionMixin, Base):
    __tablename__ = "silver_shipments"

    shipment_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    warehouse_id: Mapped[str] = mapped_column(String(100), nullable=False)
    transport_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    origin: Mapped[str | None] = mapped_column(String(100))
    destination: Mapped[str | None] = mapped_column(String(100))
    ship_date: Mapped[date | None] = mapped_column(Date)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    actual_delivery_date: Mapped[date | None] = mapped_column(Date)
    distance_km: Mapped[float | None] = mapped_column(Float)


class SilverIncident(SilverIngestionMixin, Base):
    __tablename__ = "silver_incidents"

    incident_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    shipment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    incident_date: Mapped[date | None] = mapped_column(Date)
    severity: Mapped[str | None] = mapped_column(String(50))


SILVER_MODELS: dict[str, type] = {
    "suppliers": SilverSupplier,
    "products": SilverProduct,
    "warehouses": SilverWarehouse,
    "orders": SilverOrder,
    "shipments": SilverShipment,
    "incidents": SilverIncident,
}

# Champ d'identifiant métier (clé naturelle) par entité — réutilisé pour
# l'upsert (match sur cette colonne plutôt que sur la PK technique).
SILVER_NATURAL_KEY: dict[str, str] = {
    "suppliers": "supplier_id",
    "products": "product_id",
    "warehouses": "warehouse_id",
    "orders": "order_id",
    "shipments": "shipment_id",
    "incidents": "incident_id",
}
