"""Modelli ORM del database applicativo SecureScan Cloud.

Qui viene descritta la forma con cui PostgreSQL salva i dati usati dal sito:
analisi, heartbeat delle repliche, heartbeat del worker e profili applicativi.

È importante distinguere questi modelli dai modelli Pydantic:
- i modelli ORM descrivono come i dati stanno nel database;
- i modelli Pydantic descrivono invece come quei dati viaggiano tra backend
  e frontend nelle API.

Password, credenziali e login non vengono salvati qui: restano completamente
gestiti da Keycloak.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `datetime` rappresenta data e ora
# `timezone` viene usato per generare timestamp esplicitamente in UTC
from datetime import datetime, timezone

# `Enum` permette di definire insiemi chiusi di valori simbolici, utilizzati qui per gli stati degli heartbeat
from enum import Enum

# SQLAlchemy è una libreria Python per interagire con database relazionali (nel progetto fa da livello intermedio tra codice python e PostgreSQL)
# Tipi SQLAlchemy utilizzati per definire il tipo delle colonne delle tabelle
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String

# Importa il tipo Enum di SQLAlchemy con un alias per distinguerlo da `Enum` di Python
from sqlalchemy import Enum as SqlEnum

# `Index` permette di dichiarare indici su colonne utilizzate frequentemente nelle ricerche
from sqlalchemy import Index

# `Mapped` indica che un attributo della classe Python è gestito dall'ORM e associato a una colonna della tabella
# `mapped_column` definisce concretamente quella colonna nel database specificandone tipo e proprietà come chiave primaria, valore che non può essere NULL, unicità o valore di default
from sqlalchemy.orm import Mapped, mapped_column

# `Base` è la classe dichiarativa SQLAlchemy da cui ereditano tutti i modelli ORM dell'applicazione
from app.db.base import Base

# Enum di dominio che rappresentano rispettivamente lo stato di un'analisi e il relativo livello di rischio
from app.models.analysis import AnalysisStatus, RiskLevel


# Converte una classe Enum nella lista dei valori testuali contenuti nei suoi elementi
ENUM_VALUES = lambda enum_cls: [item.value for item in enum_cls]
# `lambda` permette di creare una piccola funzione anonima senza darle un nome esplicito


# Funzione di supporto utilizzata come default Python per generare timestamp correnti in UTC
def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# Modello ORM che rappresenta una riga della tabella `analyses`
class AnalysisRecordModel(Base):
    """Record persistito di una singola analisi o job asincrono.

    Il `sequence_number` rimane la sorgente atomica del progressivo pubblico
    anche con più repliche API concorrenti, mentre `id` contiene la forma
    user-facing `ANL-YYYY-NNNN`.
    """

    # Nome della tabella SQL associata a questo modello ORM
    __tablename__ = "analyses"

    # Configurazione aggiuntiva della tabella: indici su hash e data di creazione e autoincremento esplicito per SQLite
    __table_args__ = (
        Index("ix_analyses_sha256", "sha256"),
        Index("ix_analyses_created_at", "created_at"),
        {"sqlite_autoincrement": True},
    )

    # Chiave primaria numerica autoincrementale generata dal database e utilizzata come progressivo interno dell'analisi
    sequence_number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identificatore pubblico dell'analisi, univoco, non nullo e indicizzato, nella forma `ANL-YYYY-NNNN`
    id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    # Nome originale del file sottoposto ad analisi
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Subject OIDC dell'utente proprietario dell'analisi; rappresenta il riferimento logico usato per applicare l'ownership
    # Il `sub` è l'identificatore dell'utente autenticato fornito da Keycloak e viene salvato per associare l'analisi al suo proprietario e consentire al backend di filtrare le analisi per utente
    owner_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Username associato al proprietario, memorizzato come informazione descrittiva
    owner_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Stato corrente del workflow dell'analisi, ad esempio queued, processing, completed oppure failed
    status: Mapped[AnalysisStatus] = mapped_column(
        SqlEnum(AnalysisStatus, native_enum=False, values_callable=ENUM_VALUES), nullable=False
    )

    # Livello di rischio associato all'analisi, rappresentato tramite l'enum `RiskLevel`
    risk_level: Mapped[RiskLevel] = mapped_column(
        SqlEnum(RiskLevel, native_enum=False, values_callable=ENUM_VALUES), nullable=False
    )

    # Timestamp UTC di creazione del record, generato lato Python tramite `utc_now`
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Timestamp UTC dell'ultimo aggiornamento; `onupdate` richiede a SQLAlchemy di rigenerarlo quando il record viene aggiornato
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # Momento in cui un worker ha iniziato effettivamente l'elaborazione del job
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Momento in cui l'elaborazione dell'analisi è terminata
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Identificatore del worker che ha preso in carico il job
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Numero di tentativi di elaborazione effettuati per questo job
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Percorso utilizzato dal backend per individuare il file salvato nello storage
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Dimensione del file espressa in byte
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # MIME type rilevato per il file (es. image/jpeg, application/pdf, text/plain, ecc.) o `None` se non rilevabile
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Hash SHA-256 del file, utilizzabile per identificarne il contenuto e confrontare file uguali (due file con nomi diversi ma stesso contenuto avranno lo stesso hash)
    # Due file con lo stesso contenuto producono lo stesso hash SHA-256, indipendentemente dal nome o dal percorso del file
    # Anche una piccola modifica di un file produce normalmente un hash completamente diverso
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Valore di entropia calcolato sul file durante l'analisi
    # L'entropia misura il livello di casualità o imprevedibilità dei byte che compongono il file
    entropy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Indica se l'estensione del file è coerente con il MIME type rilevato
    extension_matches_mime: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Esito complessivo prodotto dalla pipeline di scansione (es. clean, suspicious, malicious, scan_error)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Timestamp relativo al momento in cui è stata eseguita la scansione
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Stato restituito dal controllo effettuato tramite ClamAV
    clamav_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Nome dell'eventuale firma ClamAV che ha identificato una minaccia
    clamav_signature_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Eventuale messaggio di errore prodotto durante l'esecuzione di ClamAV
    clamav_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Stato restituito dalla scansione YARA
    yara_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Elenco strutturato dei match YARA memorizzato in una colonna JSON; una nuova lista vuota viene creata come default Python
    yara_matches: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)

    # Eventuale messaggio di errore prodotto durante la scansione YARA
    yara_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Elenco degli indicatori individuati durante l'analisi, memorizzato come struttura JSON
    indicators: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # Eventuale messaggio di errore generale associato al job o alla pipeline di analisi
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)


# Modello ORM che salva i dati di profilo persistenti gestiti dall'applicazione; non rappresenta gli utenti attualmente autenticati
class UserProfileModel(Base):
    """Estensioni profilo possedute dall'applicazione e indicizzate per subject OIDC."""

    # Nome della tabella SQL associata ai profili applicativi
    __tablename__ = "user_profiles"

    # Subject OIDC dell'utente, utilizzato come chiave primaria del profilo locale
    subject: Mapped[str] = mapped_column(String(255), primary_key=True)

    # Percorso dell'eventuale avatar associato al profilo
    avatar_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # MIME type dell'avatar memorizzato
    avatar_media_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Timestamp UTC di creazione del profilo applicativo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Timestamp UTC aggiornato da SQLAlchemy quando il profilo viene modificato
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


# Enum Python che definisce i possibili stati persistiti per un worker
class WorkerHeartbeatStatus(str, Enum):
    """Persistence status for one worker process."""

    # Il worker è considerato attivo
    ACTIVE = "active"

    # Il worker risulta arrestato
    STOPPED = "stopped"


# Modello ORM utilizzato per persistere l'heartbeat di ciascun worker
class WorkerHeartbeatModel(Base):
    """Heartbeat persistito dei worker per stato sistema e fault handling."""

    # Nome della tabella SQL che contiene gli heartbeat dei worker
    __tablename__ = "worker_heartbeats"

    # Indici utilizzati per velocizzare ricerche basate sullo stato del worker o sull'ultimo heartbeat ricevuto
    __table_args__ = (
        Index("ix_worker_heartbeats_status", "status"),
        Index("ix_worker_heartbeats_last_heartbeat_at", "last_heartbeat_at"),
    )

    # Identificatore univoco del worker e chiave primaria della tabella
    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Hostname della macchina o del container su cui è in esecuzione il worker
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stato persistente del worker, rappresentato tramite l'enum `WorkerHeartbeatStatus`
    status: Mapped[WorkerHeartbeatStatus] = mapped_column(
        SqlEnum(WorkerHeartbeatStatus, native_enum=False, values_callable=ENUM_VALUES),
        nullable=False,
    )

    # Timestamp UTC relativo all'avvio del worker
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Timestamp UTC dell'ultimo heartbeat registrato per il worker
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


# Enum Python che definisce i possibili stati persistiti per una replica della Analysis API
class ApiInstanceHeartbeatStatus(str, Enum):
    """Persistence status for one API replica."""

    # La replica API è considerata attiva
    ACTIVE = "active"

    # La replica API risulta arrestata
    STOPPED = "stopped"


# Modello ORM utilizzato per persistere l'heartbeat delle diverse repliche della Analysis API
class ApiInstanceHeartbeatModel(Base):
    """Heartbeat persistito delle repliche API per osservabilità e HA."""

    # Nome della tabella SQL che contiene gli heartbeat delle repliche API
    __tablename__ = "api_instance_heartbeats"

    # Indici utilizzati per velocizzare ricerche per stato e ultimo heartbeat delle repliche
    __table_args__ = (
        Index("ix_api_instance_heartbeats_status", "status"),
        Index("ix_api_instance_heartbeats_last_heartbeat_at", "last_heartbeat_at"),
    )

    # Identificatore univoco della replica API e chiave primaria della tabella
    instance_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Hostname della macchina o del container che esegue la replica API
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stato persistente della replica, rappresentato tramite l'enum `ApiInstanceHeartbeatStatus`
    status: Mapped[ApiInstanceHeartbeatStatus] = mapped_column(
        SqlEnum(ApiInstanceHeartbeatStatus, native_enum=False, values_callable=ENUM_VALUES),
        nullable=False,
    )

    # Timestamp UTC relativo all'avvio della replica API
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Timestamp UTC dell'ultimo heartbeat registrato per questa replica
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
