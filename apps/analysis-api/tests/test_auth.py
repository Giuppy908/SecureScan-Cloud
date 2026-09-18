"""Test di autenticazione JWT, RBAC e audit logging.

Questi casi verificano la base di sicurezza su cui poggiano tutte le pagine
protette del sito. Se qui ci fosse una regressione, un utente potrebbe vedere
dati non suoi in Cronologia, aprire dettagli non autorizzati o accedere ad
aree amministrative senza permesso.
"""

from __future__ import annotations

import json
import logging
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from app.auth.audit import audit_logger, configure_audit_logger
from app.auth.security import KeycloakJWTVerifier, get_jwt_verifier
from app.core.config import settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import configure_database, get_engine
from app.main import create_app


def _build_jwk(public_key, kid: str) -> dict[str, str]:
    """Costruisce una JWK compatibile con PyJWT per i test di verifica firma."""
    jwk_payload = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_payload["kid"] = kid
    jwk_payload["use"] = "sig"
    jwk_payload["alg"] = "RS256"
    return jwk_payload


def _build_verifier(fetcher, *, issuer: str | None = None, audience: str | None = None) -> KeycloakJWTVerifier:
    """Crea un verificatore JWT controllabile senza dipendere da Keycloak reale."""
    return KeycloakJWTVerifier(
        issuer=issuer or settings.keycloak_issuer,
        jwks_url="http://keycloak.test/jwks",
        audience=audience or settings.keycloak_audience,
        allowed_algorithms=("RS256",),
        request_timeout_seconds=1,
        jwks_fetcher=fetcher,
    )


@pytest.fixture()
def rsa_keypair():
    """Fornisce una coppia RSA temporanea per firmare token di test."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def build_access_token(
    private_key,
    *,
    kid: str,
    issuer: str | None = None,
    audience: str | None = None,
    roles: list[str] | None = None,
    expires_delta: timedelta = timedelta(minutes=5),
    headers: dict[str, str] | None = None,
    payload_overrides: dict[str, object] | None = None,
    algorithm: str = "RS256",
):
    """Genera un access token realistico con claims modificabili per scenario."""
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "iss": issuer or settings.keycloak_issuer,
        "aud": audience or settings.keycloak_audience,
        "sub": "user-123",
        "exp": now + expires_delta,
        "iat": now,
        "nbf": now - timedelta(seconds=5),
        "typ": "Bearer",
        "preferred_username": "analyst.demo",
        "name": "Analista Demo",
        "realm_access": {"roles": roles if roles is not None else ["analyst"]},
        "jti": "token-123",
    }
    if payload_overrides:
        payload.update(payload_overrides)

    return jwt.encode(
        payload,
        private_key,
        algorithm=algorithm,
        headers={"kid": kid, **(headers or {})},
    )


@pytest.fixture()
def secured_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, dict[str, KeycloakJWTVerifier | None]]:
    """Restituisce un client con autenticazione attiva e verifier iniettato."""
    sqlite_database_url = f"sqlite+pysqlite:///{tmp_path / 'analysis-api-auth-test.db'}"
    configure_database(sqlite_database_url)
    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())

    previous_settings = {
        "auth_enabled": settings.auth_enabled,
        "upload_dir": settings.upload_dir,
        "keycloak_issuer": settings.keycloak_issuer,
        "keycloak_audience": settings.keycloak_audience,
    }
    settings.auth_enabled = True
    settings.upload_dir = str(tmp_path / "uploads")
    settings.keycloak_issuer = "http://localhost:8180/realms/securescan"
    settings.keycloak_audience = "securescan-api"
    get_jwt_verifier.cache_clear()

    verifier_holder: dict[str, KeycloakJWTVerifier | None] = {"value": None}
    monkeypatch.setattr("app.auth.security.get_jwt_verifier", lambda: verifier_holder["value"])

    with TestClient(create_app()) as client:
        yield client, verifier_holder

    settings.auth_enabled = previous_settings["auth_enabled"]
    settings.upload_dir = previous_settings["upload_dir"]
    settings.keycloak_issuer = previous_settings["keycloak_issuer"]
    settings.keycloak_audience = previous_settings["keycloak_audience"]
    get_jwt_verifier.cache_clear()
    Base.metadata.drop_all(bind=get_engine())


def test_health_is_public(secured_client) -> None:
    client, _ = secured_client

    response = client.get("/health")

    assert response.status_code == 200


def test_audit_logger_is_configured_for_info_json_output() -> None:
    logger = configure_audit_logger()

    assert logger is audit_logger
    assert logger.level == 20
    assert logger.propagate is False
    assert logger.handlers
    assert all(handler.level <= 20 for handler in logger.handlers)
    assert all(
        handler.formatter is not None and handler.formatter._fmt == "%(message)s"
        for handler in logger.handlers
    )


def test_protected_endpoint_without_token_returns_401(secured_client) -> None:
    client, _ = secured_client

    response = client.get("/api/v1/analyses", headers={"X-Request-ID": "req-missing-auth"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["X-Request-ID"] == "req-missing-auth"


def test_malformed_authorization_header_returns_401(secured_client) -> None:
    client, _ = secured_client

    response = client.get("/api/v1/analyses", headers={"Authorization": "Basic abc123"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_invalid_token_returns_401(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    _, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})

    response = client.get("/api/v1/analyses", headers={"Authorization": "Bearer invalid-token"})

    assert response.status_code == 401


def test_expired_token_returns_401(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", expires_delta=timedelta(seconds=-1))

    response = client.get("/api/v1/analyses", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_wrong_issuer_returns_401(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", issuer="http://localhost:8180/realms/other")

    response = client.get("/api/v1/analyses", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_wrong_audience_returns_401(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", audience="wrong-audience")

    response = client.get("/api/v1/analyses", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_invalid_signature_returns_401(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(other_private_key, kid="kid-1")

    response = client.get("/api/v1/analyses", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_verifier_extracts_sid_as_current_session_id(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    verifier = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(
        private_key,
        kid="kid-1",
        payload_overrides={"sid": "session-abc"},
    )

    user = verifier.verify_access_token(token)

    assert user.session_id == "session-abc"


def test_verifier_falls_back_to_session_state_when_sid_is_missing(rsa_keypair) -> None:
    private_key, public_key = rsa_keypair
    verifier = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(
        private_key,
        kid="kid-1",
        payload_overrides={"session_state": "session-legacy", "sid": None},
    )

    user = verifier.verify_access_token(token)

    assert user.session_id == "session-legacy"


def test_system_status_without_token_returns_401(secured_client) -> None:
    client, _ = secured_client

    response = client.get("/api/v1/system/status")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_analyst_can_create_and_read(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["analyst"])
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/api/v1/analyses",
        headers=headers,
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )
    list_response = client.get("/api/v1/analyses", headers=headers)

    assert create_response.status_code == 202
    assert list_response.status_code == 200


def test_analyst_can_read_system_status(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["analyst"])

    response = client.get("/api/v1/system/status", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_analyst_cannot_delete(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["analyst"])

    response = client.delete(
        "/api/v1/analyses",
        headers={"Authorization": f"Bearer {token}", "X-Request-ID": "req-analyst-delete"},
    )

    assert response.status_code == 403
    assert response.headers["X-Request-ID"] == "req-analyst-delete"


def test_user_without_roles_cannot_read_system_status(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=[])

    response = client.get("/api/v1/system/status", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_admin_can_delete(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["admin", "analyst"])
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/api/v1/analyses",
        headers=headers,
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )
    delete_response = client.delete("/api/v1/analyses", headers=headers)

    assert create_response.status_code == 202
    assert delete_response.status_code == 204


def test_admin_can_read_system_status(secured_client, rsa_keypair) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["admin", "analyst"])

    response = client.get("/api/v1/system/status", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def _parse_audit_messages(caplog) -> list[dict[str, object]]:
    """Estrae i payload JSON di audit catturati via `caplog`."""
    records: list[dict[str, object]] = []
    for record in caplog.records:
        if record.name == "app.security.audit":
            records.append(json.loads(record.message))
    return records


def _parse_audit_messages_from_stream(stream: StringIO) -> list[dict[str, object]]:
    """Estrae i payload JSON di audit da uno stream temporaneo."""
    messages: list[dict[str, object]] = []
    for line in stream.getvalue().splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            messages.append(json.loads(stripped))
    return messages


@pytest.fixture()
def audit_stream():
    """Instrada i log audit verso uno stream ispezionabile dal test."""
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(handler)
    try:
        yield stream
    finally:
        audit_logger.removeHandler(handler)
        handler.close()


def test_audit_log_records_authentication_missing_without_logging_token(
    secured_client,
    audit_stream,
) -> None:
    client, _ = secured_client
    response = client.get("/api/v1/analyses", headers={"X-Request-ID": "req-audit-missing"})

    assert response.status_code == 401
    messages = _parse_audit_messages_from_stream(audit_stream)
    assert any(message["event"] == "authentication_missing" for message in messages)
    assert all("Bearer " not in json.dumps(message) for message in messages)


def test_audit_log_records_authorization_denied_without_logging_token(
    secured_client,
    rsa_keypair,
    audit_stream,
) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["analyst"])
    response = client.delete("/api/v1/analyses", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    messages = _parse_audit_messages_from_stream(audit_stream)
    denied = next(message for message in messages if message["event"] == "authorization_denied")
    assert denied["username"] == "analyst.demo"
    assert denied["status_code"] == 403
    assert all(token not in json.dumps(message) for message in messages)


def test_audit_log_records_analysis_creation_and_deletion(
    secured_client,
    rsa_keypair,
    audit_stream,
) -> None:
    client, verifier_holder = secured_client
    private_key, public_key = rsa_keypair
    verifier_holder["value"] = _build_verifier(lambda *_: {"keys": [_build_jwk(public_key, "kid-1")]})
    token = build_access_token(private_key, kid="kid-1", roles=["admin", "analyst"])
    headers = {"Authorization": f"Bearer {token}", "X-Request-ID": "req-audit-admin"}

    create_response = client.post(
        "/api/v1/analyses",
        headers=headers,
        files={"file": ("sample.txt", b"hello", "text/plain")},
    )
    delete_response = client.delete("/api/v1/analyses", headers=headers)

    assert create_response.status_code == 202
    assert delete_response.status_code == 204
    messages = _parse_audit_messages_from_stream(audit_stream)
    create_event = next(message for message in messages if message["event"] == "analysis_created")
    delete_event = next(message for message in messages if message["event"] == "analyses_deleted")
    assert create_event["request_id"] == "req-audit-admin"
    assert create_event["username"] == "analyst.demo"
    assert create_event["status_code"] == 202
    assert delete_event["request_id"] == "req-audit-admin"
    assert delete_event["status_code"] == 204
    assert delete_event["deleted_count"] == 1
