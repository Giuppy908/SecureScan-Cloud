"""Repository degli heartbeat del worker.

Questo file salva nel database il segnale periodico con cui ogni replica
worker dimostra di essere ancora attiva. I dati prodotti qui vengono letti
indirettamente soprattutto dalla pagina Stato del sistema.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# Modulo utilizzato per registrare eventuali errori durante le operazioni sul database
import logging

# `dataclass` permette di definire una struttura dati compatta per rappresentare un heartbeat
from dataclasses import dataclass

# Strumenti utilizzati per generare e normalizzare timestamp in UTC
from datetime import datetime, timezone

# Eccezione base utilizzata per intercettare gli errori prodotti da SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError

# `Session` rappresenta la sessione SQLAlchemy usata per comunicare con PostgreSQL
from sqlalchemy.orm import Session

# Modello ORM e stato utilizzati per rappresentare nel database le istanze worker
from app.db.models import WorkerHeartbeatModel, WorkerHeartbeatStatus

# Logger associato a questo modulo
logger = logging.getLogger(__name__)


# Eccezione applicativa utilizzata per nascondere al chiamante i dettagli degli errori SQLAlchemy
class WorkerRegistryError(Exception):
    """Errore durante la persistenza del segnale heartbeat del worker."""


# Rappresentazione semplificata dei dati di una replica worker registrata nel database
@dataclass(slots=True)
class WorkerHeartbeatRecord:
    """Rappresentazione semplificata di un heartbeat worker salvato nel DB."""

    # Identificatore univoco della replica worker nel registry
    worker_id: str

    # Nome dell'host dichiarato dal processo worker
    hostname: str

    # Stato corrente della replica, ad esempio ACTIVE oppure STOPPED
    status: WorkerHeartbeatStatus

    # Timestamp che indica quando il record worker è stato creato inizialmente
    started_at: datetime

    # Timestamp dell'ultimo heartbeat registrato con successo
    last_heartbeat_at: datetime


# Repository che incapsula registrazione, heartbeat periodico e arresto delle repliche worker
class WorkerRegistryRepository:
    """Gestisce registrazione iniziale, aggiornamento e stop del worker."""

    # Riceve una sessione SQLAlchemy già creata dal livello chiamante
    def __init__(self, session: Session) -> None:

        # Conserva la sessione che verrà utilizzata per le operazioni sul registry
        self._session = session

    # Registra una nuova replica worker oppure riattiva il record esistente
    def register_worker(self, worker_id: str, hostname: str) -> WorkerHeartbeatRecord:
        """Registra il worker all'avvio o lo riattiva se già esisteva."""

        # Recupera il timestamp UTC corrente da associare alla registrazione
        now = datetime.now(timezone.utc)

        try:

            # Cerca direttamente il worker tramite worker_id, che è la chiave primaria del record
            record = self._session.get(WorkerHeartbeatModel, worker_id)

            # Se il worker non è mai stato registrato viene creato un nuovo record
            if record is None:

                # Costruisce il nuovo heartbeat inizialmente in stato ACTIVE
                record = WorkerHeartbeatModel(
                    worker_id=worker_id,
                    hostname=hostname,
                    status=WorkerHeartbeatStatus.ACTIVE,
                    started_at=now,
                    last_heartbeat_at=now,
                )

                # Aggiunge il nuovo record alla sessione SQLAlchemy
                self._session.add(record)

            # Se il worker esiste già il record viene riattivato invece di crearne uno nuovo
            else:

                # Aggiorna l'hostname associato alla replica
                record.hostname = hostname

                # Riporta il worker nello stato ACTIVE
                record.status = WorkerHeartbeatStatus.ACTIVE

                # Registra un nuovo heartbeat senza modificare started_at
                record.last_heartbeat_at = now

            # Conferma nel database la creazione o riattivazione del worker
            self._session.commit()

            # Ricarica il record dal database dopo il commit
            self._session.refresh(record)

            # Converte il modello ORM nella struttura semplificata restituita al chiamante
            return self._to_record(record)

        # Gli errori SQLAlchemy vengono convertiti in WorkerRegistryError
        except SQLAlchemyError as exc:

            # Annulla la transazione che ha prodotto l'errore
            self._session.rollback()

            # Registra nel log l'errore associandolo al worker coinvolto
            logger.exception("Failed to register worker.", extra={"worker_id": worker_id})

            # Propaga un errore specifico del repository mantenendo l'eccezione originale come causa
            raise WorkerRegistryError("Failed to register worker.") from exc

    # Aggiorna periodicamente il segnale heartbeat della replica worker
    def touch_worker(self, worker_id: str, hostname: str) -> WorkerHeartbeatRecord:
        """Aggiorna il battito periodico del worker senza cambiarne l'avvio iniziale."""

        # Recupera il timestamp UTC corrente da utilizzare come nuovo heartbeat
        now = datetime.now(timezone.utc)

        try:

            # Cerca il record della replica tramite la sua chiave primaria worker_id
            record = self._session.get(WorkerHeartbeatModel, worker_id)

            # Se il record non esiste il metodo è in grado di crearlo autonomamente
            if record is None:

                # Crea un nuovo worker già in stato ACTIVE
                record = WorkerHeartbeatModel(
                    worker_id=worker_id,
                    hostname=hostname,
                    status=WorkerHeartbeatStatus.ACTIVE,
                    started_at=now,
                    last_heartbeat_at=now,
                )

                # Aggiunge il nuovo record alla sessione
                self._session.add(record)

            # Se il worker è già registrato viene semplicemente aggiornato
            else:

                # Aggiorna l'hostname associato alla replica
                record.hostname = hostname

                # Mantiene o riporta la replica nello stato ACTIVE
                record.status = WorkerHeartbeatStatus.ACTIVE

                # Aggiorna il timestamp che indica l'ultimo heartbeat ricevuto
                record.last_heartbeat_at = now

            # Salva nel database il nuovo stato dell'heartbeat
            self._session.commit()

            # Ricarica il record persistito
            self._session.refresh(record)

            # Restituisce una rappresentazione semplificata del record aggiornato
            return self._to_record(record)

        # Gli errori SQLAlchemy vengono normalizzati in WorkerRegistryError
        except SQLAlchemyError as exc:

            # Annulla le modifiche della transazione fallita
            self._session.rollback()

            # Registra l'errore associandolo al worker coinvolto
            logger.exception("Failed to update worker heartbeat.", extra={"worker_id": worker_id})

            # Propaga al livello superiore un errore specifico del repository
            raise WorkerRegistryError("Failed to update worker heartbeat.") from exc

    # Marca una replica come fermata durante uno shutdown ordinato
    def mark_stopped(self, worker_id: str) -> WorkerHeartbeatRecord | None:
        """Segna il worker come fermato in modo ordinato durante lo shutdown."""

        # Recupera il timestamp UTC corrente
        now = datetime.now(timezone.utc)

        try:

            # Cerca il record del worker tramite worker_id
            record = self._session.get(WorkerHeartbeatModel, worker_id)

            # Se il worker non è presente nel registry non esiste nulla da aggiornare
            if record is None:

                # Annulla l'eventuale transazione aperta dalla lettura
                self._session.rollback()

                return None

            # Porta esplicitamente la replica nello stato STOPPED
            record.status = WorkerHeartbeatStatus.STOPPED

            # Aggiorna anche l'ultimo heartbeat con l'istante dello shutdown ordinato
            record.last_heartbeat_at = now

            # Conferma la modifica nel database
            self._session.commit()

            # Ricarica il record dopo il commit
            self._session.refresh(record)

            # Restituisce il record convertito nella struttura semplificata
            return self._to_record(record)

        # Gli errori SQLAlchemy vengono trasformati in WorkerRegistryError
        except SQLAlchemyError as exc:

            # Annulla la transazione fallita
            self._session.rollback()

            # Registra nel log l'impossibilità di marcare il worker come fermato
            logger.exception("Failed to mark worker as stopped.", extra={"worker_id": worker_id})

            # Propaga un errore del livello repository mantenendo l'eccezione originale come causa
            raise WorkerRegistryError("Failed to mark worker as stopped.") from exc

    # Converte il modello ORM del database nella struttura WorkerHeartbeatRecord
    @staticmethod
    def _to_record(record: WorkerHeartbeatModel) -> WorkerHeartbeatRecord:

        # Copia i dati necessari normalizzando i timestamp in UTC
        return WorkerHeartbeatRecord(
            worker_id=record.worker_id,
            hostname=record.hostname,
            status=record.status,
            started_at=_ensure_utc(record.started_at),
            last_heartbeat_at=_ensure_utc(record.last_heartbeat_at),
        )


# Normalizza un datetime proveniente dal database affinché rappresenti esplicitamente UTC
def _ensure_utc(value: datetime) -> datetime:
    """Uniforma i timestamp letti dal database al fuso UTC."""

    # Se il datetime non contiene informazioni di timezone gli viene associato UTC
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    # Se possiede già una timezone viene convertito nel fuso UTC
    return value.astimezone(timezone.utc)
