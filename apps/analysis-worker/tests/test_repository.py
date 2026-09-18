"""Test del repository SQLAlchemy usato dal worker.

Questi casi proteggono l'assegnazione dei job, il recovery dei record bloccati
e gli aggiornamenti che poi diventano visibili in Cronologia e Dettaglio analisi.
"""

from pathlib import Path
from datetime import datetime, timezone

from app.db.models import AnalysisRecordModel, AnalysisStatus, RiskLevel, utc_now
from app.repositories.analysis_repository import AnalysisWorkerRepository, CompletedAnalysis


def seed_job(db_session, *, analysis_id: str, file_name: str, storage_path: str, status=AnalysisStatus.QUEUED, attempt_count=0):
    """Inserisce un job sintetico nel database per gli scenari di test."""
    record = AnalysisRecordModel(
        sequence_number=None,
        id=analysis_id,
        file_name=file_name,
        status=status,
        risk_level=RiskLevel.LOW,
        created_at=utc_now(),
        updated_at=utc_now(),
        processing_started_at=utc_now() if status == AnalysisStatus.PROCESSING else None,
        completed_at=None,
        worker_id=None,
        attempt_count=attempt_count,
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


def test_acquire_next_queued_analysis_claims_oldest_job(db_session, tmp_path: Path) -> None:
    seed_job(db_session, analysis_id="ANL-2026-0001", file_name="first.txt", storage_path=str(tmp_path / "first.bin"))
    seed_job(db_session, analysis_id="ANL-2026-0002", file_name="second.txt", storage_path=str(tmp_path / "second.bin"))
    repository = AnalysisWorkerRepository(db_session)

    job = repository.acquire_next_queued_analysis("worker-a")

    assert job is not None
    assert job.id == "ANL-2026-0001"
    assert job.worker_id == "worker-a"


def test_mark_completed_updates_record(db_session, tmp_path: Path) -> None:
    seed_job(
        db_session,
        analysis_id="ANL-2026-0001",
        file_name="first.txt",
        storage_path=str(tmp_path / "first.bin"),
        status=AnalysisStatus.PROCESSING,
        attempt_count=1,
    )
    repository = AnalysisWorkerRepository(db_session)

    repository.mark_completed(
        "ANL-2026-0001",
        CompletedAnalysis(
            risk_level=RiskLevel.MEDIUM,
            mime_type="text/plain",
            sha256="a" * 64,
            entropy=3.14,
            extension_matches_mime=True,
            verdict="clean",
            scanned_at=datetime.now(timezone.utc),
            clamav_status="clean",
            clamav_signature_name=None,
            clamav_error=None,
            yara_status="clean",
            yara_matches=[],
            yara_error=None,
            indicators=["indicator"],
        ),
    )

    record = db_session.get(AnalysisRecordModel, 1)
    assert record is not None
    assert record.status == AnalysisStatus.COMPLETED
    assert record.sha256 == "a" * 64


def test_mark_failed_updates_record(db_session, tmp_path: Path) -> None:
    seed_job(
        db_session,
        analysis_id="ANL-2026-0001",
        file_name="first.txt",
        storage_path=str(tmp_path / "first.bin"),
        status=AnalysisStatus.PROCESSING,
        attempt_count=1,
    )
    repository = AnalysisWorkerRepository(db_session)

    repository.mark_failed("ANL-2026-0001", "boom")

    record = db_session.get(AnalysisRecordModel, 1)
    assert record is not None
    assert record.status == AnalysisStatus.FAILED
    assert record.error_message == "boom"


def test_recover_stale_jobs_requeues_or_fails(db_session, tmp_path: Path) -> None:
    seed_job(
        db_session,
        analysis_id="ANL-2026-0001",
        file_name="first.txt",
        storage_path=str(tmp_path / "first.bin"),
        status=AnalysisStatus.PROCESSING,
        attempt_count=1,
    )
    seed_job(
        db_session,
        analysis_id="ANL-2026-0002",
        file_name="second.txt",
        storage_path=str(tmp_path / "second.bin"),
        status=AnalysisStatus.PROCESSING,
        attempt_count=3,
    )
    for record in db_session.query(AnalysisRecordModel).all():
        record.processing_started_at = utc_now().replace(year=2025)
    db_session.commit()

    repository = AnalysisWorkerRepository(db_session)
    requeued, failed = repository.recover_stale_processing_jobs(
        processing_timeout_seconds=120,
        max_attempts=3,
    )

    assert requeued == 1
    assert failed == 1


def test_no_double_processing_after_claim(db_session, tmp_path: Path) -> None:
    """Verifica in modo semplice che lo stesso job non venga assegnato due volte."""
    seed_job(db_session, analysis_id="ANL-2026-0001", file_name="first.txt", storage_path=str(tmp_path / "first.bin"))
    repository = AnalysisWorkerRepository(db_session)

    first_job = repository.acquire_next_queued_analysis("worker-a")
    second_job = repository.acquire_next_queued_analysis("worker-b")

    assert first_job is not None
    assert second_job is None
