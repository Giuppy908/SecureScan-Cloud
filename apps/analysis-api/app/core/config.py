"""Configurazione centralizzata della Analysis API.

Questo file spiega al backend come trovare gli altri componenti di
SecureScan Cloud. Qui vengono letti dall'environment:
- URL pubblici usati dal browser;
- endpoint interni Docker usati tra container;
- limiti di upload e avatar;
- parametri Keycloak;
- impostazioni utili a heartbeat, monitoring e sicurezza.

Non corrisponde a una pagina specifica, ma influenza in modo indiretto quasi
tutto il sito: Nuova analisi, Profilo, Stato del sistema, autenticazione e
integrazioni con Keycloak.
"""

# Permette la gestione posticipata (da Python) sulle indicazioni sui tipi, come `str`, `int` o `list[str]`
from __future__ import annotations

# `os` viene utilizzato per leggere le variabili d'ambiente tramite `os.getenv()`, usate per cambiare la configurazione delle API senza modificare il codice
import os

# `socket` permette di ottenere automaticamente il nome dell'host su cui sta eseguendo questa replica della Analysis API
import socket

# `BaseModel` permette di raccogliere la configurazione in un modello Pydantic tipizzato
# `Field` permette di definire valori generati dinamicamente e vincoli di validazione
from pydantic import BaseModel, Field

# Funzione di supporto usata quando una configurazione deve essere un numero intero
# Cerca la variabile d'ambiente indicata da `name`
# Se non esiste, usa il valore `default`
# Alla fine converte il valore in `int`
# Viene usata, ad esempio, per leggere limiti di upload, timeout e porte di rete
def _read_int_env(name: str, default: int) -> int:
    """Read an integer environment variable with a fallback default."""
    return int(os.getenv(name, str(default)).strip())

# Funzione di supporto usata quando una variabile d'ambiente contiene più valori separati da virgola
# Nel progetto viene utilizzata per leggere l'elenco delle origin CORS consentite
def _read_csv_env(name: str, default: tuple[str, ...]) -> list[str]:
    """Read a comma-separated environment variable as a normalized list."""

    # Legge la variabile d'ambiente e rimuove eventuali spazi iniziali e finali
    raw_value = os.getenv(name, "").strip()

    # Se la variabile non è presente o è vuota, usa i valori di default
    if not raw_value:
        return list(default)

    # Divide la stringa usando la virgola, elimina gli spazi e ignora eventuali elementi vuoti
    # Esempio:
    # "http://localhost:5173, http://localhost:8080"
    # diventa:
    # ["http://localhost:5173", "http://localhost:8080"]
    return [item.strip() for item in raw_value.split(",") if item.strip()]

# Questa classe raccoglie in un unico oggetto tutte le principali configurazioni runtime della Analysis API in questo modo gli altri moduli non devono leggere ogni volta le variabili d'ambiente, ma possono usare semplicemente `settings.<nome>`
class Settings(BaseModel):
    """Snapshot validata della configurazione runtime della replica API.

    I default restano orientati alla demo locale, mentre gli override via env
    permettono di riusare lo stesso codice in Compose o in futuri overlay
    production senza hardcoding applicativo.
    """
    # Nome e versione della Analysis API
    # In `main.py` vengono usati quando viene creato l'oggetto FastAPI
    app_name: str = "SecureScan Analysis API"
    app_version: str = "0.1.0"

    # Prefisso comune degli endpoint applicativi
    # In `main.py` viene aggiunto ai router, ad esempio quelli delle analisi, del profilo e della dashboard
    api_prefix: str = "/api/v1"

    # Identificatore della singola replica dell'Analysis API, utile per distinguere le repliche quando il backend viene eseguito con più istanze dietro Kong
    instance_id: str = Field(default_factory=lambda: os.getenv("INSTANCE_ID", "analysis-api"))

    # Nome dell'host/container su cui sta eseguendo questa replica dell'Analysis API, utilizzato dal sistema che registra lo stato delle repliche API
    hostname: str = Field(default_factory=socket.gethostname)

    # Elenco delle origin che il browser può usare per effettuare richieste cross-origin (CORS) verso questa replica dell'Analysis API. In main.py questo valore viene passato al middleware CORS
    # L'origin è la combinazione di protocollo, host e porta, ad esempio: "http://localhost:5173"
    cors_origins: list[str] = Field(
        default_factory=lambda: _read_csv_env(
            "CORS_ALLOWED_ORIGINS",
            ("http://localhost:5173", "http://localhost:8080"),
        )
    )

    # Dimensione massima consentita per un file caricato dall'utente, in megabyte. Viene usata durante il caricamento di un file da analizzare in modo tale che il backend possa verificare che il file non superi questo limite
    max_upload_size_mb: int = Field(
        default_factory=lambda: _read_int_env("MAX_UPLOAD_SIZE_MB", 250),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=1024, # `le=1024` significa massimo 1024 MB (Less than or equal to)
        validate_default=True,
    )

    # Numero di secondi dopo i quali l'ultimo heartbeat del worker viene considerato troppo vecchio
    # Il worker esegue in background le analisi del file
    # Questa configurazione viene usata nella dashboard e nella pagina di stato del sistema per capire se il worker sta ancora aggiornando regolarmente il proprio stato
    worker_heartbeat_timeout_seconds: int = Field(
        default_factory=lambda: _read_int_env("WORKER_HEARTBEAT_TIMEOUT_SECONDS", 15),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=3600, # `le=3600` significa massimo 1 ora (Less than or equal to)
        validate_default=True,
    )

    # Permette di abilitare o disabilitare l'heartbeat delle repliche API
    # L'heartbeat viene usato per registrare periodicamente che una determinata replica della Analysis API è ancora attiva
    # Solo la stringa "true" viene trasformata nel booleano True
    api_heartbeat_enabled: bool = Field(
        default_factory=lambda: os.getenv("API_HEARTBEAT_ENABLED", "true").strip().lower() == "true"
    )

    # Indica ogni quanti secondi la replica API aggiorna il proprio heartbeat
    # Con il valore di default 5, ogni 5 secondi la replica segnala di essere ancora attiva
    api_heartbeat_interval_seconds: int = Field(
        default_factory=lambda: _read_int_env("API_HEARTBEAT_INTERVAL_SECONDS", 5),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=3600, # `le=3600` significa massimo 1 ora (Less than or equal to)
        validate_default=True,
    )

    # Indica dopo quanti secondi senza un nuovo heartbeat una replica API non viene più considerata attiva dal controllo dello stato del sistema
    # Con il valore di default 15, un heartbeat più vecchio di 15 secondi è considerato scaduto
    api_heartbeat_timeout_seconds: int = Field(
        default_factory=lambda: _read_int_env("API_HEARTBEAT_TIMEOUT_SECONDS", 15),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=3600, # `le=3600` significa massimo 1 ora (Less than or equal to)
        validate_default=True,
    )

    # Indica il numero di repliche della Analysis API che il sistema si aspetta di avere attive
    # Serve allo stato del sistema per confrontare le repliche previste con quelle rilevate tramite heartbeat
    # Nel deployment del progetto il valore è 2
    configured_api_replicas: int = Field(
        default_factory=lambda: _read_int_env("CONFIGURED_API_REPLICAS", 1),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=32, # `le=32` significa massimo 32 repliche (Less than or equal to)
        validate_default=True,
    )

    # Soglia usata durante l'analisi dell'entropia di un file
    # L'entropia misura quanto il contenuto del file appare casuale (più è alto e peggio è)
    entropy_medium_threshold: float = 7.2

    # Cartella in cui il backend salva i file caricati dagli utenti, così il worker può poi recuperarlo e analizzarlo
    upload_dir: str = Field(default_factory=lambda: os.getenv("UPLOAD_DIR", "/data/uploads"))

    # Cartella in cui vengono salvati gli avatar degli utenti, quando un utente carica o modifica la propria immagine profilo
    avatar_dir: str = Field(default_factory=lambda: os.getenv("AVATAR_DIR", "/data/avatars"))

    # Nome dell'host su cui è raggiungibile ClamAV; serve al sistema per collegarsi a ClamAV quando deve effettuare la scansione antivirus di un file
    clamd_host: str = Field(default_factory=lambda: os.getenv("CLAMD_HOST", "clamav"))

    # Porta su cui ClamAV accetta le connessioni; utilizzata insieme a `clamd_host` per contattare il servizio antivirus
    clamd_port: int = Field(
        default_factory=lambda: _read_int_env("CLAMD_PORT", 3310),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=65535, # `le=65535` significa massimo la porta 65535 (Less than or equal to)
        validate_default=True,
    )

    # Numero massimo di secondi da attendere quando il sistema comunica con ClamAV
    # Se ClamAV non risponde entro questo tempo, la comunicazione non rimane bloccata indefinitamente
    clamd_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("CLAMD_TIMEOUT_SECONDS", "5.0")),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=120, # `le=120` significa massimo 2 minuti (Less than or equal to)
        validate_default=True,
    )

    # Dimensione massima consentita per l'immagine profilo, espressa in MB
    # Viene controllata quando un utente carica o modifica il proprio avatar
    max_avatar_size_mb: int = Field(
        default_factory=lambda: _read_int_env("MAX_AVATAR_SIZE_MB", 5),
        gt=0, # `gt=0` significa maggiore di 0 (Greater Than)
        le=10, # `le=10` significa massimo 10 MB (Less than or equal to)
        validate_default=True,
    )

    # Permette di abilitare o disabilitare i controlli di autenticazione del backend
    # Quando è True, gli endpoint protetti verificano il token dell'utente tramite Keycloak
    auth_enabled: bool = Field(
        default_factory=lambda: os.getenv("AUTH_ENABLED", "true").strip().lower() == "true"
    )

    # Indirizzo interno usato dalla Analysis API per contattare Keycloak nella rete Docker
    # Serve alle comunicazioni dirette tra backend e Keycloak, senza passare dal browser
    keycloak_internal_url: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080")
    )

    # Nome del realm Keycloak usato da SecureScan Cloud
    # Il realm contiene gli utenti, i ruoli e i client usati per autenticazione e autorizzazione
    keycloak_realm: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_REALM", "securescan")
    )

    # Indica se sono abilitate le funzionalità che richiedono la verifica dell'email
    # Viene usata nei flussi del profilo collegati alle email actions di Keycloak
    email_verification_enabled: bool = Field(
        default_factory=lambda: os.getenv("EMAIL_VERIFICATION_ENABLED", "false").strip().lower() == "true"
    )

    # Identifica il client Keycloak da usare per le azioni effettuate tramite email
    # Viene usato, ad esempio, nei flussi in cui Keycloak deve inviare un'azione all'utente
    keycloak_email_actions_client_id: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_EMAIL_ACTIONS_CLIENT_ID", "securescan-frontend")
    )

    # URL a cui Keycloak riporta l'utente dopo aver completato un'azione tramite email
    # Il valore di default riporta alla pagina Profilo del frontend
    keycloak_email_actions_redirect_url: str = Field(
        default_factory=lambda: os.getenv(
            "KEYCLOAK_EMAIL_ACTIONS_REDIRECT_URL",
            "http://localhost:8080/profile",
        )
    )

    # Indirizzo del server SMTP usato da Keycloak per l'invio delle email
    # Il backend controlla questo valore per capire se la configurazione email è disponibile
    keycloak_smtp_host: str = Field(default_factory=lambda: os.getenv("KEYCLOAK_SMTP_HOST", "").strip())

    # Porta del server SMTP utilizzato per l'invio delle email
    keycloak_smtp_port: int = Field(
        default_factory=lambda: _read_int_env("KEYCLOAK_SMTP_PORT", 587),
        gt=0,
        le=65535,
        validate_default=True,
    )

    # Indirizzo email utilizzato come mittente delle email inviate da Keycloak
    keycloak_smtp_from: str = Field(default_factory=lambda: os.getenv("KEYCLOAK_SMTP_FROM", "").strip())

    # Nome mostrato all'utente come mittente delle email: `SecureScan Cloud`
    keycloak_smtp_from_display_name: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_SMTP_FROM_DISPLAY_NAME", "SecureScan Cloud").strip()
    )

    # Indica se il server SMTP richiede username e password per autenticarsi
    keycloak_smtp_auth: bool = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_SMTP_AUTH", "false").strip().lower() == "true"
    )

    # Username usato per autenticarsi al server SMTP, se l'autenticazione è richiesta
    keycloak_smtp_user: str = Field(default_factory=lambda: os.getenv("KEYCLOAK_SMTP_USER", "").strip())

    # Password usata per autenticarsi al server SMTP, se l'autenticazione è richiesta
    keycloak_smtp_password: str = Field(default_factory=lambda: os.getenv("KEYCLOAK_SMTP_PASSWORD", "").strip())

    # Emittente che il backend si aspetta di trovare nei token JWT ricevuti
    # Serve a verificare che il token sia stato emesso dal realm Keycloak corretto
    keycloak_issuer: str = Field(
        default_factory=lambda: os.getenv(
            "KEYCLOAK_ISSUER",
            "http://localhost:8180/realms/securescan",
        )
    )

    # URL da cui il backend recupera le chiavi pubbliche di Keycloak
    # Queste chiavi JWKS vengono usate per verificare la firma dei token JWT ricevuti dagli utenti
    keycloak_jwks_url: str = Field(
        default_factory=lambda: os.getenv(
            "KEYCLOAK_JWKS_URL",
            "http://keycloak:8080/realms/securescan/protocol/openid-connect/certs",
        )
    )

    # Identifica il servizio a cui il token JWT deve essere destinato
    # Il backend controlla questo valore per evitare di accettare token destinati ad altri servizi
    keycloak_audience: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_AUDIENCE", "securescan-api")
    )

    # Algoritmo di firma accettato durante la verifica dei token JWT (nel nostro caso i token devono essere firmati con RS256)
    keycloak_allowed_algorithms: tuple[str, ...] = ("RS256",)

    # Numero massimo di secondi da attendere quando il backend richiede le chiavi JWKS a Keycloak
    jwks_request_timeout_seconds: float = 5.0

    # Identificativo del client usato dal backend per accedere alle Admin API di Keycloak
    # Serve per effettuare operazioni amministrative su utenti e account Keycloak
    keycloak_admin_client_id: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_ADMIN_CLIENT_ID", "securescan-admin-api")
    )

    # Secret del client amministrativo
    # Viene usato insieme al client ID per autenticare il backend verso le Admin API di Keycloak
    keycloak_admin_client_secret: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_ADMIN_CLIENT_SECRET", "change-me-securescan-admin-api")
    )

    # Identificativo del client Keycloak usato quando il backend deve verificare la password dell'utente
    keycloak_password_verification_client_id: str = Field(
        default_factory=lambda: os.getenv("KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_ID", "securescan-password-verification")
    )

    # Secret associato al client usato per la verifica della password
    keycloak_password_verification_client_secret: str = Field(
        default_factory=lambda: os.getenv(
            "KEYCLOAK_PASSWORD_VERIFICATION_CLIENT_SECRET",
            "change-me-securescan-password-verification",
        )
    )

    # Numero massimo di secondi da attendere per una risposta dalle Admin API di Keycloak
    # Evita che il backend rimanga bloccato se Keycloak non risponde
    keycloak_admin_request_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("KEYCLOAK_ADMIN_REQUEST_TIMEOUT_SECONDS", "5.0")),
        gt=0,
        le=30,
        validate_default=True,
    )

    # Numero massimo di secondi da attendere quando la Analysis API controlla lo stato degli altri servizi
    # Viene usato nella funzionalità "Stato del sistema"
    monitoring_http_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("MONITORING_HTTP_TIMEOUT_SECONDS", "2.0")),
        gt=0,
        le=30,
        validate_default=True,
    )

    # Endpoint interno interrogato per controllare se Kong è raggiungibile e pronto
    # Viene usato quando il backend costruisce lo stato complessivo del sistema
    kong_status_url: str = Field(
        default_factory=lambda: os.getenv("KONG_STATUS_URL", "http://kong:8100/status/ready")
    )

    # Endpoint interrogato per controllare se Prometheus è raggiungibile e funzionante
    prometheus_health_url: str = Field(
        default_factory=lambda: os.getenv("PROMETHEUS_HEALTH_URL", "http://prometheus:9090/-/healthy")
    )

    # Endpoint interrogato per controllare lo stato di Grafana
    grafana_health_url: str = Field(
        default_factory=lambda: os.getenv("GRAFANA_HEALTH_URL", "http://grafana:3000/api/health")
    )

    # Endpoint da cui sono esposte le metriche di PostgreSQL tramite postgres-exporter
    # Viene controllato dalla Analysis API nella funzionalità "Stato del sistema"
    postgres_exporter_metrics_url: str = Field(
        default_factory=lambda: os.getenv(
            "POSTGRES_EXPORTER_METRICS_URL",
            "http://postgres-exporter:9187/metrics",
        )
    )

    # Indirizzo di connessione al database utilizzato dalla Analysis API
    # Serve al backend per leggere e salvare i dati persistenti, ad esempio quelli delle analisi
    # Nel deployment Docker Compose viene usato PostgreSQL; SQLite è il fallback se `DATABASE_URL` non è definita
    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "sqlite+pysqlite:///./analysis-api.db",
        )
    )

    # `@property` permette di usare il risultato del metodo come un normale attributo
    # Converte il limite massimo di upload da MB a byte, formato usato per controllare la dimensione reale del file
    @property
    def max_upload_size_bytes(self) -> int:
        """Return the configured upload size limit in bytes."""
        return self.max_upload_size_mb * 1024 * 1024

    # Restituisce il limite massimo di upload in forma leggibile, ad esempio `250 MB`
    # Può essere usato nei messaggi mostrati quando si comunica il limite consentito
    @property
    def max_upload_size_label(self) -> str:
        """Return the configured upload size limit as a readable label."""
        return f"{self.max_upload_size_mb} MB"

    # Converte il limite massimo dell'avatar da MB a byte
    # Viene usato per controllare la dimensione reale dell'immagine caricata nel profilo
    @property
    def max_avatar_size_bytes(self) -> int:
        """Return the configured avatar size limit in bytes."""
        return self.max_avatar_size_mb * 1024 * 1024

    # Controlla se sono presenti i parametri SMTP minimi necessari
    # Serve al backend per capire se può usare le funzionalità di Keycloak che richiedono l'invio di email
    @property
    def smtp_configured(self) -> bool:
        """Indica se il runtime dispone delle credenziali SMTP minime richieste.

        Il backend usa questa informazione solo per abilitare o meno operazioni
        che dipendono da Keycloak email actions; non invia direttamente email.
        """

        # Se manca il server SMTP oppure l'indirizzo mittente, la configurazione non è completa
        if not self.keycloak_smtp_host or not self.keycloak_smtp_from:
            return False

        # Se SMTP richiede autenticazione, devono essere presenti anche username e password
        if self.keycloak_smtp_auth and (not self.keycloak_smtp_user or not self.keycloak_smtp_password):
            return False

        # Tutti i parametri necessari sono presenti
        return True

    # Costruisce automaticamente l'URL del token endpoint di Keycloak
    # Il backend usa questo endpoint quando deve richiedere un token a Keycloak nelle comunicazioni server-to-server
    @property
    def keycloak_token_url(self) -> str:
        """Restituisce il token endpoint interno usato dalle chiamate server-side."""

        # `rstrip('/')` elimina un eventuale `/` finale per evitare URL con due slash consecutivi
        return (
            f"{self.keycloak_internal_url.rstrip('/')}/realms/{self.keycloak_realm}"
            "/protocol/openid-connect/token"
        )

    # Costruisce automaticamente l'URL di base delle Admin API di Keycloak
    # Il backend usa questo indirizzo quando deve effettuare operazioni amministrative su Keycloak
    @property
    def keycloak_admin_base_url(self) -> str:
        """Return the internal Keycloak admin API base URL."""
        return (
            f"{self.keycloak_internal_url.rstrip('/')}/admin/realms/{self.keycloak_realm}"
        )

# Crea l'oggetto `settings` che verrà importato e utilizzato dagli altri file della Analysis API
# Quando questo modulo viene caricato, vengono lette le variabili d'ambiente e costruita la configurazione
settings = Settings()
