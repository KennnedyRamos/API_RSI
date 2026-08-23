"""Reconcile RSI query indexes.

Revision ID: d3f19a7b62e4
Revises: c1e7a8d92f41
Create Date: 2026-08-23
"""

from alembic import op


revision = "d3f19a7b62e4"
down_revision = "c1e7a8d92f41"
branch_labels = None
depends_on = None


_QUERY_INDEXES = (
    (
        "ix_rsi_symbol_intervalo_timestamp",
        "symbol, intervalo, timestamp",
    ),
    (
        "ix_rsi_signal_intervalo_timestamp",
        "signal_type, intervalo, timestamp",
    ),
    (
        "ix_rsi_level_intervalo_timestamp",
        "signal_level, intervalo, timestamp",
    ),
    ("ix_rsi_market_cap", "market_cap"),
    ("ix_rsi_ranking", "ranking"),
)


def upgrade():
    """Create any intended RSI indexes missing from older databases.

    Some deployments were stamped at the previous revision after the table
    columns had been updated, but before its query indexes existed.  PostgreSQL
    makes this repair idempotent, so new installations simply keep their
    already-created indexes.
    """
    for index_name, columns in _QUERY_INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON rsi_data ({columns})"
        )


def downgrade():
    """Keep indexes created by the historical migration intact.

    The previous revision already declared these indexes.  Dropping them here
    would make a downgrade of this repair leave that revision incomplete.
    """
