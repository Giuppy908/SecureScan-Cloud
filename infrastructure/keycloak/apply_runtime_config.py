#!/usr/bin/env python3
"""Applica a runtime le impostazioni Keycloak che non possono restare statiche nel realm JSON.

Questo script non mostra pagine direttamente all'utente, ma influenza molti flow
reali di SecureScan Cloud:
- Accedi e logout, tramite root URL / redirect URI del client frontend;
- Registrazione e Verifica email, tramite verifyEmail e required actions;
- Password dimenticata e Reimposta password, tramite SMTP e flow di reset;
- Profilo, Modifica profilo e Amministrazione, tramite client secret e service
  account usato dal backend verso la Admin API di Keycloak.

Il realm versionato fornisce una base locale/demo importabile. Questo script la
riallinea all'ambiente reale di avvio, così la stessa repository può supportare
demo locale e futura configurazione production senza duplicare l'intero realm.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def _env(name: str, default: str = "") -> str:
    """Legge una variabile d'ambiente e la normalizza rimuovendo spazi superflui."""
    return os.getenv(name, default).strip()


def _csv_env(name: str, default: tuple[str, ...]) -> list[str]:
    """Converte variabili CSV in liste Python per redirect URI e web origins."""
    raw_value = _env(name)
    if not raw_value:
        return list(default)
    return [item.strip() for item in raw_value.split(",") if item.strip()]


KEYCLOAK_INTERNAL_URL = _env("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080").rstrip("/")
KEYCLOAK_REALM = _env("KEYCLOAK_REALM", "securescan")
KEYCLOAK_ADMIN_USERNAME = _env("KEYCLOAK_ADMIN_USERNAME", "keycloak-admin")
KEYCLOAK_ADMIN_PASSWORD = _env("KEYCLOAK_ADMIN_PASSWORD", "change-me-keycloak-admin")
KEYCLOAK_ADMIN_CLIENT_ID = _env("KEYCLOAK_ADMIN_CLIENT_ID", "securescan-admin-api")
KEYCLOAK_ADMIN_CLIENT_SECRET = _env("KEYCLOAK_ADMIN_CLIENT_SECRET", "change-me-securescan-admin-api")
KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID = _env(
    "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID",
    "securescan-password-verification",
)
KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET = _env(
    "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET",
    "change-me-securescan-password-verification",
)
EMAIL_VERIFICATION_ENABLED = _env("EMAIL_VERIFICATION_ENABLED", "false").lower() == "true"
KEYCLOAK_SSL_REQUIRED = _env("KEYCLOAK_SSL_REQUIRED", "none")
KEYCLOAK_FRONTEND_CLIENT_ID = _env("KEYCLOAK_FRONTEND_CLIENT_ID", "securescan-frontend")
KEYCLOAK_FRONTEND_ROOT_URL = _env("KEYCLOAK_FRONTEND_ROOT_URL", "http://localhost:8080")
KEYCLOAK_FRONTEND_BASE_URL = _env("KEYCLOAK_FRONTEND_BASE_URL", "http://localhost:8080")
KEYCLOAK_FRONTEND_REDIRECT_URIS = _csv_env(
    "KEYCLOAK_FRONTEND_REDIRECT_URIS",
    ("http://localhost:8080/*",),
)
KEYCLOAK_FRONTEND_WEB_ORIGINS = _csv_env(
    "KEYCLOAK_FRONTEND_WEB_ORIGINS",
    ("http://localhost:8080",),
)
KEYCLOAK_FRONTEND_POST_LOGOUT_REDIRECT_URIS = _env(
    "KEYCLOAK_FRONTEND_POST_LOGOUT_REDIRECT_URIS",
    "http://localhost:8080/*",
)
KEYCLOAK_DISABLE_DEMO_USERS = _env("KEYCLOAK_DISABLE_DEMO_USERS", "false").lower() == "true"
KEYCLOAK_SMTP_HOST = _env("KEYCLOAK_SMTP_HOST")
KEYCLOAK_SMTP_PORT = _env("KEYCLOAK_SMTP_PORT", "587")
KEYCLOAK_SMTP_FROM = _env("KEYCLOAK_SMTP_FROM")
KEYCLOAK_SMTP_FROM_DISPLAY_NAME = _env("KEYCLOAK_SMTP_FROM_DISPLAY_NAME", "SecureScan Cloud")
KEYCLOAK_SMTP_AUTH = _env("KEYCLOAK_SMTP_AUTH", "false").lower() == "true"
KEYCLOAK_SMTP_USER = _env("KEYCLOAK_SMTP_USER")
KEYCLOAK_SMTP_PASSWORD = _env("KEYCLOAK_SMTP_PASSWORD")
KEYCLOAK_SMTP_SSL = _env("KEYCLOAK_SMTP_SSL", "false").lower() == "true"
KEYCLOAK_SMTP_STARTTLS = _env("KEYCLOAK_SMTP_STARTTLS", "true").lower() == "true"
KEYCLOAK_FORCE_LOGIN_AFTER_RESET = _env("KEYCLOAK_FORCE_LOGIN_AFTER_RESET", "true").lower() == "true"
KEYCLOAK_DEMO_USERNAMES = ("analyst.demo", "admin.demo")
SECURESCAN_PENDING_EMAIL_ATTRIBUTE = "securescan.email.pending"
LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE = "kc.email.pending"


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any | None = None,
    form: dict[str, str] | None = None,
) -> Any:
    """Esegue una chiamata verso la Admin API di Keycloak.

    Tutte le modifiche runtime del realm passano da qui. In questo modo lo script
    centralizza autenticazione, serializzazione JSON e gestione del body per le
    diverse operazioni amministrative.
    """
    payload: bytes | None = None
    headers = {"Accept": "application/json"}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    if form is not None:
        payload = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=payload, headers=headers, method=method)
    with urlopen(request, timeout=10) as response:
        raw = response.read()
        if not raw:
            return None
        return json.loads(raw)


def _get_admin_token() -> str:
    """Ottiene un token amministrativo dal realm `master`.

    Questo token non viene usato dal frontend o dall'Analysis API per gli utenti
    finali: serve soltanto a permettere allo script di aggiornare il realm
    `securescan` tramite la Admin API di Keycloak.
    """
    payload = _request(
        "POST",
        f"{KEYCLOAK_INTERNAL_URL}/realms/master/protocol/openid-connect/token",
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": KEYCLOAK_ADMIN_USERNAME,
            "password": KEYCLOAK_ADMIN_PASSWORD,
        },
    )
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("Impossibile ottenere il token amministrativo di Keycloak.")
    return token


def _build_smtp_server() -> dict[str, str]:
    """Costruisce la configurazione SMTP se l'ambiente fornisce i dati necessari.

    SMTP è necessario per i flow email-based: verifica email, forgot password e
    reinvio dei messaggi di verifica. Se host o sender mancano, lo script lascia
    il blocco SMTP vuoto invece di inventare una configurazione fragile.
    """
    if not KEYCLOAK_SMTP_HOST or not KEYCLOAK_SMTP_FROM:
        return {}

    smtp_server = {
        "host": KEYCLOAK_SMTP_HOST,
        "port": KEYCLOAK_SMTP_PORT,
        "from": KEYCLOAK_SMTP_FROM,
        "fromDisplayName": KEYCLOAK_SMTP_FROM_DISPLAY_NAME,
        "auth": str(KEYCLOAK_SMTP_AUTH).lower(),
        "ssl": str(KEYCLOAK_SMTP_SSL).lower(),
        "starttls": str(KEYCLOAK_SMTP_STARTTLS).lower(),
    }
    if KEYCLOAK_SMTP_AUTH:
        if not KEYCLOAK_SMTP_USER or not KEYCLOAK_SMTP_PASSWORD:
            raise RuntimeError("SMTP auth abilitata ma credenziali mancanti.")
        smtp_server["user"] = KEYCLOAK_SMTP_USER
        smtp_server["password"] = KEYCLOAK_SMTP_PASSWORD
    return smtp_server


def _get_client_id(token: str, client_id: str) -> str:
    """Traduce un `clientId` leggibile nell'ID interno usato dalla Admin API."""
    payload = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients?clientId={client_id}",
        token=token,
    )
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"Client Keycloak non trovato: {client_id}")
    client_internal_id = payload[0].get("id")
    if not isinstance(client_internal_id, str) or not client_internal_id:
        raise RuntimeError(f"ID interno Keycloak non disponibile per il client: {client_id}")
    return client_internal_id


def _ensure_service_account_roles(token: str) -> None:
    """Garantisce i ruoli `realm-management` al service account backend.

    Questo passaggio è fondamentale per Profilo, Modifica profilo e
    Amministrazione: l'Analysis API usa il client `securescan-admin-api` per
    leggere e aggiornare utenti, ruoli ed email senza gestire direttamente
    password o credenziali degli utenti finali.
    """
    backend_client_id = _get_client_id(token, KEYCLOAK_ADMIN_CLIENT_ID)
    realm_management_client_id = _get_client_id(token, "realm-management")

    service_account_user = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{backend_client_id}/service-account-user",
        token=token,
    )
    subject = service_account_user.get("id") if isinstance(service_account_user, dict) else None
    if not isinstance(subject, str) or not subject:
        raise RuntimeError("Subject del service account Keycloak non disponibile.")

    current_roles = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/users/{subject}/role-mappings/clients/{realm_management_client_id}",
        token=token,
    )
    current_names = {
        role.get("name")
        for role in current_roles
        if isinstance(role, dict) and isinstance(role.get("name"), str)
    }
    needed_roles = ["query-users", "view-users", "manage-users", "view-realm"]
    missing_names = [name for name in needed_roles if name not in current_names]
    if not missing_names:
        return

    roles_to_add = []
    for role_name in missing_names:
        role = _request(
            "GET",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{realm_management_client_id}/roles/{role_name}",
            token=token,
        )
        if isinstance(role, dict):
            roles_to_add.append(role)

    if roles_to_add:
        _request(
            "POST",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/users/{subject}/role-mappings/clients/{realm_management_client_id}",
            token=token,
            body=roles_to_add,
        )


def _configure_frontend_client(token: str) -> None:
    """Riallinea il client browser-facing `securescan-frontend`.

    Qui vengono aggiornati root URL, base URL, redirect URI, web origins e
    post-logout redirect. Sono valori centrali per Accedi, Registrazione,
    logout, Verifica email e ritorno al frontend dopo i flow Keycloak.
    """
    frontend_client_id = _get_client_id(token, KEYCLOAK_FRONTEND_CLIENT_ID)
    client = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{frontend_client_id}",
        token=token,
    )
    if not isinstance(client, dict):
        raise RuntimeError("Configurazione client frontend Keycloak non valida.")

    attributes = dict(client.get("attributes") or {})
    desired_post_logout_redirects = KEYCLOAK_FRONTEND_POST_LOGOUT_REDIRECT_URIS
    current_post_logout_redirects = attributes.get("post.logout.redirect.uris")

    client_changed = False
    if client.get("rootUrl") != KEYCLOAK_FRONTEND_ROOT_URL:
        client["rootUrl"] = KEYCLOAK_FRONTEND_ROOT_URL
        client_changed = True
    if client.get("baseUrl") != KEYCLOAK_FRONTEND_BASE_URL:
        client["baseUrl"] = KEYCLOAK_FRONTEND_BASE_URL
        client_changed = True
    if client.get("redirectUris") != KEYCLOAK_FRONTEND_REDIRECT_URIS:
        client["redirectUris"] = KEYCLOAK_FRONTEND_REDIRECT_URIS
        client_changed = True
    if client.get("webOrigins") != KEYCLOAK_FRONTEND_WEB_ORIGINS:
        client["webOrigins"] = KEYCLOAK_FRONTEND_WEB_ORIGINS
        client_changed = True
    if current_post_logout_redirects != desired_post_logout_redirects:
        attributes["post.logout.redirect.uris"] = desired_post_logout_redirects
        client["attributes"] = attributes
        client_changed = True

    if client_changed:
        _request(
            "PUT",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{frontend_client_id}",
            token=token,
            body=client,
        )


def _ensure_admin_client_secret(token: str) -> None:
    """Allinea il secret del client confidenziale usato dal backend.

    Il realm JSON contiene un placeholder demo, ma in ambienti più seri il
    valore effettivo deve arrivare dall'environment e non restare codificato nel
    file versionato.
    """
    if not KEYCLOAK_ADMIN_CLIENT_SECRET:
        return

    admin_client_id = _get_client_id(token, KEYCLOAK_ADMIN_CLIENT_ID)
    client = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{admin_client_id}",
        token=token,
    )
    if not isinstance(client, dict):
        raise RuntimeError("Configurazione client amministrativo Keycloak non valida.")

    if client.get("secret") == KEYCLOAK_ADMIN_CLIENT_SECRET:
        return

    client["secret"] = KEYCLOAK_ADMIN_CLIENT_SECRET
    _request(
        "PUT",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{admin_client_id}",
        token=token,
        body=client,
    )


def _get_client_secret_value(token: str, client_internal_id: str) -> str:
    """Legge il secret corrente tramite l'endpoint dedicato di Keycloak.

    Il secret di un client confidenziale non viene trattato come una normale
    proprietà strutturale del client: Keycloak espone infatti una resource
    amministrativa specifica per leggerlo.
    """
    payload = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_internal_id}/client-secret",
        token=token,
    )
    secret_value = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(secret_value, str) or not secret_value:
        raise RuntimeError("Secret del client Keycloak non disponibile tramite endpoint dedicato.")
    return secret_value


def _ensure_password_verification_client(token: str) -> None:
    """Crea o riallinea il client confidenziale usato per verificare la password corrente.

    Questo client e` separato dal browser client e dal client admin: serve solo
    al backend per eseguire il password grant contro Keycloak e distinguere
    chiaramente password errata da problemi di configurazione.
    """
    desired_client = {
        "clientId": KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID,
        "name": "SecureScan Password Verification",
        "description": (
            "Confidential client used by the backend to validate the current "
            "password before authenticated password changes."
        ),
        "protocol": "openid-connect",
        "publicClient": False,
        "bearerOnly": False,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": False,
        "redirectUris": [],
        "webOrigins": [],
    }

    try:
        client_internal_id = _get_client_id(token, KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID)
    except RuntimeError as exc:
        if f"Client Keycloak non trovato: {KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID}" not in str(exc):
            raise
        _request(
            "POST",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients",
            token=token,
            body={
                **desired_client,
                "secret": KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET,
            },
        )
        client_internal_id = _get_client_id(token, KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID)

    client = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_internal_id}",
        token=token,
    )
    if not isinstance(client, dict):
        raise RuntimeError("Configurazione client Keycloak per la verifica password non valida.")

    client_changed = False
    for key, value in desired_client.items():
        if client.get(key) != value:
            client[key] = value
            client_changed = True

    if client_changed:
        _request(
            "PUT",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_internal_id}",
            token=token,
            body=client,
        )

    current_secret = _get_client_secret_value(token, client_internal_id)
    if current_secret == KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET:
        return

    client["secret"] = KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET
    _request(
        "PUT",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_internal_id}",
        token=token,
        body=client,
    )


def _disable_demo_users(token: str) -> None:
    """Disabilita gli utenti demo quando l'ambiente lo richiede.

    In locale `analyst.demo` e `admin.demo` sono utili per collaudo e demo.
    In production, invece, la repository prevede di lasciarli inattivi per
    evitare credenziali note.
    """
    if not KEYCLOAK_DISABLE_DEMO_USERS:
        return

    for username in KEYCLOAK_DEMO_USERNAMES:
        users = _request(
            "GET",
            (
                f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/users"
                f"?username={quote(username, safe='')}&exact=true"
            ),
            token=token,
        )
        if not isinstance(users, list):
            raise RuntimeError(f"Risposta utenti Keycloak non valida per {username}.")
        for user in users:
            if not isinstance(user, dict):
                continue
            if user.get("username") != username:
                continue
            if user.get("enabled") is False:
                continue
            user_id = user.get("id")
            if not isinstance(user_id, str) or not user_id:
                raise RuntimeError(f"ID utente Keycloak non disponibile per {username}.")
            updated_user = dict(user)
            updated_user["enabled"] = False
            _request(
                "PUT",
                f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
                token=token,
                body=updated_user,
            )


def _ensure_required_action(
    token: str,
    *,
    alias: str,
    enabled: bool,
    default_action: bool,
) -> None:
    """Aggiorna una required action del realm senza alterarne altre proprietà.

    Le required actions sono passaggi che Keycloak può imporre all'utente in un
    certo flow, per esempio verifica email o aggiornamento password.
    """
    action = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/required-actions/{alias}",
        token=token,
    )
    if not isinstance(action, dict):
        raise RuntimeError(f"Configurazione required action non valida per {alias}.")

    if action.get("enabled") == enabled and action.get("defaultAction") == default_action:
        return

    action["enabled"] = enabled
    action["defaultAction"] = default_action

    _request(
        "PUT",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/required-actions/{alias}",
        token=token,
        body=action,
    )


def _ensure_required_actions(token: str) -> None:
    # VERIFY_EMAIL deve esistere perché viene usata dai flow di registrazione e
    # verifica email. UPDATE_EMAIL abilita il cambio indirizzo nativo di
    # Keycloak, mantenendo l'email precedente valida fino alla conferma della
    # nuova. UPDATE_PASSWORD deve restare disponibile, ma non deve comparire
    # automaticamente come obbligo generico nella registrazione standard.
    _ensure_required_action(token, alias="VERIFY_EMAIL", enabled=True, default_action=False)
    _ensure_required_action(token, alias="UPDATE_EMAIL", enabled=True, default_action=False)
    _ensure_required_action(token, alias="UPDATE_PASSWORD", enabled=True, default_action=False)


def _cleanup_legacy_update_email_required_actions(token: str) -> None:
    """Migra il vecchio pending email Keycloak verso lo stato custom SecureScan.

    Keycloak 26.7.0 usa `UserModel.EMAIL_PENDING` / `kc.email.pending` come
    trigger del required action nativo UPDATE_EMAIL durante il login.
    Lasciare quel campo persistente su un account esistente significa quindi
    rientrare nel form "Aggiorna email" a ogni nuova autenticazione.

    SecureScan deve invece mantenere il login libero durante il pending state.
    Per questo il pending email persistente viene spostato su un attributo
    separato, `securescan.email.pending`, che il login nativo di Keycloak non
    interpreta come required action.

    La migrazione interviene solo quando riconosce il nostro vecchio flow:
    - esiste una pending email legacy `kc.email.pending`;
    - esiste una email attiva diversa dalla pending email.

    In quel caso:
    - copia la pending email nel nuovo attributo SecureScan;
    - rimuove la pending email legacy nativa di Keycloak;
    - rimuove eventuali residui `UPDATE_EMAIL` e `VERIFY_EMAIL`;
    - ripristina `emailVerified=true` solo per la vecchia email già attiva.

    Non tocca invece i nuovi utenti non verificati: in registrazione la email
    attiva coincide con quella da verificare, quindi manca la discriminante
    "email attiva diversa dalla pending".
    """
    users = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/users?max=500",
        token=token,
    )
    if not isinstance(users, list):
        raise RuntimeError("Lista utenti Keycloak non valida durante la pulizia UPDATE_EMAIL.")

    for user in users:
        if not isinstance(user, dict):
            continue

        subject = user.get("id")
        if not isinstance(subject, str) or not subject:
            continue

        required_actions = user.get("requiredActions")
        if not isinstance(required_actions, list):
            continue

        attributes = user.get("attributes")
        pending_email = None
        secure_pending_email = None
        if isinstance(attributes, dict):
            raw_secure_pending = attributes.get(SECURESCAN_PENDING_EMAIL_ATTRIBUTE)
            if isinstance(raw_secure_pending, list) and raw_secure_pending:
                candidate = raw_secure_pending[0]
                if isinstance(candidate, str) and candidate.strip():
                    secure_pending_email = candidate.strip()
            elif isinstance(raw_secure_pending, str) and raw_secure_pending.strip():
                secure_pending_email = raw_secure_pending.strip()

            raw_pending = attributes.get(LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE)
            if isinstance(raw_pending, list) and raw_pending:
                candidate = raw_pending[0]
                if isinstance(candidate, str) and candidate.strip():
                    pending_email = candidate.strip()
            elif isinstance(raw_pending, str) and raw_pending.strip():
                    pending_email = raw_pending.strip()

        current_email = user.get("email")
        normalized_current_email = current_email.strip().lower() if isinstance(current_email, str) and current_email.strip() else None
        normalized_pending_email = pending_email.strip().lower() if pending_email else None
        normalized_secure_pending_email = secure_pending_email.strip().lower() if secure_pending_email else None

        if normalized_pending_email is None and normalized_secure_pending_email is None:
            continue

        # Questa è la discriminante chiave per evitare falsi positivi sui nuovi
        # utenti: se la email attiva differisce dalla pending email, allora la
        # email corrente rappresenta l'indirizzo già valido dell'account
        # esistente e i residui VERIFY/verified=false vanno ripuliti.
        has_verified_current_email_with_pending_change = (
            normalized_current_email is not None
            and normalized_pending_email is not None
            and normalized_current_email != normalized_pending_email
        )

        next_required_actions = [action for action in required_actions if action != "UPDATE_EMAIL"]
        if has_verified_current_email_with_pending_change or normalized_secure_pending_email is not None:
            next_required_actions = [action for action in next_required_actions if action != "VERIFY_EMAIL"]

        should_restore_email_verified = (
            (has_verified_current_email_with_pending_change or normalized_secure_pending_email is not None)
            and user.get("emailVerified") is False
        )
        required_actions_changed = next_required_actions != required_actions
        should_migrate_pending_email = has_verified_current_email_with_pending_change
        should_remove_legacy_pending_email = pending_email is not None and (
            has_verified_current_email_with_pending_change or normalized_secure_pending_email is not None
        )

        attributes_changed = False
        if isinstance(attributes, dict):
            next_attributes = dict(attributes)
            if should_migrate_pending_email:
                next_attributes[SECURESCAN_PENDING_EMAIL_ATTRIBUTE] = [pending_email]
                attributes_changed = True
            if should_remove_legacy_pending_email and LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE in next_attributes:
                next_attributes.pop(LEGACY_KEYCLOAK_PENDING_EMAIL_ATTRIBUTE, None)
                attributes_changed = True
            if next_attributes:
                attributes = next_attributes
            else:
                attributes = {}

        if not required_actions_changed and not should_restore_email_verified and not attributes_changed:
            continue

        user["requiredActions"] = next_required_actions
        if should_restore_email_verified:
            user["emailVerified"] = True
        user["attributes"] = attributes
        _request(
            "PUT",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/users/{quote(subject)}",
            token=token,
            body=user,
        )


def _normalize_flow_alias(alias: str) -> str:
    """Normalizza gli alias dei flow per confronti robusti lato script."""
    return " ".join(alias.split()).strip().lower()


def _find_authentication_flow_alias(token: str, *, expected_alias: str) -> str:
    """Recupera il nome effettivo di un flow anche se Keycloak varia gli spazi."""
    flows = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/flows",
        token=token,
    )
    if not isinstance(flows, list):
        raise RuntimeError("Lista dei flow di autenticazione non valida.")

    normalized_expected = _normalize_flow_alias(expected_alias)
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        alias = flow.get("alias")
        if isinstance(alias, str) and _normalize_flow_alias(alias) == normalized_expected:
            return alias

    raise RuntimeError(f"Flow di autenticazione non trovato: {expected_alias}.")


def _find_flow_execution(
    token: str,
    *,
    flow_alias: str,
    provider_id: str,
    display_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Cerca un'esecuzione interna dentro un flow di autenticazione.

    Serve quando dobbiamo aggiornare un singolo passaggio del flow, ad esempio
    l'invio email del reset password o la validazione password in registrazione.
    """
    encoded_flow_alias = quote(flow_alias, safe="")
    executions = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/flows/{encoded_flow_alias}/executions",
        token=token,
    )
    if not isinstance(executions, list):
        raise RuntimeError(f"Esecuzioni del flow {flow_alias} non valide.")

    normalized_display_names = {name.strip().lower() for name in display_names if name.strip()}
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        current_provider_id = execution.get("providerId")
        display_name = execution.get("displayName")
        normalized_display_name = display_name.strip().lower() if isinstance(display_name, str) else ""
        if current_provider_id == provider_id or normalized_display_name in normalized_display_names:
            return execution

    raise RuntimeError(f"Execution {provider_id} non trovata nel flow {flow_alias}.")


def _find_reset_email_execution(token: str) -> dict[str, Any]:
    """Individua il passaggio del flow che invia l'email di reset credenziali."""
    flow_alias = _find_authentication_flow_alias(token, expected_alias="reset credentials")
    return _find_flow_execution(
        token,
        flow_alias=flow_alias,
        provider_id="reset-credential-email",
        display_names=("Send Reset Email",),
    )


def _ensure_reset_email_force_login(token: str) -> None:
    """Configura il comportamento post-reset del flow credenziali.

    Questo valore decide se, dopo il reset password via email, Keycloak debba
    richiedere un nuovo login esplicito. Il comportamento influisce direttamente
    sul percorso Password dimenticata -> Reimposta password -> ritorno ad Accedi.
    """
    execution = _find_reset_email_execution(token)
    execution_id = execution.get("id")
    if not isinstance(execution_id, str) or not execution_id:
        raise RuntimeError("ID dell'execution Send Reset Email non disponibile.")

    config_id = execution.get("authenticationConfig")
    desired_value = "true" if KEYCLOAK_FORCE_LOGIN_AFTER_RESET else "false"

    if isinstance(config_id, str) and config_id:
        config = _request(
            "GET",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/config/{config_id}",
            token=token,
        )
        if not isinstance(config, dict):
            raise RuntimeError("Configurazione del flow Reset Credentials non valida.")
        config_map = config.setdefault("config", {})
        if isinstance(config_map, dict) and config_map.get("force-login") == desired_value:
            return
        config["config"] = {"force-login": desired_value}
        _request(
            "PUT",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/config/{config_id}",
            token=token,
            body=config,
        )
        return

    _request(
        "POST",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/executions/{execution_id}/config",
        token=token,
        body={
            "alias": "securescan-reset-credentials",
            "config": {"force-login": desired_value},
        },
    )


def _find_registration_password_execution(token: str) -> tuple[str, dict[str, Any]]:
    """Recupera il passaggio che valida e persiste la password in registrazione."""
    flow_alias = _find_authentication_flow_alias(token, expected_alias="registration")
    execution = _find_flow_execution(
        token,
        flow_alias=flow_alias,
        provider_id="registration-password-action",
        display_names=("Password Validation",),
    )
    return flow_alias, execution


def _find_registration_password_config_key(token: str) -> str:
    """Ricava la chiave di configurazione usata dalla versione corrente di Keycloak.

    Lo script evita di assumere nomi hardcoded se il provider espone già una
    descrizione ufficiale della configurazione disponibile.
    """
    description = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/config-description/registration-password-action",
        token=token,
    )
    if not isinstance(description, dict):
        raise RuntimeError("Descrizione configurazione registration-password-action non valida: atteso oggetto JSON.")

    properties = description.get("properties")
    if properties is None:
        raise RuntimeError("Descrizione configurazione registration-password-action priva di 'properties'.")
    if not isinstance(properties, list):
        raise RuntimeError("Descrizione configurazione registration-password-action non valida: 'properties' deve essere una lista.")

    expected_name = "always_set_password_on_register_form"
    expected_label = "always set password on register form"
    for property_definition in properties:
        if not isinstance(property_definition, dict):
            continue
        name = property_definition.get("name")
        label = property_definition.get("label")
        normalized_name = name.strip().lower() if isinstance(name, str) else ""
        normalized_label = label.strip().lower() if isinstance(label, str) else ""
        if normalized_name == expected_name and isinstance(name, str) and name.strip():
            return name.strip()
        if normalized_label == expected_label and isinstance(name, str) and name.strip():
            return name.strip()

    raise RuntimeError(
        "Configurazione 'Always set password on register form' non trovata in registration-password-action."
    )


def _ensure_registration_password_is_persisted(token: str) -> None:
    """Garantisce che la password inserita in registrazione venga davvero salvata.

    Questo protegge il flow Registrazione del frontend custom, che mostra
    direttamente i campi password e si aspetta che il backend di Keycloak li
    consideri parte valida del processo di creazione account.
    """
    _, execution = _find_registration_password_execution(token)
    execution_id = execution.get("id")
    if not isinstance(execution_id, str) or not execution_id:
        raise RuntimeError("ID dell'execution Password Validation non disponibile.")

    config_key = _find_registration_password_config_key(token)
    desired_value = "true"
    config_id = execution.get("authenticationConfig")

    if isinstance(config_id, str) and config_id:
        config = _request(
            "GET",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/config/{config_id}",
            token=token,
        )
        if not isinstance(config, dict):
            raise RuntimeError("Configurazione del flow Registration non valida.")

        config_map = config.setdefault("config", {})
        if isinstance(config_map, dict) and config_map.get(config_key) == desired_value:
            return
        existing_config = dict(config_map) if isinstance(config_map, dict) else {}
        config["config"] = {
            **existing_config,
            config_key: desired_value,
        }
        _request(
            "PUT",
            f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/config/{config_id}",
            token=token,
            body=config,
        )
        return

    _request(
        "POST",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}/authentication/executions/{execution_id}/config",
        token=token,
        body={
            "alias": "securescan-registration-password",
            "config": {config_key: desired_value},
        },
    )


def _apply_realm_runtime_overrides(token: str) -> None:
    """Applica le override di realm che dipendono dall'ambiente reale.

    Il realm statico locale usa valori semplici per la demo. Qui vengono invece
    riallineati SSL requirement, verifica email e SMTP in base alle variabili di
    avvio dello stack.
    """
    realm = _request(
        "GET",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}",
        token=token,
    )
    if not isinstance(realm, dict):
        raise RuntimeError("Keycloak ha restituito una configurazione realm non valida.")

    smtp_server = _build_smtp_server()
    email_verification_active = EMAIL_VERIFICATION_ENABLED and bool(smtp_server)
    realm["verifyEmail"] = email_verification_active
    realm["sslRequired"] = KEYCLOAK_SSL_REQUIRED
    realm["smtpServer"] = smtp_server
    # Il login theme `securescan` ha anche override mirati per alcune email
    # transazionali, in particolare il cambio email self-service. Le email non
    # personalizzate continuano comunque a usare il parent theme Keycloak.
    realm["emailTheme"] = "securescan"

    _request(
        "PUT",
        f"{KEYCLOAK_INTERNAL_URL}/admin/realms/{KEYCLOAK_REALM}",
        token=token,
        body=realm,
    )


def main() -> int:
    """Entry point con retry, utile perché Keycloak potrebbe non essere pronto al primo tentativo."""
    for attempt in range(10):
        try:
            token = _get_admin_token()
            _apply_realm_runtime_overrides(token)
            _configure_frontend_client(token)
            _ensure_admin_client_secret(token)
            _ensure_password_verification_client(token)
            _disable_demo_users(token)
            _ensure_service_account_roles(token)
            _ensure_required_actions(token)
            _cleanup_legacy_update_email_required_actions(token)
            _ensure_reset_email_force_login(token)
            _ensure_registration_password_is_persisted(token)
            print("Keycloak runtime configuration applied successfully.")
            return 0
        except (HTTPError, URLError, RuntimeError) as exc:
            if attempt == 9:
                print(f"Failed to apply Keycloak runtime configuration: {exc}", file=sys.stderr)
                return 1
            time.sleep(3)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
