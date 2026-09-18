"""Endpoint che alimenta la pagina Stato del sistema.

Il frontend usa questa API per mostrare se analysis-api, worker, database,
Kong, Prometheus, Grafana e ClamAV risultano disponibili. La risposta non si
limita a un semplice ping: combina probe HTTP e heartbeat applicativi.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.security import AuthenticatedUser, require_analyst
from app.models.system_status import SystemStatusSnapshot
from app.services.system_status import SystemStatusService, get_system_status_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatusSnapshot)
def get_system_status(
    _: AuthenticatedUser = Depends(require_analyst),
    service: SystemStatusService = Depends(get_system_status_service),
) -> SystemStatusSnapshot:
    """Restituisce lo stato aggregato dei componenti osservabili della piattaforma."""
    try:
        return service.collect_status()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to produce the system status snapshot.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve system status.",
        ) from exc
