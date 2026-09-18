"""Audit logging degli eventi di sicurezza della Analysis API.

Questo file non genera contenuto visibile in una pagina del sito, ma registra
azioni sensibili come login API, creazione analisi, cancellazioni o accessi
negati. I log servono a capire cosa è successo lato backend senza salvare dati
che non dovrebbero finire nel database applicativo.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `json` viene usato per serializzare il payload dell'evento di sicurezza in una stringa JSON prima di scriverlo nel log
import json

# `logging` fornisce il sistema standard Python per la gestione dei log
import logging

# `sys` viene usato per indirizzare esplicitamente il logger verso `stdout`
import sys

# `datetime` permette di generare il timestamp dell'evento
# `timezone` viene usato per specificare esplicitamente il fuso orario UTC
from datetime import datetime, timezone

# `Any` viene usato perché i dettagli aggiuntivi di un evento possono contenere valori di tipi differenti
from typing import Any

# `Request` rappresenta la richiesta HTTP corrente e permette di recuperarne informazioni come metodo, path e stato associato alla singola richiesta
from fastapi import Request

# Configurazione centralizzata della Analysis API
# In questo file viene usata per inserire nei log l'identificatore della specifica istanza backend che ha gestito l'evento
from app.core.config import settings

# Crea o recupera il logger identificato dal nome `app.security.audit`
# Questo logger è dedicato agli eventi di audit e viene configurato separatamente rispetto agli altri logger eventualmente utilizzati dall'applicazione
audit_logger = logging.getLogger("app.security.audit")


# Configura il logger dedicato all'audit logging
def configure_audit_logger() -> logging.Logger:
    """Ensure audit events are always emitted as plain JSON at INFO level."""

    # Imposta INFO come livello minimo gestito dal logger
    audit_logger.setLevel(logging.INFO)

    # Impedisce che i messaggi di questo logger vengano propagati ai logger genitori evitando, con la configurazione prevista qui, che lo stesso evento venga nuovamente gestito dalla gerarchia generale del logging Python
    audit_logger.propagate = False

    # Aggiunge un handler solo se il logger non ne possiede già uno
    # In questo modo chiamate ripetute alla funzione non aggiungono continuamente nuovi handler allo stesso logger
    if not audit_logger.handlers:

        # StreamHandler invia i messaggi a uno stream
        # In questo caso lo stream scelto è lo standard output del processo
        stream_handler = logging.StreamHandler(sys.stdout)

        # Anche l'handler accetta eventi a partire dal livello INFO
        stream_handler.setLevel(logging.INFO)

        # Il formatter stampa solamente il contenuto del messaggio senza aggiungere automaticamente livello, nome logger o altri prefissi
        # Questo permette alla stringa JSON generata successivamente di rimanere il contenuto principale della riga di log
        stream_handler.setFormatter(logging.Formatter("%(message)s"))

        # Collega l'handler appena configurato al logger di audit
        audit_logger.addHandler(stream_handler)

    # Restituisce il logger configurato
    return audit_logger


# Configura il logger immediatamente durante l'importazione del modulo quindi prima che `log_security_event()` venga utilizzata dagli altri file
configure_audit_logger()


# Funzione di supporto che genera il timestamp degli eventi di audit
def _timestamp_utc() -> str:
    """Restituisce un timestamp UTC ISO-8601 per i record di audit."""

    # Ottiene data e ora correnti in UTC e le converte nel formato ISO-8601
    return datetime.now(timezone.utc).isoformat()


# Recupera l'identificatore associato alla richiesta HTTP corrente
def get_request_id(request: Request) -> str:
    """Estrae il correlation ID assegnato dal middleware HTTP."""

    # `request.state` contiene dati associati esclusivamente alla singola richiesta
    # Il middleware HTTP della Analysis API inserisce qui il relativo `request_id`
    request_id = getattr(request.state, "request_id", None)

    # Usa il request ID solo se è effettivamente una stringa non vuota
    if isinstance(request_id, str) and request_id.strip():
        return request_id

    # Se il valore non è disponibile o non è valido viene utilizzato un placeholder
    return "-"


# Funzione centrale per la registrazione degli eventi di sicurezza
def log_security_event(
    request: Request,
    *,
    event: str,
    status_code: int,
    subject: str | None = None,
    username: str | None = None,
    roles: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
    **details: Any,
) -> None:
    """Serializza e registra un evento di sicurezza con contesto minimo utile.

    Il payload include subject, ruoli e request ID quando disponibili per
    correlare rifiuti RBAC, errori di autenticazione e azioni sensibili.
    """

    # Costruisce il payload base dell'evento di audit
    # Questi campi vengono inseriti per ogni evento registrato dalla funzione
    payload: dict[str, Any] = {

        # Momento in cui viene generato l'evento
        "timestamp": _timestamp_utc(),

        # Nome logico dell'evento, ad esempio `authentication_invalid` oppure `authorization_denied`
        "event": event,

        # Correlation ID della richiesta HTTP, utile per collegare questo evento agli altri log generati durante l'elaborazione della stessa richiesta
        "request_id": get_request_id(request),

        # Identifica la specifica istanza della Analysis API che ha gestito l'evento
        "instance_id": settings.instance_id,

        # Metodo HTTP della richiesta, ad esempio GET, POST o DELETE
        "method": request.method,

        # Percorso dell'endpoint coinvolto nella richiesta
        "path": request.url.path,

        # Codice HTTP associato all'evento
        "status_code": status_code,
    }

    # Se disponibile, registra il subject dell'utente autenticato
    if subject:
        payload["subject"] = subject

    # Se disponibile, registra lo username associato all'utente
    if username:
        payload["username"] = username

    # I ruoli vengono aggiunti solo quando sono stati forniti dal chiamante
    if roles is not None:

        # Mantiene solamente ruoli rappresentati da stringhe non vuote e li ordina per ottenere una rappresentazione stabile nel JSON
        payload["roles"] = sorted(role for role in roles if isinstance(role, str) and role.strip())

    # `details` permette ai chiamanti di aggiungere informazioni specifiche dell'evento senza dover modificare ogni volta la firma della funzione
    for key, value in details.items():

        # I dettagli con valore `None` vengono ignorati
        if value is not None:

            # Aggiunge il campo dinamico al payload
            # Poiché questa assegnazione avviene dopo i campi base, una chiave con lo stesso nome potrebbe sovrascrivere un valore precedente
            payload[key] = value

    # Converte l'intero dizionario in una stringa JSON e la invia al logger `sort_keys=True` ordina alfabeticamente le chiavi del JSON
    audit_logger.info(json.dumps(payload, sort_keys=True))
