"""Entrypoint FastAPI della Analysis API di SecureScan Cloud.

Questo file mette insieme tutti i pezzi del backend:
- registra i router usati dalle pagine del sito;
- configura CORS per il frontend;
- aggiunge middleware comuni come correlation ID e metriche;
- avvia il loop heartbeat della replica API.

Non contiene la logica business delle singole funzionalità, ma orchestra i
componenti che permettono al servizio di partire correttamente.
"""

# Questa direttiva fa sì che le type annotation vengano valutate in modo posticipato invece che immediatamente durante la definizione di funzioni e classi
from __future__ import annotations

# Modulo standard Python usato per scrivere messaggi nei log dell'applicazione
import logging

# `asynccontextmanager` permette di definire una funzione che gestisce due momenti:
# - ciò che deve succedere quando l'applicazione FastAPI viene avviata;
# - ciò che deve succedere quando l'applicazione FastAPI viene arrestata.
#
# In questo file viene usato insieme a `lifespan`
from contextlib import asynccontextmanager

# `uuid4()` genera un UUID casuale, cioè un identificatore univoco
# Qui viene usato per creare un ID per una richiesta HTTP quando il client non ne ha già inviato uno tramite l'header `X-Request-ID`
from uuid import uuid4

# `FastAPI` è la classe con cui viene creata l'applicazione backend
from fastapi import FastAPI

# Middleware che gestisce le regole CORS
# CORS stabilisce quali applicazioni web eseguite nel browser possono effettuare richieste verso questa API quando provengono da una origin diversa
from fastapi.middleware.cors import CORSMiddleware

# Questi moduli contengono i diversi gruppi di endpoint dell'applicazione
# Ogni file espone un oggetto chiamato `router`

# In `main.py` questi router vengono soltanto importati; gli endpoint veri e propri sono definiti nei rispettivi file
from app.api.admin_users import router as admin_users_router
from app.api.analyses import router as analyses_router
from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.profile import router as profile_router
from app.api.system_status import router as system_status_router

# `settings` contiene i valori di configurazione della Analysis API
# In questo file vengono usati, ad esempio, nome e versione dell'applicazione, configurazione CORS, prefisso delle API e identificatore della replica
from app.core.config import settings

# Questo servizio gestisce l'heartbeat della singola replica Analysis API
# L'heartbeat serve a far sapere periodicamente al sistema che quella replica è ancora attiva e sta aggiornando il proprio stato.
from app.services.api_instance_registry import ApiInstanceRegistryLoop

# Queste due funzioni servono per raccogliere informazioni sulle richieste HTTP:
# `request_started_at()` memorizza un riferimento temporale all'inizio della richiesta
# `record_request()` registra poi i dati della richiesta, compresa la sua durata
from app.services.metrics import record_request, request_started_at

# Crea il logger usato in questo file
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestisce startup e shutdown applicativi della singola replica API.

    L'heartbeat applicativo viene tenuto separato dai normali health check
    container/Kong per distinguere una replica HTTP raggiungibile da una
    replica che sta davvero aggiornando il proprio stato nel database.
    """

    # Crea l'oggetto che gestirà l'heartbeat di questa replica della Analysis API
    registry_loop = ApiInstanceRegistryLoop() # In questa riga l'oggetto viene soltanto creato, il loop non è ancora partito

    # Salva il riferimento al registry loop dentro lo stato dell'applicazione FastAPI
    app.state.api_instance_registry_loop = registry_loop

    # Avvia il loop di heartbeat
    registry_loop.start() # Eseguita nella fase iniziale, prima di `yield`
    try:
        # Indica il punto in cui termina la fase di avvio
        yield # Da qui FastAPI prosegue con la normale esecuzione dell'applicazione
    finally:
        # Ferma il loop di heartbeat
        registry_loop.stop()


def create_app() -> FastAPI:
    """Crea l'applicazione FastAPI completa di middleware e router.

    Le origini CORS vengono lette dalla configurazione perché il browser
    dialoga con Kong o con il frontend pubblico, non con gli indirizzi
    Docker interni usati dai servizi server-side.
    """

    # Crea l'oggetto principale FastAPI
    app = FastAPI(
        # `title` e `version` vengono letti dalla configurazione
        title=settings.app_name,
        version=settings.app_version,
        # `lifespan=lifespan` dice a FastAPI di utilizzare la funzione definita sopra durante l'avvio e l'arresto dell'applicazione
        lifespan=lifespan,
    )

    # Aggiunge il middleware CORS all'applicazione FastAPI.
    # Questo blocco definisce quali richieste provenienti da browser con origin differenti possono essere accettate
    app.add_middleware(
        CORSMiddleware,

        # Elenco delle origini consentite, letto dalla configurazione della Analysis API definita nel modulo `app.core.config`
        allow_origins=settings.cors_origins,

        # Permette l'uso di credenziali nelle richieste cross-origin
        allow_credentials=True,

        # Metodi HTTP permessi nelle richieste CORS
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],

        # Headers che il browser è autorizzato ad inviare
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # Questa funzione viene eseguita automaticamente per ogni richiesta HTTP che attraversa l'applicazione FastAPI
    @app.middleware("http")
    async def add_instance_headers_and_log(request, call_next):
        # La metrica HTTP viene registrata qui, in un punto unico, per evitare che
        # ogni endpoint debba replicare logica di osservabilità e per includere
        # anche le eccezioni non gestite dal layer business.

        # Cerca nella richiesta l'header `X-Request-ID`
        # Se esiste già, viene mantenuto.
        # Se non esiste, viene generato un nuovo UUID.
        request_id = request.headers.get("X-Request-ID") or str(uuid4()) # Il request ID permette di identificare una specifica richiesta

        # Salva il request ID nello stato della richiesta corrente
        request.state.request_id = request_id

        # Memorizza il momento iniziale della richiesta, utilizzato per calcolare la durata della richiesta
        started_at = request_started_at()

        # Salva inizialmente il percorso ricevuto nella richiesta, che potrebbe essere modificato se FastAPI ha già identificato la route corrispondente
        route_path = request.url.path
        try:
            # Fino a questo momento il middleware ha soltanto preparato informazioni relative alla richiesta
            # `call_next(request)` dice a FastAPI di proseguire con la gestione della richiesta e di restituire la risposta una volta terminato
            # `await` aspetta che il resto della pipeline FastAPI produca una risposta
            response = await call_next(request)

            # Se la richiesta è stata gestita correttamente, registra i dati della richiesta, compreso il codice di stato della risposta
            route = request.scope.get("route")

            # Se l'oggetto `route` possiede un attributo `path`, viene utilizzato quel valore
            # Se invece non è disponibile, rimane il valore precedente contenuto in `route_path`
            route_path = getattr(route, "path", route_path)

            # Registra le informazioni della richiesta completata:
            # - metodo HTTP;
            # - route;
            # - codice di stato restituito;
            # - momento iniziale della richiesta.
            #
            # `record_request()` utilizzerà queste informazioni
            # per aggiornare le metriche
            record_request(
                method=request.method,
                route=route_path,
                status_code=response.status_code,
                started_at=started_at,
            )
        except Exception:
            # Questo blocco viene eseguito se durante la gestione della richiesta viene propagata un'eccezione fino a questo middleware

            # Prova comunque a recuperare la route associata alla richiesta
            route = request.scope.get("route")
            route_path = getattr(route, "path", route_path)

            # Anche la richiesta fallita viene registrata nelle metriche, con codice di stato 500 (errore interno del server)
            record_request(
                method=request.method,
                route=route_path,
                status_code=500,
                started_at=started_at,
            )

            # L'eccezione non viene nascosta: `raise` la propaga nuovamente ai livelli successivi di FastAPI
            raise

        # Se l'esecuzione è arrivata fino a questo punto, `response` contiene la risposta ottenuta da FastAPI
        # Aggiunge alla risposta l'ID associato alla richiesta corrente
        response.headers["X-Request-ID"] = request_id

        # Aggiunge alla risposta l'identificatore della replica che ha gestito la richiesta, così che il client conosca quale replica ha risposto
        response.headers["X-Backend-Instance"] = settings.instance_id

        # Scrive nei log una riga riassuntiva della richiesta completata.
        # Vengono registrati:
        # - ID della replica;
        # - request ID;
        # - metodo HTTP;
        # - path;
        # - status code.
        logger.info(
            "Request served: instance_id=%s request_id=%s method=%s path=%s status_code=%s",
            settings.instance_id,
            request_id,
            request.method,
            request.url.path,
            response.status_code,
        )

        # Restituisce la risposta a FastAPI dopo aver aggiunto gli header e registrato le informazioni necessarie
        return response

    # Registra nell'applicazione il router dedicato agli health check
    app.include_router(health_router)

    # Registra il router che espone le metriche
    app.include_router(metrics_router)

    # I router seguenti vengono invece registrati aggiungendo `settings.api_prefix`
    # Gli endpoint veri e propri non sono implementati in questo file
    app.include_router(analyses_router, prefix=settings.api_prefix)
    app.include_router(profile_router, prefix=settings.api_prefix)
    app.include_router(admin_users_router, prefix=settings.api_prefix)
    app.include_router(dashboard_router, prefix=settings.api_prefix)
    app.include_router(system_status_router, prefix=settings.api_prefix)

    # Restituisce l'applicazione FastAPI completamente configurata
    return app

# Questa riga viene eseguita quando il modulo viene caricato da Python
app = create_app()
