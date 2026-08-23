
from __future__ import annotations

from app import db


class RSIData(db.Model):
    """
    Modelo responsável por armazenar os dados calculados
    de RSI e informações complementares do mercado.

    A identificação lógica de um candle é:

        symbol
        intervalo
        timestamp

    Essa combinação possui uma constraint UNIQUE.
    """

    __tablename__ = "rsi_data"

    # ==========================================================
    # IDENTIFICAÇÃO
    # ==========================================================

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    symbol = db.Column(
        db.String(30),
        nullable=False,
    )

    intervalo = db.Column(
        db.String(10),
        nullable=False,
    )

    # ==========================================================
    # RSI
    # ==========================================================

    rsi = db.Column(
        db.Float,
        nullable=False,
    )

    rsi_previous = db.Column(
        db.Float,
        nullable=True,
    )

    rsi_difference = db.Column(
        db.Float,
        nullable=True,
    )

    # ==========================================================
    # TEMPO
    # ==========================================================

    timestamp = db.Column(
        db.DateTime,
        nullable=False,
    )

    # ==========================================================
    # CLASSIFICAÇÃO
    # ==========================================================

    rsi_status = db.Column(
        db.String(30),
        nullable=False,
        default="NORMAL",
        server_default="NORMAL",
    )

    signal_type = db.Column(
        db.String(30),
        nullable=True,
    )

    signal_level = db.Column(
        db.String(30),
        nullable=False,
        default="NORMAL",
        server_default="NORMAL",
    )

    # ==========================================================
    # DADOS DA BINANCE
    # ==========================================================

    current_price = db.Column(
        db.Float,
        nullable=False,
        default=0.0,
        server_default="0",
    )

    change_24h = db.Column(
        db.Float,
        nullable=True,
    )

    volume_24h = db.Column(
        db.Float,
        nullable=True,
    )

    # ==========================================================
    # MARKET DATA
    # ==========================================================

    market_cap = db.Column(
        db.Float,
        nullable=True,
    )

    ranking = db.Column(
        db.Integer,
        nullable=True,
    )

    # ==========================================================
    # AUDITORIA
    # ==========================================================

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

    # ==========================================================
    # CONSTRAINTS E ÍNDICES
    # ==========================================================

    __table_args__ = (

        # ------------------------------------------------------
        # Índices legados mantidos para compatibilidade com as
        # migrações iniciais e consultas pontuais.
        # ------------------------------------------------------

        db.Index(
            "ix_rsi_data_symbol",
            "symbol",
        ),

        db.Index(
            "ix_rsi_data_intervalo",
            "intervalo",
        ),

        db.Index(
            "ix_rsi_data_signal_type",
            "signal_type",
        ),

        db.Index(
            "ix_rsi_data_timestamp",
            "timestamp",
        ),

        db.Index(
            "ix_rsi_data_ranking",
            "ranking",
        ),

        # ------------------------------------------------------
        # Um candle não pode ser duplicado.
        # ------------------------------------------------------

        db.UniqueConstraint(
            "symbol",
            "intervalo",
            "timestamp",
            name="uq_rsi_symbol_intervalo_timestamp",
        ),

        # ------------------------------------------------------
        # Histórico por símbolo/timeframe.
        # ------------------------------------------------------

        db.Index(
            "ix_rsi_symbol_intervalo_timestamp",
            "symbol",
            "intervalo",
            "timestamp",
        ),

        # ------------------------------------------------------
        # Consultas de sinais.
        # ------------------------------------------------------

        db.Index(
            "ix_rsi_signal_intervalo_timestamp",
            "signal_type",
            "intervalo",
            "timestamp",
        ),

        # ------------------------------------------------------
        # Consultas por nível de sinal.
        # ------------------------------------------------------

        db.Index(
            "ix_rsi_level_intervalo_timestamp",
            "signal_level",
            "intervalo",
            "timestamp",
        ),

        # ------------------------------------------------------
        # Ranking / Market Cap.
        # ------------------------------------------------------

        db.Index(
            "ix_rsi_market_cap",
            "market_cap",
        ),

        db.Index(
            "ix_rsi_ranking",
            "ranking",
        ),

    )

    # ==========================================================
    # REPRESENTAÇÃO
    # ==========================================================

    def __repr__(self) -> str:

        return (
            f"<RSIData "
            f"id={self.id} "
            f"symbol={self.symbol} "
            f"intervalo={self.intervalo} "
            f"rsi={self.rsi} "
            f"timestamp={self.timestamp}>"
        )
