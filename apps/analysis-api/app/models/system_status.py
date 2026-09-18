"""Schemi Pydantic per la pagina Stato del sistema.

La pagina amministrativa Stato del sistema riceve questi modelli per mostrare
lo stato di analysis-api, worker, database, Kong, Prometheus, Grafana e altri
componenti tecnici dell'architettura.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SystemStatusLevel(str, Enum):
    """Livelli di salute semplificati mostrati nella pagina Stato del sistema."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SystemServiceSnapshot(BaseModel):
    """Stato di un singolo componente mostrato nella pagina Stato del sistema."""

    name: str
    status: SystemStatusLevel
    message: str
    last_checked_at: datetime
    details: dict[str, str | int | float | bool | None | list[str]] = Field(default_factory=dict)


class SystemStatusSnapshot(BaseModel):
    """Snapshot complessivo mostrato nella pagina Stato del sistema."""

    overall_status: SystemStatusLevel
    checked_at: datetime
    services: list[SystemServiceSnapshot]
