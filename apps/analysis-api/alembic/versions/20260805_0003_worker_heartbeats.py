"""Migration che aggiunge il registro heartbeat del worker.

Questa tabella permette di capire se il worker sta davvero continuando a
lavorare. È importante perché il solo fatto che l'API risponda non basta:
una scansione può restare bloccata se il worker non è operativo.

Le informazioni create qui vengono usate indirettamente soprattutto nella
pagina Stato del sistema.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0003"
down_revision = "20260805_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crea la tabella `worker_heartbeats` e gli indici usati dal monitoraggio."""
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "stopped", name="workerheartbeatstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index("ix_worker_heartbeats_status", "worker_heartbeats", ["status"], unique=False)
    op.create_index(
        "ix_worker_heartbeats_last_heartbeat_at",
        "worker_heartbeats",
        ["last_heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    """Rimuove il registry heartbeat dei worker."""
    op.drop_index("ix_worker_heartbeats_last_heartbeat_at", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_status", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
