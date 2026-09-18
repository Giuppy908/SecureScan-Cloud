"""Metriche Prometheus del SecureScan Analysis Worker.

Questo file non alimenta direttamente una pagina del frontend classica.
Serve a esportare verso Prometheus e Grafana dati utili per capire:
- quanti job vengono presi in carico;
- quanti vengono completati o falliscono;
- quanto durano ClamAV, YARA e la pipeline complessiva;
- se il loop di polling del worker è sano.

Una parte di queste informazioni arriva indirettamente anche nella pagina
Stato del sistema.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# Strumenti utilizzati per gestire timestamp e convertirli esplicitamente in UTC
from datetime import datetime, timezone

# Response permette di restituire direttamente il contenuto dell'endpoint HTTP /metrics
from fastapi.responses import Response

# Tipi di metriche Prometheus e strumenti necessari per serializzarle nel formato esposto a Prometheus
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

# Configurazione globale del worker, utilizzata soprattutto per identificare la replica tramite worker_id
from app.core.config import settings


# Counter che conta quanti job sono stati acquisiti dal worker
JOBS_ACQUIRED = Counter(
    "securescan_worker_jobs_acquired_total",
    "Analysis jobs acquired by the worker.",
    ["worker_id"],
)

# Counter che conta quanti job sono stati completati correttamente
JOBS_COMPLETED = Counter(
    "securescan_worker_jobs_completed_total",
    "Analysis jobs completed by the worker.",
    ["worker_id"],
)

# Counter che conta i job falliti distinguendo il motivo tramite la label reason
JOBS_FAILED = Counter(
    "securescan_worker_jobs_failed_total",
    "Analysis jobs marked as failed by the worker.",
    ["worker_id", "reason"],
)

# Counter che conta i job processing stale rimessi in coda dal meccanismo di recovery
JOBS_RECOVERED = Counter(
    "securescan_worker_jobs_recovered_total",
    "Stale processing jobs returned to the queue by the worker.",
    ["worker_id"],
)

# Counter che conta le scansioni ClamAV distinguendole in base allo stato finale
CLAMAV_SCANS = Counter(
    "securescan_worker_clamav_scans_total",
    "ClamAV scans executed by the worker.",
    ["worker_id", "status"],
)

# Counter che conta quante detection sono state segnalate da ClamAV
CLAMAV_DETECTIONS = Counter(
    "securescan_worker_clamav_detections_total",
    "ClamAV detections reported by the worker.",
    ["worker_id"],
)

# Histogram che misura la distribuzione delle durate delle scansioni ClamAV in secondi
CLAMAV_SCAN_DURATION = Histogram(
    "securescan_worker_clamav_scan_duration_seconds",
    "Duration of one ClamAV scan.",
    ["worker_id", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# Counter che conta le scansioni YARA distinguendole in base allo stato finale
YARA_SCANS = Counter(
    "securescan_worker_yara_scans_total",
    "YARA scans executed by the worker.",
    ["worker_id", "status"],
)

# Counter che conta i match YARA distinguendoli in base alla severità
YARA_MATCHES = Counter(
    "securescan_worker_yara_matches_total",
    "YARA rule matches produced by the worker.",
    ["worker_id", "severity"],
)

# Histogram che misura la distribuzione delle durate delle scansioni YARA in secondi
YARA_SCAN_DURATION = Histogram(
    "securescan_worker_yara_scan_duration_seconds",
    "Duration of one YARA scan.",
    ["worker_id", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
)

# Counter che conta i cicli di polling terminati con un errore
POLLING_ERRORS = Counter(
    "securescan_worker_polling_errors_total",
    "Worker polling cycles that ended with an error.",
    ["worker_id"],
)

# Histogram che misura la durata complessiva del processing di un job distinguendo successo e fallimento
PROCESSING_DURATION = Histogram(
    "securescan_worker_job_processing_duration_seconds",
    "Wall-clock duration of one processed job.",
    ["worker_id", "outcome"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
)

# Gauge che contiene il timestamp Unix dell'ultimo ciclo di polling completato con successo
LAST_SUCCESSFUL_POLL = Gauge(
    "securescan_worker_last_successful_poll_timestamp_seconds",
    "Unix timestamp of the latest successful worker polling cycle.",
    ["worker_id"],
)

# Gauge binario che vale 1 quando il loop worker è in esecuzione e 0 quando non lo è
WORKER_RUNNING = Gauge(
    "securescan_worker_running",
    "Whether the worker loop is currently running.",
    ["worker_id"],
)

# Gauge binario che vale 1 quando il polling è attivo e non presenta un errore corrente
WORKER_POLLING_HEALTHY = Gauge(
    "securescan_worker_polling_healthy",
    "Whether the worker polling loop is currently healthy.",
    ["worker_id"],
)


# Preinizializza le principali serie Prometheus per la replica corrente anche prima del primo evento
JOBS_ACQUIRED.labels(worker_id=settings.worker_id)
JOBS_COMPLETED.labels(worker_id=settings.worker_id)
JOBS_RECOVERED.labels(worker_id=settings.worker_id)
POLLING_ERRORS.labels(worker_id=settings.worker_id)

# Preinizializza le due cause di fallimento attualmente previste dal runtime del worker
JOBS_FAILED.labels(worker_id=settings.worker_id, reason="processing_error")
JOBS_FAILED.labels(worker_id=settings.worker_id, reason="max_attempts_exceeded")

# Preinizializza le serie dell'Histogram della durata per entrambi gli outcome previsti
PROCESSING_DURATION.labels(worker_id=settings.worker_id, outcome="completed")
PROCESSING_DURATION.labels(worker_id=settings.worker_id, outcome="failed")

# Preinizializza le serie ClamAV per tutti gli stati attualmente previsti
CLAMAV_SCANS.labels(worker_id=settings.worker_id, status="clean")
CLAMAV_SCANS.labels(worker_id=settings.worker_id, status="found")
CLAMAV_SCANS.labels(worker_id=settings.worker_id, status="error")
CLAMAV_SCANS.labels(worker_id=settings.worker_id, status="timeout")
CLAMAV_SCANS.labels(worker_id=settings.worker_id, status="unavailable")

# Preinizializza il Counter complessivo delle detection ClamAV
CLAMAV_DETECTIONS.labels(worker_id=settings.worker_id)

# Preinizializza le serie di durata ClamAV per tutti gli stati previsti
CLAMAV_SCAN_DURATION.labels(worker_id=settings.worker_id, status="clean")
CLAMAV_SCAN_DURATION.labels(worker_id=settings.worker_id, status="found")
CLAMAV_SCAN_DURATION.labels(worker_id=settings.worker_id, status="error")
CLAMAV_SCAN_DURATION.labels(worker_id=settings.worker_id, status="timeout")
CLAMAV_SCAN_DURATION.labels(worker_id=settings.worker_id, status="unavailable")

# Preinizializza le serie YARA per tutti gli stati attualmente previsti
YARA_SCANS.labels(worker_id=settings.worker_id, status="clean")
YARA_SCANS.labels(worker_id=settings.worker_id, status="matched")
YARA_SCANS.labels(worker_id=settings.worker_id, status="error")
YARA_SCANS.labels(worker_id=settings.worker_id, status="unavailable")

# Preinizializza le serie dei match YARA per tutte le severità normalizzate
YARA_MATCHES.labels(worker_id=settings.worker_id, severity="test")
YARA_MATCHES.labels(worker_id=settings.worker_id, severity="suspicious")
YARA_MATCHES.labels(worker_id=settings.worker_id, severity="malicious")
YARA_MATCHES.labels(worker_id=settings.worker_id, severity="unknown")

# Preinizializza le serie di durata YARA per gli stati previsti
YARA_SCAN_DURATION.labels(worker_id=settings.worker_id, status="clean")
YARA_SCAN_DURATION.labels(worker_id=settings.worker_id, status="matched")
YARA_SCAN_DURATION.labels(worker_id=settings.worker_id, status="error")
YARA_SCAN_DURATION.labels(worker_id=settings.worker_id, status="unavailable")

# Preinizializza i Gauge runtime della replica worker
LAST_SUCCESSFUL_POLL.labels(worker_id=settings.worker_id)
WORKER_RUNNING.labels(worker_id=settings.worker_id)
WORKER_POLLING_HEALTHY.labels(worker_id=settings.worker_id)


# Registra l'acquisizione di un nuovo job da parte del worker
def record_job_acquired() -> None:
    """Incrementa il contatore dei job presi in carico da questa replica."""

    # Incrementa di uno il Counter associato alla replica corrente
    JOBS_ACQUIRED.labels(worker_id=settings.worker_id).inc()


# Registra il completamento corretto di un job e la sua durata complessiva
def record_job_completed(duration_seconds: float) -> None:
    """Registra completamento e durata di una scansione riuscita."""

    # Incrementa il numero totale di job completati
    JOBS_COMPLETED.labels(worker_id=settings.worker_id).inc()

    # Inserisce la durata osservata nell'Histogram dei job completati
    PROCESSING_DURATION.labels(worker_id=settings.worker_id, outcome="completed").observe(duration_seconds)


# Registra il fallimento di un job e il tempo trascorso prima dell'errore
def record_job_failed(*, reason: str, duration_seconds: float) -> None:
    """Registra un job fallito e la durata spesa prima del fallimento."""

    # Incrementa il Counter dei job falliti distinguendo la causa tramite reason
    JOBS_FAILED.labels(worker_id=settings.worker_id, reason=reason).inc()

    # Registra la durata nell'Histogram associato all'outcome failed
    PROCESSING_DURATION.labels(worker_id=settings.worker_id, outcome="failed").observe(duration_seconds)


# Registra esito, durata ed eventuali detection di una scansione ClamAV
def record_clamav_scan(*, status: str, duration_seconds: float, detection_count: int = 0) -> None:
    """Registra esito e durata del passaggio ClamAV."""

    # Incrementa il numero di scansioni ClamAV per lo stato ricevuto
    CLAMAV_SCANS.labels(worker_id=settings.worker_id, status=status).inc()

    # Inserisce la durata della scansione nell'Histogram relativo allo stesso stato
    CLAMAV_SCAN_DURATION.labels(worker_id=settings.worker_id, status=status).observe(duration_seconds)

    # Le detection vengono conteggiate solamente quando il valore ricevuto è positivo
    if detection_count > 0:

        # Incrementa il Counter del numero totale di detection della quantità indicata
        CLAMAV_DETECTIONS.labels(worker_id=settings.worker_id).inc(detection_count)


# Registra esito, durata e severità dei match prodotti da una scansione YARA
def record_yara_scan(*, status: str, duration_seconds: float, severities: list[str]) -> None:
    """Registra esito YARA e severità dei match trovati."""

    # Incrementa il Counter delle scansioni YARA per lo stato ricevuto
    YARA_SCANS.labels(worker_id=settings.worker_id, status=status).inc()

    # Inserisce la durata della scansione nell'Histogram relativo allo stesso stato
    YARA_SCAN_DURATION.labels(worker_id=settings.worker_id, status=status).observe(duration_seconds)

    # Analizza la severità di ogni singolo match YARA ricevuto
    for severity in severities:

        # Mantiene le severità previste e converte qualsiasi altro valore nella categoria unknown
        normalized = severity if severity in {"test", "suspicious", "malicious"} else "unknown"

        # Incrementa il Counter della categoria di severità corrispondente
        YARA_MATCHES.labels(worker_id=settings.worker_id, severity=normalized).inc()


# Registra quanti job stale sono stati rimessi in coda dal meccanismo di recovery
def record_jobs_recovered(recovered_count: int) -> None:
    """Conta i job rimessi in coda dopo un recovery da `processing` bloccato."""

    # Evita incrementi inutili quando il recovery non ha trovato job da riaccodare
    if recovered_count > 0:

        # Incrementa il Counter direttamente del numero di job recuperati
        JOBS_RECOVERED.labels(worker_id=settings.worker_id).inc(recovered_count)


# Registra i job che il recovery ha fallito definitivamente perché hanno esaurito i tentativi
def record_jobs_failed_during_recovery(failed_count: int) -> None:
    """Conta i job che superano i tentativi massimi durante il recovery."""

    # Aggiorna il Counter soltanto quando esistono realmente job falliti
    if failed_count > 0:

        # Registra i fallimenti usando la causa specifica max_attempts_exceeded
        JOBS_FAILED.labels(worker_id=settings.worker_id, reason="max_attempts_exceeded").inc(failed_count)


# Registra un ciclo di polling terminato con un errore
def record_polling_error() -> None:
    """Conta un ciclo di polling che non è riuscito a completarsi correttamente."""

    # Incrementa il Counter degli errori di polling della replica corrente
    POLLING_ERRORS.labels(worker_id=settings.worker_id).inc()


# Aggiorna i Gauge Prometheus che rappresentano lo stato runtime corrente del worker
def sync_runtime_metrics(snapshot: dict[str, datetime | str | bool | None]) -> None:
    """Sincronizza nelle metriche lo stato corrente del loop worker."""

    # Imposta il Gauge a 1 solamente se il worker risulta attualmente in esecuzione
    WORKER_RUNNING.labels(worker_id=settings.worker_id).set(1 if snapshot["is_running"] is True else 0)

    # Considera il polling sano solamente quando il worker è attivo e non esiste un errore corrente
    WORKER_POLLING_HEALTHY.labels(worker_id=settings.worker_id).set(
        1 if snapshot["is_running"] is True and snapshot["last_error"] is None else 0
    )

    # Recupera il timestamp dell'ultimo polling completato correttamente
    successful_poll = snapshot["last_successful_poll_at"]

    # Il Gauge viene aggiornato solamente se lo snapshot contiene effettivamente un datetime
    if isinstance(successful_poll, datetime):

        # Converte il datetime in UTC e poi nel corrispondente timestamp Unix espresso in secondi
        LAST_SUCCESSFUL_POLL.labels(worker_id=settings.worker_id).set(
            successful_poll.astimezone(timezone.utc).timestamp()
        )


# Produce la risposta HTTP dell'endpoint /metrics nel formato richiesto da Prometheus
def render_metrics(snapshot: dict[str, datetime | str | bool | None]) -> Response:
    """Serializza tutte le metriche del worker nel formato Prometheus."""

    # Sincronizza i Gauge runtime con lo stato corrente prima di esportare le metriche
    sync_runtime_metrics(snapshot)

    # Serializza il registry Prometheus globale e restituisce il content type ufficiale del formato exposition
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
