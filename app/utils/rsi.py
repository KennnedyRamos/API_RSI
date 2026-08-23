# app/utils/rsi.py

from __future__ import annotations

from typing import Sequence


def calcular_rsi_wilder(
    closes: Sequence[float],
    periodo: int = 14,
) -> float:

    if periodo <= 0:
        raise ValueError(
            "O período do RSI deve ser maior que zero."
        )

    if len(closes) < periodo + 1:
        raise ValueError(
            "Dados insuficientes para calcular RSI."
        )

    valores = [
        float(valor)
        for valor in closes
    ]

    ganhos = []
    perdas = []

    for i in range(1, len(valores)):

        diferenca = (
            valores[i]
            - valores[i - 1]
        )

        if diferenca > 0:

            ganhos.append(diferenca)
            perdas.append(0.0)

        else:

            ganhos.append(0.0)
            perdas.append(abs(diferenca))

    ganho_medio = (
        sum(ganhos[:periodo])
        / periodo
    )

    perda_media = (
        sum(perdas[:periodo])
        / periodo
    )

    for i in range(
        periodo,
        len(ganhos),
    ):

        ganho_medio = (
            (
                ganho_medio
                * (periodo - 1)
            )
            + ganhos[i]
        ) / periodo

        perda_media = (
            (
                perda_media
                * (periodo - 1)
            )
            + perdas[i]
        ) / periodo

    if perda_media == 0:

        if ganho_medio == 0:
            return 50.0

        return 100.0

    rs = (
        ganho_medio
        / perda_media
    )

    rsi = (
        100
        - (
            100
            / (1 + rs)
        )
    )

    return round(
        max(
            0.0,
            min(
                100.0,
                rsi,
            ),
        ),
        2,
    )


def calcular_rsi_anterior(
    closes: Sequence[float],
    periodo: int = 14,
) -> float:

    if len(closes) < periodo + 2:
        raise ValueError(
            "Dados insuficientes para RSI anterior."
        )

    return calcular_rsi_wilder(
        closes=closes[:-1],
        periodo=periodo,
    )


def calcular_diferenca_rsi(
    rsi_atual: float,
    rsi_anterior: float,
) -> float:

    return round(
        float(rsi_atual)
        - float(rsi_anterior),
        2,
    )


def classificar_rsi(
    rsi: float,
) -> str:

    rsi = float(rsi)

    if rsi >= 70:
        return "OVERBOUGHT"

    if rsi <= 30:
        return "OVERSOLD"

    return "NORMAL"


def classificar_tipo_sinal(
    rsi: float,
) -> str | None:

    rsi = float(rsi)

    if rsi >= 70:
        return "OVERBOUGHT"

    if rsi <= 30:
        return "OVERSOLD"

    return None


def classificar_nivel_sinal(
    rsi: float,
    rsi_anterior: float,
) -> str:

    rsi = float(rsi)
    rsi_anterior = float(rsi_anterior)

    diferenca = (
        rsi - rsi_anterior
    )

    # ----------------------------------------------------------
    # SOBRECOMPRA
    # ----------------------------------------------------------

    if rsi >= 80:

        return "EXTREME"

    if rsi >= 70:

        if abs(diferenca) >= 3:
            return "STRONG"

        return "MODERATE"

    # ----------------------------------------------------------
    # SOBREVENDA
    # ----------------------------------------------------------

    if rsi <= 20:

        return "EXTREME"

    if rsi <= 30:

        if abs(diferenca) >= 3:
            return "STRONG"

        return "MODERATE"

    return "NORMAL"