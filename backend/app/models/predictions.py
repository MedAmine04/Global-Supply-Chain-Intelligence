"""Prédictions de risque de retard (FR-13).

Une ligne par expédition non encore livrée, réécrite (upsert) à chaque
run de scoring — reflète toujours le dernier modèle entraîné, pas un
historique de toutes les prédictions passées (qui n'aurait de valeur que
pour un futur travail de monitoring de dérive, hors périmètre ici).
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ShipmentDelayPrediction(Base):
    __tablename__ = "shipment_delay_predictions"

    shipment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_label: Mapped[int] = mapped_column(nullable=False)  # 0/1
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
