"""Modelli Pydantic usati dalle funzionalità di analisi.

Questi schemi descrivono i dati che il frontend vede in Nuova analisi,
Cronologia e Dettaglio analisi. Non descrivono come i dati vengono salvati
in PostgreSQL: quello è il compito dei modelli ORM in `app.db.models`.
"""

# dataclass viene usato per rappresentare internamente il job assegnato al worker
from dataclasses import dataclass

# datetime rappresenta i timestamp associati alle analisi e alla loro elaborazione
from datetime import datetime

# Enum permette di definire insiemi chiusi di valori ammessi per stati, rischio e risultati degli scanner
from enum import Enum

# BaseModel definisce i modelli Pydantic, mentre Field permette di specificare validazioni e valori di default
from pydantic import BaseModel, Field


# Definisce i possibili stati tecnici attraversati da un job di analisi
class AnalysisStatus(str, Enum):
    """Stato generale con cui la GUI presenta l'avanzamento di una scansione."""

    # Il job è stato creato dall'API ed è in attesa di essere acquisito dal worker
    QUEUED = "queued"

    # Il job è stato acquisito da un worker ed è in corso di elaborazione
    PROCESSING = "processing"

    # Il processamento del job è terminato e il risultato è stato persistito
    COMPLETED = "completed"

    # Il job non è stato completato correttamente
    FAILED = "failed"


# Definisce il livello sintetico di rischio associato all'analisi
class RiskLevel(str, Enum):
    """Livello di rischio sintetico mostrato dalla UI e usato nei filtri."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Definisce il verdetto finale prodotto dalla pipeline antimalware
class AnalysisVerdict(str, Enum):
    """Verdetto finale della pipeline antimalware eseguita dal worker."""

    # Nessuna evidenza malevola è stata rilevata
    CLEAN = "clean"

    # Sono presenti elementi che richiedono attenzione ma non determinano un verdetto malicious
    SUSPICIOUS = "suspicious"

    # La pipeline ha rilevato evidenze considerate malevole
    MALICIOUS = "malicious"

    # La pipeline non è riuscita a produrre un risultato affidabile a causa di un errore di scansione
    SCAN_ERROR = "scan_error"


# Converte lo stato tecnico persistito nello stato che deve essere presentato dalla GUI
def get_presentation_analysis_status(
    status: AnalysisStatus,
    verdict: "AnalysisVerdict | None",
) -> AnalysisStatus:
    """Restituisce lo stato visibile nella GUI per una singola analisi.

    Il job tecnico può risultare `completed` anche quando la pipeline ha
    prodotto il verdetto `scan_error`: in quel caso il lavoro asincrono è
    terminato, ma il risultato mostrato all'utente deve essere "Fallita".
    """

    # Un job tecnicamente completato ma con errore di scansione viene mostrato all'utente come fallito
    if status == AnalysisStatus.COMPLETED and verdict == AnalysisVerdict.SCAN_ERROR:
        return AnalysisStatus.FAILED

    # Negli altri casi lo stato tecnico coincide con quello presentato
    return status


# Definisce i possibili risultati restituiti dal passaggio ClamAV
class ClamAvScanStatus(str, Enum):
    """Esito del passaggio ClamAV mostrato nel Dettaglio analisi."""

    CLEAN = "clean"
    FOUND = "found"
    ERROR = "error"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


# Definisce i possibili risultati restituiti dal passaggio YARA
class YaraScanStatus(str, Enum):
    """Esito del passaggio YARA mostrato nel Dettaglio analisi."""

    CLEAN = "clean"
    MATCHED = "matched"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


# Rappresenta una singola regola YARA che ha prodotto una corrispondenza
class YaraMatch(BaseModel):
    """Una singola regola YARA trovata, con i metadati mostrati in UI."""

    # Nome della regola YARA che ha effettuato il match
    rule_name: str

    # Namespace associato alla regola, se disponibile
    namespace: str | None = None

    # Metadati opzionali definiti all'interno della regola YARA
    description: str | None = None
    severity: str | None = None
    category: str | None = None
    author: str | None = None
    reference: str | None = None

    # Elenco dei tag associati alla regola, inizialmente vuoto per ogni nuova istanza
    tags: list[str] = Field(default_factory=list)


# Contiene i campi comuni condivisi dai principali modelli di risposta delle analisi
class AnalysisBase(BaseModel):
    """Campi comuni riusati nelle risposte API relative alle analisi."""

    # Nome originale del file caricato
    file_name: str

    # Stato tecnico corrente del job
    status: AnalysisStatus

    # Livello sintetico di rischio
    risk_level: RiskLevel

    # Identificatore stabile Keycloak usato per applicare l'ownership
    owner_sub: str | None = None

    # Username del proprietario, utile come informazione descrittiva
    owner_username: str | None = None

    # Dimensione del file in byte, che non può essere negativa
    size_bytes: int = Field(ge=0)

    # Tipo MIME determinato durante l'analisi strutturale
    mime_type: str | None = None

    # Digest SHA-256 calcolato sul contenuto del file
    sha256: str | None = None

    # Entropia del file, se già calcolata, con valore non negativo
    entropy: float | None = Field(default=None, ge=0.0)

    # Indica se estensione del file e tipo MIME risultano coerenti
    extension_matches_mime: bool | None = None

    # Verdetto finale aggregato della pipeline antimalware
    verdict: AnalysisVerdict | None = None

    # Timestamp nel quale è stata completata la scansione
    scanned_at: datetime | None = None

    # Risultato specifico prodotto da ClamAV
    clamav_status: ClamAvScanStatus | None = None

    # Nome della firma ClamAV rilevata, quando presente
    clamav_signature_name: str | None = None

    # Eventuale messaggio di errore prodotto durante la scansione ClamAV
    clamav_error: str | None = None

    # Risultato specifico prodotto da YARA
    yara_status: YaraScanStatus | None = None

    # Elenco delle regole YARA che hanno prodotto un match
    yara_matches: list[YaraMatch] = Field(default_factory=list)

    # Eventuale messaggio di errore relativo alla scansione YARA
    yara_error: str | None = None

    # Indicatori prodotti dall'analisi strutturale del file
    indicators: list[str]

    # Eventuale errore generale associato all'elaborazione del job
    error_message: str | None = None


# Rappresenta i dati completi di una analisi prima dell'assegnazione dell'ID pubblico da parte della persistenza
class AnalysisCreateResult(AnalysisBase):
    """Dati completi di un'analisi prima che PostgreSQL assegni l'ID pubblico."""


# Contiene i dati minimi necessari per creare nel database un nuovo job in stato queued
class QueuedAnalysisCreate(BaseModel):
    """Dati minimi salvati quando Nuova analisi crea un job in coda."""

    # Nome del file caricato
    file_name: str

    # Dimensione del file in byte
    size_bytes: int = Field(ge=0)

    # Percorso dello storage condiviso che permetterà al worker di recuperare il file
    storage_path: str

    # Identificatore stabile del proprietario ottenuto dal token autenticato
    owner_sub: str | None = None

    # Username associato al proprietario
    owner_username: str | None = None


# Rappresenta il risultato completo prodotto dopo l'esecuzione della pipeline del worker
class AnalysisCompletionResult(BaseModel):
    """Risultato finale prodotto dal worker dopo scansione e aggregazione verdict."""

    # Un risultato completo viene normalmente persistito con stato completed
    status: AnalysisStatus = AnalysisStatus.COMPLETED

    # Livello di rischio finale assegnato all'analisi
    risk_level: RiskLevel

    # Risultati dell'analisi strutturale
    mime_type: str
    sha256: str
    entropy: float = Field(ge=0.0)
    extension_matches_mime: bool

    # Verdetto finale aggregato della pipeline
    verdict: AnalysisVerdict

    # Momento in cui la scansione è stata completata
    scanned_at: datetime

    # Risultati specifici di ClamAV
    clamav_status: ClamAvScanStatus
    clamav_signature_name: str | None = None
    clamav_error: str | None = None

    # Risultati specifici di YARA
    yara_status: YaraScanStatus
    yara_matches: list[YaraMatch] = Field(default_factory=list)
    yara_error: str | None = None

    # Indicatori strutturali e possibile errore generale
    indicators: list[str]
    error_message: str | None = None


# Modello completo restituito dall'API al frontend per rappresentare una singola analisi
class Analysis(AnalysisBase):
    """Record completo esposto a Cronologia e Dettaglio analisi.

    È la forma con cui il frontend riceve una singola analisi già arricchita
    con stato, rischio, ownership e risultati antimalware.
    """

    # Identificatore pubblico dell'analisi
    id: str

    # Timestamp di creazione del record
    created_at: datetime

    # Timestamp dell'ultimo aggiornamento del record
    updated_at: datetime


# Modello restituito alla pagina Cronologia per implementare la paginazione server-side
class AnalysisPage(BaseModel):
    """Risposta paginata della Cronologia con totale già filtrato lato server."""

    # Analisi appartenenti alla pagina corrente
    items: list[Analysis] = Field(default_factory=list)

    # Numero totale di record che rispettano ownership e filtri applicati
    total: int = Field(ge=0)

    # Numero della pagina corrente
    page: int = Field(ge=1)

    # Numero massimo di elementi richiesti per pagina
    page_size: int = Field(ge=1)

    # Numero totale di pagine disponibili
    total_pages: int = Field(ge=0)


# Dataclass interna contenente le informazioni operative necessarie per rappresentare un job
@dataclass(slots=True)
class AnalysisJob:
    """Rappresentazione interna del job consegnato al worker asincrono."""

    # Identificatore del job
    id: str

    # Informazioni sul file da processare
    file_name: str
    size_bytes: int

    # Percorso che consente di recuperare il file dallo storage condiviso
    storage_path: str

    # Numero di tentativi di elaborazione già effettuati
    attempt_count: int

    # Timestamp di creazione del job
    created_at: datetime

    # Momento in cui il job è stato acquisito per l'elaborazione, se già avvenuto
    processing_started_at: datetime | None

    # Identificativo del worker che ha acquisito il job, se presente
    worker_id: str | None
