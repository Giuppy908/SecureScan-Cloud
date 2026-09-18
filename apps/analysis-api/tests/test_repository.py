"""Test del repository SQLAlchemy reale.

Questi casi verificano le garanzie su cui si basano Cronologia, Dashboard,
Dettaglio analisi e worker: ordinamento, filtri, paginazione, ownership e
transizioni corrette dei job nel database relazionale.
"""

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone

from app.db.models import AnalysisRecordModel
from app.models.analysis import (
    AnalysisCompletionResult,
    AnalysisCreateResult,
    AnalysisStatus,
    AnalysisVerdict,
    QueuedAnalysisCreate,
    RiskLevel,
)
from app.repositories.base import RepositoryError
from app.repositories.sqlalchemy_repository import SqlAlchemyAnalysisRepository


def build_analysis(file_name: str, sha256: str) -> AnalysisCreateResult:
    """Crea rapidamente un payload analisi completo per i test repository."""
    return AnalysisCreateResult(
        file_name=file_name,
        status=AnalysisStatus.COMPLETED,
        risk_level=RiskLevel.LOW,
        size_bytes=128,
        mime_type="text/plain",
        sha256=sha256,
        entropy=4.2,
        extension_matches_mime=True,
        indicators=[],
        error_message=None,
    )


def test_repository_generates_progressive_ids(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    first = repository.create(build_analysis("first.txt", "a" * 64))
    second = repository.create(build_analysis("second.txt", "b" * 64))

    assert first.id == "ANL-2026-0001"
    assert second.id == "ANL-2026-0002"


def test_repository_assigns_sequence_number(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    created = repository.create(build_analysis("first.txt", "a" * 64))
    stored = db_session.scalar(
        sa.select(AnalysisRecordModel).where(AnalysisRecordModel.id == created.id)
    )

    assert stored is not None
    assert stored.sequence_number == 1


def test_repository_lists_newest_first(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    repository.create(build_analysis("first.txt", "a" * 64))
    repository.create(build_analysis("second.txt", "b" * 64))

    analyses = repository.list_all()

    assert [analysis.file_name for analysis in analyses] == ["second.txt", "first.txt"]


def test_repository_list_page_returns_total_and_second_page(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    for index in range(12):
        repository.create(build_analysis(f"sample-{index}.txt", f"{index:064x}"))

    page = repository.list_page(page=2, page_size=10)

    assert page.total == 12
    assert page.page == 2
    assert page.page_size == 10
    assert page.total_pages == 2
    assert [analysis.id for analysis in page.items] == ["ANL-2026-0002", "ANL-2026-0001"]


def test_repository_list_page_applies_filters_before_count_and_pagination(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    matching_ids: list[str] = []
    for index in range(12):
        created = repository.create(
            build_analysis(
                f"report-{index}.pdf",
                f"{index + 1:064x}",
            )
        )
        matching_ids.append(created.id)
    repository.create(build_analysis("notes.txt", "f" * 64))

    db_session.query(AnalysisRecordModel).filter(AnalysisRecordModel.id.in_(matching_ids)).update(
        {"risk_level": RiskLevel.MEDIUM},
        synchronize_session=False,
    )
    db_session.commit()

    page = repository.list_page(
        search="REPORT",
        status=AnalysisStatus.COMPLETED,
        risk_level=RiskLevel.MEDIUM,
        page=2,
        page_size=10,
    )

    assert page.total == 12
    assert len(page.items) == 2
    assert all(analysis.file_name.startswith("report-") for analysis in page.items)


def test_repository_list_page_filters_by_owner_scope_and_admin_owner_filter(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    first = repository.create(build_analysis("owned-a.txt", "1" * 64))
    second = repository.create(build_analysis("owned-b.txt", "2" * 64))
    third = repository.create(build_analysis("owned-c.txt", "3" * 64))
    db_session.query(AnalysisRecordModel).filter_by(id=first.id).update(
        {"owner_sub": "user-a", "owner_username": "analyst.a"},
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=second.id).update(
        {"owner_sub": "user-b", "owner_username": "analyst.b"},
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=third.id).update(
        {"owner_sub": "user-b", "owner_username": "analyst.b"},
        synchronize_session=False,
    )
    db_session.commit()

    analyst_page = repository.list_page(owner_sub="user-b", page=1, page_size=10)
    admin_filtered_page = repository.list_page(owner_filter="user-a", page=1, page_size=10)

    assert analyst_page.total == 2
    assert [analysis.owner_sub for analysis in analyst_page.items] == ["user-b", "user-b"]
    assert admin_filtered_page.total == 1
    assert [analysis.owner_sub for analysis in admin_filtered_page.items] == ["user-a"]


def test_repository_list_page_filters_by_presentation_status(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    completed_clean = repository.create(build_analysis("completed-clean.txt", "1" * 64))
    completed_scan_error = repository.create(build_analysis("scan-error.txt", "2" * 64))
    raw_failed = repository.create(build_analysis("raw-failed.txt", "3" * 64))
    queued = repository.create_queued_analysis(
        QueuedAnalysisCreate(
            file_name="queued.txt",
            size_bytes=12,
            storage_path="/tmp/queued.txt",
        )
    )
    processing = repository.create_queued_analysis(
        QueuedAnalysisCreate(
            file_name="processing.txt",
            size_bytes=16,
            storage_path="/tmp/processing.txt",
        )
    )

    db_session.query(AnalysisRecordModel).filter_by(id=completed_scan_error.id).update(
        {
            "verdict": AnalysisVerdict.SCAN_ERROR,
            "risk_level": RiskLevel.CRITICAL,
            "clamav_status": "unavailable",
            "yara_status": "clean",
            "error_message": "ClamAV non raggiungibile",
        },
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=raw_failed.id).update(
        {
            "status": AnalysisStatus.FAILED,
            "verdict": None,
            "risk_level": RiskLevel.CRITICAL,
            "error_message": "Errore tecnico",
        },
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=processing.id).update(
        {
            "status": AnalysisStatus.PROCESSING,
        },
        synchronize_session=False,
    )
    db_session.commit()

    completed_page = repository.list_page(status=AnalysisStatus.COMPLETED, page=1, page_size=10)
    failed_page = repository.list_page(status=AnalysisStatus.FAILED, page=1, page_size=10)
    queued_page = repository.list_page(status=AnalysisStatus.QUEUED, page=1, page_size=10)
    processing_page = repository.list_page(status=AnalysisStatus.PROCESSING, page=1, page_size=10)

    assert completed_page.total == 1
    assert [analysis.id for analysis in completed_page.items] == [completed_clean.id]
    assert failed_page.total == 2
    assert failed_page.total_pages == 1
    assert {analysis.id for analysis in failed_page.items} == {completed_scan_error.id, raw_failed.id}
    assert [analysis.id for analysis in queued_page.items] == [queued.id]
    assert [analysis.id for analysis in processing_page.items] == [processing.id]


def test_repository_clear_does_not_reset_sequence(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    repository.create(build_analysis("first.txt", "a" * 64))
    repository.clear()
    recreated = repository.create(build_analysis("second.txt", "b" * 64))

    assert recreated.id == "ANL-2026-0002"


def test_repository_raises_on_database_error(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)
    db_session.execute(text("DROP TABLE analyses"))
    db_session.commit()

    try:
        repository.list_all()
    except RepositoryError as exc:
        assert "Failed to list analyses." in str(exc)
    else:
        raise AssertionError("Expected RepositoryError to be raised.")


def test_repository_rolls_back_on_commit_error(db_session, monkeypatch) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)
    rollback_calls: list[str] = []

    original_rollback = db_session.rollback

    def tracking_rollback():
        rollback_calls.append("rollback")
        return original_rollback()

    def failing_commit():
        raise SQLAlchemyError("commit failed")

    monkeypatch.setattr(db_session, "rollback", tracking_rollback)
    monkeypatch.setattr(db_session, "commit", failing_commit)

    try:
        repository.create(build_analysis("broken.txt", "c" * 64))
    except RepositoryError as exc:
        assert "Failed to persist analysis." in str(exc)
    else:
        raise AssertionError("Expected RepositoryError to be raised.")

    assert rollback_calls == ["rollback"]


def test_create_queued_analysis_preserves_null_result_fields(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)

    created = repository.create_queued_analysis(
        QueuedAnalysisCreate(
            file_name="queued.bin",
            size_bytes=42,
            storage_path="/tmp/queued.bin",
        )
    )
    stored = db_session.scalar(sa.select(AnalysisRecordModel).where(AnalysisRecordModel.id == created.id))

    assert created.status == AnalysisStatus.QUEUED
    assert created.mime_type is None
    assert created.sha256 is None
    assert created.entropy is None
    assert created.extension_matches_mime is None
    assert created.error_message is None
    assert stored is not None
    assert stored.processing_started_at is None
    assert stored.completed_at is None
    assert stored.worker_id is None
    assert stored.error_message is None


def test_mark_processing_enforces_processing_invariants(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)
    created = repository.create_queued_analysis(
        QueuedAnalysisCreate(
            file_name="queued.bin",
            size_bytes=42,
            storage_path="/tmp/queued.bin",
        )
    )

    job = repository.mark_processing(created.id, "worker-a")
    stored = db_session.scalar(sa.select(AnalysisRecordModel).where(AnalysisRecordModel.id == created.id))

    assert job.worker_id == "worker-a"
    assert stored is not None
    assert stored.status == AnalysisStatus.PROCESSING
    assert stored.processing_started_at is not None
    assert stored.completed_at is None
    assert stored.worker_id == "worker-a"
    assert stored.mime_type is None
    assert stored.sha256 is None
    assert stored.entropy is None
    assert stored.extension_matches_mime is None
    assert stored.error_message is None


def test_mark_completed_populates_results_and_clears_storage_path(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)
    created = repository.create_queued_analysis(
        QueuedAnalysisCreate(
            file_name="queued.bin",
            size_bytes=42,
            storage_path="/tmp/queued.bin",
        )
    )
    repository.mark_processing(created.id, "worker-a")

    completed = repository.mark_completed(
        created.id,
        AnalysisCompletionResult(
            risk_level=RiskLevel.MEDIUM,
            mime_type="text/plain",
            sha256="f" * 64,
            entropy=3.25,
            extension_matches_mime=True,
            verdict="clean",
            scanned_at=datetime.now(timezone.utc),
            clamav_status="clean",
            clamav_signature_name=None,
            clamav_error=None,
            yara_status="clean",
            yara_matches=[],
            yara_error=None,
            indicators=["Indicatore di test"],
        ),
    )
    stored = db_session.scalar(sa.select(AnalysisRecordModel).where(AnalysisRecordModel.id == created.id))

    assert completed.status == AnalysisStatus.COMPLETED
    assert completed.mime_type == "text/plain"
    assert completed.sha256 == "f" * 64
    assert completed.entropy == 3.25
    assert completed.extension_matches_mime is True
    assert completed.error_message is None
    assert stored is not None
    assert stored.completed_at is not None
    assert stored.storage_path is None


def test_mark_failed_clears_results_and_sets_error(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)
    created = repository.create_queued_analysis(
        QueuedAnalysisCreate(
            file_name="queued.bin",
            size_bytes=42,
            storage_path="/tmp/queued.bin",
        )
    )
    repository.mark_processing(created.id, "worker-a")

    failed = repository.mark_failed(created.id, "Errore controllato")
    stored = db_session.scalar(sa.select(AnalysisRecordModel).where(AnalysisRecordModel.id == created.id))

    assert failed.status == AnalysisStatus.FAILED
    assert failed.mime_type is None
    assert failed.sha256 is None
    assert failed.entropy is None
    assert failed.extension_matches_mime is None
    assert failed.error_message == "Errore controllato"
    assert stored is not None
    assert stored.completed_at is not None
    assert stored.storage_path is None


def test_mark_failed_rejects_queued_transition(db_session) -> None:
    repository = SqlAlchemyAnalysisRepository(db_session)
    created = repository.create_queued_analysis(
        QueuedAnalysisCreate(
            file_name="queued.bin",
            size_bytes=42,
            storage_path="/tmp/queued.bin",
        )
    )

    try:
        repository.mark_failed(created.id, "Non valido")
    except RepositoryError as exc:
        assert "cannot fail" in str(exc)
    else:
        raise AssertionError("Expected queued -> failed transition to be rejected.")
