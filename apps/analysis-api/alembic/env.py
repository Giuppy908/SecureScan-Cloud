"""Configurazione dell'ambiente Alembic per la Analysis API.

Alembic è lo strumento che aggiorna la struttura del database nel tempo.
Questo file collega Alembic ai modelli SQLAlchemy dell'applicazione e decide
se eseguire le migration:
- in modalità offline, generando solo SQL;
- in modalità online, collegandosi davvero al database.

Non corrisponde a una pagina del sito, ma rende possibili tutte le funzionalità
che dipendono da tabelle e colonne coerenti con il codice corrente.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base
from app.db import models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Esegue le migration in modalità offline usando solo l'URL configurato."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Esegue le migration aprendo una connessione reale al database target."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
