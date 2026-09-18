"""Test del repository heartbeat del worker.

Proteggono il meccanismo che permette alla pagina Stato del sistema di capire
quanti worker sono attivi e se una replica si è fermata correttamente.
"""

from __future__ import annotations

from app.db.models import WorkerHeartbeatModel, WorkerHeartbeatStatus
from app.repositories.worker_registry_repository import WorkerRegistryRepository


def test_register_worker_creates_active_record(db_session) -> None:
    repository = WorkerRegistryRepository(db_session)

    record = repository.register_worker("worker-a", "host-a")

    assert record.worker_id == "worker-a"
    assert record.hostname == "host-a"
    assert record.status == WorkerHeartbeatStatus.ACTIVE

    stored = db_session.get(WorkerHeartbeatModel, "worker-a")
    assert stored is not None
    assert stored.status == WorkerHeartbeatStatus.ACTIVE


def test_touch_worker_updates_existing_heartbeat(db_session) -> None:
    repository = WorkerRegistryRepository(db_session)
    first_record = repository.register_worker("worker-a", "host-a")

    touched_record = repository.touch_worker("worker-a", "host-b")

    assert touched_record.worker_id == "worker-a"
    assert touched_record.hostname == "host-b"
    assert touched_record.started_at == first_record.started_at
    assert touched_record.last_heartbeat_at >= first_record.last_heartbeat_at


def test_mark_stopped_updates_worker_status(db_session) -> None:
    repository = WorkerRegistryRepository(db_session)
    repository.register_worker("worker-a", "host-a")

    stopped_record = repository.mark_stopped("worker-a")

    assert stopped_record is not None
    assert stopped_record.status == WorkerHeartbeatStatus.STOPPED


def test_two_workers_are_persisted_as_distinct_records(db_session) -> None:
    repository = WorkerRegistryRepository(db_session)

    repository.register_worker("worker-a", "host-a")
    repository.register_worker("worker-b", "host-b")

    workers = db_session.query(WorkerHeartbeatModel).order_by(WorkerHeartbeatModel.worker_id.asc()).all()
    assert [worker.worker_id for worker in workers] == ["worker-a", "worker-b"]
