"""Endpoint Prometheus della replica API.

Questo file non alimenta direttamente una pagina del frontend utente. Espone
le metriche che Prometheus raccoglie e che poi possono essere visualizzate in
Grafana o usate durante benchmark e troubleshooting dell'architettura HA.
"""

from fastapi import APIRouter
from fastapi.responses import Response

from app.services.metrics import render_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
def get_metrics() -> Response:
    """Espone le metriche Prometheus della replica corrente."""
    return render_metrics()
