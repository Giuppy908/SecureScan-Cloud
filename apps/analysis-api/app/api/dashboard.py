"""Endpoint che alimenta la pagina Dashboard.

Il frontend non calcola questi numeri da solo e non scarica tutte le analisi
per aggregarle nel browser. Questa API restituisce direttamente i contatori,
lo storico giornaliero e la distribuzione del rischio già filtrati in base al
ruolo dell'utente autenticato.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.security import AuthenticatedUser, require_analyst
from app.models.dashboard import DashboardSnapshot
from app.services.dashboard import DashboardService, get_dashboard_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSnapshot)
def get_dashboard_snapshot(
    user: AuthenticatedUser = Depends(require_analyst),
    service: DashboardService = Depends(get_dashboard_service),
) -> DashboardSnapshot:
    """Restituisce una snapshot aggregata coerente con il ruolo dell'utente.

    Gli analyst vedono solo metriche sulle proprie analisi; gli admin vedono
    l'intero dataset. L'aggregazione resta server-side per evitare conteggi
    incoerenti o sovraesposizione di dati non autorizzati al browser.
    """
    try:
        owner_sub = None if "admin" in user.roles else user.subject
        return service.collect_snapshot(owner_sub=owner_sub)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to produce dashboard snapshot.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve dashboard snapshot.",
        ) from exc
