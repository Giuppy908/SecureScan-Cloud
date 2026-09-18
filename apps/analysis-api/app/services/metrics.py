"""Metriche Prometheus della Analysis API.

Questo file non serve una pagina del frontend tradizionale, ma fornisce i dati
che Prometheus e Grafana usano per osservabilità, benchmark HA e diagnosi.
Le metriche restano separate dai payload business per non appesantire le API.
"""

from __future__ import annotations

from time import perf_counter

from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from app.core.config import settings

REQUEST_COUNTER = Counter(
    "securescan_api_http_requests_total",
    "HTTP requests handled by the analysis API.",
    ["instance_id", "method", "route", "status_code"],
)
REQUEST_DURATION = Histogram(
    "securescan_api_http_request_duration_seconds",
    "HTTP request duration observed by the analysis API.",
    ["instance_id", "method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
ANALYSES_CREATED = Counter(
    "securescan_api_analyses_created_total",
    "Queued analyses accepted by the analysis API.",
    ["instance_id"],
)
UPLOAD_REJECTIONS = Counter(
    "securescan_api_upload_rejections_total",
    "Rejected upload attempts observed by the analysis API.",
    ["instance_id", "status_code"],
)
INSTANCE_INFO = Gauge(
    "securescan_api_instance_info",
    "Static information about the running API instance.",
    ["instance_id", "version"],
)

def _ensure_static_series() -> None:
    """Inizializza le serie statiche attese anche prima del primo evento reale."""
    INSTANCE_INFO.labels(instance_id=settings.instance_id, version=settings.app_version).set(1)
    ANALYSES_CREATED.labels(instance_id=settings.instance_id)
    for upload_rejection_status_code in ("400", "401", "403", "413", "422", "429"):
        UPLOAD_REJECTIONS.labels(
            instance_id=settings.instance_id,
            status_code=upload_rejection_status_code,
        )


def request_started_at() -> float:
    """Return a monotonic timestamp for request tracking."""
    return perf_counter()


def record_request(*, method: str, route: str, status_code: int, started_at: float) -> None:
    """Registra conteggi e latenza della richiesta appena servita.

    Il middleware chiama questa funzione una sola volta per richiesta, così
    anche gli errori non gestiti contribuiscono alle metriche aggregate.
    """
    _ensure_static_series()
    if route == "/metrics":
        return

    duration_seconds = perf_counter() - started_at
    status_code_label = str(status_code)
    REQUEST_COUNTER.labels(
        instance_id=settings.instance_id,
        method=method,
        route=route,
        status_code=status_code_label,
    ).inc()
    REQUEST_DURATION.labels(
        instance_id=settings.instance_id,
        method=method,
        route=route,
    ).observe(duration_seconds)

    if method == "POST" and route == f"{settings.api_prefix}/analyses":
        if status_code == 202:
            ANALYSES_CREATED.labels(instance_id=settings.instance_id).inc()
        elif status_code in {400, 401, 403, 413, 422, 429}:
            UPLOAD_REJECTIONS.labels(
                instance_id=settings.instance_id,
                status_code=status_code_label,
            ).inc()


def render_metrics() -> Response:
    """Renderizza il payload Prometheus usato dagli scraper interni."""
    _ensure_static_series()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
