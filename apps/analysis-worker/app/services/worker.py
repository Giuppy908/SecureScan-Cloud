"""Loop principale del worker asincrono.

Questo file implementa il comportamento che manca volutamente all'Analysis API:
l'API crea rapidamente un job `queued`, mentre qui il worker lo recupera,
lo porta in `processing`, esegue la pipeline malware e aggiorna PostgreSQL.

Se questo componente non esistesse:
- Nuova analisi potrebbe creare il job iniziale;
- ma Cronologia e Dettaglio analisi non vedrebbero mai il risultato finale;
- Dashboard non riceverebbe dati aggiornati;
- Stato del sistema non potrebbe dire se la pipeline è davvero operativa.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# Modulo utilizzato per registrare gli eventi principali del worker
import logging

# `threading` viene usato per eseguire in background il polling dei job e l'heartbeat
# Con polling si intende che il worker controlla periodicamente se nel database è comparso un nuovo job da elaborare
import threading

# `time` viene utilizzato per misurare la durata del processing e applicare eventuali attese
import time

# `datetime` e `timezone` servono per registrare e confrontare timestamp in UTC
from datetime import datetime, timezone

# `Path` permette di leggere ed eliminare il file temporaneo tramite il percorso salvato nel job
from pathlib import Path

# Configurazione generale del worker
from app.core.config import settings

# Gestione delle sessioni database e controllo della raggiungibilità di PostgreSQL
from app.db.session import is_database_reachable, session_manager

# Repository e strutture utilizzati per acquisire, aggiornare e recuperare i job di analisi
from app.repositories.analysis_repository import (
    AnalysisJob,
    AnalysisWorkerRepository,
    RepositoryError,
)

# Repository utilizzato per registrare e aggiornare l'heartbeat del worker
from app.repositories.worker_registry_repository import (
    WorkerRegistryError,
    WorkerRegistryRepository,
)

# Pipeline malware completa eseguita sul contenuto dei file acquisiti
from app.services.malware_pipeline import MalwareScanPipeline, get_default_malware_scan_pipeline

# Funzioni che aggiornano le metriche Prometheus relative al comportamento del worker
from app.services.metrics import (
    record_clamav_scan,
    record_job_acquired,
    record_job_completed,
    record_job_failed,
    record_jobs_failed_during_recovery,
    record_jobs_recovered,
    record_polling_error,
    record_yara_scan,
)

# Logger associato a questo modulo
logger = logging.getLogger(__name__)


# Mantiene lo stato runtime minimo necessario per health endpoint e metriche
class WorkerRuntimeState:
    """Stato runtime minimo esposto da `/health` e dalle metriche.

    Tiene traccia di:
    - se il loop è in esecuzione;
    - quando l'ultimo polling è andato bene;
    - l'ultimo errore osservato.
    """

    # Inizializza lo stato runtime e il lock usato per accedervi in sicurezza da thread differenti
    def __init__(self) -> None:

        # Lock che protegge letture e modifiche concorrenti dello stato runtime
        self._lock = threading.Lock()

        # Timestamp UTC dell'ultimo ciclo di polling completato correttamente
        self.last_successful_poll_at: datetime | None = None

        # Ultimo errore di polling memorizzato, oppure None se non ci sono errori correnti
        self.last_error: str | None = None

        # Indica se il loop principale di polling è attualmente in esecuzione
        self.is_running: bool = False

    # Registra il completamento corretto di un ciclo di polling
    def mark_poll_success(self) -> None:

        # Il lock impedisce aggiornamenti concorrenti incoerenti dello stato
        with self._lock:

            # Memorizza l'istante UTC dell'ultimo polling riuscito
            self.last_successful_poll_at = datetime.now(timezone.utc)

            # Un polling riuscito elimina l'eventuale errore precedente
            self.last_error = None

    # Aggiorna lo stato che indica se il loop principale è attivo
    def set_running(self, value: bool) -> None:
        with self._lock:
            self.is_running = value

    # Memorizza l'ultimo errore osservato durante il polling
    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    # Restituisce una fotografia coerente dello stato runtime corrente
    def snapshot(self) -> dict[str, datetime | str | bool | None]:
        with self._lock:
            return {
                "is_running": self.is_running,
                "last_successful_poll_at": self.last_successful_poll_at,
                "last_error": self.last_error,
            }


# Coordina polling PostgreSQL, processamento dei job e heartbeat del worker
class AnalysisWorkerLoop:
    """Loop che interroga PostgreSQL e processa i job uno alla volta per processo.

    In pratica il worker fa polling: a intervalli regolari controlla se esiste
    un record `queued`, lo prende in carico e prova a completarlo.
    """

    # Costruisce il worker usando lo stato runtime e una pipeline fornita oppure quella standard
    def __init__(self, runtime_state: WorkerRuntimeState, analyzer: MalwareScanPipeline | None = None) -> None:

        # Stato runtime condiviso con health endpoint e metriche
        self._runtime_state = runtime_state

        # Pipeline malware utilizzata per analizzare i file acquisiti
        self._analyzer = analyzer or get_default_malware_scan_pipeline()

        # Evento usato per richiedere l'arresto ordinato dei thread background
        self._stop_event = threading.Event()

        # Thread dedicato al polling e processamento dei job
        self._thread: threading.Thread | None = None

        # Thread separato dedicato alla registrazione periodica dell'heartbeat
        self._heartbeat_thread: threading.Thread | None = None

    # Avvia i due thread background del worker se non sono già attivi
    def start(self) -> None:
        """Avvia il thread di polling e il thread heartbeat del worker."""

        # Evita di avviare un secondo thread di polling se il worker è già in esecuzione
        if self._thread is not None and self._thread.is_alive():
            return

        # Rimuove un'eventuale precedente richiesta di arresto
        self._stop_event.clear()

        # Crea il thread daemon che esegue continuamente il polling dei job
        self._thread = threading.Thread(target=self.run_forever, name="analysis-worker", daemon=True)

        # Avvia il thread principale del worker
        self._thread.start()

        # Crea il thread daemon dedicato all'heartbeat
        self._heartbeat_thread = threading.Thread(
            target=self.run_heartbeat_forever,
            name="analysis-worker-heartbeat",
            daemon=True,
        )

        # Avvia il thread heartbeat
        self._heartbeat_thread.start()

    # Richiede l'arresto dei thread e attende brevemente la loro terminazione
    def stop(self) -> None:
        """Ferma in modo ordinato i thread background."""

        # Segnala ai due loop che devono terminare
        self._stop_event.set()

        # Attende fino a cinque secondi la terminazione del thread di polling
        if self._thread is not None:
            self._thread.join(timeout=5)

        # Attende fino a cinque secondi la terminazione del thread heartbeat
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)

    # Esegue continuamente polling e processamento finché non viene richiesto lo stop
    def run_forever(self) -> None:
        """Esegue il polling continuo dei job finché il processo non viene fermato."""

        # Segnala che il loop principale è attivo
        self._runtime_state.set_running(True)

        try:

            # Continua finché lo stop event non viene impostato
            while not self._stop_event.is_set():

                # Esegue un singolo ciclo di recovery, claim ed eventuale processamento
                if self._run_once():

                    # Un ciclo riuscito aggiorna timestamp ed elimina l'eventuale errore precedente
                    self._runtime_state.mark_poll_success()

                # Attende il prossimo polling, ma può essere interrotto immediatamente dallo stop event
                self._stop_event.wait(settings.poll_interval_seconds)

        finally:

            # Alla terminazione del loop segnala che il worker non è più in esecuzione
            self._runtime_state.set_running(False)

    # Gestisce registrazione e heartbeat periodico del worker nel database
    def run_heartbeat_forever(self) -> None:
        """Aggiorna periodicamente il segnale heartbeat del worker nel database."""

        # Registra inizialmente l'istanza worker nel database
        self._register_worker()

        try:

            # Continua a inviare heartbeat finché non viene richiesto lo stop
            while not self._stop_event.is_set():

                # Aggiorna il timestamp dell'heartbeat della replica corrente
                self._send_heartbeat()

                # Attende l'intervallo configurato, interrompibile dallo stop event
                self._stop_event.wait(settings.heartbeat_interval_seconds)

        finally:

            # In uno shutdown ordinato marca il worker come fermato nel database
            self._mark_worker_stopped()

    # Esegue un singolo ciclo di polling, recovery e acquisizione di un eventuale job
    def _run_once(self) -> bool:
        """Esegue un singolo ciclo di polling.

        Il ciclo prova prima a recuperare eventuali job rimasti bloccati in
        `processing`, poi cerca un nuovo job `queued`. Se non trova nulla,
        il ciclo è comunque considerato riuscito.
        """

        # Crea una nuova sessione database dedicata a questo ciclo di polling
        session = session_manager.session_factory()

        try:

            # Costruisce il repository che opera sui job di analisi
            repository = AnalysisWorkerRepository(session)

            # Recupera i job rimasti processing oltre il timeout configurato
            recovered_jobs, failed_recoveries = repository.recover_stale_processing_jobs(
                processing_timeout_seconds=settings.processing_timeout_seconds,
                max_attempts=settings.max_attempts,
            )

            # Registra nelle metriche quanti job sono stati rimessi in coda
            record_jobs_recovered(recovered_jobs)

            # Registra quanti job sono stati invece falliti definitivamente durante il recovery
            record_jobs_failed_during_recovery(failed_recoveries)

            # Tenta di acquisire atomicamente il prossimo job queued disponibile
            job = repository.acquire_next_queued_analysis(settings.worker_id)

            # Se non esistono job da processare il polling viene comunque considerato riuscito
            if job is None:
                return True

            # Memorizza un riferimento temporale monotono per misurare la durata del processing
            started_at_monotonic = time.monotonic()

            # Incrementa la metrica dei job acquisiti
            record_job_acquired()

            # Registra nel log ID del job e worker che lo ha acquisito
            logger.info(
                "Analysis job acquired: analysis_id=%s worker_id=%s",
                job.id,
                settings.worker_id,
            )

        # Un errore del repository impedisce il completamento corretto del ciclo di polling
        except RepositoryError as exc:

            # Registra stack trace e contesto dell'errore
            logger.exception("Worker repository error during polling cycle.")

            # Incrementa il contatore Prometheus degli errori di polling
            record_polling_error()

            # Memorizza l'errore nello stato runtime usato anche dall'health endpoint
            self._runtime_state.set_error(str(exc))

            # Segnala che il ciclo non è riuscito
            return False

        finally:

            # La sessione usata per recovery e claim viene sempre chiusa
            session.close()

        # Dopo il claim il processamento avviene tramite una nuova sessione database
        return self._process_job(job, started_at_monotonic)

    # Legge il file acquisito, esegue la malware pipeline e aggiorna lo stato finale del job
    def _process_job(self, job: AnalysisJob, started_at_monotonic: float) -> bool:
        """Legge il file, esegue la pipeline malware e aggiorna il record finale."""

        # Crea una nuova sessione database dedicata al processamento del job
        session = session_manager.session_factory()

        try:

            # Costruisce il repository utilizzato per aggiornare il record dell'analisi
            repository = AnalysisWorkerRepository(session)

            # Il file viene letto dal volume condiviso scritto prima
            # dall'Analysis API durante l'upload in Nuova analisi.
            content = Path(job.storage_path).read_bytes()

            # Passa nome originale e byte del file alla pipeline malware completa
            pipeline_result = self._analyzer.analyze_file(file_name=job.file_name, content=content)

            # Applica l'eventuale durata minima di processing configurata, utile soprattutto nelle demo
            self._wait_for_minimum_processing_duration(
                started_at_monotonic,
                analysis_id=job.id,
            )

            # Calcola la durata complessiva del processamento del job
            processing_duration_seconds = self._processing_duration_seconds(started_at_monotonic)

            # Salva nel database il risultato finale della pipeline e porta il job a completed
            repository.mark_completed(job.id, pipeline_result.analysis)

            # Aggiorna le metriche Prometheus relative alla scansione ClamAV
            record_clamav_scan(
                status=pipeline_result.analysis.clamav_status,
                duration_seconds=pipeline_result.clamav_duration_seconds,
                detection_count=1 if pipeline_result.analysis.clamav_status == "found" else 0,
            )

            # Aggiorna le metriche Prometheus relative alla scansione YARA
            record_yara_scan(
                status=pipeline_result.analysis.yara_status,
                duration_seconds=pipeline_result.yara_duration_seconds,
                severities=pipeline_result.yara_severities,
            )

            # Registra il completamento del job e la sua durata complessiva nelle metriche
            record_job_completed(processing_duration_seconds)

            # Registra nel log il completamento dell'analisi
            logger.info(
                "Analysis job completed: analysis_id=%s worker_id=%s processing_duration_seconds=%.3f",
                job.id,
                settings.worker_id,
                processing_duration_seconds,
            )

            # Segnala che il processamento è stato gestito correttamente
            return True

        # Qualunque errore durante lettura, pipeline o persistenza viene gestito come failure del job
        except Exception as exc:  # noqa: BLE001

            # Registra l'eccezione completa nel log
            logger.exception("Worker failed to process analysis job.", extra={"analysis_id": job.id})

            try:

                # Applica anche ai job falliti l'eventuale durata minima configurata
                self._wait_for_minimum_processing_duration(
                    started_at_monotonic,
                    analysis_id=job.id,
                )

                # Calcola la durata trascorsa fino al fallimento
                processing_duration_seconds = self._processing_duration_seconds(started_at_monotonic)

                # Chiude la sessione potenzialmente compromessa dall'errore precedente
                session.close()

                # Apre una nuova sessione indipendente per registrare in sicurezza il fallimento
                failure_session = session_manager.session_factory()

                try:

                    # Porta il job a failed e salva il messaggio tecnico dell'errore
                    AnalysisWorkerRepository(failure_session).mark_failed(
                        job.id,
                        f"Worker processing failed: {exc}",
                    )

                    # Aggiorna la metrica dei job falliti
                    record_job_failed(reason="processing_error", duration_seconds=processing_duration_seconds)

                    # Registra nel log il fallimento persistito correttamente
                    logger.info(
                        "Analysis job failed: analysis_id=%s worker_id=%s processing_duration_seconds=%.3f",
                        job.id,
                        settings.worker_id,
                        processing_duration_seconds,
                    )

                finally:

                    # Chiude sempre la sessione utilizzata per registrare il fallimento
                    failure_session.close()

            # Se anche la persistenza dello stato failed non riesce il ciclo viene considerato problematico
            except RepositoryError:

                # Registra l'impossibilità di salvare il fallimento nel database
                logger.exception("Failed to mark analysis job as failed.", extra={"analysis_id": job.id})

                # Incrementa la metrica degli errori di polling/persistenza
                record_polling_error()

                # Espone l'errore anche tramite lo stato runtime
                self._runtime_state.set_error("Failed to persist worker failure state.")

                # Segnala al loop che il ciclo non si è concluso correttamente
                return False

            # Una failure del singolo job correttamente registrata non interrompe il worker
            return True

        finally:

            # Il cleanup viene tentato sempre, sia dopo successo sia dopo fallimento
            try:

                # Il file temporaneo non deve restare nello storage upload dopo
                # il completamento del job, riuscito o fallito che sia.
                path = Path(job.storage_path)

                # Se il file esiste ancora viene eliminato dallo storage condiviso
                if path.exists():
                    path.unlink()

            # Un errore di cleanup viene registrato ma non modifica ulteriormente lo stato del job
            except Exception:  # noqa: BLE001
                logger.exception("Failed to remove processed upload.", extra={"analysis_id": job.id})

            # Chiude la sessione di processing se risulta ancora attiva
            if session.is_active:
                session.close()

    # Garantisce che il job rimanga in processing almeno per il tempo minimo configurato
    def _wait_for_minimum_processing_duration(
        self,
        started_at_monotonic: float,
        *,
        analysis_id: str,
    ) -> None:
        """Applica un tempo minimo di `processing` utile soprattutto in demo locale."""

        # Se la durata minima è disabilitata non viene applicata alcuna attesa
        if settings.min_processing_seconds <= 0:
            return

        # Calcola il tempo già trascorso dall'acquisizione del job
        elapsed_seconds = time.monotonic() - started_at_monotonic

        # Calcola quanto tempo manca per raggiungere la durata minima
        remaining_seconds = settings.min_processing_seconds - elapsed_seconds

        # Se la durata minima è già stata raggiunta non serve attendere
        if remaining_seconds <= 0:
            return

        # Registra nel log il ritardo artificiale che verrà applicato
        logger.info(
            "Applying minimum processing duration: analysis_id=%s remaining_seconds=%.3f",
            analysis_id,
            remaining_seconds,
        )

        # Sospende il thread fino al raggiungimento della durata minima
        time.sleep(remaining_seconds)

    # Calcola il tempo totale trascorso dall'acquisizione del job
    def _processing_duration_seconds(self, started_at_monotonic: float) -> float:
        """Calcola la durata complessiva del lavoro svolto su un job."""

        # La differenza tra due valori monotonic fornisce la durata senza dipendere dall'orologio di sistema
        return time.monotonic() - started_at_monotonic

    # Registra nel database l'istanza worker quando parte il thread heartbeat
    def _register_worker(self) -> None:
        """Registra la replica worker nel database all'avvio."""

        # Crea una sessione dedicata alla registrazione del worker
        session = session_manager.session_factory()

        try:

            # Registra worker_id e hostname nel registro dei worker
            WorkerRegistryRepository(session).register_worker(settings.worker_id, settings.hostname)

            # Registra nel log l'avvenuta registrazione
            logger.info(
                "Worker registered: worker_id=%s hostname=%s",
                settings.worker_id,
                settings.hostname,
            )

        # Un errore nella registrazione produce un warning ma non interrompe il processo
        except WorkerRegistryError:
            logger.warning(
                "Worker registration failed.",
                extra={"worker_id": settings.worker_id},
            )

        finally:

            # Chiude sempre la sessione usata per la registrazione
            session.close()

    # Aggiorna il timestamp heartbeat della replica worker
    def _send_heartbeat(self) -> None:
        """Aggiorna periodicamente il timestamp heartbeat del worker."""

        # Crea una nuova sessione database per questo heartbeat
        session = session_manager.session_factory()

        try:

            # Aggiorna o mantiene attivo il record della replica corrente
            WorkerRegistryRepository(session).touch_worker(settings.worker_id, settings.hostname)

            # Registra l'heartbeat a livello debug
            logger.debug(
                "Worker heartbeat updated.",
                extra={"worker_id": settings.worker_id},
            )

        # Un errore heartbeat viene registrato ma non ferma il processamento dei job
        except WorkerRegistryError:
            logger.warning(
                "Worker heartbeat update failed.",
                extra={"worker_id": settings.worker_id},
            )

        finally:

            # Chiude sempre la sessione heartbeat
            session.close()

    # Marca nel database la replica worker come fermata durante uno shutdown ordinato
    def _mark_worker_stopped(self) -> None:
        """Segna la replica worker come fermata durante lo shutdown."""

        # Crea una sessione dedicata all'aggiornamento dello stato del worker
        session = session_manager.session_factory()

        try:

            # Aggiorna il registro indicando che questa replica non è più attiva
            WorkerRegistryRepository(session).mark_stopped(settings.worker_id)

        # Un errore durante lo shutdown viene registrato ma non impedisce la terminazione del processo
        except WorkerRegistryError:
            logger.warning(
                "Failed to mark worker as stopped.",
                extra={"worker_id": settings.worker_id},
            )

        finally:

            # Chiude sempre la sessione usata durante lo shutdown
            session.close()


# Costruisce lo stato restituito dall'endpoint /health del worker
def health_payload(runtime_state: WorkerRuntimeState) -> tuple[int, dict[str, str]]:
    """Costruisce la risposta `/health` del worker.

    La risposta non controlla solo se il processo HTTP è vivo: considera anche
    database, ultimo polling riuscito ed eventuali errori persistenti.
    """

    # Legge una fotografia thread-safe dello stato runtime
    snapshot = runtime_state.snapshot()

    # Se il loop principale non è attivo il worker viene considerato unhealthy
    if snapshot["is_running"] is not True:
        return 503, {"status": "unhealthy", "database": "unknown", "polling": "stopped"}

    # Se PostgreSQL non è raggiungibile il worker non può acquisire né aggiornare job
    if not is_database_reachable():
        return 503, {"status": "unhealthy", "database": "unreachable", "polling": "failing"}

    # Un errore di polling ancora memorizzato rende il worker unhealthy
    if snapshot["last_error"] is not None:
        return 503, {"status": "unhealthy", "database": "reachable", "polling": "error"}

    # Recupera il timestamp dell'ultimo polling completato correttamente
    successful_poll = snapshot["last_successful_poll_at"]

    # Prima del primo polling riuscito il worker è ancora considerato in fase di avvio
    if successful_poll is None:
        return 503, {"status": "unhealthy", "database": "reachable", "polling": "starting"}

    # Definisce l'età massima ammessa per considerare ancora operativo il polling
    max_age = settings.poll_interval_seconds * 3 + 5

    # Calcola da quanto tempo non viene registrato un polling riuscito
    age = (datetime.now(timezone.utc) - successful_poll).total_seconds()

    # Se l'ultimo polling è troppo vecchio il loop viene considerato bloccato
    if age > max_age:
        return 503, {"status": "unhealthy", "database": "reachable", "polling": "stalled"}

    # Tutti i controlli sono superati: worker e polling vengono considerati operativi
    return 200, {"status": "healthy", "database": "reachable", "polling": "running"}
