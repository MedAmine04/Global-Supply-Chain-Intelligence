from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles ORM."""


def get_db() -> Generator[Session, None, None]:
    """Dépendance FastAPI fournissant une session DB, fermée après la requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
