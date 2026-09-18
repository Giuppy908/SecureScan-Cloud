"""Client backend-to-backend per Keycloak Admin REST API.

Questo servizio è il ponte tra Analysis API e Keycloak per tutte le operazioni
che il browser non deve eseguire direttamente: profilo, cambio dati utente,
amministrazione account, verifica email e alcune operazioni di sicurezza.

È usato indirettamente da Profilo, Modifica profilo, Amministrazione e
Dettaglio utente amministrativo.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings

logger = logging.getLogger(__name__)

SECURESCAN_PENDING_EMAIL_ATTRIBUTE = "securescan.email.pending"
LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE = "kc.email.pending"


class KeycloakAdminError(Exception):
    """Raised when the backend cannot complete a Keycloak admin operation."""


class KeycloakCredentialError(KeycloakAdminError):
    """Raised when the provided current password is invalid."""


@dataclass(frozen=True, slots=True)
class KeycloakUser:
    """Vista minima dell'utente Keycloak usata dal layer servizi."""

    subject: str
    username: str
    first_name: str | None
    last_name: str | None
    email: str | None
    email_verified: bool
    enabled: bool
    roles: list[str]
    created_at: datetime | None = None
    pending_email: str | None = None


@dataclass(frozen=True, slots=True)
class KeycloakUserSession:
    """Vista minima delle sessioni utente attive restituite da Keycloak."""

    session_id: str
    user_id: str | None
    username: str | None


class KeycloakAdminClient:
    """Client minimale verso Keycloak Admin API autenticato via client credentials."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        self._lock = threading.Lock()

    def get_user(self, subject: str) -> KeycloakUser:
        """Recupera un utente singolo e i ruoli realm rilevanti per l'app."""
        payload = self._request_json("GET", f"/users/{subject}")
        roles = self._list_user_roles(subject)
        return self._to_user(payload, roles)

    def list_users(self) -> list[KeycloakUser]:
        """Elenca gli utenti umani visibili all'amministrazione applicativa."""
        payload = self._request_json("GET", "/users", query={"max": "200"})
        if not isinstance(payload, list):
            raise KeycloakAdminError("Keycloak returned an invalid user list.")

        users: list[KeycloakUser] = []
        for raw_user in payload:
            if not isinstance(raw_user, dict):
                continue
            if isinstance(raw_user.get("serviceAccountClientId"), str):
                continue
            subject = raw_user.get("id")
            if not isinstance(subject, str) or not subject.strip():
                continue
            users.append(self._to_user(raw_user, self._list_user_roles(subject)))
        return users

    def update_user_profile(
        self,
        *,
        subject: str,
        username: str,
        first_name: str,
        last_name: str,
        email: str,
        allow_email_change: bool = True,
    ) -> KeycloakUser:
        """Aggiorna i campi identitari consentiti mantenendo la semantica email verified."""
        existing = self._request_json("GET", f"/users/{subject}")
        if not isinstance(existing, dict):
            raise KeycloakAdminError("Keycloak returned an invalid user payload.")

        current_email = existing.get("email")
        email_changed = isinstance(current_email, str) and current_email.strip().lower() != email.lower()
        if email_changed and not allow_email_change:
            raise KeycloakAdminError(
                "Per modificare l'indirizzo email usa il flusso dedicato di aggiornamento email."
            )
        body = {
            "id": subject,
            "username": username,
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "emailVerified": False if email_changed else bool(existing.get("emailVerified")),
            "enabled": bool(existing.get("enabled", True)),
        }
        self._request_no_content("PUT", f"/users/{subject}", body)
        return self.get_user(subject)

    def update_user_identity_fields(
        self,
        *,
        subject: str,
        username: str,
        first_name: str,
        last_name: str,
        fetch_updated_user: bool = True,
    ) -> KeycloakUser | None:
        """Aggiorna i campi profilo che non richiedono conferma email.

        Questo helper viene usato dal self-service profile quando l'utente
        cambia anche l'email: nome, cognome e username possono essere salvati
        subito, mentre l'indirizzo email passa invece dal workflow sicuro
        UPDATE_EMAIL gestito da Keycloak.
        """
        existing = self._request_json("GET", f"/users/{subject}")
        if not isinstance(existing, dict):
            raise KeycloakAdminError("Keycloak returned an invalid user payload.")

        body = {
            "id": subject,
            "username": username,
            "firstName": first_name,
            "lastName": last_name,
            "email": existing.get("email"),
            "emailVerified": bool(existing.get("emailVerified", False)),
            "enabled": bool(existing.get("enabled", True)),
        }
        if isinstance(existing.get("attributes"), dict):
            body["attributes"] = existing.get("attributes")
        self._request_no_content("PUT", f"/users/{subject}", body)
        if not fetch_updated_user:
            return None
        return self.get_user(subject)

    def verify_user_password(self, *, username: str, password: str) -> None:
        """Verifica la password corrente usando il password grant di un client dedicato."""
        try:
            self._submit_password_verification_request(username=username, password=password)
            return
        except HTTPError as exc:
            raise self._map_password_verification_error(exc) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise KeycloakAdminError("Keycloak token endpoint is unavailable.") from exc

    def update_user_password(
        self,
        *,
        subject: str,
        username: str,
        current_password: str,
        new_password: str,
    ) -> None:
        """Aggiorna la password in Keycloak dopo verifica esplicita della corrente."""
        self.verify_user_password(username=username, password=current_password)
        body = {
            "type": "password",
            "value": new_password,
            "temporary": False,
        }
        self._request_no_content("PUT", f"/users/{subject}/reset-password", body)

    def list_user_sessions(self, *, subject: str) -> list[KeycloakUserSession]:
        """Elenca le sessioni online attive associate all'utente richiesto."""
        payload = self._request_json("GET", f"/users/{subject}/sessions")
        if not isinstance(payload, list):
            raise KeycloakAdminError("Keycloak returned an invalid user session list.")

        sessions: list[KeycloakUserSession] = []
        for raw_session in payload:
            if not isinstance(raw_session, dict):
                continue
            session_id = raw_session.get("id")
            if not isinstance(session_id, str) or not session_id.strip():
                continue
            user_id = raw_session.get("userId")
            if user_id is not None and not isinstance(user_id, str):
                user_id = None
            username = raw_session.get("username")
            if username is not None and not isinstance(username, str):
                username = None
            sessions.append(
                KeycloakUserSession(
                    session_id=session_id,
                    user_id=user_id,
                    username=username,
                )
            )
        return sessions

    def logout_other_user_sessions(self, *, subject: str, current_session_id: str) -> int:
        """Termina tutte le altre sessioni online dell'utente mantenendo quella corrente."""
        revoked_sessions = 0
        for user_session in self.list_user_sessions(subject=subject):
            if user_session.user_id is not None and user_session.user_id != subject:
                continue
            if user_session.session_id == current_session_id:
                continue
            self._request_no_content("DELETE", f"/sessions/{user_session.session_id}")
            revoked_sessions += 1
        return revoked_sessions

    def update_user_access(self, *, subject: str, role: str | None, enabled: bool | None) -> KeycloakUser:
        """Aggiorna ruolo applicativo e/o stato enabled di un utente."""
        if enabled is not None:
            existing = self._request_json("GET", f"/users/{subject}")
            if not isinstance(existing, dict):
                raise KeycloakAdminError("Keycloak returned an invalid user payload.")
            body = {
                "id": subject,
                "username": existing.get("username"),
                "firstName": existing.get("firstName"),
                "lastName": existing.get("lastName"),
                "email": existing.get("email"),
                "emailVerified": bool(existing.get("emailVerified", False)),
                "enabled": enabled,
            }
            self._request_no_content("PUT", f"/users/{subject}", body)

        if role is not None:
            current_roles = self._request_json("GET", f"/users/{subject}/role-mappings/realm")
            if not isinstance(current_roles, list):
                raise KeycloakAdminError("Keycloak returned invalid role mappings.")

            managed_roles = [item for item in current_roles if isinstance(item, dict) and item.get("name") in {"analyst", "admin"}]
            if managed_roles:
                self._request_no_content("DELETE", f"/users/{subject}/role-mappings/realm", managed_roles)

            target_role = self._request_json("GET", f"/roles/{role}")
            if not isinstance(target_role, dict):
                raise KeycloakAdminError("Keycloak returned an invalid role payload.")
            self._request_no_content("POST", f"/users/{subject}/role-mappings/realm", [target_role])

        return self.get_user(subject)

    def send_verification_email(self, *, subject: str) -> None:
        """Invia l'action email VERIFY_EMAIL usando client e redirect configurati."""
        self._request_no_content(
            "PUT",
            f"/users/{subject}/execute-actions-email",
            ["VERIFY_EMAIL"],
            query={
                "client_id": settings.keycloak_email_actions_client_id,
                "redirect_uri": settings.keycloak_email_actions_redirect_url,
            },
        )

    def validate_pending_email_change(self, *, subject: str, new_email: str) -> None:
        """Fa validare a Keycloak il nuovo indirizzo prima di salvare il resto del profilo."""
        self._request_custom_no_content(
            "POST",
            "/email-change/validate",
            {
                "subject": subject,
                "newEmail": new_email,
                "clientId": settings.keycloak_email_actions_client_id,
                "redirectUri": settings.keycloak_email_actions_redirect_url,
            },
        )

    def initiate_pending_email_change(self, *, subject: str, new_email: str) -> None:
        """Avvia UPDATE_EMAIL mantenendo l'indirizzo corrente attivo fino alla conferma."""
        self._request_custom_no_content(
            "POST",
            "/email-change",
            {
                "subject": subject,
                "newEmail": new_email,
                "clientId": settings.keycloak_email_actions_client_id,
                "redirectUri": settings.keycloak_email_actions_redirect_url,
            },
        )

    def resend_pending_email_change(self, *, subject: str) -> None:
        """Richiede a Keycloak di reinviare il link per una nuova email già pending."""
        self._request_custom_no_content(
            "POST",
            "/email-change/resend",
            {
                "subject": subject,
                "clientId": settings.keycloak_email_actions_client_id,
                "redirectUri": settings.keycloak_email_actions_redirect_url,
            },
        )

    def delete_user(self, *, subject: str) -> None:
        """Elimina definitivamente un utente da Keycloak."""
        self._request_no_content("DELETE", f"/users/{subject}")

    def _list_user_roles(self, subject: str) -> list[str]:
        """Restituisce solo i ruoli realm rilevanti per RBAC applicativo."""
        payload = self._request_json("GET", f"/users/{subject}/role-mappings/realm")
        if not isinstance(payload, list):
            return []
        names = sorted(
            item.get("name")
            for item in payload
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        )
        return [name for name in names if name in {"analyst", "admin"}]

    def _request_json(
        self,
        method: str,
        path: str,
        body: Any | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        """Esegue una richiesta JSON autenticata verso Keycloak Admin API."""
        request = self._build_request(method, path, body=body, query=query)
        try:
            with urlopen(request, timeout=settings.keycloak_admin_request_timeout_seconds) as response:
                payload = response.read()
        except HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise KeycloakAdminError("Keycloak administration service is unavailable.") from exc

        if not payload:
            return None
        return json.loads(payload)

    def _request_no_content(
        self,
        method: str,
        path: str,
        body: Any | None = None,
        query: dict[str, str] | None = None,
    ) -> None:
        """Esegue una richiesta che deve concludersi senza body significativo."""
        request = self._build_request(method, path, body=body, query=query)
        try:
            with urlopen(request, timeout=settings.keycloak_admin_request_timeout_seconds):
                return
        except HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise KeycloakAdminError("Keycloak administration service is unavailable.") from exc

    def _request_custom_no_content(self, method: str, path: str, body: Any | None = None) -> None:
        """Esegue una richiesta verso il provider realm-scoped custom di Keycloak."""
        request = self._build_custom_request(method, path, body=body)
        try:
            with urlopen(request, timeout=settings.keycloak_admin_request_timeout_seconds):
                return
        except HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise KeycloakAdminError("Keycloak administration service is unavailable.") from exc

    def _build_request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        query: dict[str, str] | None = None,
    ) -> Request:
        """Costruisce una richiesta autenticata usando il bearer di servizio."""
        query_string = f"?{urlencode(query)}" if query else ""
        url = f"{settings.keycloak_admin_base_url}{path}{query_string}"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Accept": "application/json",
        }
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return Request(url, data=payload, headers=headers, method=method)

    def _build_custom_request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
    ) -> Request:
        """Costruisce una richiesta autenticata verso il provider custom del realm."""
        url = f"{settings.keycloak_internal_url.rstrip('/')}/realms/{settings.keycloak_realm}/securescan-account{path}"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Accept": "application/json",
        }
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return Request(url, data=payload, headers=headers, method=method)

    def _submit_password_verification_request(
        self,
        *,
        username: str,
        password: str,
    ) -> None:
        """Invia la richiesta password grant usata solo per validare la password corrente."""
        form_payload = {
            "grant_type": "password",
            "client_id": settings.keycloak_password_verification_client_id,
            "username": username,
            "password": password,
            "scope": "openid",
        }
        if settings.keycloak_password_verification_client_secret.strip():
            form_payload["client_secret"] = settings.keycloak_password_verification_client_secret
        payload = urlencode(form_payload).encode("utf-8")
        request = Request(
            settings.keycloak_token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=settings.keycloak_admin_request_timeout_seconds):
            return

    @classmethod
    def _map_password_verification_error(cls, error: HTTPError) -> KeycloakAdminError:
        """Distingue password errata da problemi di client/configurazione Keycloak."""
        raw_payload = cls._read_http_error_payload(error)
        normalized_payload = cls._normalize_error_message(raw_payload)
        lowered_raw_payload = raw_payload.lower()
        lowered_payload = normalized_payload.lower()
        if error.code in {400, 401} and (
            "invalid_client" in lowered_payload
            or "unauthorized_client" in lowered_payload
            or "invalid_client" in lowered_raw_payload
            or "unauthorized_client" in lowered_raw_payload
        ):
            raise KeycloakAdminError(
                "Il client usato per verificare la password corrente non è accettato da Keycloak."
            )
        if error.code == 400 and "invalid_grant" not in lowered_raw_payload:
            raise KeycloakAdminError(
                normalized_payload or "Keycloak ha rifiutato la verifica della password corrente."
            )
        if error.code in {400, 401}:
            raise KeycloakCredentialError("La password attuale non è corretta.")
        raise cls._map_http_error(error)

    def _get_access_token(self) -> str:
        """Ottiene e cache-a il token client credentials per le chiamate admin."""
        now = datetime.now(timezone.utc)
        with self._lock:
            if self._token and self._token_expires_at and now < self._token_expires_at:
                return self._token

        payload = urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": settings.keycloak_admin_client_id,
                "client_secret": settings.keycloak_admin_client_secret,
            }
        ).encode("utf-8")
        request = Request(
            settings.keycloak_token_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=settings.keycloak_admin_request_timeout_seconds) as response:
                token_payload = json.loads(response.read())
        except HTTPError as exc:
            raise self._map_http_error(exc) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise KeycloakAdminError("Keycloak token endpoint is unavailable.") from exc

        access_token = token_payload.get("access_token")
        expires_in = int(token_payload.get("expires_in", 60))
        if not isinstance(access_token, str) or not access_token:
            raise KeycloakAdminError("Keycloak did not return an access token.")

        expires_at = now + timedelta(seconds=max(expires_in - 30, 10))
        with self._lock:
            self._token = access_token
            self._token_expires_at = expires_at
        return access_token

    @staticmethod
    def _read_http_error_payload(error: HTTPError) -> str:
        try:
            return error.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _map_http_error(error: HTTPError) -> KeycloakAdminError:
        """Converte gli errori HTTP di Keycloak in messaggi applicativi più leggibili."""
        logger.warning(
            "Keycloak admin request failed.",
            extra={"status_code": error.code, "reason": error.reason},
        )
        normalized_payload = KeycloakAdminClient._normalize_error_message(
            KeycloakAdminClient._read_http_error_payload(error)
        )
        if error.code == 400:
            raise KeycloakAdminError(normalized_payload or "Richiesta Keycloak non valida.")
        if error.code == 401:
            raise KeycloakAdminError("Le credenziali del client amministrativo Keycloak sono state rifiutate.")
        if error.code == 403:
            raise KeycloakAdminError(
                "Il client amministrativo Keycloak non dispone dei permessi necessari per completare questa operazione."
            )
        if error.code == 404:
            raise KeycloakAdminError("L'utente richiesto non è stato trovato in Keycloak.")
        if error.code == 409:
            raise KeycloakAdminError(normalized_payload or "I dati utente sono in conflitto con un account esistente.")
        if error.code >= 500 and normalized_payload:
            raise KeycloakAdminError(normalized_payload)
        raise KeycloakAdminError("La richiesta amministrativa verso Keycloak non è andata a buon fine.")

    @staticmethod
    def _normalize_error_message(payload: str) -> str:
        """Normalizza gli errori grezzi Keycloak in messaggi più utili alla UI."""
        if not payload:
            return ""

        message = payload
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                candidate = parsed.get("errorMessage") or parsed.get("error_description") or parsed.get("error")
                if isinstance(candidate, str) and candidate.strip():
                    message = candidate
        except (json.JSONDecodeError, TypeError):
            message = payload

        lowered = message.lower()
        if "username" in lowered and "exist" in lowered:
            return "Esiste già un account con questo username"
        if "email" in lowered and "exist" in lowered:
            return "Esiste già un account con questa email"
        if "invalid email" in lowered or "email address is invalid" in lowered:
            return "L'indirizzo email non è valido"
        if "password policy" in lowered:
            sanitized = re.sub(r"^.*password policy:", "", message, flags=re.IGNORECASE).strip(" .")
            return f"La nuova password non rispetta la policy configurata da Keycloak: {sanitized}"
        if "password" in lowered and "policy" in lowered:
            return "La nuova password non rispetta la policy configurata da Keycloak"
        if "execute actions email" in lowered or "smtp" in lowered or "email exception" in lowered:
            return "L'invio dell'email non è disponibile. Configura correttamente il server SMTP"
        if "read-only" in lowered and "username" in lowered:
            return "Questo username non è disponibile"
        if "error-user-attribute-read-only" in lowered:
            return "Questo username non è disponibile"
        return message.strip()

    @staticmethod
    def _to_user(payload: dict[str, Any], roles: list[str]) -> KeycloakUser:
        """Mappa il payload Keycloak in una struttura locale tipizzata."""
        created_at: datetime | None = None
        raw_created_at = payload.get("createdTimestamp")
        if isinstance(raw_created_at, (int, float)):
            created_at = datetime.fromtimestamp(raw_created_at / 1000, tz=timezone.utc)
        pending_email: str | None = None
        raw_attributes = payload.get("attributes")
        if isinstance(raw_attributes, dict):
            for attribute_name in (SECURESCAN_PENDING_EMAIL_ATTRIBUTE, LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE):
                raw_pending_email = raw_attributes.get(attribute_name)
                if isinstance(raw_pending_email, list) and raw_pending_email:
                    first_pending_email = raw_pending_email[0]
                    if isinstance(first_pending_email, str) and first_pending_email.strip():
                        pending_email = first_pending_email.strip().lower()
                        break
                elif isinstance(raw_pending_email, str) and raw_pending_email.strip():
                    pending_email = raw_pending_email.strip().lower()
                    break
        return KeycloakUser(
            subject=str(payload.get("id", "")),
            username=str(payload.get("username", "")),
            first_name=payload.get("firstName") if isinstance(payload.get("firstName"), str) else None,
            last_name=payload.get("lastName") if isinstance(payload.get("lastName"), str) else None,
            email=payload.get("email") if isinstance(payload.get("email"), str) else None,
            email_verified=bool(payload.get("emailVerified", False)),
            pending_email=pending_email,
            enabled=bool(payload.get("enabled", True)),
            roles=roles,
            created_at=created_at,
        )
