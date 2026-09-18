"""Repository che assegna e aggiorna i job di analisi del worker.

Questo file non corrisponde direttamente a una pagina del sito, ma governa il
passaggio più delicato del flusso:
Nuova analisi -> job `queued` in PostgreSQL -> worker -> record finale
visibile in Cronologia, Dettaglio analisi e Dashboard.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# Modulo utilizzato per registrare gli errori che avvengono durante le operazioni sul database
import logging

# `dataclass` permette di definire strutture dati compatte usate per trasferire job e risultati
from dataclasses import dataclass

# Strumenti utilizzati per timestamp UTC e per calcolare quando un job processing è diventato troppo vecchio
from datetime import datetime, timedelta, timezone

# `select` permette di costruire query SQLAlchemy per recuperare i record delle analisi
from sqlalchemy import select

# Eccezione base utilizzata per intercettare gli errori prodotti da SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError

# `Session` rappresenta la sessione SQLAlchemy attraverso cui il repository comunica con il database
from sqlalchemy.orm import Session

# Modello ORM delle analisi ed enum utilizzati per stato e livello di rischio
from app.db.models import AnalysisRecordModel, AnalysisStatus, RiskLevel

# Logger associato a questo modulo
logger = logging.getLogger(__name__)


# Eccezione applicativa che nasconde al worker i dettagli degli errori SQLAlchemy
class RepositoryError(Exception):
    """Errore del livello repository durante lettura o aggiornamento dei job."""


# Contiene soltanto i dati del record necessari al worker per elaborare un'analisi
@dataclass(slots=True)
class AnalysisJob:
    """Dati minimi che il worker deve conoscere per elaborare un job."""

    # Identificatore pubblico dell'analisi
    id: str

    # Nome originale del file caricato dall'utente
    file_name: str

    # Dimensione del file espressa in byte
    size_bytes: int

    # Percorso del file temporaneo nello storage condiviso tra Analysis API e worker
    storage_path: str

    # Numero di volte in cui questo job è stato acquisito per essere processato
    attempt_count: int

    # Timestamp di creazione del job
    created_at: datetime

    # Timestamp dell'inizio dell'attuale processing, oppure None se il job non è in lavorazione
    processing_started_at: datetime | None

    # Identificatore del worker che ha acquisito il job, oppure None se non è assegnato
    worker_id: str | None


# Raccoglie il risultato prodotto dalla malware pipeline che dovrà essere archiviato nel database
@dataclass(slots=True)
class CompletedAnalysis:
    """Risultato finale che il repository salva dopo la pipeline malware."""

    # Livello di rischio finale determinato dalla pipeline
    risk_level: RiskLevel

    # MIME type determinato durante l'analisi strutturale
    mime_type: str

    # Hash SHA-256 calcolato sul contenuto del file
    sha256: str

    # Entropia Shannon calcolata sui byte del file
    entropy: float

    # Indica se estensione del file e MIME type risultano coerenti
    extension_matches_mime: bool

    # Esito generale finale della pipeline, ad esempio clean, suspicious, malicious o scan_error
    verdict: str

    # Timestamp associato alla scansione
    scanned_at: datetime

    # Stato normalizzato restituito dalla scansione ClamAV
    clamav_status: str

    # Nome della firma ClamAV rilevata, se presente
    clamav_signature_name: str | None

    # Eventuale errore prodotto durante la scansione ClamAV
    clamav_error: str | None

    # Stato normalizzato restituito dalla scansione YARA
    yara_status: str

    # Elenco serializzabile dei match YARA rilevati
    yara_matches: list[dict[str, object]]

    # Eventuale errore prodotto durante la scansione YARA
    yara_error: str | None

    # Indicatori descrittivi prodotti dalle diverse fasi della pipeline
    indicators: list[str]

    # Eventuale errore complessivo associato al risultato finale
    error_message: str | None = None


# Repository che incapsula query, transazioni e transizioni di stato dei job del worker
class AnalysisWorkerRepository:
    """Nasconde al worker i dettagli SQL di acquisizione e aggiornamento job."""

    # Riceve una sessione SQLAlchemy già creata dal livello chiamante
    def __init__(self, session: Session) -> None:

        # Conserva la sessione che verrà utilizzata da tutte le operazioni del repository
        self._session = session

    # Cerca il prossimo job queued disponibile e lo assegna al worker
    def acquire_next_queued_analysis(self, worker_id: str) -> AnalysisJob | None:
        """Assegna al worker il job `queued` più vecchio disponibile.

        `SKIP LOCKED` permette a più repliche worker di collaborare senza
        prendere lo stesso record contemporaneamente. In pratica, se un altro
        worker ha già bloccato una riga, questa replica la salta e cerca un
        job diverso.
        """

        try:

            # Costruisce la query che cerca il primo job ancora in stato queued
            statement = (
                select(AnalysisRecordModel)

                # Considera soltanto le analisi che devono ancora essere processate
                .where(AnalysisRecordModel.status == AnalysisStatus.QUEUED)

                # Ordina per sequence_number crescente per privilegiare i job inseriti prima
                .order_by(AnalysisRecordModel.sequence_number.asc())

                # Il worker acquisisce al massimo un job per ogni ciclo di polling
                .limit(1)

                # Blocca la riga selezionata e ignora quelle già bloccate da altri worker
                .with_for_update(skip_locked=True)
            )

            try:

                # Esegue la query e restituisce direttamente il singolo record selezionato
                record = self._session.scalar(statement)

            # Se il database non supporta questa modalità di locking viene tentata una query più semplice
            except SQLAlchemyError:

                # Annulla la transazione che ha prodotto l'errore prima di eseguire una nuova query
                self._session.rollback()

                # Ripete la selezione senza FOR UPDATE SKIP LOCKED
                record = self._session.scalar(
                    select(AnalysisRecordModel)
                    .where(AnalysisRecordModel.status == AnalysisStatus.QUEUED)
                    .order_by(AnalysisRecordModel.sequence_number.asc())
                    .limit(1)
                )

            # Se non esistono job queued il repository non restituisce alcun lavoro
            if record is None:

                # Chiude l'eventuale transazione aperta dalla lettura
                self._session.rollback()

                return None

            # Recupera il timestamp UTC corrente da associare all'inizio del processing
            now = datetime.now(timezone.utc)

            # Quando un job viene assegnato, ogni risultato precedente viene
            # azzerato per evitare che Cronologia o Dettaglio analisi mostrino
            # dati parziali lasciati da un tentativo fallito precedente.
            record.status = AnalysisStatus.PROCESSING

            # Registra quando è iniziato questo tentativo di processing
            record.processing_started_at = now

            # Un nuovo tentativo non può essere già completato
            record.completed_at = None

            # Associa il job all'istanza worker che lo ha acquisito
            record.worker_id = worker_id

            # Incrementa il numero di tentativi ogni volta che il job viene acquisito
            record.attempt_count += 1

            # Aggiorna il timestamp dell'ultima modifica del record
            record.updated_at = now

            # Rimuove i risultati strutturali eventualmente rimasti da un tentativo precedente
            record.mime_type = None
            record.sha256 = None
            record.entropy = None
            record.extension_matches_mime = None
            record.verdict = None
            record.scanned_at = None

            # Rimuove eventuali risultati precedenti di ClamAV
            record.clamav_status = None
            record.clamav_signature_name = None
            record.clamav_error = None

            # Rimuove eventuali risultati precedenti di YARA
            record.yara_status = None
            record.yara_matches = []
            record.yara_error = None

            # Rimuove indicatori ed eventuale errore del tentativo precedente
            record.indicators = []
            record.error_message = None

            # Conferma atomicamente nel database l'assegnazione del job e tutte le modifiche eseguite
            self._session.commit()

            # Ricarica il record dal database dopo il commit
            self._session.refresh(record)

            # Converte il modello ORM in una struttura più semplice utilizzabile dal worker
            return self._to_job(record)

        # Gli errori SQLAlchemy vengono convertiti in RepositoryError per non esporre il livello DB al worker
        except SQLAlchemyError as exc:

            # Annulla le modifiche della transazione corrente
            self._session.rollback()

            # Registra nel log lo stack trace dell'errore
            logger.exception("Failed to acquire a queued analysis job.")

            # Propaga un errore specifico del livello repository mantenendo l'eccezione originale come causa
            raise RepositoryError("Failed to acquire queued analysis.") from exc

    # Salva il risultato completo della pipeline e porta il job da processing a completed
    def mark_completed(self, analysis_id: str, result: CompletedAnalysis) -> None:
        """Scrive il risultato finale della pipeline nel record condiviso."""

        try:

            # Recupera dal database l'analisi corrispondente all'identificatore ricevuto
            record = self._session.scalar(
                select(AnalysisRecordModel).where(AnalysisRecordModel.id == analysis_id)
            )

            # Non è possibile completare un'analisi che non esiste
            if record is None:
                raise RepositoryError(f"Analysis '{analysis_id}' was not found.")

            # La transizione a completed è consentita soltanto da processing
            if record.status != AnalysisStatus.PROCESSING:
                raise RepositoryError(f"Analysis '{analysis_id}' is not processing.")

            # Recupera il timestamp UTC corrente per completamento e aggiornamento
            now = datetime.now(timezone.utc)

            # Porta il job nello stato terminale completed
            record.status = AnalysisStatus.COMPLETED

            # Salva il livello di rischio finale prodotto dalla pipeline
            record.risk_level = result.risk_level

            # Salva i risultati dell'analisi strutturale
            record.mime_type = result.mime_type
            record.sha256 = result.sha256
            record.entropy = result.entropy
            record.extension_matches_mime = result.extension_matches_mime

            # Salva verdict e timestamp della scansione
            record.verdict = result.verdict
            record.scanned_at = result.scanned_at

            # Salva il risultato della scansione ClamAV
            record.clamav_status = result.clamav_status
            record.clamav_signature_name = result.clamav_signature_name
            record.clamav_error = result.clamav_error

            # Salva il risultato e gli eventuali match della scansione YARA
            record.yara_status = result.yara_status
            record.yara_matches = result.yara_matches
            record.yara_error = result.yara_error

            # Salva gli indicatori complessivi prodotti dalla pipeline
            record.indicators = result.indicators

            # Salva l'eventuale messaggio di errore associato al risultato finale
            record.error_message = result.error_message

            # Registra quando il job è stato completato
            record.completed_at = now

            # Aggiorna il timestamp dell'ultima modifica
            record.updated_at = now

            # Il file non deve più essere utilizzato dopo il completamento e il riferimento viene rimosso dal database
            record.storage_path = None

            # Conferma tutte le modifiche nel database
            self._session.commit()

        # Gli errori logici già espressi come RepositoryError vengono propagati senza modificarli
        except RepositoryError:

            # Annulla la transazione corrente
            self._session.rollback()

            raise

        # Gli errori SQLAlchemy vengono normalizzati in RepositoryError
        except SQLAlchemyError as exc:

            # Annulla la transazione fallita
            self._session.rollback()

            # Registra l'errore associandolo all'analisi coinvolta
            logger.exception("Failed to mark analysis as completed.", extra={"analysis_id": analysis_id})

            raise RepositoryError("Failed to mark analysis as completed.") from exc

    # Porta un job processing a failed quando il worker non riesce a completarne l'elaborazione
    def mark_failed(self, analysis_id: str, error_message: str) -> None:
        """Marca il job come fallito quando la pipeline non può completarsi."""

        try:

            # Recupera il record corrispondente all'analisi da marcare come fallita
            record = self._session.scalar(
                select(AnalysisRecordModel).where(AnalysisRecordModel.id == analysis_id)
            )

            # Non è possibile modificare un'analisi inesistente
            if record is None:
                raise RepositoryError(f"Analysis '{analysis_id}' was not found.")

            # Il metodo accetta solamente job ancora in stato processing
            if record.status != AnalysisStatus.PROCESSING:
                raise RepositoryError(f"Analysis '{analysis_id}' cannot fail from status '{record.status.value}'.")

            # Recupera il timestamp UTC corrente
            now = datetime.now(timezone.utc)

            # Porta il job nello stato terminale failed
            record.status = AnalysisStatus.FAILED

            # Elimina eventuali risultati parziali dell'analisi strutturale
            record.mime_type = None
            record.sha256 = None
            record.entropy = None
            record.extension_matches_mime = None
            record.verdict = None
            record.scanned_at = None

            # Elimina eventuali risultati parziali della scansione ClamAV
            record.clamav_status = None
            record.clamav_signature_name = None
            record.clamav_error = None

            # Elimina eventuali risultati parziali della scansione YARA
            record.yara_status = None
            record.yara_matches = []
            record.yara_error = None

            # Elimina eventuali indicatori parziali
            record.indicators = []

            # Salva il motivo tecnico per cui il processamento è fallito
            record.error_message = error_message

            # Registra quando il job è entrato nello stato failed
            record.completed_at = now

            # Aggiorna il timestamp dell'ultima modifica
            record.updated_at = now

            # Rimuove dal database il riferimento al file temporaneo
            record.storage_path = None

            # Conferma la transizione a failed nel database
            self._session.commit()

        # Gli errori logici del repository vengono propagati direttamente
        except RepositoryError:

            # Annulla la transazione corrente
            self._session.rollback()

            raise

        # Gli errori SQLAlchemy vengono convertiti in RepositoryError
        except SQLAlchemyError as exc:

            # Annulla la transazione fallita
            self._session.rollback()

            # Registra nel log il fallimento dell'aggiornamento
            logger.exception("Failed to mark analysis as failed.", extra={"analysis_id": analysis_id})

            raise RepositoryError("Failed to mark analysis as failed.") from exc

    # Recupera i job rimasti processing oltre il timeout previsto
    def recover_stale_processing_jobs(
        self,
        *,
        processing_timeout_seconds: int,
        max_attempts: int,
    ) -> tuple[int, int]:
        """Recupera i job rimasti bloccati troppo a lungo in `processing`.

        Se un worker si ferma a metà elaborazione, un job potrebbe restare
        bloccato. Questa procedura lo rimette in `queued` oppure lo segna
        `failed` se ha già superato il numero massimo di tentativi.
        """

        # Recupera il timestamp UTC corrente
        now = datetime.now(timezone.utc)

        # Calcola il timestamp limite oltre il quale un processing viene considerato stale
        threshold = now - timedelta(seconds=processing_timeout_seconds)

        # Conta quanti job vengono rimessi in coda
        requeued = 0

        # Conta quanti job vengono falliti definitivamente
        failed = 0

        try:

            # Costruisce la query che cerca tutti i job processing oltre la soglia temporale
            statement = (
                select(AnalysisRecordModel)
                .where(
                    AnalysisRecordModel.status == AnalysisStatus.PROCESSING,
                    AnalysisRecordModel.processing_started_at.is_not(None),
                    AnalysisRecordModel.processing_started_at < threshold,
                )

                # Blocca i record trovati evitando quelli già gestiti da altre transazioni
                .with_for_update(skip_locked=True)
            )

            try:

                # Recupera tutti i record stale trovati dalla query
                records = self._session.scalars(statement).all()

            # Se il database non supporta il locking richiesto viene utilizzata una query senza FOR UPDATE
            except SQLAlchemyError:

                # Annulla la transazione che ha prodotto l'errore
                self._session.rollback()

                # Ripete la ricerca dei job stale senza locking specifico
                records = self._session.scalars(
                    select(AnalysisRecordModel).where(
                        AnalysisRecordModel.status == AnalysisStatus.PROCESSING,
                        AnalysisRecordModel.processing_started_at.is_not(None),
                        AnalysisRecordModel.processing_started_at < threshold,
                    )
                ).all()

            # Analizza ogni job processing considerato stale
            for record in records:

                # Se il numero massimo di tentativi è già stato raggiunto il job fallisce definitivamente
                if record.attempt_count >= max_attempts:

                    # Porta il job nello stato terminale failed
                    record.status = AnalysisStatus.FAILED

                    # Elimina eventuali risultati strutturali parziali
                    record.mime_type = None
                    record.sha256 = None
                    record.entropy = None
                    record.extension_matches_mime = None
                    record.verdict = None
                    record.scanned_at = None

                    # Elimina eventuali risultati parziali ClamAV
                    record.clamav_status = None
                    record.clamav_signature_name = None
                    record.clamav_error = None

                    # Elimina eventuali risultati parziali YARA
                    record.yara_status = None
                    record.yara_matches = []
                    record.yara_error = None

                    # Elimina gli indicatori eventualmente presenti
                    record.indicators = []

                    # Memorizza il motivo del fallimento definitivo
                    record.error_message = "Processing timed out and max attempts were exceeded."

                    # Registra il timestamp di completamento del job fallito
                    record.completed_at = now

                    # Rimuove il riferimento al file perché non verranno eseguiti altri tentativi
                    record.storage_path = None

                    # Incrementa il contatore dei recovery terminati in failure
                    failed += 1

                # Se esistono ancora tentativi disponibili il job viene rimesso in coda
                else:

                    # Riporta il job nello stato queued per consentire un nuovo claim
                    record.status = AnalysisStatus.QUEUED

                    # Elimina eventuali risultati strutturali parziali
                    record.mime_type = None
                    record.sha256 = None
                    record.entropy = None
                    record.extension_matches_mime = None
                    record.verdict = None
                    record.scanned_at = None

                    # Elimina eventuali risultati parziali ClamAV
                    record.clamav_status = None
                    record.clamav_signature_name = None
                    record.clamav_error = None

                    # Elimina eventuali risultati parziali YARA
                    record.yara_status = None
                    record.yara_matches = []
                    record.yara_error = None

                    # Elimina gli indicatori e il precedente errore
                    record.indicators = []
                    record.error_message = None

                    # Il job non è ancora terminato perché dovrà essere riprocessato
                    record.completed_at = None

                    # Incrementa il contatore dei job rimessi in coda
                    requeued += 1

                # Un job recuperato non è più associato al precedente tentativo di processing
                record.processing_started_at = None

                # Rimuove l'associazione con il worker che lo stava elaborando
                record.worker_id = None

                # Aggiorna il timestamp dell'ultima modifica
                record.updated_at = now

            # Salva in un'unica transazione tutte le modifiche effettuate sui job stale
            self._session.commit()

            # Restituisce separatamente il numero di job riaccodati e falliti
            return requeued, failed

        # Gli errori SQLAlchemy durante il recovery vengono convertiti in RepositoryError
        except SQLAlchemyError as exc:

            # Annulla tutte le modifiche della transazione corrente
            self._session.rollback()

            # Registra nel log il fallimento del recovery
            logger.exception("Failed to recover stale jobs.")

            raise RepositoryError("Failed to recover stale jobs.") from exc

    # Restituisce tutti i job ordinati per sequence_number, principalmente per supportare i test
    def list_all(self) -> list[AnalysisJob]:
        """Restituisce tutti i job, usato soprattutto nei test."""

        # Recupera tutti i record nell'ordine in cui sono stati creati
        records = self._session.scalars(
            select(AnalysisRecordModel).order_by(AnalysisRecordModel.sequence_number.asc())
        ).all()

        # Converte ogni modello ORM nella struttura AnalysisJob utilizzata dal worker
        return [self._to_job(record) for record in records]

    # Converte un AnalysisRecordModel del database nella struttura più semplice AnalysisJob
    @staticmethod
    def _to_job(record: AnalysisRecordModel) -> AnalysisJob:

        # Copia dal modello ORM soltanto i dati necessari al worker
        return AnalysisJob(
            id=record.id,
            file_name=record.file_name,
            size_bytes=record.size_bytes,

            # Se il percorso è NULL nel database viene trasformato in stringa vuota
            storage_path=record.storage_path or "",

            attempt_count=record.attempt_count,

            # I timestamp vengono normalizzati esplicitamente in UTC
            created_at=_ensure_utc(record.created_at),

            processing_started_at=(
                _ensure_utc(record.processing_started_at)
                if record.processing_started_at is not None
                else None
            ),

            worker_id=record.worker_id,
        )


# Normalizza un datetime proveniente dal database affinché rappresenti esplicitamente UTC
def _ensure_utc(value: datetime) -> datetime:
    """Normalizza i timestamp letti dal database verso UTC esplicito."""

    # Se il database restituisce un datetime senza timezone gli viene associato UTC
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    # Se il datetime possiede già una timezone viene convertito in UTC
    return value.astimezone(timezone.utc)
