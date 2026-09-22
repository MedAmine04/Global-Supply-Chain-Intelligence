from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import analytics, health

settings = get_settings()

app = FastAPI(
    title=settings.project_name,
    version=settings.api_version,
)

# CORS ouvert en développement uniquement ; à restreindre avant la Phase 8 (Production).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(analytics.router)


@app.get("/")
def root() -> dict:
    return {"project": settings.project_name, "version": settings.api_version}
