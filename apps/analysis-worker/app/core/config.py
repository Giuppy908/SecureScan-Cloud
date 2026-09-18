"""Configurazione runtime del SecureScan Analysis Worker.

Questo file non rappresenta una pagina dell'interfaccia, ma controlla quasi
tutto il comportamento del processo background:
- dove leggere i job (`DATABASE_URL`);
- come raggiungere ClamAV (`CLAMD_HOST`, `CLAMD_PORT`);
- dove trovare le regole YARA (`YARA_RULES_DIR`);
- con quale frequenza interrogare PostgreSQL;
- quando considerare bloccato un job `processing`;
- come identificare la replica worker corrente.

Sono parametri runtime e non hardcoded nella logica perché possono cambiare
tra demo locale, test e deployment futuri senza dover riscrivere il codice.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# Modulo utilizzato per leggere le variabili d'ambiente del processo
import os

# Modulo utilizzato per ottenere l'hostname della macchina o del container
import socket

# Path permette di costruire in modo portabile il percorso della directory delle regole YARA
from pathlib import Path

# uuid4 viene usato per generare un suffisso casuale nell'identificatore del worker
from uuid import uuid4

# BaseModel definisce il modello Pydantic delle configurazioni, mentre Field permette di impostare default e vincoli
from pydantic import BaseModel, Field


# Genera un worker_id quando non viene fornito esplicitamente tramite variabile d'ambiente
def default_worker_id() -> str:
    """Genera un identificatore univoco quando l'ambiente non ne fornisce uno.

    Il `worker_id` permette di capire quale replica ha preso in carico un job
    e quale heartbeat appartiene a quale processo nella pagina Stato del sistema.
    """

    # Recupera l'hostname locale eliminando eventuali spazi
    hostname = socket.gethostname().strip()

    # Se è disponibile un hostname, lo combina con i primi 8 caratteri di un UUID casuale
    if hostname:
        return f"{hostname}-{uuid4().hex[:8]}"

    # Se l'hostname non è disponibile usa il prefisso worker seguito da un suffisso UUID
    return f"worker-{uuid4().hex[:8]}"


# Determina quale identificatore assegnare alla replica worker corrente
def resolve_worker_id() -> str:
    """Preferisce `WORKER_ID` esplicito, altrimenti genera un ID locale robusto."""

    # Legge WORKER_ID dall'ambiente e considera vuota anche una stringa composta solamente da spazi
    configured_worker_id = os.getenv("WORKER_ID", "").strip()

    # Se WORKER_ID è stato configurato viene utilizzato direttamente
    if configured_worker_id:
        return configured_worker_id

    # In assenza di un valore esplicito viene generato automaticamente un nuovo identificatore
    return default_worker_id()


# Calcola il percorso predefinito della directory che contiene le regole YARA del worker
def resolve_default_yara_rules_dir() -> str:
    """Calcola la directory regole YARA inclusa nel repository/immagine worker."""

    # Parte dalla posizione di config.py, risale fino alla directory analysis-worker e aggiunge rules
    return str(Path(__file__).resolve().parents[2] / "rules")


# Modello Pydantic che raccoglie e valida tutte le principali configurazioni runtime del worker
class Settings(BaseModel):
    """Impostazioni runtime del worker validate all'avvio.

    Il modello raccoglie in un solo punto tutte le variabili environment più
    importanti. In questo modo polling, heartbeat e pipeline malware usano
    valori coerenti e verificati fin dall'avvio del processo.
    """

    # Nome visualizzato dall'applicazione FastAPI del worker
    app_name: str = "SecureScan Analysis Worker"

    # Versione applicativa esposta dal worker
    app_version: str = "0.1.0"

    # URL del database utilizzato dal worker, con fallback SQLite se DATABASE_URL non è impostata
    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL",
            "sqlite+pysqlite:///./analysis-worker.db",
        )
    )

    # Directory prevista per gli upload condivisi, anche se il worker operativo usa il percorso storage_path salvato nel DB
    upload_dir: str = Field(default_factory=lambda: os.getenv("UPLOAD_DIR", "/data/uploads"))

    # Host TCP del servizio ClamAV
    clamd_host: str = Field(default_factory=lambda: os.getenv("CLAMD_HOST", "clamav"))

    # Porta TCP di ClamAV, validata nell'intervallo delle porte consentite
    clamd_port: int = Field(
        default_factory=lambda: int(os.getenv("CLAMD_PORT", "3310")),
        gt=0,
        le=65535,
        validate_default=True,
    )

    # Timeout massimo della comunicazione con ClamAV espresso in secondi
    clamd_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("CLAMD_TIMEOUT_SECONDS", "120")),
        gt=0,
        le=3600,
        validate_default=True,
    )

    # Directory contenente le regole YARA, configurabile tramite environment
    yara_rules_dir: str = Field(
        default_factory=lambda: os.getenv("YARA_RULES_DIR", resolve_default_yara_rules_dir())
    )

    # Timeout massimo concesso al matching YARA
    yara_match_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("YARA_MATCH_TIMEOUT_SECONDS", "30")),
        gt=0,
        le=600,
        validate_default=True,
    )

    # Soglia di entropia utilizzata dall'analisi strutturale per individuare file ad alta entropia
    entropy_medium_threshold: float = Field(
        default_factory=lambda: float(os.getenv("ENTROPY_MEDIUM_THRESHOLD", "7.2"))
    )

    # Intervallo in secondi tra due cicli di polling del worker
    poll_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("WORKER_POLL_INTERVAL_SECONDS", "1")),
        gt=0,
        le=3600,
        validate_default=True,
    )

    # Durata minima artificiale del processing, configurabile soprattutto per scenari demo
    min_processing_seconds: float = Field(
        default_factory=lambda: float(os.getenv("WORKER_MIN_PROCESSING_SECONDS", "0")),
        ge=0,
        validate_default=True,
    )

    # Intervallo tra due heartbeat consecutivi inviati dal worker al database
    heartbeat_interval_seconds: int = Field(
        default_factory=lambda: int(os.getenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "5")),
        gt=0,
        le=3600,
        validate_default=True,
    )

    # Tempo oltre il quale un job rimasto processing viene considerato stale e candidato al recovery
    processing_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("WORKER_PROCESSING_TIMEOUT_SECONDS", "120")),
        gt=0,
        le=86400,
        validate_default=True,
    )

    # Numero massimo di tentativi consentiti prima di fallire definitivamente un job durante il recovery
    max_attempts: int = Field(
        default_factory=lambda: int(os.getenv("WORKER_MAX_ATTEMPTS", "3")),
        gt=0,
        le=100,
        validate_default=True,
    )

    # Identificatore della replica worker, letto da WORKER_ID oppure generato automaticamente
    worker_id: str = Field(default_factory=resolve_worker_id)

    # Hostname del processo corrente, usato nel registry degli heartbeat
    hostname: str = Field(default_factory=lambda: socket.gethostname().strip() or "unknown-host")

    # Porta configurata per il servizio health del worker
    health_port: int = Field(
        default_factory=lambda: int(os.getenv("WORKER_HEALTH_PORT", "8081")),
        gt=0,
        le=65535,
        validate_default=True,
    )


# Istanzia una sola configurazione di modulo, caricando environment e validando i valori durante l'import
settings = Settings()
