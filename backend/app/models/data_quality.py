"""Table de traçabilité des runs de Data Quality (FR-02).

Un run de contrôle qualité produit un rapport persistant plutôt qu'un
simple print console : c'est ce qui permet à un Data Engineer de
consulter l'historique des runs, de comparer les taux de rejet dans le
temps, et plus tard d'exposer ça dans le dashboard (persona Data
Engineer : "surveiller les pipelines, contrôler la qualité des données").
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    batch_id: Mapped[str] = mapped_column(String(100), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_valid: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False)

    # Détail structuré des motifs de rejet : {"missing_required_fields": {...},
    # "duplicate_ids": n, "invalid_numeric_fields": {...}, "invalid_dates": {...},
    # "invalid_foreign_keys": {...}}
    issues: Mapped[dict] = mapped_column(JSON, nullable=False)

    # IDs (colonne "id" Bronze, pas l'identifiant métier) des lignes rejetées
    # par ce run — nécessaire à FR-03 (Silver) pour savoir précisément quelles
    # lignes du batch reprendre. Cf. ADR-004.
    rejected_row_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
