#!/usr/bin/env python3
"""Verifica statica dei requisiti Keycloak per il self-service locale.

Questo script non corrisponde direttamente a una pagina, ma protegge tutti i
flow utente che dipendono da Keycloak: Accedi, Registrazione, Password
dimenticata, Reimposta password e gestione del profilo.

Controlla il realm versionato nel repository per evitare regressioni banali
nelle impostazioni che rendono possibile l'esperienza demo locale.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


def main() -> int:
    """Esegue controlli coerenti con il comportamento atteso del realm locale.

    L'obiettivo non e` testare Keycloak a runtime, ma verificare che il file
    `realm-securescan.json` continui a dichiarare le opzioni minime richieste
    da SecureScan Cloud per autenticazione, registrazione e reset password.
    """
    realm_path = Path(__file__).resolve().parents[1] / "infrastructure" / "keycloak" / "realm-securescan.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))

    failures: list[str] = []

    if realm.get("registrationAllowed") is not True:
        failures.append("registrationAllowed must be true")

    if realm.get("resetPasswordAllowed") is not True:
        failures.append("resetPasswordAllowed must be true")

    if realm.get("defaultLocale") != "it":
        failures.append("defaultLocale must be it")

    if realm.get("supportedLocales") != ["it"]:
        failures.append("supportedLocales must contain only it")

    if realm.get("duplicateEmailsAllowed") is not False:
        failures.append("duplicateEmailsAllowed must be false")

    if realm.get("registrationEmailAsUsername") is not False:
        failures.append("registrationEmailAsUsername must be false")

    if realm.get("editUsernameAllowed") is not True:
        failures.append("editUsernameAllowed must be true")

    # La policy password influenza direttamente i messaggi e i controlli visti
    # dall'utente nelle pagine Keycloak dedicate a registrazione e reset.
    password_policy = realm.get("passwordPolicy", "")
    required_policies = [
        "length(8)",
        "upperCase(1)",
        "lowerCase(1)",
        "digits(1)",
        "specialChars(1)",
        "notUsername",
    ]
    for fragment in required_policies:
        if fragment not in password_policy:
            failures.append(f"passwordPolicy must include {fragment}")

    default_role = realm.get("defaultRole")
    composites = default_role.get("composites", {}).get("realm", []) if isinstance(default_role, dict) else []
    if "analyst" not in composites:
        failures.append("defaultRole must include analyst")

    # Il client frontend rappresenta l'app React che avvia il login browser.
    frontend_client = next(
        (client for client in realm.get("clients", []) if client.get("clientId") == "securescan-frontend"),
        None,
    )
    if frontend_client is None:
        failures.append("securescan-frontend client is missing")
    else:
        if frontend_client.get("publicClient") is not True:
            failures.append("securescan-frontend must remain a public client")
        if frontend_client.get("directAccessGrantsEnabled") is not False:
            failures.append("securescan-frontend must keep direct access grants disabled")

    # Il client admin e` usato dal backend per operazioni amministrative verso
    # Keycloak; per questo deve restare confidential con service account.
    admin_client = next(
        (client for client in realm.get("clients", []) if client.get("clientId") == "securescan-admin-api"),
        None,
    )
    if admin_client is None:
        failures.append("securescan-admin-api client is missing")
    else:
        if admin_client.get("serviceAccountsEnabled") is not True:
            failures.append("securescan-admin-api must enable service accounts")
        if admin_client.get("publicClient") is not False:
            failures.append("securescan-admin-api must remain confidential")

    # Questo client confidenziale e` dedicato alla verifica della password
    # corrente durante il cambio password autenticato dal profilo.
    password_verification_client = next(
        (client for client in realm.get("clients", []) if client.get("clientId") == "securescan-password-verification"),
        None,
    )
    if password_verification_client is None:
        failures.append("securescan-password-verification client is missing")
    else:
        if password_verification_client.get("publicClient") is not False:
            failures.append("securescan-password-verification must remain confidential")
        if password_verification_client.get("directAccessGrantsEnabled") is not True:
            failures.append("securescan-password-verification must enable direct access grants for current password verification")

    service_account_user = next(
        (
            user
            for user in realm.get("users", [])
            if user.get("serviceAccountClientId") == "securescan-admin-api"
        ),
        None,
    )
    if service_account_user is None:
        failures.append("service account user for securescan-admin-api is missing")
    else:
        if service_account_user.get("username") != "service-account-securescan-admin-api":
            failures.append("service account username for securescan-admin-api must be service-account-securescan-admin-api")
        realm_management_roles = service_account_user.get("clientRoles", {}).get("realm-management", [])
        if "view-realm" not in realm_management_roles:
            failures.append("service account realm-management roles must include view-realm")

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    print("PASS: Keycloak self-service configuration is coherent for local demo use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
