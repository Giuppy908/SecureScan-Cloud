"""Test di ownership, Profilo, Modifica profilo e Amministrazione utenti.

Questa è la suite che protegge la separazione più delicata del progetto:
- un analyst deve vedere solo il proprio perimetro;
- un admin deve poter gestire globalmente utenti e analisi;
- profilo, avatar e dati Keycloak devono restare coerenti tra sistemi diversi.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs

import pytest
from fastapi import UploadFile

from app.core.config import settings
from app.api.admin_users import get_profile_service as get_admin_profile_service
from app.api.profile import get_profile_service as get_route_profile_service
from app.db.models import AnalysisRecordModel
from app.models.profile import (
    AdminUserProfileUpdateRequest,
    AdminUserAnalysesSnapshot,
    AdminUserSummary,
    AdminUserUpdateRequest,
    ProfileStatistics,
    UpdateOwnPasswordRequest,
    UpdateOwnProfileRequest,
    VerificationEmailResponse,
    UserProfileSnapshot,
)
from app.models.dashboard import DashboardRiskDistributionEntry
from app.services.keycloak_admin import KeycloakAdminClient, KeycloakAdminError, KeycloakCredentialError, KeycloakUser, KeycloakUserSession
from app.services.profile_service import ProfileServiceError, UserProfileService
from app.services.avatar_storage import AvatarStorageService, AvatarValidationError

from .test_auth import (
    _build_jwk,
    _build_verifier,
    build_access_token,
    rsa_keypair,
    secured_client,
)


def _build_headers(
    secured_client_value,
    rsa_keypair_value,
    *,
    subject: str,
    username: str,
    roles: list[str],
) -> dict[str, str]:
    """Costruisce header Authorization realistici per i test RBAC end-to-end."""
    client, verifier_holder = secured_client_value
    private_key, public_key = rsa_keypair_value
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(
        private_key,
        kid="kid-1",
        roles=roles,
        payload_overrides={"sub": subject, "preferred_username": username, "name": username},
    )
    return {"Authorization": f"Bearer {token}"}


def test_analyst_only_sees_own_analyses(secured_client, rsa_keypair, db_session) -> None:
    client, _ = secured_client
    analyst_one_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-1",
        username="analyst.one",
        roles=["analyst"],
    )
    analyst_two_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-2",
        username="analyst.two",
        roles=["analyst"],
    )
    admin_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-admin-1",
        username="admin.demo",
        roles=["admin", "analyst"],
    )

    first_response = client.post(
        "/api/v1/analyses",
        headers=analyst_one_headers,
        files={"file": ("first.txt", b"first", "text/plain")},
    )
    second_response = client.post(
        "/api/v1/analyses",
        headers=analyst_two_headers,
        files={"file": ("second.txt", b"second", "text/plain")},
    )

    assert first_response.status_code == 202
    assert second_response.status_code == 202

    first_analysis_id = first_response.json()["id"]
    stored_record = db_session.query(AnalysisRecordModel).filter_by(id=first_analysis_id).one()
    assert stored_record.owner_sub == "user-analyst-1"
    assert stored_record.owner_username == "analyst.one"

    analyst_one_list = client.get("/api/v1/analyses", headers=analyst_one_headers)
    analyst_two_list = client.get("/api/v1/analyses", headers=analyst_two_headers)
    admin_list = client.get("/api/v1/analyses", headers=admin_headers)

    assert [item["owner_sub"] for item in analyst_one_list.json()["items"]] == ["user-analyst-1"]
    assert analyst_one_list.json()["total"] == 1
    assert [item["owner_sub"] for item in analyst_two_list.json()["items"]] == ["user-analyst-2"]
    assert analyst_two_list.json()["total"] == 1
    assert admin_list.json()["total"] == 2


def test_analyst_cannot_open_another_users_analysis(secured_client, rsa_keypair) -> None:
    client, _ = secured_client
    analyst_one_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-1",
        username="analyst.one",
        roles=["analyst"],
    )
    analyst_two_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-2",
        username="analyst.two",
        roles=["analyst"],
    )

    create_response = client.post(
        "/api/v1/analyses",
        headers=analyst_one_headers,
        files={"file": ("private.txt", b"private", "text/plain")},
    )
    analysis_id = create_response.json()["id"]

    response = client.get(f"/api/v1/analyses/{analysis_id}", headers=analyst_two_headers)

    assert response.status_code == 404


def test_admin_can_open_any_users_analysis(secured_client, rsa_keypair) -> None:
    client, _ = secured_client
    analyst_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-1",
        username="analyst.one",
        roles=["analyst"],
    )
    admin_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-admin-1",
        username="admin.demo",
        roles=["admin", "analyst"],
    )

    create_response = client.post(
        "/api/v1/analyses",
        headers=analyst_headers,
        files={"file": ("shared.txt", b"shared", "text/plain")},
    )
    analysis_id = create_response.json()["id"]

    response = client.get(f"/api/v1/analyses/{analysis_id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["owner_username"] == "analyst.one"


def test_user_without_roles_cannot_read_analyses(secured_client, rsa_keypair) -> None:
    headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-no-role",
        username="viewer.demo",
        roles=[],
    )
    client, _ = secured_client

    list_response = client.get("/api/v1/analyses", headers=headers)
    detail_response = client.get("/api/v1/analyses/ANL-2026-0001", headers=headers)

    assert list_response.status_code == 403
    assert detail_response.status_code == 403


def test_analysis_history_is_sorted_by_created_at_desc_then_id_desc(secured_client, rsa_keypair, db_session) -> None:
    client, _ = secured_client
    admin_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-admin-1",
        username="admin.demo",
        roles=["admin", "analyst"],
    )

    first_response = client.post(
        "/api/v1/analyses",
        headers=admin_headers,
        files={"file": ("first.txt", b"first", "text/plain")},
    )
    second_response = client.post(
        "/api/v1/analyses",
        headers=admin_headers,
        files={"file": ("second.txt", b"second", "text/plain")},
    )
    shared_timestamp = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    db_session.query(AnalysisRecordModel).filter(
        AnalysisRecordModel.id.in_(
            [first_response.json()["id"], second_response.json()["id"]],
        )
    ).update({"created_at": shared_timestamp}, synchronize_session=False)
    db_session.commit()

    response = client.get("/api/v1/analyses", headers=admin_headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"][:2]] == [
        second_response.json()["id"],
        first_response.json()["id"],
    ]


def test_admin_can_filter_analysis_history_by_owner_subject(secured_client, rsa_keypair) -> None:
    client, _ = secured_client
    analyst_one_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-1",
        username="analyst.one",
        roles=["analyst"],
    )
    analyst_two_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-2",
        username="analyst.two",
        roles=["analyst"],
    )
    admin_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-admin-1",
        username="admin.demo",
        roles=["admin", "analyst"],
    )

    first_response = client.post(
        "/api/v1/analyses",
        headers=analyst_one_headers,
        files={"file": ("first.txt", b"first", "text/plain")},
    )
    second_response = client.post(
        "/api/v1/analyses",
        headers=analyst_two_headers,
        files={"file": ("second.txt", b"second", "text/plain")},
    )
    assert first_response.status_code == 202
    assert second_response.status_code == 202

    response = client.get("/api/v1/analyses?owner=user-analyst-2", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["owner_sub"] for item in payload["items"]] == ["user-analyst-2"]


def test_status_filter_uses_visible_failed_semantics_with_rbac(secured_client, rsa_keypair, db_session) -> None:
    client, _ = secured_client
    analyst_one_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-1",
        username="analyst.one",
        roles=["analyst"],
    )
    analyst_two_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-2",
        username="analyst.two",
        roles=["analyst"],
    )
    admin_headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-admin-1",
        username="admin.demo",
        roles=["admin", "analyst"],
    )

    analyst_one_failed = client.post(
        "/api/v1/analyses",
        headers=analyst_one_headers,
        files={"file": ("scan-error-test.txt", b"scan-error", "text/plain")},
    )
    analyst_one_completed = client.post(
        "/api/v1/analyses",
        headers=analyst_one_headers,
        files={"file": ("completed-clean.txt", b"completed", "text/plain")},
    )
    analyst_two_failed = client.post(
        "/api/v1/analyses",
        headers=analyst_two_headers,
        files={"file": ("other-failed.txt", b"other-failed", "text/plain")},
    )

    assert analyst_one_failed.status_code == 202
    assert analyst_one_completed.status_code == 202
    assert analyst_two_failed.status_code == 202

    db_session.query(AnalysisRecordModel).filter_by(id=analyst_one_failed.json()["id"]).update(
        {
            "status": "completed",
            "verdict": "scan_error",
            "risk_level": "critical",
            "clamav_status": "unavailable",
            "yara_status": "clean",
            "error_message": "ClamAV non raggiungibile",
        },
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=analyst_one_completed.json()["id"]).update(
        {
            "status": "completed",
            "verdict": "clean",
            "risk_level": "low",
            "clamav_status": "clean",
            "yara_status": "clean",
        },
        synchronize_session=False,
    )
    db_session.query(AnalysisRecordModel).filter_by(id=analyst_two_failed.json()["id"]).update(
        {
            "status": "failed",
            "verdict": None,
            "risk_level": "critical",
            "error_message": "Errore worker",
        },
        synchronize_session=False,
    )
    db_session.commit()

    analyst_one_failed_response = client.get("/api/v1/analyses?status=failed", headers=analyst_one_headers)
    analyst_one_completed_response = client.get("/api/v1/analyses?status=completed", headers=analyst_one_headers)
    analyst_two_failed_response = client.get("/api/v1/analyses?status=failed", headers=analyst_two_headers)
    admin_failed_response = client.get("/api/v1/analyses?status=failed", headers=admin_headers)
    admin_owner_filtered_response = client.get(
        "/api/v1/analyses?status=failed&owner=user-analyst-1",
        headers=admin_headers,
    )

    assert analyst_one_failed_response.status_code == 200
    assert [item["id"] for item in analyst_one_failed_response.json()["items"]] == [analyst_one_failed.json()["id"]]
    assert analyst_one_failed_response.json()["total"] == 1

    assert analyst_one_completed_response.status_code == 200
    assert [item["id"] for item in analyst_one_completed_response.json()["items"]] == [
        analyst_one_completed.json()["id"]
    ]
    assert analyst_one_completed_response.json()["total"] == 1

    assert analyst_two_failed_response.status_code == 200
    assert [item["id"] for item in analyst_two_failed_response.json()["items"]] == [analyst_two_failed.json()["id"]]
    assert analyst_two_failed_response.json()["total"] == 1

    assert admin_failed_response.status_code == 200
    assert {item["id"] for item in admin_failed_response.json()["items"]} == {
        analyst_one_failed.json()["id"],
        analyst_two_failed.json()["id"],
    }
    assert admin_failed_response.json()["total"] == 2

    assert admin_owner_filtered_response.status_code == 200
    assert [item["id"] for item in admin_owner_filtered_response.json()["items"]] == [
        analyst_one_failed.json()["id"]
    ]
    assert admin_owner_filtered_response.json()["total"] == 1


@dataclass
class FakeProfileService:
    """Doppio di test del servizio profilo per validare il solo layer routing."""

    snapshot: UserProfileSnapshot
    admin_user: AdminUserSummary
    avatar_path: Path | None = None
    deleted_subjects: list[str] | None = None

    def get_profile_snapshot(self, _user):
        return self.snapshot

    def update_profile(self, _user, payload: UpdateOwnProfileRequest):
        if payload.username == "taken.user":
            raise ProfileServiceError("Esiste già un account con questo username", 409)
        if payload.email == "taken@example.com":
            raise ProfileServiceError("Esiste già un account con questa email", 409)
        if payload.email != (self.snapshot.email or ""):
            self.snapshot = self.snapshot.model_copy(
                update={
                    "first_name": payload.first_name,
                    "last_name": payload.last_name,
                    "username": payload.username,
                    "pending_email": payload.email,
                    "email_change_pending": True,
                    "email_verified": True,
                }
            )
            return self.snapshot
        self.snapshot = self.snapshot.model_copy(
            update={
                "first_name": payload.first_name,
                "last_name": payload.last_name,
                "username": payload.username,
                "email": payload.email,
            }
        )
        return self.snapshot

    def change_password(self, _user, payload: UpdateOwnPasswordRequest):
        if payload.current_password != "Current-Password-1!":
            raise ProfileServiceError("La password attuale non è corretta.")
        if payload.new_password != payload.confirm_new_password:
            raise ProfileServiceError("La conferma della nuova password non corrisponde.")
        if payload.new_password == "weak":
            raise ProfileServiceError("La nuova password non rispetta la policy configurata da Keycloak.")
        return None

    def replace_avatar(self, _user, _avatar):
        self.snapshot = self.snapshot.model_copy(update={"avatar_url": "/api/v1/me/avatar"})
        return self.snapshot

    def delete_avatar(self, _user):
        self.snapshot = self.snapshot.model_copy(update={"avatar_url": None})
        return self.snapshot

    def send_verification_email(self, _user):
        if self.snapshot.pending_email:
            return VerificationEmailResponse(detail="Email di verifica inviata correttamente al nuovo indirizzo.")
        return VerificationEmailResponse(detail="Email di verifica inviata correttamente")

    def delete_own_account(self, _user):
        if "admin" in self.snapshot.roles:
            raise ProfileServiceError(
                "Non è possibile eliminare l'ultimo amministratore attivo del sistema.",
                409,
            )
        return None

    def get_avatar_file(self, _user):
        if self.avatar_path is None:
            raise ProfileServiceError("Immagine profilo non trovata.", 404)
        return self.avatar_path, "image/png"

    def list_admin_users(self):
        return [self.admin_user]

    def update_admin_user(self, *, acting_user, subject: str, payload):
        assert acting_user.subject
        assert subject == self.admin_user.subject
        roles = [payload.role] if payload.role is not None else self.admin_user.roles
        enabled = payload.enabled if payload.enabled is not None else self.admin_user.enabled
        self.admin_user = self.admin_user.model_copy(update={"roles": roles, "enabled": enabled})
        return self.admin_user

    def update_admin_user_profile(self, *, acting_user, subject: str, payload):
        assert acting_user.subject
        assert subject == self.admin_user.subject
        if payload.username == "taken.user":
            raise ProfileServiceError("Questo username non è disponibile", 409)
        if payload.email == "taken@example.com":
            raise ProfileServiceError("Esiste già un account con questa email", 409)
        self.admin_user = self.admin_user.model_copy(
            update={
                "first_name": payload.first_name,
                "last_name": payload.last_name,
                "username": payload.username,
                "email": payload.email,
                "email_verified": False if payload.email != self.admin_user.email else self.admin_user.email_verified,
            }
        )
        return self.admin_user

    def send_admin_verification_email(self, *, subject: str):
        assert subject == self.admin_user.subject
        return VerificationEmailResponse(detail="Email di verifica inviata correttamente")

    def delete_admin_user(self, *, acting_user, subject: str):
        assert acting_user.subject
        assert subject == self.admin_user.subject
        if self.deleted_subjects is None:
            self.deleted_subjects = []
        self.deleted_subjects.append(subject)
        return None

    def get_admin_user_analyses(self, subject: str):
        assert subject == self.admin_user.subject
        return AdminUserAnalysesSnapshot(
            user=self.admin_user,
            statistics=ProfileStatistics(total_analyses=2, completed=1, queued_or_processing=1, failed=0),
            risk_distribution=[
                DashboardRiskDistributionEntry(risk_level="critical", count=0),
                DashboardRiskDistributionEntry(risk_level="high", count=1),
                DashboardRiskDistributionEntry(risk_level="medium", count=1),
                DashboardRiskDistributionEntry(risk_level="low", count=0),
            ],
            analyses=[],
        )


@pytest.fixture()
def fake_profile_service():
    """Espone un servizio profilo fittizio sovrascrivendo le dependency FastAPI."""
    snapshot = UserProfileSnapshot(
        subject="user-123",
        username="analyst.demo",
        first_name="Analista",
        last_name="Demo",
        email="analyst.demo@securescan.local",
        email_verified=True,
        pending_email=None,
        email_change_pending=False,
        email_verification_available=False,
        roles=["analyst"],
        avatar_url=None,
        statistics=ProfileStatistics(total_analyses=1, completed=1, queued_or_processing=0, failed=0),
    )
    admin_user = AdminUserSummary(
        subject="user-321",
        username="target.user",
        first_name="Target",
        last_name="User",
        email="target.user@securescan.local",
        email_verified=True,
        pending_email=None,
        email_change_pending=False,
        enabled=True,
        roles=["analyst"],
        analysis_count=2,
        avatar_data_url=None,
        created_at=None,
    )
    return FakeProfileService(snapshot=snapshot, admin_user=admin_user)


def test_profile_routes_return_and_update_snapshot(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        get_response = client.get("/api/v1/me/profile")
        put_response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "giuppy908",
                "email": "analyst.demo@securescan.local",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert get_response.status_code == 200
    assert get_response.json()["avatar_url"] is None
    assert put_response.status_code == 200
    assert put_response.json()["first_name"] == "Giuseppe"
    assert put_response.json()["username"] == "giuppy908"
    assert put_response.json()["email"] == "analyst.demo@securescan.local"


def test_profile_route_starts_pending_email_change_for_existing_verified_user(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "giuppy908",
                "email": "giuseppe@example.com",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["email"] == "analyst.demo@securescan.local"
    assert response.json()["pending_email"] == "giuseppe@example.com"
    assert response.json()["email_change_pending"] is True
    assert response.json()["email_verified"] is True


def test_profile_avatar_route_returns_image(client, fake_profile_service, tmp_path: Path) -> None:
    avatar_path = tmp_path / "avatar.png"
    avatar_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDAT\x08\x99c```\x00\x00\x00\x04\x00\x01"
        b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    fake_profile_service.avatar_path = avatar_path

    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.get("/api/v1/me/avatar")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_profile_avatar_route_disables_browser_caching(client, fake_profile_service, tmp_path: Path) -> None:
    avatar_path = tmp_path / "avatar.png"
    avatar_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDAT\x08\x99c```\x00\x00\x00\x04\x00\x01"
        b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    fake_profile_service.avatar_path = avatar_path

    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.get("/api/v1/me/avatar")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["vary"] == "Authorization"


def test_profile_route_rejects_duplicate_username(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "taken.user",
                "email": "giuseppe@example.com",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Esiste già un account con questo username"


def test_profile_route_rejects_duplicate_email(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "giuppy908",
                "email": "taken@example.com",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Esiste già un account con questa email"


def test_profile_route_rejects_role_override(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "giuppy908",
                "email": "giuseppe@example.com",
                "role": "admin",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_profile_route_rejects_invalid_username_pattern(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "bad user",
                "email": "giuseppe@example.com",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_profile_route_rejects_too_long_name(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "G" * 51,
                "last_name": "Favata",
                "username": "giuppy908",
                "email": "giuseppe@example.com",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_profile_route_rejects_invalid_email(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.put(
            "/api/v1/me/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "giuppy908",
                "email": "invalid-email",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_password_change_route_accepts_valid_payload(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.post(
            "/api/v1/me/password",
            json={
                "current_password": "Current-Password-1!",
                "new_password": "Updated-Password-1!",
                "confirm_new_password": "Updated-Password-1!",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 204


def test_resend_verification_email_route_returns_message(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.post("/api/v1/me/verification-email")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["detail"] == "Email di verifica inviata correttamente"


def test_resend_verification_email_route_supports_pending_email_change(client, fake_profile_service) -> None:
    fake_profile_service.snapshot = fake_profile_service.snapshot.model_copy(
        update={
            "pending_email": "pending@example.com",
            "email_change_pending": True,
            "email_verified": True,
        }
    )
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.post("/api/v1/me/verification-email")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["detail"] == "Email di verifica inviata correttamente al nuovo indirizzo."


def test_delete_own_account_route_returns_no_content(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.delete("/api/v1/me/profile")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 204


def test_password_change_route_rejects_wrong_current_password(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.post(
            "/api/v1/me/password",
            json={
                "current_password": "wrong-password",
                "new_password": "Updated-Password-1!",
                "confirm_new_password": "Updated-Password-1!",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "La password attuale non è corretta."


def test_password_change_route_rejects_non_compliant_password(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.post(
            "/api/v1/me/password",
            json={
                "current_password": "Current-Password-1!",
                "new_password": "weak",
                "confirm_new_password": "weak",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_password_change_route_rejects_mismatched_confirmation(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.post(
            "/api/v1/me/password",
            json={
                "current_password": "Current-Password-1!",
                "new_password": "Updated-Password-1!",
                "confirm_new_password": "Different-Password-1!",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 400
    assert response.json()["detail"] == "La conferma della nuova password non corrisponde."


def test_delete_avatar_route_returns_updated_snapshot(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_route_profile_service] = lambda: fake_profile_service
    try:
        response = client.delete("/api/v1/me/avatar")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["avatar_url"] is None


def test_admin_user_routes_are_available_for_admin_only(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_admin_profile_service] = lambda: fake_profile_service
    try:
        list_response = client.get("/api/v1/admin/users")
        detail_response = client.get("/api/v1/admin/users/user-321")
        patch_response = client.patch("/api/v1/admin/users/user-321", json={"role": "admin", "enabled": False})
        profile_patch_response = client.patch(
            "/api/v1/admin/users/user-321/profile",
            json={
                "first_name": "Giuseppe",
                "last_name": "Favata",
                "username": "giuppy908",
                "email": "giuseppe@example.com",
            },
        )
        verify_response = client.post("/api/v1/admin/users/user-321/verification-email")
        delete_response = client.delete("/api/v1/admin/users/user-321")
        analyses_response = client.get("/api/v1/admin/users/user-321/analyses")
    finally:
        client.app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    assert patch_response.status_code == 200
    assert patch_response.json()["roles"] == ["admin"]
    assert patch_response.json()["enabled"] is False
    assert profile_patch_response.status_code == 200
    assert profile_patch_response.json()["username"] == "giuppy908"
    assert profile_patch_response.json()["email_verified"] is False
    assert verify_response.status_code == 200
    assert delete_response.status_code == 204
    assert analyses_response.status_code == 200
    assert analyses_response.json()["statistics"]["total_analyses"] == 2
    assert analyses_response.json()["risk_distribution"][1]["risk_level"] == "high"


def test_admin_user_profile_route_rejects_duplicate_username(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_admin_profile_service] = lambda: fake_profile_service
    try:
        response = client.patch(
            "/api/v1/admin/users/user-321/profile",
            json={
                "first_name": "Target",
                "last_name": "User",
                "username": "taken.user",
                "email": "target.user@securescan.local",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Questo username non è disponibile"


def test_admin_user_profile_route_rejects_duplicate_email(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_admin_profile_service] = lambda: fake_profile_service
    try:
        response = client.patch(
            "/api/v1/admin/users/user-321/profile",
            json={
                "first_name": "Target",
                "last_name": "User",
                "username": "target.user",
                "email": "taken@example.com",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Esiste già un account con questa email"


def test_admin_user_profile_route_forbids_unexpected_fields(client, fake_profile_service) -> None:
    client.app.dependency_overrides[get_admin_profile_service] = lambda: fake_profile_service
    try:
        response = client.patch(
            "/api/v1/admin/users/user-321/profile",
            json={
                "first_name": "Target",
                "last_name": "User",
                "username": "target.user",
                "email": "target.user@securescan.local",
                "role": "admin",
            },
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 422


def test_analyst_cannot_access_admin_user_routes(secured_client, rsa_keypair) -> None:
    client, _ = secured_client
    headers = _build_headers(
        secured_client,
        rsa_keypair,
        subject="user-analyst-1",
        username="analyst.one",
        roles=["analyst"],
    )

    response = client.get("/api/v1/admin/users", headers=headers)

    assert response.status_code == 403


def test_last_admin_cannot_remove_own_admin_role(db_session) -> None:
    class LastAdminKeycloakClient:
        def get_user(self, subject: str):
            assert subject == "user-admin-1"
            return KeycloakUser(
                subject="user-admin-1",
                username="admin.demo",
                first_name="Admin",
                last_name="Demo",
                email="admin.demo@securescan.local",
                email_verified=True,
                enabled=True,
                roles=["admin", "analyst"],
                created_at=None,
            )

        def list_users(self):
            return [
                KeycloakUser(
                    subject="user-admin-1",
                    username="admin.demo",
                    first_name="Admin",
                    last_name="Demo",
                    email="admin.demo@securescan.local",
                    email_verified=True,
                    enabled=True,
                    roles=["admin", "analyst"],
                    created_at=None,
                )
            ]

        def update_user_access(self, **_kwargs):
            raise AssertionError("update_user_access should not be called for the last active admin")

    service = UserProfileService(
        session=db_session,
        keycloak_admin=LastAdminKeycloakClient(),
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )
    acting_user = type(
        "ActingUser",
        (),
        {"subject": "user-admin-1", "username": "admin.demo", "roles": ["admin", "analyst"]},
    )()

    with pytest.raises(ProfileServiceError) as exc_info:
        service.update_admin_user(
            acting_user=acting_user,
            subject="user-admin-1",
            payload=AdminUserUpdateRequest(role="analyst"),
        )

    assert exc_info.value.status_code == 409
    assert "ultimo amministratore attivo" in str(exc_info.value)


def test_last_admin_cannot_delete_self_account(db_session) -> None:
    class LastAdminKeycloakClient:
        def get_user(self, subject: str):
            assert subject == "user-admin-1"
            return KeycloakUser(
                subject="user-admin-1",
                username="admin.demo",
                first_name="Admin",
                last_name="Demo",
                email="admin.demo@securescan.local",
                email_verified=True,
                enabled=True,
                roles=["admin", "analyst"],
                created_at=None,
            )

        def list_users(self):
            return [
                KeycloakUser(
                    subject="user-admin-1",
                    username="admin.demo",
                    first_name="Admin",
                    last_name="Demo",
                    email="admin.demo@securescan.local",
                    email_verified=True,
                    enabled=True,
                    roles=["admin", "analyst"],
                    created_at=None,
                )
            ]

    service = UserProfileService(
        session=db_session,
        keycloak_admin=LastAdminKeycloakClient(),
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )
    acting_user = type(
        "ActingUser",
        (),
        {"subject": "user-admin-1", "username": "admin.demo", "roles": ["admin", "analyst"]},
    )()

    with pytest.raises(ProfileServiceError) as exc_info:
        service.delete_own_account(acting_user)

    assert exc_info.value.status_code == 409
    assert "ultimo amministratore attivo" in str(exc_info.value)


def test_admin_role_change_analyst_to_admin_updates_keycloak_access(db_session) -> None:
    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.update_calls: list[dict[str, object]] = []

        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="target.user",
                first_name="Target",
                last_name="User",
                email="target@example.com",
                email_verified=False,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

        def list_users(self):
            return [
                KeycloakUser(
                    subject="admin-1",
                    username="admin.demo",
                    first_name="Admin",
                    last_name="Demo",
                    email="admin@example.com",
                    email_verified=True,
                    enabled=True,
                    roles=["admin", "analyst"],
                    created_at=None,
                ),
                self.get_user("target-1"),
            ]

        def update_user_access(self, *, subject: str, role: str | None, enabled: bool | None):
            self.update_calls.append({"subject": subject, "role": role, "enabled": enabled})
            return KeycloakUser(
                subject=subject,
                username="target.user",
                first_name="Target",
                last_name="User",
                email="target@example.com",
                email_verified=False,
                enabled=True,
                roles=["admin", "analyst"],
                created_at=None,
            )

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )
    acting_user = type("AdminUser", (), {"subject": "admin-1", "username": "admin.demo", "roles": ["admin", "analyst"]})()

    updated_user = service.update_admin_user(
        acting_user=acting_user,
        subject="target-1",
        payload=AdminUserUpdateRequest(role="admin"),
    )

    assert keycloak_admin.update_calls == [{"subject": "target-1", "role": "admin", "enabled": None}]
    assert "admin" in (updated_user.roles or [])


def test_admin_role_change_admin_to_analyst_updates_keycloak_access(db_session) -> None:
    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.update_calls: list[dict[str, object]] = []

        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="target.admin",
                first_name="Target",
                last_name="Admin",
                email="target.admin@example.com",
                email_verified=True,
                enabled=True,
                roles=["admin", "analyst"],
                created_at=None,
            )

        def list_users(self):
            return [
                KeycloakUser(
                    subject="admin-1",
                    username="admin.demo",
                    first_name="Admin",
                    last_name="Demo",
                    email="admin@example.com",
                    email_verified=True,
                    enabled=True,
                    roles=["admin", "analyst"],
                    created_at=None,
                ),
                KeycloakUser(
                    subject="admin-2",
                    username="target.admin",
                    first_name="Target",
                    last_name="Admin",
                    email="target.admin@example.com",
                    email_verified=True,
                    enabled=True,
                    roles=["admin", "analyst"],
                    created_at=None,
                ),
            ]

        def update_user_access(self, *, subject: str, role: str | None, enabled: bool | None):
            self.update_calls.append({"subject": subject, "role": role, "enabled": enabled})
            return KeycloakUser(
                subject=subject,
                username="target.admin",
                first_name="Target",
                last_name="Admin",
                email="target.admin@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )
    acting_user = type("AdminUser", (), {"subject": "admin-1", "username": "admin.demo", "roles": ["admin", "analyst"]})()

    updated_user = service.update_admin_user(
        acting_user=acting_user,
        subject="admin-2",
        payload=AdminUserUpdateRequest(role="analyst"),
    )

    assert keycloak_admin.update_calls == [{"subject": "admin-2", "role": "analyst", "enabled": None}]
    assert updated_user.roles == ["analyst"]


def test_update_profile_without_email_change_updates_identity_fields(db_session) -> None:
    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.identity_updates: list[dict[str, str]] = []

        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="analyst.demo",
                first_name="Analista",
                last_name="Demo",
                email="verified@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

        def update_user_identity_fields(
            self,
            *,
            subject: str,
            username: str,
            first_name: str,
            last_name: str,
            fetch_updated_user: bool = True,
        ):
            self.identity_updates.append(
                {
                    "subject": subject,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                }
            )
            assert fetch_updated_user is True
            return KeycloakUser(
                subject=subject,
                username=username,
                first_name=first_name,
                last_name=last_name,
                email="verified@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

    service = UserProfileService(
        session=db_session,
        keycloak_admin=FakeKeycloakAdmin(),  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    snapshot = service.update_profile(
        type("User", (), {"subject": "user-123"})(),
        UpdateOwnProfileRequest(
            first_name="Giuseppe",
            last_name="Favata",
            username="giuppy908",
            email="verified@example.com",
        ),
    )

    assert snapshot.email == "verified@example.com"
    assert snapshot.pending_email is None
    assert snapshot.email_change_pending is False
    assert snapshot.username == "giuppy908"
    assert service.keycloak_admin.identity_updates == [  # type: ignore[attr-defined]
        {
            "subject": "user-123",
            "username": "giuppy908",
            "first_name": "Giuseppe",
            "last_name": "Favata",
        }
    ]


def test_update_profile_with_email_change_keeps_current_email_and_starts_pending_flow(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_verification_enabled", True)
    monkeypatch.setattr(settings, "keycloak_smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "keycloak_smtp_from", "noreply@example.com")
    monkeypatch.setattr(settings, "keycloak_smtp_auth", False)

    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.identity_updates: list[dict[str, str]] = []
            self.validated_email: str | None = None
            self.initiated_email: str | None = None
            self.identity_fetch_updated_user: bool | None = None

        def get_user(self, subject: str):
            pending = self.initiated_email
            return KeycloakUser(
                subject=subject,
                username="analyst.demo" if not self.identity_updates else self.identity_updates[-1]["username"],
                first_name="Analista" if not self.identity_updates else self.identity_updates[-1]["first_name"],
                last_name="Demo" if not self.identity_updates else self.identity_updates[-1]["last_name"],
                email="verified@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
                pending_email=pending,
            )

        def validate_pending_email_change(self, *, subject: str, new_email: str) -> None:
            assert subject == "user-123"
            self.validated_email = new_email

        def update_user_identity_fields(
            self,
            *,
            subject: str,
            username: str,
            first_name: str,
            last_name: str,
            fetch_updated_user: bool = True,
        ):
            self.identity_fetch_updated_user = fetch_updated_user
            self.identity_updates.append(
                {
                    "subject": subject,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                }
            )
            return self.get_user(subject)

        def initiate_pending_email_change(self, *, subject: str, new_email: str) -> None:
            assert subject == "user-123"
            self.initiated_email = new_email

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    snapshot = service.update_profile(
        type("User", (), {"subject": "user-123"})(),
        UpdateOwnProfileRequest(
            first_name="Giuseppe",
            last_name="Favata",
            username="giuppy908",
            email="nuova@example.com",
        ),
    )

    assert keycloak_admin.validated_email == "nuova@example.com"
    assert keycloak_admin.initiated_email == "nuova@example.com"
    assert keycloak_admin.identity_fetch_updated_user is False
    assert snapshot.email == "verified@example.com"
    assert snapshot.email_verified is True
    assert snapshot.pending_email == "nuova@example.com"
    assert snapshot.email_change_pending is True


def test_update_profile_allows_replacing_existing_pending_email(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_verification_enabled", True)
    monkeypatch.setattr(settings, "keycloak_smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "keycloak_smtp_from", "noreply@example.com")
    monkeypatch.setattr(settings, "keycloak_smtp_auth", False)

    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.initiated_email: str | None = None

        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="analyst.demo",
                first_name="Analista",
                last_name="Demo",
                email="verified@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
                pending_email=self.initiated_email or "old-pending@example.com",
            )

        def validate_pending_email_change(self, *, subject: str, new_email: str) -> None:
            assert subject == "user-123"
            assert new_email == "new-pending@example.com"

        def update_user_identity_fields(
            self,
            *,
            subject: str,
            username: str,
            first_name: str,
            last_name: str,
            fetch_updated_user: bool = True,
        ):
            assert fetch_updated_user is False
            return self.get_user(subject)

        def initiate_pending_email_change(self, *, subject: str, new_email: str) -> None:
            self.initiated_email = new_email

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    snapshot = service.update_profile(
        type("User", (), {"subject": "user-123"})(),
        UpdateOwnProfileRequest(
            first_name="Analista",
            last_name="Demo",
            username="analyst.demo",
            email="new-pending@example.com",
        ),
    )

    assert snapshot.email == "verified@example.com"
    assert snapshot.pending_email == "new-pending@example.com"
    assert snapshot.email_verified is True


def test_update_profile_rejects_duplicate_email_without_side_effects(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_verification_enabled", True)
    monkeypatch.setattr(settings, "keycloak_smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "keycloak_smtp_from", "noreply@example.com")
    monkeypatch.setattr(settings, "keycloak_smtp_auth", False)

    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.identity_update_called = False
            self.initiate_pending_email_change_called = False

        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="analyst.demo",
                first_name="Analista",
                last_name="Demo",
                email="verified@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

        def validate_pending_email_change(self, *, subject: str, new_email: str) -> None:
            assert subject == "user-123"
            assert new_email == "taken@example.com"
            raise KeycloakAdminError("Esiste già un account con questa email")

        def update_user_identity_fields(
            self,
            *,
            subject: str,
            username: str,
            first_name: str,
            last_name: str,
            fetch_updated_user: bool = True,
        ):
            self.identity_update_called = True
            return self.get_user(subject)

        def initiate_pending_email_change(self, *, subject: str, new_email: str) -> None:
            self.initiate_pending_email_change_called = True

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    with pytest.raises(ProfileServiceError, match="Esiste già un account con questa email") as exc_info:
        service.update_profile(
            type("User", (), {"subject": "user-123"})(),
            UpdateOwnProfileRequest(
                first_name="Analista",
                last_name="Demo",
                username="analyst.demo",
                email="taken@example.com",
            ),
        )

    assert exc_info.value.status_code == 409
    assert keycloak_admin.identity_update_called is False
    assert keycloak_admin.initiate_pending_email_change_called is False


def test_update_profile_rejects_email_change_when_current_email_is_not_verified(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_verification_enabled", True)
    monkeypatch.setattr(settings, "keycloak_smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "keycloak_smtp_from", "noreply@example.com")
    monkeypatch.setattr(settings, "keycloak_smtp_auth", False)

    class FakeKeycloakAdmin:
        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="pending.user",
                first_name="Pending",
                last_name="User",
                email="pending@example.com",
                email_verified=False,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

    service = UserProfileService(
        session=db_session,
        keycloak_admin=FakeKeycloakAdmin(),  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    with pytest.raises(ProfileServiceError, match="Completa prima la verifica") as exc_info:
        service.update_profile(
            type("User", (), {"subject": "user-123"})(),
            UpdateOwnProfileRequest(
                first_name="Pending",
                last_name="User",
                username="pending.user",
                email="new@example.com",
            ),
        )

    assert exc_info.value.status_code == 409


def test_send_verification_email_self_service_rejects_already_verified(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_verification_enabled", True)
    monkeypatch.setattr(settings, "keycloak_smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "keycloak_smtp_from", "noreply@example.com")
    monkeypatch.setattr(settings, "keycloak_smtp_auth", False)

    class FakeKeycloakAdmin:
        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="verified.user",
                first_name="Verified",
                last_name="User",
                email="verified@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

    service = UserProfileService(
        session=db_session,
        keycloak_admin=FakeKeycloakAdmin(),  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    with pytest.raises(ProfileServiceError, match="già verificato") as exc_info:
        service.send_verification_email(type("User", (), {"subject": "verified-1"})())

    assert exc_info.value.status_code == 409


def test_send_verification_email_self_service_resends_pending_email_change(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_verification_enabled", True)
    monkeypatch.setattr(settings, "keycloak_smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "keycloak_smtp_from", "noreply@example.com")
    monkeypatch.setattr(settings, "keycloak_smtp_auth", False)

    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.called_subject: str | None = None

        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="verified.user",
                first_name="Verified",
                last_name="User",
                email="verified@example.com",
                email_verified=True,
                enabled=True,
                roles=["analyst"],
                created_at=None,
                pending_email="pending@example.com",
            )

        def resend_pending_email_change(self, *, subject: str) -> None:
            self.called_subject = subject

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    response = service.send_verification_email(type("User", (), {"subject": "verified-1"})())

    assert response.detail == "Email di verifica inviata correttamente al nuovo indirizzo."
    assert keycloak_admin.called_subject == "verified-1"


def test_send_verification_email_admin_uses_keycloak_subject(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "email_verification_enabled", True)
    monkeypatch.setattr(settings, "keycloak_smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "keycloak_smtp_from", "noreply@example.com")
    monkeypatch.setattr(settings, "keycloak_smtp_auth", False)

    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.called_subject: str | None = None

        def get_user(self, subject: str):
            return KeycloakUser(
                subject=subject,
                username="pending.user",
                first_name="Pending",
                last_name="User",
                email="pending@example.com",
                email_verified=False,
                enabled=True,
                roles=["analyst"],
                created_at=None,
            )

        def send_verification_email(self, *, subject: str) -> None:
            self.called_subject = subject

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService("/tmp/securescan-avatar-tests"),
    )

    response = service.send_admin_verification_email(subject="pending-1")

    assert response.detail == "Email di verifica inviata correttamente"
    assert keycloak_admin.called_subject == "pending-1"


def test_keycloak_error_read_only_username_is_mapped_to_friendly_message() -> None:
    message = KeycloakAdminClient._normalize_error_message("error-user-attribute-read-only")

    assert message == "Questo username non è disponibile"


def test_keycloak_admin_maps_duplicate_email_conflict_from_custom_provider() -> None:
    error = HTTPError(
        url="http://keycloak.local/realms/securescan/securescan-account/email-change/validate",
        code=409,
        msg="Conflict",
        hdrs=None,
        fp=BytesIO(b'{"errorMessage":"Esiste gia un account con questa email"}'),
    )

    with pytest.raises(KeycloakAdminError, match="Esiste gia un account con questa email"):
        raise KeycloakAdminClient._map_http_error(error)


def test_keycloak_admin_maps_invalid_email_from_custom_provider() -> None:
    error = HTTPError(
        url="http://keycloak.local/realms/securescan/securescan-account/email-change/validate",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=BytesIO(b"{\"errorMessage\":\"L'indirizzo email non e valido\"}"),
    )

    with pytest.raises(KeycloakAdminError, match="indirizzo email non e valido"):
        raise KeycloakAdminClient._map_http_error(error)


def test_keycloak_admin_maps_forbidden_to_friendly_permission_error() -> None:
    error = HTTPError(
        url="http://keycloak.local/admin",
        code=403,
        msg="Forbidden",
        hdrs=None,
        fp=BytesIO(b""),
    )

    with pytest.raises(KeycloakAdminError, match="non dispone dei permessi necessari"):
        raise KeycloakAdminClient._map_http_error(error)


@pytest.mark.anyio
async def test_avatar_storage_rejects_invalid_mime(tmp_path: Path) -> None:
    storage = AvatarStorageService(str(tmp_path))
    uploaded_file = UploadFile(filename="avatar.txt", file=Path(__file__).open("rb"))

    with pytest.raises(AvatarValidationError):
        await storage.save_avatar(uploaded_file)


@pytest.mark.anyio
async def test_avatar_storage_generates_safe_file_name(tmp_path: Path) -> None:
    storage = AvatarStorageService(str(tmp_path))
    png_payload = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDAT\x08\x99c```\x00\x00\x00\x04\x00\x01"
        b"\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    uploaded_file = UploadFile(filename="../../avatar.png", file=Path(tmp_path / "avatar.bin").open("wb+"))
    uploaded_file.file.write(png_payload)
    uploaded_file.file.seek(0)

    stored = await storage.save_avatar(uploaded_file)

    assert Path(stored.path).parent == tmp_path
    assert ".." not in Path(stored.path).name
    assert Path(stored.path).suffix == ".png"


@pytest.mark.anyio
async def test_avatar_storage_rejects_file_over_five_megabytes(tmp_path: Path) -> None:
    storage = AvatarStorageService(str(tmp_path))
    oversized_payload = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * (5 * 1024 * 1024 + 1)
    )
    uploaded_file = UploadFile(filename="avatar.png", file=Path(tmp_path / "oversized-avatar.bin").open("wb+"))
    uploaded_file.file.write(oversized_payload)
    uploaded_file.file.seek(0)

    with pytest.raises(AvatarValidationError, match="5 MB"):
        await storage.save_avatar(uploaded_file)


def test_change_password_service_uses_current_subject_only(db_session) -> None:
    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.last_call = None

        def get_user(self, subject: str):
            return type(
                "User",
                (),
                {
                    "subject": subject,
                    "username": "analyst.demo",
                    "first_name": "Analista",
                    "last_name": "Demo",
                    "email": "analyst.demo@securescan.local",
                    "email_verified": True,
                    "roles": ["analyst"],
                },
            )()

        def update_user_password(self, *, subject: str, username: str, current_password: str, new_password: str):
            self.last_call = {
                "subject": subject,
                "username": username,
                "current_password": current_password,
                "new_password": new_password,
            }

        def logout_other_user_sessions(self, *, subject: str, current_session_id: str) -> int:
            raise AssertionError("logout_other_user_sessions should not be called in this scenario")

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService(str(Path.cwd())),
    )

    service.change_password(
        type("User", (), {"subject": "user-123", "username": "spoofed.user"})(),
        UpdateOwnPasswordRequest(
            current_password="Current-Password-1!",
            new_password="Updated-Password-1!",
            confirm_new_password="Updated-Password-1!",
            logout_other_sessions=False,
        ),
    )

    assert keycloak_admin.last_call == {
        "subject": "user-123",
        "username": "analyst.demo",
        "current_password": "Current-Password-1!",
        "new_password": "Updated-Password-1!",
    }


def test_change_password_service_logs_out_other_sessions_by_default(db_session) -> None:
    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.password_update_called = False
            self.logout_call = None

        def get_user(self, subject: str):
            return type(
                "User",
                (),
                {
                    "subject": subject,
                    "username": "analyst.demo",
                    "first_name": "Analista",
                    "last_name": "Demo",
                    "email": "analyst.demo@securescan.local",
                    "email_verified": True,
                    "roles": ["analyst"],
                },
            )()

        def update_user_password(self, *, subject: str, username: str, current_password: str, new_password: str):
            self.password_update_called = True

        def logout_other_user_sessions(self, *, subject: str, current_session_id: str) -> int:
            self.logout_call = {
                "subject": subject,
                "current_session_id": current_session_id,
            }
            return 2

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService(str(Path.cwd())),
    )

    service.change_password(
        type("User", (), {"subject": "user-123", "session_id": "current-session"})(),
        UpdateOwnPasswordRequest(
            current_password="Current-Password-1!",
            new_password="Updated-Password-1!",
            confirm_new_password="Updated-Password-1!",
        ),
    )

    assert keycloak_admin.password_update_called is True
    assert keycloak_admin.logout_call == {
        "subject": "user-123",
        "current_session_id": "current-session",
    }


def test_change_password_service_skips_session_revoke_when_disabled(db_session) -> None:
    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.password_update_called = False
            self.logout_called = False

        def get_user(self, subject: str):
            return type(
                "User",
                (),
                {
                    "subject": subject,
                    "username": "analyst.demo",
                    "first_name": "Analista",
                    "last_name": "Demo",
                    "email": "analyst.demo@securescan.local",
                    "email_verified": True,
                    "roles": ["analyst"],
                },
            )()

        def update_user_password(self, *, subject: str, username: str, current_password: str, new_password: str):
            self.password_update_called = True

        def logout_other_user_sessions(self, *, subject: str, current_session_id: str) -> int:
            self.logout_called = True
            return 0

    keycloak_admin = FakeKeycloakAdmin()
    service = UserProfileService(
        session=db_session,
        keycloak_admin=keycloak_admin,  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService(str(Path.cwd())),
    )

    service.change_password(
        type("User", (), {"subject": "user-123", "session_id": "current-session"})(),
        UpdateOwnPasswordRequest(
            current_password="Current-Password-1!",
            new_password="Updated-Password-1!",
            confirm_new_password="Updated-Password-1!",
            logout_other_sessions=False,
        ),
    )

    assert keycloak_admin.password_update_called is True
    assert keycloak_admin.logout_called is False


def test_change_password_service_does_not_revoke_sessions_when_current_password_is_wrong(db_session) -> None:
    class FakeKeycloakAdmin:
        def __init__(self) -> None:
            self.logout_called = False

        def get_user(self, subject: str):
            return type(
                "User",
                (),
                {
                    "subject": subject,
                    "username": "analyst.demo",
                    "first_name": "Analista",
                    "last_name": "Demo",
                    "email": "analyst.demo@securescan.local",
                    "email_verified": True,
                    "roles": ["analyst"],
                },
            )()

        def update_user_password(self, *, subject: str, username: str, current_password: str, new_password: str):
            raise KeycloakCredentialError("La password attuale non è corretta.")

        def logout_other_user_sessions(self, *, subject: str, current_session_id: str) -> int:
            self.logout_called = True
            return 0

    service = UserProfileService(
        session=db_session,
        keycloak_admin=FakeKeycloakAdmin(),  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService(str(Path.cwd())),
    )

    with pytest.raises(ProfileServiceError, match="La password attuale non è corretta\\."):
        service.change_password(
            type("User", (), {"subject": "user-123", "session_id": "current-session"})(),
            UpdateOwnPasswordRequest(
                current_password="wrong-password",
                new_password="Updated-Password-1!",
                confirm_new_password="Updated-Password-1!",
            ),
        )


def test_change_password_service_reports_session_revoke_failure_after_password_change(db_session) -> None:
    class FakeKeycloakAdmin:
        def get_user(self, subject: str):
            return type(
                "User",
                (),
                {
                    "subject": subject,
                    "username": "analyst.demo",
                    "first_name": "Analista",
                    "last_name": "Demo",
                    "email": "analyst.demo@securescan.local",
                    "email_verified": True,
                    "roles": ["analyst"],
                },
            )()

        def update_user_password(self, *, subject: str, username: str, current_password: str, new_password: str):
            return None

        def logout_other_user_sessions(self, *, subject: str, current_session_id: str) -> int:
            raise KeycloakAdminError("Keycloak admin request failed.")

    service = UserProfileService(
        session=db_session,
        keycloak_admin=FakeKeycloakAdmin(),  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService(str(Path.cwd())),
    )

    with pytest.raises(ProfileServiceError, match="non è stato possibile disconnettere le altre sessioni attive"):
        service.change_password(
            type("User", (), {"subject": "user-123", "session_id": "current-session"})(),
            UpdateOwnPasswordRequest(
                current_password="Current-Password-1!",
                new_password="Updated-Password-1!",
                confirm_new_password="Updated-Password-1!",
            ),
        )


def test_keycloak_password_verification_uses_dedicated_client(monkeypatch) -> None:
    captured_request = {}
    client = KeycloakAdminClient()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured_request["timeout"] = timeout
        captured_request["data"] = request.data.decode("utf-8")
        return _Response()

    monkeypatch.setattr("app.services.keycloak_admin.urlopen", fake_urlopen)
    monkeypatch.setattr(settings, "keycloak_password_verification_client_id", "securescan-password-verification")
    monkeypatch.setattr(settings, "keycloak_password_verification_client_secret", "prod-secret-value")

    client.verify_user_password(username="renamed.user", password="Current-Password-1!")

    payload = parse_qs(captured_request["data"])
    assert payload["grant_type"] == ["password"]
    assert payload["client_id"] == ["securescan-password-verification"]
    assert payload["username"] == ["renamed.user"]
    assert payload["password"] == ["Current-Password-1!"]
    assert payload["client_secret"] == ["prod-secret-value"]


def test_keycloak_password_verification_reports_invalid_client(monkeypatch) -> None:
    client = KeycloakAdminClient()

    def fake_urlopen(_request, timeout=None):
        raise HTTPError(
            url=settings.keycloak_token_url,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"unauthorized_client"}'),
        )

    monkeypatch.setattr("app.services.keycloak_admin.urlopen", fake_urlopen)

    with pytest.raises(KeycloakAdminError, match="client usato per verificare la password corrente"):
        client.verify_user_password(username="analyst.demo", password="Current-Password-1!")


def test_keycloak_password_verification_reports_wrong_password(monkeypatch) -> None:
    client = KeycloakAdminClient()

    def fake_urlopen(_request, timeout=None):
        raise HTTPError(
            url=settings.keycloak_token_url,
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid_grant","error_description":"Invalid user credentials"}'),
        )

    monkeypatch.setattr("app.services.keycloak_admin.urlopen", fake_urlopen)

    with pytest.raises(KeycloakAdminError, match="La password attuale non è corretta\\."):
        client.verify_user_password(username="analyst.demo", password="wrong-password")


def test_change_password_service_keeps_infrastructure_errors_distinct_from_wrong_password(db_session) -> None:
    class FakeKeycloakAdmin:
        def get_user(self, subject: str):
            return type(
                "User",
                (),
                {
                    "subject": subject,
                    "username": "analyst.demo",
                    "first_name": "Analista",
                    "last_name": "Demo",
                    "email": "analyst.demo@securescan.local",
                    "email_verified": True,
                    "roles": ["analyst"],
                },
            )()

        def update_user_password(self, *, subject: str, username: str, current_password: str, new_password: str):
            raise KeycloakAdminError("Il client usato per verificare la password corrente non è accettato da Keycloak.")

    service = UserProfileService(
        session=db_session,
        keycloak_admin=FakeKeycloakAdmin(),  # type: ignore[arg-type]
        avatar_storage=AvatarStorageService(str(Path.cwd())),
    )

    with pytest.raises(ProfileServiceError, match="Il client usato per verificare la password corrente non è accettato da Keycloak\\."):
        service.change_password(
            type("User", (), {"subject": "user-123"})(),
            UpdateOwnPasswordRequest(
                current_password="Current-Password-1!",
                new_password="Updated-Password-1!",
                confirm_new_password="Updated-Password-1!",
                logout_other_sessions=False,
            ),
        )


def test_keycloak_admin_lists_user_sessions(monkeypatch) -> None:
    client = KeycloakAdminClient()

    monkeypatch.setattr(
        client,
        "_request_json",
        lambda method, path, body=None, query=None: [
            {"id": "session-1", "userId": "user-123", "username": "analyst.demo"},
            {"id": "session-2", "userId": "user-123", "username": "analyst.demo"},
        ],
    )

    sessions = client.list_user_sessions(subject="user-123")

    assert sessions == [
        KeycloakUserSession(session_id="session-1", user_id="user-123", username="analyst.demo"),
        KeycloakUserSession(session_id="session-2", user_id="user-123", username="analyst.demo"),
    ]


def test_keycloak_admin_logs_out_only_other_user_sessions(monkeypatch) -> None:
    client = KeycloakAdminClient()
    deleted_sessions = []

    monkeypatch.setattr(
        client,
        "list_user_sessions",
        lambda subject: [
            KeycloakUserSession(session_id="current-session", user_id="user-123", username="analyst.demo"),
            KeycloakUserSession(session_id="other-session-1", user_id="user-123", username="analyst.demo"),
            KeycloakUserSession(session_id="other-session-2", user_id="user-123", username="analyst.demo"),
        ],
    )
    monkeypatch.setattr(
        client,
        "_request_no_content",
        lambda method, path, body=None, query=None: deleted_sessions.append((method, path)),
    )

    revoked = client.logout_other_user_sessions(subject="user-123", current_session_id="current-session")

    assert revoked == 2
    assert deleted_sessions == [
        ("DELETE", "/sessions/other-session-1"),
        ("DELETE", "/sessions/other-session-2"),
    ]


def test_keycloak_admin_logout_other_user_sessions_succeeds_when_no_other_session_exists(monkeypatch) -> None:
    client = KeycloakAdminClient()
    monkeypatch.setattr(
        client,
        "list_user_sessions",
        lambda subject: [
            KeycloakUserSession(session_id="current-session", user_id="user-123", username="analyst.demo"),
        ],
    )

    revoked = client.logout_other_user_sessions(subject="user-123", current_session_id="current-session")

    assert revoked == 0


def test_keycloak_send_verification_email_includes_redirect_parameters(monkeypatch) -> None:
    captured_request = {}
    client = KeycloakAdminClient()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured_request["url"] = request.full_url
        captured_request["body"] = request.data.decode("utf-8")
        captured_request["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("app.services.keycloak_admin.urlopen", fake_urlopen)
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    monkeypatch.setattr(settings, "keycloak_email_actions_client_id", "securescan-frontend")
    monkeypatch.setattr(settings, "keycloak_email_actions_redirect_url", "http://localhost:8080/profile")

    client.send_verification_email(subject="user-123")

    assert "client_id=securescan-frontend" in captured_request["url"]
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fprofile" in captured_request["url"]
    assert json.loads(captured_request["body"]) == ["VERIFY_EMAIL"]


def test_keycloak_validate_pending_email_change_calls_custom_realm_resource(monkeypatch) -> None:
    captured_request = {}
    client = KeycloakAdminClient()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured_request["url"] = request.full_url
        captured_request["body"] = json.loads(request.data.decode("utf-8"))
        captured_request["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("app.services.keycloak_admin.urlopen", fake_urlopen)
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    monkeypatch.setattr(settings, "keycloak_internal_url", "http://keycloak:8080")
    monkeypatch.setattr(settings, "keycloak_realm", "securescan")
    monkeypatch.setattr(settings, "keycloak_email_actions_client_id", "securescan-frontend")
    monkeypatch.setattr(settings, "keycloak_email_actions_redirect_url", "http://localhost:8080/profile")

    client.validate_pending_email_change(subject="user-123", new_email="new@example.com")

    assert captured_request["url"] == "http://keycloak:8080/realms/securescan/securescan-account/email-change/validate"
    assert captured_request["body"] == {
        "subject": "user-123",
        "newEmail": "new@example.com",
        "clientId": "securescan-frontend",
        "redirectUri": "http://localhost:8080/profile",
    }


def test_keycloak_initiate_pending_email_change_calls_custom_realm_resource(monkeypatch) -> None:
    captured_request = {}
    client = KeycloakAdminClient()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured_request["url"] = request.full_url
        captured_request["body"] = json.loads(request.data.decode("utf-8"))
        captured_request["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("app.services.keycloak_admin.urlopen", fake_urlopen)
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    monkeypatch.setattr(settings, "keycloak_internal_url", "http://keycloak:8080")
    monkeypatch.setattr(settings, "keycloak_realm", "securescan")
    monkeypatch.setattr(settings, "keycloak_email_actions_client_id", "securescan-frontend")
    monkeypatch.setattr(settings, "keycloak_email_actions_redirect_url", "http://localhost:8080/profile")

    client.initiate_pending_email_change(subject="user-123", new_email="new@example.com")

    assert captured_request["url"] == "http://keycloak:8080/realms/securescan/securescan-account/email-change"
    assert captured_request["body"] == {
        "subject": "user-123",
        "newEmail": "new@example.com",
        "clientId": "securescan-frontend",
        "redirectUri": "http://localhost:8080/profile",
    }


def test_keycloak_resend_pending_email_change_calls_custom_realm_resource(monkeypatch) -> None:
    captured_request = {}
    client = KeycloakAdminClient()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        captured_request["url"] = request.full_url
        captured_request["body"] = json.loads(request.data.decode("utf-8"))
        captured_request["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("app.services.keycloak_admin.urlopen", fake_urlopen)
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    monkeypatch.setattr(settings, "keycloak_internal_url", "http://keycloak:8080")
    monkeypatch.setattr(settings, "keycloak_realm", "securescan")
    monkeypatch.setattr(settings, "keycloak_email_actions_client_id", "securescan-frontend")
    monkeypatch.setattr(settings, "keycloak_email_actions_redirect_url", "http://localhost:8080/profile")

    client.resend_pending_email_change(subject="user-123")

    assert captured_request["url"] == "http://keycloak:8080/realms/securescan/securescan-account/email-change/resend"
    assert captured_request["body"] == {
        "subject": "user-123",
        "clientId": "securescan-frontend",
        "redirectUri": "http://localhost:8080/profile",
    }


def test_keycloak_user_mapper_reads_pending_email_attribute() -> None:
    mapped_user = KeycloakAdminClient._to_user(
        {
            "id": "user-123",
            "username": "analyst.demo",
            "firstName": "Analista",
            "lastName": "Demo",
            "email": "verified@example.com",
            "emailVerified": True,
            "enabled": True,
            "attributes": {"securescan.email.pending": ["pending@example.com"]},
        },
        ["analyst"],
    )

    assert mapped_user.email == "verified@example.com"
    assert mapped_user.email_verified is True
    assert mapped_user.pending_email == "pending@example.com"


def test_keycloak_user_mapper_falls_back_to_legacy_pending_email_attribute() -> None:
    mapped_user = KeycloakAdminClient._to_user(
        {
            "id": "user-123",
            "username": "analyst.demo",
            "firstName": "Analista",
            "lastName": "Demo",
            "email": "verified@example.com",
            "emailVerified": True,
            "enabled": True,
            "attributes": {"kc.email.pending": ["legacy-pending@example.com"]},
        },
        ["analyst"],
    )

    assert mapped_user.pending_email == "legacy-pending@example.com"
