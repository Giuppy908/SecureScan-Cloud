"""Test di Nuova analisi, Cronologia e Dettaglio analisi.

Questa suite protegge i flussi più visibili del prodotto:
- caricamento file dalla pagina Nuova analisi;
- creazione del job `queued`;
- cronologia paginata e filtrata lato server;
- lettura del dettaglio di una singola analisi.
"""

from pathlib import Path

import anyio
import pytest

from app.core.config import settings
from app.db.models import AnalysisRecordModel
from app.models.analysis import AnalysisPage, AnalysisStatus, AnalysisVerdict, RiskLevel
from app.repositories.base import AnalysisRepository, RepositoryError
from app.repositories.sqlalchemy_repository import get_repository
from app.services.upload_storage import UploadStorageError, UploadStorageService


class FailingRepository(AnalysisRepository):
    """Stub che forza errori repository per testare i path 500 dell'API."""

    def create(self, analysis_data):
        raise RepositoryError("create failed")

    def create_queued_analysis(self, analysis_data):
        raise RepositoryError("create failed")

    def acquire_next_queued_analysis(self, worker_id: str):
        raise RepositoryError("acquire failed")

    def mark_processing(self, analysis_id: str, worker_id: str):
        raise RepositoryError("processing failed")

    def mark_completed(self, analysis_id: str, result):
        raise RepositoryError("completed failed")

    def mark_failed(self, analysis_id: str, error_message: str):
        raise RepositoryError("failed failed")

    def recover_stale_processing_jobs(self, *, processing_timeout_seconds: int, max_attempts: int):
        raise RepositoryError("recover failed")

    def list_all(self, owner_sub=None):
        raise RepositoryError("list failed")

    def list_page(
        self,
        *,
        owner_sub=None,
        search=None,
        status=None,
        risk_level=None,
        owner_filter=None,
        page=1,
        page_size=10,
    ):
        raise RepositoryError("list failed")

    def get_by_id(self, analysis_id: str, owner_sub=None):
        raise RepositoryError("get failed")

    def clear(self) -> list[str]:
        raise RepositoryError("clear failed")


def _extract_page_payload(response):
    """Restituisce payload completo e lista `items` da una risposta paginata."""
    payload = response.json()
    return payload, payload["items"]


def _create_analysis(client, file_name: str, content: bytes | None = None):
    """Helper per creare rapidamente un'analisi via API durante i test."""
    return client.post(
        "/api/v1/analyses",
        files={"file": (file_name, content or file_name.encode("utf-8"), "text/plain")},
    )


def test_create_analysis_returns_queued_with_null_results(client) -> None:
    content = b"hello securscan"

    response = client.post(
        "/api/v1/analyses",
        files={"file": ("sample.txt", content, "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["id"] == "ANL-2026-0001"
    assert payload["sha256"] is None
    assert payload["size_bytes"] == len(content)
    assert payload["mime_type"] is None
    assert payload["entropy"] is None
    assert payload["extension_matches_mime"] is None
    assert payload["verdict"] is None
    assert payload["clamav_status"] is None
    assert payload["yara_status"] is None
    assert payload["yara_matches"] == []
    assert payload["status"] == "queued"
    assert payload["risk_level"] == "low"
    assert payload["error_message"] is None
    assert response.headers["X-Backend-Instance"] == "test-analysis-api"


def test_list_analyses_returns_newest_first(client) -> None:
    _create_analysis(client, "first.txt", b"first")
    second_response = client.post("/api/v1/analyses", files={"file": ("second.txt", b"%PDF-1.4 example", "application/pdf")})

    response = client.get("/api/v1/analyses")

    assert second_response.status_code == 202
    assert response.status_code == 200
    assert response.headers["X-Backend-Instance"] == "test-analysis-api"
    payload, items = _extract_page_payload(response)
    assert payload["total"] == 2
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["total_pages"] == 1
    assert len(items) == 2
    assert items[0]["id"] == "ANL-2026-0002"
    assert items[1]["id"] == "ANL-2026-0001"


def test_get_analysis_returns_existing_item(client) -> None:
    create_response = client.post(
        "/api/v1/analyses",
        files={"file": ("report.pdf", b"%PDF-1.4 report", "application/pdf")},
    )
    analysis_id = create_response.json()["id"]

    response = client.get(f"/api/v1/analyses/{analysis_id}")

    assert response.status_code == 200
    assert response.headers["X-Backend-Instance"] == "test-analysis-api"
    assert response.json()["id"] == analysis_id


def test_get_analysis_returns_404_when_missing(client) -> None:
    response = client.get("/api/v1/analyses/ANL-2026-9999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Analysis 'ANL-2026-9999' not found."


def test_create_analysis_rejects_empty_file(client) -> None:
    response = client.post(
        "/api/v1/analyses",
        files={"file": ("empty.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file is empty."


def test_create_analysis_accepts_file_exactly_at_configured_limit(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    content = b"a" * settings.max_upload_size_bytes

    response = client.post(
        "/api/v1/analyses",
        files={"file": ("limit.txt", content, "text/plain")},
    )

    assert response.status_code == 202
    assert response.json()["size_bytes"] == len(content)


def test_create_analysis_rejects_file_one_byte_over_limit(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    content = b"a" * (settings.max_upload_size_bytes + 1)

    response = client.post(
        "/api/v1/analyses",
        files={"file": ("large.txt", content, "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Uploaded file exceeds the maximum allowed size of 1 MB."


def test_create_analysis_over_limit_does_not_create_record(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    before_response = client.get("/api/v1/analyses")

    response = client.post(
        "/api/v1/analyses",
        files={"file": ("large.txt", b"a" * (settings.max_upload_size_bytes + 1), "text/plain")},
    )
    after_response = client.get("/api/v1/analyses")

    assert response.status_code == 413
    assert before_response.json()["items"] == []
    assert after_response.json()["items"] == []


def test_create_analysis_respects_custom_limit_configuration(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_upload_size_mb", 2)

    accepted_response = client.post(
        "/api/v1/analyses",
        files={"file": ("accepted.bin", b"a" * settings.max_upload_size_bytes, "application/octet-stream")},
    )
    rejected_response = client.post(
        "/api/v1/analyses",
        files={"file": ("rejected.bin", b"a" * (settings.max_upload_size_bytes + 1), "application/octet-stream")},
    )

    assert accepted_response.status_code == 202
    assert rejected_response.status_code == 413
    assert rejected_response.json()["detail"] == "Uploaded file exceeds the maximum allowed size of 2 MB."


def test_delete_analyses_clears_repository_without_reusing_ids(client) -> None:
    client.post(
        "/api/v1/analyses",
        files={"file": ("demo.txt", b"demo", "text/plain")},
    )

    delete_response = client.delete("/api/v1/analyses")
    recreate_response = client.post(
        "/api/v1/analyses",
        files={"file": ("second-demo.txt", b"demo-2", "text/plain")},
    )

    assert delete_response.status_code == 204
    assert recreate_response.status_code == 202
    assert recreate_response.json()["id"] == "ANL-2026-0002"


def test_repository_error_returns_500(client) -> None:
    client.app.dependency_overrides[get_repository] = lambda: FailingRepository()
    try:
        response = client.post(
            "/api/v1/analyses",
            files={"file": ("sample.txt", b"content", "text/plain")},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to persist analysis."


def test_upload_writes_file_to_shared_storage(client) -> None:
    content = b"stored content"

    response = client.post(
        "/api/v1/analyses",
        files={"file": ("stored.txt", content, "text/plain")},
    )

    assert response.status_code == 202

    list_response = client.get("/api/v1/analyses")
    analysis_id = response.json()["id"]
    assert any(item["id"] == analysis_id for item in list_response.json()["items"])

    from app.core.config import settings

    upload_dir = Path(settings.upload_dir)
    stored_files = list(upload_dir.iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == content


def test_storage_error_returns_500(client, monkeypatch) -> None:
    from app.api import analyses as analyses_module

    async def failing_save_upload(self, _):
        raise analyses_module.UploadStorageError("boom")

    monkeypatch.setattr(analyses_module.UploadStorageService, "save_upload", failing_save_upload)

    response = client.post(
        "/api/v1/analyses",
        files={"file": ("sample.txt", b"content", "text/plain")},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to store uploaded file."


def test_delete_analyses_removes_stored_files(client) -> None:
    response = client.post(
        "/api/v1/analyses",
        files={"file": ("stored.txt", b"content", "text/plain")},
    )
    assert response.status_code == 202

    from app.core.config import settings

    upload_dir = Path(settings.upload_dir)
    assert any(upload_dir.iterdir())

    delete_response = client.delete("/api/v1/analyses")

    assert delete_response.status_code == 204
    assert list(upload_dir.iterdir()) == []


def test_list_analyses_returns_empty_page_when_no_results(client) -> None:
    response = client.get("/api/v1/analyses")

    assert response.status_code == 200
    payload, items = _extract_page_payload(response)
    assert items == []
    assert payload["total"] == 0
    assert payload["total_pages"] == 0


def test_list_analyses_returns_single_page_when_results_are_under_default_page_size(client) -> None:
    for index in range(3):
        create_response = _create_analysis(client, f"sample-{index}.txt")
        assert create_response.status_code == 202

    response = client.get("/api/v1/analyses")

    assert response.status_code == 200
    payload, items = _extract_page_payload(response)
    assert payload["total"] == 3
    assert payload["total_pages"] == 1
    assert len(items) == 3


def test_list_analyses_returns_exactly_one_full_page(client) -> None:
    for index in range(10):
        create_response = _create_analysis(client, f"sample-{index}.txt")
        assert create_response.status_code == 202

    response = client.get("/api/v1/analyses")

    assert response.status_code == 200
    payload, items = _extract_page_payload(response)
    assert payload["total"] == 10
    assert payload["total_pages"] == 1
    assert len(items) == 10


def test_list_analyses_returns_second_page_when_results_exceed_default_page_size(client) -> None:
    for index in range(12):
        create_response = _create_analysis(client, f"sample-{index}.txt")
        assert create_response.status_code == 202

    response = client.get("/api/v1/analyses?page=2")

    assert response.status_code == 200
    payload, items = _extract_page_payload(response)
    assert payload["total"] == 12
    assert payload["page"] == 2
    assert payload["total_pages"] == 2
    assert len(items) == 2
    assert items[0]["id"] == "ANL-2026-0002"
    assert items[1]["id"] == "ANL-2026-0001"


def test_list_analyses_filters_by_file_name_and_total(client) -> None:
    _create_analysis(client, "invoice.pdf")
    _create_analysis(client, "report.pdf")
    _create_analysis(client, "invoice-archive.zip")

    response = client.get("/api/v1/analyses?search=INVOICE")

    assert response.status_code == 200
    payload, items = _extract_page_payload(response)
    assert payload["total"] == 2
    assert [item["file_name"] for item in items] == ["invoice-archive.zip", "invoice.pdf"]


def test_list_analyses_filters_by_analysis_id(client) -> None:
    first_response = _create_analysis(client, "first.txt")
    second_response = _create_analysis(client, "second.txt")
    assert first_response.status_code == 202
    assert second_response.status_code == 202

    response = client.get("/api/v1/analyses?search=0001")

    assert response.status_code == 200
    payload, items = _extract_page_payload(response)
    assert payload["total"] == 1
    assert [item["id"] for item in items] == ["ANL-2026-0001"]


def test_list_analyses_filters_by_status_and_risk(client, db_session) -> None:
    first_response = _create_analysis(client, "queued.txt")
    second_response = _create_analysis(client, "completed.txt")
    assert first_response.status_code == 202
    assert second_response.status_code == 202

    db_session.query(AnalysisRecordModel).filter_by(id=second_response.json()["id"]).update(
        {
            "status": AnalysisStatus.COMPLETED,
            "risk_level": RiskLevel.HIGH,
            "mime_type": "text/plain",
            "sha256": "a" * 64,
            "entropy": 7.2,
            "extension_matches_mime": True,
        },
        synchronize_session=False,
    )
    db_session.commit()

    response = client.get("/api/v1/analyses?status=completed&risk=high")

    assert response.status_code == 200
    payload, items = _extract_page_payload(response)
    assert payload["total"] == 1
    assert [item["id"] for item in items] == [second_response.json()["id"]]


def test_list_analyses_filters_by_visible_status_semantics(client, db_session) -> None:
    clean_response = _create_analysis(client, "completed-clean.txt")
    scan_error_response = _create_analysis(client, "scan-error-test.txt")
    failed_response = _create_analysis(client, "processing-failed.txt")
    queued_response = _create_analysis(client, "queued.txt")
    processing_response = _create_analysis(client, "processing.txt")

    assert clean_response.status_code == 202
    assert scan_error_response.status_code == 202
    assert failed_response.status_code == 202
    assert queued_response.status_code == 202
    assert processing_response.status_code == 202

    db_session.query(AnalysisRecordModel).filter_by(id=clean_response.json()["id"]).update(
        {
            "status": AnalysisStatus.COMPLETED,
            "verdict": AnalysisVerdict.CLEAN,
            "risk_level": RiskLevel.LOW,
            "mime_type": "text/plain",
            "sha256": "a" * 64,
            "entropy": 2.1,
            "extension_matches_mime": True,
            "clamav_status": "clean",
            "yara_status": "clean",
        },
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=scan_error_response.json()["id"]).update(
        {
            "status": AnalysisStatus.COMPLETED,
            "verdict": AnalysisVerdict.SCAN_ERROR,
            "risk_level": RiskLevel.CRITICAL,
            "clamav_status": "unavailable",
            "yara_status": "clean",
            "error_message": "ClamAV non raggiungibile",
        },
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=failed_response.json()["id"]).update(
        {
            "status": AnalysisStatus.FAILED,
            "verdict": None,
            "risk_level": RiskLevel.CRITICAL,
            "error_message": "Errore worker",
        },
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=processing_response.json()["id"]).update(
        {
            "status": AnalysisStatus.PROCESSING,
        },
        synchronize_session=False,
    )
    db_session.commit()

    completed_response = client.get("/api/v1/analyses?status=completed")
    failed_status_response = client.get("/api/v1/analyses?status=failed")
    queued_status_response = client.get("/api/v1/analyses?status=queued")
    processing_status_response = client.get("/api/v1/analyses?status=processing")

    completed_payload, completed_items = _extract_page_payload(completed_response)
    failed_payload, failed_items = _extract_page_payload(failed_status_response)
    queued_payload, queued_items = _extract_page_payload(queued_status_response)
    processing_payload, processing_items = _extract_page_payload(processing_status_response)

    assert completed_payload["total"] == 1
    assert [item["id"] for item in completed_items] == [clean_response.json()["id"]]
    assert failed_payload["total"] == 2
    assert failed_payload["total_pages"] == 1
    assert {item["id"] for item in failed_items} == {
        scan_error_response.json()["id"],
        failed_response.json()["id"],
    }
    assert [item["id"] for item in queued_items] == [queued_response.json()["id"]]
    assert [item["id"] for item in processing_items] == [processing_response.json()["id"]]


def test_list_analyses_applies_combined_filters_before_pagination(client, db_session) -> None:
    matching_ids: list[str] = []
    for index in range(12):
        response = _create_analysis(client, f"report-{index}.pdf")
        assert response.status_code == 202
        matching_ids.append(response.json()["id"])
    for index in range(3):
        response = _create_analysis(client, f"other-{index}.txt")
        assert response.status_code == 202

    db_session.query(AnalysisRecordModel).filter(AnalysisRecordModel.id.in_(matching_ids)).update(
        {"status": AnalysisStatus.COMPLETED, "risk_level": RiskLevel.MEDIUM},
        synchronize_session=False,
    )
    db_session.commit()

    page_one = client.get("/api/v1/analyses?search=report&status=completed&risk=medium&page=1")
    page_two = client.get("/api/v1/analyses?search=report&status=completed&risk=medium&page=2")

    assert page_one.status_code == 200
    assert page_two.status_code == 200
    first_payload, first_items = _extract_page_payload(page_one)
    second_payload, second_items = _extract_page_payload(page_two)
    assert first_payload["total"] == 12
    assert first_payload["total_pages"] == 2
    assert len(first_items) == 10
    assert second_payload["total"] == 12
    assert len(second_items) == 2


def test_list_analyses_rejects_invalid_pagination_parameters(client) -> None:
    response = client.get("/api/v1/analyses?page=0&page_size=0")

    assert response.status_code == 422


def test_upload_storage_service_cleans_up_partial_file(tmp_path, monkeypatch) -> None:
    service = UploadStorageService(str(tmp_path / "uploads"))
    target_file = (tmp_path / "uploads") / "deadbeef.txt"

    class FakeUploadFile:
        filename = "partial.txt"

        def __init__(self) -> None:
            self._read_called = False
            self.closed = False

        async def read(self, _size: int) -> bytes:
            if self._read_called:
                return b""
            self._read_called = True
            return b"partial-content"

        async def close(self) -> None:
            self.closed = True

    class FakeUUID:
        hex = "deadbeef"

    class FailingWriter:
        def __init__(self, path: Path) -> None:
            self._path = path

        def __enter__(self) -> "FailingWriter":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def write(self, _content: bytes) -> int:
            self._path.touch(exist_ok=True)
            raise OSError("disk full")

    def failing_open(self: Path, mode: str = "r", *args, **kwargs) -> FailingWriter:
        assert mode == "wb"
        return FailingWriter(self)

    monkeypatch.setattr("app.services.upload_storage.uuid4", lambda: FakeUUID())
    monkeypatch.setattr(Path, "open", failing_open)

    uploaded_file = FakeUploadFile()

    with pytest.raises(UploadStorageError) as exc_info:
        anyio.run(service.save_upload, uploaded_file)

    assert "Failed to store uploaded file." in str(exc_info.value)
    assert uploaded_file.closed is True
    assert not target_file.exists()


def test_upload_storage_service_deletes_partial_file_when_limit_is_exceeded(tmp_path, monkeypatch) -> None:
    service = UploadStorageService(str(tmp_path / "uploads"))
    target_file = (tmp_path / "uploads") / "deadbeef.bin"
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)

    class FakeUploadFile:
        filename = "too-large.bin"

        def __init__(self) -> None:
            self._chunks = [
                b"a" * (512 * 1024),
                b"b" * (512 * 1024),
                b"c",
            ]
            self._index = 0
            self.closed = False

        async def read(self, _size: int) -> bytes:
            if self._index >= len(self._chunks):
                return b""
            chunk = self._chunks[self._index]
            self._index += 1
            return chunk

        async def close(self) -> None:
            self.closed = True

    class FakeUUID:
        hex = "deadbeef"

    monkeypatch.setattr("app.services.upload_storage.uuid4", lambda: FakeUUID())
    uploaded_file = FakeUploadFile()

    with pytest.raises(ValueError) as exc_info:
        anyio.run(service.save_upload, uploaded_file)

    assert str(exc_info.value) == "Uploaded file exceeds the maximum allowed size of 1 MB."
    assert uploaded_file.closed is True
    assert not target_file.exists()
