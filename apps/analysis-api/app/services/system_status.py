"""Servizio che costruisce la pagina Stato del sistema.

Qui viene riassunto lo stato della piattaforma guardando più fonti insieme:
- probe HTTP verso servizi interni;
- heartbeat applicativi delle repliche API e del worker;
- raggiungibilità del database.

È utile distinguere questi concetti:
- un health check Docker dice se un container risponde;
- un heartbeat applicativo dice se quel componente continua davvero a lavorare.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `logging` permette di registrare warning e messaggi di debug relativi ai controlli sullo stato dei servizi
import logging

# `socket` permette di aprire una connessione TCP diretta verso ClamAV sulla rete interna
import socket

# `JSONDecodeError` viene intercettato tra gli errori possibili durante i probe HTTP
from json import JSONDecodeError

# `HTTPError` e `URLError` rappresentano errori HTTP o di rete prodotti durante i probe delle dipendenze
from urllib.error import HTTPError, URLError

# `urlopen` esegue richieste HTTP sincrone verso i servizi tecnici monitorati
from urllib.request import urlopen

# `datetime`, `timedelta` e `timezone` servono per creare timestamp UTC e calcolare le soglie oltre le quali un heartbeat è considerato troppo vecchio
from datetime import datetime, timedelta, timezone

# `func`, `select` e `text` permettono di costruire rispettivamente aggregazioni, query ORM e query SQL testuali con SQLAlchemy
from sqlalchemy import func, select, text

# Eccezione SQLAlchemy intercettata quando le operazioni verso il database falliscono
from sqlalchemy.exc import SQLAlchemyError

# Configurazione applicativa contenente timeout, URL, numero di repliche attese e parametri dei servizi monitorati
from app.core.config import settings

# Modelli ORM e relativi enum utilizzati per leggere gli heartbeat delle repliche API e dei worker dal database
from app.db.models import (
    ApiInstanceHeartbeatModel,
    ApiInstanceHeartbeatStatus,
    WorkerHeartbeatModel,
    WorkerHeartbeatStatus,
)

# Gestore utilizzato per creare le Session SQLAlchemy necessarie ai controlli sul database e sugli heartbeat
from app.db.session import session_manager

# Modelli di dominio utilizzati per rappresentare lo stato di un singolo servizio, il livello di stato e lo snapshot complessivo
from app.models.system_status import (
    SystemServiceSnapshot,
    SystemStatusLevel,
    SystemStatusSnapshot,
)


# Logger associato a questo modulo
logger = logging.getLogger(__name__)


# Eccezione specifica dichiarata per gli errori relativi alla costruzione dello stato del sistema
class SystemStatusError(Exception):
    """Errore sollevato quando non è possibile costruire lo stato della piattaforma."""


# Restituisce sempre il timestamp corrente come datetime timezone-aware espresso in UTC
def utc_now() -> datetime:
    """Restituisce l'istante corrente in UTC con timezone esplicita."""

    # Crea il timestamp UTC utilizzato come riferimento comune per tutti i controlli dello snapshot
    return datetime.now(timezone.utc)


# Service che raccoglie i controlli sui diversi componenti e costruisce uno snapshot aggregato dello stato della piattaforma
class SystemStatusService:
    """Aggrega lo stato dei componenti che alimentano la pagina Stato del sistema."""

    # Costruisce lo snapshot completo eseguendo i controlli necessari sui diversi componenti della piattaforma
    def collect_status(self) -> SystemStatusSnapshot:
        """Costruisce la risposta completa usata dalla pagina Stato del sistema."""

        # Usa un unico timestamp di riferimento per mantenere coerenti temporalmente tutti i controlli eseguiti nello stesso snapshot
        checked_at = utc_now()

        # Verifica per prima cosa se il database è raggiungibile tramite una query minima
        postgres_status = self._build_database_status(checked_at)

        # Se PostgreSQL è indisponibile non è possibile leggere dal database gli heartbeat delle API e dei worker
        if postgres_status.status == SystemStatusLevel.UNAVAILABLE:

            # In assenza del database la disponibilità delle repliche API non può essere determinata e viene rappresentata come DEGRADED
            analysis_api_status = SystemServiceSnapshot(
                name="analysis-api",
                status=SystemStatusLevel.DEGRADED,
                message="API replica availability could not be determined because the database is unreachable.",
                last_checked_at=checked_at,
                details={
                    "version": settings.app_version,
                    "instance_id": settings.instance_id,
                    "configured_instances": settings.configured_api_replicas,
                    "active_instances": 0,
                    "active_instance_ids": [],
                },
            )

            # In assenza del database anche la disponibilità dei worker non può essere determinata e viene rappresentata come UNAVAILABLE
            worker_status = SystemServiceSnapshot(
                name="analysis-worker",
                status=SystemStatusLevel.UNAVAILABLE,
                message="Worker availability could not be determined because the database is unreachable.",
                last_checked_at=checked_at,
                details={"active_workers": 0},
            )

        else:

            # Se PostgreSQL è disponibile vengono letti e valutati gli heartbeat delle repliche API
            analysis_api_status = self._build_analysis_api_status(checked_at)

            # Vengono inoltre letti e valutati gli heartbeat dei worker
            worker_status = self._build_worker_status(checked_at)

        # Costruisce l'elenco completo degli snapshot dei componenti realmente monitorati da questo service
        services = [
            analysis_api_status,
            postgres_status,
            worker_status,

            # Verifica direttamente ClamAV tramite una connessione TCP interna
            self._build_clamav_status(checked_at),

            # Verifica Kong attraverso un probe HTTP verso l'URL di stato configurato
            self._build_http_dependency_status(
                name="kong",
                checked_at=checked_at,
                url=settings.kong_status_url,
                healthy_message="Gateway is reachable.",
                unavailable_message="Gateway is unreachable.",
            ),

            # Verifica Prometheus attraverso un probe HTTP
            self._build_http_dependency_status(
                name="prometheus",
                checked_at=checked_at,
                url=settings.prometheus_health_url,
                healthy_message="Metrics collector is reachable.",
                unavailable_message="Metrics collector is unreachable.",
            ),

            # Verifica Grafana attraverso un probe HTTP
            self._build_http_dependency_status(
                name="grafana",
                checked_at=checked_at,
                url=settings.grafana_health_url,
                healthy_message="Dashboard service is reachable.",
                unavailable_message="Dashboard service is unreachable.",
            ),

            # Verifica postgres-exporter attraverso il relativo endpoint HTTP delle metriche
            self._build_http_dependency_status(
                name="postgres-exporter",
                checked_at=checked_at,
                url=settings.postgres_exporter_metrics_url,
                healthy_message="Database exporter is reachable.",
                unavailable_message="Database exporter is unreachable.",
            ),
        ]

        # Aggrega gli stati dei singoli componenti per determinare il livello complessivo della piattaforma
        overall_status = self._aggregate_overall_status(services)

        # Restituisce lo snapshot completo con stato complessivo, timestamp del controllo e dettagli dei singoli servizi
        return SystemStatusSnapshot(
            overall_status=overall_status,
            checked_at=checked_at,
            services=services,
        )

    # Valuta quante repliche Analysis API risultano ACTIVE e hanno inviato un heartbeat sufficientemente recente
    def _build_analysis_api_status(self, checked_at: datetime) -> SystemServiceSnapshot:
        # Replica liveness is derived from heartbeats stored by each API instance.
        # This keeps the status page meaningful even if Kong is healthy but one
        # replica stopped refreshing its own registration record.

        # Calcola il timestamp minimo oltre il quale un heartbeat API viene considerato ancora valido
        threshold = checked_at - timedelta(seconds=settings.api_heartbeat_timeout_seconds)

        # Crea una Session SQLAlchemy dedicata alla lettura degli heartbeat delle repliche API
        session = session_manager.session_factory()

        try:

            # Seleziona gli ID delle sole repliche con stato ACTIVE e heartbeat non più vecchio della soglia
            rows = session.execute(
                select(ApiInstanceHeartbeatModel.instance_id)
                .where(
                    ApiInstanceHeartbeatModel.status == ApiInstanceHeartbeatStatus.ACTIVE,
                    ApiInstanceHeartbeatModel.last_heartbeat_at >= threshold,
                )

                # Ordina gli identificatori delle repliche in modo deterministico
                .order_by(ApiInstanceHeartbeatModel.instance_id.asc())
            ).all()

        # Se la query fallisce non è possibile determinare con affidabilità la disponibilità delle repliche
        except SQLAlchemyError:

            # Ripristina l'eventuale transazione corrente
            session.rollback()

            # Registra il fallimento della query senza interrompere la costruzione dello snapshot
            logger.warning("API replica heartbeat query failed for system status.")

            # In caso di errore di lettura lo stato della Analysis API viene rappresentato come DEGRADED
            return SystemServiceSnapshot(
                name="analysis-api",
                status=SystemStatusLevel.DEGRADED,
                message="API replica availability could not be determined.",
                last_checked_at=checked_at,
                details={
                    "version": settings.app_version,
                    "instance_id": settings.instance_id,
                    "configured_instances": settings.configured_api_replicas,
                    "active_instances": 0,
                    "active_instance_ids": [],
                },
            )

        finally:

            # Chiude sempre la Session utilizzata per il controllo degli heartbeat API
            session.close()

        # Estrae dalla risposta SQLAlchemy soltanto gli instance_id rappresentati effettivamente come stringhe
        active_instance_ids = [row[0] for row in rows if isinstance(row[0], str)]

        # Conta quante repliche risultano attive e non stale
        active_instances_count = len(active_instance_ids)

        # Se nessuna replica risulta attiva entro la finestra di heartbeat la Analysis API viene considerata UNAVAILABLE
        if active_instances_count <= 0:
            return SystemServiceSnapshot(
                name="analysis-api",
                status=SystemStatusLevel.UNAVAILABLE,
                message="No active API replica detected within the heartbeat timeout window.",
                last_checked_at=checked_at,
                details={
                    "version": settings.app_version,
                    "instance_id": settings.instance_id,
                    "configured_instances": settings.configured_api_replicas,
                    "active_instances": 0,
                    "active_instance_ids": [],
                    "heartbeat_timeout_seconds": settings.api_heartbeat_timeout_seconds,
                },
            )

        # Se almeno una replica è attiva ma il numero è inferiore a quello configurato, il servizio viene considerato DEGRADED
        if active_instances_count < settings.configured_api_replicas:
            return SystemServiceSnapshot(
                name="analysis-api",
                status=SystemStatusLevel.DEGRADED,
                message=(
                    f"{active_instances_count} of {settings.configured_api_replicas} API replicas are active."
                ),
                last_checked_at=checked_at,
                details={
                    "version": settings.app_version,
                    "instance_id": settings.instance_id,
                    "configured_instances": settings.configured_api_replicas,
                    "active_instances": active_instances_count,
                    "active_instance_ids": active_instance_ids,
                    "heartbeat_timeout_seconds": settings.api_heartbeat_timeout_seconds,
                },
            )

        # Se il numero di repliche attive è almeno pari a quello configurato, la Analysis API viene considerata HEALTHY
        return SystemServiceSnapshot(
            name="analysis-api",
            status=SystemStatusLevel.HEALTHY,
            message=f"{active_instances_count} API replicas are active.",
            last_checked_at=checked_at,
            details={
                "version": settings.app_version,
                "instance_id": settings.instance_id,
                "configured_instances": settings.configured_api_replicas,
                "active_instances": active_instances_count,
                "active_instance_ids": active_instance_ids,
                "heartbeat_timeout_seconds": settings.api_heartbeat_timeout_seconds,
            },
        )

    # Verifica che il database accetti almeno una query SQL minima
    def _build_database_status(self, checked_at: datetime) -> SystemServiceSnapshot:
        """Verifica il database con una query minima indipendente dai repository."""

        # Crea una Session SQLAlchemy dedicata al controllo di raggiungibilità del database
        session = session_manager.session_factory()

        try:

            # `SELECT 1` verifica che sia possibile comunicare con il database ed eseguire una query minima
            session.execute(text("SELECT 1"))

            # Se la query riesce il database viene considerato raggiungibile
            return SystemServiceSnapshot(
                name="postgres",
                status=SystemStatusLevel.HEALTHY,
                message="Database is reachable.",
                last_checked_at=checked_at,
                details={},
            )

        # Un errore SQLAlchemy durante la query rende il database UNAVAILABLE per questo controllo
        except SQLAlchemyError as exc:

            # Annulla l'eventuale transazione corrente
            session.rollback()

            # Registra il fallimento del controllo
            logger.warning("Database reachability check failed for system status.")

            # Restituisce lo stato di indisponibilità del database
            return SystemServiceSnapshot(
                name="postgres",
                status=SystemStatusLevel.UNAVAILABLE,
                message="Database is unreachable.",
                last_checked_at=checked_at,
                details={},
            )

        finally:

            # Chiude sempre la Session utilizzata per il probe del database
            session.close()

    # Valuta se esiste almeno un worker ACTIVE con heartbeat abbastanza recente
    def _build_worker_status(self, checked_at: datetime) -> SystemServiceSnapshot:
        # The worker is monitored separately from the API because queued uploads
        # can accumulate even while synchronous endpoints remain available.

        # Calcola la soglia temporale oltre la quale un heartbeat worker viene considerato stale
        threshold = checked_at - timedelta(seconds=settings.worker_heartbeat_timeout_seconds)

        # Crea una Session SQLAlchemy dedicata alla lettura degli heartbeat dei worker
        session = session_manager.session_factory()

        try:

            # Conta direttamente nel database i worker ACTIVE il cui ultimo heartbeat rientra nella finestra temporale valida
            active_workers = session.scalar(
                select(func.count())
                .select_from(WorkerHeartbeatModel)
                .where(
                    WorkerHeartbeatModel.status == WorkerHeartbeatStatus.ACTIVE,
                    WorkerHeartbeatModel.last_heartbeat_at >= threshold,
                )
            )

            # Converte il risultato SQLAlchemy in intero utilizzando zero se il valore restituito fosse nullo o falso
            active_workers_count = int(active_workers or 0)

        # Se la query fallisce la disponibilità dei worker non può essere determinata correttamente
        except SQLAlchemyError as exc:

            # Annulla l'eventuale transazione corrente
            session.rollback()

            # Registra il fallimento della query degli heartbeat worker
            logger.warning("Worker heartbeat query failed for system status.")

            # Un errore di lettura degli heartbeat worker degrada lo stato del componente senza rendere necessariamente indisponibile l'intera piattaforma
            return SystemServiceSnapshot(
                name="analysis-worker",
                status=SystemStatusLevel.DEGRADED,
                message="Worker availability could not be determined.",
                last_checked_at=checked_at,
                details={"active_workers": 0},
            )

        finally:

            # Chiude sempre la Session utilizzata per il controllo degli heartbeat worker
            session.close()

        # Se nessun worker ACTIVE ha un heartbeat recente, il componente viene considerato DEGRADED
        if active_workers_count <= 0:
            return SystemServiceSnapshot(
                name="analysis-worker",
                status=SystemStatusLevel.DEGRADED,
                message="No active worker detected within the heartbeat timeout window.",
                last_checked_at=checked_at,
                details={
                    "active_workers": 0,
                    "heartbeat_timeout_seconds": settings.worker_heartbeat_timeout_seconds,
                },
            )

        # Seleziona la forma singolare o plurale da utilizzare nel messaggio restituito
        noun = "worker" if active_workers_count == 1 else "workers"

        # La presenza di almeno un worker ACTIVE e non stale rende il componente HEALTHY
        return SystemServiceSnapshot(
            name="analysis-worker",
            status=SystemStatusLevel.HEALTHY,
            message=f"{active_workers_count} active {noun} detected.",
            last_checked_at=checked_at,
            details={
                "active_workers": active_workers_count,
                "heartbeat_timeout_seconds": settings.worker_heartbeat_timeout_seconds,
            },
        )

    # Verifica direttamente la raggiungibilità del daemon ClamAV attraverso il protocollo TCP interno
    def _build_clamav_status(self, checked_at: datetime) -> SystemServiceSnapshot:
        # ClamAV is intentionally checked over the internal Docker network rather
        # than through Kong, because the antivirus daemon is not a public service.

        try:

            # Apre una connessione TCP verso host e porta configurati per il daemon ClamAV
            with socket.create_connection(
                (settings.clamd_host, settings.clamd_port),
                timeout=settings.clamd_timeout_seconds,
            ) as sock:

                # Imposta anche sulle successive operazioni del socket lo stesso timeout configurato
                sock.settimeout(settings.clamd_timeout_seconds)

                # Invia a ClamAV il comando `zVERSION` terminato da byte nullo per richiedere la versione del daemon
                sock.sendall(b"zVERSION\0")

                # Riceve la risposta, la converte da byte a stringa e rimuove terminatori e spazi superflui
                payload = sock.recv(4096).decode("utf-8", errors="replace").rstrip("\0").strip()

        # Un errore di rete o socket viene interpretato come indisponibilità temporanea del motore antimalware
        except OSError:
            return SystemServiceSnapshot(
                name="clamav",
                status=SystemStatusLevel.DEGRADED,
                message="Motore antimalware temporaneamente non raggiungibile.",
                last_checked_at=checked_at,
                details={},
            )

        # Se connessione, invio e ricezione hanno successo ClamAV viene considerato HEALTHY
        return SystemServiceSnapshot(
            name="clamav",
            status=SystemStatusLevel.HEALTHY,
            message="Motore antimalware raggiungibile.",
            last_checked_at=checked_at,
            details={"version": payload},
        )

    # Converte il risultato di un probe HTTP in uno snapshot uniforme per una dipendenza tecnica
    def _build_http_dependency_status(
        self,
        *,
        name: str,
        checked_at: datetime,
        url: str,
        healthy_message: str,
        unavailable_message: str,
    ) -> SystemServiceSnapshot:
        """Converte un probe HTTP minimale in una voce dello stato sistema."""

        # Una risposta HTTP 2xx produce HEALTHY mentre un probe fallito produce DEGRADED
        status = SystemStatusLevel.HEALTHY if self._is_http_endpoint_reachable(url) else SystemStatusLevel.DEGRADED

        # Costruisce lo snapshot della dipendenza usando il messaggio coerente con il risultato del probe
        return SystemServiceSnapshot(
            name=name,
            status=status,
            message=healthy_message if status == SystemStatusLevel.HEALTHY else unavailable_message,
            last_checked_at=checked_at,
            details={},
        )

    # Esegue un probe HTTP sincrono e restituisce soltanto se l'endpoint risulta raggiungibile tramite una risposta 2xx
    @staticmethod
    def _is_http_endpoint_reachable(url: str) -> bool:

        try:

            # Apre l'URL usando il timeout configurato per i servizi di monitoring
            with urlopen(url, timeout=settings.monitoring_http_timeout_seconds) as response:

                # Considera raggiungibile soltanto una risposta HTTP compresa tra 200 e 299
                return 200 <= response.status < 300

        # Gli errori HTTP, di rete, timeout, URL e decoding previsti vengono trasformati semplicemente in un risultato False
        except (HTTPError, URLError, TimeoutError, ValueError, JSONDecodeError):

            # Registra a livello debug l'URL per il quale il probe non è riuscito
            logger.debug("Monitoring dependency check failed: url=%s", url)

            return False

    # Combina gli stati dei singoli componenti applicando una priorità maggiore ai servizi considerati essenziali
    @staticmethod
    def _aggregate_overall_status(
        services: list[SystemServiceSnapshot],
    ) -> SystemStatusLevel:

        # Analysis API e PostgreSQL sono i soli servizi che, se UNAVAILABLE, rendono direttamente UNAVAILABLE lo stato complessivo
        essential_services = {"analysis-api", "postgres"}

        # Se almeno uno dei servizi essenziali è UNAVAILABLE, l'intera piattaforma viene dichiarata UNAVAILABLE
        if any(
            service.status == SystemStatusLevel.UNAVAILABLE and service.name in essential_services
            for service in services
        ):
            return SystemStatusLevel.UNAVAILABLE

        # Se nessun servizio essenziale è indisponibile ma almeno un componente è DEGRADED o UNAVAILABLE, lo stato complessivo diventa DEGRADED
        if any(
            service.status in {SystemStatusLevel.DEGRADED, SystemStatusLevel.UNAVAILABLE}
            for service in services
        ):
            return SystemStatusLevel.DEGRADED

        # Se tutti i componenti risultano HEALTHY, anche lo stato complessivo è HEALTHY
        return SystemStatusLevel.HEALTHY


# Dependency FastAPI che crea una nuova istanza stateless di SystemStatusService quando richiesta dall'endpoint
def get_system_status_service() -> SystemStatusService:
    """Dependency FastAPI per il servizio di stato sistema."""

    # Il service non mantiene stato interno persistente, quindi può essere creato direttamente a ogni risoluzione della dependency
    return SystemStatusService()
