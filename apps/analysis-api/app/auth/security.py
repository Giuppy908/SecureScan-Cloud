"""Autenticazione JWT e autorizzazione RBAC della Analysis API.

Questo modulo protegge quasi tutte le pagine dell'applicazione. Il flusso è:
Keycloak esegue il login, il frontend riceve un JWT, il frontend invia quel
token all'API e qui il token viene verificato prima di fidarsi dell'utente.

In modo semplice:
- il `subject` identifica in maniera stabile l'utente;
- i ruoli `analyst` e `admin` determinano cosa può fare;
- JWKS (JSON Web Key Set) è l'insieme delle chiavi pubbliche pubblicate da
  Keycloak che l'API usa per controllare che il token sia autentico.

Da questo file dipendono direttamente le protezioni di Cronologia, Dettaglio
analisi, Profilo, Dashboard, Stato del sistema e Amministrazione.
"""

# Permette la gestione posticipata delle annotazioni di tipo, ad esempio `str | None`
from __future__ import annotations

# `json` viene usato per interpretare il documento JWKS restituito da Keycloak
import json

# `logging` permette di registrare warning quando il recupero o la lettura delle chiavi pubbliche di Keycloak presenta problemi
import logging

# `threading` viene usato per creare un lock che protegge l'accesso concorrente alla cache delle chiavi JWKS
import threading

# `dataclass` permette di definire in modo compatto la struttura che rappresenta un utente autenticato
from dataclasses import dataclass

# `lru_cache` viene usato per riutilizzare la stessa istanza del verificatore JWT all'interno del processo della Analysis API
from functools import lru_cache

# `Any` viene usato quando il tipo concreto può variare
# `Callable` descrive una funzione che può essere passata come parametro
from typing import Any, Callable

# `URLError` permette di intercettare errori durante il contatto HTTP con l'endpoint JWKS di Keycloak
from urllib.error import URLError

# `urlopen` viene usato per effettuare la richiesta HTTP verso l'endpoint JWKS
from urllib.request import urlopen

# Libreria PyJWT usata per leggere e verificare i token JWT
import jwt

# Componenti FastAPI:
# - `Depends` e `Security` gestiscono le dipendenze di autenticazione/autorizzazione
# - `HTTPException` genera risposte HTTP di errore
# - `Request` rappresenta la richiesta HTTP corrente
# - `status` fornisce le costanti dei codici HTTP
from fastapi import Depends, HTTPException, Request, Security, status

# Tipi e strumenti FastAPI specifici per lo schema HTTP Bearer
# Bearer indica nell'header HTTP `Authorization` che la richiesta sta trasportando un token di accesso
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# `PyJWK` converte una chiave descritta nel documento JWKS in una chiave utilizzabile da PyJWT per verificare la firma
from jwt import PyJWK

# Eccezione base di PyJWT per token non validi
from jwt.exceptions import InvalidTokenError

# Funzione interna del progetto usata per registrare eventi di sicurezza come autenticazioni mancanti, token invalidi o autorizzazioni negate
from app.auth.audit import log_security_event

# Configurazione centralizzata della Analysis API: issuer, audience, URL JWKS, algoritmi ammessi, timeout e flag autenticazione
from app.core.config import settings

# Logger associato a questo modulo
logger = logging.getLogger(__name__)

# Definisce lo schema di autenticazione Bearer usato da FastAPI `auto_error=False` evita che HTTPBearer generi automaticamente l'errore: sarà `get_current_user()` a decidere come gestire credenziali mancanti o errate
bearer_scheme = HTTPBearer(auto_error=False)

# Eccezione interna usata quando il token non può essere considerato valido per autenticare l'utente
class AuthenticationError(Exception):
    """Raised when a JWT is invalid for authentication."""

# Eccezione separata usata quando il problema non è il token dell'utente, ma l'impossibilità di ottenere le chiavi pubbliche dall'Identity Provider (Keycloak)
class IdentityProviderUnavailableError(Exception):
    """Raised when JWKS cannot be retrieved from the identity provider."""

# `@dataclass` genera automaticamente il costruttore e altri metodi utili
# `frozen=True` rende l'oggetto immutabile dopo la creazione
# `slots=True` limita gli attributi a quelli dichiarati nella classe
@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Identità applicativa ottenuta dopo la verifica completa del JWT."""

    # Identificatore stabile dell'utente ricavato dal claim JWT `sub`
    subject: str

    # Nome utente applicativo, ricavato dai claim del token
    username: str

    # Nome mostrato nell'interfaccia o nei log
    display_name: str

    # Insieme immutabile dei ruoli associati all'utente, ad esempio `analyst` e/o `admin` (un utente potrebbe possedere più ruoli)
    roles: frozenset[str]

    # Identificatore del singolo token, ricavato dal claim JWT `jti` (JWT ID), se presente
    token_id: str | None = None

    # Identificatore della sessione Keycloak, ricavato dal claim JWT `sid` oppure, se `sid` non è presente, dal claim `session_state`
    session_id: str | None = None

# Funzione predefinita che scarica il documento JWKS dall'Identity Provider.
# Il JWKS (JSON Web Key Set) contiene le chiavi pubbliche con cui l'API può verificare la firma dei JWT emessi da Keycloak.
def _default_jwks_fetcher(url: str, timeout_seconds: float) -> dict[str, Any]:
    """Scarica il documento JWKS dall'identity provider configurato."""

    # Apre la connessione HTTP verso l'URL JWKS `with` garantisce la corretta chiusura della risposta
    with urlopen(url, timeout=timeout_seconds) as response:

        # Interpreta il corpo HTTP come JSON e restituisce il dizionario ottenuto
        return json.load(response)

# Classe responsabile della verifica completa dei JWT emessi da Keycloak
class KeycloakJWTVerifier:
    """Verifica i token emessi da Keycloak prima che l'API li utilizzi.

    La cache delle chiavi evita una chiamata HTTP a Keycloak per ogni singola
    richiesta. Se compare un `kid` nuovo, la cache viene aggiornata e l'API
    prova di nuovo a verificare la firma del token.
    """

    # Il costruttore riceve tutti i parametri necessari per validare i JWT
    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        audience: str,
        allowed_algorithms: tuple[str, ...],
        request_timeout_seconds: float,
        jwks_fetcher: Callable[[str, float], dict[str, Any]] | None = None,
    ) -> None:
        # Emittente atteso nel claim `iss`
        self._issuer = issuer

        # Endpoint da cui recuperare le chiavi pubbliche JWKS
        self._jwks_url = jwks_url

        # Audience che il token deve contenere per essere accettato dalla API
        # L'audience di un JWT indica a chi è destinato quel token, ovvero quale servizio dovrebbe accettarlo
        self._audience = audience

        # Algoritmi di firma consentiti, nel progetto RS256
        self._allowed_algorithms = allowed_algorithms

        # Timeout massimo per il recupero delle JWKS
        self._request_timeout_seconds = request_timeout_seconds

        # Se viene fornita una funzione di fetch personalizzata viene usata quella; altrimenti si usa `_default_jwks_fetcher`
        # Questo rende il componente più facilmente testabile
        self._jwks_fetcher = jwks_fetcher or _default_jwks_fetcher

        # Cache locale delle chiavi pubbliche indicizzate per `kid`
        # `kid` = Key ID, identificatore della chiave associata alla firma del JWT
        self._keys_by_kid: dict[str, Any] = {}

        # Conta quante volte la cache JWKS viene aggiornata
        self._refresh_counter = 0

        # Lock usato per proteggere cache e contatore in presenza di accessi concorrenti da più richieste
        self._lock = threading.Lock()

    # Espone il contatore come proprietà in sola lettura
    @property
    def refresh_counter(self) -> int:
        """Espone quante volte la cache JWKS è stata aggiornata."""

        # Il lock garantisce una lettura sincronizzata del contatore
        with self._lock:
            return self._refresh_counter

    # Metodo principale: prende il JWT ricevuto dal client, lo verifica e restituisce l'identità applicativa dell'utente
    def verify_access_token(self, token: str) -> AuthenticatedUser:
        """Controlla il token e costruisce l'identità usata dal resto dell'API."""

        # Legge l'header del JWT senza verificarne ancora la firma
        # Questa fase serve per conoscere `alg` (algoritmo crittografico usato per la firma digitale del JWT) e `kid` (Key ID, chiave pubblica necessaria per verificare l'algoritmo)
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise AuthenticationError("Token header is invalid.") from exc

        # Recupera l'algoritmo dichiarato nell'header del JWT
        algorithm = header.get("alg")

        # Accetta il token solo se l'algoritmo appartiene all'elenco esplicitamente consentito dal backend
        if algorithm not in self._allowed_algorithms:
            raise AuthenticationError("Token algorithm is not allowed.")

        # Recupera il `kid`, cioè l'identificatore della chiave dichiarato nell'header non ancora verificato del token
        kid = header.get("kid")

        # Il `kid` deve essere una stringa valida e non vuota
        if not isinstance(kid, str) or not kid:
            raise AuthenticationError("Token kid is missing.")

        # Cerca nella cache o recupera da Keycloak la chiave pubblica corrispondente al `kid`
        signing_key = self._get_signing_key(kid)

        # Verifica effettivamente il JWT
        try:
            payload = jwt.decode(
                token,

                # Chiave pubblica usata per verificare la firma digitale
                key=signing_key,

                # Limita gli algoritmi accettabili a quelli configurati
                algorithms=list(self._allowed_algorithms),

                # Controlla che il token sia destinato alla Analysis API
                audience=self._audience,

                # Controlla che il token provenga dall'emittente Keycloak atteso
                issuer=self._issuer,

                # Richiede esplicitamente la presenza dei claim: `exp` = scadenza, `sub` = identificatore dell'utente
                options={"require": ["exp", "sub"]},
            )
        except InvalidTokenError as exc:
            # PyJWT usa questa famiglia di eccezioni per errori quali firma invalida, token scaduto, emittente/audience errati, ecc.
            raise AuthenticationError("Token verification failed.") from exc

        # Recupera il subject dell'utente dal claim `sub`
        subject = payload.get("sub")

        # Anche dopo la decode viene verificato che il subject sia effettivamente una stringa non vuota
        if not isinstance(subject, str) or not subject.strip():
            raise AuthenticationError("Token subject is missing.")

        # Recupera opzionalmente il tipo di token
        token_type = payload.get("typ")

        # Se `typ` è presente, il backend accetta esclusivamente `Bearer`
        if token_type is not None and token_type != "Bearer":
            raise AuthenticationError("Token type is invalid.")

        # Estrae dal payload i ruoli Keycloak usati per l'RBAC
        roles = self._extract_roles(payload)

        # Ricava uno username; se i claim previsti non esistono, utilizza il subject come fallback
        username = self._extract_username(payload, fallback=subject)

        # Ricava il nome da mostrare; come fallback usa lo username
        display_name = self._extract_display_name(payload, fallback=username)

        # Recupera il claim `jti`, usato come identificatore del token, se presente
        token_id = payload.get("jti")

        # Se `jti` esiste ma non è una stringa viene ignorato
        if token_id is not None and not isinstance(token_id, str):
            token_id = None

        # Cerca prima il claim `sid` come identificatore della sessione
        session_id = payload.get("sid")

        # Se `sid` non è presente, usa il claim `session_state` come fallback
        if session_id is None:
            session_id = payload.get("session_state")

        # Anche il session ID viene mantenuto solo se è una stringa
        if session_id is not None and not isinstance(session_id, str):
            session_id = None

        # Tutte le informazioni validate vengono raccolte nell'oggetto applicativo `AuthenticatedUser`
        return AuthenticatedUser(
            subject=subject,
            username=username,
            display_name=display_name,
            roles=roles,
            token_id=token_id,
            session_id=session_id,
        )

    # Estrae dal payload i ruoli definiti a livello di realm Keycloak
    def _extract_roles(self, payload: dict[str, Any]) -> frozenset[str]:
        """Ricava dal token i ruoli che regolano analyst/admin nel backend."""

        # I ruoli del realm si trovano dentro `realm_access`
        realm_access = payload.get("realm_access")

        # Se la struttura non esiste o non è un dizionario, l'utente viene considerato senza ruoli
        if not isinstance(realm_access, dict):
            return frozenset()

        # Recupera la lista dei ruoli dal campo `roles`
        raw_roles = realm_access.get("roles")

        # Se non è una lista valida, restituisce un insieme vuoto
        if not isinstance(raw_roles, list):
            return frozenset()

        # Mantiene solamente elementi di tipo stringa e non vuoti e restituisce un insieme immutabile senza duplicati
        return frozenset(role for role in raw_roles if isinstance(role, str) and role.strip())

    # Ricava lo username da usare nel backend
    def _extract_username(self, payload: dict[str, Any], *, fallback: str) -> str:
        """Ricava il nome breve mostrato in UI e log quando disponibile."""

        # Prima scelta: `preferred_username`
        preferred_username = payload.get("preferred_username")
        if isinstance(preferred_username, str) and preferred_username.strip():
            return preferred_username

        # Seconda scelta: claim `name`
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            return name

        # Ultimo fallback: valore fornito dal chiamante, che nel flusso principale è il subject
        return fallback

    # Ricava il nome più leggibile da mostrare all'utente
    def _extract_display_name(self, payload: dict[str, Any], *, fallback: str) -> str:
        """Ricava il nome visualizzato privilegiando il nome completo di Keycloak."""

        # Prima scelta: nome completo
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            return name

        # Seconda scelta: username Keycloak
        preferred_username = payload.get("preferred_username")
        if isinstance(preferred_username, str) and preferred_username.strip():
            return preferred_username

        # Ultimo fallback: username già calcolato
        return fallback

    # Recupera la chiave pubblica associata al `kid`
    def _get_signing_key(self, kid: str) -> Any:
        """Restituisce la chiave pubblica associata al `kid` richiesto."""

        # Prima prova a usare la chiave già presente nella cache locale
        with self._lock:
            cached_key = self._keys_by_kid.get(kid)

        # Se la chiave è già disponibile non serve contattare Keycloak
        if cached_key is not None:
            return cached_key

        # Se il `kid` non è presente, aggiorna l'intero set di chiavi JWKS
        self._refresh_keys()

        # Dopo il refresh cerca nuovamente la chiave richiesta
        with self._lock:
            refreshed_key = self._keys_by_kid.get(kid)

        # Se neppure il nuovo documento JWKS contiene il `kid`, il token non può essere verificato
        if refreshed_key is None:
            raise AuthenticationError("Token kid is unknown.")

        return refreshed_key

    # Recupera da Keycloak tutte le chiavi pubbliche attualmente disponibili
    def _refresh_keys(self) -> None:
        """Ricarica le chiavi pubbliche da Keycloak e sostituisce la cache locale."""

        try:
            # Chiama il fetcher configurato usando URL JWKS e timeout
            payload = self._jwks_fetcher(self._jwks_url, self._request_timeout_seconds)

        # Queste eccezioni indicano problemi di rete, timeout o risposta JWKS non interpretabile correttamente
        except (URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Unable to retrieve JWKS from Keycloak.")
            raise IdentityProviderUnavailableError("JWKS endpoint is unavailable.") from exc

        # Il documento JWKS deve contenere una proprietà `keys`
        keys = payload.get("keys")

        # `keys` deve essere una lista di definizioni JWK
        if not isinstance(keys, list):
            raise IdentityProviderUnavailableError("JWKS payload is malformed.")

        # Dizionario temporaneo che conterrà le nuove chiavi valide
        next_keys: dict[str, Any] = {}

        # Analizza ogni chiave presente nel documento JWKS
        for key_definition in keys:

            # Ignora elementi che non siano dizionari
            if not isinstance(key_definition, dict):
                continue

            # Ogni chiave deve avere un `kid`
            kid = key_definition.get("kid")
            if not isinstance(kid, str) or not kid:
                continue

            try:
                # Converte la descrizione JSON della JWK nella chiave crittografica utilizzabile da PyJWT
                next_keys[kid] = PyJWK.from_dict(key_definition).key

            # Se una singola JWK è malformata viene ignorata, senza rendere inutilizzabili le altre chiavi valide
            except Exception:  # noqa: BLE001
                logger.warning("Ignoring malformed JWK from Keycloak.", extra={"kid": kid})

        # Se nessuna chiave valida è stata ricavata, il backend non può verificare i JWT
        if not next_keys:
            raise IdentityProviderUnavailableError("No usable JWK is available.")

        # Sostituisce atomicamente la cache precedente con quella appena costruita e incrementa il contatore dei refresh
        with self._lock:
            self._keys_by_kid = next_keys
            self._refresh_counter += 1


# La cache conserva una sola istanza di `KeycloakJWTVerifier` per ogni processo della Analysis API
# In questo modo chiavi JWKS e stato interno del verifier possono essere riutilizzati
@lru_cache(maxsize=1)
def get_jwt_verifier() -> KeycloakJWTVerifier:
    """Restituisce il verificatore JWT condiviso dalla replica API."""

    # Costruisce il verifier usando i valori della configurazione centralizzata
    return KeycloakJWTVerifier(
        issuer=settings.keycloak_issuer,
        jwks_url=settings.keycloak_jwks_url,
        audience=settings.keycloak_audience,
        allowed_algorithms=settings.keycloak_allowed_algorithms,
        request_timeout_seconds=settings.jwks_request_timeout_seconds,
    )


# Funzione di supporto per generare sempre una risposta HTTP 401 coerente con lo schema di autenticazione Bearer
def _build_unauthorized_exception(message: str) -> HTTPException:
    """Costruisce una 401 coerente con autenticazione Bearer."""

    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,

        # Questo header comunica al client che il metodo di autenticazione richiesto è HTTP Bearer
        headers={"WWW-Authenticate": "Bearer"},
    )


# Dependency FastAPI principale per autenticare l'utente corrente
def get_current_user(
    request: Request,

    # `Security(bearer_scheme)` fa analizzare a FastAPI l'header Authorization e restituisce le credenziali Bearer, se presenti
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthenticatedUser:
    """Risoluzione dell'utente corrente a partire dall'header Authorization.

    In locale i test possono disabilitare `AUTH_ENABLED`; in tutte le altre
    modalità il token viene verificato prima di qualsiasi decisione RBAC.
    """

    # Se l'autenticazione è disabilitata, non viene controllato alcun JWT e viene restituito un utente sintetico dotato di entrambi i ruoli
    if not settings.auth_enabled:
        return AuthenticatedUser(
            subject="test-user",
            username="test.user",
            display_name="Utente di test",
            roles=frozenset({"admin", "analyst"}),
        )

    # Se non esistono credenziali oppure lo schema non è Bearer, la richiesta non può essere autenticata
    if credentials is None or credentials.scheme.lower() != "bearer":

        # Registra l'evento di sicurezza prima di restituire 401
        log_security_event(
            request,
            event="authentication_missing",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

        raise _build_unauthorized_exception("Authentication credentials were not provided.")

    try:
        # Estrae la stringa del JWT dalle credenziali Bearer e la verifica
        return get_jwt_verifier().verify_access_token(credentials.credentials)

    # Se le JWKS non sono disponibili, sono malformate o non contengono chiavi utilizzabili, il problema riguarda il servizio di autenticazione e non un token non valido del client
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable.",
        ) from exc

    # Se invece il token è presente ma non valido, la richiesta viene considerata non autenticata
    except AuthenticationError as exc:

        # Registra l'evento di autenticazione fallita
        log_security_event(
            request,
            event="authentication_invalid",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

        raise _build_unauthorized_exception("Invalid bearer token.") from exc


# Funzione interna comune usata per applicare i controlli RBAC
def _require_roles(
    request: Request,
    user: AuthenticatedUser,
    *,
    allowed_roles: frozenset[str],
) -> AuthenticatedUser:
    """Applica il controllo RBAC minimo richiesto dall'endpoint chiamante."""

    # `intersection()` verifica se esiste almeno un ruolo presente sia nei ruoli dell'utente sia in quelli consentiti
    if user.roles.intersection(allowed_roles):

        # Se almeno un ruolo è ammesso, l'utente può proseguire
        return user

    # Se nessun ruolo è consentito, registra il rifiuto includendo informazioni utili per l'audit
    log_security_event(
        request,
        event="authorization_denied",
        status_code=status.HTTP_403_FORBIDDEN,
        subject=user.subject,
        username=user.username,
        roles=user.roles,
    )

    # 403 significa che l'utente è stato autenticato, ma non possiede i permessi necessari per l'operazione richiesta
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions.",
    )


# Dependency FastAPI usata dagli endpoint accessibili sia agli analyst sia agli admin
def require_analyst(
    request: Request,

    # Prima di controllare il ruolo, FastAPI esegue automaticamente `get_current_user`, quindi l'utente deve essere già autenticato
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Permette accesso a ruoli `analyst` e `admin`."""

    # Un admin supera anche questo controllo perché entrambi i ruoli fanno parte dell'insieme consentito
    return _require_roles(request, user, allowed_roles=frozenset({"analyst", "admin"}))


# Dependency FastAPI riservata esclusivamente agli amministratori
def require_admin(
    request: Request,

    # Anche qui FastAPI autentica prima l'utente tramite `get_current_user`
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Permette accesso esclusivamente al ruolo `admin`."""

    # Solo il ruolo `admin` appartiene all'insieme consentito
    return _require_roles(request, user, allowed_roles=frozenset({"admin"}))
