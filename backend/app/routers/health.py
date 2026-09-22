from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict:
    """Vérifie que l'API tourne et que la base de données répond.

    Utilisé par docker-compose (healthcheck) et par le frontend pour
    prouver la liaison bout-en-bout dès la Phase 0.
    """
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
