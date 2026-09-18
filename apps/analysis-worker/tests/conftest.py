"""Fixture condivise per i test del worker.

Le fixture preparano un database SQLite temporaneo che permette di testare
polling, repository e pipeline senza dover avviare l'intero stack Docker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.base import Base
from app.db.session import configure_database, get_engine, session_manager


@pytest.fixture()
def sqlite_database_url(tmp_path: Path) -> str:
    """Crea un database temporaneo isolato per il singolo test."""
    return f"sqlite+pysqlite:///{tmp_path / 'analysis-worker-test.db'}"


@pytest.fixture()
def db_session(sqlite_database_url: str):
    """Prepara schema e sessione DB temporanea per ogni scenario di test."""
    configure_database(sqlite_database_url)
    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())
    session = session_manager.session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=get_engine())
