from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration de l'application, lue depuis les variables d'environnement.

    Ne jamais mettre de secret en dur ici : tout passe par .env / les
    secrets CI-CD en production.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    api_secret_key: str = "change-me"
    database_url: str = "postgresql+psycopg://gsci:gsci@localhost:5432/gsci"

    project_name: str = "Global Supply Chain Intelligence"
    api_version: str = "0.1.0"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_shipment_status_topic: str = "shipment_status_updated"


@lru_cache
def get_settings() -> Settings:
    """Settings mis en cache : évite de re-parser l'environnement à chaque appel."""
    return Settings()
