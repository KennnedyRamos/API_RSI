from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.rsi_service import RSIService, rsi_service
from app.utils.timeframes import RSI_TIMEFRAMES
from database.repositories import (
    NotificationDeliveryRepository,
    RSISnapshotRepository,
    SignalEventRepository,
)
from services.telegram_service import (
    TelegramDeliveryError,
    TelegramService,
    telegram_service,
)

logger = logging.getLogger(__name__)


class SignalAlertService:
    """Converte transições de RSI em eventos e entregas Telegram.

    O serviço não participa do cálculo técnico. Ele é chamado pelo worker
    depois da persistência do candle e registra uma outbox idempotente para
    que reprocessamentos não causem spam no grupo.
    """

    DEFAULT_MAX_DISPATCH_PER_CYCLE = 10
    DEFAULT_MAX_ATTEMPTS = 5
    MAX_ALERT_AGE = timedelta(minutes=1)
    SENDING_RECOVERY_DELAY = timedelta(seconds=15)

    def __init__(
        self,
        *,
        event_repository=SignalEventRepository,
        delivery_repository=NotificationDeliveryRepository,
        snapshot_repository=RSISnapshotRepository,
        rsi_service_instance: RSIService | None = None,
        telegram: TelegramService | None = None,
    ) -> None:
        self.event_repository = event_repository
        self.delivery_repository = delivery_repository
        self.snapshot_repository = snapshot_repository
        self.rsi_service = rsi_service_instance or rsi_service
        self.telegram = telegram or telegram_service
        self.max_dispatch_per_cycle = max(
            0,
            int(
                os.getenv(
                    "TELEGRAM_MAX_DISPATCH_PER_CYCLE",
                    self.DEFAULT_MAX_DISPATCH_PER_CYCLE,
                )
            ),
        )
        self.max_attempts = int(
            os.getenv(
                "TELEGRAM_MAX_ATTEMPTS",
                self.DEFAULT_MAX_ATTEMPTS,
            )
        )
        self.allowed_intervals = self._csv_env(
            "TELEGRAM_ALLOWED_INTERVALS",
        )
        self.allowed_levels = self._csv_env(
            "TELEGRAM_SIGNAL_LEVELS",
        )
        self.max_ranking = self._optional_int_env(
            "TELEGRAM_MAX_RANK",
        )

    def registrar_resultados(
        self,
        resultados: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Registra eventos de entrada e suas entregas pendentes."""

        metricas, _ = self._registrar_resultados(
            resultados,
            rsi_por_symbol={},
        )
        return metricas

    def registrar_resultados_com_entregas(
        self,
        resultados: list[dict[str, Any]],
        *,
        rsi_por_symbol: dict[
            str,
            dict[str, float | None],
        ],
    ) -> tuple[dict[str, int], list[int]]:
        """Registra alertas e retorna apenas as entregas recém-criadas.

        O cache é compartilhado pelo ciclo do worker. Assim, se um mesmo
        par gerar mais de um alerta, os RSI complementares são consultados na
        Binance no máximo uma vez durante esse ciclo.
        """

        return self._registrar_resultados(
            resultados,
            rsi_por_symbol=rsi_por_symbol,
        )

    def _registrar_resultados(
        self,
        resultados: list[dict[str, Any]],
        *,
        rsi_por_symbol: dict[
            str,
            dict[str, float | None],
        ],
    ) -> tuple[dict[str, int], list[int]]:
        """Implementação compartilhada do registro idempotente de alertas."""

        eventos_criados = 0
        entregas_criadas = 0
        delivery_ids: list[int] = []

        for resultado in resultados:
            event_type = self.determinar_evento(resultado)
            rsi_data_id = resultado.get("rsi_data_id")

            if event_type is None or not rsi_data_id:
                continue

            try:
                evento, criado = self.event_repository.criar_ou_buscar(
                    rsi_data_id=int(rsi_data_id),
                    event_type=event_type,
                    signal_level=str(
                        resultado.get("signal_level", "NORMAL"),
                    ),
                    candle_closed_at=self._candle_closed_at(resultado),
                )
            except Exception:
                logger.exception(
                    "Não foi possível registrar evento RSI | "
                    "symbol=%s | intervalo=%s",
                    resultado.get("symbol"),
                    resultado.get("intervalo"),
                )
                continue

            if criado:
                eventos_criados += 1

            if not criado or not self._deve_enfileirar(resultado):
                continue

            if not self._esta_recente(evento.candle_closed_at):
                logger.info(
                    "Alerta Telegram expirado antes do enfileiramento | "
                    "symbol=%s | intervalo=%s",
                    resultado.get("symbol"),
                    resultado.get("intervalo"),
                )
                continue

            symbol = str(resultado.get("symbol", "")).strip()
            if symbol not in rsi_por_symbol:
                rsi_por_symbol[symbol] = self._obter_rsi_por_intervalo(
                    symbol,
                )

            self._atualizar_rsi_no_resumo(
                rsi_por_symbol[symbol],
                resultado,
            )

            payload = self._criar_payload(
                resultado,
                event_type=event_type,
                rsi_por_intervalo=dict(rsi_por_symbol[symbol]),
                candle_closed_at=evento.candle_closed_at,
            )
            dedup_key = self._dedup_key(
                payload,
                destination=self.telegram.chat_id,
            )

            try:
                entrega, entrega_criada = (
                    self.delivery_repository.criar_ou_buscar(
                        signal_event_id=evento.id,
                        destination=self.telegram.chat_id,
                        dedup_key=dedup_key,
                        payload=payload,
                    )
                )
            except Exception:
                logger.exception(
                    "Não foi possível enfileirar alerta Telegram | "
                    "symbol=%s | intervalo=%s",
                    resultado.get("symbol"),
                    resultado.get("intervalo"),
                )
                continue

            if entrega_criada:
                entregas_criadas += 1
                delivery_ids.append(int(entrega.id))

        return (
            {
                "events_created": eventos_criados,
                "deliveries_created": entregas_criadas,
            },
            delivery_ids,
        )

    def despachar_pendentes(
        self,
        *,
        limite: int | None = None,
        delivery_ids: list[int] | None = None,
        expirar_pendentes: bool = True,
    ) -> dict[str, int]:
        """Envia uma quantidade limitada da outbox de maneira sequencial.

        ``delivery_ids`` permite que o worker priorize as entregas recém
        criadas pelo símbolo que acabou de ser calculado, sem furar o limite
        global de mensagens do ciclo.
        """

        if not self.telegram.configurado:
            return {
                "sent": 0,
                "retried": 0,
                "expired": 0,
                "skipped": 1,
            }

        try:
            limite_solicitado = (
                self.max_dispatch_per_cycle
                if limite is None
                else int(limite)
            )
        except (TypeError, ValueError):
            limite_solicitado = 0

        limite_efetivo = min(
            self.max_dispatch_per_cycle,
            max(0, limite_solicitado),
        )
        expiradas = (
            self.delivery_repository.expirar_anteriores_a(
                cutoff=self._freshness_cutoff(),
            )
            if expirar_pendentes
            else 0
        )
        recuperadas = self.delivery_repository.recuperar_envios_interrompidos(
            cutoff=(
                datetime.now(timezone.utc).replace(tzinfo=None)
                - self.SENDING_RECOVERY_DELAY
            ),
        )
        if recuperadas:
            logger.warning(
                "Entregas Telegram recuperadas após lease vencido | total=%s",
                recuperadas,
            )
        if limite_efetivo == 0:
            return {
                "sent": 0,
                "retried": 0,
                "expired": expiradas,
                "skipped": 0,
            }

        enviadas = 0
        reagendadas = 0
        if delivery_ids is None:
            entregas = self.delivery_repository.buscar_pendentes(
                limite=limite_efetivo,
            )
        else:
            entregas = self.delivery_repository.buscar_pendentes_por_ids(
                delivery_ids=delivery_ids,
                limite=limite_efetivo,
            )
        rsi_por_symbol: dict[str, dict[str, float | None]] = {}

        for entrega in entregas:
            try:
                if not self._entrega_esta_recente(entrega):
                    self.delivery_repository.marcar_expirada(entrega)
                    expiradas += 1
                    continue

                payload = self._enriquecer_payload_rsi(
                    entrega.payload,
                    rsi_por_symbol=rsi_por_symbol,
                )
                if payload != entrega.payload:
                    entrega.payload = payload

                if not self._entrega_esta_recente(entrega):
                    self.delivery_repository.marcar_expirada(entrega)
                    expiradas += 1
                    continue

                self.delivery_repository.marcar_enviando(entrega)
                message_id = self.telegram.enviar_sinal(
                    payload,
                )
                self.delivery_repository.marcar_enviado(
                    entrega,
                    telegram_message_id=message_id,
                )
                enviadas += 1
            except TelegramDeliveryError as exc:
                retry_after = (
                    exc.retry_after_seconds
                    if exc.retry_after_seconds is not None
                    else self._retry_delay(entrega.attempts)
                )
                self.delivery_repository.reagendar(
                    entrega,
                    erro=str(exc),
                    retry_after_seconds=retry_after,
                    max_attempts=self.max_attempts,
                )
                reagendadas += 1
                logger.warning(
                    "Entrega Telegram reagendada | id=%s | attempts=%s",
                    entrega.id,
                    entrega.attempts,
                )
            except Exception:
                self.delivery_repository.reagendar(
                    entrega,
                    erro="Erro inesperado na entrega Telegram.",
                    retry_after_seconds=self._retry_delay(
                        entrega.attempts,
                    ),
                    max_attempts=self.max_attempts,
                )
                reagendadas += 1
                logger.exception(
                    "Erro inesperado ao despachar Telegram | id=%s",
                    entrega.id,
                )

        return {
            "sent": enviadas,
            "retried": reagendadas,
            "expired": expiradas,
            "skipped": 0,
        }

    @staticmethod
    def determinar_evento(
        resultado: dict[str, Any],
    ) -> str | None:
        """Identifica apenas a entrada numa zona, não seu estado contínuo."""

        try:
            rsi_atual = float(resultado["rsi"])
            rsi_anterior = float(resultado["rsi_previous"])
        except (KeyError, TypeError, ValueError):
            return None

        if rsi_anterior < 70 <= rsi_atual:
            return "ENTER_OVERBOUGHT"

        if rsi_anterior > 30 >= rsi_atual:
            return "ENTER_OVERSOLD"

        return None

    def _deve_enfileirar(
        self,
        resultado: dict[str, Any],
    ) -> bool:
        if not self.telegram.configurado:
            return False

        intervalo = str(resultado.get("intervalo", "")).upper()
        if self.allowed_intervals and intervalo not in self.allowed_intervals:
            return False

        nivel = str(resultado.get("signal_level", "NORMAL"))
        if self.allowed_levels and nivel not in self.allowed_levels:
            return False

        if self.max_ranking is not None:
            try:
                if int(resultado.get("ranking")) > self.max_ranking:
                    return False
            except (TypeError, ValueError):
                return False

        return True

    @staticmethod
    def _csv_env(name: str) -> set[str]:
        raw = os.getenv(name, "")
        return {
            value.strip().upper()
            for value in raw.split(",")
            if value.strip()
        }

    @staticmethod
    def _optional_int_env(name: str) -> int | None:
        value = os.getenv(name)

        if not value:
            return None

        try:
            return int(value)
        except ValueError:
            logger.warning(
                "%s deve ser um inteiro; filtro ignorado.",
                name,
            )
            return None

    @staticmethod
    def _retry_delay(attempts: int) -> float:
        return min(300.0, 5.0 * (2 ** max(0, attempts - 1)))

    @classmethod
    def _freshness_cutoff(cls) -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None) - cls.MAX_ALERT_AGE

    @classmethod
    def _esta_recente(cls, timestamp: datetime | None) -> bool:
        if timestamp is None:
            return False
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        return timestamp >= cls._freshness_cutoff()

    @staticmethod
    def _payload_candle_closed_at(payload: dict[str, Any]) -> datetime | None:
        value = payload.get("candle_closed_at")
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _entrega_esta_recente(self, entrega: Any) -> bool:
        candle_closed_at = self._payload_candle_closed_at(entrega.payload)
        return self._esta_recente(candle_closed_at or entrega.created_at)

    @staticmethod
    def _atualizar_rsi_no_resumo(
        resumo: dict[str, float | None],
        resultado: dict[str, Any],
    ) -> None:
        """Mantém no cache o RSI que acabou de ser persistido."""

        intervalo = str(resultado.get("intervalo", ""))
        if intervalo not in RSI_TIMEFRAMES:
            return

        try:
            resumo[intervalo] = float(resultado["rsi"])
        except (KeyError, TypeError, ValueError):
            return

    def _obter_rsi_por_intervalo(
        self,
        symbol: str,
    ) -> dict[str, float | None]:
        """Monta a fotografia dos RSI atuais para persistir na outbox."""

        rsi_por_intervalo: dict[str, float | None] = {
            intervalo: None
            for intervalo in RSI_TIMEFRAMES
        }

        if not symbol:
            return rsi_por_intervalo

        try:
            valores_atuais = self.snapshot_repository.buscar_rsi_atuais(
                symbol=symbol,
                intervalos=RSI_TIMEFRAMES,
            )
        except Exception:
            logger.exception(
                "Não foi possível obter o resumo RSI | symbol=%s",
                symbol,
            )
            valores_atuais = {}

        for intervalo in RSI_TIMEFRAMES:
            rsi_por_intervalo[intervalo] = valores_atuais.get(
                intervalo,
            )

        intervalos_sem_snapshot = tuple(
            intervalo
            for intervalo, rsi in rsi_por_intervalo.items()
            if rsi is None
        )
        if not intervalos_sem_snapshot:
            return rsi_por_intervalo

        # Um snapshot ausente acontece, por exemplo, no primeiro ciclo do
        # worker. Para o alerta não sair com N/D, consulta diretamente a
        # Binance apenas para os períodos faltantes.
        try:
            valores_em_tempo_real = self.rsi_service.obter_rsi_atuais(
                symbol=symbol,
                intervalos=intervalos_sem_snapshot,
            )
        except Exception:
            logger.exception(
                "Não foi possível completar o resumo RSI em tempo real | "
                "symbol=%s",
                symbol,
            )
            return rsi_por_intervalo

        for intervalo in intervalos_sem_snapshot:
            rsi_em_tempo_real = valores_em_tempo_real.get(intervalo)
            if rsi_em_tempo_real is not None:
                rsi_por_intervalo[intervalo] = rsi_em_tempo_real

        return rsi_por_intervalo

    def _enriquecer_payload_rsi(
        self,
        payload: dict[str, Any],
        *,
        rsi_por_symbol: dict[str, dict[str, float | None]],
    ) -> dict[str, Any]:
        """Completa entregas pendentes criadas antes da hidratação RSI."""

        valores_do_payload = payload.get("rsi_por_intervalo")
        if isinstance(valores_do_payload, dict) and all(
            valores_do_payload.get(intervalo) is not None
            for intervalo in RSI_TIMEFRAMES
        ):
            return payload

        symbol = str(payload.get("symbol", "")).strip()
        if not symbol:
            return payload

        if symbol not in rsi_por_symbol:
            rsi_por_symbol[symbol] = self._obter_rsi_por_intervalo(
                symbol,
            )

        resumo_atual = rsi_por_symbol[symbol]
        resumo = {
            intervalo: (
                resumo_atual.get(intervalo)
                if resumo_atual.get(intervalo) is not None
                else (
                    valores_do_payload.get(intervalo)
                    if isinstance(valores_do_payload, dict)
                    else None
                )
            )
            for intervalo in RSI_TIMEFRAMES
        }
        payload_atualizado = dict(payload)
        payload_atualizado["rsi_por_intervalo"] = resumo
        return payload_atualizado

    @staticmethod
    def _criar_payload(
        resultado: dict[str, Any],
        *,
        event_type: str,
        rsi_por_intervalo: dict[str, float | None],
        candle_closed_at: datetime,
    ) -> dict[str, Any]:
        payload = {
            key: resultado.get(key)
            for key in (
                "symbol",
                "intervalo",
                "rsi",
                "rsi_previous",
                "rsi_difference",
                "signal_level",
                "current_price",
                "change_24h",
                "volume_24h",
                "market_cap",
                "ranking",
            )
        }
        payload["rsi_por_intervalo"] = rsi_por_intervalo

        timestamp = resultado.get("timestamp")
        if isinstance(timestamp, datetime):
            payload["candle_timestamp"] = timestamp.replace(
                tzinfo=timezone.utc,
            ).isoformat()
        else:
            payload["candle_timestamp"] = str(timestamp or "")

        if candle_closed_at.tzinfo is None:
            candle_closed_at = candle_closed_at.replace(tzinfo=timezone.utc)
        payload["candle_closed_at"] = candle_closed_at.isoformat()

        payload["event_type"] = event_type
        payload["detected_at"] = datetime.now(
            timezone.utc,
        ).isoformat()
        return payload

    @staticmethod
    def _dedup_key(
        payload: dict[str, Any],
        *,
        destination: str,
    ) -> str:
        return ":".join(
            (
                "telegram",
                "v1",
                destination,
                str(payload.get("symbol", "")),
                str(payload.get("intervalo", "")),
                str(payload.get("candle_timestamp", "")),
                str(payload.get("event_type", "")),
            )
        )

    @staticmethod
    def _candle_closed_at(
        resultado: dict[str, Any],
    ) -> datetime:
        timestamp = resultado.get("timestamp")

        if not isinstance(timestamp, datetime):
            raise TypeError("Timestamp do candle não informado.")

        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(timezone.utc).replace(
                tzinfo=None,
            )

        intervalos = {
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "12h": timedelta(hours=12),
            "1d": timedelta(days=1),
            "1w": timedelta(weeks=1),
        }
        intervalo = str(resultado.get("intervalo", ""))

        if intervalo == "1M":
            if timestamp.month == 12:
                return timestamp.replace(
                    year=timestamp.year + 1,
                    month=1,
                    day=1,
                )
            return timestamp.replace(
                month=timestamp.month + 1,
                day=1,
            )

        try:
            return timestamp + intervalos[intervalo]
        except KeyError as exc:
            raise ValueError(
                f"Intervalo não suportado: {intervalo}",
            ) from exc


signal_alert_service = SignalAlertService()
