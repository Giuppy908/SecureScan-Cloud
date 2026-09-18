"""Test del loop principale del worker e dei suoi endpoint tecnici.

Questa suite protegge il comportamento end-to-end del processo background:
presa in carico del job, esecuzione pipeline, cleanup del file temporaneo,
health endpoint e metriche esportate a Prometheus.
"""

from pathlib import Path
from datetime import datetime, timezone

from app.core.config import settings
from app.db.models import AnalysisRecordModel, AnalysisStatus, RiskLevel, utc_now
from app.repositories.analysis_repository import AnalysisJob
from app.repositories.analysis_repository import RepositoryError
from app.repositories.analysis_repository import AnalysisWorkerRepository
from app.repositories.worker_registry_repository import WorkerRegistryError
from app.services.malware_pipeline import PipelineScanResult
from app.services.metrics import render_metrics
from app.services.worker import AnalysisWorkerLoop, WorkerRuntimeState, health_payload


def _parse_metric_value(payload: str, metric_name: str, labels: dict[str, str]) -> float:
    """Legge il valore di una serie Prometheus specifica nel payload testato."""
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


def _metric_line_exists(payload: str, metric_name: str, labels: dict[str, str]) -> bool:
    """Controlla la presenza di una serie Prometheus etichettata."""
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


def seed_job(db_session, storage_path: str) -> None:
    """Crea un job `queued` minimale come farebbe l'Analysis API."""
    record = AnalysisRecordModel(
        id="ANL-2026-0001",
        file_name="sample.txt",
        status=AnalysisStatus.QUEUED,
        risk_level=RiskLevel.LOW,
        created_at=utc_now(),
        updated_at=utc_now(),
        processing_started_at=None,
        completed_at=None,
        worker_id=None,
        attempt_count=0,
        storage_path=storage_path,
        size_bytes=5,
        mime_type=None,
        sha256=None,
        entropy=None,
        extension_matches_mime=None,
        indicators=[],
        error_message=None,
    )
    db_session.add(record)
    db_session.commit()


def test_worker_processes_job_and_deletes_file(db_session, tmp_path: Path) -> None:
    target = tmp_path / "sample.bin"
    target.write_bytes(b"hello")
    seed_job(db_session, str(target))

    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)
    repository = AnalysisWorkerRepository(db_session)
    job = repository.acquire_next_queued_analysis("worker-test")
    assert job is not None

    baseline_metrics = render_metrics(runtime_state.snapshot()).body.decode()
    baseline_completed = _parse_metric_value(
        baseline_metrics,
        "securescan_worker_jobs_completed_total",
        {"worker_id": settings.worker_id},
    )

    worker._process_job(job, 0.0)

    db_session.expire_all()
    record = db_session.get(AnalysisRecordModel, 1)
    assert record is not None
    assert record.status == AnalysisStatus.COMPLETED
    assert record.worker_id == "worker-test"
    assert not target.exists()
    updated_metrics = render_metrics(runtime_state.snapshot()).body.decode()
    updated_completed = _parse_metric_value(
        updated_metrics,
        "securescan_worker_jobs_completed_total",
        {"worker_id": settings.worker_id},
    )
    assert updated_completed == baseline_completed + 1


def test_worker_marks_failed_when_file_is_missing(db_session, tmp_path: Path) -> None:
    target = tmp_path / "missing.bin"
    seed_job(db_session, str(target))

    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)
    repository = AnalysisWorkerRepository(db_session)
    job = repository.acquire_next_queued_analysis("worker-test")
    assert job is not None

    baseline_metrics = render_metrics(runtime_state.snapshot()).body.decode()
    baseline_failed = _parse_metric_value(
        baseline_metrics,
        "securescan_worker_jobs_failed_total",
        {"worker_id": settings.worker_id, "reason": "processing_error"},
    )

    worker._process_job(job, 0.0)

    db_session.expire_all()
    record = db_session.get(AnalysisRecordModel, 1)
    assert record is not None
    assert record.status == AnalysisStatus.FAILED
    assert "No such file" in (record.error_message or "") or "missing" in (record.error_message or "").lower()
    updated_metrics = render_metrics(runtime_state.snapshot()).body.decode()
    updated_failed = _parse_metric_value(
        updated_metrics,
        "securescan_worker_jobs_failed_total",
        {"worker_id": settings.worker_id, "reason": "processing_error"},
    )
    assert updated_failed == baseline_failed + 1


def test_health_returns_200_after_successful_poll(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    runtime_state.set_running(True)
    runtime_state.mark_poll_success()

    monkeypatch.setattr("app.services.worker.is_database_reachable", lambda: True)

    status_code, payload = health_payload(runtime_state)

    assert status_code == 200
    assert payload == {
        "status": "healthy",
        "database": "reachable",
        "polling": "running",
    }


def test_health_returns_503_after_polling_error(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    runtime_state.set_running(True)
    runtime_state.set_error("db failure")

    monkeypatch.setattr("app.services.worker.is_database_reachable", lambda: True)

    status_code, payload = health_payload(runtime_state)

    assert status_code == 503
    assert payload == {
        "status": "unhealthy",
        "database": "reachable",
        "polling": "error",
    }


def test_worker_recovers_on_next_poll_with_new_session(monkeypatch) -> None:
    """Verifica che un errore temporaneo non blocchi definitivamente il polling."""
    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)

    class FakeSession:
        def __init__(self, identifier: int) -> None:
            self.identifier = identifier
            self.closed = False

        def close(self) -> None:
            self.closed = True

    created_sessions: list[FakeSession] = []
    call_log: list[tuple[str, int]] = []

    def fake_session_factory():
        session = FakeSession(len(created_sessions) + 1)
        created_sessions.append(session)
        return session

    class FakeRepository:
        def __init__(self, session) -> None:
            self._session = session

        def recover_stale_processing_jobs(self, **kwargs):
            call_log.append(("recover", self._session.identifier))
            if self._session.identifier == 1:
                raise RepositoryError("temporary database error")
            return (0, 0)

        def acquire_next_queued_analysis(self, worker_id: str):
            call_log.append(("acquire", self._session.identifier))
            return None

    class FakeSessionManager:
        def session_factory(self):
            return fake_session_factory()

    monkeypatch.setattr("app.services.worker.AnalysisWorkerRepository", FakeRepository)
    monkeypatch.setattr("app.services.worker.session_manager", FakeSessionManager())
    monkeypatch.setattr("app.services.worker.is_database_reachable", lambda: True)

    runtime_state.set_running(True)
    first_result = worker._run_once()
    second_result = worker._run_once()
    runtime_state.mark_poll_success()

    assert first_result is False
    assert second_result is True
    assert created_sessions[0].closed is True
    assert created_sessions[1].closed is True
    assert call_log == [("recover", 1), ("recover", 2), ("acquire", 2)]
    assert health_payload(runtime_state)[0] == 200


def test_wait_for_minimum_processing_duration_skips_sleep_when_disabled(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)
    sleep_calls: list[float] = []
    previous_value = settings.min_processing_seconds
    settings.min_processing_seconds = 0

    monkeypatch.setattr("app.services.worker.time.monotonic", lambda: 10.0)
    monkeypatch.setattr("app.services.worker.time.sleep", lambda seconds: sleep_calls.append(seconds))

    try:
        worker._wait_for_minimum_processing_duration(5.0, analysis_id="ANL-2026-0001")
    finally:
        settings.min_processing_seconds = previous_value

    assert sleep_calls == []


def test_wait_for_minimum_processing_duration_sleeps_for_remaining_time(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)
    sleep_calls: list[float] = []
    previous_value = settings.min_processing_seconds
    settings.min_processing_seconds = 2.0

    monkeypatch.setattr("app.services.worker.time.monotonic", lambda: 100.5)
    monkeypatch.setattr("app.services.worker.time.sleep", lambda seconds: sleep_calls.append(seconds))

    try:
        worker._wait_for_minimum_processing_duration(100.0, analysis_id="ANL-2026-0001")
    finally:
        settings.min_processing_seconds = previous_value

    assert sleep_calls == [1.5]


def test_wait_for_minimum_processing_duration_skips_sleep_when_job_already_exceeded_minimum(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)
    sleep_calls: list[float] = []
    previous_value = settings.min_processing_seconds
    settings.min_processing_seconds = 2.0

    monkeypatch.setattr("app.services.worker.time.monotonic", lambda: 103.0)
    monkeypatch.setattr("app.services.worker.time.sleep", lambda seconds: sleep_calls.append(seconds))

    try:
        worker._wait_for_minimum_processing_duration(100.0, analysis_id="ANL-2026-0001")
    finally:
        settings.min_processing_seconds = previous_value

    assert sleep_calls == []


def test_processing_delay_is_applied_before_mark_completed(monkeypatch, tmp_path: Path) -> None:
    runtime_state = WorkerRuntimeState()
    previous_value = settings.min_processing_seconds
    settings.min_processing_seconds = 2.0
    events: list[str] = []

    class FakeAnalyzer:
        def analyze_file(self, *, file_name: str, content: bytes):
            from app.repositories.analysis_repository import CompletedAnalysis

            return PipelineScanResult(
                analysis=CompletedAnalysis(
                    risk_level=RiskLevel.LOW,
                    mime_type="text/plain",
                    sha256="a" * 64,
                    entropy=1.23,
                    extension_matches_mime=True,
                    verdict="clean",
                    scanned_at=datetime.now(timezone.utc),
                    clamav_status="clean",
                    clamav_signature_name=None,
                    clamav_error=None,
                    yara_status="clean",
                    yara_matches=[],
                    yara_error=None,
                    indicators=[],
                ),
                clamav_duration_seconds=0.1,
                yara_duration_seconds=0.1,
                yara_severities=[],
            )

    worker = AnalysisWorkerLoop(runtime_state, analyzer=FakeAnalyzer())

    target = tmp_path / "sample.bin"
    target.write_bytes(b"hello")

    class FakeRepository:
        def __init__(self, _session) -> None:
            pass

        def mark_completed(self, analysis_id, result) -> None:
            events.append(f"completed:{analysis_id}")

    class FakeSession:
        def __init__(self) -> None:
            self.is_active = True

        def close(self) -> None:
            self.is_active = False

    class FakeSessionManager:
        @property
        def session_factory(self):
            return lambda: FakeSession()

    monkeypatch.setattr("app.services.worker.AnalysisWorkerRepository", FakeRepository)
    monkeypatch.setattr("app.services.worker.session_manager", FakeSessionManager())
    monkeypatch.setattr("app.services.worker.time.monotonic", lambda: 10.5)
    monkeypatch.setattr("app.services.worker.time.sleep", lambda seconds: events.append(f"sleep:{seconds:.1f}"))

    job = AnalysisJob(
        id="ANL-2026-0001",
        file_name="sample.txt",
        size_bytes=5,
        storage_path=str(target),
        attempt_count=1,
        created_at=utc_now(),
        processing_started_at=utc_now(),
        worker_id="worker-test",
    )

    try:
        worker._process_job(job, 10.0)
    finally:
        settings.min_processing_seconds = previous_value

    assert events == ["sleep:1.5", "completed:ANL-2026-0001"]
    assert not target.exists()


def test_processing_delay_is_applied_before_mark_failed(monkeypatch, tmp_path: Path) -> None:
    runtime_state = WorkerRuntimeState()
    previous_value = settings.min_processing_seconds
    settings.min_processing_seconds = 2.0
    events: list[str] = []

    class FailingAnalyzer:
        def analyze_file(self, *, file_name: str, content: bytes):
            raise ValueError("boom")

    worker = AnalysisWorkerLoop(runtime_state, analyzer=FailingAnalyzer())

    class FakeRepository:
        def __init__(self, _session) -> None:
            pass

        def mark_failed(self, analysis_id, error_message) -> None:
            events.append(f"failed:{analysis_id}")

    class FakeSession:
        def __init__(self) -> None:
            self.is_active = True

        def close(self) -> None:
            self.is_active = False

    target = tmp_path / "sample.bin"
    target.write_bytes(b"hello")
    session_instances = [FakeSession(), FakeSession()]

    class FakeSessionManager:
        @property
        def session_factory(self):
            return lambda: session_instances.pop(0)

    monkeypatch.setattr("app.services.worker.AnalysisWorkerRepository", FakeRepository)
    monkeypatch.setattr("app.services.worker.session_manager", FakeSessionManager())
    monkeypatch.setattr("app.services.worker.time.monotonic", lambda: 20.5)
    monkeypatch.setattr("app.services.worker.time.sleep", lambda seconds: events.append(f"sleep:{seconds:.1f}"))

    job = AnalysisJob(
        id="ANL-2026-0001",
        file_name="sample.txt",
        size_bytes=5,
        storage_path=str(target),
        attempt_count=1,
        created_at=utc_now(),
        processing_started_at=utc_now(),
        worker_id="worker-test",
    )

    try:
        worker._process_job(job, 20.0)
    finally:
        settings.min_processing_seconds = previous_value

    assert events == ["sleep:1.5", "failed:ANL-2026-0001"]
    assert not target.exists()


def test_run_once_without_job_does_not_sleep(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)
    sleep_calls: list[float] = []

    class FakeRepository:
        def __init__(self, _session) -> None:
            pass

        def recover_stale_processing_jobs(self, **kwargs):
            return (0, 0)

        def acquire_next_queued_analysis(self, worker_id: str):
            return None

    class FakeSession:
        def close(self) -> None:
            pass

    class FakeSessionManager:
        @property
        def session_factory(self):
            return lambda: FakeSession()

    monkeypatch.setattr("app.services.worker.AnalysisWorkerRepository", FakeRepository)
    monkeypatch.setattr("app.services.worker.session_manager", FakeSessionManager())
    monkeypatch.setattr("app.services.worker.time.sleep", lambda seconds: sleep_calls.append(seconds))

    result = worker._run_once()

    assert result is True
    assert sleep_calls == []


def test_heartbeat_error_does_not_interrupt_job_polling(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)

    class FakeRegistryRepository:
        def __init__(self, _session) -> None:
            pass

        def touch_worker(self, worker_id: str, hostname: str) -> None:
            raise WorkerRegistryError("heartbeat failed")

    class FakeAnalysisRepository:
        def __init__(self, _session) -> None:
            pass

        def recover_stale_processing_jobs(self, **kwargs):
            return (0, 0)

        def acquire_next_queued_analysis(self, worker_id: str):
            return None

    class FakeSession:
        def close(self) -> None:
            pass

    class FakeSessionManager:
        @property
        def session_factory(self):
            return lambda: FakeSession()

    monkeypatch.setattr("app.services.worker.WorkerRegistryRepository", FakeRegistryRepository)
    monkeypatch.setattr("app.services.worker.AnalysisWorkerRepository", FakeAnalysisRepository)
    monkeypatch.setattr("app.services.worker.session_manager", FakeSessionManager())

    worker._send_heartbeat()
    result = worker._run_once()

    assert result is True


def test_worker_metrics_expose_last_successful_poll_and_running_state(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    runtime_state.set_running(True)
    runtime_state.mark_poll_success()

    payload = render_metrics(runtime_state.snapshot()).body.decode()

    running_value = _parse_metric_value(
        payload,
        "securescan_worker_running",
        {"worker_id": settings.worker_id},
    )
    healthy_value = _parse_metric_value(
        payload,
        "securescan_worker_polling_healthy",
        {"worker_id": settings.worker_id},
    )
    timestamp_value = _parse_metric_value(
        payload,
        "securescan_worker_last_successful_poll_timestamp_seconds",
        {"worker_id": settings.worker_id},
    )

    assert running_value == 1
    assert healthy_value == 1
    assert timestamp_value > 0


def test_worker_metrics_count_polling_errors(monkeypatch) -> None:
    runtime_state = WorkerRuntimeState()
    worker = AnalysisWorkerLoop(runtime_state)

    class FakeRepository:
        def __init__(self, _session) -> None:
            pass

        def recover_stale_processing_jobs(self, **kwargs):
            raise RepositoryError("database unavailable")

    class FakeSession:
        def close(self) -> None:
            pass

    class FakeSessionManager:
        @property
        def session_factory(self):
            return lambda: FakeSession()

    monkeypatch.setattr("app.services.worker.AnalysisWorkerRepository", FakeRepository)
    monkeypatch.setattr("app.services.worker.session_manager", FakeSessionManager())

    baseline_metrics = render_metrics(runtime_state.snapshot()).body.decode()
    baseline_errors = _parse_metric_value(
        baseline_metrics,
        "securescan_worker_polling_errors_total",
        {"worker_id": settings.worker_id},
    )

    result = worker._run_once()

    assert result is False
    updated_metrics = render_metrics(runtime_state.snapshot()).body.decode()
    updated_errors = _parse_metric_value(
        updated_metrics,
        "securescan_worker_polling_errors_total",
        {"worker_id": settings.worker_id},
    )
    assert updated_errors == baseline_errors + 1


def test_worker_metrics_expose_zero_initialized_job_series() -> None:
    runtime_state = WorkerRuntimeState()

    payload = render_metrics(runtime_state.snapshot()).body.decode()

    assert _metric_line_exists(
        payload,
        "securescan_worker_jobs_completed_total",
        {"worker_id": settings.worker_id},
    )
    assert _metric_line_exists(
        payload,
        "securescan_worker_jobs_failed_total",
        {"worker_id": settings.worker_id, "reason": "processing_error"},
    )
