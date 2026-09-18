"""Test del servizio e dell'endpoint Stato del sistema.

Questa suite protegge la pagina che riassume la salute della piattaforma:
repliche API, worker, database e dipendenze infrastrutturali devono produrre
uno stato coerente e leggibile dall'interfaccia amministrativa.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.models import (
    ApiInstanceHeartbeatModel,
    ApiInstanceHeartbeatStatus,
    WorkerHeartbeatModel,
    WorkerHeartbeatStatus,
)
from app.db.session import session_manager
from app.models.system_status import SystemServiceSnapshot, SystemStatusLevel
from app.services.system_status import SystemStatusService


def _parse_iso_datetime(value: str) -> datetime:
    """Normalizza i timestamp ISO ricevuti dall'endpoint in `datetime` UTC."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _patch_clamav(monkeypatch, status: SystemStatusLevel = SystemStatusLevel.HEALTHY) -> None:
    """Simula la reachability di ClamAV senza usare il daemon reale nei test."""
    monkeypatch.setattr(
        SystemStatusService,
        "_build_clamav_status",
        lambda _self, checked_at: SystemServiceSnapshot(
            name="clamav",
            status=status,
            message="Motore antimalware raggiungibile." if status == SystemStatusLevel.HEALTHY else "Motore antimalware temporaneamente non raggiungibile.",
            last_checked_at=checked_at,
            details={"version": "ClamAV test"} if status == SystemStatusLevel.HEALTHY else {},
        ),
    )


def _insert_worker_heartbeat(
    *,
    worker_id: str,
    seconds_ago: int = 0,
    status: WorkerHeartbeatStatus = WorkerHeartbeatStatus.ACTIVE,
    hostname: str = "worker-host",
) -> None:
    """Inserisce heartbeat worker di test con età temporale controllata."""
    now = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    session = session_manager.session_factory()
    try:
        session.add(
            WorkerHeartbeatModel(
                worker_id=worker_id,
                hostname=hostname,
                status=status,
                started_at=now - timedelta(minutes=1),
                last_heartbeat_at=now,
            )
        )
        session.commit()
    finally:
        session.close()


def _insert_api_instance_heartbeat(
    *,
    instance_id: str,
    seconds_ago: int = 0,
    status: ApiInstanceHeartbeatStatus = ApiInstanceHeartbeatStatus.ACTIVE,
    hostname: str = "api-host",
) -> None:
    """Inserisce heartbeat API di test con età temporale controllata."""
    now = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    session = session_manager.session_factory()
    try:
        session.add(
            ApiInstanceHeartbeatModel(
                instance_id=instance_id,
                hostname=hostname,
                status=status,
                started_at=now - timedelta(minutes=1),
                last_heartbeat_at=now,
            )
        )
        session.commit()
    finally:
        session.close()


def test_system_status_is_healthy_with_active_worker(client, monkeypatch) -> None:
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)
    _insert_api_instance_heartbeat(instance_id="analysis-api-1")
    _insert_worker_heartbeat(worker_id="worker-a")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "healthy"
    assert _parse_iso_datetime(payload["checked_at"]).tzinfo is not None
    service_names = {service["name"] for service in payload["services"]}
    assert service_names == {
        "analysis-api",
        "postgres",
        "analysis-worker",
        "clamav",
        "kong",
        "prometheus",
        "grafana",
        "postgres-exporter",
    }
    worker_service = next(service for service in payload["services"] if service["name"] == "analysis-worker")
    api_service = next(service for service in payload["services"] if service["name"] == "analysis-api")
    assert api_service["status"] == "healthy"
    assert api_service["details"]["configured_instances"] == 1
    assert api_service["details"]["active_instances"] == 1
    assert api_service["details"]["active_instance_ids"] == ["analysis-api-1"]
    assert worker_service["status"] == "healthy"
    assert worker_service["details"]["active_workers"] == 1
    assert _parse_iso_datetime(worker_service["last_checked_at"]).tzinfo is not None


def test_system_status_is_healthy_with_two_api_replicas(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "configured_api_replicas", 2)
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)
    _insert_api_instance_heartbeat(instance_id="analysis-api-1")
    _insert_api_instance_heartbeat(instance_id="analysis-api-2")
    _insert_worker_heartbeat(worker_id="worker-a")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "healthy"
    api_service = next(service for service in payload["services"] if service["name"] == "analysis-api")
    assert api_service["status"] == "healthy"
    assert api_service["details"]["configured_instances"] == 2
    assert api_service["details"]["active_instances"] == 2
    assert api_service["details"]["active_instance_ids"] == ["analysis-api-1", "analysis-api-2"]


def test_system_status_is_degraded_without_active_workers(client, monkeypatch) -> None:
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)
    _insert_api_instance_heartbeat(instance_id="analysis-api-1")
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "degraded"
    worker_service = next(service for service in payload["services"] if service["name"] == "analysis-worker")
    assert worker_service["status"] == "degraded"
    assert worker_service["details"]["active_workers"] == 0


def test_system_status_excludes_stale_workers(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "worker_heartbeat_timeout_seconds", 10)
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)
    _insert_api_instance_heartbeat(instance_id="analysis-api-1")
    _insert_worker_heartbeat(worker_id="worker-stale", seconds_ago=60)

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    worker_service = next(service for service in payload["services"] if service["name"] == "analysis-worker")
    assert worker_service["status"] == "degraded"
    assert worker_service["details"]["active_workers"] == 0


def test_system_status_counts_multiple_active_workers(client, monkeypatch) -> None:
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)
    _insert_api_instance_heartbeat(instance_id="analysis-api-1")
    _insert_worker_heartbeat(worker_id="worker-a", hostname="host-a")
    _insert_worker_heartbeat(worker_id="worker-b", hostname="host-b")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    worker_service = next(service for service in payload["services"] if service["name"] == "analysis-worker")
    assert worker_service["status"] == "healthy"
    assert worker_service["details"]["active_workers"] == 2


def test_system_status_is_degraded_when_one_api_replica_is_missing(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "configured_api_replicas", 2)
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)
    _insert_api_instance_heartbeat(instance_id="analysis-api-1")
    _insert_worker_heartbeat(worker_id="worker-a")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "degraded"
    api_service = next(service for service in payload["services"] if service["name"] == "analysis-api")
    assert api_service["status"] == "degraded"
    assert api_service["details"]["configured_instances"] == 2
    assert api_service["details"]["active_instances"] == 1
    assert api_service["details"]["active_instance_ids"] == ["analysis-api-1"]


def test_system_status_is_unavailable_when_no_api_replica_is_active(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "configured_api_replicas", 2)
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)
    _insert_worker_heartbeat(worker_id="worker-a")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "unavailable"
    api_service = next(service for service in payload["services"] if service["name"] == "analysis-api")
    assert api_service["status"] == "unavailable"
    assert api_service["details"]["configured_instances"] == 2
    assert api_service["details"]["active_instances"] == 0


def test_system_status_service_reports_unavailable_when_database_is_unreachable(monkeypatch) -> None:
    class FakeSession:
        def execute(self, *_args, **_kwargs):
            raise SQLAlchemyError("database down")

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    class FakeSessionManager:
        def session_factory(self):
            return FakeSession()

    monkeypatch.setattr("app.services.system_status.session_manager", FakeSessionManager())
    monkeypatch.setattr(SystemStatusService, "_is_http_endpoint_reachable", staticmethod(lambda _url: True))
    _patch_clamav(monkeypatch)

    snapshot = SystemStatusService().collect_status()

    assert snapshot.overall_status.value == "unavailable"
    postgres_service = next(service for service in snapshot.services if service.name == "postgres")
    worker_service = next(service for service in snapshot.services if service.name == "analysis-worker")
    assert postgres_service.status.value == "unavailable"
    assert worker_service.status.value == "unavailable"


def test_system_status_is_degraded_when_monitoring_component_is_unreachable(client, monkeypatch) -> None:
    monkeypatch.setattr(
        SystemStatusService,
        "_is_http_endpoint_reachable",
        staticmethod(lambda url: url != settings.prometheus_health_url),
    )
    _patch_clamav(monkeypatch)
    _insert_api_instance_heartbeat(instance_id="analysis-api-1")
    _insert_worker_heartbeat(worker_id="worker-a")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] == "degraded"
    prometheus_service = next(service for service in payload["services"] if service["name"] == "prometheus")
    assert prometheus_service["status"] == "degraded"


def test_system_status_endpoint_hides_internal_error_details(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.system_status.SystemStatusService.collect_status",
        lambda _self: (_ for _ in ()).throw(RuntimeError("traceback should stay hidden")),
    )

    response = client.get("/api/v1/system/status")

    assert response.status_code == 500
    assert response.json() == {"detail": "Failed to retrieve system status."}
