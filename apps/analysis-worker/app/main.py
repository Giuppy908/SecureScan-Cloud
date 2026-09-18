"""Entrypoint FastAPI del worker asincrono.

Questo file non corrisponde direttamente a una pagina del sito. Serve ad
avviare il processo che, in background:
- interroga PostgreSQL per cercare nuovi job `queued`;
- esegue la pipeline metadata + ClamAV + YARA;
- aggiorna il record finale visibile in Cronologia e Dettaglio analisi;
- espone `/health` e `/metrics` per osservabilità e Stato del sistema.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# FastAPI viene usato per creare l'applicazione HTTP del worker
from fastapi import FastAPI

# JSONResponse serve per /health, mentre Response rappresenta la risposta generica usata da /metrics
from fastapi.responses import JSONResponse, Response

# Configurazione globale già caricata e validata durante l'import di config.py
from app.core.config import settings

# Funzione che serializza le metriche del worker nel formato Prometheus
from app.services.metrics import render_metrics

# Componenti che gestiscono stato runtime, loop del worker e costruzione della risposta health
from app.services.worker import AnalysisWorkerLoop, WorkerRuntimeState, health_payload


# Stato condiviso del worker, utilizzato sia dai thread background sia dagli endpoint di osservabilità
runtime_state = WorkerRuntimeState()

# Crea il runtime principale che gestisce polling, heartbeat e processing dei job
worker_loop = AnalysisWorkerLoop(runtime_state)

# Crea l'app FastAPI usando nome e versione definiti nella configurazione del worker
app = FastAPI(title=settings.app_name, version=settings.app_version)


# Registra una funzione eseguita automaticamente da FastAPI durante lo startup dell'applicazione
@app.on_event("startup")
def startup() -> None:
    """Avvia il loop di polling e il loop heartbeat quando parte il container."""

    # Avvia i thread background del worker dedicati al polling e agli heartbeat
    worker_loop.start()


# Registra una funzione eseguita automaticamente durante lo shutdown dell'applicazione
@app.on_event("shutdown")
def shutdown() -> None:
    """Ferma ordinatamente i thread background quando il processo termina."""

    # Segnala l'arresto al runtime e attende la terminazione dei thread secondo la logica definita in worker.py
    worker_loop.stop()


# Espone l'endpoint HTTP utilizzato per verificare lo stato operativo del worker
@app.get("/health")
def get_health() -> JSONResponse:
    """Espone lo stato operativo del worker a Docker e all'Analysis API."""

    # Costruisce codice HTTP e payload verificando lo stato runtime e la raggiungibilità del database
    status_code, payload = health_payload(runtime_state)

    # Restituisce il payload JSON con il codice HTTP determinato dal controllo di salute
    return JSONResponse(status_code=status_code, content=payload)


# Espone le metriche Prometheus senza includere l'endpoint nella documentazione OpenAPI
@app.get("/metrics", include_in_schema=False)
def get_metrics() -> Response:
    """Espone le metriche Prometheus raccolte durante il lavoro del worker."""

    # Legge uno snapshot consistente dello stato runtime e lo usa per aggiornare ed esportare le metriche
    return render_metrics(runtime_state.snapshot())
