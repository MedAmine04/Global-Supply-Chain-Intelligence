"""Métriques Prometheus (Phase 8 — Observabilité).

Compteurs/histogrammes exposés sur /metrics, scrapés par Prometheus
(service docker-compose, cf. infra ci-dessous). Pas de dépendance
externe au runtime : prometheus-client expose simplement un registre en
mémoire, aucun appel réseau sortant n'est nécessaire pour que ça
fonctionne — vérifiable sans aucune infrastructure Prometheus réelle.
"""

import time
from collections.abc import Callable

from fastapi import Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "gsci_http_requests_total", "Nombre de requêtes HTTP", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "gsci_http_request_duration_seconds", "Durée des requêtes HTTP", ["method", "path"]
)
PIPELINE_RUNS = Counter(
    "gsci_pipeline_runs_total", "Runs de pipeline Data Engineering", ["stage", "status"]
)


async def metrics_middleware(request: Request, call_next: Callable) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    # Chemin brut (pas les paramètres de requête/IDs) pour éviter une
    # cardinalité illimitée de labels Prometheus (ex. /api/predictions/
    # at-risk?limit=5 doit compter comme un seul chemin, pas un par
    # valeur de `limit`).
    path = request.url.path
    REQUEST_COUNT.labels(method=request.method, path=path, status=response.status_code).inc()
    REQUEST_LATENCY.labels(method=request.method, path=path).observe(duration)
    return response


def metrics_endpoint() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
