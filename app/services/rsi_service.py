from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import ccxt

from app.utils.rsi import (
    calcular_diferenca_rsi,
    calcular_rsi_anterior,
    calcular_rsi_wilder,
    classificar_nivel_sinal,
    classificar_rsi,
    classificar_tipo_sinal,
)

from database.repositories import (
    RSIRepository,
    RSISnapshotRepository,
)

from services.binance_service import binance_service
from services.market_service import market_service


logger = logging.getLogger(__name__)


class RSIService:
    """
    Serviço responsável pelas regras de negócio do RSI.

    Responsabilidades:

        - validar e normalizar símbolos
        - validar timeframes
        - buscar candles da Binance
        - utilizar somente candles fechados
        - calcular RSI Wilder
        - calcular RSI anterior
        - calcular diferença do RSI
        - obter dados do ticker
        - obter market cap
        - obter ranking
        - classificar RSI
        - classificar tipo de sinal
        - classificar nível do sinal
        - persistir dados no PostgreSQL

    Não possui lógica de:

        - Telegram
        - Redis
        - Worker
        - Dashboard
        - HTTP/API
    """

    # ==========================================================
    # CONFIGURAÇÕES
    # ==========================================================

    PERIODO_RSI = 14

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

    # Quantidade de candles históricos adicionais utilizados
    # para melhorar a estabilidade do cálculo do RSI Wilder.

    CANDLES_HISTORICO_EXTRA = 100

    # +1 representa o candle que pode estar em formação.

    CANDLES_NECESSARIOS = (
        PERIODO_RSI
        + CANDLES_HISTORICO_EXTRA
        + 1
    )

    # ==========================================================
    # CONSTRUTOR
    # ==========================================================

    def __init__(
        self,
        binance=None,
        repository=None,
        market=None,
        snapshot_repository=None,
    ) -> None:

        self.binance = (
            binance
            or binance_service
        )

        self.repository = (
            repository
            or RSIRepository
        )

        self.market = (
            market
            or market_service
        )

        self.snapshot_repository = (
            snapshot_repository
            or RSISnapshotRepository
        )

    # ==========================================================
    # PROCESSAR SÍMBOLO
    # ==========================================================

    def processar_simbolo(
        self,
        symbol: str,
        intervalo: str,
        ticker: Optional[
            dict[str, Any]
        ] = None,
        salvar: bool = True,
    ) -> dict[str, Any]:
        """
        Processa um símbolo em determinado timeframe.

        O processamento utiliza:

            1. candles da Binance
            2. somente candles fechados
            3. RSI Wilder
            4. RSI anterior
            5. diferença do RSI
            6. classificação do RSI
            7. classificação do sinal
            8. ticker da Binance
            9. market cap/ranking
            10. persistência opcional

        Args:
            symbol:
                Símbolo, por exemplo BTC/USDT.

            intervalo:
                Timeframe, por exemplo 1h.

            ticker:
                Ticker previamente carregado.
                Quando não informado, será buscado.

            salvar:
                Se True, persiste no banco.

        Returns:
            Dicionário com o resultado do processamento.
        """

        # ======================================================
        # VALIDAR / NORMALIZAR SÍMBOLO
        # ======================================================

        symbol = self._normalizar_symbol(
            symbol
        )

        # ======================================================
        # VALIDAR INTERVALO
        # ======================================================

        self._validar_intervalo(
            intervalo
        )

        logger.debug(
            "Processando RSI | "
            "symbol=%s | intervalo=%s | salvar=%s",
            symbol,
            intervalo,
            salvar,
        )

        # ======================================================
        # OBTER CANDLES
        # ======================================================

        candles = self.binance.get_ohlcv(
            symbol=symbol,
            timeframe=intervalo,
            limit=self.CANDLES_NECESSARIOS,
        )

        # ======================================================
        # VALIDAR CANDLES
        # ======================================================

        self._validar_candles(
            candles=candles,
            symbol=symbol,
            intervalo=intervalo,
        )

        # ======================================================
        # REMOVER CANDLE EM FORMAÇÃO
        # ======================================================

        candles_fechados = self._obter_candles_fechados(
            candles
        )

        quantidade_minima = (
            self.PERIODO_RSI + 2
        )

        if len(candles_fechados) < quantidade_minima:

            raise ValueError(
                "Candles fechados insuficientes "
                "para calcular RSI atual e anterior | "
                f"symbol={symbol} | "
                f"intervalo={intervalo} | "
                f"recebidos={len(candles_fechados)} | "
                f"necessarios={quantidade_minima}"
            )

        # ======================================================
        # EXTRAIR FECHAMENTOS
        # ======================================================

        closes = self._extrair_closes(
            candles_fechados
        )

        # ======================================================
        # RSI ATUAL
        # ======================================================

        rsi_atual = calcular_rsi_wilder(
            closes=closes,
            periodo=self.PERIODO_RSI,
        )

        # ======================================================
        # VALIDAR RSI ATUAL
        # ======================================================

        self._validar_rsi(
            rsi=rsi_atual,
            nome="RSI atual",
            symbol=symbol,
        )

        # ======================================================
        # RSI ANTERIOR
        # ======================================================

        rsi_anterior = calcular_rsi_anterior(
            closes=closes,
            periodo=self.PERIODO_RSI,
        )

        # ======================================================
        # VALIDAR RSI ANTERIOR
        # ======================================================

        self._validar_rsi(
            rsi=rsi_anterior,
            nome="RSI anterior",
            symbol=symbol,
        )

        # ======================================================
        # DIFERENÇA
        # ======================================================

        rsi_difference = calcular_diferenca_rsi(
            rsi_atual=rsi_atual,
            rsi_anterior=rsi_anterior,
        )

        # ======================================================
        # TIMESTAMP
        # ======================================================

        candle_atual = candles_fechados[-1]

        timestamp_ms = candle_atual[0]

        timestamp = (
            self._timestamp_para_datetime(
                timestamp_ms
            )
        )

        # ======================================================
        # CLASSIFICAÇÃO DO RSI
        # ======================================================

        rsi_status = classificar_rsi(
            rsi_atual
        )

        # ======================================================
        # TIPO DO SINAL
        # ======================================================

        signal_type = classificar_tipo_sinal(
            rsi_atual
        )

        # ======================================================
        # NÍVEL DO SINAL
        # ======================================================

        signal_level = classificar_nivel_sinal(
            rsi=rsi_atual,
            rsi_anterior=rsi_anterior,
        )

        # Quando não existe sinal,
        # o nível deve permanecer NORMAL.

        if signal_type is None:

            signal_level = "NORMAL"

        # ======================================================
        # TICKER
        # ======================================================

        if ticker is None:

            ticker = self.binance.get_ticker(
                symbol
            )

        market_data_binance = (
            self._extrair_dados_ticker(
                symbol=symbol,
                ticker=ticker,
            )
        )

        # ======================================================
        # MARKET DATA
        # ======================================================

        market_data = (
            self._obter_market_data(
                symbol=symbol
            )
        )

        # ======================================================
        # RESULTADO
        # ======================================================

        resultado: dict[str, Any] = {

            # --------------------------------------------------
            # IDENTIFICAÇÃO
            # --------------------------------------------------

            "symbol": symbol,

            "intervalo": intervalo,

            # --------------------------------------------------
            # RSI
            # --------------------------------------------------

            "rsi": rsi_atual,

            "rsi_previous": rsi_anterior,

            "rsi_difference": rsi_difference,

            # --------------------------------------------------
            # TEMPO
            # --------------------------------------------------

            "timestamp": timestamp,

            # --------------------------------------------------
            # CLASSIFICAÇÃO
            # --------------------------------------------------

            "rsi_status": rsi_status,

            "signal_type": signal_type,

            "signal_level": signal_level,

            # --------------------------------------------------
            # BINANCE
            # --------------------------------------------------

            "current_price": (
                market_data_binance[
                    "current_price"
                ]
            ),

            "change_24h": (
                market_data_binance[
                    "change_24h"
                ]
            ),

            "volume_24h": (
                market_data_binance[
                    "volume_24h"
                ]
            ),

            # --------------------------------------------------
            # MARKET DATA
            # --------------------------------------------------

            "market_cap": (
                market_data[
                    "market_cap"
                ]
            ),

            "ranking": (
                market_data[
                    "ranking"
                ]
            ),
        }

        # ======================================================
        # PERSISTÊNCIA
        # ======================================================

        if salvar:

            resultado["rsi_data_id"] = (
                self._salvar_resultado(
                    resultado,
                )
            )

            resultado["saved"] = True

        else:

            resultado["saved"] = False

        logger.debug(
            "RSI processado | "
            "symbol=%s | "
            "intervalo=%s | "
            "RSI=%.2f | "
            "anterior=%.2f | "
            "diferença=%.2f | "
            "status=%s | "
            "sinal=%s | "
            "nível=%s",
            symbol,
            intervalo,
            rsi_atual,
            rsi_anterior,
            rsi_difference,
            rsi_status,
            signal_type,
            signal_level,
        )

        return resultado

    # ==========================================================
    # NORMALIZAR SÍMBOLO
    # ==========================================================

    def _normalizar_symbol(
        self,
        symbol: str,
    ) -> str:
        """
        Normaliza o símbolo utilizando a validação do
        BinanceService.

        Exemplos aceitos:

            BTC/USDT
            BTCUSDT
            BTC-USDT

        Resultado:

            BTC/USDT
        """

        if not symbol:

            raise ValueError(
                "Símbolo não informado."
            )

        try:

            return self.binance.validar_symbol(
                symbol
            )

        except AttributeError:

            # Fallback para implementações de BinanceService
            # que não possuam validar_symbol.

            normalized = (
                str(symbol)
                .strip()
                .upper()
                .replace("-", "/")
            )

            if (
                "/" not in normalized
                and normalized.endswith("USDT")
            ):

                normalized = (
                    f"{normalized[:-4]}/USDT"
                )

            if "/" not in normalized:

                raise ValueError(
                    f"Símbolo inválido: {normalized}. "
                    "Use o formato BTC/USDT."
                )

            return normalized

    # ==========================================================
    # VALIDAR CANDLES
    # ==========================================================

    @staticmethod
    def _validar_candles(
        candles: Any,
        symbol: str,
        intervalo: str,
    ) -> None:
        """
        Valida a estrutura básica dos candles retornados
        pela Binance.
        """

        if not candles:

            raise ValueError(
                f"Nenhum candle retornado | "
                f"symbol={symbol} | "
                f"intervalo={intervalo}"
            )

        if not isinstance(candles, (list, tuple)):

            raise TypeError(
                f"Formato inválido de candles | "
                f"symbol={symbol} | "
                f"intervalo={intervalo}"
            )

        for index, candle in enumerate(candles):

            if not isinstance(
                candle,
                (list, tuple),
            ):

                raise ValueError(
                    f"Candle inválido no índice {index} | "
                    f"symbol={symbol} | "
                    f"intervalo={intervalo}"
                )

            if len(candle) < 5:

                raise ValueError(
                    f"Candle incompleto no índice {index} | "
                    f"symbol={symbol} | "
                    f"intervalo={intervalo}"
                )

    # ==========================================================
    # OBTER CANDLES FECHADOS
    # ==========================================================

    @staticmethod
    def _obter_candles_fechados(
        candles: list[list[Any]],
    ) -> list[list[Any]]:
        """
        Remove o último candle.

        A Binance normalmente retorna o candle atual,
        que ainda pode estar em formação.

        Portanto:

            candles[:-1]

        garante que o RSI seja calculado apenas com
        candles fechados.
        """

        if len(candles) <= 1:

            return []

        return candles[:-1]

    # ==========================================================
    # EXTRAIR CLOSES
    # ==========================================================

    @staticmethod
    def _extrair_closes(
        candles: list[list[Any]],
    ) -> list[float]:
        """
        Extrai os preços de fechamento dos candles.
        """

        closes: list[float] = []

        for index, candle in enumerate(candles):

            try:

                close = float(
                    candle[4]
                )

            except (
                TypeError,
                ValueError,
                IndexError,
            ) as exc:

                raise ValueError(
                    "Preço de fechamento inválido "
                    f"no candle {index}."
                ) from exc

            if close <= 0:

                raise ValueError(
                    "Preço de fechamento deve ser "
                    f"maior que zero. Candle={index}."
                )

            closes.append(
                close
            )

        return closes

    # ==========================================================
    # VALIDAR RSI
    # ==========================================================

    @staticmethod
    def _validar_rsi(
        rsi: Any,
        nome: str,
        symbol: str,
    ) -> None:
        """
        Valida se o RSI retornado está dentro do intervalo
        matematicamente esperado: 0 <= RSI <= 100.
        """

        if rsi is None:

            raise ValueError(
                f"{nome} não foi calculado | "
                f"symbol={symbol}"
            )

        try:

            valor = float(rsi)

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise ValueError(
                f"{nome} inválido | "
                f"symbol={symbol} | "
                f"valor={rsi}"
            ) from exc

        if not 0 <= valor <= 100:

            raise ValueError(
                f"{nome} fora do intervalo 0-100 | "
                f"symbol={symbol} | "
                f"valor={valor}"
            )

    # ==========================================================
    # OBTER MARKET DATA
    # ==========================================================

    def _obter_market_data(
        self,
        symbol: str,
    ) -> dict[str, Any]:
        """
        Obtém market cap e ranking através do MarketService.

        A indisponibilidade do CoinGecko/MarketService NÃO
        interrompe o processamento do RSI.

        Retorno em caso de falha:

            {
                "market_cap": None,
                "ranking": None
            }
        """

        try:

            data = self.market.get_market_data(
                symbol
            )

            if not data:

                logger.warning(
                    "MarketService retornou dados vazios | "
                    "symbol=%s",
                    symbol,
                )

                return {
                    "market_cap": None,
                    "ranking": None,
                }

            market_cap = data.get(
                "market_cap"
            )

            ranking = data.get(
                "ranking"
            )

            # --------------------------------------------------
            # MARKET CAP
            # --------------------------------------------------

            if market_cap is not None:

                try:

                    market_cap = float(
                        market_cap
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    logger.warning(
                        "Market cap inválido | "
                        "symbol=%s | valor=%s",
                        symbol,
                        market_cap,
                    )

                    market_cap = None

            # --------------------------------------------------
            # RANKING
            # --------------------------------------------------

            if ranking is not None:

                try:

                    ranking = int(
                        ranking
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    logger.warning(
                        "Ranking inválido | "
                        "symbol=%s | valor=%s",
                        symbol,
                        ranking,
                    )

                    ranking = None

            logger.debug(
                "Market data obtido | "
                "symbol=%s | "
                "market_cap=%s | "
                "ranking=%s",
                symbol,
                market_cap,
                ranking,
            )

            return {
                "market_cap": market_cap,
                "ranking": ranking,
            }

        except Exception as exc:

            logger.warning(
                "Não foi possível obter market data | "
                "symbol=%s | erro=%s",
                symbol,
                exc,
            )

            return {
                "market_cap": None,
                "ranking": None,
            }

    # ==========================================================
    # PROCESSAR INTERVALO
    # ==========================================================

    def processar_intervalo(
        self,
        intervalo: str,
        symbols: Optional[
            list[str]
        ] = None,
        tickers: Optional[
            dict[str, dict[str, Any]]
        ] = None,
        salvar: bool = True,
    ) -> dict[str, Any]:
        """
        Processa todos os símbolos USDT em determinado
        timeframe.

        O método pode receber símbolos e tickers já carregados
        pelo Worker para evitar chamadas repetidas à Binance.
        """

        self._validar_intervalo(
            intervalo
        )

        results: list[
            dict[str, Any]
        ] = []

        errors: list[
            dict[str, Any]
        ] = []

        # ======================================================
        # SÍMBOLOS
        # ======================================================

        if symbols is None:

            symbols = (
                self.binance.get_usdt_symbols()
            )

        if not symbols:

            logger.warning(
                "Nenhum símbolo para processar | "
                "intervalo=%s",
                intervalo,
            )

            return {
                "intervalo": intervalo,
                "results": [],
                "errors": [],
                "total_results": 0,
                "total_errors": 0,
            }

        # ======================================================
        # TICKERS
        # ======================================================

        if tickers is None:

            tickers = (
                self.binance.get_tickers()
            )

        if tickers is None:

            tickers = {}

        logger.info(
            "Processando símbolos | "
            "intervalo=%s | "
            "symbols=%d | "
            "tickers=%d",
            intervalo,
            len(symbols),
            len(tickers),
        )

        # ======================================================
        # PROCESSAMENTO
        # ======================================================

        for symbol in symbols:

            if not symbol:

                continue

            try:

                symbol_normalizado = (
                    self._normalizar_symbol(
                        symbol
                    )
                )

                # ------------------------------------------------
                # TICKER
                # ------------------------------------------------

                ticker = self._obter_ticker_do_mapa(
                    tickers=tickers,
                    symbol=symbol_normalizado,
                )

                if ticker is None:

                    errors.append(
                        {
                            "symbol": symbol_normalizado,
                            "intervalo": intervalo,
                            "error": (
                                "Ticker não encontrado."
                            ),
                            "type": (
                                "ticker_not_found"
                            ),
                        }
                    )

                    continue

                # ------------------------------------------------
                # RSI
                # ------------------------------------------------

                resultado = (
                    self.processar_simbolo(
                        symbol=symbol_normalizado,
                        intervalo=intervalo,
                        ticker=ticker,
                        salvar=salvar,
                    )
                )

                results.append(
                    resultado
                )

            except ccxt.NetworkError as exc:

                logger.warning(
                    "Erro de rede | "
                    "symbol=%s | "
                    "intervalo=%s | %s",
                    symbol,
                    intervalo,
                    exc,
                )

                errors.append(
                    {
                        "symbol": symbol,
                        "intervalo": intervalo,
                        "error": str(exc),
                        "type": "network_error",
                    }
                )

            except ccxt.ExchangeError as exc:

                logger.warning(
                    "Erro da exchange | "
                    "symbol=%s | "
                    "intervalo=%s | %s",
                    symbol,
                    intervalo,
                    exc,
                )

                errors.append(
                    {
                        "symbol": symbol,
                        "intervalo": intervalo,
                        "error": str(exc),
                        "type": "exchange_error",
                    }
                )

            except ValueError as exc:

                logger.warning(
                    "Dados inválidos | "
                    "symbol=%s | "
                    "intervalo=%s | %s",
                    symbol,
                    intervalo,
                    exc,
                )

                errors.append(
                    {
                        "symbol": symbol,
                        "intervalo": intervalo,
                        "error": str(exc),
                        "type": "validation_error",
                    }
                )

            except Exception as exc:

                logger.exception(
                    "Erro interno | "
                    "symbol=%s | "
                    "intervalo=%s",
                    symbol,
                    intervalo,
                )

                errors.append(
                    {
                        "symbol": symbol,
                        "intervalo": intervalo,
                        "error": str(exc),
                        "type": "internal_error",
                    }
                )

        # ======================================================
        # RETORNO
        # ======================================================

        return {
            "intervalo": intervalo,
            "results": results,
            "errors": errors,
            "total_results": len(
                results
            ),
            "total_errors": len(
                errors
            ),
        }

    # ==========================================================
    # OBTER TICKER DO MAPA
    # ==========================================================

    @staticmethod
    def _obter_ticker_do_mapa(
        tickers: dict[str, dict[str, Any]],
        symbol: str,
    ) -> Optional[
        dict[str, Any]
    ]:
        """
        Localiza um ticker no mapa retornado pelo BinanceService.

        Tenta primeiro o símbolo normalizado e depois algumas
        variações para aumentar a compatibilidade.
        """

        if not tickers:

            return None

        ticker = tickers.get(
            symbol
        )

        if ticker is not None:

            return ticker

        compact = symbol.replace(
            "/",
            "",
        )

        ticker = tickers.get(
            compact
        )

        if ticker is not None:

            return ticker

        hyphen = symbol.replace(
            "/",
            "-",
        )

        ticker = tickers.get(
            hyphen
        )

        if ticker is not None:

            return ticker

        # Último fallback: comparar normalizado.

        for key, value in tickers.items():

            try:

                key_normalizado = (
                    str(key)
                    .strip()
                    .upper()
                    .replace("-", "/")
                )

                if (
                    "/" not in key_normalizado
                    and key_normalizado.endswith("USDT")
                ):

                    key_normalizado = (
                        f"{key_normalizado[:-4]}/USDT"
                    )

                if key_normalizado == symbol:

                    return value

            except Exception:

                continue

        return None

    # ==========================================================
    # PROCESSAR TODOS
    # ==========================================================

    def processar_todos(
        self,
        symbols: Optional[
            list[str]
        ] = None,
        intervalos: Optional[
            list[str]
        ] = None,
        salvar: bool = True,
    ) -> dict[str, Any]:
        """
        Processa todos os símbolos em todos os timeframes
        informados.

        Símbolos e tickers são carregados uma única vez e
        reutilizados entre os timeframes.
        """

        # ======================================================
        # INTERVALOS
        # ======================================================

        if intervalos is None:

            intervalos = list(
                self.TIMEFRAMES_PERMITIDOS
            )

        # ======================================================
        # VALIDAR INTERVALOS
        # ======================================================

        for intervalo in intervalos:

            self._validar_intervalo(
                intervalo
            )

        # ======================================================
        # SÍMBOLOS
        # ======================================================

        if symbols is None:

            symbols = (
                self.binance.get_usdt_symbols()
            )

        # ======================================================
        # TICKERS
        # ======================================================

        tickers = (
            self.binance.get_tickers()
        )

        # ======================================================
        # RESULTADOS
        # ======================================================

        all_results: list[
            dict[str, Any]
        ] = []

        all_errors: list[
            dict[str, Any]
        ] = []

        # ======================================================
        # PROCESSAR INTERVALOS
        # ======================================================

        for intervalo in intervalos:

            resultado = (
                self.processar_intervalo(
                    intervalo=intervalo,
                    symbols=symbols,
                    tickers=tickers,
                    salvar=salvar,
                )
            )

            all_results.extend(
                resultado[
                    "results"
                ]
            )

            all_errors.extend(
                resultado[
                    "errors"
                ]
            )

        # ======================================================
        # RETORNO
        # ======================================================

        return {
            "results": all_results,
            "errors": all_errors,
            "total_results": len(
                all_results
            ),
            "total_errors": len(
                all_errors
            ),
        }

    # ==========================================================
    # SALVAR / ATUALIZAR RESULTADO
    # ==========================================================

    def _salvar_resultado(
        self,
        resultado: dict[str, Any],
    ) -> int:
        """
        Persiste o resultado no PostgreSQL.

        Chave lógica do candle:

            symbol
            intervalo
            timestamp

        Se já existir:

            UPDATE

        Caso contrário:

            INSERT
        """

        symbol = resultado[
            "symbol"
        ]

        intervalo = resultado[
            "intervalo"
        ]

        timestamp = resultado[
            "timestamp"
        ]

        # ======================================================
        # BUSCAR CANDLE
        # ======================================================

        existente = (
            self.repository.buscar_por_candle(
                symbol=symbol,
                intervalo=intervalo,
                timestamp=timestamp,
            )
        )

        # ======================================================
        # UPDATE
        # ======================================================

        if existente is not None:

            logger.debug(
                "Candle existente. Atualizando | "
                "symbol=%s | "
                "intervalo=%s | "
                "timestamp=%s",
                symbol,
                intervalo,
                timestamp,
            )

            registro = self.repository.atualizar(
                existente,

                rsi=resultado[
                    "rsi"
                ],

                rsi_previous=resultado[
                    "rsi_previous"
                ],

                rsi_difference=resultado[
                    "rsi_difference"
                ],

                rsi_status=resultado[
                    "rsi_status"
                ],

                signal_type=resultado[
                    "signal_type"
                ],

                signal_level=resultado[
                    "signal_level"
                ],

                current_price=resultado[
                    "current_price"
                ],

                change_24h=resultado[
                    "change_24h"
                ],

                volume_24h=resultado[
                    "volume_24h"
                ],

                market_cap=resultado[
                    "market_cap"
                ],

                ranking=resultado[
                    "ranking"
                ],
            )

            logger.info(
                "RSI atualizado | "
                "symbol=%s | "
                "intervalo=%s | "
                "RSI=%s | "
                "market_cap=%s | "
                "ranking=%s",
                symbol,
                intervalo,
                resultado["rsi"],
                resultado["market_cap"],
                resultado["ranking"],
            )

            self.snapshot_repository.atualizar(
                symbol=symbol,
                intervalo=intervalo,
                rsi_data_id=registro.id,
            )

            return registro.id

        # ======================================================
        # INSERT
        # ======================================================

        registro = self.repository.criar(
            symbol=symbol,

            intervalo=intervalo,

            rsi=resultado[
                "rsi"
            ],

            rsi_previous=resultado[
                "rsi_previous"
            ],

            rsi_difference=resultado[
                "rsi_difference"
            ],

            timestamp=timestamp,

            rsi_status=resultado[
                "rsi_status"
            ],

            signal_type=resultado[
                "signal_type"
            ],

            signal_level=resultado[
                "signal_level"
            ],

            current_price=resultado[
                "current_price"
            ],

            change_24h=resultado[
                "change_24h"
            ],

            volume_24h=resultado[
                "volume_24h"
            ],

            market_cap=resultado[
                "market_cap"
            ],

            ranking=resultado[
                "ranking"
            ],
        )

        logger.info(
            "Novo RSI salvo | "
            "symbol=%s | "
            "intervalo=%s | "
            "RSI=%s | "
            "market_cap=%s | "
            "ranking=%s",
            symbol,
            intervalo,
            resultado["rsi"],
            resultado["market_cap"],
            resultado["ranking"],
        )

        self.snapshot_repository.atualizar(
            symbol=symbol,
            intervalo=intervalo,
            rsi_data_id=registro.id,
        )

        return registro.id

    # ==========================================================
    # EXTRAIR DADOS DO TICKER
    # ==========================================================

    @staticmethod
    def _extrair_dados_ticker(
        symbol: str,
        ticker: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Extrai dados relevantes do ticker CCXT.

        Retorna:

            current_price
            change_24h
            volume_24h
        """

        if not ticker:

            raise ValueError(
                f"Ticker vazio para {symbol}."
            )

        # ======================================================
        # PREÇO
        # ======================================================

        current_price = ticker.get(
            "last"
        )

        if current_price is None:

            current_price = ticker.get(
                "close"
            )

        if current_price is None:

            raise ValueError(
                f"Preço atual não disponível "
                f"para {symbol}."
            )

        try:

            current_price = float(
                current_price
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise ValueError(
                f"Preço atual inválido "
                f"para {symbol}: {current_price}"
            ) from exc

        if current_price <= 0:

            raise ValueError(
                f"Preço atual inválido "
                f"para {symbol}: {current_price}"
            )

        # ======================================================
        # VARIAÇÃO 24H
        # ======================================================

        change_24h = ticker.get(
            "percentage"
        )

        if change_24h is not None:

            try:

                change_24h = float(
                    change_24h
                )

            except (
                TypeError,
                ValueError,
            ):

                logger.warning(
                    "Variação 24h inválida | "
                    "symbol=%s | valor=%s",
                    symbol,
                    change_24h,
                )

                change_24h = None

        # ======================================================
        # VOLUME 24H
        # ======================================================

        volume_24h = ticker.get(
            "quoteVolume"
        )

        if volume_24h is None:

            base_volume = ticker.get(
                "baseVolume"
            )

            if base_volume is not None:

                try:

                    volume_24h = (
                        float(base_volume)
                        * current_price
                    )

                except (
                    TypeError,
                    ValueError,
                ):

                    volume_24h = None

        elif volume_24h is not None:

            try:

                volume_24h = float(
                    volume_24h
                )

            except (
                TypeError,
                ValueError,
            ):

                logger.warning(
                    "Volume 24h inválido | "
                    "symbol=%s | valor=%s",
                    symbol,
                    volume_24h,
                )

                volume_24h = None

        # ======================================================
        # RETORNO
        # ======================================================

        return {
            "symbol": symbol,

            "current_price": current_price,

            "change_24h": change_24h,

            "volume_24h": volume_24h,
        }

    # ==========================================================
    # TIMESTAMP
    # ==========================================================

    @staticmethod
    def _timestamp_para_datetime(
        timestamp_ms: int | float,
    ) -> datetime:
        """
        Converte timestamp da Binance em milissegundos
        para datetime UTC sem timezone.

        O PostgreSQL atual utiliza DateTime sem timezone.
        """

        try:

            timestamp = float(
                timestamp_ms
            )

        except (
            TypeError,
            ValueError,
        ) as exc:

            raise ValueError(
                f"Timestamp inválido: {timestamp_ms}"
            ) from exc

        if timestamp <= 0:

            raise ValueError(
                f"Timestamp inválido: {timestamp_ms}"
            )

        return datetime.fromtimestamp(
            timestamp / 1000,
            tz=timezone.utc,
        ).replace(
            tzinfo=None
        )

    # ==========================================================
    # VALIDAR INTERVALO
    # ==========================================================

    def _validar_intervalo(
        self,
        intervalo: str,
    ) -> None:
        """
        Valida o timeframe informado.
        """

        if not intervalo:

            raise ValueError(
                "Timeframe não informado."
            )

        intervalo = str(
            intervalo
        ).strip()

        if intervalo not in (
            self.TIMEFRAMES_PERMITIDOS
        ):

            raise ValueError(
                f"Timeframe inválido: "
                f"{intervalo}. "
                f"Permitidos: "
                f"{list(self.TIMEFRAMES_PERMITIDOS)}"
            )


# ==============================================================
# INSTÂNCIA PADRÃO
# ==============================================================

rsi_service = RSIService()
