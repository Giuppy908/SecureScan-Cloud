"""Repository in memoria usato soprattutto nei test.

Questo file non viene usato dal runtime reale della demo locale, ma è molto
utile per verificare la logica di analisi senza dipendere sempre da un vero
database PostgreSQL. Mantiene quindi lo stesso contratto del repository reale.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `OrderedDict` è un dizionario che mantiene l'ordine di inserimento degli elementi, utile qui per individuare il job QUEUED più vecchio
from collections import OrderedDict

# `datetime` gestisce data e ora, `timedelta` rappresenta intervalli temporali e `timezone` permette di lavorare esplicitamente in UTC
from datetime import datetime, timedelta, timezone

# Modelli di dominio, enum e helper utilizzati per rappresentare analisi, job, risultati, filtri e stati
from app.models.analysis import (
    Analysis,
    AnalysisCompletionResult,
    AnalysisCreateResult,
    AnalysisPage,
    AnalysisJob,
    AnalysisStatus,
    QueuedAnalysisCreate,
    RiskLevel,
    get_presentation_analysis_status,
)

# Importa il contratto astratto che questa classe deve implementare e l'eccezione comune del layer repository
from app.repositories.base import AnalysisRepository, RepositoryError


# Implementazione del repository che conserva tutti i dati nella memoria del processo Python invece di utilizzare PostgreSQL
class InMemoryAnalysisRepository(AnalysisRepository):
    """Implementazione minimale del repository con transizioni di stato locali."""

    # Inizializza tutte le strutture dati locali utilizzate per simulare la persistenza e lo stato dei job
    def __init__(self) -> None:

        # Memorizza le analisi indicizzandole tramite ID pubblico e conserva anche il loro ordine di inserimento
        self._items: OrderedDict[str, Analysis] = OrderedDict()

        # Associa a ogni analisi il percorso del file temporaneo da elaborare, quando ancora necessario
        self._storage_paths: dict[str, str | None] = {}

        # Associa a ogni analisi il momento in cui è iniziata l'elaborazione oppure None se non è attualmente in processing
        self._processing_started_at: dict[str, datetime | None] = {}

        # Associa a ogni analisi l'identificatore del worker che l'ha acquisita oppure None
        self._worker_ids: dict[str, str | None] = {}

        # Mantiene per ogni analisi il numero di tentativi di elaborazione effettuati
        self._attempt_counts: dict[str, int] = {}

        # Contatore locale utilizzato per generare la parte progressiva degli ID pubblici
        self._sequence: int = 0

        # Memorizza l'anno corrente per poter azzerare il progressivo quando cambia anno
        self._year: int = datetime.now(timezone.utc).year

    # Crea direttamente un'analisi già completa e la conserva nelle strutture dati locali
    def create(self, analysis_data: AnalysisCreateResult) -> Analysis:
        """Persist a completed analysis directly."""

        # Recupera una sola volta il timestamp UTC corrente utilizzato come data di creazione e aggiornamento
        now = datetime.now(timezone.utc)

        # Genera localmente un nuovo ID pubblico nel formato ANL-ANNO-PROGRESSIVO
        analysis_id = self._next_public_id(now.year)

        # Costruisce il modello Analysis combinando ID e timestamp con tutti i valori ricevuti nel modello di input
        analysis = Analysis(
            id=analysis_id,
            created_at=now,
            updated_at=now,
            **analysis_data.model_dump(),
        )

        # Salva l'analisi nel dizionario principale usando l'ID come chiave
        self._items[analysis_id] = analysis

        # Questo percorso crea un'analisi già completa e quindi non conserva alcun file in attesa di elaborazione
        self._storage_paths[analysis_id] = None

        # Non esiste un'elaborazione in corso per questa analisi
        self._processing_started_at[analysis_id] = None

        # Nessun worker è associato inizialmente all'analisi
        self._worker_ids[analysis_id] = None

        # Il numero iniziale di tentativi viene impostato a zero
        self._attempt_counts[analysis_id] = 0

        # Restituisce il modello Analysis appena memorizzato
        return analysis

    # Crea un nuovo job in stato QUEUED che dovrà essere successivamente acquisito ed elaborato
    def create_queued_analysis(self, analysis_data: QueuedAnalysisCreate) -> Analysis:
        """Persist a queued analysis job."""

        # Recupera il timestamp UTC corrente
        now = datetime.now(timezone.utc)

        # Genera localmente il nuovo ID pubblico senza utilizzare un sequence_number proveniente dal database
        analysis_id = self._next_public_id(now.year)

        # Costruisce l'analisi iniziale con stato QUEUED e senza risultati perché il worker non ha ancora elaborato il file
        analysis = Analysis(
            id=analysis_id,
            file_name=analysis_data.file_name,
            status=AnalysisStatus.QUEUED,
            risk_level=RiskLevel.LOW,
            created_at=now,
            updated_at=now,
            owner_sub=analysis_data.owner_sub,
            owner_username=analysis_data.owner_username,
            size_bytes=analysis_data.size_bytes,
            mime_type=None,
            sha256=None,
            entropy=None,
            extension_matches_mime=None,
            indicators=[],
            error_message=None,
        )

        # Memorizza il job nel dizionario principale
        self._items[analysis_id] = analysis

        # Conserva separatamente il percorso del file che dovrà essere recuperato dal worker
        self._storage_paths[analysis_id] = analysis_data.storage_path

        # Il job non è ancora entrato nello stato PROCESSING
        self._processing_started_at[analysis_id] = None

        # Nessun worker ha ancora acquisito il job
        self._worker_ids[analysis_id] = None

        # Nessun tentativo di elaborazione è stato ancora effettuato
        self._attempt_counts[analysis_id] = 0

        # Restituisce l'analisi appena creata
        return analysis

    # Cerca il primo job QUEUED secondo l'ordine di inserimento e lo assegna al worker indicato
    def acquire_next_queued_analysis(self, worker_id: str) -> AnalysisJob | None:
        """Acquire the oldest queued job and move it to processing."""

        # Scorre le analisi nell'ordine mantenuto da OrderedDict
        for analysis in self._items.values():

            # Il primo elemento ancora QUEUED viene considerato il job più vecchio disponibile
            if analysis.status == AnalysisStatus.QUEUED:

                # Delega a mark_processing la vera transizione QUEUED -> PROCESSING
                return self.mark_processing(analysis.id, worker_id)

        # Se non esistono job disponibili restituisce None
        return None

    # Porta una specifica analisi dallo stato QUEUED allo stato PROCESSING e la associa a un worker
    def mark_processing(self, analysis_id: str, worker_id: str) -> AnalysisJob:
        """Move a queued job to processing."""

        # Recupera obbligatoriamente l'analisi richiesta oppure solleva RepositoryError se l'ID non esiste
        analysis = self._require_analysis(analysis_id)

        # La transizione è consentita soltanto se l'analisi si trova attualmente in stato QUEUED
        if analysis.status != AnalysisStatus.QUEUED:
            raise RepositoryError(f"Analysis '{analysis_id}' is not queued.")

        # Timestamp che identifica l'inizio del nuovo tentativo di elaborazione
        now = datetime.now(timezone.utc)

        # Crea una nuova copia del modello Pydantic aggiornando lo stato e azzerando alcuni risultati precedenti
        updated = analysis.model_copy(
            update={
                "status": AnalysisStatus.PROCESSING,
                "updated_at": now,
                "mime_type": None,
                "sha256": None,
                "entropy": None,
                "extension_matches_mime": None,
                "indicators": [],
                "error_message": None,
            }
        )

        # Sostituisce nel dizionario principale la precedente versione dell'analisi con quella aggiornata
        self._items[analysis_id] = updated

        # Registra quando è iniziato questo tentativo di elaborazione
        self._processing_started_at[analysis_id] = now

        # Registra quale worker ha acquisito il job
        self._worker_ids[analysis_id] = worker_id

        # Incrementa il numero di tentativi effettuati sul job
        self._attempt_counts[analysis_id] += 1

        # Costruisce e restituisce la rappresentazione compatta del job necessaria per l'elaborazione
        return AnalysisJob(
            id=updated.id,
            file_name=updated.file_name,
            size_bytes=updated.size_bytes,

            # Se il percorso non fosse disponibile viene utilizzata una stringa vuota per rispettare il tipo previsto dal modello
            storage_path=self._storage_paths[analysis_id] or "",

            # Espone al worker il numero aggiornato di tentativi
            attempt_count=self._attempt_counts[analysis_id],

            created_at=updated.created_at,
            processing_started_at=now,
            worker_id=worker_id,
        )

    # Completa un job PROCESSING copiando nell'analisi i risultati ricevuti
    def mark_completed(self, analysis_id: str, result: AnalysisCompletionResult) -> Analysis:
        """Mark one job as completed."""

        # Recupera l'analisi richiesta oppure genera RepositoryError se non esiste
        analysis = self._require_analysis(analysis_id)

        # Solo un job attualmente PROCESSING può essere completato
        if analysis.status != AnalysisStatus.PROCESSING:
            raise RepositoryError(f"Analysis '{analysis_id}' is not processing.")

        # Timestamp UTC dell'aggiornamento
        now = datetime.now(timezone.utc)

        # Crea una nuova copia dell'analisi impostando COMPLETED e copiando i risultati gestiti da questa implementazione
        updated = analysis.model_copy(
            update={
                "status": AnalysisStatus.COMPLETED,
                "risk_level": result.risk_level,
                "mime_type": result.mime_type,
                "sha256": result.sha256,
                "entropy": result.entropy,
                "extension_matches_mime": result.extension_matches_mime,
                "indicators": result.indicators,
                "error_message": result.error_message,
                "updated_at": now,
            }
        )

        # Sostituisce il modello precedente con quello completato
        self._items[analysis_id] = updated

        # Il file non è più necessario per ulteriori elaborazioni e quindi il riferimento allo storage viene rimosso
        self._storage_paths[analysis_id] = None

        # Restituisce l'analisi aggiornata
        return updated

    # Porta un job PROCESSING nello stato terminale FAILED e memorizza il messaggio di errore
    def mark_failed(self, analysis_id: str, error_message: str) -> Analysis:
        """Mark one job as failed."""

        # Recupera obbligatoriamente l'analisi indicata
        analysis = self._require_analysis(analysis_id)

        # Il metodo permette il fallimento solamente partendo dallo stato PROCESSING
        if analysis.status != AnalysisStatus.PROCESSING:
            raise RepositoryError(f"Analysis '{analysis_id}' cannot fail from status '{analysis.status}'.")

        # Timestamp utilizzato per registrare l'ultima modifica
        now = datetime.now(timezone.utc)

        # Crea una copia aggiornata marcando il job come FAILED e cancellando alcuni risultati parziali
        updated = analysis.model_copy(
            update={
                "status": AnalysisStatus.FAILED,
                "mime_type": None,
                "sha256": None,
                "entropy": None,
                "extension_matches_mime": None,
                "indicators": [],
                "error_message": error_message,
                "updated_at": now,
            }
        )

        # Memorizza la nuova versione dell'analisi
        self._items[analysis_id] = updated

        # Rimuove il riferimento al file perché il job è ormai in uno stato terminale
        self._storage_paths[analysis_id] = None

        # Restituisce l'analisi fallita
        return updated

    # Recupera i job rimasti troppo a lungo in PROCESSING rimettendoli in coda oppure marcandoli come falliti
    def recover_stale_processing_jobs(
        self,
        *,
        processing_timeout_seconds: int,
        max_attempts: int,
    ) -> tuple[int, int]:
        """Requeue or fail stale processing jobs."""

        # Timestamp UTC corrente usato come riferimento per verificare il timeout
        now = datetime.now(timezone.utc)

        # Calcola il limite temporale oltre il quale un job PROCESSING viene considerato stale
        threshold = now - timedelta(seconds=processing_timeout_seconds)

        # Conta quanti job vengono rimessi in coda
        requeued = 0

        # Conta quanti job vengono definitivamente marcati come falliti
        failed = 0

        # Crea una lista degli elementi per poter modificare il dizionario durante l'iterazione senza lavorare sulla sua vista dinamica
        for analysis_id, analysis in list(self._items.items()):

            # Recupera il timestamp di inizio elaborazione associato al job
            started_at = self._processing_started_at.get(analysis_id)

            # Ignora i job non PROCESSING, privi di timestamp di avvio o ancora entro il timeout consentito
            if analysis.status != AnalysisStatus.PROCESSING or started_at is None or started_at >= threshold:
                continue

            # Se il job ha già raggiunto il numero massimo di tentativi viene definitivamente marcato come FAILED
            if self._attempt_counts.get(analysis_id, 0) >= max_attempts:

                # Riutilizza mark_failed per applicare la transizione terminale e registrare il motivo del fallimento
                self.mark_failed(analysis_id, "Processing timed out and max attempts were exceeded.")

                # Incrementa il contatore dei job falliti durante il recovery
                failed += 1

            else:

                # Se sono ancora consentiti tentativi, crea una nuova copia del job riportandolo nello stato QUEUED
                self._items[analysis_id] = analysis.model_copy(
                    update={
                        "status": AnalysisStatus.QUEUED,
                        "updated_at": now,
                        "mime_type": None,
                        "sha256": None,
                        "entropy": None,
                        "extension_matches_mime": None,
                        "indicators": [],
                        "error_message": None,
                    }
                )

                # Il job non è più considerato in elaborazione
                self._processing_started_at[analysis_id] = None

                # Rimuove l'associazione con il precedente worker
                self._worker_ids[analysis_id] = None

                # Incrementa il numero di job rimessi in coda
                requeued += 1

        # Restituisce rispettivamente quanti job sono stati rimessi in coda e quanti sono stati falliti
        return requeued, failed

    # Restituisce tutte le analisi ordinate dalla più recente alla più vecchia con eventuale filtro di ownership
    def list_all(self, owner_sub: str | None = None) -> list[Analysis]:
        """Return analyses ordered from newest to oldest."""

        # Recupera inizialmente tutti i valori presenti nel dizionario delle analisi
        items = self._items.values()

        # Se viene fornito owner_sub mantiene solamente le analisi appartenenti a quel subject OIDC
        if owner_sub is not None:
            items = [analysis for analysis in items if analysis.owner_sub == owner_sub]

        # Ordina in modo decrescente prima per data di creazione e poi per ID
        return sorted(items, key=lambda analysis: (analysis.created_at, analysis.id), reverse=True)

    # Restituisce una pagina di analisi applicando filtri e paginazione direttamente sulle strutture Python in memoria
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
        """Return one filtered page of analyses with total count."""

        # Normalizza la stringa di ricerca rimuovendo spazi esterni e convertendola in minuscolo
        normalized_search = (search or "").strip().lower()

        # Costruisce in memoria la lista degli elementi che soddisfano contemporaneamente tutti i filtri richiesti
        filtered = [
            analysis
            for analysis in self.list_all(owner_sub=owner_sub)
            if (
                (not normalized_search)
                or normalized_search in analysis.file_name.lower()
                or normalized_search in analysis.id.lower()
            )

            # Confronta lo stato richiesto con quello di presentazione, così COMPLETED con verdict SCAN_ERROR può essere mostrato come FAILED
            and (
                status is None
                or get_presentation_analysis_status(analysis.status, analysis.verdict) == status
            )

            # Applica l'eventuale filtro sul livello di rischio
            and (risk_level is None or analysis.risk_level == risk_level)

            # Applica l'eventuale filtro esplicito sul proprietario
            and (owner_filter is None or analysis.owner_sub == owner_filter)
        ]

        # Calcola il numero totale di elementi rimasti dopo i filtri
        total = len(filtered)

        # Calcola l'indice del primo elemento appartenente alla pagina richiesta
        start = (page - 1) * page_size

        # Lo slicing Python estrae esclusivamente gli elementi appartenenti alla pagina corrente
        items = filtered[start : start + page_size]

        # Calcola il numero complessivo di pagine arrotondando verso l'alto
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        # Restituisce elementi e metadati della paginazione nel modello AnalysisPage
        return AnalysisPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    # Recupera una singola analisi tramite ID applicando opzionalmente anche il controllo sul proprietario
    def get_by_id(self, analysis_id: str, owner_sub: str | None = None) -> Analysis | None:
        """Return one analysis if present."""

        # Cerca direttamente l'ID nel dizionario locale
        analysis = self._items.get(analysis_id)

        # Se l'analisi non esiste restituisce None
        if analysis is None:
            return None

        # Se è richiesto un controllo di ownership ma il proprietario non coincide, l'analisi viene trattata come non visibile
        if owner_sub is not None and analysis.owner_sub != owner_sub:
            return None

        # Restituisce l'analisi trovata e autorizzata dal filtro di ownership
        return analysis

    # Elimina tutte le analisi e i relativi metadati conservati nella memoria del repository
    def clear(self) -> list[str]:
        """Remove all stored analyses and return tracked storage paths."""

        # Salva prima della cancellazione tutti i percorsi storage effettivamente valorizzati
        storage_paths = [path for path in self._storage_paths.values() if path]

        # Svuota il dizionario contenente le analisi
        self._items.clear()

        # Svuota la mappa dei percorsi storage
        self._storage_paths.clear()

        # Svuota i timestamp di inizio elaborazione
        self._processing_started_at.clear()

        # Svuota le associazioni con i worker
        self._worker_ids.clear()

        # Svuota i contatori dei tentativi
        self._attempt_counts.clear()

        # Aggiorna l'anno corrente ma non azzera direttamente il contatore `_sequence`
        self._year = datetime.now(timezone.utc).year

        # Restituisce i percorsi che erano associati ai job prima della pulizia
        return storage_paths

    # Genera localmente l'ID pubblico dell'analisi mantenendo un progressivo separato per anno
    def _next_public_id(self, year: int) -> str:
        """Genera un ID pubblico compatibile con il formato mostrato in UI."""

        # Quando cambia anno aggiorna `_year` e riparte dal progressivo zero
        if year != self._year:
            self._year = year
            self._sequence = 0

        # Incrementa il contatore locale prima di costruire il nuovo identificatore
        self._sequence += 1

        # `:04d` rappresenta il progressivo su almeno quattro cifre aggiungendo eventuali zeri iniziali
        return f"ANL-{self._year}-{self._sequence:04d}"

    # Recupera un'analisi che deve obbligatoriamente esistere e centralizza la gestione dell'ID non trovato
    def _require_analysis(self, analysis_id: str) -> Analysis:

        # Cerca l'analisi nel dizionario principale
        analysis = self._items.get(analysis_id)

        # Se l'ID non esiste solleva l'eccezione comune del layer repository
        if analysis is None:
            raise RepositoryError(f"Analysis '{analysis_id}' was not found.")

        # Restituisce l'analisi trovata
        return analysis


# Istanza globale condivisa all'interno dello stesso processo Python per mantenere in memoria lo stesso stato tra le chiamate che la utilizzano
repository = InMemoryAnalysisRepository()


# Dependency FastAPI che restituisce sempre l'istanza globale del repository in memoria
def get_memory_repository() -> InMemoryAnalysisRepository:
    """Dependency FastAPI per il repository in memoria."""

    # Restituisce la stessa istanza senza crearne una nuova a ogni chiamata
    return repository
