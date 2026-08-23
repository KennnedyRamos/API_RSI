from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from flask import jsonify, render_template, request
from sqlalchemy import text
from sqlalchemy.exc import (
    OperationalError,
    ProgrammingError,
    SQLAlchemyError,
)

from app import db
from app.utils.signal_levels import rotulo_nivel_sinal
from database.repositories.rsi_repository import RSIRepository
from services.binance_service import BinanceService, binance_service

import logging


logger = logging.getLogger(__name__)


# ==============================================================
# BLUEPRINT
# ==============================================================

DEFAULT_INTERVALO = "1h"

DEFAULT_LIMITE = 20

LIMITE_MINIMO = 1

LIMITE_MAXIMO = 500


# ==============================================================
# HELPERS
# ==============================================================

def _obter_intervalo() -> str:
    """
    Obtém o timeframe informado na query string.

    Exemplo:

        ?intervalo=1h
    """

    intervalo = request.args.get("intervalo")

    if intervalo is None:
        intervalo = request.args.get(
            "timeframe",
            DEFAULT_INTERVALO,
        )

    intervalo = intervalo.strip()

    if not intervalo:
        intervalo = DEFAULT_INTERVALO

    if intervalo not in BinanceService.TIMEFRAMES_PERMITIDOS:
        raise ValueError(
            "Timeframe inválido: "
            f"{intervalo}. Permitidos: "
            f"{', '.join(BinanceService.TIMEFRAMES_PERMITIDOS)}."
        )

    return intervalo


def _obter_limite(
    default: int = DEFAULT_LIMITE,
) -> int:
    """
    Obtém e valida o limite de registros.

    Exemplo:

        ?limite=20
    """

    valor = request.args.get("limite")

    if valor is None:
        valor = request.args.get(
            "limit",
            str(default),
        )

    try:
        limite = int(valor)

    except (TypeError, ValueError):

        raise ValueError(
            "O parâmetro 'limite' deve ser um número inteiro."
        )

    if limite < LIMITE_MINIMO:

        raise ValueError(
            f"O parâmetro 'limite' deve ser "
            f"maior ou igual a {LIMITE_MINIMO}."
        )

    if limite > LIMITE_MAXIMO:

        raise ValueError(
            f"O parâmetro 'limite' não pode ser "
            f"maior que {LIMITE_MAXIMO}."
        )

    return limite


def _serializar_datetime(
    value: Any,
) -> Any:
    """
    Converte datetime para ISO 8601.
    """

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.isoformat()

    return value


def _serializar_rsi(
    registro: Any,
) -> dict[str, Any]:
    """
    Converte RSIData em JSON.

    A função aceita tanto uma instância
    do modelo quanto um dicionário.
    """

    if registro is None:

        return {}

    # ==========================================================
    # DICIONÁRIO
    # ==========================================================

    if isinstance(
        registro,
        dict,
    ):

        resultado = dict(registro)

        if "timestamp" in resultado:

            resultado["timestamp"] = (
                _serializar_datetime(
                    resultado["timestamp"]
                )
            )

        if "created_at" in resultado:

            resultado["created_at"] = (
                _serializar_datetime(
                    resultado["created_at"]
                )
            )

        if "updated_at" in resultado:

            resultado["updated_at"] = (
                _serializar_datetime(
                    resultado["updated_at"]
                )
            )

        resultado["signal_level_label"] = rotulo_nivel_sinal(
            resultado.get("signal_level")
        )

        return resultado

    # ==========================================================
    # MODELO SQLALCHEMY
    # ==========================================================

    resultado = {

        "id": getattr(
            registro,
            "id",
            None,
        ),

        "symbol": getattr(
            registro,
            "symbol",
            None,
        ),

        "intervalo": getattr(
            registro,
            "intervalo",
            None,
        ),

        "rsi": getattr(
            registro,
            "rsi",
            None,
        ),

        "rsi_previous": getattr(
            registro,
            "rsi_previous",
            None,
        ),

        "rsi_difference": getattr(
            registro,
            "rsi_difference",
            None,
        ),

        "timestamp": getattr(
            registro,
            "timestamp",
            None,
        ),

        "rsi_status": getattr(
            registro,
            "rsi_status",
            None,
        ),

        "signal_type": getattr(
            registro,
            "signal_type",
            None,
        ),

        "signal_level": getattr(
            registro,
            "signal_level",
            None,
        ),

        "current_price": getattr(
            registro,
            "current_price",
            None,
        ),

        "change_24h": getattr(
            registro,
            "change_24h",
            None,
        ),

        "volume_24h": getattr(
            registro,
            "volume_24h",
            None,
        ),

        "market_cap": getattr(
            registro,
            "market_cap",
            None,
        ),

        "ranking": getattr(
            registro,
            "ranking",
            None,
        ),

        "created_at": getattr(
            registro,
            "created_at",
            None,
        ),

        "updated_at": getattr(
            registro,
            "updated_at",
            None,
        ),
    }

    resultado["timestamp"] = (
        _serializar_datetime(
            resultado["timestamp"]
        )
    )

    resultado["created_at"] = (
        _serializar_datetime(
            resultado["created_at"]
        )
    )

    resultado["updated_at"] = (
        _serializar_datetime(
            resultado["updated_at"]
        )
    )

    resultado["signal_level_label"] = rotulo_nivel_sinal(
        resultado["signal_level"]
    )

    return resultado


def _serializar_lista(
    registros: list[Any],
) -> list[dict[str, Any]]:
    """
    Serializa uma lista de registros RSI.
    """

    return [
        _serializar_rsi(
            registro
        )
        for registro in registros
    ]


def _resposta_erro(
    mensagem: str,
    status_code: int = 400,
    **extra: Any,
):
    """
    Padroniza respostas de erro.
    """

    payload = {

        "success": False,

        "error": mensagem,

    }

    payload.update(extra)

    return jsonify(payload), status_code


# ==============================================================
# HOME
# ==============================================================

def home():
    """
    Rota inicial.
    """

    return jsonify(
        {
            "service": "API RSI",
            "status": "online",
            "success": True,
            "version": "v1",
        }
    )


# ==============================================================
# HEALTH
# ==============================================================

def api_health():
    """
    Health check da API.
    """

    return jsonify(
        {
            "service": "API RSI",
            "status": "online",
            "success": True,
            "version": "v1",
        }
    )


# ==============================================================
def api_readiness():
    """Confirma que a API consegue consultar o banco de dados."""

    try:
        db.session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        db.session.rollback()
        logger.exception("Health check de prontidão falhou no banco.")
        return jsonify(
            {
                "service": "API RSI",
                "status": "unavailable",
                "success": False,
                "database": "unavailable",
            }
        ), 503

    return jsonify(
        {
            "service": "API RSI",
            "status": "ready",
            "success": True,
            "database": "online",
        }
    )


# GET /api/v1/rsi/<symbol>
# ==============================================================

def api_rsi_symbol(
    symbol: str,
):
    """
    Consulta o último RSI salvo para determinado símbolo
    e timeframe.

    Esta rota consulta exclusivamente o PostgreSQL.

    Exemplos:

        GET /api/v1/rsi/BTCUSDT?intervalo=1h

        GET /api/v1/rsi/BTC%2FUSDT?intervalo=1h
    """

    inicio = perf_counter()

    try:

        intervalo = _obter_intervalo()

        # ==========================================================
        # NORMALIZAÇÃO DO SÍMBOLO
        # ==========================================================

        try:

            symbol = binance_service.validar_symbol(
                symbol
            )

        except ValueError as exc:

            return _resposta_erro(
                str(exc),
                400,
            )

        logger.debug(
            "Consulta RSI PostgreSQL | "
            "symbol=%s | intervalo=%s",
            symbol,
            intervalo,
        )

        # ==========================================================
        # SOMENTE POSTGRESQL
        # ==========================================================

        registro = (
            RSIRepository.buscar_ultimo(
                symbol=symbol,
                intervalo=intervalo,
            )
        )

        # ==========================================================
        # NÃO ENCONTRADO
        # ==========================================================

        if registro is None:

            return _resposta_erro(
                (
                    f"Nenhum RSI encontrado para "
                    f"{symbol} no intervalo {intervalo}."
                ),
                404,
            )

        # ==========================================================
        # SERIALIZAÇÃO
        # ==========================================================

        data = _serializar_rsi(
            registro
        )

        tempo_execucao = round(
            perf_counter() - inicio,
            4,
        )

        return jsonify(
            {
                "success": True,
                "data": data,
                "tempo_execucao": tempo_execucao,
            }
        )

    except ValueError as exc:

        return _resposta_erro(
            str(exc),
            400,
        )

    except Exception:

        logger.exception(
            "Erro ao consultar RSI | "
            "symbol=%s",
            symbol,
        )

        return _resposta_erro(
            "Erro interno ao consultar RSI.",
            500,
        )


# ==============================================================
# GET /api/v1/rsi
# ==============================================================

def api_rsi():
    """
    Consulta RSI diretamente do PostgreSQL.

    NÃO executa processamento.

    Exemplo:

        GET /api/v1/rsi?intervalo=1h&limite=20
    """

    inicio = perf_counter()

    try:

        intervalo = _obter_intervalo()

        limite = _obter_limite()

        logger.debug(
            "Consulta RSI | "
            "intervalo=%s | limite=%s",
            intervalo,
            limite,
        )

        registros = (
            RSIRepository.buscar_por_intervalo(
                intervalo=intervalo,
                limite=limite,
            )
        )

        data = _serializar_lista(
            registros
        )

        tempo_execucao = round(
            perf_counter() - inicio,
            4,
        )

        return jsonify(
            {
                "success": True,
                "intervalo": intervalo,
                "results": data,
                "total": len(data),
                "tempo_execucao": tempo_execucao,
            }
        )

    except ValueError as exc:

        return _resposta_erro(
            str(exc),
            400,
        )

    except Exception:

        logger.exception(
            "Erro ao consultar RSI | "
            "intervalo=%s",
            _obter_intervalo(),
        )

        return _resposta_erro(
            "Erro interno ao consultar RSI.",
            500,
        )


# ==============================================================
# GET /api/v1/rsi/all
# ==============================================================

def api_rsi_all():
    """
    Consulta os registros RSI mais recentes
    diretamente do PostgreSQL.

    Não processa Binance.

    Não consulta CoinGecko.

    Exemplo:

        GET /api/v1/rsi/all?limite=100
    """

    inicio = perf_counter()

    try:

        limite = _obter_limite()

        intervalo = request.args.get(
            "intervalo"
        )

        if intervalo:

            intervalo = intervalo.strip()

        logger.debug(
            "Consulta RSI ALL | "
            "intervalo=%s | limite=%s",
            intervalo,
            limite,
        )

        if intervalo:

            registros = (
                RSIRepository.buscar_por_intervalo(
                    intervalo=intervalo,
                    limite=limite,
                )
            )

        else:

            registros = (
                RSIRepository.buscar_ultimos(
                    limite=limite,
                )
            )

        data = _serializar_lista(
            registros
        )

        tempo_execucao = round(
            perf_counter() - inicio,
            4,
        )

        return jsonify(
            {
                "success": True,
                "results": data,
                "total": len(data),
                "tempo_execucao": tempo_execucao,
            }
        )

    except ValueError as exc:

        return _resposta_erro(
            str(exc),
            400,
        )

    except Exception:

        logger.exception(
            "Erro ao consultar todos os RSI.",
        )

        return _resposta_erro(
            "Erro interno ao consultar RSI.",
            500,
        )


# ==============================================================
# GET /api/v1/signals
# ==============================================================

def api_signals():
    """
    Consulta sinais RSI diretamente do PostgreSQL.

    Exemplo:

        GET /api/v1/signals?intervalo=1h&limite=20
    """

    inicio = perf_counter()

    try:

        intervalo = _obter_intervalo()

        limite = _obter_limite()

        logger.debug(
            "Consulta sinais RSI | "
            "intervalo=%s | limite=%s",
            intervalo,
            limite,
        )

        registros = (
            RSIRepository.buscar_sinais(
                intervalo=intervalo,
                limite=limite,
            )
        )

        data = _serializar_lista(
            registros
        )

        tempo_execucao = round(
            perf_counter() - inicio,
            4,
        )

        return jsonify(
            {
                "success": True,
                "results": data,
                "total": len(data),
                "tempo_execucao": tempo_execucao,
            }
        )

    except ValueError as exc:

        return _resposta_erro(
            str(exc),
            400,
        )

    except Exception:

        logger.exception(
            "Erro ao consultar sinais RSI.",
        )

        return _resposta_erro(
            "Erro interno ao consultar sinais.",
            500,
        )


# ==============================================================
# GET /api/v1/signals/overbought
# ==============================================================

def api_overbought():
    """
    Consulta sinais de sobrecompra.

    SOMENTE PostgreSQL.
    """

    inicio = perf_counter()

    try:

        intervalo = _obter_intervalo()

        limite = _obter_limite()

        logger.debug(
            "Consulta sinais OVERBOUGHT | "
            "intervalo=%s | limite=%s",
            intervalo,
            limite,
        )

        registros = (
            RSIRepository.buscar_sobrecompra(
                intervalo=intervalo,
                limite=limite,
            )
        )

        data = _serializar_lista(
            registros
        )

        tempo_execucao = round(
            perf_counter() - inicio,
            4,
        )

        return jsonify(
            {
                "success": True,
                "signal_type": "OVERBOUGHT",
                "results": data,
                "total": len(data),
                "tempo_execucao": tempo_execucao,
            }
        )

    except ValueError as exc:

        return _resposta_erro(
            str(exc),
            400,
        )

    except Exception:

        logger.exception(
            "Erro ao consultar sinais "
            "de sobrecompra.",
        )

        return _resposta_erro(
            "Erro interno ao consultar sobrecompra.",
            500,
        )


# ==============================================================
# GET /api/v1/signals/oversold
# ==============================================================

def api_oversold():
    """
    Consulta sinais de sobrevenda.

    SOMENTE PostgreSQL.
    """

    inicio = perf_counter()

    try:

        intervalo = _obter_intervalo()

        limite = _obter_limite()

        logger.debug(
            "Consulta sinais OVERSOLD | "
            "intervalo=%s | limite=%s",
            intervalo,
            limite,
        )

        registros = (
            RSIRepository.buscar_sobrevenda(
                intervalo=intervalo,
                limite=limite,
            )
        )

        data = _serializar_lista(
            registros
        )

        tempo_execucao = round(
            perf_counter() - inicio,
            4,
        )

        return jsonify(
            {
                "success": True,
                "signal_type": "OVERSOLD",
                "results": data,
                "total": len(data),
                "tempo_execucao": tempo_execucao,
            }
        )

    except ValueError as exc:

        return _resposta_erro(
            str(exc),
            400,
        )

    except Exception:

        logger.exception(
            "Erro ao consultar sinais "
            "de sobrevenda.",
        )

        return _resposta_erro(
            "Erro interno ao consultar sobrevenda.",
            500,
        )


# ==============================================================
# DASHBOARD E CONSULTAS DE ANÁLISE
# ==============================================================

def dashboard_page():
    """Página web local do painel de sinais."""

    return render_template("dashboard.html")


def api_timeframes():
    """Fonte única de timeframes para clientes web e integrações."""

    return jsonify(
        {
            "success": True,
            "results": list(
                BinanceService.TIMEFRAMES_PERMITIDOS
            ),
        }
    )


def api_symbols():
    """Busca pares já presentes no histórico da aplicação."""

    try:
        termo = request.args.get("q", "").strip()
        limite = _obter_limite(default=30)
        results = RSIRepository.buscar_symbols(
            termo=termo or None,
            limite=limite,
        )

        return jsonify(
            {
                "success": True,
                "results": results,
                "total": len(results),
            }
        )
    except ValueError as exc:
        return _resposta_erro(str(exc), 400)
    except Exception:
        logger.exception("Erro ao buscar pares para o dashboard.")
        return _resposta_erro(
            "Erro interno ao buscar pares.",
            500,
        )


def api_current_signals():
    """Lista apenas o sinal atual de cada par/timeframe.

    Ao contrário de ``/api/v1/signals``, esta rota não mistura candles
    históricos e é a fonte adequada para uma tabela de oportunidades.
    """

    try:
        intervalo = _obter_intervalo()
        limite = _obter_limite(default=100)
        signal_type = (
            request.args.get("tipo")
            or request.args.get("type")
            or ""
        ).strip().upper()
        signal_level = (
            request.args.get("nivel")
            or request.args.get("level")
            or ""
        ).strip().upper()
        symbol = request.args.get("symbol", "").strip()

        if signal_type and signal_type not in {
            "OVERBOUGHT",
            "OVERSOLD",
        }:
            raise ValueError(
                "Tipo de sinal inválido. Use OVERBOUGHT ou OVERSOLD."
            )

        if signal_level and signal_level not in {
            "MODERATE",
            "STRONG",
            "EXTREME",
        }:
            raise ValueError(
                "Nível de sinal inválido. Use MODERATE, STRONG ou EXTREME."
            )

        if symbol:
            symbol = binance_service.validar_symbol(symbol)

        registros = RSIRepository.buscar_sinais_atuais(
            intervalo=intervalo,
            symbol=symbol or None,
            signal_type=signal_type or None,
            signal_level=signal_level or None,
            limite=limite,
        )
        data = _serializar_lista(registros)

        return jsonify(
            {
                "success": True,
                "intervalo": intervalo,
                "results": data,
                "total": len(data),
            }
        )
    except ValueError as exc:
        return _resposta_erro(str(exc), 400)
    except (OperationalError, ProgrammingError):
        logger.exception(
            "Banco ainda não possui a estrutura do painel."
        )
        return _resposta_erro(
            "O banco ainda não foi atualizado para o painel. "
            "Execute 'flask --app main:app db upgrade'.",
            503,
        )
    except Exception:
        logger.exception("Erro ao consultar sinais atuais.")
        return _resposta_erro(
            "Erro interno ao consultar sinais atuais.",
            500,
        )


def api_rsi_history(
    symbol: str,
):
    """Histórico cronológico de RSI usado pelo gráfico do ativo."""

    try:
        symbol = binance_service.validar_symbol(symbol)
        intervalo = _obter_intervalo()
        limite = _obter_limite(default=200)
        registros = RSIRepository.buscar_historico_grafico(
            symbol=symbol,
            intervalo=intervalo,
            limite=limite,
        )
        data = _serializar_lista(registros)

        return jsonify(
            {
                "success": True,
                "symbol": symbol,
                "intervalo": intervalo,
                "results": data,
                "total": len(data),
            }
        )
    except ValueError as exc:
        return _resposta_erro(str(exc), 400)
    except Exception:
        logger.exception(
            "Erro ao consultar histórico RSI | symbol=%s",
            symbol,
        )
        return _resposta_erro(
            "Erro interno ao consultar histórico RSI.",
            500,
        )


def api_market_candles(
    symbol: str,
):
    """Fornece candles da Binance ao gráfico sem expor a exchange ao browser."""

    try:
        symbol = binance_service.validar_symbol(symbol)
        intervalo = _obter_intervalo()
        limite = _obter_limite(default=200)
        candles = binance_service.get_ohlcv(
            symbol=symbol,
            timeframe=intervalo,
            limit=limite,
        )
        data = []

        for candle in candles:
            if len(candle) < 6:
                continue

            data.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        float(candle[0]) / 1000,
                        tz=timezone.utc,
                    ).isoformat(),
                    "open": float(candle[1]),
                    "high": float(candle[2]),
                    "low": float(candle[3]),
                    "close": float(candle[4]),
                    "volume": float(candle[5]),
                }
            )

        return jsonify(
            {
                "success": True,
                "symbol": symbol,
                "intervalo": intervalo,
                "source": "binance",
                "results": data,
                "total": len(data),
            }
        )
    except ValueError as exc:
        return _resposta_erro(str(exc), 400)
    except Exception:
        logger.exception(
            "Erro ao consultar candles | symbol=%s",
            symbol,
        )
        return _resposta_erro(
            "Não foi possível obter candles do mercado.",
            502,
        )


# ==============================================================
# ROTAS LEGACY
# ==============================================================

def rsi_all_legacy():
    """
    Compatibilidade com:

        GET /rsi/all
    """

    return api_rsi_all()


def rsi_intervalo_legacy(
    intervalo: str,
):
    """
    Compatibilidade com:

        GET /rsi/<intervalo>
    """

    with app_context_safe():

        try:

            registros = (
                RSIRepository.buscar_por_intervalo(
                    intervalo=intervalo,
                    limite=DEFAULT_LIMITE,
                )
            )

            data = _serializar_lista(
                registros
            )

            return jsonify(
                {
                    "success": True,
                    "intervalo": intervalo,
                    "results": data,
                    "total": len(data),
                }
            )

        except Exception:

            logger.exception(
                "Erro na rota legacy RSI | "
                "intervalo=%s",
                intervalo,
            )

            return _resposta_erro(
                "Erro interno ao consultar RSI.",
                500,
            )


# ==============================================================
# REGISTRO DAS ROTAS
# ==============================================================

def init_routes(
    app,
):
    """
    Registra todas as rotas da aplicação.
    """

    # ==========================================================
    # HOME
    # ==========================================================

    app.add_url_rule(
        "/",
        endpoint="home",
        view_func=home,
        methods=["GET"],
    )

    # ==========================================================
    # HEALTH
    # ==========================================================

    app.add_url_rule(
        "/api/v1/health",
        endpoint="api_health",
        view_func=api_health,
        methods=["GET"],
    )

    app.add_url_rule(
        "/health",
        endpoint="health",
        view_func=api_health,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/ready",
        endpoint="api_readiness",
        view_func=api_readiness,
        methods=["GET"],
    )

    # ==========================================================
    # RSI
    # ==========================================================

    app.add_url_rule(
        "/api/v1/rsi",
        endpoint="api_rsi",
        view_func=api_rsi,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/rsi/all",
        endpoint="api_rsi_all",
        view_func=api_rsi_all,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/rsi/<path:symbol>",
        endpoint="api_rsi_symbol",
        view_func=api_rsi_symbol,
        methods=["GET"],
    )

    # ==========================================================
    # SIGNALS
    # ==============================================================

    app.add_url_rule(
        "/api/v1/signals",
        endpoint="api_signals",
        view_func=api_signals,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/signals/overbought",
        endpoint="api_overbought",
        view_func=api_overbought,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/signals/oversold",
        endpoint="api_oversold",
        view_func=api_oversold,
        methods=["GET"],
    )

    # ==========================================================
    # DASHBOARD / ANÁLISE
    # ==========================================================

    app.add_url_rule(
        "/dashboard",
        endpoint="dashboard_page",
        view_func=dashboard_page,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/meta/timeframes",
        endpoint="api_timeframes",
        view_func=api_timeframes,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/symbols",
        endpoint="api_symbols",
        view_func=api_symbols,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/signals/current",
        endpoint="api_current_signals",
        view_func=api_current_signals,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/history/<path:symbol>",
        endpoint="api_rsi_history",
        view_func=api_rsi_history,
        methods=["GET"],
    )

    app.add_url_rule(
        "/api/v1/market/<path:symbol>/candles",
        endpoint="api_market_candles",
        view_func=api_market_candles,
        methods=["GET"],
    )

    # ==========================================================
    # LEGACY
    # ==========================================================

    app.add_url_rule(
        "/rsi/all",
        endpoint="rsi_all_legacy",
        view_func=rsi_all_legacy,
        methods=["GET"],
    )

    app.add_url_rule(
        "/rsi/<intervalo>",
        endpoint="rsi_intervalo_legacy",
        view_func=rsi_intervalo_legacy,
        methods=["GET"],
    )

    logger.info(
        "Rotas registradas com sucesso."
    )


# ==============================================================
# CONTEXTO AUXILIAR
# ==============================================================

class app_context_safe:
    """
    Context manager simples para manter compatibilidade
    com a rota legacy.

    Normalmente as rotas Flask já executam dentro
    do contexto da aplicação.
    """

    def __enter__(self):

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):

        return False
