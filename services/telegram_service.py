from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from app.utils.signal_levels import rotulo_nivel_sinal
from app.utils.timeframes import RSI_TIMEFRAMES, rotulo_timeframe

logger = logging.getLogger(__name__)


class TelegramDeliveryError(RuntimeError):
    """Erro de entrega com metadados úteis para o retry da outbox."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TelegramService:
    """Cliente mínimo e seguro da API HTTP do Telegram."""

    API_BASE_URL = "https://api.telegram.org"
    DEFAULT_TIMEOUT_SECONDS = 10.0
    MAX_PRICE_DECIMAL_PLACES = 8

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        bot_token: str | None = None,
        chat_id: str | None = None,
        message_thread_id: str | None = None,
        timeout_seconds: float | None = None,
        app_timezone: str | None = None,
        dashboard_public_url: str | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.enabled = (
            enabled
            if enabled is not None
            else self._env_bool("TELEGRAM_ENABLED", False)
        )
        self.bot_token = bot_token or os.getenv(
            "TELEGRAM_BOT_TOKEN",
            "",
        )
        self.chat_id = chat_id or os.getenv(
            "TELEGRAM_CHAT_ID",
            "",
        )
        self.message_thread_id = (
            message_thread_id
            or os.getenv("TELEGRAM_MESSAGE_THREAD_ID", "")
        )
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(
                os.getenv(
                    "TELEGRAM_SEND_TIMEOUT_SECONDS",
                    self.DEFAULT_TIMEOUT_SECONDS,
                )
            )
        )
        self.dashboard_public_url = (
            dashboard_public_url
            or os.getenv("DASHBOARD_PUBLIC_URL", "").rstrip("/")
        )
        self.session = session or requests.Session()

        timezone_name = app_timezone or os.getenv(
            "APP_TIMEZONE",
            "America/Sao_Paulo",
        )
        try:
            self.app_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            logger.warning(
                "Timezone inválido para Telegram: %s. Usando UTC.",
                timezone_name,
            )
            self.app_timezone = timezone.utc

    @property
    def configurado(self) -> bool:
        return bool(
            self.enabled
            and self.bot_token
            and self.chat_id
        )

    @staticmethod
    def _env_bool(
        name: str,
        default: bool,
    ) -> bool:
        value = os.getenv(name)

        if value is None:
            return default

        return value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def enviar_sinal(
        self,
        payload: dict[str, Any],
    ) -> str | None:
        """Envia um evento já persistido pela outbox."""

        if not self.configurado:
            raise TelegramDeliveryError(
                "Telegram não está configurado.",
            )

        body: dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": self.formatar_sinal(payload),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        if self.message_thread_id:
            body["message_thread_id"] = int(
                self.message_thread_id,
            )

        try:
            response = self.session.post(
                f"{self.API_BASE_URL}/bot{self.bot_token}/sendMessage",
                json=body,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TelegramDeliveryError(
                "Falha de rede ao enviar alerta ao Telegram.",
            ) from exc

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.status_code >= 400 or not data.get("ok"):
            parameters = data.get("parameters") or {}
            retry_after = parameters.get("retry_after")
            retry_after_seconds = (
                float(retry_after)
                if retry_after is not None
                else None
            )
            description = data.get(
                "description",
                f"HTTP {response.status_code}",
            )
            raise TelegramDeliveryError(
                f"Telegram recusou a mensagem: {description}",
                retry_after_seconds=retry_after_seconds,
            )

        result = data.get("result") or {}
        message_id = result.get("message_id")
        return str(message_id) if message_id is not None else None

    def formatar_sinal(
        self,
        payload: dict[str, Any],
    ) -> str:
        """Converte o snapshot do evento no formato do grupo."""

        symbol = html.escape(str(payload.get("symbol", "N/D")))
        ranking = payload.get("ranking")
        event_type = str(payload.get("event_type", ""))

        titulo = self._estrelas(ranking)
        indicador, operacao, evento = self._detalhes_evento(
            event_type
        )
        linhas_rsi_por_intervalo = self._linhas_rsi_por_intervalo(
            payload,
        )

        linhas = [
            f"{titulo} 🪙 <b>{symbol}</b>",
            "",
            f"{indicador} <b>OPERAÇÃO: {operacao}</b>",
            "",
            f"• Top Ranking: {self._formatar_ranking(ranking)}",
            "",
            f"• 💵 Valor atual: {self._formatar_moeda(payload.get('current_price'))}",
            (
                "• ⏱ Timeframe: "
                f"{html.escape(rotulo_timeframe(payload.get('intervalo', 'N/D')))}"
            ),
            f"• 📊 RSI atingido: {self._formatar_numero(payload.get('rsi'))}",
            *linhas_rsi_por_intervalo,
            f"• 📈 Variação 24h: {self._formatar_percentual(payload.get('change_24h'))}",
            f"• 📊 RSI anterior: {self._formatar_numero(payload.get('rsi_previous'))}",
            f"• 📊 Diferença do RSI: {self._formatar_assinado(payload.get('rsi_difference'))}",
            f"• 💰 Volume 24h: {self._formatar_volume(payload.get('volume_24h'))}",
            (
                "• 🔥 Nível do sinal: "
                f"{html.escape(rotulo_nivel_sinal(payload.get('signal_level')))}"
            ),
            f"• 🚨 Evento: {evento}",
            f"• 🕐 Horário: {self._formatar_data(payload.get('detected_at'))}",
        ]

        if self.dashboard_public_url:
            symbol_path = str(
                payload.get("symbol", ""),
            ).replace("/", "")
            intervalo = str(payload.get("intervalo", ""))
            linhas.extend(
                [
                    "",
                    (
                        "<a href=\""
                        f"{html.escape(self.dashboard_public_url)}/dashboard"
                        f"?symbol={html.escape(symbol_path)}"
                        f"&amp;intervalo={html.escape(intervalo)}\""
                        ">Ver análise no painel</a>"
                    ),
                ]
            )

        linhas.extend(
            [
                "",
                (
                    "⚠️ <i>Indicador técnico. Não constitui recomendação "
                    "de compra ou venda.</i>"
                ),
            ]
        )

        return "\n".join(linhas)

    @classmethod
    def _linhas_rsi_por_intervalo(
        cls,
        payload: dict[str, Any],
    ) -> list[str]:
        """Lista os outros RSI sem repetir o período que gerou o alerta."""

        valores = payload.get("rsi_por_intervalo")
        # Entregas antigas da outbox não possuíam este snapshot. Ainda
        # exibimos a grade para que a mensagem mantenha o mesmo layout; os
        # períodos indisponíveis aparecem como N/D.
        if not isinstance(valores, dict):
            valores = {}

        intervalo_alerta = str(payload.get("intervalo", "")).strip()
        if intervalo_alerta.lower() == "1w":
            intervalo_alerta = "1w"

        return [
            (
                "• 📊 RSI "
                f"{html.escape(rotulo_timeframe(intervalo))}: "
                f"{cls._formatar_numero(valores.get(intervalo))}"
            )
            for intervalo in RSI_TIMEFRAMES
            if intervalo != intervalo_alerta
        ]

    @staticmethod
    def _detalhes_evento(
        event_type: str,
    ) -> tuple[str, str, str]:
        """Traduz o evento RSI para a direção exibida no alerta."""
        if event_type == "ENTER_OVERBOUGHT":
            return "🔴", "VENDA", "Entrada em sobrecompra"

        if event_type == "ENTER_OVERSOLD":
            return "🟢", "COMPRA", "Entrada em sobrevenda"

        return "⚪", "ANALISAR", "Movimento de RSI"

    @staticmethod
    def _estrelas(ranking: Any) -> str:
        try:
            ranking_int = int(ranking)
        except (TypeError, ValueError):
            return "⭐"

        if ranking_int <= 10:
            return "⭐⭐⭐"

        if ranking_int <= 100:
            return "⭐⭐"

        return "⭐"

    @staticmethod
    def _formatar_ranking(value: Any) -> str:
        try:
            return f"#{int(value)}"
        except (TypeError, ValueError):
            return "N/D"

    @staticmethod
    def _formatar_numero(value: Any) -> str:
        try:
            return f"{float(value):,.2f}".replace(",", "X").replace(
                ".",
                ",",
            ).replace("X", ".")
        except (TypeError, ValueError):
            return "N/D"

    @classmethod
    def _formatar_assinado(cls, value: Any) -> str:
        try:
            numero = float(value)
        except (TypeError, ValueError):
            return "N/D"

        sinal = "+" if numero > 0 else ""
        return f"{sinal}{cls._formatar_numero(numero)}"

    @classmethod
    def _formatar_percentual(cls, value: Any) -> str:
        try:
            numero = float(value)
        except (TypeError, ValueError):
            return "N/D"

        sinal = "+" if numero > 0 else ""
        return f"{sinal}{cls._formatar_numero(numero)}%"

    @classmethod
    def _formatar_moeda(cls, value: Any) -> str:
        numero = cls._formatar_preco(value)
        return "$" + numero if numero != "N/D" else numero

    @classmethod
    def _formatar_preco(cls, value: Any) -> str:
        """Formata preços preservando a precisão de moedas baratas.

        O RSI e os percentuais permanecem com duas casas, mas um preço
        como ``0.00012345`` não pode ser reduzido para ``0,00``. Mantemos
        no máximo oito casas decimais, removendo apenas zeros supérfluos
        e conservando pelo menos duas casas para a leitura pt-BR.
        """

        try:
            numero = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return "N/D"

        if not numero.is_finite():
            return "N/D"

        texto = format(
            numero,
            f",.{cls.MAX_PRICE_DECIMAL_PLACES}f",
        )
        inteiro, decimal = texto.split(".")
        decimal = decimal.rstrip("0").ljust(2, "0")
        texto = f"{inteiro}.{decimal}"

        return texto.replace(",", "X").replace(
            ".",
            ",",
        ).replace("X", ".")

    @classmethod
    def _formatar_volume(cls, value: Any) -> str:
        try:
            numero = float(value)
        except (TypeError, ValueError):
            return "N/D"

        for divisor, sufixo in (
            (1_000_000_000, "B"),
            (1_000_000, "M"),
            (1_000, "K"),
        ):
            if abs(numero) >= divisor:
                return "$" + cls._formatar_numero(
                    numero / divisor,
                ) + sufixo

        return "$" + cls._formatar_numero(numero)

    def _formatar_data(
        self,
        value: Any,
    ) -> str:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(
                    value.replace("Z", "+00:00"),
                )
            except ValueError:
                return "N/D"

        if not isinstance(value, datetime):
            return "N/D"

        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(
            self.app_timezone,
        ).strftime("%d/%m/%Y %H:%M")


telegram_service = TelegramService()
