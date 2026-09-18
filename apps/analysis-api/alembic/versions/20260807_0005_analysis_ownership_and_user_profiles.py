"""Migration che introduce ownership delle analisi e profili applicativi.

Questa revisione aggiunge le informazioni che permettono di associare ogni
analisi all'utente che l'ha creata.

Quando un utente carica un file da Nuova analisi, il suo subject Keycloak e il
suo username vengono salvati insieme all'analisi. Questo permette:
- a Cronologia di mostrare all'analyst solo le proprie analisi;
- a Dettaglio analisi di negare l'accesso ai record altrui;
- a Dashboard di calcolare i dati nello stesso perimetro;
- all'amministratore di vedere invece l'intero dataset.

La migration crea anche `user_profiles`, usata per dati applicativi come
l'avatar, che non vengono gestiti direttamente da Keycloak.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260807_0005"
down_revision = "20260806_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Aggiunge ownership alle analisi e crea la tabella `user_profiles`."""
    op.add_column("analyses", sa.Column("owner_sub", sa.String(length=255), nullable=True))
    op.add_column("analyses", sa.Column("owner_username", sa.String(length=255), nullable=True))
    op.create_index("ix_analyses_owner_sub", "analyses", ["owner_sub"], unique=False)

    op.create_table(
        "user_profiles",
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("avatar_path", sa.String(length=1024), nullable=True),
        sa.Column("avatar_media_type", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("subject"),
    )


def downgrade() -> None:
    """Rimuove supporto ownership e tabella profili applicativi."""
    op.drop_table("user_profiles")
    op.drop_index("ix_analyses_owner_sub", table_name="analyses")
    op.drop_column("analyses", "owner_username")
    op.drop_column("analyses", "owner_sub")
