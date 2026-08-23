from __future__ import annotations

from app import db


class RSISnapshot(db.Model):
    """Estado mais recente de um par em determinado timeframe.

    O histórico completo permanece em ``rsi_data``. Esta tabela existe
    apenas para que a API do painel consiga listar o estado atual de cada
    par sem repetir candles antigos.
    """

    __tablename__ = "rsi_snapshots"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    symbol = db.Column(
        db.String(30),
        nullable=False,
    )

    intervalo = db.Column(
        db.String(10),
        nullable=False,
    )

    rsi_data_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "rsi_data.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "rsi_data_id",
            name="uq_rsi_snapshot_rsi_data_id",
        ),
        db.UniqueConstraint(
            "symbol",
            "intervalo",
            name="uq_rsi_snapshot_symbol_intervalo",
        ),
        db.Index(
            "ix_rsi_snapshot_intervalo",
            "intervalo",
        ),
    )
