"""Modèles de la couche Bronze.

Principe Bronze : les données sont stockées telles qu'elles arrivent,
sans validation ni transformation de type. C'est pourquoi toutes les
colonnes métier sont des `String` nullable, même pour des champs qui
seront numériques ou des dates en Silver — la validation/typage stricte
est le rôle de la transformation Bronze -> Silver (FR-03), pas de
l'ingestion elle-même.

Chaque table Bronze est *insert-only* : on n'update et ne supprime
jamais une ligne Bronze. Les doublons éventuels (ré-ingestion d'un même
fichier) sont normaux et gérés en Silver.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BronzeIngestionMixin:
    """Colonnes de traçabilité communes à toutes les tables Bronze."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BronzeSupplier(BronzeIngestionMixin, Base):
    __tablename__ = "bronze_suppliers"

    supplier_id: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100))
    reliability_score: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[str | None] = mapped_column(String(50))


class BronzeProduct(BronzeIngestionMixin, Base):
    __tablename__ = "bronze_products"

    product_id: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(100))
    unit_cost: Mapped[str | None] = mapped_column(String(50))


class BronzeWarehouse(BronzeIngestionMixin, Base):
    __tablename__ = "bronze_warehouses"

    warehouse_id: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    country: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    capacity: Mapped[str | None] = mapped_column(String(50))


class BronzeOrder(BronzeIngestionMixin, Base):
    __tablename__ = "bronze_orders"

    order_id: Mapped[str | None] = mapped_column(String(100))
    supplier_id: Mapped[str | None] = mapped_column(String(100))
    product_id: Mapped[str | None] = mapped_column(String(100))
    warehouse_id: Mapped[str | None] = mapped_column(String(100))
    order_date: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(String(50))


class BronzeShipment(BronzeIngestionMixin, Base):
    __tablename__ = "bronze_shipments"

    shipment_id: Mapped[str | None] = mapped_column(String(100))
    order_id: Mapped[str | None] = mapped_column(String(100))
    warehouse_id: Mapped[str | None] = mapped_column(String(100))
    transport_mode: Mapped[str | None] = mapped_column(String(50))
    origin: Mapped[str | None] = mapped_column(String(100))
    destination: Mapped[str | None] = mapped_column(String(100))
    ship_date: Mapped[str | None] = mapped_column(String(50))
    expected_delivery_date: Mapped[str | None] = mapped_column(String(50))
    actual_delivery_date: Mapped[str | None] = mapped_column(String(50))
    distance_km: Mapped[str | None] = mapped_column(String(50))


class BronzeIncident(BronzeIngestionMixin, Base):
    __tablename__ = "bronze_incidents"

    incident_id: Mapped[str | None] = mapped_column(String(100))
    shipment_id: Mapped[str | None] = mapped_column(String(100))
    incident_type: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(2000))
    incident_date: Mapped[str | None] = mapped_column(String(50))
    severity: Mapped[str | None] = mapped_column(String(50))


# Registre entité -> modèle, utilisé par le service d'ingestion générique.
BRONZE_MODELS: dict[str, type] = {
    "suppliers": BronzeSupplier,
    "products": BronzeProduct,
    "warehouses": BronzeWarehouse,
    "orders": BronzeOrder,
    "shipments": BronzeShipment,
    "incidents": BronzeIncident,
}
