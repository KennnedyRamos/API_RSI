from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import ccxt
import requests


logger = logging.getLogger(__name__)


class BinanceService:
    """
    Serviço responsável pela comunicação com a Binance
    através do CCXT.

    Responsabilidades:

        - conectar à Binance
        - obter mercados
        - obter símbolos USDT
        - obter tickers
        - obter OHLCV
        - normalizar símbolos
        - validar timeframes
        - tratar erros da exchange
        - controlar retries
        - respeitar rate limit
    """

    # ==========================================================
    # CONFIGURAÇÕES
    # ==========================================================

    DEFAULT_TIMEFRAME = "1h"

    TIMEFRAMES_PERMITIDOS = (
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

    # ----------------------------------------------------------
    # RETRY
    # ----------------------------------------------------------

    DEFAULT_MAX_RETRIES = 2

    DEFAULT_RETRY_DELAY = 1.0

    DEFAULT_RETRY_BACKOFF = 2.0

    # ----------------------------------------------------------
    # CACHE DE MERCADOS
    # ----------------------------------------------------------

    DEFAULT_MARKETS_CACHE_TTL = 900

    # ----------------------------------------------------------
    # TICKERS SELECIONADOS
    # ----------------------------------------------------------

    # A rota pública aceita uma lista de pares e, diferente do
    # ``fetch_ticker`` do CCXT, não precisa carregar o catálogo completo da
    # Binance antes da primeira consulta. Isso é essencial nas VMs pequenas.
    TICKERS_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"

    # Um ciclo que excede um minuto não pode gerar alertas Telegram. Mantemos
    # um timeout curto para falhar cedo e nunca transformar uma indisponibilidade
    # temporária da Binance em alerta atrasado.
    TICKERS_REQUEST_TIMEOUT = 8.0

    # ==========================================================
    # INIT
    # ==========================================================

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
        retry_backoff: float = DEFAULT_RETRY_BACKOFF,
        markets_cache_ttl: int = DEFAULT_MARKETS_CACHE_TTL,
    ) -> None:
        """
        Inicializa o BinanceService.

        Args:
            api_key:
                API Key da Binance.

            secret:
                Secret da Binance.

            max_retries:
                Quantidade máxima de tentativas adicionais
                após a primeira tentativa.

            retry_delay:
                Delay inicial entre tentativas.

            retry_backoff:
                Multiplicador do backoff.

            markets_cache_ttl:
                Tempo de validade do cache de mercados.
        """

        if max_retries < 0:
            raise ValueError(
                "max_retries deve ser maior ou igual a zero."
            )

        if retry_delay < 0:
            raise ValueError(
                "retry_delay não pode ser negativo."
            )

        if retry_backoff < 1:
            raise ValueError(
                "retry_backoff deve ser maior ou igual a 1."
            )

        if markets_cache_ttl < 0:
            raise ValueError(
                "markets_cache_ttl não pode ser negativo."
            )

        self.api_key = api_key
        self.secret = secret

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_backoff = retry_backoff
        self.markets_cache_ttl = markets_cache_ttl

        # ------------------------------------------------------
        # CACHE
        # ------------------------------------------------------

        self._markets: Optional[
            dict[str, Any]
        ] = None

        self._markets_timestamp = 0.0

        # A sessão é reutilizada entre ciclos para manter a conexão HTTPS e
        # reduzir a latência das consultas reduzidas de ticker.
        self._ticker_session = requests.Session()

        # ------------------------------------------------------
        # EXCHANGE
        # ------------------------------------------------------

        self.exchange = self._criar_exchange()

        logger.info(
            "BinanceService inicializado | "
            "max_retries=%s | "
            "retry_delay=%ss | "
            "retry_backoff=%s | "
            "markets_cache_ttl=%ss",
            self.max_retries,
            self.retry_delay,
            self.retry_backoff,
            self.markets_cache_ttl,
        )

    # ==========================================================
    # CRIAR EXCHANGE
    # ==========================================================

    def _criar_exchange(self) -> ccxt.binance:
        """
        Cria a conexão com a Binance.

        Não é necessário utilizar API Key para consultas
        públicas como OHLCV e ticker.
        """

        try:

            exchange = ccxt.binance(
                {
                    "apiKey": self.api_key,
                    "secret": self.secret,
                    "enableRateLimit": True,
                    "options": {
                        "defaultType": "spot",
                        # CCXT tenta carregar spot, futuros lineares e
                        # futuros inversos por padrão. O RSI deste projeto
                        # usa somente pares spot/USDT.
                        "fetchMarkets": {
                            "types": ["spot"],
                        },
                    },
                }
            )

            logger.info(
                "Conexão CCXT com Binance criada."
            )

            return exchange

        except Exception:

            logger.exception(
                "Erro ao criar conexão com Binance."
            )

            raise

    # ==========================================================
    # RETRY
    # ==========================================================

    def _deve_repetir(
        self,
        exc: Exception,
    ) -> bool:
        """
        Determina se uma exceção permite retry.
        """

        return isinstance(
            exc,
            (
                ccxt.NetworkError,
                ccxt.RequestTimeout,
                ccxt.ExchangeNotAvailable,
                ccxt.RateLimitExceeded,
                requests.RequestException,
            ),
        )

    # ==========================================================

    def _executar_com_retry(
        self,
        func,
        *,
        operacao: str,
        **kwargs,
    ):
        """
        Executa uma operação CCXT com retry e backoff.

        A primeira execução acontece imediatamente.

        Em caso de erro transitório:

            tentativa 1
                ↓
              espera
                ↓
            tentativa 2
                ↓
              espera
                ↓
            tentativa 3

        O número total de execuções é:

            max_retries + 1
        """

        ultima_excecao: Optional[
            Exception
        ] = None

        total_tentativas = (
            self.max_retries + 1
        )

        for tentativa in range(
            1,
            total_tentativas + 1,
        ):

            try:

                return func(
                    **kwargs
                )

            except Exception as exc:

                ultima_excecao = exc

                # --------------------------------------------------
                # NÃO É ERRO TRANSITÓRIO
                # --------------------------------------------------

                if not self._deve_repetir(
                    exc
                ):

                    raise

                # --------------------------------------------------
                # ÚLTIMA TENTATIVA
                # --------------------------------------------------

                if tentativa >= total_tentativas:

                    logger.error(
                        "Operação Binance falhou após "
                        "%d tentativa(s) | "
                        "operação=%s | erro=%s",
                        tentativa,
                        operacao,
                        exc,
                    )

                    raise

                # --------------------------------------------------
                # BACKOFF
                # --------------------------------------------------

                atraso = (
                    self.retry_delay
                    * (
                        self.retry_backoff
                        ** (tentativa - 1)
                    )
                )

                logger.warning(
                    "Erro transitório na Binance | "
                    "operação=%s | "
                    "tentativa=%d/%d | "
                    "aguardando=%.2fs | "
                    "erro=%s",
                    operacao,
                    tentativa,
                    total_tentativas,
                    atraso,
                    exc,
                )

                time.sleep(
                    atraso
                )

        # Segurança teórica.
        if ultima_excecao is not None:
            raise ultima_excecao

        raise RuntimeError(
            f"Falha inesperada na operação Binance: {operacao}"
        )

    # ==========================================================
    # CACHE DE MERCADOS
    # ==========================================================

    def _markets_cache_valido(
        self,
    ) -> bool:
        """
        Verifica se o cache de mercados ainda é válido.
        """

        if self._markets is None:
            return False

        if self._markets_timestamp <= 0:
            return False

        if self.markets_cache_ttl == 0:
            return False

        idade = (
            time.monotonic()
            - self._markets_timestamp
        )

        return idade < self.markets_cache_ttl

    # ==========================================================

    def limpar_cache_mercados(
        self,
    ) -> None:
        """
        Limpa o cache de mercados da Binance.
        """

        self._markets = None
        self._markets_timestamp = 0.0

        logger.info(
            "Cache de mercados da Binance limpo."
        )

    # ==========================================================

    def cache_info(
        self,
    ) -> dict[str, Any]:
        """
        Retorna informações do cache de mercados.
        """

        idade = None

        if self._markets_timestamp > 0:

            idade = (
                time.monotonic()
                - self._markets_timestamp
            )

        return {
            "items": (
                len(self._markets)
                if self._markets is not None
                else 0
            ),
            "ttl": self.markets_cache_ttl,
            "age": idade,
            "valid": self._markets_cache_valido(),
            "available": self._markets is not None,
        }

    # ==========================================================
    # CARREGAR MERCADOS
    # ==========================================================

    def carregar_mercados(
        self,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Carrega os mercados disponíveis na Binance.

        Utiliza cache para evitar chamadas repetitivas
        ao endpoint da exchange.

        Args:
            force:
                Se True, ignora o cache e força nova consulta.
        """

        # ------------------------------------------------------
        # CACHE
        # ------------------------------------------------------

        if (
            not force
            and self._markets_cache_valido()
        ):

            logger.debug(
                "Cache de mercados Binance ainda válido."
            )

            return self._markets or {}

        logger.info(
            "Carregando mercados da Binance..."
        )

        try:

            markets = (
                self._executar_com_retry(
                    self.exchange.load_markets,
                    operacao="load_markets",
                )
            )

            if not markets:

                raise RuntimeError(
                    "Binance não retornou mercados."
                )

            self._markets = dict(
                markets
            )

            self._markets_timestamp = (
                time.monotonic()
            )

            logger.info(
                "Mercados Binance carregados | "
                "total=%d",
                len(self._markets),
            )

            return self._markets

        except ccxt.NetworkError:

            logger.exception(
                "Erro de rede ao carregar "
                "mercados da Binance."
            )

            raise

        except ccxt.ExchangeError:

            logger.exception(
                "Erro da Binance ao carregar mercados."
            )

            raise

        except Exception:

            logger.exception(
                "Erro inesperado ao carregar mercados."
            )

            raise

    # ==========================================================
    # SÍMBOLOS USDT
    # ==========================================================

    def get_usdt_symbols(
        self,
        force_refresh: bool = False,
    ) -> list[str]:
        """
        Retorna os símbolos spot cotados em USDT.

        Exemplos:

            BTC/USDT
            ETH/USDT
            BNB/USDT
        """

        markets = (
            self.carregar_mercados(
                force=force_refresh
            )
        )

        symbols: list[str] = []

        for symbol, market in markets.items():

            try:

                if not market.get(
                    "spot"
                ):
                    continue

                if not market.get(
                    "active",
                    True,
                ):
                    continue

                if market.get(
                    "quote"
                ) != "USDT":
                    continue

                symbols.append(
                    symbol
                )

            except Exception:

                logger.warning(
                    "Não foi possível processar "
                    "mercado: %s",
                    symbol,
                )

        symbols.sort()

        logger.info(
            "Símbolos USDT encontrados: %d",
            len(symbols),
        )

        return symbols

    # ==========================================================
    # VALIDAR SÍMBOLO
    # ==========================================================

    def validar_symbol(
        self,
        symbol: str,
    ) -> str:
        """
        Normaliza e valida um símbolo.

        Exemplos aceitos:

            BTC/USDT
            BTC-USDT
            BTCUSDT

        Resultado:

            BTC/USDT
        """

        if not symbol:

            raise ValueError(
                "Símbolo não informado."
            )

        symbol = (
            str(symbol)
            .strip()
            .upper()
        )

        symbol = symbol.replace(
            "-",
            "/",
        )

        # ------------------------------------------------------
        # SÍMBOLO SEM SEPARADOR
        # ------------------------------------------------------

        if (
            "/" not in symbol
            and symbol.endswith(
                "USDT"
            )
        ):

            base = symbol[:-4]

            if not base:

                raise ValueError(
                    f"Símbolo inválido: {symbol}."
                )

            symbol = (
                f"{base}/USDT"
            )

        # ------------------------------------------------------
        # VALIDAR FORMATO
        # ------------------------------------------------------

        if "/" not in symbol:

            raise ValueError(
                f"Símbolo inválido: {symbol}. "
                f"Use o formato BTC/USDT."
            )

        partes = symbol.split(
            "/"
        )

        if len(partes) != 2:

            raise ValueError(
                f"Símbolo inválido: {symbol}."
            )

        base, quote = partes

        if not base or not quote:

            raise ValueError(
                f"Símbolo inválido: {symbol}."
            )

        if quote != "USDT":

            raise ValueError(
                f"Símbolo inválido: {symbol}. "
                f"Apenas pares USDT são suportados."
            )

        return symbol

    # ==========================================================
    # VALIDAR TIMEFRAME
    # ==========================================================

    def _validar_timeframe(
        self,
        timeframe: str,
    ) -> str:
        """
        Valida o timeframe informado.
        """

        if not timeframe:

            raise ValueError(
                "Timeframe não informado."
            )

        timeframe = (
            str(timeframe)
            .strip()
        )

        if (
            timeframe
            not in self.TIMEFRAMES_PERMITIDOS
        ):

            raise ValueError(
                f"Timeframe inválido: {timeframe}. "
                f"Permitidos: "
                f"{', '.join(self.TIMEFRAMES_PERMITIDOS)}."
            )

        return timeframe

    # ==========================================================
    # OHLCV
    # ==========================================================

    def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = DEFAULT_TIMEFRAME,
        limit: int = 100,
    ) -> list[list[Any]]:
        """
        Obtém candles OHLCV da Binance.

        Estrutura:

            [
                timestamp,
                open,
                high,
                low,
                close,
                volume
            ]
        """

        symbol = self.validar_symbol(
            symbol
        )

        timeframe = self._validar_timeframe(
            timeframe
        )

        if limit <= 0:

            raise ValueError(
                "O limite de candles deve ser "
                "maior que zero."
            )

        try:

            candles = (
                self._executar_com_retry(
                    self.exchange.fetch_ohlcv,
                    operacao=(
                        f"fetch_ohlcv "
                        f"{symbol} "
                        f"{timeframe}"
                    ),
                    symbol=symbol,
                    timeframe=timeframe,
                    limit=limit,
                )
            )

            if not candles:

                raise ValueError(
                    f"Nenhum candle retornado para "
                    f"{symbol} no timeframe "
                    f"{timeframe}."
                )

            logger.debug(
                "OHLCV obtido | "
                "symbol=%s | "
                "timeframe=%s | "
                "candles=%d",
                symbol,
                timeframe,
                len(candles),
            )

            return candles

        except ccxt.NetworkError:

            logger.exception(
                "Erro de rede ao obter OHLCV | "
                "symbol=%s | timeframe=%s",
                symbol,
                timeframe,
            )

            raise

        except ccxt.ExchangeError:

            logger.exception(
                "Erro da Binance ao obter OHLCV | "
                "symbol=%s | timeframe=%s",
                symbol,
                timeframe,
            )

            raise

        except Exception:

            logger.exception(
                "Erro inesperado ao obter OHLCV | "
                "symbol=%s | timeframe=%s",
                symbol,
                timeframe,
            )

            raise

    # ==========================================================
    # TICKER
    # ==========================================================

    def get_ticker(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        """
        Obtém o ticker de um símbolo.
        """

        symbol = self.validar_symbol(
            symbol
        )

        try:

            ticker = (
                self._executar_com_retry(
                    self.exchange.fetch_ticker,
                    operacao=(
                        f"fetch_ticker {symbol}"
                    ),
                    symbol=symbol,
                )
            )

            if not ticker:

                raise ValueError(
                    f"Ticker não retornado para "
                    f"{symbol}."
                )

            logger.debug(
                "Ticker obtido | symbol=%s",
                symbol,
            )

            return ticker

        except ccxt.NetworkError:

            logger.exception(
                "Erro de rede ao obter ticker | "
                "symbol=%s",
                symbol,
            )

            raise

        except ccxt.ExchangeError:

            logger.exception(
                "Erro da Binance ao obter ticker | "
                "symbol=%s",
                symbol,
            )

            raise

        except Exception:

            logger.exception(
                "Erro inesperado ao obter ticker | "
                "symbol=%s",
                symbol,
            )

            raise

    # ==========================================================
    # TODOS OS TICKERS
    # ==========================================================

    def _buscar_tickers_selecionados_publicos(
        self,
        symbols: list[str],
    ) -> list[dict[str, Any]]:
        """Busca somente os tickers solicitados na API pública da Binance."""

        response = self._ticker_session.get(
            self.TICKERS_24H_URL,
            params={
                "symbols": json.dumps(
                    symbols,
                    separators=(",", ":"),
                ),
            },
            timeout=self.TICKERS_REQUEST_TIMEOUT,
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, list):
            raise TypeError(
                "A Binance retornou um formato inválido de tickers."
            )

        return payload

    def _obter_tickers_selecionados(
        self,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Converte a resposta pública reduzida ao formato usado pelo RSI."""

        compactos = {
            symbol.replace("/", ""): symbol
            for symbol in symbols
        }
        payload = self._executar_com_retry(
            self._buscar_tickers_selecionados_publicos,
            operacao="ticker_24h de pares selecionados",
            symbols=list(compactos),
        )

        tickers: dict[str, dict[str, Any]] = {}
        for ticker in payload:
            if not isinstance(ticker, dict):
                continue

            compacto = str(ticker.get("symbol") or "").upper()
            symbol = compactos.get(compacto)
            if symbol is None:
                continue

            tickers[symbol] = {
                "symbol": symbol,
                "last": ticker.get("lastPrice"),
                "close": ticker.get("lastPrice"),
                "percentage": ticker.get("priceChangePercent"),
                "quoteVolume": ticker.get("quoteVolume"),
                "baseVolume": ticker.get("volume"),
                "timestamp": ticker.get("closeTime"),
            }

        ausentes = [
            symbol
            for symbol in symbols
            if symbol not in tickers
        ]
        if ausentes:
            raise ValueError(
                "A Binance não retornou ticker para: "
                f"{', '.join(ausentes)}."
            )

        logger.info(
            "Tickers Binance obtidos em lote público | total=%d",
            len(tickers),
        )
        return tickers

    def get_tickers(
        self,
        symbols: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Obtém os tickers da Binance.

        Quando ``symbols`` é informado, consulta somente esses pares em um
        lote público reduzido. Isso evita o catálogo completo da Binance e
        mantém o ciclo suficientemente rápido para alertas recentes.
        """

        selected_symbols: list[str] | None = None
        if symbols:
            selected_symbols = list(
                dict.fromkeys(
                    self.validar_symbol(symbol)
                    for symbol in symbols
                )
            )

        if selected_symbols:
            return self._obter_tickers_selecionados(
                selected_symbols
            )

        try:

            tickers = (
                self._executar_com_retry(
                    self.exchange.fetch_tickers,
                    operacao="fetch_tickers",
                )
            )

            if not tickers:

                raise ValueError(
                    "Binance não retornou tickers."
                )

            logger.info(
                "Tickers Binance obtidos | total=%d | selecionados=todos",
                len(tickers),
            )

            return tickers

        except ccxt.NetworkError:

            logger.exception(
                "Erro de rede ao obter tickers "
                "da Binance."
            )

            raise

        except ccxt.ExchangeError:

            logger.exception(
                "Erro da Binance ao obter tickers."
            )

            raise

        except Exception:

            logger.exception(
                "Erro inesperado ao obter tickers."
            )

            raise

    # ==========================================================
    # CLOSE
    # ==========================================================

    def close(
        self,
    ) -> None:
        """
        Fecha a conexão da exchange.
        """

        try:

            close_method = getattr(
                self.exchange,
                "close",
                None,
            )

            if callable(
                close_method
            ):

                close_method()

            ticker_session = getattr(
                self,
                "_ticker_session",
                None,
            )
            session_close = getattr(
                ticker_session,
                "close",
                None,
            )
            if callable(session_close):
                session_close()

            logger.info(
                "Conexão Binance encerrada."
            )

        except Exception:

            logger.exception(
                "Erro ao fechar conexão "
                "com Binance."
            )


# ==============================================================
# SINGLETON
# ==============================================================

binance_service = BinanceService()
