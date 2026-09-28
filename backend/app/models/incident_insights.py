"""Informations extraites des descriptions d'incidents (Phase 4 — NLP)."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IncidentInsight(Base):
    __tablename__ = "incident_insights"

    incident_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    predicted_type: Mapped[str] = mapped_column(String(100), nullable=False)
    type_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(200))
    shipment_ref: Mapped[str | None] = mapped_column(String(100))
    enriched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
