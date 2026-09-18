"""Gestione centralizzata dell'accesso a PostgreSQL per il worker.

Questo file crea l'engine SQLAlchemy e la factory delle sessioni usate dal
worker. In questo modo repository e servizi non devono conoscere i dettagli
tecnici della connessione al database.
"""

# Permette di gestire le annotazioni di tipo in modo posticipato
from __future__ import annotations

# create_engine costruisce l'Engine SQLAlchemy, mentre text permette di eseguire query SQL testuali come SELECT 1
from sqlalchemy import create_engine, text

# Engine rappresenta l'oggetto SQLAlchemy che gestisce configurazione DB e pool delle connessioni
from sqlalchemy.engine import Engine

# SQLAlchemyError è la classe base delle eccezioni SQLAlchemy gestite durante il probe del database
from sqlalchemy.exc import SQLAlchemyError

# Session rappresenta una sessione ORM, mentre sessionmaker è la factory usata per crearne di nuove
from sqlalchemy.orm import Session, sessionmaker

# Importa la configurazione globale del worker, compreso l'URL del database
from app.core.config import settings


# Classe che centralizza la creazione dell'Engine e delle Session SQLAlchemy usate dal worker
class DatabaseSessionManager:
    """Gestisce engine e sessioni SQLAlchemy del worker."""

    # Inizializza il manager senza Engine o factory e applica subito la configurazione ricevuta
    def __init__(self, database_url: str) -> None:

        # Conterrà l'Engine SQLAlchemy condiviso dal worker
        self._engine: Engine | None = None

        # Conterrà la factory usata per creare nuove Session indipendenti
        self._session_factory: sessionmaker[Session] | None = None

        # Configura Engine e session factory usando l'URL fornito
        self.configure(database_url)

    # Configura o riconfigura l'accesso al database
    def configure(self, database_url: str) -> None:
        """Riconfigura la connessione, utile soprattutto nei test isolati."""

        # Se esiste già un Engine, ne elimina il pool delle connessioni prima di sostituirlo
        if self._engine is not None:
            self._engine.dispose()

        # SQLite richiede questa opzione nei test per permettere l'uso della connessione anche da thread differenti
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}

        # Crea l'Engine e abilita il controllo preventivo delle connessioni recuperate dal pool
        self._engine = create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)

        # Crea la factory che produrrà una nuova Session SQLAlchemy per ogni operazione del worker
        self._session_factory = sessionmaker(

            # Collega tutte le Session create dalla factory all'Engine appena configurato
            bind=self._engine,

            # Impone la gestione esplicita del commit da parte dei repository
            autocommit=False,

            # Evita che SQLAlchemy esegua automaticamente il flush prima delle query
            autoflush=False,

            # Mantiene disponibili gli attributi degli oggetti ORM anche dopo un commit
            expire_on_commit=False,

            # Specifica che la factory deve produrre normali oggetti Session SQLAlchemy
            class_=Session,
        )

    # Espone in sola lettura l'Engine configurato
    @property
    def engine(self) -> Engine:

        # Impedisce l'utilizzo del manager se l'Engine non è stato configurato
        if self._engine is None:
            raise RuntimeError("Database engine is not configured.")

        # Restituisce l'Engine corrente mantenuto dal manager
        return self._engine

    # Espone in sola lettura la factory delle Session configurata
    @property
    def session_factory(self) -> sessionmaker[Session]:

        # Impedisce la creazione di Session se la factory non è stata configurata
        if self._session_factory is None:
            raise RuntimeError("Database session factory is not configured.")

        # Restituisce la factory condivisa che può creare nuove Session indipendenti
        return self._session_factory

    # Verifica rapidamente se il database accetta una query minima
    def ping(self) -> bool:
        """Esegue una query minima per capire se PostgreSQL è raggiungibile."""

        try:

            # Crea una Session temporanea e garantisce che venga chiusa al termine del blocco with
            with self.session_factory() as session:

                # Esegue una query minima che verifica la possibilità di comunicare con il database
                session.execute(text("SELECT 1"))

            # Se la query termina senza errori SQLAlchemy, il database viene considerato raggiungibile
            return True

        # Intercetta gli errori SQLAlchemy prodotti durante apertura della Session o esecuzione della query
        except SQLAlchemyError:

            # Il probe restituisce semplicemente False senza propagare l'eccezione
            return False


# Crea il manager globale usando l'URL del database definito nella configurazione del worker
session_manager = DatabaseSessionManager(settings.database_url)


# Permette di sostituire l'URL del database e ricreare Engine e session factory, principalmente nei test
def configure_database(database_url: str) -> None:
    """Aggiorna il database usato dal worker, tipicamente nei test."""

    # Delega la riconfigurazione al manager globale
    session_manager.configure(database_url)


# Espone l'Engine corrente mantenuto dal manager globale
def get_engine() -> Engine:
    """Espone l'engine SQLAlchemy corrente."""

    # Restituisce lo stesso Engine utilizzato dalla session factory
    return session_manager.engine


# Fornisce un controllo rapido della raggiungibilità del database
def is_database_reachable() -> bool:
    """Restituisce un controllo rapido di reachability del database."""

    # Delega il controllo al metodo ping del manager globale
    return session_manager.ping()
