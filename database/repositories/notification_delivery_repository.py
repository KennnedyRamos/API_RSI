from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from app import db
from database.models.notification_delivery import NotificationDelivery


class NotificationDeliveryRepository:
    """Fila outbox para canais externos, inicialmente o Telegram."""

    @staticmethod
    def criar_ou_buscar(
        *,
        signal_event_id: int,
        destination: str,
        dedup_key: str,
        payload: dict[str, Any],
    ) -> tuple[NotificationDelivery, bool]:
        existente = NotificationDelivery.query.filter_by(
            dedup_key=dedup_key,
        ).first()

        if existente is not None:
            return existente, False

        entrega = NotificationDelivery(
            signal_event_id=signal_event_id,
            channel="TELEGRAM",
            destination=destination,
            dedup_key=dedup_key,
            payload=payload,
            status="PENDING",
        )

        try:
            db.session.add(entrega)
            db.session.commit()
            return entrega, True
        except IntegrityError:
            db.session.rollback()
            existente = NotificationDelivery.query.filter_by(
                dedup_key=dedup_key,
            ).one()
            return existente, False

    @staticmethod
    def buscar_pendentes(
        *,
        limite: int,
    ) -> list[NotificationDelivery]:
        agora = datetime.now(timezone.utc).replace(
            tzinfo=None,
        )

        return (
            NotificationDelivery.query
            .filter(
                NotificationDelivery.status.in_((
                    "PENDING",
                    "RETRY",
                )),
                NotificationDelivery.available_at <= agora,
            )
            .order_by(
                NotificationDelivery.available_at.asc(),
                NotificationDelivery.id.asc(),
            )
            .limit(limite)
            .all()
        )

    @staticmethod
    def marcar_enviando(
        entrega: NotificationDelivery,
    ) -> None:
        entrega.status = "SENDING"
        entrega.attempts += 1
        entrega.last_error = None
        db.session.commit()

    @staticmethod
    def marcar_enviado(
        entrega: NotificationDelivery,
        telegram_message_id: str | None,
    ) -> None:
        entrega.status = "SENT"
        entrega.sent_at = datetime.now(timezone.utc).replace(
            tzinfo=None,
        )
        entrega.telegram_message_id = telegram_message_id
        entrega.last_error = None
        db.session.commit()

    @staticmethod
    def reagendar(
        entrega: NotificationDelivery,
        *,
        erro: str,
        retry_after_seconds: float,
        max_attempts: int,
    ) -> None:
        if entrega.attempts >= max_attempts:
            entrega.status = "FAILED"
            entrega.last_error = erro[:2000]
            db.session.commit()
            return

        agora = datetime.now(timezone.utc).replace(
            tzinfo=None,
        )
        entrega.status = "RETRY"
        entrega.last_error = erro[:2000]
        entrega.available_at = agora + timedelta(
            seconds=max(1.0, retry_after_seconds),
        )
        db.session.commit()
