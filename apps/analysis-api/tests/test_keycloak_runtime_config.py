"""Test della riallineazione runtime del realm Keycloak versionato.

Questa suite protegge la distinzione tra demo locale e configurazione runtime:
le pagine di autenticazione devono continuare a funzionare senza richiedere
modifiche manuali al realm a ogni avvio dello stack.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_runtime_config_module():
    """Carica dinamicamente lo script di runtime config senza import globale."""
    module_path = (
        Path(__file__).resolve().parents[3]
        / "infrastructure"
        / "keycloak"
        / "apply_runtime_config.py"
    )
    spec = importlib.util.spec_from_file_location("apply_runtime_config", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_compose_file(path: str) -> str:
    return (
        Path(__file__).resolve().parents[3]
        / path
    ).read_text(encoding="utf-8")


def test_required_actions_keep_update_password_non_default(monkeypatch) -> None:
    module = _load_runtime_config_module()
    calls: list[tuple[str, str, object | None]] = []
    state = {
        "VERIFY_EMAIL": {"alias": "VERIFY_EMAIL", "enabled": False, "defaultAction": True},
        "UPDATE_EMAIL": {"alias": "UPDATE_EMAIL", "enabled": False, "defaultAction": True},
        "UPDATE_PASSWORD": {"alias": "UPDATE_PASSWORD", "enabled": True, "defaultAction": True},
    }

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        calls.append((method, url, body))
        if method == "GET":
            alias = url.rsplit("/", 1)[-1]
            return dict(state[alias])
        if method == "PUT":
            alias = url.rsplit("/", 1)[-1]
            state[alias] = dict(body)
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    module._ensure_required_actions("token")

    assert state["VERIFY_EMAIL"]["enabled"] is True
    assert state["VERIFY_EMAIL"]["defaultAction"] is False
    assert state["UPDATE_EMAIL"]["enabled"] is True
    assert state["UPDATE_EMAIL"]["defaultAction"] is False
    assert state["UPDATE_PASSWORD"]["enabled"] is True
    assert state["UPDATE_PASSWORD"]["defaultAction"] is False
    assert any(call[0] == "PUT" and call[1].endswith("/VERIFY_EMAIL") for call in calls)
    assert any(call[0] == "PUT" and call[1].endswith("/UPDATE_EMAIL") for call in calls)
    assert any(call[0] == "PUT" and call[1].endswith("/UPDATE_PASSWORD") for call in calls)


def test_compose_runtime_config_service_receives_password_verification_credentials() -> None:
    compose_yaml = _read_compose_file("infrastructure/compose/compose.yaml")

    assert "keycloak-runtime-config:" in compose_yaml
    assert (
        "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID: "
        "${KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID:-securescan-password-verification}"
    ) in compose_yaml
    assert (
        "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET: "
        "${KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET:-change-me-securescan-password-verification}"
    ) in compose_yaml


def test_production_compose_runtime_config_requires_password_verification_credentials() -> None:
    compose_production_yaml = _read_compose_file("infrastructure/compose/compose.production.yaml")

    assert "keycloak-runtime-config:" in compose_production_yaml
    assert (
        "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID: "
        "${KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID:?KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID is required for production}"
    ) in compose_production_yaml
    assert (
        "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET: "
        "${KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET:?KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET is required for production}"
    ) in compose_production_yaml


def test_cleanup_legacy_update_email_required_actions_removes_only_residual_assignments_for_existing_accounts(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    users = [
        {
            "id": "user-with-pending",
            "username": "pending.user",
            "requiredActions": ["UPDATE_EMAIL", "UPDATE_PASSWORD"],
            "attributes": {"kc.email.pending": ["new@example.com"]},
            "email": "current@example.com",
            "emailVerified": True,
        },
        {
            "id": "user-with-legacy-verify-email",
            "username": "legacy.verify.user",
            "requiredActions": ["VERIFY_EMAIL", "UPDATE_PASSWORD"],
            "attributes": {"kc.email.pending": ["new@example.com"]},
            "email": "current@example.com",
            "emailVerified": False,
        },
        {
            "id": "user-without-pending",
            "username": "native-update-email",
            "requiredActions": ["UPDATE_EMAIL"],
            "attributes": {},
            "email": "current@example.com",
            "emailVerified": True,
        },
        {
            "id": "verify-email-user",
            "username": "verify.user",
            "requiredActions": ["VERIFY_EMAIL"],
            "attributes": {"kc.email.pending": ["ignored@example.com"]},
            "email": "ignored@example.com",
            "emailVerified": False,
        },
    ]

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith(f"/admin/realms/{module.KEYCLOAK_REALM}/users?max=500"):
            return users
        if method == "PUT" and "/admin/realms/" in url and "/users/" in url:
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    module._cleanup_legacy_update_email_required_actions("token")

    assert len(recorded_puts) == 2

    update_payloads = {url.rsplit("/", 1)[-1]: payload for url, payload in recorded_puts}

    payload = update_payloads["user-with-pending"]
    assert isinstance(payload, dict)
    assert payload["requiredActions"] == ["UPDATE_PASSWORD"]
    assert payload["attributes"]["securescan.email.pending"] == ["new@example.com"]
    assert "kc.email.pending" not in payload["attributes"]
    assert payload["email"] == "current@example.com"
    assert payload["emailVerified"] is True

    payload = update_payloads["user-with-legacy-verify-email"]
    assert isinstance(payload, dict)
    assert payload["requiredActions"] == ["UPDATE_PASSWORD"]
    assert payload["attributes"]["securescan.email.pending"] == ["new@example.com"]
    assert "kc.email.pending" not in payload["attributes"]
    assert payload["email"] == "current@example.com"
    assert payload["emailVerified"] is True


def test_cleanup_legacy_update_email_required_actions_skips_users_without_residual_state(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form, body
        if method == "GET" and url.endswith(f"/admin/realms/{module.KEYCLOAK_REALM}/users?max=500"):
            return [
                {
                    "id": "clean-user",
                    "requiredActions": [],
                    "attributes": {"securescan.email.pending": ["pending@example.com"]},
                },
                {
                    "id": "verify-user",
                    "requiredActions": ["VERIFY_EMAIL"],
                    "attributes": {"kc.email.pending": ["pending@example.com"]},
                    "email": "pending@example.com",
                    "emailVerified": False,
                },
                {
                    "id": "new-user-registration",
                    "requiredActions": ["VERIFY_EMAIL"],
                    "attributes": {},
                    "email": "new.user@example.com",
                    "emailVerified": False,
                },
            ]
        if method == "PUT":
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    module._cleanup_legacy_update_email_required_actions("token")

    assert recorded_puts == []


def test_apply_realm_runtime_overrides_updates_ssl_required_and_verify_email(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith(f"/admin/realms/{module.KEYCLOAK_REALM}"):
            return {
                "realm": module.KEYCLOAK_REALM,
                "verifyEmail": False,
                "sslRequired": "none",
                "smtpServer": {},
                "emailTheme": "base",
            }
        if method == "PUT" and url.endswith(f"/admin/realms/{module.KEYCLOAK_REALM}"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(module, "KEYCLOAK_SSL_REQUIRED", "external")
    monkeypatch.setattr(module, "_build_smtp_server", lambda: {"host": "smtp.example.com", "from": "noreply@example.com"})

    module._apply_realm_runtime_overrides("token")

    assert recorded_puts
    payload = recorded_puts[0][1]
    assert isinstance(payload, dict)
    assert payload["verifyEmail"] is True
    assert payload["sslRequired"] == "external"
    assert payload["emailTheme"] == "securescan"


def test_configure_frontend_client_updates_root_urls_redirects_and_origins(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith(f"/clients?clientId={module.KEYCLOAK_FRONTEND_CLIENT_ID}"):
            return [{"id": "frontend-internal-id"}]
        if method == "GET" and url.endswith("/clients/frontend-internal-id"):
            return {
                "id": "frontend-internal-id",
                "clientId": module.KEYCLOAK_FRONTEND_CLIENT_ID,
                "rootUrl": "http://localhost:8080",
                "baseUrl": "http://localhost:8080",
                "redirectUris": ["http://localhost:8080/*"],
                "webOrigins": ["http://localhost:8080"],
                "attributes": {"post.logout.redirect.uris": "http://localhost:8080/*"},
            }
        if method == "PUT" and url.endswith("/clients/frontend-internal-id"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_FRONTEND_ROOT_URL", "https://app.example.com")
    monkeypatch.setattr(module, "KEYCLOAK_FRONTEND_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(module, "KEYCLOAK_FRONTEND_REDIRECT_URIS", ["https://app.example.com/*"])
    monkeypatch.setattr(module, "KEYCLOAK_FRONTEND_WEB_ORIGINS", ["https://app.example.com"])
    monkeypatch.setattr(module, "KEYCLOAK_FRONTEND_POST_LOGOUT_REDIRECT_URIS", "https://app.example.com/*")

    module._configure_frontend_client("token")

    assert recorded_puts
    payload = recorded_puts[0][1]
    assert isinstance(payload, dict)
    assert payload["rootUrl"] == "https://app.example.com"
    assert payload["baseUrl"] == "https://app.example.com"
    assert payload["redirectUris"] == ["https://app.example.com/*"]
    assert payload["webOrigins"] == ["https://app.example.com"]
    assert payload["attributes"]["post.logout.redirect.uris"] == "https://app.example.com/*"


def test_ensure_admin_client_secret_updates_runtime_secret(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith(f"/clients?clientId={module.KEYCLOAK_ADMIN_CLIENT_ID}"):
            return [{"id": "admin-client"}]
        if method == "GET" and url.endswith("/clients/admin-client"):
            return {"id": "admin-client", "clientId": module.KEYCLOAK_ADMIN_CLIENT_ID, "secret": "change-me"}
        if method == "PUT" and url.endswith("/clients/admin-client"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_ADMIN_CLIENT_SECRET", "prod-secret-value")

    module._ensure_admin_client_secret("token")

    assert recorded_puts
    payload = recorded_puts[0][1]
    assert isinstance(payload, dict)
    assert payload["secret"] == "prod-secret-value"


def test_ensure_password_verification_client_creates_missing_confidential_client(monkeypatch) -> None:
    module = _load_runtime_config_module()
    calls: list[tuple[str, str, object | None]] = []
    created = {"done": False}

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        calls.append((method, url, body))
        if method == "GET" and url.endswith(f"/clients?clientId={module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID}"):
            if not created["done"]:
                return []
            return [{"id": "password-client"}]
        if method == "POST" and url.endswith("/clients"):
            created["done"] = True
            return None
        if method == "GET" and url.endswith("/clients/password-client"):
            return {
                "id": "password-client",
                "clientId": module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID,
                "name": "SecureScan Password Verification",
                "description": (
                    "Confidential client used by the backend to validate the current "
                    "password before authenticated password changes."
                ),
                "protocol": "openid-connect",
                "publicClient": False,
                "directAccessGrantsEnabled": True,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "serviceAccountsEnabled": False,
                "bearerOnly": False,
                "redirectUris": [],
                "webOrigins": [],
            }
        if method == "GET" and url.endswith("/clients/password-client/client-secret"):
            return {"type": "secret", "value": module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET}
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID", "securescan-password-verification")
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET", "prod-password-secret")

    module._ensure_password_verification_client("token")

    create_calls = [call for call in calls if call[0] == "POST" and call[1].endswith("/clients")]
    assert len(create_calls) == 1
    payload = create_calls[0][2]
    assert isinstance(payload, dict)
    assert payload["clientId"] == "securescan-password-verification"
    assert payload["publicClient"] is False
    assert payload["directAccessGrantsEnabled"] is True
    assert payload["secret"] == "prod-password-secret"


def test_ensure_password_verification_client_updates_existing_client(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith(f"/clients?clientId={module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID}"):
            return [{"id": "password-client"}]
        if method == "GET" and url.endswith("/clients/password-client"):
            return {
                "id": "password-client",
                "clientId": module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID,
                "name": "Wrong name",
                "description": "Wrong description",
                "protocol": "openid-connect",
                "publicClient": True,
                "directAccessGrantsEnabled": False,
                "standardFlowEnabled": True,
                "implicitFlowEnabled": True,
                "serviceAccountsEnabled": True,
                "bearerOnly": True,
                "redirectUris": ["https://wrong.example.com/*"],
                "webOrigins": ["https://wrong.example.com"],
            }
        if method == "GET" and url.endswith("/clients/password-client/client-secret"):
            return {"type": "secret", "value": "prod-password-secret"}
        if method == "PUT" and url.endswith("/clients/password-client"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID", "securescan-password-verification")
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET", "prod-password-secret")

    module._ensure_password_verification_client("token")

    assert len(recorded_puts) == 1
    payload = recorded_puts[0][1]
    assert isinstance(payload, dict)
    assert payload["name"] == "SecureScan Password Verification"
    assert payload["description"] == (
        "Confidential client used by the backend to validate the current "
        "password before authenticated password changes."
    )
    assert payload["publicClient"] is False
    assert payload["directAccessGrantsEnabled"] is True
    assert payload["standardFlowEnabled"] is False
    assert payload["implicitFlowEnabled"] is False
    assert payload["serviceAccountsEnabled"] is False
    assert payload["bearerOnly"] is False
    assert payload["redirectUris"] == []
    assert payload["webOrigins"] == []
    assert "secret" not in payload


def test_ensure_password_verification_client_keeps_fully_aligned_client_unchanged(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith(f"/clients?clientId={module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID}"):
            return [{"id": "password-client"}]
        if method == "GET" and url.endswith("/clients/password-client"):
            return {
                "id": "password-client",
                "clientId": module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID,
                "name": "SecureScan Password Verification",
                "description": (
                    "Confidential client used by the backend to validate the current "
                    "password before authenticated password changes."
                ),
                "protocol": "openid-connect",
                "publicClient": False,
                "directAccessGrantsEnabled": True,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "serviceAccountsEnabled": False,
                "bearerOnly": False,
                "redirectUris": [],
                "webOrigins": [],
            }
        if method == "GET" and url.endswith("/clients/password-client/client-secret"):
            return {"type": "secret", "value": "prod-password-secret"}
        if method == "PUT" and url.endswith("/clients/password-client"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID", "securescan-password-verification")
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET", "prod-password-secret")

    module._ensure_password_verification_client("token")

    assert recorded_puts == []


def test_ensure_password_verification_client_updates_secret_separately_when_mismatched(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith(f"/clients?clientId={module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID}"):
            return [{"id": "password-client"}]
        if method == "GET" and url.endswith("/clients/password-client"):
            return {
                "id": "password-client",
                "clientId": module.KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID,
                "name": "SecureScan Password Verification",
                "description": (
                    "Confidential client used by the backend to validate the current "
                    "password before authenticated password changes."
                ),
                "protocol": "openid-connect",
                "publicClient": False,
                "directAccessGrantsEnabled": True,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "serviceAccountsEnabled": False,
                "bearerOnly": False,
                "redirectUris": [],
                "webOrigins": [],
            }
        if method == "GET" and url.endswith("/clients/password-client/client-secret"):
            return {"type": "secret", "value": "stale-secret"}
        if method == "PUT" and url.endswith("/clients/password-client"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID", "securescan-password-verification")
    monkeypatch.setattr(module, "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET", "prod-password-secret")

    module._ensure_password_verification_client("token")

    assert len(recorded_puts) == 1
    payload = recorded_puts[0][1]
    assert isinstance(payload, dict)
    assert payload["secret"] == "prod-password-secret"
    assert payload["publicClient"] is False


def test_disable_demo_users_turns_off_seed_accounts_when_enabled(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and "users?username=analyst.demo&exact=true" in url:
            return [{"id": "analyst-id", "username": "analyst.demo", "enabled": True}]
        if method == "GET" and "users?username=admin.demo&exact=true" in url:
            return [{"id": "admin-id", "username": "admin.demo", "enabled": True}]
        if method == "PUT" and url.endswith("/users/analyst-id"):
            recorded_puts.append((url, body))
            return None
        if method == "PUT" and url.endswith("/users/admin-id"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_DISABLE_DEMO_USERS", True)

    module._disable_demo_users("token")

    assert len(recorded_puts) == 2
    assert all(isinstance(payload, dict) and payload["enabled"] is False for _, payload in recorded_puts)


def test_find_authentication_flow_alias_matches_lowercase_runtime_alias(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/flows")
        return [
            {"alias": "browser"},
            {"alias": "reset credentials"},
            {"alias": "registration"},
        ]

    monkeypatch.setattr(module, "_request", fake_request)

    assert module._find_authentication_flow_alias("token", expected_alias="reset credentials") == "reset credentials"


def test_find_authentication_flow_alias_is_case_insensitive_and_whitespace_safe(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/flows")
        return [
            {"alias": "browser"},
            {"alias": "  Reset   Credentials  "},
        ]

    monkeypatch.setattr(module, "_request", fake_request)

    assert module._find_authentication_flow_alias("token", expected_alias="reset credentials") == "  Reset   Credentials  "


def test_find_authentication_flow_alias_raises_readable_error_when_missing(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/flows")
        return [{"alias": "browser"}, {"alias": "registration"}]

    monkeypatch.setattr(module, "_request", fake_request)

    with pytest.raises(RuntimeError, match="Flow di autenticazione non trovato: reset credentials\\."):
        module._find_authentication_flow_alias("token", expected_alias="reset credentials")


def test_find_reset_email_execution_uses_runtime_alias_with_url_encoding(monkeypatch) -> None:
    module = _load_runtime_config_module()
    requested_urls: list[str] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        requested_urls.append(url)
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "reset credentials"}]
        if method == "GET" and url.endswith("/authentication/flows/reset%20credentials/executions"):
            return [
                {
                    "id": "exec-1",
                    "providerId": "reset-credential-email",
                    "displayName": "Send Reset Email",
                    "authenticationConfig": "cfg-1",
                }
            ]
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    execution = module._find_reset_email_execution("token")

    assert execution["id"] == "exec-1"
    assert any(url.endswith("/authentication/flows/reset%20credentials/executions") for url in requested_urls)


def test_find_reset_email_execution_accepts_casing_variation(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "Reset Credentials"}]
        if method == "GET" and url.endswith("/authentication/flows/Reset%20Credentials/executions"):
            return [
                {
                    "id": "exec-2",
                    "providerId": "reset-credential-email",
                    "displayName": "Send Reset Email",
                    "authenticationConfig": "cfg-2",
                }
            ]
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    assert module._find_reset_email_execution("token")["id"] == "exec-2"


def test_find_reset_email_execution_raises_readable_error_when_execution_missing(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "reset credentials"}]
        if method == "GET" and url.endswith("/authentication/flows/reset%20credentials/executions"):
            return [{"id": "other", "providerId": "auth-cookie", "displayName": "Cookie"}]
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    with pytest.raises(RuntimeError, match="Execution reset-credential-email non trovata nel flow reset credentials\\."):
        module._find_reset_email_execution("token")


def test_reset_credentials_force_login_skips_write_when_already_correct(monkeypatch) -> None:
    module = _load_runtime_config_module()
    put_calls: list[tuple[str, object | None]] = []
    post_calls: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "reset credentials"}]
        if method == "GET" and url.endswith("/authentication/flows/reset%20credentials/executions"):
            return [
                {
                    "id": "exec-1",
                    "providerId": "reset-credential-email",
                    "displayName": "Send Reset Email",
                    "authenticationConfig": "cfg-1",
                }
            ]
        if method == "GET" and url.endswith("/authentication/config/cfg-1"):
            return {"id": "cfg-1", "alias": "securescan-reset-credentials", "config": {"force-login": "true"}}
        if method == "PUT":
            put_calls.append((url, body))
            return None
        if method == "POST":
            post_calls.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_FORCE_LOGIN_AFTER_RESET", True)

    module._ensure_reset_email_force_login("token")

    assert put_calls == []
    assert post_calls == []


def test_reset_credentials_force_login_updates_existing_config(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "reset credentials"}]
        if method == "GET" and url.endswith("/authentication/flows/reset%20credentials/executions"):
            return [
                {
                    "id": "exec-1",
                    "providerId": "reset-credential-email",
                    "displayName": "Send Reset Email",
                    "authenticationConfig": "cfg-1",
                }
            ]
        if method == "GET" and url.endswith("/authentication/config/cfg-1"):
            return {"id": "cfg-1", "alias": "securescan-reset-credentials", "config": {"force-login": "false"}}
        if method == "PUT" and url.endswith("/authentication/config/cfg-1"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_FORCE_LOGIN_AFTER_RESET", True)

    module._ensure_reset_email_force_login("token")

    assert recorded_puts == [
        (
            f"{module.KEYCLOAK_INTERNAL_URL}/admin/realms/{module.KEYCLOAK_REALM}/authentication/config/cfg-1",
            {
                "id": "cfg-1",
                "alias": "securescan-reset-credentials",
                "config": {"force-login": "true"},
            },
        )
    ]


def test_reset_credentials_force_login_creates_missing_config(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_posts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "reset credentials"}]
        if method == "GET" and url.endswith("/authentication/flows/reset%20credentials/executions"):
            return [
                {
                    "id": "exec-1",
                    "providerId": "reset-credential-email",
                    "displayName": "Send Reset Email",
                    "authenticationConfig": None,
                }
            ]
        if method == "POST" and url.endswith("/authentication/executions/exec-1/config"):
            recorded_posts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)
    monkeypatch.setattr(module, "KEYCLOAK_FORCE_LOGIN_AFTER_RESET", True)

    module._ensure_reset_email_force_login("token")

    assert recorded_posts == [
        (
            f"{module.KEYCLOAK_INTERNAL_URL}/admin/realms/{module.KEYCLOAK_REALM}/authentication/executions/exec-1/config",
            {
                "alias": "securescan-reset-credentials",
                "config": {"force-login": "true"},
            },
        )
    ]


def test_find_registration_password_execution_uses_runtime_alias_with_url_encoding(monkeypatch) -> None:
    module = _load_runtime_config_module()
    requested_urls: list[str] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        requested_urls.append(url)
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "Registration"}]
        if method == "GET" and url.endswith("/authentication/flows/Registration/executions"):
            return [
                {
                    "id": "exec-registration",
                    "providerId": "registration-password-action",
                    "displayName": "Password Validation",
                    "authenticationConfig": "cfg-registration",
                }
            ]
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    flow_alias, execution = module._find_registration_password_execution("token")

    assert flow_alias == "Registration"
    assert execution["id"] == "exec-registration"
    assert any(url.endswith("/authentication/flows/Registration/executions") for url in requested_urls)


def test_find_registration_password_execution_is_case_insensitive(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "  REGISTRATION  "}]
        if method == "GET" and url.endswith("/authentication/flows/%20%20REGISTRATION%20%20/executions"):
            return [
                {
                    "id": "exec-registration",
                    "providerId": "registration-password-action",
                    "displayName": "Password Validation",
                    "authenticationConfig": "cfg-registration",
                }
            ]
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    assert module._find_registration_password_execution("token")[1]["id"] == "exec-registration"


def test_find_registration_password_execution_raises_when_missing(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "registration"}]
        if method == "GET" and url.endswith("/authentication/flows/registration/executions"):
            return [{"id": "other", "providerId": "registration-user-creation", "displayName": "Registration User Creation"}]
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    with pytest.raises(RuntimeError, match="Execution registration-password-action non trovata nel flow registration\\."):
        module._find_registration_password_execution("token")


def test_find_registration_password_config_key_uses_label_case_insensitively(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/config-description/registration-password-action")
        return {
            "name": "Password Validation",
            "providerId": "registration-password-action",
            "properties": [
                {"name": "other", "label": "Another property"},
                {
                    "name": "forcePasswordRegistration",
                    "label": "Always Set Password On Register Form",
                },
            ],
        }

    monkeypatch.setattr(module, "_request", fake_request)

    assert module._find_registration_password_config_key("token") == "forcePasswordRegistration"


def test_find_registration_password_config_key_uses_runtime_name_when_available(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/config-description/registration-password-action")
        return {
            "name": "Password Validation",
            "providerId": "registration-password-action",
            "properties": [
                {
                    "name": "always_set_password_on_register_form",
                    "label": "Another label",
                }
            ],
        }

    monkeypatch.setattr(module, "_request", fake_request)

    assert module._find_registration_password_config_key("token") == "always_set_password_on_register_form"


def test_find_registration_password_config_key_accepts_label_with_different_casing(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/config-description/registration-password-action")
        return {
            "name": "Password Validation",
            "providerId": "registration-password-action",
            "properties": [
                {
                    "name": "camelCaseName",
                    "label": "ALWAYS set PASSWORD on REGISTER form",
                }
            ],
        }

    monkeypatch.setattr(module, "_request", fake_request)

    assert module._find_registration_password_config_key("token") == "camelCaseName"


def test_find_registration_password_config_key_raises_when_response_is_not_dict(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/config-description/registration-password-action")
        return []

    monkeypatch.setattr(module, "_request", fake_request)

    with pytest.raises(
        RuntimeError,
        match="Descrizione configurazione registration-password-action non valida: atteso oggetto JSON\\.",
    ):
        module._find_registration_password_config_key("token")


def test_find_registration_password_config_key_raises_when_properties_missing(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/config-description/registration-password-action")
        return {"name": "Password Validation", "providerId": "registration-password-action"}

    monkeypatch.setattr(module, "_request", fake_request)

    with pytest.raises(
        RuntimeError,
        match="Descrizione configurazione registration-password-action priva di 'properties'\\.",
    ):
        module._find_registration_password_config_key("token")


def test_find_registration_password_config_key_raises_when_properties_is_not_list(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/config-description/registration-password-action")
        return {
            "name": "Password Validation",
            "providerId": "registration-password-action",
            "properties": {"name": "always_set_password_on_register_form"},
        }

    monkeypatch.setattr(module, "_request", fake_request)

    with pytest.raises(
        RuntimeError,
        match="Descrizione configurazione registration-password-action non valida: 'properties' deve essere una lista\\.",
    ):
        module._find_registration_password_config_key("token")


def test_find_registration_password_config_key_raises_when_missing(monkeypatch) -> None:
    module = _load_runtime_config_module()

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, body, form
        assert method == "GET"
        assert url.endswith("/authentication/config-description/registration-password-action")
        return {
            "name": "Password Validation",
            "providerId": "registration-password-action",
            "properties": [{"name": "somethingElse", "label": "Another property"}],
        }

    monkeypatch.setattr(module, "_request", fake_request)

    with pytest.raises(
        RuntimeError,
        match="Configurazione 'Always set password on register form' non trovata in registration-password-action\\.",
    ):
        module._find_registration_password_config_key("token")


def test_registration_password_persist_skips_write_when_already_correct(monkeypatch) -> None:
    module = _load_runtime_config_module()
    put_calls: list[tuple[str, object | None]] = []
    post_calls: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "registration"}]
        if method == "GET" and url.endswith("/authentication/flows/registration/executions"):
            return [
                {
                    "id": "exec-registration",
                    "providerId": "registration-password-action",
                    "displayName": "Password Validation",
                    "authenticationConfig": "cfg-registration",
                }
            ]
        if method == "GET" and url.endswith("/authentication/config-description/registration-password-action"):
            return {
                "name": "Password Validation",
                "providerId": "registration-password-action",
                "properties": [
                    {
                        "name": "forcePasswordRegistration",
                        "label": "Always set password on register form",
                    }
                ],
            }
        if method == "GET" and url.endswith("/authentication/config/cfg-registration"):
            return {
                "id": "cfg-registration",
                "alias": "securescan-registration-password",
                "config": {"forcePasswordRegistration": "true"},
            }
        if method == "PUT":
            put_calls.append((url, body))
            return None
        if method == "POST":
            post_calls.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    module._ensure_registration_password_is_persisted("token")

    assert put_calls == []
    assert post_calls == []


def test_registration_password_persist_updates_existing_config(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_puts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "registration"}]
        if method == "GET" and url.endswith("/authentication/flows/registration/executions"):
            return [
                {
                    "id": "exec-registration",
                    "providerId": "registration-password-action",
                    "displayName": "Password Validation",
                    "authenticationConfig": "cfg-registration",
                }
            ]
        if method == "GET" and url.endswith("/authentication/config-description/registration-password-action"):
            return {
                "name": "Password Validation",
                "providerId": "registration-password-action",
                "properties": [
                    {
                        "name": "forcePasswordRegistration",
                        "label": "Always set password on register form",
                    }
                ],
            }
        if method == "GET" and url.endswith("/authentication/config/cfg-registration"):
            return {
                "id": "cfg-registration",
                "alias": "securescan-registration-password",
                "config": {"forcePasswordRegistration": "false"},
            }
        if method == "PUT" and url.endswith("/authentication/config/cfg-registration"):
            recorded_puts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    module._ensure_registration_password_is_persisted("token")

    assert recorded_puts == [
        (
            f"{module.KEYCLOAK_INTERNAL_URL}/admin/realms/{module.KEYCLOAK_REALM}/authentication/config/cfg-registration",
            {
                "id": "cfg-registration",
                "alias": "securescan-registration-password",
                "config": {"forcePasswordRegistration": "true"},
            },
        )
    ]


def test_registration_password_persist_creates_missing_config(monkeypatch) -> None:
    module = _load_runtime_config_module()
    recorded_posts: list[tuple[str, object | None]] = []

    def fake_request(method: str, url: str, *, token=None, body=None, form=None):
        del token, form
        if method == "GET" and url.endswith("/authentication/flows"):
            return [{"alias": "registration"}]
        if method == "GET" and url.endswith("/authentication/flows/registration/executions"):
            return [
                {
                    "id": "exec-registration",
                    "providerId": "registration-password-action",
                    "displayName": "Password Validation",
                    "authenticationConfig": None,
                }
            ]
        if method == "GET" and url.endswith("/authentication/config-description/registration-password-action"):
            return {
                "name": "Password Validation",
                "providerId": "registration-password-action",
                "properties": [
                    {
                        "name": "forcePasswordRegistration",
                        "label": "Always set password on register form",
                    }
                ],
            }
        if method == "POST" and url.endswith("/authentication/executions/exec-registration/config"):
            recorded_posts.append((url, body))
            return None
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr(module, "_request", fake_request)

    module._ensure_registration_password_is_persisted("token")

    assert recorded_posts == [
        (
            f"{module.KEYCLOAK_INTERNAL_URL}/admin/realms/{module.KEYCLOAK_REALM}/authentication/executions/exec-registration/config",
            {
                "alias": "securescan-registration-password",
                "config": {"forcePasswordRegistration": "true"},
            },
        )
    ]
