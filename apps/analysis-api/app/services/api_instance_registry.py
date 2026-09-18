"""Heartbeat applicativo delle repliche API.

Questo file non corrisponde a una pagina utente, ma alimenta soprattutto la
pagina Stato del sistema. Ogni replica API aggiorna periodicamente PostgreSQL
per dimostrare che non è soltanto avviata, ma che sta ancora eseguendo il
proprio loop applicativo.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `logging` permette di registrare nei log informazioni e warning relativi al ciclo di vita dell'heartbeat
import logging

# `threading` fornisce il thread che esegue gli heartbeat periodici e l'Event usato per richiederne l'arresto
import threading

# Configurazione applicativa contenente instance_id, hostname, abilitazione e intervallo dell'heartbeat API
from app.core.config import settings

# Gestore delle sessioni SQLAlchemy usato per creare una nuova Session per ogni operazione sul registro delle istanze
from app.db.session import session_manager

# Repository che persiste gli heartbeat nel database ed eccezione specifica utilizzata per gestire gli errori di persistenza
from app.repositories.api_instance_registry_repository import (
    ApiInstanceRegistryError,
    ApiInstanceRegistryRepository,
)


# Logger associato a questo modulo
logger = logging.getLogger(__name__)


# Gestisce il ciclo di vita dell'heartbeat della singola replica Analysis API
class ApiInstanceRegistryLoop:
    """Mantiene la registrazione della replica API corrente nel database."""

    # Prepara il meccanismo di stop e il riferimento al thread che verrà creato durante start()
    def __init__(self) -> None:

        # `Event` è una primitive di sincronizzazione che permette a un thread di attendere finché non viene richiesto lo stop
        self._stop_event = threading.Event()

        # Il riferimento al thread parte da None e verrà valorizzato quando il loop viene avviato
        self._thread: threading.Thread | None = None

    # Registra la replica corrente e avvia il thread che invierà periodicamente gli heartbeat
    def start(self) -> None:
        """Registra la replica corrente e avvia il thread heartbeat."""

        # Se l'heartbeat API è disabilitato dalla configurazione, il service non avvia alcuna attività
        if not settings.api_heartbeat_enabled:
            return

        # Evita di creare un secondo thread se quello precedente esiste ed è ancora in esecuzione
        if self._thread is not None and self._thread.is_alive():
            return

        # Registra subito la replica nel database prima di avviare il ciclo periodico
        self._register_instance()

        # Porta l'Event nello stato non impostato, permettendo al nuovo loop di continuare a eseguire gli heartbeat
        self._stop_event.clear()

        # Crea un thread separato che eseguirà `_run_forever` indipendentemente dalla gestione delle richieste HTTP
        self._thread = threading.Thread(
            target=self._run_forever,

            # Assegna al thread un nome che include l'identificatore della replica per facilitarne il riconoscimento nei log e nel debug
            name=f"api-instance-heartbeat-{settings.instance_id}",

            # Un thread daemon non impedisce autonomamente la terminazione del processo Python
            daemon=True,
        )

        # Avvia effettivamente il thread e quindi l'esecuzione concorrente di `_run_forever`
        self._thread.start()

        # Registra nei log l'avvio del monitoraggio heartbeat della replica corrente
        logger.info(
            "API instance started: instance_id=%s hostname=%s",
            settings.instance_id,
            settings.hostname,
        )

    # Richiede l'arresto del thread e tenta di registrare nel database uno shutdown ordinato della replica
    def stop(self) -> None:
        """Arresta il loop e prova a segnare la replica come fermata pulita."""

        # Se l'heartbeat era disabilitato non esiste alcun loop da arrestare
        if not settings.api_heartbeat_enabled:
            return

        # Imposta l'Event di stop, facendo terminare l'attesa di `_run_forever`
        self._stop_event.set()

        # Se il thread è stato creato, attende la sua terminazione per un massimo di cinque secondi
        if self._thread is not None:
            self._thread.join(timeout=5)

        # Dopo l'attesa prova a impostare nel database lo stato persistito della replica a STOPPED
        self._mark_stopped()

        # Registra nei log il completamento della procedura di arresto
        logger.info("API instance stopped: instance_id=%s", settings.instance_id)

    # Loop eseguito dal thread daemon che attende l'intervallo configurato e invia un heartbeat finché non riceve lo stop
    def _run_forever(self) -> None:
        """Esegue heartbeat periodici finché il thread non riceve lo stop."""

        # `wait(timeout)` restituisce False se il timeout scade senza stop e True se l'Event viene impostato
        while not self._stop_event.wait(settings.api_heartbeat_interval_seconds):

            # Se l'intervallo è trascorso senza richiesta di stop viene aggiornato l'heartbeat della replica
            self._send_heartbeat()

    # Registra nel database la presenza della replica durante il bootstrap
    def _register_instance(self) -> None:
        """Scrive la registrazione iniziale della replica al bootstrap."""

        # Crea una nuova Session SQLAlchemy dedicata esclusivamente a questa operazione
        session = session_manager.session_factory()

        try:

            # Costruisce il repository sulla Session appena creata e registra instance_id e hostname della replica corrente
            ApiInstanceRegistryRepository(session).register_instance(
                settings.instance_id,
                settings.hostname,
            )

        # Un errore di persistenza viene trattato come warning e non impedisce l'avvio dell'API
        except ApiInstanceRegistryError:

            # Registra il fallimento includendo l'identificatore della replica coinvolta
            logger.warning(
                "API instance registration failed.",
                extra={"instance_id": settings.instance_id},
            )

        finally:

            # Chiude sempre la Session SQLAlchemy anche se la registrazione ha generato un errore
            session.close()

    # Aggiorna periodicamente nel database il timestamp dell'ultimo heartbeat della replica
    def _send_heartbeat(self) -> None:
        """Aggiorna il heartbeat della replica senza modificarne lo started_at."""

        # Ogni heartbeat utilizza una nuova Session SQLAlchemy indipendente dalle precedenti
        session = session_manager.session_factory()

        try:

            # Il repository aggiorna il record della replica mantenendola ACTIVE e modificando last_heartbeat_at
            ApiInstanceRegistryRepository(session).touch_instance(
                settings.instance_id,
                settings.hostname,
            )

        # Gli errori di persistenza vengono intercettati per evitare che un singolo heartbeat interrompa definitivamente il loop
        except ApiInstanceRegistryError:

            # Registra un warning e permette al thread di tentare nuovamente al ciclo successivo
            logger.warning(
                "API instance heartbeat update failed.",
                extra={"instance_id": settings.instance_id},
            )

        finally:

            # La Session viene sempre chiusa al termine del singolo tentativo di heartbeat
            session.close()

    # Tenta di registrare nel database che la replica è stata arrestata attraverso uno shutdown ordinato
    def _mark_stopped(self) -> None:
        """Tenta di marcare la replica come `stopped` durante lo shutdown."""

        # Crea una nuova Session dedicata alla registrazione dello stato STOPPED
        session = session_manager.session_factory()

        try:

            # Chiede al repository di impostare a STOPPED il record associato all'instance_id corrente
            ApiInstanceRegistryRepository(session).mark_stopped(settings.instance_id)

        # Anche un errore durante lo shutdown viene registrato senza essere rilanciato dal service
        except ApiInstanceRegistryError:

            # Registra il fallimento dell'aggiornamento dello stato
            logger.warning(
                "Failed to mark API instance as stopped.",
                extra={"instance_id": settings.instance_id},
            )

        finally:

            # Chiude sempre la Session utilizzata durante la procedura di stop
            session.close()
