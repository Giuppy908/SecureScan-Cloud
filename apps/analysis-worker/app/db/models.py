"""Modelli ORM usati dal worker per leggere e aggiornare PostgreSQL.

Qui viene descritta la forma con cui il worker vede i record già creati
dall'Analysis API. Il worker non salva password o dati di login: lavora
solo sulle tabelle tecniche che servono a pipeline malware e heartbeat.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# datetime rappresenta istanti temporali, mentre timezone permette di usare esplicitamente UTC
from datetime import datetime, timezone

# Enum permette di definire insiemi chiusi di valori validi, come gli stati di una scansione
from enum import Enum

# Tipi SQLAlchemy usati per descrivere le colonne delle tabelle mappate dal worker
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String

# L'Enum SQLAlchemy viene rinominato per distinguerlo dall'Enum Python importato sopra
from sqlalchemy import Enum as SqlEnum

# Index permette di dichiarare indici sulle colonne utilizzate frequentemente nelle query
from sqlalchemy import Index

# Mapped descrive il tipo Python di un attributo ORM, mentre mapped_column definisce la relativa colonna database
from sqlalchemy.orm import Mapped, mapped_column

# Base è la classe dichiarativa comune da cui ereditano i modelli ORM del worker
from app.db.base import Base


# Enum che rappresenta le possibili fasi del ciclo di vita di un job di analisi
class AnalysisStatus(str, Enum):
    """Stati generali di una scansione visibili anche in Cronologia."""

    # Il job è stato creato dall'Analysis API ed è in attesa di essere acquisito da un worker
    QUEUED = "queued"

    # Il job è stato acquisito da un worker ed è attualmente in elaborazione
    PROCESSING = "processing"

    # Il worker ha terminato correttamente il processing e ha persistito il risultato
    COMPLETED = "completed"

    # Il processing non è stato completato correttamente e il job è stato marcato come fallito
    FAILED = "failed"


# Enum che rappresenta il livello sintetico di rischio assegnato all'analisi
class RiskLevel(str, Enum):
    """Livello di rischio sintetico mostrato in Cronologia e Dettaglio analisi."""

    # Livello di rischio più basso
    LOW = "low"

    # Livello di rischio intermedio
    MEDIUM = "medium"

    # Livello di rischio elevato
    HIGH = "high"

    # Livello di rischio massimo previsto dal modello
    CRITICAL = "critical"


# Converte una classe Enum nella lista dei suoi valori testuali, usata da SQLAlchemy per la persistenza degli enum
ENUM_VALUES = lambda enum_cls: [item.value for item in enum_cls]


# Funzione usata come factory per ottenere timestamp UTC aggiornati al momento della creazione o modifica del record
def utc_now() -> datetime:
    """Restituisce l'istante corrente in UTC con timezone esplicita."""

    # Restituisce un datetime timezone-aware riferito all'istante corrente in UTC
    return datetime.now(timezone.utc)


# Modello ORM che rappresenta una riga della tabella PostgreSQL analyses
class AnalysisRecordModel(Base):
    """Record di analisi condiviso tra Analysis API e worker.

    La Analysis API crea il job iniziale. Il worker legge e aggiorna questo
    stesso record con stato, risultati ClamAV/YARA, hash, MIME, indicatori
    e verdict finale poi mostrati in Cronologia e Dettaglio analisi.
    """

    # Collega questa classe Python alla tabella fisica analyses del database
    __tablename__ = "analyses"

    # Configura gli indici espliciti della tabella e abilita l'autoincremento SQLite usato anche nei test
    __table_args__ = (
        # Indice sull'hash SHA-256 per rendere più efficienti eventuali query basate sul digest
        Index("ix_analyses_sha256", "sha256"),

        # Indice sulla data di creazione utile per query e ordinamenti temporali delle analisi
        Index("ix_analyses_created_at", "created_at"),

        # Mantiene un comportamento di autoincremento esplicito quando il modello viene usato con SQLite
        {"sqlite_autoincrement": True},
    )

    # Chiave primaria numerica progressiva usata internamente dal database e per ordinare i job queued
    sequence_number: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Identificatore pubblico e univoco dell'analisi, utilizzato da API, frontend e repository
    id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    # Nome originale del file caricato dall'utente e associato al job
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stato corrente del workflow della scansione, persistito usando i valori testuali dell'Enum Python
    status: Mapped[AnalysisStatus] = mapped_column(
        SqlEnum(AnalysisStatus, native_enum=False, values_callable=ENUM_VALUES), nullable=False
    )

    # Livello di rischio sintetico associato all'analisi
    risk_level: Mapped[RiskLevel] = mapped_column(
        SqlEnum(RiskLevel, native_enum=False, values_callable=ENUM_VALUES), nullable=False
    )

    # Timestamp UTC di creazione del record, valorizzato automaticamente se non specificato
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Timestamp dell'ultimo aggiornamento, inizializzato alla creazione e aggiornato nelle successive modifiche ORM
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    # Istante in cui un worker ha iniziato a elaborare il job, usato anche per individuare processing troppo vecchi
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Istante in cui il job ha raggiunto uno stato finale completed o failed
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Identificatore del worker che ha acquisito il job corrente
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Numero di volte in cui il job è stato acquisito da un worker, usato dalla logica di retry e recovery
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Percorso del file nello storage condiviso, utilizzato dal worker per recuperare i byte da analizzare
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Dimensione del file caricato espressa in byte
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # MIME type determinato durante l'analisi strutturale del file
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Digest SHA-256 calcolato sul contenuto del file e rappresentato come stringa esadecimale di 64 caratteri
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Valore di entropia calcolato sui byte del file durante l'analisi strutturale
    entropy: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Indica se l'estensione dichiarata del file è coerente con il MIME type rilevato
    extension_matches_mime: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Esito applicativo finale prodotto dalla pipeline, ad esempio clean, suspicious, malicious o scan_error
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Istante associato al completamento della scansione malware
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Stato restituito dalla scansione ClamAV, ad esempio clean, found, error, timeout o unavailable
    clamav_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Nome della firma ClamAV rilevata quando la scansione trova una corrispondenza
    clamav_signature_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Dettaglio dell'eventuale errore prodotto durante la scansione ClamAV
    clamav_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Stato restituito dalla scansione YARA
    yara_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Elenco strutturato dei match YARA serializzato in una colonna JSON
    yara_matches: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)

    # Dettaglio dell'eventuale errore verificatosi durante la scansione YARA
    yara_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Elenco degli indicatori prodotti dalla pipeline e mostrabili come motivazioni del risultato
    indicators: Mapped[list[str]] = mapped_column(JSON, nullable=False)

    # Messaggio associato a un errore generale del processing del job
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)


# Enum che rappresenta lo stato registrato del worker nel meccanismo di heartbeat persistente
class WorkerHeartbeatStatus(str, Enum):
    """Stati minimi del segnale heartbeat del worker."""

    # Il worker risulta registrato come attivo
    ACTIVE = "active"

    # Il worker è stato arrestato ordinatamente ed è stato marcato come fermo
    STOPPED = "stopped"


# Modello ORM che rappresenta una riga della tabella worker_heartbeats
class WorkerHeartbeatModel(Base):
    """Heartbeat persistito del worker usato soprattutto da Stato del sistema.

    Questo record è diverso da un normale health check Docker: dimostra che
    il processo worker continua davvero a eseguire il proprio ciclo applicativo.
    """

    # Collega il modello alla tabella PostgreSQL che mantiene lo stato persistente dei worker
    __tablename__ = "worker_heartbeats"

    # Definisce gli indici utilizzati per interrogare più efficientemente stato e freschezza degli heartbeat
    __table_args__ = (
        # Indice sullo stato del worker, utile per selezionare quelli marcati come active
        Index("ix_worker_heartbeats_status", "status"),

        # Indice sul timestamp dell'ultimo heartbeat, utile per verificare se un worker è ancora recente
        Index("ix_worker_heartbeats_last_heartbeat_at", "last_heartbeat_at"),
    )

    # Identificatore univoco del worker e chiave primaria della tabella heartbeat
    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)

    # Nome dell'host o container su cui il worker dichiara di essere in esecuzione
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stato persistente del worker, salvato come valore testuale active oppure stopped
    status: Mapped[WorkerHeartbeatStatus] = mapped_column(
        SqlEnum(WorkerHeartbeatStatus, native_enum=False, values_callable=ENUM_VALUES),
        nullable=False,
    )

    # Timestamp UTC associato alla registrazione iniziale del record heartbeat
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    # Timestamp UTC dell'ultimo heartbeat registrato, aggiornato periodicamente dal repository del worker
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
