from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db
from app.services.signal_alert_service import SignalAlertService
from app.utils.timeframes import RSI_TIMEFRAMES
from database.models.notification_delivery import NotificationDelivery
from database.models.rsi import RSIData
from database.models.signal_event import SignalEvent
from database.repositories.rsi_snapshot_repository import (
    RSISnapshotRepository,
)
from services.telegram_service import TelegramService


def test_alerts_only_trigger_on_zone_entry():
    assert SignalAlertService.determinar_evento(
        {"rsi_previous": 69.84, "rsi": 72.41}
    ) == "ENTER_OVERBOUGHT"
    assert SignalAlertService.determinar_evento(
        {"rsi_previous": 72.41, "rsi": 74.0}
    ) is None
    assert SignalAlertService.determinar_evento(
        {"rsi_previous": 31.5, "rsi": 28.9}
    ) == "ENTER_OVERSOLD"


def test_telegram_message_uses_pt_br_formatting():
    telegram = TelegramService(
        enabled=False,
        app_timezone="America/Sao_Paulo",
    )
    message = telegram.formatar_sinal(
        {
            "symbol": "BTC/USDT",
            "ranking": 1,
            "event_type": "ENTER_OVERBOUGHT",
            "current_price": 104250,
            "rsi": 72.41,
            "intervalo": "1h",
            "detected_at": "2026-08-21T20:42:00+00:00",
            "change_24h": 3.82,
            "rsi_previous": 69.84,
            "rsi_difference": 2.57,
            "volume_24h": 42_310_000_000,
            "signal_level": "MODERATE",
            "rsi_por_intervalo": {
                "5m": 66.18,
                "15m": 68.95,
                "30m": 71.07,
                "1h": 72.41,
                "4h": 63.5,
                "12h": None,
                "1d": 58.42,
                "1w": 54.11,
                "1M": 49.8,
            },
        }
    )

    assert "BTC/USDT" in message
    assert "$104.250,00" in message
    assert "72,41" in message
    assert "🔴 <b>OPERAÇÃO: VENDA</b>" in message
    assert "Nível do sinal: Moderado" in message
    assert "Entrada em sobrecompra" in message
    assert "RSI 5m: 66,18" in message
    assert "RSI 15m: 68,95" in message
    assert "RSI 30m: 71,07" in message
    assert "RSI 1h:" not in message
    assert "RSI 4h: 63,50" in message
    assert "RSI 12h: N/D" in message
    assert "RSI 1d: 58,42" in message
    assert "RSI 1W: 54,11" in message
    assert "RSI 1M: 49,80" in message


def test_telegram_message_marks_oversold_as_buy():
    telegram = TelegramService(enabled=False)
    message = telegram.formatar_sinal(
        {
            "symbol": "ETH/USDT",
            "event_type": "ENTER_OVERSOLD",
        }
    )

    assert "🟢 <b>OPERAÇÃO: COMPRA</b>" in message
    assert "Entrada em sobrevenda" in message


def test_telegram_message_marks_unknown_event_as_analyze():
    telegram = TelegramService(enabled=False)
    message = telegram.formatar_sinal(
        {
            "symbol": "ETH/USDT",
            "event_type": "UNKNOWN",
        }
    )

    assert "⚪ <b>OPERAÇÃO: ANALISAR</b>" in message
    assert "Movimento de RSI" in message


def test_telegram_message_keeps_precision_for_low_price_and_translates_level():
    telegram = TelegramService(enabled=False)
    message = telegram.formatar_sinal(
        {
            "symbol": "LOW/USDT",
            "event_type": "ENTER_OVERBOUGHT",
            "current_price": "0.00012345",
            "signal_level": "STRONG",
            "intervalo": "30m",
        }
    )

    assert "Valor atual: $0,00012345" in message
    assert "Nível do sinal: Forte" in message


def test_telegram_message_keeps_rsi_layout_for_legacy_outbox_payload():
    telegram = TelegramService(enabled=False)
    message = telegram.formatar_sinal(
        {
            "symbol": "DUSK/USDT",
            "event_type": "ENTER_OVERBOUGHT",
            "intervalo": "30m",
        }
    )

    assert "RSI 5m: N/D" in message
    assert "RSI 15m: N/D" in message
    assert "RSI 30m:" not in message
    assert "RSI 1h: N/D" in message
    assert "RSI 4h: N/D" in message


def test_alert_service_fills_missing_rsi_with_live_values():
    class SnapshotRepositoryFake:
        @staticmethod
        def buscar_rsi_atuais(*, symbol, intervalos):
            assert symbol == "DUSK/USDT"
            assert tuple(intervalos) == RSI_TIMEFRAMES
            return {"5m": 72.82}

    class RSIServiceFake:
        def __init__(self):
            self.calls = []

        def obter_rsi_atuais(self, *, symbol, intervalos):
            self.calls.append((symbol, tuple(intervalos)))
            return {
                intervalo: 40.0 + indice
                for indice, intervalo in enumerate(intervalos)
            }

    rsi_service_fake = RSIServiceFake()
    service = SignalAlertService(
        snapshot_repository=SnapshotRepositoryFake,
        rsi_service_instance=rsi_service_fake,
        telegram=TelegramService(enabled=False),
    )

    resumo = service._obter_rsi_por_intervalo("DUSK/USDT")

    assert resumo["5m"] == 72.82
    assert all(valor is not None for valor in resumo.values())
    assert rsi_service_fake.calls == [
        ("DUSK/USDT", RSI_TIMEFRAMES[1:]),
    ]


def test_alert_service_enriches_incomplete_pending_payload():
    class SnapshotRepositoryFake:
        @staticmethod
        def buscar_rsi_atuais(*, symbol, intervalos):
            assert symbol == "DUSK/USDT"
            assert tuple(intervalos) == RSI_TIMEFRAMES
            return {}

    class RSIServiceFake:
        def __init__(self):
            self.calls = []

        def obter_rsi_atuais(self, *, symbol, intervalos):
            self.calls.append((symbol, tuple(intervalos)))
            return {
                intervalo: 50.0 + indice
                for indice, intervalo in enumerate(intervalos)
            }

    rsi_service_fake = RSIServiceFake()
    service = SignalAlertService(
        snapshot_repository=SnapshotRepositoryFake,
        rsi_service_instance=rsi_service_fake,
        telegram=TelegramService(enabled=False),
    )
    payload = {
        "symbol": "DUSK/USDT",
        "intervalo": "5m",
        "rsi_por_intervalo": {"5m": 72.82},
    }

    resultado = service._enriquecer_payload_rsi(
        payload,
        rsi_por_symbol={},
    )

    assert all(
        resultado["rsi_por_intervalo"][intervalo] is not None
        for intervalo in RSI_TIMEFRAMES
    )
    assert resultado["rsi_por_intervalo"]["5m"] == 50.0
    assert rsi_service_fake.calls == [
        ("DUSK/USDT", RSI_TIMEFRAMES),
    ]


def test_event_and_outbox_are_idempotent(app):
    with app.app_context():
        timestamp = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(hours=1, seconds=10)
        )
        rsi_por_intervalo = {
            "5m": 65.12,
            "15m": 67.34,
            "30m": 70.01,
            "1h": 72.41,
            "4h": 61.78,
            "12h": 58.92,
            "1d": 55.67,
            "1w": 52.45,
            "1M": 49.23,
        }
        registros: dict[str, RSIData] = {}

        for intervalo in RSI_TIMEFRAMES:
            rsi = rsi_por_intervalo[intervalo]
            registro = RSIData(
                symbol="BTC/USDT",
                intervalo=intervalo,
                rsi=rsi,
                rsi_previous=69.84 if intervalo == "1h" else rsi - 1,
                rsi_difference=2.57 if intervalo == "1h" else 1.0,
                timestamp=timestamp,
                rsi_status="OVERBOUGHT" if rsi >= 70 else "NORMAL",
                signal_type="OVERBOUGHT" if rsi >= 70 else None,
                signal_level="MODERATE",
                current_price=104250.0,
                change_24h=3.82,
                volume_24h=42_310_000_000.0,
                ranking=1,
            )
            registros[intervalo] = registro
            db.session.add(registro)

        db.session.commit()

        for intervalo, registro in registros.items():
            RSISnapshotRepository.atualizar(
                symbol=registro.symbol,
                intervalo=intervalo,
                rsi_data_id=registro.id,
            )

        registro = registros["1h"]

        telegram = TelegramService(
            enabled=True,
            bot_token="token-de-teste",
            chat_id="-100123",
        )
        service = SignalAlertService(telegram=telegram)
        resultado = {
            "rsi_data_id": registro.id,
            "symbol": registro.symbol,
            "intervalo": registro.intervalo,
            "rsi": registro.rsi,
            "rsi_previous": registro.rsi_previous,
            "rsi_difference": registro.rsi_difference,
            "timestamp": registro.timestamp,
            "signal_level": registro.signal_level,
            "current_price": registro.current_price,
            "change_24h": registro.change_24h,
            "volume_24h": registro.volume_24h,
            "ranking": registro.ranking,
        }

        primeiro = service.registrar_resultados([resultado])
        segundo = service.registrar_resultados([resultado])

        assert primeiro == {
            "events_created": 1,
            "deliveries_created": 1,
        }
        assert segundo == {
            "events_created": 0,
            "deliveries_created": 0,
        }
        assert SignalEvent.query.count() == 1
        assert NotificationDelivery.query.count() == 1
        entrega = NotificationDelivery.query.one()
        assert entrega.payload["rsi_por_intervalo"] == rsi_por_intervalo


def test_alert_service_expires_delivery_with_old_candle(app):
    class TelegramFake:
        configurado = True
        chat_id = "-100123"

        def __init__(self):
            self.messages: list[dict] = []

        def enviar_sinal(self, payload):
            self.messages.append(payload)
            return "message-id"

    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        event = SignalEvent(
            rsi_data_id=1,
            event_type="ENTER_OVERBOUGHT",
            signal_level="NORMAL",
            candle_closed_at=now - timedelta(minutes=2),
        )
        db.session.add(event)
        db.session.commit()
        delivery = NotificationDelivery(
            signal_event_id=event.id,
            channel="TELEGRAM",
            destination="-100123",
            dedup_key="old-candle",
            payload={
                "symbol": "BTC/USDT",
                "candle_closed_at": (
                    now - timedelta(minutes=2)
                ).replace(tzinfo=timezone.utc).isoformat(),
                "rsi_por_intervalo": {
                    intervalo: 50.0 for intervalo in RSI_TIMEFRAMES
                },
            },
            status="PENDING",
            available_at=now,
            created_at=now,
        )
        db.session.add(delivery)
        db.session.commit()

        telegram = TelegramFake()
        result = SignalAlertService(telegram=telegram).despachar_pendentes()

        assert result == {"sent": 0, "retried": 0, "expired": 1, "skipped": 0}
        assert telegram.messages == []
        assert delivery.status == "EXPIRED"


def test_alert_service_expires_old_pending_outbox_before_dispatch(app):
    class TelegramFake:
        configurado = True
        chat_id = "-100123"

        def enviar_sinal(self, payload):
            raise AssertionError("Uma entrega expirada não pode ser enviada.")

    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        event = SignalEvent(
            rsi_data_id=1,
            event_type="ENTER_OVERSOLD",
            signal_level="NORMAL",
            candle_closed_at=now,
        )
        db.session.add(event)
        db.session.commit()
        delivery = NotificationDelivery(
            signal_event_id=event.id,
            channel="TELEGRAM",
            destination="-100123",
            dedup_key="old-outbox",
            payload={"symbol": "ETH/USDT"},
            status="PENDING",
            available_at=now - timedelta(minutes=2),
            created_at=now - timedelta(minutes=2),
        )
        db.session.add(delivery)
        db.session.commit()

        result = SignalAlertService(
            telegram=TelegramFake(),
        ).despachar_pendentes()

        assert result == {"sent": 0, "retried": 0, "expired": 1, "skipped": 0}
        db.session.refresh(delivery)
        assert delivery.status == "EXPIRED"


def test_alert_service_dispatches_delivery_with_fresh_candle(app):
    class TelegramFake:
        configurado = True
        chat_id = "-100123"

        def __init__(self):
            self.messages: list[dict] = []

        def enviar_sinal(self, payload):
            self.messages.append(payload)
            return "message-id"

    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        event = SignalEvent(
            rsi_data_id=1,
            event_type="ENTER_OVERBOUGHT",
            signal_level="NORMAL",
            candle_closed_at=now - timedelta(seconds=20),
        )
        db.session.add(event)
        db.session.commit()
        delivery = NotificationDelivery(
            signal_event_id=event.id,
            channel="TELEGRAM",
            destination="-100123",
            dedup_key="fresh-candle",
            payload={
                "symbol": "BTC/USDT",
                "candle_closed_at": (
                    now - timedelta(seconds=20)
                ).replace(tzinfo=timezone.utc).isoformat(),
                "rsi_por_intervalo": {
                    intervalo: 50.0 for intervalo in RSI_TIMEFRAMES
                },
            },
            status="PENDING",
            available_at=now,
            created_at=now,
        )
        db.session.add(delivery)
        db.session.commit()

        telegram = TelegramFake()
        result = SignalAlertService(telegram=telegram).despachar_pendentes()

        assert result == {"sent": 1, "retried": 0, "expired": 0, "skipped": 0}
        assert len(telegram.messages) == 1
        assert delivery.status == "SENT"


def test_alert_service_rechecks_age_after_payload_enrichment(app):
    class TelegramFake:
        configurado = True
        chat_id = "-100123"

        def enviar_sinal(self, payload):
            raise AssertionError("Um alerta que venceu no ciclo não pode ser enviado.")

    with app.app_context():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        event = SignalEvent(
            rsi_data_id=1,
            event_type="ENTER_OVERBOUGHT",
            signal_level="NORMAL",
            candle_closed_at=now - timedelta(seconds=20),
        )
        db.session.add(event)
        db.session.commit()
        delivery = NotificationDelivery(
            signal_event_id=event.id,
            channel="TELEGRAM",
            destination="-100123",
            dedup_key="expires-during-enrichment",
            payload={
                "symbol": "BTC/USDT",
                "candle_closed_at": (
                    now - timedelta(seconds=20)
                ).replace(tzinfo=timezone.utc).isoformat(),
                "rsi_por_intervalo": {
                    intervalo: 50.0 for intervalo in RSI_TIMEFRAMES
                },
            },
            status="PENDING",
            available_at=now,
            created_at=now,
        )
        db.session.add(delivery)
        db.session.commit()

        service = SignalAlertService(telegram=TelegramFake())
        freshness_checks = iter((True, False))

        def entrega_esta_recente(_):
            return next(freshness_checks)

        service._entrega_esta_recente = entrega_esta_recente

        result = service.despachar_pendentes()

        assert result == {"sent": 0, "retried": 0, "expired": 1, "skipped": 0}
        assert delivery.status == "EXPIRED"
