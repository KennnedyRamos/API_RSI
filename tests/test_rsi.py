# tests/test_rsi.py

from __future__ import annotations

import pytest

from app.services.rsi_service import RSIService
from app.utils.rsi import (
    calcular_diferenca_rsi,
    calcular_rsi_anterior,
    calcular_rsi_wilder,
    classificar_nivel_sinal,
    classificar_rsi,
    classificar_tipo_sinal,
)

# ==========================================================
# RSI WILDER
# ==========================================================

def test_calcular_rsi_wilder():
    """
    Verifica se o cálculo do RSI retorna um valor válido.
    """

    closes = [
        100.0,
        101.0,
        102.0,
        101.0,
        103.0,
        104.0,
        105.0,
        104.0,
        106.0,
        107.0,
        108.0,
        107.0,
        109.0,
        110.0,
        111.0,
        112.0,
        111.0,
        113.0,
        114.0,
        115.0,
    ]

    resultado = calcular_rsi_wilder(
        closes=closes,
        periodo=14,
    )

    assert resultado is not None

    assert isinstance(
        resultado,
        float,
    )

    assert 0 <= resultado <= 100


# ==========================================================
# RSI ANTERIOR
# ==========================================================

def test_calcular_rsi_anterior():
    """
    Verifica o cálculo do RSI anterior.
    """

    closes = [
        100.0,
        101.0,
        102.0,
        101.0,
        103.0,
        104.0,
        105.0,
        104.0,
        106.0,
        107.0,
        108.0,
        107.0,
        109.0,
        110.0,
        111.0,
        112.0,
        111.0,
        113.0,
        114.0,
        115.0,
    ]

    resultado = calcular_rsi_anterior(
        closes=closes,
        periodo=14,
    )

    assert resultado is not None

    assert isinstance(
        resultado,
        float,
    )

    assert 0 <= resultado <= 100


# ==========================================================
# DIFERENÇA
# ==========================================================

def test_calcular_diferenca_rsi():
    """
    Verifica a diferença entre RSI atual e anterior.
    """

    resultado = calcular_diferenca_rsi(
        rsi_atual=55.31,
        rsi_anterior=52.94,
    )

    assert resultado == pytest.approx(
        2.37,
        abs=0.01,
    )


# ==========================================================
# CLASSIFICAÇÃO RSI
# ==========================================================

@pytest.mark.parametrize(
    "rsi",
    [
        0.0,
        20.0,
        30.0,
        50.0,
        70.0,
        80.0,
        100.0,
    ],
)
def test_classificar_rsi(rsi):
    """
    Garante que a classificação sempre produza
    um status válido.
    """

    resultado = classificar_rsi(
        rsi
    )

    assert resultado is not None

    assert isinstance(
        resultado,
        str,
    )


# ==========================================================
# TIPO DO SINAL
# ==========================================================

def test_classificar_tipo_sinal_normal():
    """
    RSI em região normal não deve gerar sinal.
    """

    resultado = classificar_tipo_sinal(
        55.31
    )

    assert resultado is None


def test_classificar_tipo_sinal_overbought():
    """
    RSI alto deve gerar sinal de sobrecompra.
    """

    resultado = classificar_tipo_sinal(
        75.0
    )

    assert resultado == "OVERBOUGHT"


def test_classificar_tipo_sinal_oversold():
    """
    RSI baixo deve gerar sinal de sobrevenda.
    """

    resultado = classificar_tipo_sinal(
        25.0
    )

    assert resultado == "OVERSOLD"


# ==========================================================
# NÍVEL DO SINAL
# ==========================================================

def test_classificar_nivel_sinal_normal():
    """
    RSI normal deve resultar em nível NORMAL.
    """

    resultado = classificar_nivel_sinal(
        rsi=55.31,
        rsi_anterior=52.94,
    )

    assert resultado == "NORMAL"


# ==========================================================
# VALIDAÇÃO DE ENTRADA
# ==========================================================

def test_rsi_insuficiente():
    """
    Verifica se o cálculo rejeita quantidade insuficiente
    de candles.
    """

    closes = [
        100.0,
        101.0,
        102.0,
    ]

    with pytest.raises(
        (ValueError, Exception)
    ):

        calcular_rsi_wilder(
            closes=closes,
            periodo=14,
        )


# ==========================================================
# RSI EM TEMPO REAL PARA ALERTAS
# ==========================================================

def test_obter_rsi_atuais_usa_apenas_candle_fechado():
    """O candle em forma\u00e7\u00e3o n\u00e3o pode alterar o RSI do alerta."""

    closes = [
        100.0 + ((indice % 5) - 2) * 1.5
        for indice in range(RSIService.CANDLES_NECESSARIOS - 1)
    ]
    closes.append(1_000.0)
    candles = [
        [indice, close, close, close, close, 0.0]
        for indice, close in enumerate(closes)
    ]

    class BinanceFake:
        def __init__(self):
            self.calls = []

        @staticmethod
        def validar_symbol(symbol):
            return symbol

        def get_ohlcv(self, *, symbol, timeframe, limit):
            self.calls.append((symbol, timeframe, limit))
            return candles

    binance = BinanceFake()
    service = RSIService(binance=binance)

    valores = service.obter_rsi_atuais(
        symbol="BTC/USDT",
        intervalos=("5m", "1h"),
    )

    esperado = calcular_rsi_wilder(
        closes=closes[:-1],
        periodo=RSIService.PERIODO_RSI,
    )
    assert valores == {"5m": esperado, "1h": esperado}
    assert binance.calls == [
        ("BTC/USDT", "5m", RSIService.CANDLES_NECESSARIOS),
        ("BTC/USDT", "1h", RSIService.CANDLES_NECESSARIOS),
    ]
