"""Fixture condivise per la suite test della Analysis API.

Questo file prepara un piccolo ambiente controllato che assomiglia al backend
reale senza richiedere l'intero stack Docker. In questo modo i test possono
verificare API, repository e servizi con dati isolati e ripetibili.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import configure_database, get_engine, session_manager
from app.auth.security import get_jwt_verifier
from app.main import create_app


@pytest.fixture()
def sqlite_database_url(tmp_path: Path) -> str:
    """Fornisce un database SQLite temporaneo distinto per ogni test."""
    return f"sqlite+pysqlite:///{tmp_path / 'analysis-api-test.db'}"


@pytest.fixture()
def client(sqlite_database_url: str) -> TestClient:
    """Restituisce un client FastAPI con DB e storage effimeri."""
    configure_database(sqlite_database_url)
    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())
    # Upload e avatar puntano a directory temporanee dedicate per evitare che
    # i test tocchino lo storage condiviso della demo locale.
    upload_dir = Path(sqlite_database_url.removeprefix("sqlite+pysqlite:///")).parent / "uploads"
    avatar_dir = Path(sqlite_database_url.removeprefix("sqlite+pysqlite:///")).parent / "avatars"
    settings.upload_dir = str(upload_dir)
    settings.avatar_dir = str(avatar_dir)
    previous_max_upload_size_mb = settings.max_upload_size_mb
    previous_max_avatar_size_mb = settings.max_avatar_size_mb
    previous_worker_heartbeat_timeout_seconds = settings.worker_heartbeat_timeout_seconds
    previous_api_heartbeat_enabled = settings.api_heartbeat_enabled
    previous_api_heartbeat_timeout_seconds = settings.api_heartbeat_timeout_seconds
    previous_configured_api_replicas = settings.configured_api_replicas
    previous_instance_id = settings.instance_id
    settings.max_upload_size_mb = 250
    settings.max_avatar_size_mb = 5
    settings.worker_heartbeat_timeout_seconds = 15
    settings.api_heartbeat_enabled = False
    settings.api_heartbeat_timeout_seconds = 15
    settings.configured_api_replicas = 1
    settings.instance_id = "test-analysis-api"
    previous_auth_enabled = settings.auth_enabled
    settings.auth_enabled = False
    get_jwt_verifier.cache_clear()

    with TestClient(create_app()) as test_client:
        yield test_client

    settings.max_upload_size_mb = previous_max_upload_size_mb
    settings.max_avatar_size_mb = previous_max_avatar_size_mb
    settings.worker_heartbeat_timeout_seconds = previous_worker_heartbeat_timeout_seconds
    settings.api_heartbeat_enabled = previous_api_heartbeat_enabled
    settings.api_heartbeat_timeout_seconds = previous_api_heartbeat_timeout_seconds
    settings.configured_api_replicas = previous_configured_api_replicas
    settings.instance_id = previous_instance_id
    settings.auth_enabled = previous_auth_enabled
    get_jwt_verifier.cache_clear()
    Base.metadata.drop_all(bind=get_engine())


@pytest.fixture()
def db_session(sqlite_database_url: str) -> Session:
    """Espone una sessione SQLAlchemy isolata per test repository e servizi."""
    configure_database(sqlite_database_url)
    Base.metadata.drop_all(bind=get_engine())
    Base.metadata.create_all(bind=get_engine())

    session = session_manager.session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=get_engine())
