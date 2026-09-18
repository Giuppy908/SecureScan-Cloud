"""Apertura delle connessioni al database applicativo.

Questo file non corrisponde a una pagina del sito. Serve a creare l'engine
SQLAlchemy e le sessioni usate da repository e servizi per leggere e scrivere
su PostgreSQL senza spargere dettagli tecnici in tutto il codice.
"""

# Permette la gestione posticipata delle annotazioni di tipo
from __future__ import annotations

# `Generator` viene usato per annotare `get_db_session()`, che fornisce una sessione tramite `yield` e poi ne esegue la chiusura
from collections.abc import Generator

# `create_engine` crea l'engine SQLAlchemy a partire dall'URL del database
# `text` permette di rappresentare una semplice istruzione SQL testuale, usata qui per `SELECT 1`
# SQLAlchemy è una libreria Python per interagire con database relazionali (nel progetto fa da livello intermedio tra codice python e PostgreSQL)
from sqlalchemy import create_engine, text

# `Engine` rappresenta il componente SQLAlchemy che gestisce l'accesso al database e, quando previsto dal backend, il pool delle connessioni
from sqlalchemy.engine import Engine

# Eccezione base usata per intercettare errori generati da SQLAlchemy durante il probe del database
from sqlalchemy.exc import SQLAlchemyError

# `Session` rappresenta una sessione di lavoro SQLAlchemy
# `sessionmaker` è una factory utilizzata per creare nuove sessioni configurate nello stesso modo
from sqlalchemy.orm import Session, sessionmaker

# Configurazione centralizzata della Analysis API
# In questo file viene utilizzato `settings.database_url` per stabilire a quale database collegarsi
from app.core.config import settings


# Gestisce in un unico punto l'engine SQLAlchemy e la factory usata per creare le sessioni
# Una factory, generalmente, è un componente il cui compito è creare altri oggetti già configurati in modo corretto
class DatabaseSessionManager:
    """Gestisce engine e session factory condivisi dalla replica API."""

    # Il costruttore riceve l'URL del database e prepara immediatamente engine e session factory chiamando `configure()`
    def __init__(self, database_url: str) -> None:

        # Memorizza l'URL del database attualmente configurato
        self._database_url = database_url

        # L'engine viene inizialmente impostato a `None` e viene creato subito dopo tramite `configure()`
        self._engine: Engine | None = None

        # La session factory viene anch'essa inizialmente impostata a `None` e verrà creata insieme all'engine
        self._session_factory: sessionmaker[Session] | None = None

        # Esegue la configurazione iniziale usando l'URL ricevuto
        self.configure(database_url)

    # Crea o ricrea l'engine e la relativa factory di sessioni
    def configure(self, database_url: str) -> None:
        """Riconfigura engine e session factory per runtime o test.

        SQLite richiede `check_same_thread=False` per funzionare correttamente
        nei test FastAPI; gli altri backend usano la configurazione standard.
        """

        # Se esiste già un engine, prima della riconfigurazione ne vengono rilasciate le risorse gestite tramite `dispose()`
        if self._engine is not None:
            self._engine.dispose()

        # Aggiorna l'URL del database memorizzato dal manager
        self._database_url = database_url

        # SQLite riceve l'opzione `check_same_thread=False`
        # Gli altri database, come PostgreSQL nel deployment Compose, non ricevono argomenti di connessione aggiuntivi in questo punto
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}

        # Crea l'engine SQLAlchemy associato al database indicato dall'URL
        # L'engine è il componente condiviso che SQLAlchemy usa per gestire la comunicazione con il database e l'eventuale pool di connessioni
        #
        # `pool_pre_ping=True` fa controllare a SQLAlchemy che una connessione recuperata dal pool sia ancora utilizzabile prima di impiegarla
        self._engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)

        # Crea una factory di sessioni collegata all'engine appena creato
        # Ogni chiamata alla factory produrrà una nuova `Session`
        self._session_factory = sessionmaker(

            # Associa le sessioni create da questa factory all'engine configurato
            bind=self._engine,

            # Le operazioni non vengono confermate automaticamente: eventuali `commit()` devono essere eseguiti esplicitamente dal codice chiamante
            autocommit=False,

            # Disabilita il flush automatico prima di determinate operazioni/query; il flush potrà comunque essere eseguito esplicitamente o durante un commit
            # Il flush sincronizza con il database le modifiche pendenti nella sessione, ad esempio INSERT, UPDATE o DELETE
            autoflush=False,

            # Dopo un commit gli oggetti già caricati nella sessione non vengono automaticamente marcati come scaduti
            expire_on_commit=False,

            # Specifica la classe di sessione che la factory deve creare
            class_=Session,
        )

    # `@property` permette di usare `session_manager.engine` come un normale attributo, pur eseguendo il controllo definito nel metodo
    @property
    def engine(self) -> Engine:
        """Return the configured engine."""

        # Protezione difensiva: se per qualche motivo l'engine non fosse configurato, viene sollevato un errore invece di restituire `None`
        if self._engine is None:
            raise RuntimeError("Database engine is not configured.")

        # Restituisce l'engine SQLAlchemy attualmente configurato
        return self._engine

    # Espone in modo controllato la factory usata per creare nuove sessioni
    @property
    def session_factory(self) -> sessionmaker[Session]:
        """Return the configured session factory."""

        # Come per l'engine, impedisce di usare una factory non configurata
        if self._session_factory is None:
            raise RuntimeError("Database session factory is not configured.")

        # Restituisce la factory attualmente collegata all'engine
        return self._session_factory

    # Verifica in modo minimale se il database configurato riesce a rispondere
    def ping(self) -> bool:
        """Esegue un probe minimale verso il database configurato."""

        try:

            # Crea una nuova sessione tramite la factory
            # Il `with` usa la sessione come context manager e ne garantisce la chiusura quando si esce dal blocco
            with self.session_factory() as session:

                # Esegue una query minimale che non legge dati applicativi: se `SELECT 1` viene eseguita correttamente, il database sta rispondendo
                session.execute(text("SELECT 1"))

            # Nessuna eccezione SQLAlchemy è stata sollevata
            return True

        # Se SQLAlchemy segnala un errore durante l'apertura della sessione o l'esecuzione della query, il database viene considerato non raggiungibile
        except SQLAlchemyError:
            return False


# Crea il session manager condiviso dal processo della Analysis API
# La configurazione iniziale usa `database_url` letto dalle impostazioni dell'applicazione
session_manager = DatabaseSessionManager(settings.database_url)


# Permette di riconfigurare il database utilizzato dal session manager condiviso
# Nel repository questa funzione viene utilizzata anche dai test con database SQLite temporanei
def configure_database(database_url: str) -> None:
    """Riconfigura il session manager condiviso."""

    # Delega tutta la logica di riconfigurazione al manager
    session_manager.configure(database_url)


# Funzione di supporto che espone l'engine SQLAlchemy attualmente configurato
def get_engine() -> Engine:
    """Restituisce l'engine SQLAlchemy condiviso."""

    return session_manager.engine


# Dependency FastAPI che fornisce una nuova sessione database al codice che la richiede
def get_db_session() -> Generator[Session, None, None]:
    """Dependency FastAPI che fornisce una sessione con chiusura garantita."""

    # Crea una nuova Session a partire dalla factory condivisa
    # L'engine è condiviso, mentre questa sessione rappresenta un contesto di lavoro separato
    session = session_manager.session_factory()

    try:

        # `yield` consegna la sessione al codice chiamante
        # In FastAPI la parte successiva verrà eseguita quando la dependency termina
        yield session

    finally:

        # La sessione viene sempre chiusa, anche se durante l'elaborazione della richiesta si verifica un'eccezione
        # Questa funzione non esegue automaticamente né `commit()` né `rollback()`
        session.close()


# Funzione utilizzabile dai controlli di health/status per verificare se il database risponde al probe (nel metodo ping())
def is_database_reachable() -> bool:
    """Ritorna True quando il database risponde a una query elementare."""

    return session_manager.ping()
