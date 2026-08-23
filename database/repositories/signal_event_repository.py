from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app import db
from database.models.signal_event import SignalEvent


class SignalEventRepository:
    """Persiste eventos de transição de RSI de forma idempotente."""

    @staticmethod
    def criar_ou_buscar(
        *,
        rsi_data_id: int,
        event_type: str,
        signal_level: str,
        candle_closed_at: datetime,
    ) -> tuple[SignalEvent, bool]:
        existente = SignalEvent.query.filter_by(
            rsi_data_id=rsi_data_id,
            event_type=event_type,
        ).first()

        if existente is not None:
            return existente, False

        evento = SignalEvent(
            rsi_data_id=rsi_data_id,
            event_type=event_type,
            signal_level=signal_level,
            candle_closed_at=candle_closed_at,
        )

        try:
            db.session.add(evento)
            db.session.commit()
            return evento, True
        except IntegrityError:
            # Outro worker pode ter persistido o mesmo evento enquanto
            # esta instância processava o candle.
            db.session.rollback()
            existente = SignalEvent.query.filter_by(
                rsi_data_id=rsi_data_id,
                event_type=event_type,
            ).one()
            return existente, False
