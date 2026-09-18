"""Schemi Pydantic usati dalla pagina Dashboard.

Questi modelli descrivono i dati già aggregati che il frontend mostra nei
widget della Dashboard: contatori, distribuzione del rischio, elenco recente
e andamento giornaliero delle analisi.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.models.analysis import Analysis, RiskLevel


class DashboardSummary(BaseModel):
    """Contatori principali mostrati nella parte alta della Dashboard."""

    total_analyses: int = Field(ge=0)
    completed: int = Field(ge=0)
    processing: int = Field(ge=0)
    queued: int = Field(ge=0)
    failed: int = Field(ge=0)


class DashboardRiskDistributionEntry(BaseModel):
    """Una riga della distribuzione del rischio mostrata nella Dashboard."""

    risk_level: RiskLevel
    count: int = Field(ge=0)


class DashboardAnalysesOverTimeEntry(BaseModel):
    """Un punto dello storico giornaliero usato dal riquadro Andamento analisi."""

    bucket_date: date
    count: int = Field(ge=0)


class DashboardSnapshot(BaseModel):
    """Snapshot completo che la pagina Dashboard riceve dal backend.

    Raccoglie in un solo payload tutto ciò che la pagina deve disegnare senza
    ulteriori calcoli nel browser.
    """

    summary: DashboardSummary
    risk_distribution: list[DashboardRiskDistributionEntry]
    recent_analyses: list[Analysis]
    analyses_over_time: list[DashboardAnalysesOverTimeEntry]
