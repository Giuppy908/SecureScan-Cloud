"""Prima migration del progetto per salvare le analisi in PostgreSQL.

Una migration Alembic è un file che descrive come cambiare la struttura del
database in modo controllato e ripetibile.

Questa migration crea la tabella `analyses`, cioè il contenitore principale
dei dati mostrati poi in Cronologia, Dettaglio analisi e Dashboard.
Introduce anche il progressivo numerico da cui nascerà l'ID pubblico
`ANL-YYYY-NNNN`.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260805_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Crea la tabella `analyses` e gli indici base della milestone iniziale."""
    op.create_table(
        "analyses",
        sa.Column("sequence_number", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.Enum("queued", "processing", "completed", "failed", name="analysisstatus", native_enum=False), nullable=False),
        sa.Column("risk_level", sa.Enum("low", "medium", "high", "critical", name="risklevel", native_enum=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("entropy", sa.Float(), nullable=False),
        sa.Column("extension_matches_mime", sa.Boolean(), nullable=False),
        sa.Column("indicators", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint("sequence_number"),
        sa.UniqueConstraint("id"),
        sqlite_autoincrement=True,
    )
    op.create_index(op.f("ix_analyses_id"), "analyses", ["id"], unique=False)
    op.create_index("ix_analyses_sha256", "analyses", ["sha256"], unique=False)
    op.create_index("ix_analyses_created_at", "analyses", ["created_at"], unique=False)


def downgrade() -> None:
    """Rimuove la tabella `analyses` e gli indici creati dalla revisione iniziale."""
    op.drop_index("ix_analyses_created_at", table_name="analyses")
    op.drop_index("ix_analyses_sha256", table_name="analyses")
    op.drop_index(op.f("ix_analyses_id"), table_name="analyses")
    op.drop_table("analyses")
