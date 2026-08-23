"""
ajusta estrutura RSI

Revision ID: 8eaa08674c8e
Revises: b3a53bbbfdad
Create Date: 2026-08-22 18:37:42.613249
"""

from alembic import op
import sqlalchemy as sa


# ==========================================================
# REVISION IDENTIFIERS
# ==========================================================

revision = "8eaa08674c8e"

down_revision = "b3a53bbbfdad"

branch_labels = None

depends_on = None


# ==========================================================
# UPGRADE
# ==========================================================

def upgrade():
    """
    Atualiza a tabela rsi_data para a estrutura atual.

    Alterações:

        - adiciona created_at
        - adiciona updated_at
        - reduz symbol para VARCHAR(30)
        - remove índices antigos que não são mais utilizados
        - cria índices adequados para as consultas atuais
    """

    # ======================================================
    # ALTERAÇÕES NA TABELA
    # ======================================================

    with op.batch_alter_table(
        "rsi_data",
        schema=None,
    ) as batch_op:

        # --------------------------------------------------
        # AUDITORIA
        # --------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text(
                    "now()"
                ),
                nullable=False,
            )
        )

        batch_op.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text(
                    "now()"
                ),
                nullable=False,
            )
        )

        # --------------------------------------------------
        # SYMBOL
        # --------------------------------------------------

        batch_op.alter_column(
            "symbol",

            existing_type=sa.VARCHAR(
                length=50
            ),

            type_=sa.String(
                length=30
            ),

            existing_nullable=False,
        )

    # ======================================================
    # ÍNDICES
    # ======================================================
    #
    # Os índices antigos não serão simplesmente removidos.
    #
    # Vamos garantir os índices necessários para:
    #
    #   - histórico
    #   - último candle
    #   - sinais
    #   - ranking
    #
    # ======================================================

    # Os índices compostos de signal_type e signal_level já foram
    # criados pela revisão 397f48e7a9c5. Não os recrie aqui: isso
    # impediria que uma instalação PostgreSQL vazia chegasse ao head.

    # ------------------------------------------------------
    # ÍNDICE:
    #
    # symbol + intervalo + timestamp
    # ------------------------------------------------------

    op.create_index(
        "ix_rsi_symbol_intervalo_timestamp",
        "rsi_data",
        [
            "symbol",
            "intervalo",
            "timestamp",
        ],
        unique=False,
    )

    # ------------------------------------------------------
    # ÍNDICE:
    #
    # market_cap
    # ------------------------------------------------------

    op.create_index(
        "ix_rsi_market_cap",
        "rsi_data",
        [
            "market_cap",
        ],
        unique=False,
    )

    # ------------------------------------------------------
    # ÍNDICE:
    #
    # ranking
    # ------------------------------------------------------

    op.create_index(
        "ix_rsi_ranking",
        "rsi_data",
        [
            "ranking",
        ],
        unique=False,
    )


# ==========================================================
# DOWNGRADE
# ==========================================================

def downgrade():
    """
    Reverte a migration.

    Remove:

        - índices novos
        - created_at
        - updated_at

    E restaura:

        symbol VARCHAR(50)
    """

    # ======================================================
    # REMOVER ÍNDICES
    # ======================================================

    op.drop_index(
        "ix_rsi_ranking",
        table_name="rsi_data",
    )

    op.drop_index(
        "ix_rsi_market_cap",
        table_name="rsi_data",
    )

    op.drop_index(
        "ix_rsi_symbol_intervalo_timestamp",
        table_name="rsi_data",
    )

    # ======================================================
    # ALTERAR TABELA
    # ======================================================

    with op.batch_alter_table(
        "rsi_data",
        schema=None,
    ) as batch_op:

        # --------------------------------------------------
        # RESTAURAR SYMBOL
        # --------------------------------------------------

        batch_op.alter_column(
            "symbol",

            existing_type=sa.String(
                length=30
            ),

            type_=sa.VARCHAR(
                length=50
            ),

            existing_nullable=False,
        )

        # --------------------------------------------------
        # REMOVER AUDITORIA
        # --------------------------------------------------

        batch_op.drop_column(
            "updated_at"
        )

        batch_op.drop_column(
            "created_at"
        )
