#!/usr/bin/env python3
"""Suite locale di controlli RBAC per la demo di SecureScan Cloud.

Questo file non implementa una pagina dell'interfaccia. Viene eseguito a
parte per verificare, con chiamate HTTP reali, che analyst e admin vedano
soltanto cio` che il backend permette davvero.

Protegge indirettamente pagine come Cronologia, Dettaglio analisi, Stato del
sistema e Amministrazione, dimostrando che i controlli server-side non
dipendono dalla sola UI frontend.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _env(name: str, default: str) -> str:
    """Legge una variabile ambiente con fallback pensato per la demo locale."""
    return os.getenv(name, default).strip()


GATEWAY_URL = _env("SECURESCAN_GATEWAY_URL", "http://localhost:8000")
KEYCLOAK_URL = _env("SECURESCAN_KEYCLOAK_URL", "http://localhost:8180")
KEYCLOAK_REALM = _env("SECURESCAN_KEYCLOAK_REALM", "securescan")
RBAC_CLIENT_ID = _env("SECURESCAN_RBAC_CLIENT_ID", "securescan-rbac-demo")
ANALYST_USERNAME = _env("SECURESCAN_ANALYST_USERNAME", "analyst.demo")
ANALYST_PASSWORD = _env("SECURESCAN_ANALYST_PASSWORD", "ChangeMe-Analyst-123!")
ADMIN_USERNAME = _env("SECURESCAN_ADMIN_USERNAME", "admin.demo")
ADMIN_PASSWORD = _env("SECURESCAN_ADMIN_PASSWORD", "ChangeMe-Admin-123!")
REQUEST_ID_PREFIX = "rbac-demo"


@dataclass
class HttpResult:
    """Risultato normalizzato di una chiamata HTTP effettuata dallo script."""
    status: int
    body_text: str
    json_body: dict[str, Any] | list[Any] | None
    headers: dict[str, str]


@dataclass
class CheckResult:
    """Esito di un controllo RBAC stampato nel report finale."""
    name: str
    outcome: str
    detail: str


def http_request(
    *,
    method: str,
    url: str,
    bearer_token: str | None = None,
    json_payload: dict[str, Any] | None = None,
    form_payload: dict[str, str] | None = None,
    request_id: str,
) -> HttpResult:
    """Invia una richiesta HTTP al gateway o a Keycloak.

    Lo script passa sempre dal gateway pubblico locale per riprodurre il
    percorso usato dal frontend: browser -> Kong -> Analysis API.
    """
    data: bytes | None = None
    headers: dict[str, str] = {"X-Request-ID": request_id}

    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    if json_payload is not None:
        data = json.dumps(json_payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form_payload is not None:
        data = urlencode(form_payload).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = Request(url=url, method=method, data=data, headers=headers)

    try:
        with urlopen(request, timeout=10) as response:
            body_bytes = response.read()
            status = response.status
            response_headers = dict(response.headers.items())
    except HTTPError as exc:
        body_bytes = exc.read()
        status = exc.code
        response_headers = dict(exc.headers.items())
    except URLError as exc:
        raise RuntimeError(f"Network error while calling {url}: {exc}") from exc

    body_text = body_bytes.decode("utf-8", errors="replace")
    try:
        json_body = json.loads(body_text) if body_text.strip() else None
    except json.JSONDecodeError:
        json_body = None

    return HttpResult(
        status=status,
        body_text=body_text,
        json_body=json_body,
        headers=response_headers,
    )


def get_token(*, username: str, password: str) -> str:
    """Ottiene un token Keycloak reale per i controlli analyst/admin."""
    token_url = (
        f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
    )
    result = http_request(
        method="POST",
        url=token_url,
        form_payload={
            "grant_type": "password",
            "client_id": RBAC_CLIENT_ID,
            "username": username,
            "password": password,
        },
        request_id=f"{REQUEST_ID_PREFIX}-token-{username}",
    )
    if result.status != 200 or not isinstance(result.json_body, dict):
        raise RuntimeError(
            f"Unable to obtain token for {username}. HTTP {result.status}: {result.body_text[:200]}"
        )

    access_token = result.json_body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError(f"Token response for {username} does not contain access_token.")
    return access_token


def run_check(name: str, func) -> CheckResult:
    """Esegue un singolo controllo e converte eccezioni/assert in un esito leggibile."""
    try:
        detail = func()
        return CheckResult(name=name, outcome="PASS", detail=detail)
    except AssertionError as exc:
        return CheckResult(name=name, outcome="FAIL", detail=str(exc) or "Assertion failed.")
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=name, outcome="FAIL", detail=str(exc))


def main() -> int:
    """Coordina i controlli RBAC principali della demo locale.

    I test coprono sia casi positivi sia negativi:
    - richieste senza token;
    - permessi consentiti ad analyst;
    - permessi consentiti ad admin;
    - operazioni che un analyst non deve poter eseguire.
    """
    parser = argparse.ArgumentParser(description="Run SecureScan Cloud RBAC demo checks.")
    parser.add_argument(
        "--allow-delete",
        action="store_true",
        help="Actually call DELETE /api/v1/analyses using the admin token.",
    )
    args = parser.parse_args()

    # Questi endpoint corrispondono a funzionalita` reali usate poi dal sito:
    # Cronologia/Dettaglio analisi interrogano le analisi, mentre Stato del
    # sistema espone una vista tecnica leggibile anche dal frontend.
    analyses_url = f"{GATEWAY_URL}/api/v1/analyses"
    system_status_url = f"{GATEWAY_URL}/api/v1/system/status"

    analyst_token = get_token(username=ANALYST_USERNAME, password=ANALYST_PASSWORD)
    admin_token = get_token(username=ADMIN_USERNAME, password=ADMIN_PASSWORD)

    results: list[CheckResult] = []

    results.append(
        run_check(
            "401 without token",
            lambda: _assert_status(
                http_request(
                    method="GET",
                    url=analyses_url,
                    request_id=f"{REQUEST_ID_PREFIX}-missing-token",
                ),
                401,
                "Request without token must be rejected with 401.",
            ),
        )
    )
    results.append(
        run_check(
            "analyst can list analyses",
            lambda: _assert_status(
                http_request(
                    method="GET",
                    url=analyses_url,
                    bearer_token=analyst_token,
                    request_id=f"{REQUEST_ID_PREFIX}-analyst-list",
                ),
                200,
                "Analyst must be able to list analyses.",
            ),
        )
    )
    results.append(
        run_check(
            "analyst can read system status",
            lambda: _assert_status(
                http_request(
                    method="GET",
                    url=system_status_url,
                    bearer_token=analyst_token,
                    request_id=f"{REQUEST_ID_PREFIX}-analyst-system-status",
                ),
                200,
                "Analyst must be able to read system status.",
            ),
        )
    )
    results.append(
        run_check(
            "analyst can create analysis",
            lambda: _assert_status(
                http_request(
                    method="POST",
                    url=analyses_url,
                    bearer_token=analyst_token,
                    json_payload={"unsupported": True},
                    request_id=f"{REQUEST_ID_PREFIX}-analyst-post-shape-check",
                ),
                422,
                "Analyst authorization is confirmed when the request reaches validation and returns 422.",
            ),
        )
    )
    results.append(
        run_check(
            "analyst receives 403 on delete",
            lambda: _assert_status(
                http_request(
                    method="DELETE",
                    url=analyses_url,
                    bearer_token=analyst_token,
                    request_id=f"{REQUEST_ID_PREFIX}-analyst-delete",
                ),
                403,
                "Analyst must receive 403 on DELETE /api/v1/analyses.",
            ),
        )
    )
    results.append(
        run_check(
            "admin can read system status",
            lambda: _assert_status(
                http_request(
                    method="GET",
                    url=system_status_url,
                    bearer_token=admin_token,
                    request_id=f"{REQUEST_ID_PREFIX}-admin-system-status",
                ),
                200,
                "Admin must be able to read system status.",
            ),
        )
    )

    if args.allow_delete:
        results.append(
            run_check(
                "admin can delete analyses",
                lambda: _assert_status(
                    http_request(
                        method="DELETE",
                        url=analyses_url,
                        bearer_token=admin_token,
                        request_id=f"{REQUEST_ID_PREFIX}-admin-delete",
                    ),
                    204,
                    "Admin must be able to delete analyses.",
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                name="admin can delete analyses",
                outcome="SKIP",
                detail="Skipped by default to avoid destructive deletion. Re-run with --allow-delete.",
            )
        )

    print("SecureScan Cloud RBAC demo")
    print(f"Gateway: {GATEWAY_URL}")
    print(f"Keycloak realm: {KEYCLOAK_REALM}")
    print(f"RBAC client: {RBAC_CLIENT_ID}")
    print()

    max_name_length = max(len(result.name) for result in results)
    failed = False
    for result in results:
        print(f"{result.outcome:<5}  {result.name.ljust(max_name_length)}  {result.detail}")
        if result.outcome == "FAIL":
            failed = True

    return 1 if failed else 0


def _assert_status(result: HttpResult, expected_status: int, message: str) -> str:
    """Verifica il codice HTTP e restituisce un dettaglio sintetico per il report."""
    assert result.status == expected_status, (
        f"{message} Expected HTTP {expected_status}, got {result.status}. "
        f"Body: {result.body_text[:200]}"
    )
    return f"HTTP {result.status}"


if __name__ == "__main__":
    sys.exit(main())
