"""Persistenza heartbeat delle repliche API.

Il repository mantiene traccia delle repliche attive nel database condiviso
per alimentare stato sistema e diagnosi HA oltre ai soli health check HTTP.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `logging` permette di registrare nei log eventuali errori durante le operazioni di persistenza degli heartbeat
import logging

# `dataclass` consente di definire una semplice struttura dati Python usata per restituire le informazioni dell'heartbeat senza esporre direttamente il modello ORM
from dataclasses import dataclass

# `datetime` rappresenta data e ora mentre `timezone` permette di utilizzare esplicitamente timestamp UTC
from datetime import datetime, timezone

# Eccezione base di SQLAlchemy utilizzata per intercettare gli errori prodotti durante le operazioni sul database
from sqlalchemy.exc import SQLAlchemyError

# `Session` rappresenta la sessione SQLAlchemy attraverso cui vengono eseguite letture, modifiche, commit e rollback sul database
from sqlalchemy.orm import Session

# Modello ORM della tabella degli heartbeat delle istanze API ed enum che rappresenta lo stato ACTIVE o STOPPED della replica
from app.db.models import ApiInstanceHeartbeatModel, ApiInstanceHeartbeatStatus


# Crea un logger associato al nome di questo modulo per registrare gli errori del repository
logger = logging.getLogger(__name__)


# Eccezione specifica del repository utilizzata per nascondere ai livelli superiori i dettagli degli errori SQLAlchemy
class ApiInstanceRegistryError(Exception):
    """Raised when API instance heartbeat persistence fails."""


# `dataclass` crea automaticamente una struttura dati semplice mentre `slots=True` evita il normale dizionario dinamico degli attributi delle istanze
@dataclass(slots=True)
class ApiInstanceHeartbeatRecord:
    """Stored API instance heartbeat information."""

    # Identificatore univoco della replica API, utilizzato anche come chiave primaria nel database
    instance_id: str

    # Nome dell'host o container sul quale è in esecuzione la replica
    hostname: str

    # Stato persistito della replica, ad esempio ACTIVE oppure STOPPED
    status: ApiInstanceHeartbeatStatus

    # Istante in cui l'istanza è stata registrata inizialmente
    started_at: datetime

    # Istante dell'ultimo heartbeat ricevuto dalla replica
    last_heartbeat_at: datetime


# Repository dedicato alla persistenza del registro operativo delle repliche API, separato dal repository che gestisce le analisi
class ApiInstanceRegistryRepository:
    """Persiste registrazione iniziale, heartbeat e stop delle repliche API."""

    # Riceve una Session SQLAlchemy già aperta e la conserva per tutte le operazioni del repository
    def __init__(self, session: Session) -> None:

        # La Session rappresenta il contesto SQLAlchemy attraverso cui questo repository esegue le operazioni sul database configurato
        self._session = session

    # Registra una replica all'avvio oppure riattiva il record già esistente con lo stesso instance_id
    def register_instance(self, instance_id: str, hostname: str) -> ApiInstanceHeartbeatRecord:
        """Crea o riattiva il record di una replica alla partenza del processo."""

        # Recupera il timestamp UTC corrente usato come momento della registrazione o dell'ultimo heartbeat
        now = datetime.now(timezone.utc)

        # Tutte le operazioni SQLAlchemy vengono protette per poter eseguire rollback e tradurre eventuali errori
        try:

            # Cerca direttamente nella tabella il record avente instance_id come chiave primaria
            record = self._session.get(ApiInstanceHeartbeatModel, instance_id)

            # Se la replica non è mai stata registrata viene creato un nuovo record
            if record is None:

                # Crea il modello ORM iniziale marcando subito l'istanza come ACTIVE
                record = ApiInstanceHeartbeatModel(
                    instance_id=instance_id,
                    hostname=hostname,
                    status=ApiInstanceHeartbeatStatus.ACTIVE,
                    started_at=now,
                    last_heartbeat_at=now,
                )

                # Aggiunge il nuovo modello ORM alla Session affinché venga inserito nel database al commit
                self._session.add(record)

            else:

                # Aggiorna l'hostname nel caso in cui il record esistesse già
                record.hostname = hostname

                # Una nuova registrazione riporta esplicitamente la replica nello stato ACTIVE
                record.status = ApiInstanceHeartbeatStatus.ACTIVE

                # Aggiorna l'ultimo heartbeat senza modificare lo started_at originario del record esistente
                record.last_heartbeat_at = now

            # Conferma definitivamente nel database l'inserimento o gli aggiornamenti effettuati
            self._session.commit()

            # Ricarica dal database il modello ORM dopo il commit così da avere i valori persistiti aggiornati
            self._session.refresh(record)

            # Converte il modello ORM in un semplice record Python prima di restituirlo
            return self._to_record(record)

        # Intercetta gli errori prodotti da SQLAlchemy durante lettura o persistenza
        except SQLAlchemyError as exc:

            # Annulla le modifiche non confermate della transazione corrente
            self._session.rollback()

            # Registra lo stack trace dell'errore includendo l'identificatore della replica coinvolta
            logger.exception("Failed to register API instance.", extra={"instance_id": instance_id})

            # Espone ai livelli superiori un'eccezione specifica del repository mantenendo quella originale come causa
            raise ApiInstanceRegistryError("Failed to register API instance.") from exc

    # Aggiorna periodicamente l'heartbeat di una replica già registrata oppure crea il record se per qualche motivo non esiste
    def touch_instance(self, instance_id: str, hostname: str) -> ApiInstanceHeartbeatRecord:
        """Aggiorna il heartbeat periodico preservando l'istante di avvio originario."""

        # Recupera il timestamp UTC del nuovo heartbeat
        now = datetime.now(timezone.utc)

        # Protegge le operazioni sul database permettendo rollback e gestione uniforme degli errori
        try:

            # Cerca il record della replica tramite la sua chiave primaria instance_id
            record = self._session.get(ApiInstanceHeartbeatModel, instance_id)

            # Se il record non esiste il metodo è in grado di crearlo direttamente
            if record is None:

                # Crea un nuovo heartbeat ACTIVE usando il momento corrente anche come started_at
                record = ApiInstanceHeartbeatModel(
                    instance_id=instance_id,
                    hostname=hostname,
                    status=ApiInstanceHeartbeatStatus.ACTIVE,
                    started_at=now,
                    last_heartbeat_at=now,
                )

                # Inserisce il nuovo modello nella Session
                self._session.add(record)

            else:

                # Aggiorna l'hostname associato alla replica
                record.hostname = hostname

                # Ogni heartbeat valido riporta o mantiene l'istanza nello stato ACTIVE
                record.status = ApiInstanceHeartbeatStatus.ACTIVE

                # Aggiorna esclusivamente l'ultimo heartbeat preservando lo started_at originario
                record.last_heartbeat_at = now

            # Rende persistenti nel database le modifiche effettuate
            self._session.commit()

            # Sincronizza nuovamente il modello ORM con il contenuto persistito
            self._session.refresh(record)

            # Restituisce una rappresentazione indipendente dal modello ORM
            return self._to_record(record)

        # Gestisce in modo uniforme qualsiasi SQLAlchemyError
        except SQLAlchemyError as exc:

            # Ripristina la transazione corrente eliminando eventuali modifiche non confermate
            self._session.rollback()

            # Registra nei log l'errore relativo all'aggiornamento dell'heartbeat
            logger.exception("Failed to update API instance heartbeat.", extra={"instance_id": instance_id})

            # Traduce l'errore SQLAlchemy nell'eccezione specifica di questo repository
            raise ApiInstanceRegistryError("Failed to update API instance heartbeat.") from exc

    # Segna una replica come STOPPED quando il processo termina attraverso uno shutdown ordinato
    def mark_stopped(self, instance_id: str) -> ApiInstanceHeartbeatRecord | None:
        """Segna una replica come arrestata durante uno shutdown pulito."""

        # Timestamp UTC utilizzato come ultimo heartbeat della replica prima dell'arresto
        now = datetime.now(timezone.utc)

        # Protegge la lettura e l'aggiornamento del record
        try:

            # Cerca il record della replica tramite instance_id
            record = self._session.get(ApiInstanceHeartbeatModel, instance_id)

            # Se non esiste alcun record non c'è nulla da marcare come STOPPED
            if record is None:

                # Annulla l'eventuale transazione corrente e termina restituendo None
                self._session.rollback()

                return None

            # Registra nel database che la replica non è più considerata attiva (imposta lo stato a STOPPED)
            record.status = ApiInstanceHeartbeatStatus.STOPPED

            # Aggiorna il timestamp dell'ultima attività registrata al momento dello shutdown
            record.last_heartbeat_at = now

            # Conferma definitivamente l'aggiornamento nel database
            self._session.commit()

            # Ricarica dal database il record dopo il commit
            self._session.refresh(record)

            # Restituisce il record convertito nella dataclass del repository
            return self._to_record(record)

        # Intercetta eventuali errori SQLAlchemy
        except SQLAlchemyError as exc:

            # Annulla le modifiche ancora pendenti nella transazione
            self._session.rollback()

            # Registra l'errore e l'identificatore della replica coinvolta
            logger.exception("Failed to mark API instance as stopped.", extra={"instance_id": instance_id})

            # Propaga un'eccezione del layer repository mantenendo quella SQLAlchemy come causa originale
            raise ApiInstanceRegistryError("Failed to mark API instance as stopped.") from exc

    # Metodo di utilità che converte il modello ORM persistito in una struttura dati Python indipendente da SQLAlchemy
    @staticmethod
    def _to_record(record: ApiInstanceHeartbeatModel) -> ApiInstanceHeartbeatRecord:

        # Costruisce il record copiando i campi ORM e normalizzando i timestamp in UTC
        return ApiInstanceHeartbeatRecord(
            instance_id=record.instance_id,
            hostname=record.hostname,
            status=record.status,
            started_at=_ensure_utc(record.started_at),
            last_heartbeat_at=_ensure_utc(record.last_heartbeat_at),
        )


# Normalizza un datetime affinché il repository restituisca sempre timestamp timezone-aware espressi in UTC
def _ensure_utc(value: datetime) -> datetime:

    # Se il valore non contiene informazioni di timezone viene interpretato esplicitamente come UTC
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    # Se il timestamp possiede già una timezone viene convertito nell'equivalente valore UTC
    return value.astimezone(timezone.utc)
