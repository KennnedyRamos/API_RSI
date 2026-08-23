"""Rótulos de apresentação para os níveis internos de sinal RSI."""

from typing import Final


SIGNAL_LEVEL_LABELS: Final[dict[str, str]] = {
    "NORMAL": "Normal",
    "MODERATE": "Moderado",
    "STRONG": "Forte",
    "EXTREME": "Extremo",
}


def rotulo_nivel_sinal(value: object) -> str:
    """Retorna o rótulo pt-BR sem alterar o código persistido."""
    if value is None:
        return SIGNAL_LEVEL_LABELS["NORMAL"]

    codigo = str(value).strip().upper()
    if not codigo:
        return SIGNAL_LEVEL_LABELS["NORMAL"]

    return SIGNAL_LEVEL_LABELS.get(codigo, "Não classificado")
