"""Interfaccia comune per accedere alle analisi.

Questo file non corrisponde a una pagina del sito, ma serve indirettamente
Cronologia, Dettaglio analisi, Dashboard, Stato del sistema e worker.

L'idea è semplice: i livelli superiori chiedono "crea", "leggi", "filtra",
"aggiorna stato" senza sapere se dietro ci sia PostgreSQL o una struttura
in memoria usata nei test.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `ABC` permette di definire una classe base astratta, mentre `abstractmethod` contrassegna i metodi che le sottoclassi concrete devono implementare
from abc import ABC, abstractmethod

# Modelli di dominio utilizzati per definire in modo esplicito input e output delle operazioni offerte dal repository
from app.models.analysis import (
    Analysis,
    AnalysisCompletionResult,
    AnalysisCreateResult,
    AnalysisJob,
    AnalysisPage,
    AnalysisStatus,
    QueuedAnalysisCreate,
    RiskLevel,
)


# Eccezione specifica del layer repository utilizzata per segnalare errori di persistenza senza esporre ai livelli superiori dettagli tecnologici come SQLAlchemyError
class RepositoryError(Exception):
    """Raised when repository operations fail."""


# Classe base astratta che definisce il contratto comune che ogni repository delle analisi deve rispettare
class AnalysisRepository(ABC):
    """Contratto di persistenza e transizione di stato per le analisi."""

    # `abstractmethod` obbliga ogni sottoclasse concreta a fornire una propria implementazione di questo metodo prima di poter essere istanziata
    @abstractmethod
    # Definisce l'operazione per persistere un'analisi per la quale sono già disponibili i risultati
    def create(self, analysis_data: AnalysisCreateResult) -> Analysis:
        """Persist a new analysis."""

    # Dichiara l'operazione necessaria per creare un nuovo job inizialmente in stato QUEUED
    @abstractmethod
    def create_queued_analysis(self, analysis_data: QueuedAnalysisCreate) -> Analysis:
        """Persist a new queued analysis job."""

    # Dichiara l'operazione che assegna a un worker il job QUEUED più vecchio disponibile
    @abstractmethod
    def acquire_next_queued_analysis(self, worker_id: str) -> AnalysisJob | None:
        """Claim the oldest queued job for one worker."""

    # Dichiara la transizione di una specifica analisi dallo stato QUEUED allo stato PROCESSING
    @abstractmethod
    def mark_processing(self, analysis_id: str, worker_id: str) -> AnalysisJob:
        """Move a queued job to processing."""

    # Dichiara l'operazione che completa un job PROCESSING salvando i risultati prodotti dalla pipeline
    @abstractmethod
    def mark_completed(self, analysis_id: str, result: AnalysisCompletionResult) -> Analysis:
        """Mark a processing job as completed."""

    # Dichiara l'operazione che porta un job PROCESSING nello stato terminale FAILED registrando il relativo errore
    @abstractmethod
    def mark_failed(self, analysis_id: str, error_message: str) -> Analysis:
        """Mark a processing job as failed."""

    # Dichiara l'operazione di recovery dei job rimasti troppo a lungo in PROCESSING
    @abstractmethod
    def recover_stale_processing_jobs(
        self,
        *,
        processing_timeout_seconds: int,
        max_attempts: int,
    ) -> tuple[int, int]:
        """Requeue stale processing jobs and fail exhausted ones."""

    # Dichiara l'operazione che restituisce tutte le analisi visibili, con eventuale filtro sul proprietario
    @abstractmethod
    def list_all(self, owner_sub: str | None = None) -> list[Analysis]:
        """Return analyses ordered from newest to oldest."""

    # Dichiara l'operazione di lettura paginata e filtrata delle analisi
    @abstractmethod
    def list_page(
        self,
        *,
        owner_sub: str | None = None,
        search: str | None = None,
        status: AnalysisStatus | None = None,
        risk_level: RiskLevel | None = None,
        owner_filter: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> AnalysisPage:
        """Restituisce una pagina filtrata con totale già calcolato sul dataset visibile."""

    # Dichiara l'operazione che recupera una singola analisi tramite ID, applicando opzionalmente anche il filtro di ownership
    @abstractmethod
    def get_by_id(self, analysis_id: str, owner_sub: str | None = None) -> Analysis | None:
        """Return one analysis if present."""

    # Dichiara l'operazione che elimina tutte le analisi e restituisce i percorsi storage ancora associati ai record rimossi
    @abstractmethod
    def clear(self) -> list[str]:
        """Delete all analyses and return associated storage paths."""
