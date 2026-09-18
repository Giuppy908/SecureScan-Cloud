# SecureScan Security Utilities

Questa directory contiene utility locali per verificare aspetti di sicurezza e coerenza della demo.

## File presenti

- `demo_rbac.py`
- `check_keycloak_self_service.py`

## `demo_rbac.py`

Questa suite verifica con chiamate HTTP reali che:

- senza token si ottenga `401`;
- un `analyst` possa usare gli endpoint consentiti;
- un `analyst` riceva `403` sulle operazioni amministrative;
- un `admin` abbia i privilegi previsti.

È pensata per il contesto locale demo e usa Keycloak e Kong reali del progetto.

## `check_keycloak_self_service.py`

Questo script esegue una verifica statica del realm versionato per controllare che restino coerenti:

- registrazione;
- reset password;
- locale italiana;
- policy password;
- configurazione minima dei client principali.

## Ambito

Questi strumenti non sostituiscono audit completi di sicurezza o penetration test. Servono a rendere riproducibili controlli mirati sul comportamento locale del progetto.

## Collegamenti utili

- [Autenticazione e RBAC](../docs/authentication-rbac.md)
- [README root](../README.md)
