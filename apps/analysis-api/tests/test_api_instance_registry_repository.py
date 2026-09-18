"""Test del repository heartbeat delle repliche API.

Questi casi verificano il meccanismo interno che permette alla pagina Stato
del sistema di distinguere le due repliche API e capire se una di esse ha
smesso di aggiornare il proprio segnale applicativo.
"""

import sqlalchemy as sa

from app.db.models import ApiInstanceHeartbeatStatus
from app.repositories.api_instance_registry_repository import ApiInstanceRegistryRepository


def test_register_instance_creates_active_record(db_session) -> None:
    repository = ApiInstanceRegistryRepository(db_session)

    record = repository.register_instance("analysis-api-1", "host-a")

    assert record.instance_id == "analysis-api-1"
    assert record.hostname == "host-a"
    assert record.status == ApiInstanceHeartbeatStatus.ACTIVE
    assert record.started_at.tzinfo is not None
    assert record.last_heartbeat_at.tzinfo is not None


def test_touch_instance_updates_existing_heartbeat(db_session) -> None:
    repository = ApiInstanceRegistryRepository(db_session)
    original = repository.register_instance("analysis-api-1", "host-a")

    touched = repository.touch_instance("analysis-api-1", "host-b")

    assert touched.instance_id == "analysis-api-1"
    assert touched.hostname == "host-b"
    assert touched.status == ApiInstanceHeartbeatStatus.ACTIVE
    assert touched.started_at == original.started_at
    assert touched.last_heartbeat_at >= original.last_heartbeat_at


def test_mark_stopped_updates_instance_status(db_session) -> None:
    repository = ApiInstanceRegistryRepository(db_session)
    repository.register_instance("analysis-api-1", "host-a")

    stopped = repository.mark_stopped("analysis-api-1")

    assert stopped is not None
    assert stopped.status == ApiInstanceHeartbeatStatus.STOPPED
    assert stopped.last_heartbeat_at.tzinfo is not None


def test_two_instances_are_persisted_as_distinct_records(db_session) -> None:
    repository = ApiInstanceRegistryRepository(db_session)

    repository.register_instance("analysis-api-1", "host-a")
    repository.register_instance("analysis-api-2", "host-b")

    records = db_session.execute(
        sa.text("SELECT instance_id, hostname, status FROM api_instance_heartbeats ORDER BY instance_id")
    ).all()

    assert records == [
        ("analysis-api-1", "host-a", "active"),
        ("analysis-api-2", "host-b", "active"),
    ]
