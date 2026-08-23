"""Constantes e rótulos compartilhados dos períodos de RSI."""

from __future__ import annotations


# A ordem também é usada na mensagem do Telegram, do menor para o maior.
RSI_TIMEFRAMES = (
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "12h",
    "1d",
    "1w",
    "1M",
)


def rotulo_timeframe(intervalo: object) -> str:
    """Exibe semanal como ``1W`` sem alterar o código interno ``1w``."""

    valor = str(intervalo).strip()
    return "1W" if valor.lower() == "1w" else valor
