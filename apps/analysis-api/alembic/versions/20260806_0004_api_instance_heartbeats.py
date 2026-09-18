"""Migration che registra gli heartbeat delle repliche API.

Oltre ai normali health check di Docker e Kong, SecureScan Cloud mantiene un
segnale applicativo periodico inviato da ogni replica API. Questo permette di
capire meglio cosa sta succedendo durante fault, recovery e osservabilità.

Le informazioni create qui vengono mostrate soprattutto nella pagina
Stato del sistema.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260806_0004"
down_revision = "20260805_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crea la tabella `api_instance_heartbeats` e i relativi indici."""
    op.create_table(
        "api_instance_heartbeats",
        sa.Column("instance_id", sa.String(length=128), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "stopped", name="apiinstanceheartbeatstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("instance_id"),
    )
    op.create_index(
        "ix_api_instance_heartbeats_status",
        "api_instance_heartbeats",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_api_instance_heartbeats_last_heartbeat_at",
        "api_instance_heartbeats",
        ["last_heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    """Rimuove il registry heartbeat delle repliche API."""
    op.drop_index("ix_api_instance_heartbeats_last_heartbeat_at", table_name="api_instance_heartbeats")
    op.drop_index("ix_api_instance_heartbeats_status", table_name="api_instance_heartbeats")
    op.drop_table("api_instance_heartbeats")
