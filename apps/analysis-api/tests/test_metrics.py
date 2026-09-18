"""Test delle metriche Prometheus esportate dalla Analysis API.

Questi casi proteggono l'osservabilità del backend, utile per Grafana,
Prometheus e benchmark HA, senza influire direttamente sulle pagine utente.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.core.config import settings


def _parse_metric_value(payload: str, metric_name: str, labels: Mapping[str, str]) -> float:
    """Estrae il valore numerico di una serie Prometheus specifica."""
    for line in payload.splitlines():
        if not line.startswith(f"{metric_name}{{"):
            continue
        label_segment, _, value_segment = line.partition("} ")
        raw_labels = label_segment.removeprefix(f"{metric_name}{{")
        parsed_labels: dict[str, str] = {}
        for item in raw_labels.split(","):
            key, _, raw_value = item.partition("=")
            parsed_labels[key] = raw_value.strip('"')
        if all(parsed_labels.get(key) == value for key, value in labels.items()):
            return float(value_segment)
    return 0.0


def _metric_line_exists(payload: str, metric_name: str, labels: Mapping[str, str]) -> bool:
    """Controlla se una serie Prometheus etichettata è presente nel payload."""
    for line in payload.splitlines():
        if not line.startswith(f"{metric_name}{{"):
            continue
        label_segment, _, _value_segment = line.partition("} ")
        raw_labels = label_segment.removeprefix(f"{metric_name}{{")
        parsed_labels: dict[str, str] = {}
        for item in raw_labels.split(","):
            key, _, raw_value = item.partition("=")
            parsed_labels[key] = raw_value.strip('"')
        if all(parsed_labels.get(key) == value for key, value in labels.items()):
            return True
    return False


def test_metrics_endpoint_exposes_health_request_counter(client) -> None:
    baseline = client.get("/metrics").text
    labels = {
        "instance_id": "test-analysis-api",
        "method": "GET",
        "route": "/health",
        "status_code": "200",
    }
    baseline_value = _parse_metric_value(
        baseline,
        "securescan_api_http_requests_total",
        labels,
    )

    response = client.get("/health")

    assert response.status_code == 200
    updated_payload = client.get("/metrics").text
    updated_value = _parse_metric_value(
        updated_payload,
        "securescan_api_http_requests_total",
        labels,
    )
    assert updated_value == baseline_value + 1


def test_metrics_normalize_dynamic_analysis_route(client) -> None:
    baseline = client.get("/metrics").text
    labels = {
        "instance_id": "test-analysis-api",
        "method": "GET",
        "route": "/api/v1/analyses/{analysis_id}",
        "status_code": "404",
    }
    baseline_value = _parse_metric_value(
        baseline,
        "securescan_api_http_requests_total",
        labels,
    )

    response = client.get("/api/v1/analyses/ANL-2026-4040")

    assert response.status_code == 404
    updated_payload = client.get("/metrics").text
    updated_value = _parse_metric_value(
        updated_payload,
        "securescan_api_http_requests_total",
        labels,
    )
    assert updated_value == baseline_value + 1
    assert "/api/v1/analyses/ANL-2026-4040" not in updated_payload


def test_metrics_count_accepted_analysis_creation(client) -> None:
    baseline = client.get("/metrics").text
    labels = {"instance_id": "test-analysis-api"}
    baseline_value = _parse_metric_value(
        baseline,
        "securescan_api_analyses_created_total",
        labels,
    )

    response = client.post(
        "/api/v1/analyses",
        files={"file": ("sample.txt", b"hello world", "text/plain")},
    )

    assert response.status_code == 202
    updated_payload = client.get("/metrics").text
    updated_value = _parse_metric_value(
        updated_payload,
        "securescan_api_analyses_created_total",
        labels,
    )
    assert updated_value == baseline_value + 1


def test_metrics_count_rejected_uploads(client) -> None:
    previous_limit = settings.max_upload_size_mb
    settings.max_upload_size_mb = 1
    try:
        baseline = client.get("/metrics").text
        labels = {"instance_id": "test-analysis-api", "status_code": "413"}
        baseline_value = _parse_metric_value(
            baseline,
            "securescan_api_upload_rejections_total",
            labels,
        )

        response = client.post(
            "/api/v1/analyses",
            files={"file": ("large.bin", b"a" * (settings.max_upload_size_bytes + 1), "application/octet-stream")},
        )

        assert response.status_code == 413
        updated_payload = client.get("/metrics").text
        updated_value = _parse_metric_value(
            updated_payload,
            "securescan_api_upload_rejections_total",
            labels,
        )
        assert updated_value == baseline_value + 1
    finally:
        settings.max_upload_size_mb = previous_limit


def test_metrics_expose_zero_initialized_upload_rejection_series(client) -> None:
    metrics_payload = client.get("/metrics").text

    assert _metric_line_exists(
        metrics_payload,
        "securescan_api_upload_rejections_total",
        {"instance_id": "test-analysis-api", "status_code": "429"},
    )
