"""Servizio che costruisce i dati mostrati nella Dashboard.

La Dashboard non scarica tutte le analisi per poi fare i calcoli nel browser.
Questo servizio interroga il database, applica lo scope RBAC e restituisce
solo gli aggregati già pronti per i widget dell'interfaccia.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `date` rappresenta una data senza orario ed è utilizzato per i bucket giornalieri del grafico temporale
from datetime import date

# `Depends` permette a FastAPI di risolvere automaticamente la Session necessaria al service
from fastapi import Depends

# `func` espone funzioni SQL come COUNT e DATE, mentre `select` permette di costruire query SQLAlchemy
from sqlalchemy import func, select

# `Session` rappresenta una sessione SQLAlchemy attraverso cui il service esegue le query sul database
from sqlalchemy.orm import Session

# Modello ORM che rappresenta i record della tabella `analyses` utilizzati per costruire tutte le statistiche della Dashboard
from app.db.models import AnalysisRecordModel

# Dependency che fornisce una Session SQLAlchemy gestita per la durata della richiesta FastAPI
from app.db.session import get_db_session

# Modelli di dominio ed enum utilizzati per rappresentare analisi, stati del job e livelli di rischio
from app.models.analysis import Analysis, AnalysisStatus, RiskLevel

# Modelli Pydantic che costituiscono le diverse sezioni della risposta restituita alla Dashboard
from app.models.dashboard import (
    DashboardAnalysesOverTimeEntry,
    DashboardRiskDistributionEntry,
    DashboardSnapshot,
    DashboardSummary,
)


# Ordine fisso con cui i livelli di rischio vengono restituiti alla Dashboard, dal più grave al meno grave
RISK_ORDER = (
    RiskLevel.CRITICAL,
    RiskLevel.HIGH,
    RiskLevel.MEDIUM,
    RiskLevel.LOW,
)


# Service che esegue le query aggregate necessarie a costruire i dati mostrati nella Dashboard
class DashboardService:
    """Costruisce la risposta completa usata dalla pagina Dashboard."""

    # Riceve una Session SQLAlchemy già creata dalla dependency FastAPI e la conserva per le query del service
    def __init__(self, session: Session) -> None:

        # La Session viene salvata nell'istanza e riutilizzata dai diversi metodi che costruiscono lo snapshot
        self._session = session

    # Costruisce lo snapshot completo della Dashboard aggregando contatori, rischio, analisi recenti e andamento temporale
    def collect_snapshot(self, owner_sub: str | None = None) -> DashboardSnapshot:
        """Aggrega i dati che popolano i riquadri e i grafici della Dashboard."""

        # Conta le analisi raggruppandole per stato tecnico ed eventualmente limitandole al proprietario indicato
        status_counts = self._collect_status_counts(owner_sub)

        # Conta le analisi raggruppandole per livello di rischio applicando lo stesso eventuale filtro di ownership
        risk_counts = self._collect_risk_counts(owner_sub)

        # Recupera le cinque analisi più recenti visibili nello scope corrente
        recent_analyses = self._collect_recent_analyses(limit=5, owner_sub=owner_sub)

        # Recupera gli ultimi quattordici bucket giornalieri che contengono almeno un'analisi
        analyses_over_time = self._collect_analyses_over_time(limit=14, owner_sub=owner_sub)

        # Costruisce i contatori principali mostrati nei riquadri riepilogativi della Dashboard
        summary = DashboardSummary(

            # Il totale viene ottenuto sommando i conteggi di tutti gli stati tecnici dell'analisi
            total_analyses=sum(status_counts.values()),

            # Numero di analisi persistite nello stato tecnico COMPLETED
            completed=status_counts[AnalysisStatus.COMPLETED],

            # Numero di analisi attualmente nello stato PROCESSING
            processing=status_counts[AnalysisStatus.PROCESSING],

            # Numero di analisi ancora in attesa nello stato QUEUED
            queued=status_counts[AnalysisStatus.QUEUED],

            # Numero di analisi persistite nello stato tecnico FAILED
            failed=status_counts[AnalysisStatus.FAILED],
        )

        # Trasforma i conteggi per rischio in una lista ordinata pronta per essere utilizzata dai widget della Dashboard
        risk_distribution = [

            # Costruisce una voce composta dal livello di rischio e dal relativo numero di analisi
            DashboardRiskDistributionEntry(risk_level=risk_level, count=risk_counts[risk_level])

            # Itera sempre secondo RISK_ORDER così l'ordine della risposta non dipende dall'ordine restituito dal database
            for risk_level in RISK_ORDER
        ]

        # Restituisce tutte le sezioni della Dashboard raccolte in un unico modello di risposta
        return DashboardSnapshot(
            summary=summary,
            risk_distribution=risk_distribution,
            recent_analyses=recent_analyses,
            analyses_over_time=analyses_over_time,
        )

    # Conta le analisi per ciascuno stato tecnico persistito nel database
    def _collect_status_counts(self, owner_sub: str | None) -> dict[AnalysisStatus, int]:

        # Inizializza tutti gli stati possibili a zero così la risposta contiene anche categorie senza record
        counts = {status: 0 for status in AnalysisStatus}

        # Prepara una query che seleziona stato e COUNT(*) dalla tabella delle analisi
        statement = select(AnalysisRecordModel.status, func.count())

        # Se viene fornito owner_sub, limita il conteggio alle sole analisi appartenenti a quell'utente
        if owner_sub is not None:
            statement = statement.where(AnalysisRecordModel.owner_sub == owner_sub)

        # Raggruppa i record per stato ed esegue la query ottenendo una riga per ogni stato presente nel database
        rows = self._session.execute(statement.group_by(AnalysisRecordModel.status)).all()

        # Scorre le coppie stato-conteggio restituite dal database
        for raw_status, raw_count in rows:

            # Accetta soltanto valori riconosciuti come membri dell'enum AnalysisStatus
            if isinstance(raw_status, AnalysisStatus):

                # Salva il conteggio convertendolo esplicitamente in intero
                counts[raw_status] = int(raw_count)

        # Restituisce il dizionario completo con tutti gli stati, compresi quelli rimasti a zero
        return counts

    # Conta le analisi per ciascun livello di rischio persistito nel database
    def _collect_risk_counts(self, owner_sub: str | None) -> dict[RiskLevel, int]:

        # Inizializza tutti i livelli di rischio a zero così anche quelli assenti saranno presenti nello snapshot
        counts = {risk: 0 for risk in RiskLevel}

        # Prepara una query che seleziona livello di rischio e relativo COUNT(*)
        statement = select(AnalysisRecordModel.risk_level, func.count())

        # Se owner_sub è presente, applica il filtro di ownership prima dell'aggregazione
        if owner_sub is not None:
            statement = statement.where(AnalysisRecordModel.owner_sub == owner_sub)

        # Raggruppa i record per risk_level ed esegue la query
        rows = self._session.execute(statement.group_by(AnalysisRecordModel.risk_level)).all()

        # Scorre le coppie rischio-conteggio restituite dal database
        for raw_risk, raw_count in rows:

            # Considera soltanto valori riconosciuti come membri dell'enum RiskLevel
            if isinstance(raw_risk, RiskLevel):

                # Aggiorna il conteggio del relativo livello di rischio
                counts[raw_risk] = int(raw_count)

        # Restituisce tutti i livelli di rischio con il rispettivo conteggio
        return counts

    # Recupera un numero limitato di analisi ordinate dalla più recente alla meno recente
    def _collect_recent_analyses(self, *, limit: int, owner_sub: str | None) -> list[Analysis]:

        # Prepara una query che seleziona i record completi della tabella analyses
        statement = select(AnalysisRecordModel)

        # Se necessario limita la query alle analisi appartenenti al subject indicato
        if owner_sub is not None:
            statement = statement.where(AnalysisRecordModel.owner_sub == owner_sub)

        # Esegue la query restituendo direttamente gli oggetti ORM AnalysisRecordModel
        records = self._session.scalars(
            statement

            # Ordina prima per created_at decrescente e usa sequence_number come secondo criterio deterministico
            .order_by(AnalysisRecordModel.created_at.desc(), AnalysisRecordModel.sequence_number.desc())

            # Limita il numero massimo di record restituiti
            .limit(limit)
        ).all()

        # Converte ogni record ORM nel modello di dominio Analysis utilizzato dalla risposta API
        return [self._to_analysis(record) for record in records]

    # Raggruppa le analisi per giorno di creazione e restituisce soltanto gli ultimi bucket giornalieri disponibili
    def _collect_analyses_over_time(self, *, limit: int, owner_sub: str | None) -> list[DashboardAnalysesOverTimeEntry]:
        """Restituisce solo i giorni con analisi reali per tenere la UI compatta."""

        # `DATE(created_at)` estrae soltanto la componente data dal timestamp di creazione per poter raggruppare le analisi per giorno
        bucket_expression = func.date(AnalysisRecordModel.created_at)

        # Seleziona la data del bucket e il numero di analisi appartenenti a quel giorno
        statement = select(bucket_expression.label("bucket_date"), func.count().label("count"))

        # Applica eventualmente lo stesso filtro di ownership utilizzato nelle altre statistiche della Dashboard
        if owner_sub is not None:
            statement = statement.where(AnalysisRecordModel.owner_sub == owner_sub)

        # Raggruppa per giorno e ordina cronologicamente i bucket dal più vecchio al più recente
        rows = self._session.execute(
            statement.group_by(bucket_expression).order_by(bucket_expression.asc())
        ).all()

        # Converte ogni riga SQLAlchemy nel modello utilizzato dal grafico temporale della Dashboard
        entries = [
            DashboardAnalysesOverTimeEntry(

                # Normalizza il valore della data restituito dal database nel tipo Python `date`
                bucket_date=self._normalize_bucket_date(raw_bucket_date),

                # Converte il conteggio del bucket in un intero
                count=int(raw_count),
            )
            for raw_bucket_date, raw_count in rows
        ]

        # Mantiene soltanto gli ultimi `limit` bucket esistenti, non necessariamente gli ultimi `limit` giorni di calendario
        return entries[-limit:]

    # Normalizza il valore di una data restituito dal database in un oggetto Python `date`
    @staticmethod
    def _normalize_bucket_date(raw_value: object) -> date:

        # Se il driver SQLAlchemy ha già restituito un oggetto date, non serve alcuna conversione
        if isinstance(raw_value, date):
            return raw_value

        # Altrimenti converte il valore in stringa e interpreta il formato ISO come una data Python
        return date.fromisoformat(str(raw_value))

    # Converte un record ORM della tabella analyses nel modello Analysis utilizzato dalla Dashboard
    @staticmethod
    def _to_analysis(record: AnalysisRecordModel) -> Analysis:
        """Mappa un record recente nel sottoinsieme di campi utile alla dashboard."""

        # Costruisce il modello di dominio copiando soltanto i campi che questo mapping rende disponibili alla sezione delle analisi recenti
        return Analysis(

            # Identificatore pubblico dell'analisi
            id=record.id,

            # Nome del file analizzato
            file_name=record.file_name,

            # Subject OIDC del proprietario utilizzato per associare l'analisi all'utente autenticato
            owner_sub=record.owner_sub,

            # Username del proprietario conservato come informazione descrittiva
            owner_username=record.owner_username,

            # Stato tecnico persistito del job di analisi
            status=record.status,

            # Livello di rischio associato all'analisi
            risk_level=record.risk_level,

            # Timestamp di creazione del record
            created_at=record.created_at,

            # Timestamp dell'ultimo aggiornamento del record
            updated_at=record.updated_at,

            # Dimensione del file espressa in byte
            size_bytes=record.size_bytes,

            # MIME type rilevato o associato al file
            mime_type=record.mime_type,

            # Hash SHA-256 utilizzato come impronta del contenuto del file
            sha256=record.sha256,

            # Valore di entropia calcolato sul contenuto del file
            entropy=record.entropy,

            # Indica se l'estensione dichiarata del file è coerente con il MIME type rilevato
            extension_matches_mime=record.extension_matches_mime,

            # Copia gli indicatori in una nuova lista e usa una lista vuota se il valore persistito è assente
            indicators=list(record.indicators or []),

            # Eventuale messaggio di errore associato all'analisi
            error_message=record.error_message,
        )


# Dependency FastAPI che costruisce DashboardService usando la Session SQLAlchemy della richiesta corrente
def get_dashboard_service(session: Session = Depends(get_db_session)) -> DashboardService:
    """Dependency FastAPI che fornisce il servizio usato dalla Dashboard."""

    # Restituisce il service associandogli la Session risolta automaticamente da FastAPI
    return DashboardService(session)
