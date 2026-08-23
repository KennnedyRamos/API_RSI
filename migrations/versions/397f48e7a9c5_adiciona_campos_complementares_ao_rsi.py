"""adiciona campos complementares ao RSI

Revision ID: 397f48e7a9c5
Revises: 5ffb16c40e4d
Create Date: 2026-08-22 17:21:16.228367

"""

from alembic import op
import sqlalchemy as sa


# ============================================================
# REVISION
# ============================================================

revision = "397f48e7a9c5"
down_revision = "5ffb16c40e4d"
branch_labels = None
depends_on = None


# ============================================================
# UPGRADE
# ============================================================

def upgrade():
    """
    Atualiza a tabela rsi_data para a nova estrutura.

    Alterações:

        - adiciona RSI anterior
        - adiciona diferença do RSI
        - adiciona tipo do sinal
        - adiciona nível do sinal
        - adiciona variação 24h
        - adiciona volume 24h
        - aumenta tamanho de rsi_status
        - cria índices
        - cria constraint UNIQUE

    Atenção:

        O banco já possui registros antigos.

        Por isso signal_level é inicialmente criado
        com DEFAULT 'NORMAL', evitando erro de NOT NULL.
    """

    # ========================================================
    # 1. ALTERAR TABELA
    # ========================================================

    with op.batch_alter_table(
        "rsi_data",
        schema=None,
    ) as batch_op:

        # ----------------------------------------------------
        # RSI ANTERIOR
        # ----------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "rsi_previous",
                sa.Float(),
                nullable=True,
            )
        )

        # ----------------------------------------------------
        # DIFERENÇA DO RSI
        # ----------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "rsi_difference",
                sa.Float(),
                nullable=True,
            )
        )

        # ----------------------------------------------------
        # TIPO DO SINAL
        # ----------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "signal_type",
                sa.String(length=30),
                nullable=True,
            )
        )

        # ----------------------------------------------------
        # NÍVEL DO SINAL
        # ----------------------------------------------------
        #
        # Existem registros antigos no banco.
        #
        # Por isso precisamos de um DEFAULT.
        #
        # Todos os registros antigos receberão:
        #
        #     NORMAL
        #
        # Depois mantemos a coluna como NOT NULL.
        #

        batch_op.add_column(
            sa.Column(
                "signal_level",
                sa.String(length=30),
                nullable=False,
                server_default=sa.text("'NORMAL'"),
            )
        )

        # ----------------------------------------------------
        # VARIAÇÃO 24H
        # ----------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "change_24h",
                sa.Float(),
                nullable=True,
            )
        )

        # ----------------------------------------------------
        # VOLUME 24H
        # ----------------------------------------------------

        batch_op.add_column(
            sa.Column(
                "volume_24h",
                sa.Float(),
                nullable=True,
            )
        )

        # ----------------------------------------------------
        # RSI STATUS
        # ----------------------------------------------------

        batch_op.alter_column(
            "rsi_status",
            existing_type=sa.VARCHAR(length=20),
            type_=sa.String(length=30),
            existing_nullable=False,
        )

        # ====================================================
        # ÍNDICES
        # ====================================================

        batch_op.create_index(
            batch_op.f("ix_rsi_data_intervalo"),
            ["intervalo"],
            unique=False,
        )

        batch_op.create_index(
            batch_op.f("ix_rsi_data_signal_level"),
            ["signal_level"],
            unique=False,
        )

        batch_op.create_index(
            batch_op.f("ix_rsi_data_signal_type"),
            ["signal_type"],
            unique=False,
        )

        batch_op.create_index(
            batch_op.f("ix_rsi_data_symbol"),
            ["symbol"],
            unique=False,
        )

        batch_op.create_index(
            batch_op.f("ix_rsi_data_timestamp"),
            ["timestamp"],
            unique=False,
        )

        # ----------------------------------------------------
        # ÍNDICE:
        #
        # signal_level + intervalo + timestamp
        # ----------------------------------------------------

        batch_op.create_index(
            "ix_rsi_level_intervalo_timestamp",
            [
                "signal_level",
                "intervalo",
                "timestamp",
            ],
            unique=False,
        )

        # ----------------------------------------------------
        # ÍNDICE:
        #
        # signal_type + intervalo + timestamp
        # ----------------------------------------------------

        batch_op.create_index(
            "ix_rsi_signal_intervalo_timestamp",
            [
                "signal_type",
                "intervalo",
                "timestamp",
            ],
            unique=False,
        )

        # ----------------------------------------------------
        # ÍNDICE:
        #
        # symbol + intervalo
        # ----------------------------------------------------

        batch_op.create_index(
            "ix_rsi_symbol_intervalo",
            [
                "symbol",
                "intervalo",
            ],
            unique=False,
        )

        # ====================================================
        # UNIQUE
        # ====================================================
        #
        # Impede registros duplicados do mesmo candle.
        #
        # Combinação:
        #
        # symbol
        # intervalo
        # timestamp
        #
        # Exemplo:
        #
        # BTC/USDT
        # 1h
        # 2026-08-22 19:00:00
        #
        # Só pode existir uma vez.
        #

        batch_op.create_unique_constraint(
            "uq_rsi_symbol_intervalo_timestamp",
            [
                "symbol",
                "intervalo",
                "timestamp",
            ],
        )


# ============================================================
# DOWNGRADE
# ============================================================

def downgrade():
    """
    Reverte a migration.
    """

    with op.batch_alter_table(
        "rsi_data",
        schema=None,
    ) as batch_op:

        # ====================================================
        # REMOVER UNIQUE
        # ====================================================

        batch_op.drop_constraint(
            "uq_rsi_symbol_intervalo_timestamp",
            type_="unique",
        )

        # ====================================================
        # REMOVER ÍNDICES
        # ====================================================

        batch_op.drop_index(
            "ix_rsi_symbol_intervalo",
        )

        batch_op.drop_index(
            "ix_rsi_signal_intervalo_timestamp",
        )

        batch_op.drop_index(
            "ix_rsi_level_intervalo_timestamp",
        )

        batch_op.drop_index(
            batch_op.f("ix_rsi_data_timestamp"),
        )

        batch_op.drop_index(
            batch_op.f("ix_rsi_data_symbol"),
        )

        batch_op.drop_index(
            batch_op.f("ix_rsi_data_signal_type"),
        )

        batch_op.drop_index(
            batch_op.f("ix_rsi_data_signal_level"),
        )

        batch_op.drop_index(
            batch_op.f("ix_rsi_data_intervalo"),
        )

        # ====================================================
        # VOLTAR RSI STATUS
        # ====================================================

        batch_op.alter_column(
            "rsi_status",
            existing_type=sa.String(length=30),
            type_=sa.VARCHAR(length=20),
            existing_nullable=False,
        )

        # ====================================================
        # REMOVER NOVAS COLUNAS
        # ====================================================

        batch_op.drop_column(
            "volume_24h",
        )

        batch_op.drop_column(
            "change_24h",
        )

        batch_op.drop_column(
            "signal_level",
        )

        batch_op.drop_column(
            "signal_type",
        )

        batch_op.drop_column(
            "rsi_difference",
        )

        batch_op.drop_column(
            "rsi_previous",
        )