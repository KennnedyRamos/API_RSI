"""add signal events snapshots and notification outbox

Revision ID: c1e7a8d92f41
Revises: 8eaa08674c8e
Create Date: 2026-08-23 13:10:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "c1e7a8d92f41"
down_revision = "8eaa08674c8e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rsi_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=30), nullable=False),
        sa.Column("intervalo", sa.String(length=10), nullable=False),
        sa.Column("rsi_data_id", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rsi_data_id"],
            ["rsi_data.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rsi_data_id",
            name="uq_rsi_snapshot_rsi_data_id",
        ),
        sa.UniqueConstraint(
            "symbol",
            "intervalo",
            name="uq_rsi_snapshot_symbol_intervalo",
        ),
    )
    op.create_index(
        "ix_rsi_snapshot_intervalo",
        "rsi_snapshots",
        ["intervalo"],
        unique=False,
    )

    # Mantém o painel útil imediatamente após o upgrade: o snapshot de
    # cada par/timeframe aponta para o candle mais recente já existente.
    op.execute(
        """
        INSERT INTO rsi_snapshots (symbol, intervalo, rsi_data_id)
        SELECT DISTINCT ON (symbol, intervalo)
            symbol,
            intervalo,
            id
        FROM rsi_data
        ORDER BY symbol, intervalo, timestamp DESC, id DESC
        """
    )

    op.create_table(
        "signal_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("rsi_data_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "signal_level",
            sa.String(length=30),
            server_default=sa.text("'NORMAL'"),
            nullable=False,
        ),
        sa.Column("candle_closed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["rsi_data_id"],
            ["rsi_data.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rsi_data_id",
            "event_type",
            name="uq_signal_event_rsi_data_type",
        ),
    )
    op.create_index(
        "ix_signal_event_detected_at",
        "signal_events",
        ["detected_at"],
        unique=False,
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("signal_event_id", sa.Integer(), nullable=False),
        sa.Column(
            "channel",
            sa.String(length=30),
            server_default=sa.text("'TELEGRAM'"),
            nullable=False,
        ),
        sa.Column("destination", sa.String(length=100), nullable=False),
        sa.Column("dedup_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("telegram_message_id", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["signal_event_id"],
            ["signal_events.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "dedup_key",
            name="uq_notification_delivery_dedup_key",
        ),
    )
    op.create_index(
        "ix_notification_delivery_status_available_at",
        "notification_deliveries",
        ["status", "available_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_notification_delivery_status_available_at",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")

    op.drop_index(
        "ix_signal_event_detected_at",
        table_name="signal_events",
    )
    op.drop_table("signal_events")

    op.drop_index(
        "ix_rsi_snapshot_intervalo",
        table_name="rsi_snapshots",
    )
    op.drop_table("rsi_snapshots")
