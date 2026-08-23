"""adiciona market cap e ranking ao RSI

Revision ID: b3a53bbbfdad
Revises: 397f48e7a9c5
Create Date: 2026-08-22 17:41:10.410938

"""

from alembic import op
import sqlalchemy as sa


# ==========================================================
# REVISION IDENTIFIERS
# ==========================================================

revision = "b3a53bbbfdad"
down_revision = "397f48e7a9c5"
branch_labels = None
depends_on = None


# ==========================================================
# UPGRADE
# ==========================================================

def upgrade():
    """
    Adiciona informações de market data ao RSI.

    Novos campos:

        market_cap
            Capitalização de mercado da criptomoeda.

        ranking
            Ranking da criptomoeda por market cap.

    Ambos são nullable porque:
        - nem todos os ativos poderão ter dados do MarketService;
        - registros antigos não possuem essas informações;
        - o Worker poderá preencher esses campos posteriormente.
    """

    with op.batch_alter_table(
        "rsi_data",
        schema=None,
    ) as batch_op:

        # --------------------------------------------------
        # MARKET CAP
        # --------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "market_cap",
                sa.Float(),
                nullable=True,
            )
        )

        # --------------------------------------------------
        # RANKING
        # --------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "ranking",
                sa.Integer(),
                nullable=True,
            )
        )

        # --------------------------------------------------
        # ÍNDICES
        # --------------------------------------------------

        batch_op.create_index(
            "ix_rsi_data_market_cap",
            ["market_cap"],
            unique=False,
        )

        batch_op.create_index(
            "ix_rsi_data_ranking",
            ["ranking"],
            unique=False,
        )


# ==========================================================
# DOWNGRADE
# ==========================================================

def downgrade():
    """
    Remove market_cap e ranking.
    """

    with op.batch_alter_table(
        "rsi_data",
        schema=None,
    ) as batch_op:

        # --------------------------------------------------
        # REMOVER ÍNDICES
        # --------------------------------------------------

        batch_op.drop_index(
            "ix_rsi_data_ranking"
        )

        batch_op.drop_index(
            "ix_rsi_data_market_cap"
        )

        # --------------------------------------------------
        # REMOVER COLUNAS
        # --------------------------------------------------

        batch_op.drop_column(
            "ranking"
        )

        batch_op.drop_column(
            "market_cap"
        )