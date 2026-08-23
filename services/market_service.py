# services/market_service.py

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import requests


logger = logging.getLogger(__name__)


class MarketService:
    """
    Serviço responsável por obter dados de mercado da CoinGecko.

    Dados fornecidos:

        - market_cap
        - ranking

    Arquitetura:

        RSIService
              │
              ▼
        MarketService
              │
              ├── Cache em memória
              │
              └── CoinGecko API

    O serviço utiliza o endpoint /coins/markets para carregar
    dados de vários ativos em lote.

    Características:

        - cache em memória
        - TTL configurável
        - paginação configurável
        - retry para erros temporários
        - tratamento de HTTP 429
        - suporte ao header Retry-After
        - fallback para cache antigo
        - atualização atômica do cache
        - normalização de símbolos Binance
        - thread-safe através de RLock
    """

    BASE_URL = (
        "https://api.coingecko.com/api/v3"
    )

    MARKETS_ENDPOINT = (
        "/coins/markets"
    )

    VS_CURRENCY = "usd"

    # ==========================================================
    # CACHE
    # ==========================================================

    DEFAULT_CACHE_TTL = 300

    # Para o projeto atual, uma página é suficiente para obter
    # os principais ativos por market cap.
    #
    # 1 página = até 250 moedas.
    #
    # Isso reduz drasticamente o risco de rate limit da CoinGecko.

    DEFAULT_MAX_PAGES = 1

    PER_PAGE = 250

    # ==========================================================
    # REQUEST
    # ==========================================================

    DEFAULT_TIMEOUT = 15

    # Quantidade máxima de tentativas por requisição.
    #
    # Exemplo:
    #
    # tentativa 1
    # tentativa 2
    # tentativa 3
    #
    DEFAULT_MAX_RETRIES = 2

    # Delay inicial utilizado no backoff exponencial.
    #
    # retry 1 -> 1s
    # retry 2 -> 2s
    #
    DEFAULT_RETRY_DELAY = 1.0

    # Status HTTP que podem indicar uma falha temporária.

    RETRYABLE_STATUS_CODES = (
        408,
        429,
        500,
        502,
        503,
        504,
    )

    # ==========================================================
    # CONSTRUTOR
    # ==========================================================

    def __init__(
        self,
        cache_ttl: Optional[int] = None,
        timeout: Optional[int] = None,
        max_pages: Optional[int] = None,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ) -> None:
        """
        Inicializa o MarketService.

        Args:
            cache_ttl:
                Tempo do cache em segundos.

            timeout:
                Timeout HTTP da CoinGecko.

            max_pages:
                Quantidade máxima de páginas consultadas.

            max_retries:
                Quantidade de retries após a primeira tentativa.

            retry_delay:
                Delay inicial do backoff exponencial.
        """

        self.cache_ttl = (
            cache_ttl
            if cache_ttl is not None
            else self.DEFAULT_CACHE_TTL
        )

        self.timeout = (
            timeout
            if timeout is not None
            else self.DEFAULT_TIMEOUT
        )

        self.max_pages = (
            max_pages
            if max_pages is not None
            else self.DEFAULT_MAX_PAGES
        )

        self.max_retries = (
            max_retries
            if max_retries is not None
            else self.DEFAULT_MAX_RETRIES
        )

        self.retry_delay = (
            retry_delay
            if retry_delay is not None
            else self.DEFAULT_RETRY_DELAY
        )

        if self.cache_ttl < 0:
            raise ValueError(
                "cache_ttl não pode ser negativo."
            )

        if self.timeout <= 0:
            raise ValueError(
                "timeout deve ser maior que zero."
            )

        if self.max_pages <= 0:
            raise ValueError(
                "max_pages deve ser maior que zero."
            )

        if self.max_retries < 0:
            raise ValueError(
                "max_retries não pode ser negativo."
            )

        if self.retry_delay < 0:
            raise ValueError(
                "retry_delay não pode ser negativo."
            )

        # ======================================================
        # CACHE PRINCIPAL
        # ======================================================

        self._cache: dict[
            str,
            dict[str, Any],
        ] = {}

        # ======================================================
        # CONTROLE DO CACHE
        # ======================================================

        self._cache_timestamp: float = 0.0

        # ======================================================
        # LOCK
        # ======================================================

        self._lock = threading.RLock()

        # ======================================================
        # SESSION HTTP
        # ======================================================

        self.session = requests.Session()

        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "API-RSI/1.0 "
                    "(MarketDataService)"
                ),
            }
        )

        logger.info(
            "MarketService inicializado | "
            "cache_ttl=%ss | "
            "timeout=%ss | "
            "max_pages=%s | "
            "max_retries=%s | "
            "retry_delay=%ss",
            self.cache_ttl,
            self.timeout,
            self.max_pages,
            self.max_retries,
            self.retry_delay,
        )

    # ==========================================================
    # NORMALIZAR SYMBOL
    # ==========================================================

    @staticmethod
    def _normalizar_symbol(
        symbol: str,
    ) -> str:
        """
        Normaliza símbolos da Binance.

        Exemplos:

            BTC/USDT
            BTCUSDT
            BTC-USDT

        Todos são convertidos internamente para:

            BTC
        """

        if not symbol:
            return ""

        symbol = str(
            symbol
        ).strip().upper()

        symbol = symbol.replace(
            "/",
            "",
        )

        symbol = symbol.replace(
            "-",
            "",
        )

        if symbol.endswith(
            "USDT"
        ):
            symbol = symbol[
                :-4
            ]

        return symbol

    # ==========================================================
    # CACHE VÁLIDO
    # ==========================================================

    def _cache_valido(
        self,
    ) -> bool:
        """
        Verifica se o cache ainda está dentro do TTL.
        """

        if not self._cache:
            return False

        if self._cache_timestamp <= 0:
            return False

        idade = (
            time.monotonic()
            - self._cache_timestamp
        )

        return idade < self.cache_ttl

    # ==========================================================
    # CACHE EXISTENTE
    # ==========================================================

    def _cache_disponivel(
        self,
    ) -> bool:
        """
        Verifica se existe algum cache disponível.

        Diferente de _cache_valido(), este método considera
        também cache expirado.

        Isso permite utilizar o último snapshot conhecido
        quando a CoinGecko estiver indisponível.
        """

        return bool(
            self._cache
        )

    # ==========================================================
    # IDADE DO CACHE
    # ==========================================================

    def _cache_idade(
        self,
    ) -> Optional[float]:
        """
        Retorna a idade do cache em segundos.
        """

        if self._cache_timestamp <= 0:
            return None

        return (
            time.monotonic()
            - self._cache_timestamp
        )

    # ==========================================================
    # LIMPAR CACHE
    # ==========================================================

    def limpar_cache(
        self,
    ) -> None:
        """
        Limpa completamente o cache.
        """

        with self._lock:

            self._cache.clear()

            self._cache_timestamp = 0.0

        logger.info(
            "Cache do MarketService limpo."
        )

    # ==========================================================
    # ESTATÍSTICAS DO CACHE
    # ==========================================================

    def cache_info(
        self,
    ) -> dict[str, Any]:
        """
        Retorna informações sobre o cache.
        """

        with self._lock:

            idade = (
                self._cache_idade()
            )

            return {
                "items": len(
                    self._cache
                ),
                "ttl": self.cache_ttl,
                "age": idade,
                "valid": self._cache_valido(),
                "available": self._cache_disponivel(),
                "max_pages": self.max_pages,
            }

    # ==========================================================
    # RETRY-AFTER
    # ==========================================================

    @staticmethod
    def _obter_retry_after(
        response: requests.Response,
    ) -> Optional[float]:
        """
        Obtém o valor do header Retry-After.

        O header pode informar:

            Retry-After: 5

        indicando que devemos aguardar 5 segundos.

        Caso o header não exista ou seja inválido, retorna None.
        """

        valor = response.headers.get(
            "Retry-After"
        )

        if not valor:
            return None

        try:
            segundos = float(
                valor
            )

            if segundos < 0:
                return None

            return segundos

        except (
            TypeError,
            ValueError,
        ):
            return None

    # ==========================================================
    # DELAY RETRY
    # ==========================================================

    def _calcular_retry_delay(
        self,
        tentativa: int,
    ) -> float:
        """
        Calcula delay utilizando backoff exponencial.

        Exemplo com retry_delay=1:

            tentativa 1 -> 1s
            tentativa 2 -> 2s
            tentativa 3 -> 4s
        """

        return (
            self.retry_delay
            * (
                2 ** tentativa
            )
        )

    # ==========================================================
    # REQUEST COINGECKO
    # ==========================================================

    def _buscar_pagina(
        self,
        page: int,
    ) -> list[dict[str, Any]]:
        """
        Busca uma página da CoinGecko.

        Possui retry para:

            - HTTP 408
            - HTTP 429
            - HTTP 500
            - HTTP 502
            - HTTP 503
            - HTTP 504
            - erros de conexão
            - timeout

        Em caso de falha definitiva, retorna [].

        Isso permite que _carregar_cache() preserve o cache
        anterior quando disponível.
        """

        url = (
            self.BASE_URL
            + self.MARKETS_ENDPOINT
        )

        params = {
            "vs_currency": self.VS_CURRENCY,
            "order": "market_cap_desc",
            "per_page": self.PER_PAGE,
            "page": page,
            "sparkline": "false",
        }

        total_tentativas = (
            self.max_retries + 1
        )

        for tentativa in range(
            total_tentativas
        ):

            try:

                logger.debug(
                    "Consultando CoinGecko | "
                    "page=%s | tentativa=%s/%s",
                    page,
                    tentativa + 1,
                    total_tentativas,
                )

                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                )

                status = (
                    response.status_code
                )

                # ==================================================
                # SUCESSO
                # ==================================================

                if status == 200:

                    data = response.json()

                    if not isinstance(
                        data,
                        list,
                    ):

                        logger.warning(
                            "Resposta inesperada "
                            "da CoinGecko | page=%s",
                            page,
                        )

                        return []

                    return data

                # ==================================================
                # RATE LIMIT / ERRO TEMPORÁRIO
                # ==================================================

                if status in (
                    self.RETRYABLE_STATUS_CODES
                ):

                    ultima_tentativa = (
                        tentativa
                        >= total_tentativas - 1
                    )

                    if ultima_tentativa:

                        logger.warning(
                            "CoinGecko retornou "
                            "HTTP %s após %s tentativa(s) "
                            "| page=%s",
                            status,
                            total_tentativas,
                            page,
                        )

                        return []

                    retry_after = (
                        self._obter_retry_after(
                            response
                        )
                    )

                    if retry_after is not None:

                        delay = retry_after

                    else:

                        delay = (
                            self._calcular_retry_delay(
                                tentativa
                            )
                        )

                    logger.warning(
                        "CoinGecko retornou HTTP %s "
                        "| page=%s | "
                        "aguardando %.2fs antes do retry.",
                        status,
                        page,
                        delay,
                    )

                    if delay > 0:

                        time.sleep(
                            delay
                        )

                    continue

                # ==================================================
                # ERRO NÃO RECUPERÁVEL
                # ==================================================

                logger.warning(
                    "CoinGecko retornou "
                    "HTTP %s | page=%s",
                    status,
                    page,
                )

                response.raise_for_status()

                return []

            except requests.RequestException as exc:

                ultima_tentativa = (
                    tentativa
                    >= total_tentativas - 1
                )

                if ultima_tentativa:

                    logger.warning(
                        "Erro HTTP ao consultar "
                        "CoinGecko | page=%s | "
                        "tentativas=%s | erro=%s",
                        page,
                        total_tentativas,
                        exc,
                    )

                    return []

                delay = (
                    self._calcular_retry_delay(
                        tentativa
                    )
                )

                logger.warning(
                    "Erro temporário ao consultar "
                    "CoinGecko | page=%s | "
                    "aguardando %.2fs | erro=%s",
                    page,
                    delay,
                    exc,
                )

                if delay > 0:

                    time.sleep(
                        delay
                    )

            except ValueError as exc:

                logger.warning(
                    "CoinGecko retornou JSON inválido "
                    "| page=%s | erro=%s",
                    page,
                    exc,
                )

                return []

            except Exception as exc:

                logger.exception(
                    "Erro inesperado ao consultar "
                    "CoinGecko | page=%s | erro=%s",
                    page,
                    exc,
                )

                return []

        return []

    # ==========================================================
    # NORMALIZAR DADOS DA MOEDA
    # ==========================================================

    @staticmethod
    def _normalizar_coin(
        coin: dict[str, Any],
    ) -> Optional[
        tuple[
            str,
            dict[str, Any],
        ]
    ]:
        """
        Normaliza os dados retornados pela CoinGecko.

        Retorna:

            (
                symbol_normalizado,
                {
                    "market_cap": ...,
                    "ranking": ...
                }
            )

        ou None quando os dados são inválidos.
        """

        symbol = coin.get(
            "symbol"
        )

        if not symbol:
            return None

        symbol_normalizado = (
            MarketService._normalizar_symbol(
                symbol
            )
        )

        if not symbol_normalizado:
            return None

        market_cap = coin.get(
            "market_cap"
        )

        if market_cap is not None:

            try:

                market_cap = float(
                    market_cap
                )

            except (
                TypeError,
                ValueError,
            ):

                market_cap = None

        market_cap_rank = coin.get(
            "market_cap_rank"
        )

        if market_cap_rank is not None:

            try:

                market_cap_rank = int(
                    market_cap_rank
                )

            except (
                TypeError,
                ValueError,
            ):

                market_cap_rank = None

        return (
            symbol_normalizado,
            {
                "market_cap": market_cap,
                "ranking": market_cap_rank,
            },
        )

    # ==========================================================
    # CONSTRUIR CACHE
    # ==========================================================

    def _carregar_cache(
        self,
    ) -> bool:
        """
        Atualiza o cache utilizando dados da CoinGecko.

        Regras:

            1. Se o cache ainda estiver válido, não consulta.
            2. Consulta as páginas configuradas.
            3. Se houver dados, atualiza o cache atomicamente.
            4. Se a CoinGecko falhar e já existir cache antigo,
               preserva o cache antigo.
            5. Nunca substitui um cache existente por um cache vazio.

        Retorna:

            True  -> cache disponível após a operação.
            False -> não foi possível obter nenhum dado.
        """

        with self._lock:

            # --------------------------------------------------
            # DOUBLE CHECK
            # --------------------------------------------------

            if self._cache_valido():

                logger.debug(
                    "Cache CoinGecko ainda válido. "
                    "Nenhuma chamada necessária."
                )

                return True

            tinha_cache_anterior = (
                self._cache_disponivel()
            )

            cache_anterior = (
                self._cache
            )

            logger.info(
                "Atualizando cache CoinGecko..."
            )

            novo_cache: dict[
                str,
                dict[str, Any],
            ] = {}

            try:

                for page in range(
                    1,
                    self.max_pages + 1,
                ):

                    dados = (
                        self._buscar_pagina(
                            page
                        )
                    )

                    # --------------------------------------------------
                    # FALHA / RATE LIMIT
                    # --------------------------------------------------

                    if not dados:

                        logger.warning(
                            "Nenhum dado retornado "
                            "pela CoinGecko | page=%s",
                            page,
                        )

                        break

                    for coin in dados:

                        if not isinstance(
                            coin,
                            dict,
                        ):
                            continue

                        normalizado = (
                            self._normalizar_coin(
                                coin
                            )
                        )

                        if normalizado is None:
                            continue

                        (
                            symbol_normalizado,
                            data,
                        ) = normalizado

                        novo_cache[
                            symbol_normalizado
                        ] = data

                    logger.debug(
                        "Página CoinGecko processada | "
                        "page=%s | items=%s | "
                        "cache_acumulado=%s",
                        page,
                        len(dados),
                        len(novo_cache),
                    )

                    # --------------------------------------------------
                    # PÁGINA INCOMPLETA
                    # --------------------------------------------------

                    if len(
                        dados
                    ) < self.PER_PAGE:

                        break

                # --------------------------------------------------
                # NENHUM DADO NOVO
                # --------------------------------------------------

                if not novo_cache:

                    if tinha_cache_anterior:

                        logger.warning(
                            "CoinGecko indisponível. "
                            "Mantendo cache anterior | "
                            "moedas=%d | idade=%.2fs",
                            len(cache_anterior),
                            self._cache_idade()
                            or 0.0,
                        )

                        return True

                    logger.warning(
                        "CoinGecko não retornou "
                        "dados e não existe cache anterior."
                    )

                    return False

                # --------------------------------------------------
                # ATUALIZAÇÃO ATÔMICA
                # --------------------------------------------------

                self._cache = novo_cache

                self._cache_timestamp = (
                    time.monotonic()
                )

                logger.info(
                    "Cache CoinGecko atualizado | "
                    "moedas=%d | ttl=%ss",
                    len(self._cache),
                    self.cache_ttl,
                )

                return True

            except requests.RequestException as exc:

                logger.warning(
                    "Erro HTTP ao atualizar "
                    "cache CoinGecko | %s",
                    exc,
                )

                if tinha_cache_anterior:

                    logger.warning(
                        "Mantendo cache anterior "
                        "após falha da CoinGecko."
                    )

                    return True

                return False

            except Exception as exc:

                logger.exception(
                    "Erro inesperado ao atualizar "
                    "cache CoinGecko | %s",
                    exc,
                )

                if tinha_cache_anterior:

                    logger.warning(
                        "Mantendo cache anterior "
                        "após erro inesperado."
                    )

                    return True

                return False

    # ==========================================================
    # PRECARREGAR MARKET DATA
    # ==========================================================

    def precarregar_market_data(
        self,
        symbols: Optional[
            list[str]
        ] = None,
    ) -> dict[
        str,
        dict[str, Any],
    ]:
        """
        Precarrega os dados de mercado.

        Se symbols for informado, retorna somente os símbolos
        solicitados.

        A CoinGecko somente é consultada quando o cache
        estiver expirado.

        Se a CoinGecko estiver indisponível, o cache antigo
        continuará sendo utilizado quando existir.
        """

        sucesso = (
            self._carregar_cache()
        )

        if not sucesso:

            logger.warning(
                "Não foi possível atualizar "
                "o cache CoinGecko."
            )

        # ------------------------------------------------------
        # SEM SYMBOLS
        # ------------------------------------------------------

        if symbols is None:

            with self._lock:

                return {
                    symbol: dict(data)
                    for symbol, data
                    in self._cache.items()
                }

        # ------------------------------------------------------
        # FILTRAR SYMBOLS
        # ------------------------------------------------------

        resultado: dict[
            str,
            dict[str, Any],
        ] = {}

        with self._lock:

            for symbol in symbols:

                normalizado = (
                    self._normalizar_symbol(
                        symbol
                    )
                )

                if not normalizado:
                    continue

                data = self._cache.get(
                    normalizado
                )

                if data is None:
                    continue

                resultado[
                    symbol
                ] = dict(
                    data
                )

        return resultado

    # ==========================================================
    # GET MARKET DATA
    # ==========================================================

    def get_market_data(
        self,
        symbol: str,
    ) -> Optional[
        dict[str, Any]
    ]:
        """
        Retorna market cap e ranking de um símbolo.

        Não realiza chamada individual por moeda.

        Fluxo:

            get_market_data()
                    │
                    ▼
              cache válido?
                 /     \
               sim     não
                │       │
                ▼       ▼
             retorna  atualiza
                         │
                         ▼
                       cache
                         │
                         ▼
                       busca
        """

        if not symbol:
            return None

        normalizado = (
            self._normalizar_symbol(
                symbol
            )
        )

        if not normalizado:
            return None

        # ------------------------------------------------------
        # GARANTIR CACHE
        # ------------------------------------------------------

        if not self._cache_valido():

            sucesso = (
                self._carregar_cache()
            )

            if not sucesso:

                logger.warning(
                    "Não foi possível obter "
                    "dados da CoinGecko | "
                    "symbol=%s",
                    symbol,
                )

        # ------------------------------------------------------
        # BUSCAR NO CACHE
        # ------------------------------------------------------

        with self._lock:

            data = self._cache.get(
                normalizado
            )

            if data is None:

                logger.debug(
                    "Criptomoeda não encontrada "
                    "no cache CoinGecko | "
                    "symbol=%s | "
                    "normalizado=%s",
                    symbol,
                    normalizado,
                )

                return None

            return dict(
                data
            )

    # ==========================================================
    # CLOSE
    # ==========================================================

    def close(
        self,
    ) -> None:
        """
        Fecha a sessão HTTP.
        """

        try:

            self.session.close()

            logger.debug(
                "Sessão HTTP do MarketService encerrada."
            )

        except Exception as exc:

            logger.debug(
                "Erro ao fechar sessão "
                "do MarketService | %s",
                exc,
            )


# ==============================================================
# SINGLETON
# ==============================================================

market_service = MarketService()