# database/repositories/rsi_repository.py

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import case, desc, func

from app import db
from database.models.rsi import RSIData
from database.models.rsi_snapshot import RSISnapshot


logger = logging.getLogger(__name__)


class RSIRepository:
    """
    Repository responsável pelo acesso aos dados de RSI.

    Centraliza:

        - INSERT
        - UPDATE
        - DELETE
        - consultas
        - histórico
        - sinais
        - ranking
        - contagem
    """

    # ==========================================================
    # CREATE
    # ==========================================================

    @staticmethod
    def criar(
        symbol: str,
        intervalo: str,
        rsi: float,
        timestamp: datetime,
        rsi_previous: Optional[float] = None,
        rsi_difference: Optional[float] = None,
        rsi_status: str = "NORMAL",
        signal_type: Optional[str] = None,
        signal_level: str = "NORMAL",
        current_price: float = 0.0,
        change_24h: Optional[float] = None,
        volume_24h: Optional[float] = None,
        market_cap: Optional[float] = None,
        ranking: Optional[int] = None,
    ) -> RSIData:

        try:

            registro = RSIData(
                symbol=symbol,
                intervalo=intervalo,
                rsi=float(rsi),
                rsi_previous=(
                    float(rsi_previous)
                    if rsi_previous is not None
                    else None
                ),
                rsi_difference=(
                    float(rsi_difference)
                    if rsi_difference is not None
                    else None
                ),
                timestamp=timestamp,
                rsi_status=rsi_status,
                signal_type=signal_type,
                signal_level=signal_level,
                current_price=float(current_price),
                change_24h=(
                    float(change_24h)
                    if change_24h is not None
                    else None
                ),
                volume_24h=(
                    float(volume_24h)
                    if volume_24h is not None
                    else None
                ),
                market_cap=(
                    float(market_cap)
                    if market_cap is not None
                    else None
                ),
                ranking=(
                    int(ranking)
                    if ranking is not None
                    else None
                ),
            )

            db.session.add(registro)
            db.session.commit()

            return registro

        except Exception:

            db.session.rollback()

            logger.exception(
                "Erro ao criar RSI | %s | %s",
                symbol,
                intervalo,
            )

            raise

    # ==========================================================
    # FIND BY ID
    # ==========================================================

    @staticmethod
    def buscar_por_id(
        registro_id: int,
    ) -> Optional[RSIData]:

        return (
            RSIData.query
            .filter(
                RSIData.id == registro_id
            )
            .first()
        )

    # ==========================================================
    # FIND BY CANDLE
    # ==========================================================

    @staticmethod
    def buscar_por_candle(
        symbol: str,
        intervalo: str,
        timestamp: datetime,
    ) -> Optional[RSIData]:

        return (
            RSIData.query
            .filter(
                RSIData.symbol == symbol,
                RSIData.intervalo == intervalo,
                RSIData.timestamp == timestamp,
            )
            .first()
        )

    # ==========================================================
    # EXISTS
    # ==========================================================

    @staticmethod
    def existe(
        symbol: str,
        intervalo: str,
        timestamp: datetime,
    ) -> bool:

        return (
            RSIRepository.buscar_por_candle(
                symbol,
                intervalo,
                timestamp,
            )
            is not None
        )

    # ==========================================================
    # ÚLTIMO
    # ==========================================================

    @staticmethod
    def buscar_ultimo(
        symbol: str,
        intervalo: str,
    ) -> Optional[RSIData]:

        return (
            RSIData.query
            .filter(
                RSIData.symbol == symbol,
                RSIData.intervalo == intervalo,
            )
            .order_by(
                desc(RSIData.timestamp)
            )
            .first()
        )

    # ==========================================================
    # ÚLTIMOS REGISTROS
    # ==========================================================

    @staticmethod
    def buscar_ultimos(
        limite: int = 20,
        intervalo: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> list[RSIData]:

        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        query = RSIData.query

        if intervalo:
            query = query.filter(
                RSIData.intervalo == intervalo
            )

        if symbol:
            query = query.filter(
                RSIData.symbol == symbol
            )

        return (
            query
            .order_by(
                desc(RSIData.timestamp),
                desc(RSIData.id),
            )
            .limit(limite)
            .all()
        )

    # ==========================================================
    # ANTERIOR
    # ==========================================================

    @staticmethod
    def buscar_anterior(
        symbol: str,
        intervalo: str,
        timestamp: datetime,
    ) -> Optional[RSIData]:

        return (
            RSIData.query
            .filter(
                RSIData.symbol == symbol,
                RSIData.intervalo == intervalo,
                RSIData.timestamp < timestamp,
            )
            .order_by(
                desc(RSIData.timestamp)
            )
            .first()
        )

    # ==========================================================
    # HISTÓRICO
    # ==========================================================

    @staticmethod
    def buscar_historico(
        symbol: str,
        intervalo: str,
        limite: int = 100,
    ) -> list[RSIData]:

        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        return (
            RSIData.query
            .filter(
                RSIData.symbol == symbol,
                RSIData.intervalo == intervalo,
            )
            .order_by(
                desc(RSIData.timestamp)
            )
            .limit(limite)
            .all()
        )

    # ==========================================================
    # HISTÓRICO CRONOLÓGICO PARA GRÁFICOS
    # ==========================================================

    @staticmethod
    def buscar_historico_grafico(
        symbol: str,
        intervalo: str,
        limite: int = 200,
    ) -> list[RSIData]:
        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        registros = (
            RSIData.query
            .filter(
                RSIData.symbol == symbol,
                RSIData.intervalo == intervalo,
            )
            .order_by(
                desc(RSIData.timestamp),
                desc(RSIData.id),
            )
            .limit(limite)
            .all()
        )

        return list(reversed(registros))

    # ==========================================================
    # SINAIS ATUAIS POR PAR
    # ==========================================================

    @staticmethod
    def buscar_sinais_atuais(
        *,
        intervalo: Optional[str] = None,
        symbol: Optional[str] = None,
        signal_type: Optional[str] = None,
        signal_level: Optional[str] = None,
        limite: int = 100,
    ) -> list[RSIData]:
        """Retorna no máximo um estado atual por par/timeframe."""

        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        nivel_peso = case(
            (RSIData.signal_level == "EXTREME", 3),
            (RSIData.signal_level == "STRONG", 2),
            (RSIData.signal_level == "MODERATE", 1),
            else_=0,
        )

        query = (
            RSIData.query
            .join(
                RSISnapshot,
                RSISnapshot.rsi_data_id == RSIData.id,
            )
            .filter(
                RSIData.signal_type.isnot(None),
            )
        )

        if intervalo:
            query = query.filter(
                RSISnapshot.intervalo == intervalo,
            )

        if symbol:
            query = query.filter(
                RSISnapshot.symbol == symbol,
            )

        if signal_type:
            query = query.filter(
                RSIData.signal_type == signal_type,
            )

        if signal_level:
            query = query.filter(
                RSIData.signal_level == signal_level,
            )

        return (
            query
            .order_by(
                nivel_peso.desc(),
                func.abs(RSIData.rsi_difference).desc(),
                RSIData.ranking.asc().nullslast(),
                desc(RSIData.timestamp),
            )
            .limit(limite)
            .all()
        )

    # ==========================================================
    # SÍMBOLOS PARA BUSCA
    # ==========================================================

    @staticmethod
    def buscar_symbols(
        *,
        termo: Optional[str] = None,
        limite: int = 30,
    ) -> list[str]:
        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        query = db.session.query(
            RSIData.symbol,
        ).distinct()

        if termo:
            query = query.filter(
                RSIData.symbol.ilike(
                    f"%{termo.upper()}%"
                )
            )

        return [
            row[0]
            for row in (
                query
                .order_by(RSIData.symbol.asc())
                .limit(limite)
                .all()
            )
        ]

    # ==========================================================
    # POR INTERVALO
    # ==========================================================

    @staticmethod
    def buscar_por_intervalo(
        intervalo: str,
        limite: int = 100,
    ) -> list[RSIData]:

        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        return (
            RSIData.query
            .filter(
                RSIData.intervalo == intervalo
            )
            .order_by(
                desc(RSIData.timestamp)
            )
            .limit(limite)
            .all()
        )

    # ==========================================================
    # POR SÍMBOLO
    # ==========================================================

    @staticmethod
    def buscar_por_symbol(
        symbol: str,
        limite: int = 100,
    ) -> list[RSIData]:

        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        return (
            RSIData.query
            .filter(
                RSIData.symbol == symbol
            )
            .order_by(
                desc(RSIData.timestamp)
            )
            .limit(limite)
            .all()
        )

    # ==========================================================
    # SINAIS
    # ==========================================================

    @staticmethod
    def buscar_sinais(
        intervalo: Optional[str] = None,
        signal_type: Optional[str] = None,
        signal_level: Optional[str] = None,
        limite: int = 100,
    ) -> list[RSIData]:

        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        query = RSIData.query.filter(
            RSIData.signal_type.isnot(None)
        )

        if intervalo:
            query = query.filter(
                RSIData.intervalo == intervalo
            )

        if signal_type:
            query = query.filter(
                RSIData.signal_type == signal_type
            )

        if signal_level:
            query = query.filter(
                RSIData.signal_level == signal_level
            )

        return (
            query
            .order_by(
                desc(RSIData.timestamp)
            )
            .limit(limite)
            .all()
        )

    # ==========================================================
    # SOBRECOMPRA
    # ==========================================================

    @staticmethod
    def buscar_sobrecompra(
        intervalo: Optional[str] = None,
        limite: int = 100,
    ) -> list[RSIData]:

        return RSIRepository.buscar_sinais(
            intervalo=intervalo,
            signal_type="OVERBOUGHT",
            limite=limite,
        )

    # ==========================================================
    # SOBREVENDA
    # ==========================================================

    @staticmethod
    def buscar_sobrevenda(
        intervalo: Optional[str] = None,
        limite: int = 100,
    ) -> list[RSIData]:

        return RSIRepository.buscar_sinais(
            intervalo=intervalo,
            signal_type="OVERSOLD",
            limite=limite,
        )

    # ==========================================================
    # SINAIS RECENTES
    # ==========================================================

    @staticmethod
    def buscar_sinais_recentes(
        intervalo: Optional[str] = None,
        limite: int = 20,
    ) -> list[RSIData]:

        return RSIRepository.buscar_sinais(
            intervalo=intervalo,
            limite=limite,
        )

    # ==========================================================
    # ÚLTIMO SINAL
    # ==========================================================

    @staticmethod
    def buscar_ultimo_sinal(
        symbol: str,
        intervalo: Optional[str] = None,
    ) -> Optional[RSIData]:

        query = RSIData.query.filter(
            RSIData.symbol == symbol,
            RSIData.signal_type.isnot(None),
        )

        if intervalo:
            query = query.filter(
                RSIData.intervalo == intervalo
            )

        return (
            query
            .order_by(
                desc(RSIData.timestamp)
            )
            .first()
        )

    # ==========================================================
    # RANKING
    # ==========================================================

    @staticmethod
    def buscar_ranking(
        intervalo: Optional[str] = None,
        limite: int = 20,
    ) -> list[RSIData]:

        if limite <= 0:
            raise ValueError(
                "O limite deve ser maior que zero."
            )

        query = RSIData.query

        if intervalo:
            query = query.filter(
                RSIData.intervalo == intervalo
            )

        return (
            query
            .filter(
                RSIData.ranking.isnot(None)
            )
            .order_by(
                RSIData.ranking.asc(),
                desc(RSIData.timestamp),
            )
            .limit(limite)
            .all()
        )

    # ==========================================================
    # UPDATE
    # ==========================================================

    @staticmethod
    def atualizar(
        registro: RSIData,
        **dados,
    ) -> RSIData:

        try:

            campos_protegidos = {
                "id",
                "created_at",
                "updated_at",
            }

            for campo, valor in dados.items():

                if campo in campos_protegidos:
                    raise ValueError(
                        f"Campo protegido: {campo}"
                    )

                if not hasattr(
                    registro,
                    campo,
                ):
                    raise ValueError(
                        f"Campo inválido para RSIData: "
                        f"{campo}"
                    )

                setattr(
                    registro,
                    campo,
                    valor,
                )

            db.session.commit()

            return registro

        except Exception:

            db.session.rollback()

            logger.exception(
                "Erro ao atualizar RSI | id=%s",
                getattr(registro, "id", None),
            )

            raise

    # ==========================================================
    # DELETE
    # ==========================================================

    @staticmethod
    def deletar(
        registro: RSIData,
    ) -> None:

        try:

            db.session.delete(registro)
            db.session.commit()

        except Exception:

            db.session.rollback()

            logger.exception(
                "Erro ao remover RSI | id=%s",
                getattr(registro, "id", None),
            )

            raise

    # ==========================================================
    # COUNT
    # ==========================================================

    @staticmethod
    def contar(
        symbol: Optional[str] = None,
        intervalo: Optional[str] = None,
        signal_type: Optional[str] = None,
        signal_level: Optional[str] = None,
    ) -> int:

        query = RSIData.query

        if symbol:
            query = query.filter(
                RSIData.symbol == symbol
            )

        if intervalo:
            query = query.filter(
                RSIData.intervalo == intervalo
            )

        if signal_type:
            query = query.filter(
                RSIData.signal_type == signal_type
            )

        if signal_level:
            query = query.filter(
                RSIData.signal_level == signal_level
            )

        return query.count()
