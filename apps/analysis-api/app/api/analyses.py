"""Endpoint REST delle analisi mostrati nelle pagine centrali del sito.

Questo file serve direttamente tre aree della GUI:
- Nuova analisi, che carica un file e crea un nuovo job;
- Cronologia, che richiede elenco filtrato e paginato delle analisi;
- Dettaglio analisi, che carica un singolo record completo.

Qui viene applicato il controllo server-side più importante del progetto:
un analyst può vedere solo le proprie analisi, mentre un admin può vedere
tutto il dataset. Il router non interroga mai il database in modo diretto:
delega repository e storage dedicati.
"""

# Importa il modulo standard usato per registrare errori applicativi, ad esempio durante il salvataggio degli upload
import logging

# Importa i componenti FastAPI necessari per definire router, dependency injection, upload, query parameter, risposte ed errori HTTP
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status

# Importa la funzione che registra gli eventi di sicurezza significativi prodotti dagli endpoint
from app.auth.audit import log_security_event

# AuthenticatedUser rappresenta l'utente autenticato, mentre require_analyst e require_admin applicano il controllo dei ruoli
from app.auth.security import AuthenticatedUser, require_admin, require_analyst

# Importa i modelli Pydantic restituiti dall'API e gli enum utilizzati per filtrare stato e livello di rischio
from app.models.analysis import Analysis, AnalysisPage, AnalysisStatus, RiskLevel

# AnalysisRepository definisce il contratto del repository, mentre RepositoryError rappresenta gli errori del livello di persistenza
from app.repositories.base import AnalysisRepository, RepositoryError

# Importa la dependency che fornisce l'implementazione SQLAlchemy del repository
from app.repositories.sqlalchemy_repository import get_repository

# Importa il servizio che salva gli upload e le eccezioni specifiche che possono verificarsi durante questa operazione
from app.services.upload_storage import (
    UploadTooLargeError,
    UploadStorageError,
    UploadStorageService,
    get_upload_storage_service,
)

# Crea il router FastAPI dedicato alle analisi e applica il prefisso /analyses a tutti gli endpoint definiti nel file
router = APIRouter(prefix="/analyses", tags=["analyses"])

# Crea il logger associato a questo modulo
logger = logging.getLogger(__name__)


# Espone l'endpoint POST che accetta un nuovo file e restituisce immediatamente il job creato con stato HTTP 202
@router.post("", response_model=Analysis, status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    # Request contiene le informazioni della richiesta HTTP ed è utilizzata successivamente per l'audit di sicurezza
    request: Request,
    # File rende obbligatorio l'upload multipart e UploadFile permette di gestire il file ricevuto senza trattarlo come semplice stringa o JSON
    file: UploadFile = File(..., description="File to analyze"),
    # La dependency richiede un utente con ruolo analyst oppure admin e restituisce la sua identità autenticata
    user: AuthenticatedUser = Depends(require_analyst),
    # FastAPI recupera tramite dependency injection il repository utilizzato per accedere ai record delle analisi
    repository: AnalysisRepository = Depends(get_repository),
    # FastAPI recupera il servizio dedicato allo storage dei file caricati
    storage: UploadStorageService = Depends(get_upload_storage_service),
) -> Analysis:
    """Gestisce l'upload proveniente da Nuova analisi.

    L'API non esegue qui la scansione completa: salva il file nello storage
    condiviso, crea un job iniziale in stato `queued` e risponde subito.
    Il worker completerà poi la pipeline ClamAV/YARA e aggiornerà il record
    che comparirà in Cronologia e nel Dettaglio analisi.
    """

    # Prima di creare il record nel database, l'API prova a salvare fisicamente il file nello storage condiviso
    try:
        # save_upload legge il file ricevuto e restituisce le informazioni necessarie per creare successivamente il job
        queued_analysis = await storage.save_upload(file)

    # Un file che supera il limite configurato viene rifiutato con HTTP 413
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    # Un valore non valido prodotto durante la gestione dell'upload viene tradotto in HTTP 400
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Gli errori dello storage rappresentano invece un problema interno del server
    except UploadStorageError as exc:
        # Registra nel log l'errore insieme al nome del file coinvolto
        logger.exception(
            "Failed to store uploaded file for analysis.",
            extra={"file_name": file.filename or "uploaded-file"},
        )

        # Il client riceve HTTP 500 senza esporre dettagli interni dello storage
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file.",
        ) from exc

    # Dopo avere salvato il file, l'API prova a creare nel database il job persistente che verrà acquisito dal worker
    try:
        # Il repository inserisce una nuova analisi inizialmente accodata per l'elaborazione asincrona
        analysis = repository.create_queued_analysis(
            # model_copy crea una copia dei dati prodotti dallo storage aggiungendo le informazioni di ownership ricavate dal token
            queued_analysis.model_copy(
                update={
                    # L'ownership viene sempre fissata lato server usando il
                    # subject del token verificato: il client non può scegliere
                    # arbitrariamente il proprietario dell'analisi.
                    "owner_sub": user.subject,
                    "owner_username": user.username,
                }
            )
        )

    # Se la persistenza nel database fallisce, il file già salvato non deve possibilmente rimanere orfano
    except RepositoryError as exc:
        # Tenta quindi una compensazione eliminando il file precedentemente scritto nello storage
        try:
            storage.delete_path(queued_analysis.storage_path)

        # Se anche la pulizia dello storage fallisce, l'errore viene ignorato perché la risposta principale rimane il fallimento DB
        except UploadStorageError:
            pass

        # Comunica al client che non è stato possibile persistere la nuova analisi
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist analysis.",
        ) from exc

    # Registra nell'audit di sicurezza la creazione avvenuta con successo
    log_security_event(
        request,
        event="analysis_created",
        status_code=status.HTTP_202_ACCEPTED,
        subject=user.subject,
        username=user.username,
        roles=user.roles,
        analysis_id=analysis.id,
    )

    # Restituisce il record appena creato senza attendere l'esecuzione della scansione da parte del worker
    return analysis


# Espone l'endpoint GET utilizzato dalla pagina Cronologia per ottenere una pagina di analisi
@router.get("", response_model=AnalysisPage)
def list_analyses(
    # page indica il numero della pagina richiesta e deve essere almeno 1
    page: int = Query(default=1, ge=1),
    # page_size indica quanti risultati devono essere restituiti in una pagina
    page_size: int = Query(default=10, ge=1),
    # search permette una ricerca testuale opzionale
    search: str | None = Query(default=None),
    # Il parametro HTTP status viene convertito nell'enum AnalysisStatus
    analysis_status: AnalysisStatus | None = Query(default=None, alias="status"),
    # Il parametro HTTP risk viene convertito nell'enum RiskLevel
    risk_level: RiskLevel | None = Query(default=None, alias="risk"),
    # owner è un filtro opzionale utilizzabile realmente soltanto dagli amministratori
    owner: str | None = Query(default=None),
    # Anche la consultazione della cronologia richiede almeno il ruolo analyst
    user: AuthenticatedUser = Depends(require_analyst),
    # Il repository eseguirà filtraggio, conteggio e paginazione nel livello di persistenza
    repository: AnalysisRepository = Depends(get_repository),
) -> AnalysisPage:
    """Restituisce una pagina della Cronologia già filtrata lato server.

    L'ordine delle operazioni è importante:
    1. si decide quali record l'utente è autorizzato a vedere;
    2. si applicano ricerca e filtri scelti nella pagina Cronologia;
    3. si calcola il totale dei risultati filtrati;
    4. solo alla fine si applicano page e page_size.

    In questo modo il totale mostrato nella GUI rappresenta davvero tutti i
    risultati compatibili con i filtri correnti e non solo la pagina caricata.
    """

    # Tutta la lettura dal database viene delegata al repository e gli eventuali errori vengono convertiti in errori HTTP
    try:
        # `owner_sub` implementa il perimetro di visibilità obbligatorio.
        # `owner_filter` è invece un filtro opzionale disponibile soltanto
        # agli amministratori sopra il dataset già autorizzato.
        # Un admin usa None perché deve poter vedere tutte le analisi, mentre un analyst viene limitato al proprio subject
        owner_sub = None if "admin" in user.roles else user.subject

        # Solo un admin può utilizzare il parametro owner per filtrare ulteriormente il dataset visibile
        owner_filter = owner if "admin" in user.roles else None

        # Delega al repository ownership, filtri, conteggio totale e paginazione
        return repository.list_page(
            owner_sub=owner_sub,
            search=search,
            status=analysis_status,
            risk_level=risk_level,
            owner_filter=owner_filter,
            page=page,
            page_size=page_size,
        )

    # Un problema durante l'accesso ai dati viene presentato al client come errore interno del server
    except RepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list analyses.",
        ) from exc


# Espone l'endpoint GET utilizzato per recuperare una singola analisi tramite il suo identificativo
@router.get("/{analysis_id}", response_model=Analysis)
def get_analysis(
    # analysis_id proviene direttamente dal path della richiesta HTTP
    analysis_id: str,
    # L'utente deve essere autenticato e possedere almeno il ruolo analyst
    user: AuthenticatedUser = Depends(require_analyst),
    # Il repository recupera il record senza far accedere direttamente il router a SQLAlchemy
    repository: AnalysisRepository = Depends(get_repository),
) -> Analysis:
    """Carica il record mostrato nella pagina Dettaglio analisi.

    Anche qui l'ownership è controllata server-side: conoscere l'ID di un'altra
    analisi non basta per leggerla se il token appartiene a un analyst diverso.
    """

    # Prova a recuperare l'analisi applicando prima il corretto perimetro di ownership
    try:
        # Un admin non riceve alcun vincolo owner_sub, mentre un analyst viene limitato al proprio subject
        owner_sub = None if "admin" in user.roles else user.subject

        # Il repository cerca l'ID eventualmente insieme al vincolo di ownership
        analysis = repository.get_by_id(analysis_id, owner_sub=owner_sub)

    # Eventuali problemi di accesso al database vengono tradotti in HTTP 500
    except RepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve analysis.",
        ) from exc

    # Se non esiste un record visibile con quell'ID viene restituito HTTP 404
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis '{analysis_id}' not found.",
        )

    # Restituisce l'analisi autorizzata al client
    return analysis


# Espone un endpoint amministrativo che cancella l'intero dataset delle analisi
@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_analyses(
    # Request viene utilizzata per registrare successivamente l'evento nell'audit
    request: Request,
    # require_admin impedisce agli analyst di utilizzare l'operazione di cancellazione globale
    user: AuthenticatedUser = Depends(require_admin),
    # Il repository si occupa della cancellazione dei record persistiti
    repository: AnalysisRepository = Depends(get_repository),
    # Lo storage viene utilizzato per eliminare anche i file fisici ancora associati ai record
    storage: UploadStorageService = Depends(get_upload_storage_service),
) -> Response:
    """Elimina tutte le analisi e i file temporanei associati.

    Questo endpoint non corrisponde a una normale pagina utente: serve ai
    workflow di manutenzione e demo locale. È riservato agli amministratori
    perché agisce sull'intero dataset condiviso visibile in Cronologia.
    """

    # Prima vengono cancellati i record dal database e recuperati i relativi percorsi dei file
    try:
        storage_paths = repository.clear()

    # Se la cancellazione dal repository fallisce, l'operazione termina con HTTP 500
    except RepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete analyses.",
        ) from exc

    # Dopo la cancellazione DB vengono rimossi anche i file ancora presenti nello storage
    try:
        storage.delete_paths(storage_paths)

    # Se questa seconda fase fallisce, i record DB sono già stati eliminati e possono rimanere file orfani
    except UploadStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete stored files.",
        ) from exc

    # Registra nell'audit la cancellazione globale completata con successo
    log_security_event(
        request,
        event="analyses_deleted",
        status_code=status.HTTP_204_NO_CONTENT,
        subject=user.subject,
        username=user.username,
        roles=user.roles,
        deleted_count=len(storage_paths),
    )

    # HTTP 204 indica che l'operazione è riuscita e non deve essere restituito un body
    return Response(status_code=status.HTTP_204_NO_CONTENT)
