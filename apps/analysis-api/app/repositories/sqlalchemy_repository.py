"""Repository SQLAlchemy usato dal runtime reale della Analysis API.

Questo è il file che traduce le esigenze delle pagine del sito in query SQL.
Serve direttamente o indirettamente:
- Cronologia, per elenco paginato e filtrato;
- Dettaglio analisi, per il recupero di un singolo record;
- Dashboard, per statistiche e recenti;
- worker, per acquisire e completare i job;
- funzioni amministrative e di manutenzione.

La sua responsabilità principale è applicare query corrette senza caricare
in memoria tutta la tabella delle analisi.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# Modulo standard Python utilizzato per produrre messaggi di log
import logging

# `datetime` gestisce data e ora, `timedelta` rappresenta intervalli temporali e `timezone` permette di lavorare esplicitamente in UTC
from datetime import datetime, timedelta, timezone

# `uuid4` genera identificatori UUID casuali utilizzati per creare l'ID temporaneo PENDING prima che il database assegni il progressivo
from uuid import uuid4

# `Depends` implementa il sistema di dependency injection di FastAPI e viene utilizzato per ricevere automaticamente la sessione database
from fastapi import Depends

# Funzioni SQLAlchemy utilizzate per costruire condizioni AND/OR, DELETE, funzioni SQL e query SELECT
from sqlalchemy import and_, delete, func, or_, select

# Eccezione base di SQLAlchemy utilizzata per intercettare errori relativi alle operazioni sul database
from sqlalchemy.exc import SQLAlchemyError

# `Session` rappresenta la sessione ORM attraverso cui il repository esegue query e modifiche sul database
from sqlalchemy.orm import Session

# Modello ORM che rappresenta una riga della tabella `analyses`
from app.db.models import AnalysisRecordModel

# Dependency che crea e fornisce la sessione SQLAlchemy utilizzata durante la richiesta HTTP
from app.db.session import get_db_session

# Modelli di dominio utilizzati come input e output delle operazioni del repository
from app.models.analysis import (
    Analysis,
    AnalysisCompletionResult,
    AnalysisCreateResult,
    AnalysisPage,
    AnalysisJob,
    AnalysisStatus,
    AnalysisVerdict,
    QueuedAnalysisCreate,
    RiskLevel,
)

# `AnalysisRepository` definisce il contratto del repository, mentre `RepositoryError` rappresenta gli errori esposti da questo layer
from app.repositories.base import AnalysisRepository, RepositoryError

# Logger associato al nome corrente del modulo per registrare gli errori senza gestirli con semplici print
logger = logging.getLogger(__name__)


# Implementazione SQLAlchemy del contratto `AnalysisRepository`, responsabile dell'accesso alla tabella `analyses`
class SqlAlchemyAnalysisRepository(AnalysisRepository):
    """Gestisce le analisi nel database PostgreSQL condiviso dalle repliche API."""

    # Il repository riceve una Session già creata: non apre e non chiude direttamente la sessione database
    def __init__(self, session: Session) -> None:
        # Salva la sessione ricevuta affinché tutti i metodi del repository possano utilizzarla
        self._session = session

    # Persiste nel database un'analisi per la quale sono già disponibili i risultati completi
    def create(self, analysis_data: AnalysisCreateResult) -> Analysis:
        """Persiste un'analisi già completa.

        Questo percorso è oggi secondario rispetto alla coda worker, ma resta
        disponibile per compatibilità e test del dominio.
        """

        # Costruisce l'oggetto ORM da inserire nella tabella `analyses` copiando i valori dal modello di input
        record = AnalysisRecordModel(
            # Identificatore temporaneo univoco usato finché il database non assegna il `sequence_number`
            id=f"PENDING-{uuid4().hex[:24]}",

            # Nome originale del file analizzato
            file_name=analysis_data.file_name,

            # Subject OIDC del proprietario dell'analisi, usato per l'ownership
            owner_sub=analysis_data.owner_sub,

            # Username del proprietario, conservato come informazione descrittiva
            owner_username=analysis_data.owner_username,

            # Stato corrente dell'analisi, ad esempio completed o failed in questo percorso
            status=analysis_data.status,

            # Livello di rischio associato al risultato dell'analisi
            risk_level=analysis_data.risk_level,

            # Dimensione del file espressa in byte
            size_bytes=analysis_data.size_bytes,

            # MIME type rilevato per il file
            mime_type=analysis_data.mime_type,

            # Hash SHA-256 calcolato sul contenuto del file
            sha256=analysis_data.sha256,

            # Valore di entropia calcolato sul contenuto del file
            entropy=analysis_data.entropy,

            # Indica se l'estensione dichiarata del file è coerente con il MIME type rilevato
            extension_matches_mime=analysis_data.extension_matches_mime,

            # Esito complessivo prodotto dalla pipeline di scansione
            verdict=analysis_data.verdict,

            # Timestamp relativo al momento in cui è stata eseguita la scansione
            scanned_at=analysis_data.scanned_at,

            # Stato del controllo effettuato tramite ClamAV
            clamav_status=analysis_data.clamav_status,

            # Nome dell'eventuale firma ClamAV che ha identificato una minaccia
            clamav_signature_name=analysis_data.clamav_signature_name,

            # Eventuale messaggio di errore prodotto durante l'esecuzione di ClamAV
            clamav_error=analysis_data.clamav_error,

            # Stato della scansione effettuata tramite YARA
            yara_status=analysis_data.yara_status,

            # Converte ciascun modello Pydantic relativo a un match YARA in un dizionario serializzabile nella colonna JSON
            yara_matches=[match.model_dump() for match in analysis_data.yara_matches],

            yara_error=analysis_data.yara_error,
            indicators=analysis_data.indicators,
            error_message=analysis_data.error_message,

            # Questo percorso rappresenta un'analisi già completata e quindi non necessita di conservare un file in attesa del worker
            storage_path=None,

            processing_started_at=None,

            # Se lo stato ricevuto è già terminale viene registrato immediatamente anche il timestamp di completamento
            completed_at=(
                datetime.now(timezone.utc)
                if analysis_data.status in (AnalysisStatus.COMPLETED, AnalysisStatus.FAILED)
                else None
            ),
            worker_id=None,
            attempt_count=0,
        )

        try:
            # Registra il nuovo oggetto ORM nella sessione come record da inserire
            self._session.add(record)

            # Invia l'INSERT al database senza terminare la transazione, permettendo di ottenere il sequence_number autoincrementale
            self._session.flush()

            # Il progressivo pubblico viene costruito solo dopo il flush: è il database ad assegnare in modo atomico `sequence_number`
            # flush() serve a sincronizzare con il database le modifiche pendenti presenti nella Session SQLAlchemy, senza però chiudere la transazione.
            if record.sequence_number is None:
                # Protezione nel caso anomalo in cui il database non abbia assegnato il progressivo previsto
                raise RepositoryError("Database did not assign sequence_number during flush.")

            # Sostituisce l'ID temporaneo con l'identificatore pubblico costruito a partire da anno e sequence_number
            record.id = self._build_analysis_id(record.sequence_number, record.created_at.year)

            # Conferma definitivamente INSERT e aggiornamento dell'ID concludendo la transazione
            self._session.commit()

            # Ricarica l'oggetto ORM dal database in modo da avere lo stato persistito aggiornato
            self._session.refresh(record)

        # Gli errori già appartenenti al layer repository vengono propagati dopo aver annullato la transazione
        except RepositoryError:
            self._session.rollback()
            raise

        # Gli errori SQLAlchemy vengono convertiti nell'eccezione astratta `RepositoryError`
        except SQLAlchemyError as exc:
            self._session.rollback()

            # Registra nei log l'errore insieme ad alcune informazioni utili per diagnosticarlo
            logger.exception(
                "Failed to persist direct analysis into the database.",
                extra={"file_name": analysis_data.file_name, "pending_id": record.id},
            )

            # `from exc` mantiene collegata l'eccezione SQLAlchemy originale alla nuova eccezione del repository
            raise RepositoryError("Failed to persist analysis.") from exc

        # Converte il record ORM persistente nel modello di dominio utilizzato dal resto dell'applicazione
        return self._to_domain(record)

    # Crea nel database il record iniziale di un nuovo job asincrono ancora in attesa di elaborazione
    def create_queued_analysis(self, analysis_data: QueuedAnalysisCreate) -> Analysis:
        """Salva il job iniziale creato dalla pagina Nuova analisi."""

        # Costruisce il record iniziale con stato QUEUED e senza risultati di scansione perché il worker non lo ha ancora elaborato
        record = AnalysisRecordModel(
            # ID temporaneo necessario perché l'ID pubblico può essere costruito solo dopo aver ottenuto sequence_number dal database
            id=f"PENDING-{uuid4().hex[:24]}",
            file_name=analysis_data.file_name,
            owner_sub=analysis_data.owner_sub,
            owner_username=analysis_data.owner_username,

            # Un nuovo job entra inizialmente nello stato QUEUED
            status=AnalysisStatus.QUEUED,

            # Il livello LOW costituisce il valore iniziale prima che la pipeline produca il risultato effettivo
            risk_level=RiskLevel.LOW,

            size_bytes=analysis_data.size_bytes,

            # I risultati seguenti non esistono ancora perché il file deve ancora essere elaborato dal worker
            mime_type=None,
            sha256=None,
            entropy=None,
            extension_matches_mime=None,
            verdict=None,
            scanned_at=None,
            clamav_status=None,
            clamav_signature_name=None,
            clamav_error=None,
            yara_status=None,
            yara_matches=[],
            yara_error=None,
            indicators=[],
            error_message=None,

            # Percorso del file nello storage condiviso che consentirà successivamente al worker di recuperarlo
            storage_path=analysis_data.storage_path,

            processing_started_at=None,
            completed_at=None,
            worker_id=None,
            attempt_count=0,
        )

        try:
            # Inserisce il nuovo oggetto nella sessione SQLAlchemy
            self._session.add(record)

            # Esegue l'INSERT senza commit per ottenere il sequence_number assegnato atomicamente dal database
            self._session.flush()

            # Verifica che il database abbia realmente assegnato il progressivo tecnico
            if record.sequence_number is None:
                raise RepositoryError("Database did not assign sequence_number during flush.")

            # Costruisce l'ID pubblico dell'analisi utilizzando anno e sequence_number
            record.id = self._build_analysis_id(record.sequence_number, record.created_at.year)

            # Conferma definitivamente la transazione
            self._session.commit()

            # Rilegge dal database il record appena persistito
            self._session.refresh(record)

        except RepositoryError:
            # Un errore applicativo durante la creazione causa l'annullamento della transazione corrente
            self._session.rollback()
            raise

        except SQLAlchemyError as exc:
            # Un errore SQLAlchemy causa rollback per riportare la sessione a uno stato consistente
            self._session.rollback()

            # Registra l'errore includendo dati utili alla diagnosi
            logger.exception(
                "Failed to persist queued analysis into the database.",
                extra={
                    "file_name": analysis_data.file_name,
                    "storage_path": analysis_data.storage_path,
                    "pending_id": record.id,
                },
            )

            # Nasconde al layer superiore il dettaglio SQLAlchemy esponendo un errore del repository
            raise RepositoryError("Failed to persist analysis.") from exc

        # Restituisce al resto dell'applicazione il modello di dominio e non direttamente l'oggetto ORM
        return self._to_domain(record)

    # Cerca il job QUEUED più vecchio e lo assegna atomicamente al worker indicato
    def acquire_next_queued_analysis(self, worker_id: str) -> AnalysisJob | None:
        """Consegna al worker il job in coda più vecchio senza duplicazioni.

        `FOR UPDATE SKIP LOCKED` evita che due worker prendano la stessa analisi
        quando la piattaforma elabora più file in parallelo.
        """
        try:
            # Costruisce la query che seleziona il job QUEUED con sequence_number più basso, cioè il più vecchio ancora disponibile
            statement = (
                select(AnalysisRecordModel)
                .where(AnalysisRecordModel.status == AnalysisStatus.QUEUED)
                .order_by(AnalysisRecordModel.sequence_number.asc())
                .limit(1)

                # Blocca la riga selezionata e ignora eventuali righe già bloccate da un'altra transazione concorrente
                .with_for_update(skip_locked=True)
            )

            # `scalar()` esegue la query e restituisce direttamente il singolo oggetto ORM selezionato
            record = self._session.scalar(statement)

            # Se non esistono job disponibili non viene assegnato nulla al worker
            if record is None:
                # Annulla la transazione di lettura aperta dalla sessione prima di restituire l'assenza di job
                self._session.rollback()
                return None

            # Memorizza una sola volta il timestamp corrente utilizzato per tutta la transizione di acquisizione
            now = datetime.now(timezone.utc)

            # Il job passa formalmente da QUEUED a PROCESSING
            record.status = AnalysisStatus.PROCESSING

            # Ogni nuovo tentativo azzera gli esiti precedenti così il frontend non mostra dati parziali se un job viene recuperato dopo un fault
            record.processing_started_at = now
            record.completed_at = None

            # Registra quale worker ha acquisito il job
            record.worker_id = worker_id

            # Incrementa il numero di tentativi effettuati sul job
            record.attempt_count += 1

            # Aggiorna esplicitamente il timestamp dell'ultima modifica
            record.updated_at = now

            # Cancella eventuali risultati di tentativi precedenti prima di una nuova elaborazione
            record.mime_type = None
            record.sha256 = None
            record.entropy = None
            record.extension_matches_mime = None
            record.verdict = None
            record.scanned_at = None
            record.clamav_status = None
            record.clamav_signature_name = None
            record.clamav_error = None
            record.yara_status = None
            record.yara_matches = []
            record.yara_error = None
            record.indicators = []
            record.error_message = None

            # Conferma atomicamente l'assegnazione del job al worker e tutte le modifiche al record
            self._session.commit()

            # Ricarica il record dopo il commit
            self._session.refresh(record)

            # Restituisce una rappresentazione specifica del job contenente solo le informazioni necessarie alla lavorazione
            return self._to_job(record)

        except SQLAlchemyError as exc:
            # Qualsiasi errore DB annulla la transazione di acquisizione
            self._session.rollback()

            # Registra l'errore nel sistema di logging
            logger.exception("Failed to acquire queued analysis job.")

            # Converte l'errore SQLAlchemy in un errore del layer repository
            raise RepositoryError("Failed to acquire queued analysis.") from exc

    # Porta esplicitamente una specifica analisi dallo stato QUEUED allo stato PROCESSING
    def mark_processing(self, analysis_id: str, worker_id: str) -> AnalysisJob:
        """Move a queued job to processing explicitly."""
        try:
            # Cerca l'analisi tramite ID pubblico e richiede un lock sulla riga per proteggerne la transizione concorrente
            record = self._session.scalar(
                select(AnalysisRecordModel)
                .where(AnalysisRecordModel.id == analysis_id)
                .with_for_update(skip_locked=True)
            )

            # La transizione non può avvenire se l'analisi richiesta non esiste
            if record is None:
                raise RepositoryError(f"Analysis '{analysis_id}' was not found.")

            # La transizione è valida esclusivamente se il job si trova ancora in stato QUEUED
            if record.status != AnalysisStatus.QUEUED:
                raise RepositoryError(f"Analysis '{analysis_id}' is not queued.")

            # Timestamp comune alla transizione
            now = datetime.now(timezone.utc)

            # Imposta il nuovo stato ed associa il job al worker che lo elaborerà
            record.status = AnalysisStatus.PROCESSING
            record.processing_started_at = now
            record.completed_at = None
            record.worker_id = worker_id
            record.attempt_count += 1
            record.updated_at = now

            # Rimuove eventuali risultati precedenti prima del nuovo tentativo di elaborazione
            record.mime_type = None
            record.sha256 = None
            record.entropy = None
            record.extension_matches_mime = None
            record.verdict = None
            record.scanned_at = None
            record.clamav_status = None
            record.clamav_signature_name = None
            record.clamav_error = None
            record.yara_status = None
            record.yara_matches = []
            record.yara_error = None
            record.indicators = []
            record.error_message = None

            # Conferma la transizione di stato e gli aggiornamenti associati
            self._session.commit()

            # Sincronizza nuovamente l'oggetto ORM con quanto persistito
            self._session.refresh(record)

            # Restituisce la rappresentazione interna del job
            return self._to_job(record)

        except RepositoryError:
            # Anche gli errori di dominio del repository provocano il rollback della transazione
            self._session.rollback()
            raise

        except SQLAlchemyError as exc:
            self._session.rollback()

            # Registra ID dell'analisi coinvolta per facilitare il troubleshooting
            logger.exception("Failed to mark analysis as processing.", extra={"analysis_id": analysis_id})

            raise RepositoryError("Failed to mark analysis as processing.") from exc

    # Completa un job in PROCESSING salvando nel record tutti i risultati prodotti dalla pipeline
    def mark_completed(self, analysis_id: str, result: AnalysisCompletionResult) -> Analysis:
        """Mark a processing job as completed."""
        try:
            # Recupera e blocca la riga relativa all'analisi da completare
            record = self._session.scalar(
                select(AnalysisRecordModel)
                .where(AnalysisRecordModel.id == analysis_id)
                .with_for_update(skip_locked=True)
            )

            # Impedisce l'aggiornamento di un'analisi inesistente
            if record is None:
                raise RepositoryError(f"Analysis '{analysis_id}' was not found.")

            # Una analisi può essere completata tramite questo metodo solo se risulta attualmente PROCESSING
            if record.status != AnalysisStatus.PROCESSING:
                raise RepositoryError(f"Analysis '{analysis_id}' is not processing.")

            # Timestamp utilizzato per completamento e aggiornamento del record
            now = datetime.now(timezone.utc)

            # Porta il workflow nello stato terminale COMPLETED
            record.status = AnalysisStatus.COMPLETED

            # Copia nel record tutti i risultati della pipeline di analisi
            record.risk_level = result.risk_level
            record.mime_type = result.mime_type
            record.sha256 = result.sha256
            record.entropy = result.entropy
            record.extension_matches_mime = result.extension_matches_mime
            record.verdict = result.verdict
            record.scanned_at = result.scanned_at
            record.clamav_status = result.clamav_status
            record.clamav_signature_name = result.clamav_signature_name
            record.clamav_error = result.clamav_error
            record.yara_status = result.yara_status

            # Converte i match YARA in dizionari memorizzabili nella colonna JSON
            record.yara_matches = [match.model_dump() for match in result.yara_matches]

            record.yara_error = result.yara_error
            record.indicators = result.indicators
            record.error_message = result.error_message

            # Registra quando l'elaborazione è terminata
            record.completed_at = now
            record.updated_at = now

            # Dopo il completamento il database non mantiene più il percorso del file temporaneo associato al job
            record.storage_path = None

            # Conferma in un'unica transazione sia lo stato COMPLETED sia tutti i risultati della scansione
            self._session.commit()

            # Ricarica il record persistente
            self._session.refresh(record)

            # Restituisce il risultato come modello di dominio
            return self._to_domain(record)

        # Se viene sollevato un errore già appartenente al layer repository, annulla la transazione corrente e propaga la stessa eccezione al chiamante
        except RepositoryError:
            self._session.rollback()
            raise

        # Se si verifica un errore SQLAlchemy, annulla la transazione e lo converte in un errore più generico del repository
        except SQLAlchemyError as exc:
            self._session.rollback()

            # Registra nel log l'errore insieme all'ID dell'analisi coinvolta per facilitare la diagnosi del problema
            logger.exception("Failed to mark analysis as completed.", extra={"analysis_id": analysis_id})

            # Solleva un RepositoryError mantenendo collegata l'eccezione SQLAlchemy originale tramite `from exc`
            raise RepositoryError("Failed to mark analysis as completed.") from exc

    # Porta un job PROCESSING nello stato terminale FAILED e registra il motivo dell'errore
    def mark_failed(self, analysis_id: str, error_message: str) -> Analysis:
        """Mark a queued or processing job as failed."""
        try:
            # Cerca e blocca la riga da modificare per evitare aggiornamenti concorrenti incompatibili
            record = self._session.scalar(
                select(AnalysisRecordModel)
                .where(AnalysisRecordModel.id == analysis_id)
                .with_for_update(skip_locked=True)
            )

            # Non è possibile fallire un'analisi che non esiste
            if record is None:
                raise RepositoryError(f"Analysis '{analysis_id}' was not found.")

            # Il codice accetta concretamente la transizione a FAILED soltanto a partire dallo stato PROCESSING
            if record.status != AnalysisStatus.PROCESSING:
                raise RepositoryError(f"Analysis '{analysis_id}' cannot fail from status '{record.status.value}'.")

            # Timestamp comune utilizzato per registrare il fallimento
            now = datetime.now(timezone.utc)

            # Imposta lo stato terminale FAILED
            record.status = AnalysisStatus.FAILED

            # Elimina eventuali risultati parziali perché il job non è stato completato correttamente
            record.mime_type = None
            record.sha256 = None
            record.entropy = None
            record.extension_matches_mime = None
            record.verdict = None
            record.scanned_at = None
            record.clamav_status = None
            record.clamav_signature_name = None
            record.clamav_error = None
            record.yara_status = None
            record.yara_matches = []
            record.yara_error = None
            record.indicators = []

            # Memorizza invece il messaggio che descrive il fallimento della pipeline
            record.error_message = error_message

            # Un job fallito viene comunque considerato terminato dal punto di vista del workflow
            record.completed_at = now
            record.updated_at = now

            # Il riferimento al file temporaneo non viene più conservato nel record
            record.storage_path = None

            # Conferma atomicamente il fallimento e la pulizia dei risultati
            self._session.commit()

            # Rilegge lo stato persistente
            self._session.refresh(record)

            # Converte il record ORM aggiornato nel modello di dominio `Analysis` restituito al chiamante
            return self._to_domain(record)

        # Se viene sollevato un errore già appartenente al layer repository, annulla la transazione e propaga la stessa eccezione
        except RepositoryError:
            self._session.rollback()
            raise

        # Se si verifica un errore SQLAlchemy, annulla la transazione e lo converte in un errore del repository
        except SQLAlchemyError as exc:
            self._session.rollback()

            # Registra nel log l'errore insieme all'ID dell'analisi che si stava tentando di marcare come fallita
            logger.exception("Failed to mark analysis as failed.", extra={"analysis_id": analysis_id})

            # Solleva un RepositoryError mantenendo l'eccezione SQLAlchemy originale come causa tramite `from exc`
            raise RepositoryError("Failed to mark analysis as failed.") from exc

    # Recupera job rimasti troppo a lungo in PROCESSING, ad esempio in seguito al fault del worker che li aveva acquisiti
    def recover_stale_processing_jobs(
        self,
        *,
        processing_timeout_seconds: int,
        max_attempts: int,
    ) -> tuple[int, int]:
        """Recupera job bloccati in `processing` dopo fault o timeout del worker."""

        # Timestamp corrente utilizzato come riferimento per calcolare quali job sono ormai considerati stale (vecchio)
        now = datetime.now(timezone.utc)

        # Un job è considerato stale se `processing_started_at` è precedente a questa soglia temporale
        threshold = now - timedelta(seconds=processing_timeout_seconds)

        # Contatori restituiti dal metodo per indicare quanti job vengono rimessi in coda e quanti vengono definitivamente falliti
        requeued = 0
        failed = 0

        try:
            # Recupera tutti i job PROCESSING il cui avvio è più vecchio della soglia, bloccandone le righe durante il recovery
            records = self._session.scalars(
                select(AnalysisRecordModel)
                .where(
                    AnalysisRecordModel.status == AnalysisStatus.PROCESSING,
                    AnalysisRecordModel.processing_started_at.is_not(None),
                    AnalysisRecordModel.processing_started_at < threshold,
                )
                .with_for_update(skip_locked=True)
            ).all()

            # Esamina individualmente ogni job bloccato
            for record in records:

                # Se il numero massimo di tentativi è già stato raggiunto, il job non viene più rimesso in coda
                if record.attempt_count >= max_attempts:
                    # Il job viene definitivamente marcato come FAILED
                    record.status = AnalysisStatus.FAILED

                    # Vengono eliminati gli eventuali risultati parziali del tentativo interrotto
                    record.mime_type = None
                    record.sha256 = None
                    record.entropy = None
                    record.extension_matches_mime = None
                    record.verdict = None
                    record.scanned_at = None
                    record.clamav_status = None
                    record.clamav_signature_name = None
                    record.clamav_error = None
                    record.yara_status = None
                    record.yara_matches = []
                    record.yara_error = None
                    record.indicators = []

                    # Memorizza una spiegazione esplicita del fallimento dovuto a timeout e superamento dei tentativi
                    record.error_message = "Processing timed out and max attempts were exceeded."

                    # Registra il momento terminale e rimuove il percorso del file dal record
                    record.completed_at = now
                    record.storage_path = None

                    # Incrementa il numero di job definitivamente falliti durante questa operazione di recovery
                    failed += 1

                else:
                    # Se sono ancora disponibili tentativi, il job torna nello stato QUEUED e potrà essere acquisito nuovamente
                    record.status = AnalysisStatus.QUEUED

                    # Pulisce tutti i risultati eventualmente prodotti dal tentativo precedente
                    record.mime_type = None
                    record.sha256 = None
                    record.entropy = None
                    record.extension_matches_mime = None
                    record.verdict = None
                    record.scanned_at = None
                    record.clamav_status = None
                    record.clamav_signature_name = None
                    record.clamav_error = None
                    record.yara_status = None
                    record.yara_matches = []
                    record.yara_error = None
                    record.indicators = []
                    record.error_message = None
                    record.completed_at = None

                    # Incrementa il numero di job rimessi in coda
                    requeued += 1

                # Qualunque sia l'esito del recovery, il job non è più associato al precedente tentativo PROCESSING
                record.processing_started_at = None
                record.worker_id = None
                record.updated_at = now

            # Conferma in un'unica transazione tutte le modifiche effettuate sui job stale
            self._session.commit()

            # Restituisce rispettivamente il numero di job rimessi in coda e definitivamente falliti
            return requeued, failed

        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("Failed to recover stale processing jobs.")
            raise RepositoryError("Failed to recover stale processing jobs.") from exc

    # Restituisce tutte le analisi visibili al chiamante, con eventuale filtro per proprietario
    def list_all(self, owner_sub: str | None = None) -> list[Analysis]:
        """Restituisce tutte le analisi visibili, ordinate newest-first."""
        try:
            # Costruisce inizialmente una SELECT sulla tabella completa delle analisi
            statement = select(AnalysisRecordModel)

            # Se viene fornito owner_sub, limita la query alle sole analisi appartenenti a quel subject OIDC
            if owner_sub is not None:
                statement = statement.where(AnalysisRecordModel.owner_sub == owner_sub)

            # Esegue la SELECT ordinando prima le analisi più recenti e usando l'ID come secondo criterio deterministico
            records = self._session.scalars(
                statement.order_by(
                    AnalysisRecordModel.created_at.desc(),
                    AnalysisRecordModel.id.desc(),
                )
            ).all()

        except SQLAlchemyError as exc:
            # Le operazioni di sola lettura trasformano l'errore SQLAlchemy senza eseguire qui un rollback esplicito
            raise RepositoryError("Failed to list analyses.") from exc

        # Converte ogni record ORM nel corrispondente modello di dominio
        return [self._to_domain(record) for record in records]

    # Restituisce una singola pagina di analisi applicando filtri e paginazione direttamente nel database
    def list_page(
        self,
        *,
        owner_sub: str | None = None,
        search: str | None = None,
        status: AnalysisStatus | None = None,
        risk_level: RiskLevel | None = None,
        owner_filter: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> AnalysisPage:
        """Restituisce una pagina realmente server-side con count filtrato.

        L'ordine applicato è: scope RBAC, filtri opzionali, count del risultato
        filtrato, ordinamento deterministico, quindi offset e limit.
        """
        try:
            # Costruisce una sola lista di condizioni riutilizzata sia per il conteggio sia per il recupero della pagina
            conditions = self._build_list_conditions(
                owner_sub=owner_sub,
                search=search,
                status=status,
                risk_level=risk_level,
                owner_filter=owner_filter,
            )

            # Esegue COUNT direttamente nel database per conoscere il numero totale di record che soddisfano i filtri
            total = int(
                self._session.scalar(
                    select(func.count()).select_from(AnalysisRecordModel).where(*conditions)
                )
                or 0
            )

            # Calcola quanti record devono essere saltati in base alla pagina richiesta
            offset = (page - 1) * page_size

            # Recupera esclusivamente i record della pagina corrente senza caricare l'intera tabella in memoria
            records = self._session.scalars(
                select(AnalysisRecordModel)
                .where(*conditions)
                .order_by(
                    AnalysisRecordModel.created_at.desc(),
                    AnalysisRecordModel.id.desc(),
                )
                .offset(offset)
                .limit(page_size)
            ).all()

        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to list analyses.") from exc

        # Calcola il numero totale di pagine mediante divisione intera arrotondata verso l'alto
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        # Restituisce sia gli elementi della pagina sia i metadati necessari alla paginazione del frontend
        return AnalysisPage(
            items=[self._to_domain(record) for record in records],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    # Recupera una singola analisi tramite ID pubblico, applicando opzionalmente anche il vincolo di ownership
    def get_by_id(self, analysis_id: str, owner_sub: str | None = None) -> Analysis | None:
        """Return one analysis if present."""
        try:
            # Costruisce la SELECT che cerca l'analisi con l'ID richiesto
            statement = select(AnalysisRecordModel).where(AnalysisRecordModel.id == analysis_id)

            # Se viene specificato owner_sub, l'analisi viene restituita soltanto se appartiene anche a quel proprietario
            if owner_sub is not None:
                statement = statement.where(AnalysisRecordModel.owner_sub == owner_sub)

            # Esegue la query e restituisce il singolo record ORM oppure None
            record = self._session.scalar(statement)

        except SQLAlchemyError as exc:
            raise RepositoryError("Failed to retrieve analysis.") from exc

        # Converte il record ORM nel modello di dominio solo quando il record esiste
        return self._to_domain(record) if record is not None else None

    # Elimina tutti i record delle analisi e restituisce prima i percorsi dei file ancora associati ai record
    def clear(self) -> list[str]:
        """Delete all analyses and return associated storage paths."""
        try:
            # Recupera i soli storage_path non nulli prima di cancellare i record che li contengono
            storage_paths = self._session.scalars(
                select(AnalysisRecordModel.storage_path).where(AnalysisRecordModel.storage_path.is_not(None))
            ).all()

            # Esegue una DELETE sull'intera tabella `analyses`
            self._session.execute(delete(AnalysisRecordModel))

            # Conferma definitivamente la cancellazione dei record
            self._session.commit()

            # Restituisce al chiamante soltanto i path effettivamente valorizzati, che potranno essere gestiti dal layer storage
            return [path for path in storage_paths if path]

        except SQLAlchemyError as exc:
            # In caso di errore la cancellazione viene annullata
            self._session.rollback()
            raise RepositoryError("Failed to delete analyses.") from exc

    # Metodo di utilità indipendente dall'istanza che costruisce l'identificatore pubblico leggibile dell'analisi
    @staticmethod
    def _build_analysis_id(sequence_number: int, year: int) -> str:
        """Build the public analysis identifier."""

        # `:04d` rappresenta il numero su almeno quattro cifre aggiungendo zeri iniziali, ad esempio 7 diventa 0007
        return f"ANL-{year}-{sequence_number:04d}"

    # Helper che traduce i filtri ricevuti dal repository in condizioni SQLAlchemy riutilizzabili
    @staticmethod
    def _build_list_conditions(
        *,
        owner_sub: str | None,
        search: str | None,
        status: AnalysisStatus | None,
        risk_level: RiskLevel | None,
        owner_filter: str | None,
    ) -> list[object]:
        """Costruisce le clausole SQL condivise tra count e query paginata."""

        # Lista inizialmente vuota in cui vengono aggiunte solamente le condizioni effettivamente richieste
        conditions: list[object] = []

        # Limita i risultati alle analisi appartenenti al subject corrente quando viene applicato lo scope di ownership
        if owner_sub is not None:
            conditions.append(AnalysisRecordModel.owner_sub == owner_sub)

        # Aggiunge un ulteriore eventuale filtro esplicito sul proprietario
        if owner_filter is not None:
            conditions.append(AnalysisRecordModel.owner_sub == owner_filter)

        # Traduce lo stato richiesto nella condizione SQL coerente con la rappresentazione mostrata dal frontend
        if status is not None:
            conditions.append(SqlAlchemyAnalysisRepository._build_presentation_status_condition(status))

        # Filtra le analisi in base al livello di rischio richiesto
        if risk_level is not None:
            conditions.append(AnalysisRecordModel.risk_level == risk_level)

        # Normalizza la stringa di ricerca eliminando spazi esterni e convertendola in minuscolo
        normalized_search = (search or "").strip().lower()

        # Applica la ricerca soltanto quando dopo la normalizzazione rimane effettivamente del testo
        if normalized_search:
            conditions.append(
                # È sufficiente che il testo sia contenuto nel nome file oppure nell'ID dell'analisi
                or_(
                    func.lower(AnalysisRecordModel.file_name).contains(normalized_search),
                    func.lower(AnalysisRecordModel.id).contains(normalized_search),
                )
            )

        # Tutte le condizioni presenti nella lista verranno successivamente combinate dalla clausola WHERE
        return conditions

    # Costruisce il filtro database tenendo conto della differenza tra stato interno del workflow e stato presentato in GUI
    @staticmethod
    def _build_presentation_status_condition(status: AnalysisStatus):
        """Costruisce la condizione SQL coerente con lo stato mostrato in GUI.

        In Cronologia il frontend presenta `completed + scan_error` come
        "Fallita". Il filtro server-side deve quindi usare la stessa semantica
        per mantenere coerenti tabella, totale e paginazione.
        """

        # La voce FAILED della GUI comprende sia i job realmente FAILED sia le analisi completate il cui verdict è SCAN_ERROR
        if status == AnalysisStatus.FAILED:
            return or_(
                AnalysisRecordModel.status == AnalysisStatus.FAILED,
                and_(
                    AnalysisRecordModel.status == AnalysisStatus.COMPLETED,
                    AnalysisRecordModel.verdict == AnalysisVerdict.SCAN_ERROR,
                ),
            )

        # La voce COMPLETED esclude invece le analisi che, pur avendo workflow completato, hanno prodotto il verdict SCAN_ERROR
        if status == AnalysisStatus.COMPLETED:
            return or_(
                and_(
                    AnalysisRecordModel.status == AnalysisStatus.COMPLETED,
                    AnalysisRecordModel.verdict.is_(None),
                ),
                and_(
                    AnalysisRecordModel.status == AnalysisStatus.COMPLETED,
                    AnalysisRecordModel.verdict != AnalysisVerdict.SCAN_ERROR,
                ),
            )

        # Per gli altri stati non è necessaria alcuna traduzione e viene confrontato direttamente lo stato persistito
        return AnalysisRecordModel.status == status

    # Converte un oggetto ORM proveniente dalla tabella `analyses` nel modello di dominio `Analysis`
    @staticmethod
    def _to_domain(record: AnalysisRecordModel) -> Analysis:
        """Map an ORM record to the API domain model."""

        # Normalizza i timestamp principali in UTC prima di inserirli nel modello restituito dall'API
        created_at = SqlAlchemyAnalysisRepository._ensure_utc(record.created_at)
        updated_at = SqlAlchemyAnalysisRepository._ensure_utc(record.updated_at)

        # Costruisce il modello di dominio copiando i dati persistiti dall'oggetto ORM
        return Analysis(
            id=record.id,
            file_name=record.file_name,
            owner_sub=record.owner_sub,
            owner_username=record.owner_username,
            status=record.status,
            risk_level=record.risk_level,
            created_at=created_at,
            updated_at=updated_at,
            size_bytes=record.size_bytes,
            mime_type=record.mime_type,
            sha256=record.sha256,
            entropy=record.entropy,
            extension_matches_mime=record.extension_matches_mime,
            verdict=record.verdict,

            # `scanned_at` viene normalizzato in UTC soltanto quando è presente
            scanned_at=(
                SqlAlchemyAnalysisRepository._ensure_utc(record.scanned_at)
                if record.scanned_at is not None
                else None
            ),

            clamav_status=record.clamav_status,
            clamav_signature_name=record.clamav_signature_name,
            clamav_error=record.clamav_error,
            yara_status=record.yara_status,

            # Crea una nuova lista Python e gestisce in modo sicuro anche un eventuale valore nullo
            yara_matches=list(record.yara_matches or []),

            yara_error=record.yara_error,

            # Anche gli indicatori vengono restituiti come una nuova lista Python
            indicators=list(record.indicators or []),

            error_message=record.error_message,
        )

    # Converte il record ORM in una rappresentazione più compatta specifica per il job di elaborazione
    @staticmethod
    def _to_job(record: AnalysisRecordModel) -> AnalysisJob:
        """Map an ORM record to an internal worker job representation."""

        # Il modello `AnalysisJob` contiene esclusivamente le informazioni necessarie a identificare e processare il job
        return AnalysisJob(
            id=record.id,
            file_name=record.file_name,
            size_bytes=record.size_bytes,

            # Se storage_path fosse nullo verrebbe utilizzata una stringa vuota per rispettare il tipo previsto dal modello
            storage_path=record.storage_path or "",

            attempt_count=record.attempt_count,

            # Normalizza i timestamp in UTC
            created_at=SqlAlchemyAnalysisRepository._ensure_utc(record.created_at),

            processing_started_at=(
                SqlAlchemyAnalysisRepository._ensure_utc(record.processing_started_at)
                if record.processing_started_at is not None
                else None
            ),

            worker_id=record.worker_id,
        )

    # Helper che garantisce che un datetime restituito dal database sia rappresentato esplicitamente in UTC
    @staticmethod
    def _ensure_utc(value):
        """Normalize datetimes to UTC even on SQLite."""

        # SQLite nei test può restituire datetime privi dell'informazione di timezone, quindi in quel caso viene associato esplicitamente UTC
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        # Se il datetime contiene già una timezone, viene convertito nel corrispondente istante UTC
        return value.astimezone(timezone.utc)


# Dependency FastAPI che costruisce il repository reale utilizzando la Session fornita da `get_db_session`
def get_repository(session: Session = Depends(get_db_session)) -> SqlAlchemyAnalysisRepository:
    """Dependency FastAPI che fornisce il repository SQLAlchemy reale."""

    # Il repository riceve la sessione già gestita dalla dependency database e non ne controlla direttamente apertura o chiusura
    return SqlAlchemyAnalysisRepository(session)
