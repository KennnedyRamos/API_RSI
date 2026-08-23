from __future__ import annotations

from app import db


class NotificationDelivery(db.Model):
    """Outbox persistida para entrega de notificações externas."""

    __tablename__ = "notification_deliveries"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    signal_event_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "signal_events.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    channel = db.Column(
        db.String(30),
        nullable=False,
        server_default="TELEGRAM",
    )

    destination = db.Column(
        db.String(100),
        nullable=False,
    )

    dedup_key = db.Column(
        db.String(255),
        nullable=False,
    )

    payload = db.Column(
        db.JSON,
        nullable=False,
    )

    status = db.Column(
        db.String(20),
        nullable=False,
        server_default="PENDING",
    )

    attempts = db.Column(
        db.Integer,
        nullable=False,
        server_default="0",
    )

    available_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
    )

    sent_at = db.Column(
        db.DateTime,
        nullable=True,
    )

    telegram_message_id = db.Column(
        db.String(100),
        nullable=True,
    )

    last_error = db.Column(
        db.Text,
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
    )

    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint(
            "dedup_key",
            name="uq_notification_delivery_dedup_key",
        ),
        db.Index(
            "ix_notification_delivery_status_available_at",
            "status",
            "available_at",
        ),
    )
