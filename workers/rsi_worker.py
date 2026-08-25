from __future__ import annotations

import logging
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app import create_app

from app.services.rsi_service import (
    RSIService,
    rsi_service,
)
from app.services.signal_alert_service import (
    SignalAlertService,
    signal_alert_service,
)

from services.binance_service import (
    BinanceService,
    binance_service,
)

from services.market_service import (
    MarketService,
    market_service,
)


logger = logging.getLogger(__name__)


class RSIWorker:
    """
    Worker responsável pelo processamento automático do RSI.

    O Worker é responsável pela ORQUESTRAÇÃO.

    Fluxo:

        Relógio UTC
             ↓
        Timeframe vencido?
             ↓
        Binance
             ↓
        símbolos
             ↓
        tickers
             ↓
        MarketService
             ↓
        RSIService
             ↓
        PostgreSQL

    Estratégia de execução:

        O Worker NÃO executa todos os timeframes a cada 60 segundos.

        Cada timeframe é executado somente quando seu candle
        correspondente estiver fechado.

    Exemplos:

        5m  → a cada fechamento de candle de 5 minutos
        15m → a cada fechamento de candle de 15 minutos
        30m → a cada fechamento de candle de 30 minutos
        1h  → a cada fechamento de candle de 1 hora
        4h  → a cada fechamento de candle de 4 horas
        12h → a cada fechamento de candle de 12 horas
        1d  → a cada fechamento diário
        1w  → a cada fechamento semanal
        1M  → a cada fechamento mensal

    O Worker não possui lógica de:

        - cálculo do RSI;
        - classificação do RSI;
        - Telegram;
        - Redis;
        - persistência direta no banco;
        - regras de negócio do RSI.
    """

    # ==========================================================
    # CONFIGURAÇÕES
    # ==========================================================

    DEFAULT_INTERVALOS = (
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
    # Intervalo de verificação do relógio.
    #
    # Isso NÃO significa que o processamento acontece a cada
    # segundo.
    #
    # O Worker apenas verifica se algum timeframe está vencido.
    # ----------------------------------------------------------

    DEFAULT_CHECK_INTERVAL_SECONDS = 1

    # ----------------------------------------------------------
    # Pequena margem após o fechamento do candle.
    #
    # Exemplo:
    #
    # candle fecha 15:00:00
    # Worker processa a partir de aproximadamente 15:00:05
    #
    # Isso reduz o risco de consultar a Binance exatamente no
    # instante em que o candle acabou de fechar.
    # ----------------------------------------------------------

    DEFAULT_CANDLE_CLOSE_DELAY_SECONDS = 5

    # ----------------------------------------------------------
    # Retry para falhas temporárias.
    # ----------------------------------------------------------

    DEFAULT_MAX_RETRIES = 2

    DEFAULT_RETRY_DELAY_SECONDS = 3

    # ----------------------------------------------------------
    # Concorrência.
    #
    # Por segurança, o padrão é 1.
    #
    # A Binance possui rate limits e o RSIService executa várias
    # chamadas de OHLCV.
    #
    # A implementação suporta processamento paralelo controlado,
    # mas NÃO é ativada por padrão.
    # ----------------------------------------------------------

    DEFAULT_MAX_TIMEFRAME_WORKERS = 1

    # ==========================================================
    # CONSTRUTOR
    # ==========================================================

    def __init__(
        self,
        intervalos: Optional[
            list[str]
        ] = None,
        intervalo_ciclo: Optional[
            int
        ] = None,
        rsi_service_instance: Optional[
            RSIService
        ] = None,
        binance: Optional[
            BinanceService
        ] = None,
        market: Optional[
            MarketService
        ] = None,
        candle_close_delay_seconds: Optional[
            int
        ] = None,
        max_retries: Optional[
            int
        ] = None,
        retry_delay_seconds: Optional[
            int
        ] = None,
        max_timeframe_workers: Optional[
            int
        ] = None,
        alert_service_instance: Optional[
            SignalAlertService
        ] = None,
        symbols: Optional[
            list[str]
        ] = None,
    ) -> None:
        """
        Inicializa o Worker.

        Args:
            intervalos:
                Timeframes que serão processados.

            intervalo_ciclo:
                Intervalo em segundos utilizado somente para
                verificar o relógio.

                Não representa o intervalo de processamento
                dos timeframes.

            rsi_service_instance:
                Instância do RSIService.

            binance:
                Instância do BinanceService.

            market:
                Instância do MarketService.

            candle_close_delay_seconds:
                Margem após o fechamento do candle.

            max_retries:
                Quantidade máxima de tentativas para falhas
                temporárias de um timeframe.

            retry_delay_seconds:
                Tempo entre tentativas.

            max_timeframe_workers:
                Quantidade máxima de timeframes processados
                simultaneamente.

                Recomenda-se manter 1 até que o rate limit da
                Binance seja devidamente controlado.
        """

        # ------------------------------------------------------
        # SERVIÇOS
        # ------------------------------------------------------

        self.rsi_service = (
            rsi_service_instance
            if rsi_service_instance is not None
            else rsi_service
        )

        self.binance = (
            binance
            if binance is not None
            else getattr(
                self.rsi_service,
                "binance",
                binance_service,
            )
        )

        self.market = (
            market
            if market is not None
            else getattr(
                self.rsi_service,
                "market",
                market_service,
            )
        )

        self.alert_service = (
            alert_service_instance
            if alert_service_instance is not None
            else signal_alert_service
        )

        # ------------------------------------------------------
        # INTERVALOS
        # ------------------------------------------------------

        intervalos_configurados = (
            intervalos
            if intervalos is not None
            else self._csv_env(
                "RSI_WORKER_INTERVALS"
            )
        )

        self.intervalos = self._normalizar_intervalos(
            intervalos_configurados
            or list(
                self.DEFAULT_INTERVALOS
            )
        )

        # Em produção normal, o Worker acompanha todos os pares USDT.
        # Em máquinas pequenas, RSI_WORKER_SYMBOLS permite restringir a
        # coleta a uma lista explícita sem alterar o comportamento padrão.
        symbols_configurados = (
            symbols
            if symbols is not None
            else self._csv_env(
                "RSI_WORKER_SYMBOLS"
            )
        )
        self.symbols_configurados = self._normalizar_symbols(
            symbols_configurados
        )

        # ------------------------------------------------------
        # INTERVALO DE VERIFICAÇÃO
        # ------------------------------------------------------

        self.intervalo_ciclo = (
            intervalo_ciclo
            if intervalo_ciclo is not None
            else self.DEFAULT_CHECK_INTERVAL_SECONDS
        )

        if self.intervalo_ciclo <= 0:

            raise ValueError(
                "intervalo_ciclo deve ser maior que zero."
            )

        # ------------------------------------------------------
        # DELAY APÓS FECHAMENTO
        # ------------------------------------------------------

        self.candle_close_delay_seconds = (
            candle_close_delay_seconds
            if candle_close_delay_seconds is not None
            else self.DEFAULT_CANDLE_CLOSE_DELAY_SECONDS
        )

        if self.candle_close_delay_seconds < 0:

            raise ValueError(
                "candle_close_delay_seconds "
                "não pode ser negativo."
            )

        # ------------------------------------------------------
        # RETRIES
        # ------------------------------------------------------

        self.max_retries = (
            max_retries
            if max_retries is not None
            else self.DEFAULT_MAX_RETRIES
        )

        if self.max_retries < 0:

            raise ValueError(
                "max_retries não pode ser negativo."
            )

        self.retry_delay_seconds = (
            retry_delay_seconds
            if retry_delay_seconds is not None
            else self.DEFAULT_RETRY_DELAY_SECONDS
        )

        if self.retry_delay_seconds < 0:

            raise ValueError(
                "retry_delay_seconds "
                "não pode ser negativo."
            )

        # ------------------------------------------------------
        # CONCORRÊNCIA
        # ------------------------------------------------------

        self.max_timeframe_workers = (
            max_timeframe_workers
            if max_timeframe_workers is not None
            else self.DEFAULT_MAX_TIMEFRAME_WORKERS
        )

        if self.max_timeframe_workers <= 0:

            raise ValueError(
                "max_timeframe_workers "
                "deve ser maior que zero."
            )

        # ------------------------------------------------------
        # ESTADO
        # ------------------------------------------------------

        self.running = False

        self.app = None

        # ------------------------------------------------------
        # CONTROLE DOS TIMEFRAMES
        # ------------------------------------------------------

        self._proxima_execucao: dict[
            str,
            datetime,
        ] = {}

        # ------------------------------------------------------
        # ESTATÍSTICAS
        # ------------------------------------------------------

        self.ultimo_ciclo: Optional[
            datetime
        ] = None

        self.ultimo_resultado: Optional[
            dict[str, Any]
        ] = None

        self.estatisticas_timeframes: dict[
            str,
            dict[str, Any],
        ] = {
            intervalo: self._criar_metricas_timeframe()
            for intervalo in self.intervalos
        }

        logger.info(
            "RSIWorker inicializado | "
            "intervalos=%s | "
            "check=%ss | "
            "delay_candle=%ss | "
            "max_retries=%d | "
            "workers=%d | "
            "symbols_configurados=%d",
            self.intervalos,
            self.intervalo_ciclo,
            self.candle_close_delay_seconds,
            self.max_retries,
            self.max_timeframe_workers,
            len(self.symbols_configurados),
        )

    # ==========================================================
    # MÉTRICAS
    # ==========================================================

    @staticmethod
    def _criar_metricas_timeframe() -> dict[str, Any]:
        """
        Cria estrutura padrão de métricas de um timeframe.
        """

        return {
            "execucoes": 0,
            "sucessos": 0,
            "erros": 0,
            "symbols": 0,
            "resultados": 0,
            "salvos": 0,
            "inserts": 0,
            "updates": 0,
            "duracao_segundos": 0.0,
            "ultima_execucao": None,
            "ultimo_erro": None,
        }

    def _atualizar_metricas_timeframe(
        self,
        intervalo: str,
        *,
        duracao: float,
        symbols: int,
        resultados: int,
        erros: int,
        salvos: int,
        erro: Optional[str] = None,
    ) -> None:
        """
        Atualiza métricas de um timeframe.

        Observação:

        O RSIService atualmente retorna somente "saved".
        Portanto inserts/updates permanecem em zero até que
        o Repository/RSIService passe a informar essa diferença.
        """

        metricas = self.estatisticas_timeframes.setdefault(
            intervalo,
            self._criar_metricas_timeframe(),
        )

        metricas["execucoes"] += 1

        metricas["symbols"] = symbols

        metricas["resultados"] += resultados

        metricas["erros"] += erros

        metricas["salvos"] += salvos

        metricas["duracao_segundos"] = round(
            duracao,
            2,
        )

        metricas["ultima_execucao"] = (
            datetime.now(
                timezone.utc
            )
        )

        if erros == 0:

            metricas["sucessos"] += 1

        if erro is not None:

            metricas["ultimo_erro"] = erro

    # ==========================================================
    # NORMALIZAR INTERVALOS
    # ==========================================================

    @staticmethod
    def _csv_env(
        nome: str,
    ) -> list[str]:
        """Lê uma lista CSV opcional sem considerar valores vazios."""

        valor = os.getenv(
            nome,
            "",
        )

        return [
            item.strip()
            for item in valor.split(",")
            if item.strip()
        ]

    def _normalizar_intervalos(
        self,
        intervalos: list[str],
    ) -> list[str]:
        """
        Normaliza e valida os timeframes.

        Remove duplicados preservando a ordem.
        """

        if not intervalos:

            raise ValueError(
                "É necessário informar pelo menos "
                "um intervalo."
            )

        permitidos = set(
            getattr(
                self.rsi_service,
                "TIMEFRAMES_PERMITIDOS",
                self.DEFAULT_INTERVALOS,
            )
        )

        resultado: list[str] = []

        for intervalo in intervalos:

            if not intervalo:
                continue

            intervalo = str(
                intervalo
            ).strip()

            if not intervalo:
                continue

            if intervalo not in permitidos:

                raise ValueError(
                    "Intervalo inválido: "
                    f"{intervalo}. "
                    f"Permitidos: "
                    f"{sorted(permitidos)}"
                )

            if intervalo not in resultado:

                resultado.append(
                    intervalo
                )

        if not resultado:

            raise ValueError(
                "Nenhum intervalo válido foi informado."
            )

        return resultado

    def _normalizar_symbols(
        self,
        symbols: Optional[
            list[str]
        ],
    ) -> list[str]:
        """Normaliza pares USDT opcionais preservando ordem e unicidade."""

        if not symbols:
            return []

        resultado: list[str] = []

        for symbol in symbols:
            normalizado = self.binance.validar_symbol(
                symbol
            )

            if normalizado not in resultado:
                resultado.append(
                    normalizado
                )

        return resultado

    # ==========================================================
    # PARAR
    # ==========================================================

    def parar(
        self,
        *_args: Any,
    ) -> None:
        """
        Solicita parada controlada do Worker.
        """

        if self.running:

            logger.info(
                "Solicitação de parada recebida."
            )

        self.running = False

    # ==========================================================
    # CONFIGURAR SIGNALS
    # ==========================================================

    def _configurar_signals(
        self,
    ) -> None:
        """
        Configura SIGINT e SIGTERM.

        Permite encerramento controlado.
        """

        try:

            signal.signal(
                signal.SIGINT,
                self.parar,
            )

        except (
            ValueError,
            OSError,
        ):

            logger.debug(
                "Não foi possível configurar "
                "SIGINT neste contexto."
            )

        try:

            signal.signal(
                signal.SIGTERM,
                self.parar,
            )

        except (
            ValueError,
            OSError,
        ):

            logger.debug(
                "Não foi possível configurar "
                "SIGTERM neste contexto."
            )

    # ==========================================================
    # TIMEFRAME → DURAÇÃO
    # ==========================================================

    @staticmethod
    def _intervalo_para_timedelta(
        intervalo: str,
    ) -> Optional[timedelta]:
        """
        Retorna a duração dos timeframes que possuem duração
        fixa.

        Timeframes especiais:

            1w
            1M

        são tratados separadamente.
        """

        mapa = {
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "12h": timedelta(hours=12),
            "1d": timedelta(days=1),
        }

        return mapa.get(
            intervalo
        )

    # ==========================================================
    # PRÓXIMO FECHAMENTO
    # ==========================================================

    @classmethod
    def _calcular_proximo_fechamento(
        cls,
        intervalo: str,
        agora: datetime,
    ) -> datetime:
        """
        Calcula o próximo fechamento do candle em UTC.

        A Binance utiliza candles alinhados ao UTC.

        Exemplos:

            5m:
                10:00
                10:05
                10:10

            1h:
                10:00
                11:00
                12:00

            1d:
                00:00 UTC

            1w:
                segunda-feira 00:00 UTC

            1M:
                primeiro dia do próximo mês 00:00 UTC
        """

        if agora.tzinfo is None:

            agora = agora.replace(
                tzinfo=timezone.utc
            )

        else:

            agora = agora.astimezone(
                timezone.utc
            )

        # ------------------------------------------------------
        # TIMEFRAMES FIXOS
        # ------------------------------------------------------

        duracao = cls._intervalo_para_timedelta(
            intervalo
        )

        if duracao is not None:

            if intervalo.endswith("m"):

                minutos = int(
                    intervalo[:-1]
                )

                total_minutos = (
                    agora.hour * 60
                    + agora.minute
                )

                proximo_total = (
                    (
                        total_minutos
                        // minutos
                    )
                    + 1
                ) * minutos

                dias_adicionais = (
                    proximo_total // 1440
                )

                minutos_do_dia = (
                    proximo_total % 1440
                )

                hora = (
                    minutos_do_dia
                    // 60
                )

                minuto = (
                    minutos_do_dia
                    % 60
                )

                resultado = agora.replace(
                    hour=hora,
                    minute=minuto,
                    second=0,
                    microsecond=0,
                )

                if dias_adicionais:

                    resultado += timedelta(
                        days=dias_adicionais
                    )

                return resultado

            # --------------------------------------------------
            # HORAS
            # --------------------------------------------------

            if intervalo.endswith("h"):

                horas = int(
                    intervalo[:-1]
                )

                hora_atual = agora.hour

                proxima_hora = (
                    (
                        hora_atual
                        // horas
                    )
                    + 1
                ) * horas

                if proxima_hora >= 24:

                    return (
                        agora.replace(
                            hour=0,
                            minute=0,
                            second=0,
                            microsecond=0,
                        )
                        + timedelta(days=1)
                    )

                return agora.replace(
                    hour=proxima_hora,
                    minute=0,
                    second=0,
                    microsecond=0,
                )

            # --------------------------------------------------
            # 1 DIA
            # --------------------------------------------------

            if intervalo == "1d":

                return (
                    agora.replace(
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    + timedelta(days=1)
                )

        # ------------------------------------------------------
        # 1 SEMANA
        # ------------------------------------------------------

        if intervalo == "1w":

            dias_ate_segunda = (
                7 - agora.weekday()
            )

            if dias_ate_segunda == 0:

                dias_ate_segunda = 7

            proxima_segunda = (
                agora.replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0,
                )
                + timedelta(
                    days=dias_ate_segunda
                )
            )

            return proxima_segunda

        # ------------------------------------------------------
        # 1 MÊS
        # ------------------------------------------------------

        if intervalo == "1M":

            if agora.month == 12:

                return datetime(
                    year=agora.year + 1,
                    month=1,
                    day=1,
                    tzinfo=timezone.utc,
                )

            return datetime(
                year=agora.year,
                month=agora.month + 1,
                day=1,
                tzinfo=timezone.utc,
            )

        raise ValueError(
            f"Intervalo não suportado: {intervalo}"
        )

    # ==========================================================
    # INICIALIZAR AGENDA
    # ==========================================================

    def _inicializar_agenda(
        self,
    ) -> None:
        """
        Inicializa o próximo fechamento de cada timeframe.

        No primeiro ciclo o Worker NÃO processa todos os
        timeframes imediatamente.

        Ele aguarda o próximo fechamento real de cada candle.
        """

        agora = datetime.now(
            timezone.utc
        )

        self._proxima_execucao.clear()

        for intervalo in self.intervalos:

            proximo_fechamento = (
                self._calcular_proximo_fechamento(
                    intervalo=intervalo,
                    agora=agora,
                )
            )

            execucao = (
                proximo_fechamento
                + timedelta(
                    seconds=self.candle_close_delay_seconds
                )
            )

            self._proxima_execucao[
                intervalo
            ] = execucao

            logger.info(
                "Agenda inicializada | "
                "timeframe=%s | "
                "próxima execução=%s",
                intervalo,
                execucao.isoformat(),
            )

    # ==========================================================
    # OBTER TIMEFRAMES VENCIDOS
    # ==========================================================

    def _obter_timeframes_vencidos(
        self,
        agora: Optional[
            datetime
        ] = None,
    ) -> list[str]:
        """
        Retorna os timeframes cuja próxima execução já venceu.
        """

        if agora is None:

            agora = datetime.now(
                timezone.utc
            )

        vencidos: list[str] = []

        for intervalo in self.intervalos:

            proxima = (
                self._proxima_execucao.get(
                    intervalo
                )
            )

            if proxima is None:

                self._proxima_execucao[
                    intervalo
                ] = (
                    self._calcular_proximo_fechamento(
                        intervalo=intervalo,
                        agora=agora,
                    )
                    + timedelta(
                        seconds=self.candle_close_delay_seconds
                    )
                )

                continue

            if agora >= proxima:

                vencidos.append(
                    intervalo
                )

        return vencidos

    # ==========================================================
    # AVANÇAR AGENDA
    # ==========================================================

    def _agendar_proxima_execucao(
        self,
        intervalo: str,
        agora: Optional[
            datetime
        ] = None,
    ) -> None:
        """
        Agenda o próximo fechamento do timeframe.

        O cálculo é baseado no relógio e não na duração do
        processamento.

        Isso evita drift.

        Exemplo ruim:

            execução
              ↓
            espera 60s
              ↓
            execução
              ↓
            espera 60s

        Exemplo atual:

            10:00 candle
            10:05 candle
            10:10 candle
            10:15 candle
        """

        if agora is None:

            agora = datetime.now(
                timezone.utc
            )

        proximo_fechamento = (
            self._calcular_proximo_fechamento(
                intervalo=intervalo,
                agora=agora,
            )
        )

        self._proxima_execucao[
            intervalo
        ] = (
            proximo_fechamento
            + timedelta(
                seconds=self.candle_close_delay_seconds
            )
        )

    # ==========================================================
    # PRÓXIMA EXECUÇÃO
    # ==========================================================

    def _segundos_ate_proxima_execucao(
        self,
    ) -> float:
        """
        Calcula quanto tempo o Worker pode dormir antes de
        verificar novamente a agenda.
        """

        agora = datetime.now(
            timezone.utc
        )

        proximas = [
            data
            for data in self._proxima_execucao.values()
            if data is not None
        ]

        if not proximas:

            return float(
                self.intervalo_ciclo
            )

        proxima = min(
            proximas
        )

        restante = (
            proxima - agora
        ).total_seconds()

        if restante <= 0:

            return 0.0

        return min(
            restante,
            float(
                self.intervalo_ciclo
            ),
        )

    # ==========================================================
    # OBTER SYMBOLS
    # ==========================================================

    def _obter_symbols(
        self,
    ) -> list[str]:
        """
        Obtém todos os símbolos USDT disponíveis na Binance.

        Remove duplicados preservando a ordem.
        """

        if self.symbols_configurados:

            logger.info(
                "Usando símbolos configurados | total=%d",
                len(self.symbols_configurados),
            )

            return list(
                self.symbols_configurados
            )

        logger.info(
            "Obtendo símbolos USDT da Binance..."
        )

        symbols = (
            self.binance.get_usdt_symbols()
        )

        if not symbols:

            raise RuntimeError(
                "Binance não retornou "
                "símbolos USDT."
            )

        symbols = list(
            dict.fromkeys(
                symbols
            )
        )

        logger.info(
            "Símbolos obtidos | total=%d",
            len(symbols),
        )

        return symbols

    # ==========================================================
    # OBTER TICKERS
    # ==========================================================

    def _aquecer_cache_mercados_binance(
        self,
    ) -> None:
        """Carrega mercados antes do próximo fechamento de candle.

        O CCXT precisa conhecer os mercados antes do primeiro OHLCV. Fazer
        isso durante a inicialização impede que a primeira leitura de RSI
        consuma o prazo máximo de um minuto reservado aos alertas Telegram.
        """

        carregar_mercados = getattr(
            self.binance,
            "carregar_mercados",
            None,
        )
        if not callable(carregar_mercados):
            logger.warning(
                "BinanceService não oferece aquecimento de mercados."
            )
            return

        logger.info("Aquecendo cache de mercados da Binance...")
        inicio = time.monotonic()
        try:
            mercados = carregar_mercados()
        except Exception as exc:
            # A falha de warm-up não pode impedir a recuperação do worker.
            # O serviço mantém o retry normal na primeira consulta de candle.
            logger.warning(
                "Não foi possível aquecer mercados da Binance | erro=%s",
                exc,
            )
            return

        logger.info(
            "Cache de mercados Binance aquecido | total=%d | tempo=%.2fs",
            len(mercados),
            time.monotonic() - inicio,
        )

    def _obter_tickers(
        self,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        """
        Obtém os tickers necessários para o ciclo uma única vez.

        No modo com símbolos configurados, pede somente esses tickers para
        evitar que uma VM pequena mantenha em memória todos os pares da
        Binance. Sem essa configuração, preserva a busca completa atual.
        """

        logger.info(
            "Obtendo tickers da Binance | symbols=%s",
            len(symbols) if self.symbols_configurados else "todos",
        )

        tickers = (
            self.binance.get_tickers(
                symbols=symbols if self.symbols_configurados else None
            )
        )

        if not tickers:

            raise RuntimeError(
                "Binance não retornou "
                "tickers."
            )

        logger.info(
            "Tickers obtidos | total=%d",
            len(tickers),
        )

        return tickers

    # ==========================================================
    # PRECARREGAR MARKET DATA
    # ==========================================================

    def _precarregar_market_data(
        self,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        """
        Precarrega o cache da CoinGecko.

        O MarketService controla o TTL e o rate limit.

        O Worker faz apenas uma chamada por lote/ciclo.
        """

        logger.info(
            "Precarregando Market Data | "
            "symbols=%d",
            len(symbols),
        )

        try:

            market_data = (
                self.market.precarregar_market_data(
                    symbols
                )
            )

            logger.info(
                "Market Data carregado | "
                "encontrados=%d/%d",
                len(market_data),
                len(symbols),
            )

            return market_data

        except Exception as exc:

            logger.exception(
                "Erro ao precarregar Market Data | "
                "%s",
                exc,
            )

            # --------------------------------------------------
            # Market Data é complementar.
            #
            # Não derrubamos o processamento do RSI.
            # --------------------------------------------------

            return {}

    # ==========================================================
    # PROCESSAR TIMEFRAME
    # ==========================================================

    def _processar_timeframe(
        self,
        intervalo: str,
        symbols: list[str],
        tickers: dict[str, dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """
        Processa um único timeframe.

        Retorna:

            results
            errors
        """

        inicio = time.monotonic()

        logger.info(
            "Processando timeframe | "
            "intervalo=%s | "
            "símbolos=%d",
            intervalo,
            len(symbols),
        )

        resultado = (
            self.rsi_service.processar_intervalo(
                intervalo=intervalo,
                symbols=symbols,
                tickers=tickers,
                salvar=True,
            )
        )

        results = resultado.get(
            "results",
            [],
        )

        errors = resultado.get(
            "errors",
            [],
        )

        duracao = (
            time.monotonic()
            - inicio
        )

        salvos = sum(
            1
            for resultado_item in results
            if resultado_item.get(
                "saved",
                False,
            )
        )

        self._atualizar_metricas_timeframe(
            intervalo=intervalo,
            duracao=duracao,
            symbols=len(symbols),
            resultados=len(results),
            erros=len(errors),
            salvos=salvos,
        )

        logger.info(
            "Timeframe concluído | "
            "intervalo=%s | "
            "símbolos=%d | "
            "resultados=%d | "
            "erros=%d | "
            "salvos=%d | "
            "tempo=%.2fs",
            intervalo,
            len(symbols),
            len(results),
            len(errors),
            salvos,
            duracao,
        )

        return (
            results,
            errors,
        )

    # ==========================================================
    # PROCESSAR TIMEFRAME COM RETRY
    # ==========================================================

    def _processar_timeframe_com_retry(
        self,
        intervalo: str,
        symbols: list[str],
        tickers: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Processa um timeframe com retry controlado.

        Uma falha em um timeframe não interrompe os demais.
        """

        tentativa = 0

        ultimo_erro: Optional[
            Exception
        ] = None

        while (
            tentativa
            <= self.max_retries
            and self.running
        ):

            tentativa += 1

            try:

                inicio = time.monotonic()

                results, errors = (
                    self._processar_timeframe(
                        intervalo=intervalo,
                        symbols=symbols,
                        tickers=tickers,
                    )
                )

                duracao = (
                    time.monotonic()
                    - inicio
                )

                return {
                    "intervalo": intervalo,
                    "results": results,
                    "errors": errors,
                    "duracao_segundos": round(
                        duracao,
                        2,
                    ),
                    "tentativas": tentativa,
                    "success": True,
                }

            except Exception as exc:

                ultimo_erro = exc

                logger.exception(
                    "Falha no timeframe | "
                    "intervalo=%s | "
                    "tentativa=%d/%d | %s",
                    intervalo,
                    tentativa,
                    self.max_retries + 1,
                    exc,
                )

                if (
                    tentativa
                    <= self.max_retries
                    and self.running
                ):

                    logger.warning(
                        "Aguardando %ss antes de tentar "
                        "novamente | timeframe=%s",
                        self.retry_delay_seconds,
                        intervalo,
                    )

                    self._aguardar_segundos(
                        self.retry_delay_seconds
                    )

        # ------------------------------------------------------
        # TODAS AS TENTATIVAS FALHARAM
        # ------------------------------------------------------

        erro_texto = (
            str(ultimo_erro)
            if ultimo_erro is not None
            else "Erro desconhecido."
        )

        metricas = (
            self.estatisticas_timeframes.setdefault(
                intervalo,
                self._criar_metricas_timeframe(),
            )
        )

        metricas["erros"] += 1

        metricas["ultimo_erro"] = erro_texto

        return {
            "intervalo": intervalo,
            "results": [],
            "errors": [
                {
                    "intervalo": intervalo,
                    "error": erro_texto,
                    "type": "timeframe_retry_exhausted",
                }
            ],
            "duracao_segundos": 0.0,
            "tentativas": tentativa,
            "success": False,
        }

    # ==========================================================
    # PROCESSAR TIMEFRAMES CONTROLADOS
    # ==========================================================

    def _processar_timeframes(
        self,
        intervalos: list[str],
        symbols: list[str],
        tickers: dict[str, dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """
        Processa os timeframes vencidos.

        Por padrão é sequencial.

        max_timeframe_workers > 1 ativa execução paralela
        controlada.

        Recomenda-se manter:

            max_timeframe_workers=1

        até que o rate limit da Binance esteja devidamente
        controlado.
        """

        resultados: list[
            dict[str, Any]
        ] = []

        erros: list[
            dict[str, Any]
        ] = []

        if not intervalos:

            return (
                resultados,
                erros,
            )

        # ======================================================
        # EXECUÇÃO SEQUENCIAL
        # ======================================================

        if self.max_timeframe_workers == 1:

            for intervalo in intervalos:

                if not self.running:

                    break

                resultado = (
                    self._processar_timeframe_com_retry(
                        intervalo=intervalo,
                        symbols=symbols,
                        tickers=tickers,
                    )
                )

                resultados.extend(
                    resultado["results"]
                )

                erros.extend(
                    resultado["errors"]
                )

                # ------------------------------------------------
                # Agenda o próximo candle independentemente de
                # sucesso ou falha.
                #
                # Caso contrário, um timeframe com problema
                # ficaria eternamente vencido.
                # ------------------------------------------------

                self._agendar_proxima_execucao(
                    intervalo
                )

            return (
                resultados,
                erros,
            )

        # ======================================================
        # EXECUÇÃO PARALELA CONTROLADA
        # ======================================================

        logger.warning(
            "Processamento paralelo habilitado | "
            "workers=%d | "
            "verifique o rate limit da Binance.",
            self.max_timeframe_workers,
        )

        with ThreadPoolExecutor(
            max_workers=self.max_timeframe_workers
        ) as executor:

            futures = {
                executor.submit(
                    self._processar_timeframe_com_retry,
                    intervalo,
                    symbols,
                    tickers,
                ): intervalo
                for intervalo in intervalos
                if self.running
            }

            for future in as_completed(
                futures
            ):

                intervalo = futures[
                    future
                ]

                try:

                    resultado = future.result()

                    resultados.extend(
                        resultado["results"]
                    )

                    erros.extend(
                        resultado["errors"]
                    )

                except Exception as exc:

                    logger.exception(
                        "Falha inesperada em future | "
                        "intervalo=%s | %s",
                        intervalo,
                        exc,
                    )

                    erros.append(
                        {
                            "intervalo": intervalo,
                            "error": str(exc),
                            "type": "future_error",
                        }
                    )

                finally:

                    self._agendar_proxima_execucao(
                        intervalo
                    )

        return (
            resultados,
            erros,
        )

    # ==========================================================
    # PROCESSAR CICLO
    # ==========================================================

    def processar_ciclo(
        self,
        intervalos_vencidos: Optional[
            list[str]
        ] = None,
    ) -> dict[str, Any]:
        """
        Executa um ciclo de processamento.

        IMPORTANTE:

        Este método não significa mais "processar todos os
        timeframes".

        Ele processa somente os timeframes vencidos.

        Fluxo:

            timeframe vencido
                    ↓
                 symbols
                    ↓
                 tickers
                    ↓
               market data
                    ↓
               RSIService
                    ↓
                PostgreSQL
        """

        inicio_monotonic = (
            time.monotonic()
        )

        ciclo_inicio = (
            datetime.now(
                timezone.utc
            )
        )

        if intervalos_vencidos is None:

            intervalos_vencidos = (
                self._obter_timeframes_vencidos(
                    ciclo_inicio
                )
            )

        # ------------------------------------------------------
        # Nenhum timeframe vencido.
        #
        # Não faz nenhuma chamada à Binance.
        # ------------------------------------------------------

        if not intervalos_vencidos:

            return {
                "inicio": ciclo_inicio,
                "fim": ciclo_inicio,
                "duracao_segundos": 0.0,
                "intervalos": [],
                "total_symbols": 0,
                "total_results": 0,
                "total_errors": 0,
                "results": [],
                "errors": [],
                "timeframes": {},
                "nenhum_timeframe_vencido": True,
            }

        logger.info(
            "=================================================="
        )

        logger.info(
            "INICIANDO CICLO RSI"
        )

        logger.info(
            "Timeframes vencidos=%s",
            intervalos_vencidos,
        )

        resultados: list[
            dict[str, Any]
        ] = []

        erros: list[
            dict[str, Any]
        ] = []

        symbols: list[str] = []

        tickers: dict[
            str,
            dict[str, Any],
        ] = {}

        # ======================================================
        # SYMBOLS
        # ======================================================

        try:

            symbols = (
                self._obter_symbols()
            )

        except Exception as exc:

            logger.exception(
                "Falha ao obter símbolos da Binance."
            )

            return self._montar_resultado_final(
                ciclo_inicio=ciclo_inicio,
                inicio_monotonic=inicio_monotonic,
                symbols=[],
                resultados=[],
                erros=[
                    {
                        "error": str(exc),
                        "type": "symbols_error",
                    }
                ],
                intervalos_processados=(
                    intervalos_vencidos
                ),
            )

        if not self.running:

            logger.info(
                "Worker interrompido "
                "após obtenção dos símbolos."
            )

            return self._montar_resultado_final(
                ciclo_inicio=ciclo_inicio,
                inicio_monotonic=inicio_monotonic,
                symbols=symbols,
                resultados=resultados,
                erros=erros,
                intervalos_processados=(
                    intervalos_vencidos
                ),
            )

        # ======================================================
        # TICKERS
        # ======================================================

        try:

            tickers = (
                self._obter_tickers(symbols)
            )

        except Exception as exc:

            logger.exception(
                "Falha ao obter tickers da Binance."
            )

            erros.append(
                {
                    "error": str(exc),
                    "type": "tickers_error",
                }
            )

            return self._montar_resultado_final(
                ciclo_inicio=ciclo_inicio,
                inicio_monotonic=inicio_monotonic,
                symbols=symbols,
                resultados=resultados,
                erros=erros,
                intervalos_processados=(
                    intervalos_vencidos
                ),
            )

        if not self.running:

            logger.info(
                "Worker interrompido "
                "após obtenção dos tickers."
            )

            return self._montar_resultado_final(
                ciclo_inicio=ciclo_inicio,
                inicio_monotonic=inicio_monotonic,
                symbols=symbols,
                resultados=resultados,
                erros=erros,
                intervalos_processados=(
                    intervalos_vencidos
                ),
            )

        # ======================================================
        # MARKET DATA
        # ======================================================

        self._precarregar_market_data(
            symbols
        )

        if not self.running:

            logger.info(
                "Worker interrompido "
                "após Market Data."
            )

            return self._montar_resultado_final(
                ciclo_inicio=ciclo_inicio,
                inicio_monotonic=inicio_monotonic,
                symbols=symbols,
                resultados=resultados,
                erros=erros,
                intervalos_processados=(
                    intervalos_vencidos
                ),
            )

        # ======================================================
        # TIMEFRAMES
        # ======================================================

        (
            resultados,
            erros,
        ) = self._processar_timeframes(
            intervalos=intervalos_vencidos,
            symbols=symbols,
            tickers=tickers,
        )

        # Eventos e entrega são processados depois que todos os
        # timeframes terminaram. Isso evita chamadas ao Telegram a partir
        # das threads de processamento e mantém a entrega sequencial.
        alertas = {
            "events_created": 0,
            "deliveries_created": 0,
            "sent": 0,
            "retried": 0,
        }

        try:
            alertas.update(
                self.alert_service.registrar_resultados(
                    resultados,
                )
            )
            alertas.update(
                self.alert_service.despachar_pendentes()
            )
        except Exception:
            logger.exception(
                "Falha no processamento de alertas RSI.",
            )

        # ======================================================
        # RESULTADO FINAL
        # ======================================================

        resultado_final = self._montar_resultado_final(
            ciclo_inicio=ciclo_inicio,
            inicio_monotonic=inicio_monotonic,
            symbols=symbols,
            resultados=resultados,
            erros=erros,
            intervalos_processados=(
                intervalos_vencidos
            ),
        )

        resultado_final["alerts"] = alertas
        return resultado_final

    # ==========================================================
    # MONTAR RESULTADO FINAL
    # ==========================================================

    def _montar_resultado_final(
        self,
        ciclo_inicio: datetime,
        inicio_monotonic: float,
        symbols: list[str],
        resultados: list[dict[str, Any]],
        erros: list[dict[str, Any]],
        intervalos_processados: Optional[
            list[str]
        ] = None,
    ) -> dict[str, Any]:
        """
        Monta e registra o resultado final do ciclo.
        """

        fim = datetime.now(
            timezone.utc
        )

        duracao = (
            time.monotonic()
            - inicio_monotonic
        )

        if intervalos_processados is None:

            intervalos_processados = []

        # ------------------------------------------------------
        # RESUMO POR TIMEFRAME
        # ------------------------------------------------------

        metricas_ciclo: dict[
            str,
            dict[str, Any],
        ] = {}

        for intervalo in intervalos_processados:

            metricas = (
                self.estatisticas_timeframes.get(
                    intervalo,
                    self._criar_metricas_timeframe(),
                )
            )

            metricas_ciclo[
                intervalo
            ] = dict(
                metricas
            )

        resultado_final: dict[str, Any] = {
            "inicio": ciclo_inicio,
            "fim": fim,
            "duracao_segundos": round(
                duracao,
                2,
            ),
            "intervalos": list(
                intervalos_processados
            ),
            "total_symbols": len(
                symbols
            ),
            "total_results": len(
                resultados
            ),
            "total_errors": len(
                erros
            ),
            "results": resultados,
            "errors": erros,
            "timeframes": metricas_ciclo,
        }

        self.ultimo_ciclo = fim

        self.ultimo_resultado = (
            resultado_final
        )

        logger.info(
            "=================================================="
        )

        logger.info(
            "CICLO RSI CONCLUÍDO | "
            "timeframes=%s | "
            "symbols=%d | "
            "resultados=%d | "
            "erros=%d | "
            "tempo=%.2fs",
            intervalos_processados,
            len(symbols),
            len(resultados),
            len(erros),
            duracao,
        )

        for intervalo in intervalos_processados:

            metricas = (
                self.estatisticas_timeframes.get(
                    intervalo,
                    {},
                )
            )

            logger.info(
                "MÉTRICAS | "
                "timeframe=%s | "
                "symbols=%s | "
                "resultados=%s | "
                "erros=%s | "
                "salvos=%s | "
                "inserts=%s | "
                "updates=%s | "
                "tempo=%.2fs",
                intervalo,
                metricas.get(
                    "symbols",
                    0,
                ),
                metricas.get(
                    "resultados",
                    0,
                ),
                metricas.get(
                    "erros",
                    0,
                ),
                metricas.get(
                    "salvos",
                    0,
                ),
                metricas.get(
                    "inserts",
                    0,
                ),
                metricas.get(
                    "updates",
                    0,
                ),
                metricas.get(
                    "duracao_segundos",
                    0.0,
                ),
            )

        logger.info(
            "=================================================="
        )

        return resultado_final

    # ==========================================================
    # AGUARDAR SEGUNDOS
    # ==========================================================

    def _aguardar_segundos(
        self,
        segundos: float,
    ) -> None:
        """
        Aguarda pequenos intervalos permitindo shutdown rápido.
        """

        restante = max(
            0.0,
            float(segundos),
        )

        while (
            self.running
            and restante > 0
        ):

            espera = min(
                1.0,
                restante,
            )

            time.sleep(
                espera
            )

            restante -= espera

    # ==========================================================
    # AGUARDAR PRÓXIMA EXECUÇÃO
    # ==========================================================

    def _aguardar_proximo_ciclo(
        self,
    ) -> None:
        """
        Aguarda até a próxima verificação da agenda.

        O Worker não fica dormindo 60 segundos.

        Ele acorda no máximo a cada intervalo_ciclo para verificar
        se algum timeframe venceu.
        """

        segundos = (
            self._segundos_ate_proxima_execucao()
        )

        if segundos <= 0:

            return

        logger.debug(
            "Próxima verificação da agenda em %.2fs.",
            segundos,
        )

        self._aguardar_segundos(
            segundos
        )

    # ==========================================================
    # EXECUTAR UMA VEZ
    # ==========================================================

    def executar_uma_vez(
        self,
        forcar: bool = False,
    ) -> dict[str, Any]:
        """
        Executa somente um ciclo.

        Args:
            forcar:
                Se True, processa todos os timeframes informados
                imediatamente.

                Útil para:

                    - testes;
                    - diagnóstico;
                    - execução manual;
                    - cron.

                Se False, processa somente os timeframes cujo
                candle já estiver vencido.
        """

        self.running = True

        if self.app is None:

            self.app = create_app()

        try:

            with self.app.app_context():

                # ------------------------------------------------
                # Agenda
                # ------------------------------------------------

                # Mantém a agenda existente quando o worker é usado
                # por um scheduler externo. Recriá-la a cada chamada
                # faria todos os timeframes parecerem "não vencidos".
                if not self._proxima_execucao:
                    self._inicializar_agenda()

                if forcar:

                    intervalos = list(
                        self.intervalos
                    )

                else:

                    intervalos = (
                        self._obter_timeframes_vencidos()
                    )

                # ------------------------------------------------
                # Execução manual sem forçar.
                #
                # Se nenhum candle venceu, não faz chamadas.
                # ------------------------------------------------

                return self.processar_ciclo(
                    intervalos_vencidos=intervalos
                )

        finally:

            self.running = False

    # ==========================================================
    # EXECUTAR LOOP
    # ==========================================================

    def executar(
        self,
    ) -> None:
        """
        Executa o Worker continuamente.

        O loop funciona baseado no fechamento dos candles.

        Exemplo:

            14:59
                ↓
            aguardando

            15:00:05
                ↓
            processa 5m
            processa 15m
            processa 30m
            processa 1h
            ...

        Somente os timeframes que realmente venceram são
        processados.
        """

        self.running = True

        self._configurar_signals()

        if self.app is None:

            self.app = create_app()

        # ------------------------------------------------------
        # Aquece mercados e inicializa agenda
        # ------------------------------------------------------

        self._aquecer_cache_mercados_binance()

        self._inicializar_agenda()

        logger.info(
            "=================================================="
        )

        logger.info(
            "RSI WORKER INICIADO"
        )

        logger.info(
            "Timeframes: %s",
            self.intervalos,
        )

        logger.info(
            "Intervalo de verificação: %ss",
            self.intervalo_ciclo,
        )

        logger.info(
            "Delay após fechamento do candle: %ss",
            self.candle_close_delay_seconds,
        )

        logger.info(
            "Max retries: %d",
            self.max_retries,
        )

        logger.info(
            "Workers de timeframe: %d",
            self.max_timeframe_workers,
        )

        logger.info(
            "Estratégia: processamento baseado "
            "no fechamento dos candles."
        )

        logger.info(
            "=================================================="
        )

        try:

            with self.app.app_context():

                while self.running:

                    # ------------------------------------------
                    # VERIFICAR TIMEFRAMES VENCIDOS
                    # ------------------------------------------

                    agora = datetime.now(
                        timezone.utc
                    )

                    intervalos_vencidos = (
                        self._obter_timeframes_vencidos(
                            agora
                        )
                    )

                    # ------------------------------------------
                    # PROCESSAR SOMENTE SE NECESSÁRIO
                    # ------------------------------------------

                    if intervalos_vencidos:

                        logger.info(
                            "Timeframes vencidos detectados | "
                            "%s",
                            intervalos_vencidos,
                        )

                        try:

                            self.processar_ciclo(
                                intervalos_vencidos=(
                                    intervalos_vencidos
                                )
                            )

                        except Exception as exc:

                            # ----------------------------------
                            # Falha global inesperada.
                            #
                            # O Worker continua vivo.
                            # ----------------------------------

                            logger.exception(
                                "Erro inesperado "
                                "no ciclo RSI | %s",
                                exc,
                            )

                            # ----------------------------------
                            # Avança a agenda dos timeframes
                            # para evitar loop infinito de erro.
                            # ----------------------------------

                            for intervalo in (
                                intervalos_vencidos
                            ):

                                self._agendar_proxima_execucao(
                                    intervalo
                                )

                    # ------------------------------------------
                    # PARADA
                    # ------------------------------------------

                    if not self.running:

                        break

                    # ------------------------------------------
                    # AGUARDAR
                    # ------------------------------------------

                    self._aguardar_proximo_ciclo()

        finally:

            self.running = False

            logger.info(
                "RSI WORKER FINALIZADO."
            )

    # ==========================================================
    # STATUS
    # ==========================================================

    def obter_status(
        self,
    ) -> dict[str, Any]:
        """
        Retorna o estado atual do Worker.

        Útil futuramente para:

            /health
            /status
            dashboard
            monitoramento
        """

        agora = datetime.now(
            timezone.utc
        )

        proximas_execucoes = {
            intervalo: (
                data.isoformat()
                if data is not None
                else None
            )
            for intervalo, data
            in self._proxima_execucao.items()
        }

        vencidos = (
            self._obter_timeframes_vencidos(
                agora
            )
            if self._proxima_execucao
            else []
        )

        return {
            "running": self.running,
            "intervalos": list(
                self.intervalos
            ),
            "intervalo_verificacao_segundos": (
                self.intervalo_ciclo
            ),
            "candle_close_delay_seconds": (
                self.candle_close_delay_seconds
            ),
            "max_retries": (
                self.max_retries
            ),
            "max_timeframe_workers": (
                self.max_timeframe_workers
            ),
            "proximas_execucoes": (
                proximas_execucoes
            ),
            "timeframes_vencidos": vencidos,
            "ultimo_ciclo": (
                self.ultimo_ciclo.isoformat()
                if self.ultimo_ciclo
                else None
            ),
            "estatisticas": {
                intervalo: dict(
                    metricas
                )
                for intervalo, metricas
                in self.estatisticas_timeframes.items()
            },
        }


# ==============================================================
# SINGLETON
# ==============================================================

rsi_worker = RSIWorker()


# ==============================================================
# EXECUÇÃO DIRETA
# ==============================================================

if __name__ == "__main__":

    rsi_worker.executar()
