from __future__ import annotations

from app import db


class SignalEvent(db.Model):
    """Evento de entrada em uma zona de RSI.

    ``signal_type`` em ``rsi_data`` descreve o estado de todos os candles.
    Esta entidade registra somente a transição que merece um alerta.
    """

    __tablename__ = "signal_events"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    rsi_data_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "rsi_data.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    event_type = db.Column(
        db.String(40),
        nullable=False,
    )

    signal_level = db.Column(
        db.String(30),
        nullable=False,
        server_default="NORMAL",
    )

    candle_closed_at = db.Column(
        db.DateTime,
        nullable=False,
    )

    detected_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "rsi_data_id",
            "event_type",
            name="uq_signal_event_rsi_data_type",
        ),
        db.Index(
            "ix_signal_event_detected_at",
            "detected_at",
        ),
    )
