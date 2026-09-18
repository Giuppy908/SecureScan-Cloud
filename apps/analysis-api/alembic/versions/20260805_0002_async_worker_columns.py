"""Migration che prepara il passaggio alla pipeline asincrona con worker.

Questa modifica aggiunge alla tabella `analyses` i campi necessari quando il
file non viene più analizzato dentro la richiesta HTTP, ma viene consegnato a
un worker separato.

In pratica abilita il flusso:
Nuova analisi -> job `queued` -> worker -> aggiornamento record finale.

Ne beneficiano soprattutto Nuova analisi, Cronologia e Dettaglio analisi.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0002"
down_revision = "20260805_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Aggiunge colonne worker/storage e rende nullable i risultati posticipati."""
    op.add_column("analyses", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("analyses", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("analyses", sa.Column("worker_id", sa.String(length=128), nullable=True))
    op.add_column("analyses", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("analyses", sa.Column("storage_path", sa.String(length=1024), nullable=True))

    op.alter_column("analyses", "mime_type", existing_type=sa.String(length=255), nullable=True)
    op.alter_column("analyses", "sha256", existing_type=sa.String(length=64), nullable=True)
    op.alter_column("analyses", "entropy", existing_type=sa.Float(), nullable=True)
    op.alter_column("analyses", "extension_matches_mime", existing_type=sa.Boolean(), nullable=True)
    op.alter_column("analyses", "attempt_count", server_default=None)


def downgrade() -> None:
    """Ripristina lo schema precedente alla coda worker asincrona."""
    op.alter_column("analyses", "extension_matches_mime", existing_type=sa.Boolean(), nullable=False)
    op.alter_column("analyses", "entropy", existing_type=sa.Float(), nullable=False)
    op.alter_column("analyses", "sha256", existing_type=sa.String(length=64), nullable=False)
    op.alter_column("analyses", "mime_type", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("analyses", "storage_path")
    op.drop_column("analyses", "attempt_count")
    op.drop_column("analyses", "worker_id")
    op.drop_column("analyses", "completed_at")
    op.drop_column("analyses", "processing_started_at")
