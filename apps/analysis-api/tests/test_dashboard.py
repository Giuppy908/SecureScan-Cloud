"""Test della pagina Dashboard calcolata lato backend.

Questa suite verifica che i numeri mostrati nella Dashboard non dipendano dal
browser e che rispettino lo stesso scope RBAC usato nel resto dell'applicazione.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import AnalysisRecordModel
from app.models.analysis import AnalysisStatus, RiskLevel
from app.services.dashboard import DashboardService

from .test_auth import (
    _build_jwk,
    _build_verifier,
    build_access_token,
    rsa_keypair,
    secured_client,
)


def _insert_analysis(
    db_session,
    *,
    analysis_id: str,
    file_name: str,
    status: AnalysisStatus,
    risk_level: RiskLevel,
    created_at: datetime,
    updated_at: datetime | None = None,
) -> None:
    """Inserisce rapidamente record analisi per scenari dashboard controllati."""
    db_session.add(
        AnalysisRecordModel(
            id=analysis_id,
            file_name=file_name,
            status=status,
            risk_level=risk_level,
            created_at=created_at,
            updated_at=updated_at or created_at,
            processing_started_at=None,
            completed_at=created_at if status in {AnalysisStatus.COMPLETED, AnalysisStatus.FAILED} else None,
            worker_id=None,
            attempt_count=0,
            storage_path=None,
            size_bytes=128,
            mime_type="text/plain" if status == AnalysisStatus.COMPLETED else None,
            sha256="a" * 64 if status == AnalysisStatus.COMPLETED else None,
            entropy=4.2 if status == AnalysisStatus.COMPLETED else None,
            extension_matches_mime=True if status == AnalysisStatus.COMPLETED else None,
            indicators=[],
            error_message="timeout" if status == AnalysisStatus.FAILED else None,
        )
    )
    db_session.commit()


def test_dashboard_returns_zeroed_snapshot_when_empty(client) -> None:
    response = client.get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "total_analyses": 0,
        "completed": 0,
        "processing": 0,
        "queued": 0,
        "failed": 0,
    }
    assert payload["recent_analyses"] == []
    assert payload["analyses_over_time"] == []
    assert payload["risk_distribution"] == [
        {"risk_level": "critical", "count": 0},
        {"risk_level": "high", "count": 0},
        {"risk_level": "medium", "count": 0},
        {"risk_level": "low", "count": 0},
    ]


def test_dashboard_aggregates_real_analysis_data(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    _insert_analysis(
        db_session,
        analysis_id="ANL-2026-0001",
        file_name="queued.txt",
        status=AnalysisStatus.QUEUED,
        risk_level=RiskLevel.LOW,
        created_at=now - timedelta(days=2),
    )
    _insert_analysis(
        db_session,
        analysis_id="ANL-2026-0002",
        file_name="processing.txt",
        status=AnalysisStatus.PROCESSING,
        risk_level=RiskLevel.MEDIUM,
        created_at=now - timedelta(days=1, minutes=10),
    )
    _insert_analysis(
        db_session,
        analysis_id="ANL-2026-0003",
        file_name="completed.txt",
        status=AnalysisStatus.COMPLETED,
        risk_level=RiskLevel.HIGH,
        created_at=now - timedelta(hours=2),
    )
    _insert_analysis(
        db_session,
        analysis_id="ANL-2026-0004",
        file_name="failed.txt",
        status=AnalysisStatus.FAILED,
        risk_level=RiskLevel.CRITICAL,
        created_at=now - timedelta(hours=1),
    )

    response = client.get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == {
        "total_analyses": 4,
        "completed": 1,
        "processing": 1,
        "queued": 1,
        "failed": 1,
    }
    assert [entry["risk_level"] for entry in payload["risk_distribution"]] == [
        "critical",
        "high",
        "medium",
        "low",
    ]
    assert [entry["count"] for entry in payload["risk_distribution"]] == [1, 1, 1, 1]
    assert [analysis["id"] for analysis in payload["recent_analyses"]] == [
        "ANL-2026-0004",
        "ANL-2026-0003",
        "ANL-2026-0002",
        "ANL-2026-0001",
    ]
    assert len(payload["analyses_over_time"]) == 3
    assert sum(entry["count"] for entry in payload["analyses_over_time"]) == 4


def test_dashboard_recent_analyses_are_limited_to_five_and_newest_first(client, db_session) -> None:
    now = datetime.now(timezone.utc)
    for offset in range(6):
        _insert_analysis(
            db_session,
            analysis_id=f"ANL-2026-00{offset + 1:02d}",
            file_name=f"file-{offset}.txt",
            status=AnalysisStatus.COMPLETED,
            risk_level=RiskLevel.LOW,
            created_at=now - timedelta(minutes=offset),
        )

    response = client.get("/api/v1/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["recent_analyses"]) == 5
    assert [analysis["file_name"] for analysis in payload["recent_analyses"]] == [
        "file-0.txt",
        "file-1.txt",
        "file-2.txt",
        "file-3.txt",
        "file-4.txt",
    ]


def test_dashboard_service_limits_time_buckets_to_last_fourteen(db_session) -> None:
    now = datetime.now(timezone.utc)
    for offset in range(16):
        _insert_analysis(
            db_session,
            analysis_id=f"ANL-2026-BKT-{offset:02d}",
            file_name=f"bucket-{offset}.txt",
            status=AnalysisStatus.COMPLETED,
            risk_level=RiskLevel.LOW,
            created_at=now - timedelta(days=offset),
        )

    snapshot = DashboardService(db_session).collect_snapshot()

    assert len(snapshot.analyses_over_time) == 14


def test_dashboard_requires_authentication_when_enabled(secured_client) -> None:
    client, _ = secured_client

    response = client.get("/api/v1/dashboard")

    assert response.status_code == 401


def test_dashboard_allows_analyst_when_token_is_valid(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["analyst"])

    response = client.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_dashboard_allows_admin_when_token_is_valid(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["admin", "analyst"])

    response = client.get("/api/v1/dashboard", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
