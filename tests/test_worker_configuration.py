from __future__ import annotations

from types import SimpleNamespace

from services.binance_service import BinanceService
from workers.rsi_worker import RSIWorker


class FakeBinance:
    def __init__(self) -> None:
        self.get_usdt_symbols_calls = 0
        self.get_tickers_calls: list[list[str] | None] = []
        self.carregar_mercados_calls = 0

    def validar_symbol(self, symbol: str) -> str:
        value = symbol.strip().upper().replace("-", "/")
        if "/" not in value and value.endswith("USDT"):
            value = f"{value[:-4]}/USDT"
        if not value.endswith("/USDT"):
            raise ValueError("Apenas pares USDT são aceitos.")
        return value

    def get_usdt_symbols(self) -> list[str]:
        self.get_usdt_symbols_calls += 1
        return ["BTC/USDT", "ETH/USDT"]

    def carregar_mercados(self) -> dict[str, dict]:
        self.carregar_mercados_calls += 1
        return {
            "BTC/USDT": {},
            "ETH/USDT": {},
        }

    def get_tickers(self, symbols: list[str] | None = None) -> dict[str, dict]:
        self.get_tickers_calls.append(symbols)
        return {symbol: {} for symbol in (symbols or ["BTC/USDT", "ETH/USDT"])}


def build_worker(binance: FakeBinance) -> RSIWorker:
    rsi_service = SimpleNamespace(
        TIMEFRAMES_PERMITIDOS=("5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w", "1M"),
        binance=binance,
        market=SimpleNamespace(),
    )
    return RSIWorker(
        rsi_service_instance=rsi_service,
        binance=binance,
        market=rsi_service.market,
    )


def test_worker_uses_configured_symbols_and_timeframes(monkeypatch):
    monkeypatch.setenv("RSI_WORKER_INTERVALS", "5m, 1h, 5m")
    monkeypatch.setenv(
        "RSI_WORKER_SYMBOLS",
        "BTCUSDT, ETH/USDT, BTC-USDT",
    )
    binance = FakeBinance()

    worker = build_worker(binance)

    assert worker.intervalos == ["5m", "1h"]
    assert worker.symbols_configurados == ["BTC/USDT", "ETH/USDT"]
    assert worker._obter_symbols() == ["BTC/USDT", "ETH/USDT"]
    assert binance.get_usdt_symbols_calls == 0


def test_worker_defaults_to_all_usdt_symbols_without_configuration(monkeypatch):
    monkeypatch.delenv("RSI_WORKER_INTERVALS", raising=False)
    monkeypatch.delenv("RSI_WORKER_SYMBOLS", raising=False)
    binance = FakeBinance()

    worker = build_worker(binance)

    assert worker.intervalos == list(worker.DEFAULT_INTERVALOS)
    assert worker.symbols_configurados == []
    assert worker._obter_symbols() == ["BTC/USDT", "ETH/USDT"]
    assert binance.get_usdt_symbols_calls == 1


def test_worker_requests_only_configured_tickers(monkeypatch):
    monkeypatch.setenv("RSI_WORKER_SYMBOLS", "BTCUSDT, ETHUSDT")
    binance = FakeBinance()

    worker = build_worker(binance)
    symbols = worker._obter_symbols()

    tickers = worker._obter_tickers(symbols)

    assert set(tickers) == {"BTC/USDT", "ETH/USDT"}
    assert binance.get_tickers_calls == [["BTC/USDT", "ETH/USDT"]]


def test_worker_warms_binance_markets_before_processing():
    binance = FakeBinance()
    worker = build_worker(binance)

    worker._aquecer_cache_mercados_binance()

    assert binance.carregar_mercados_calls == 1


def test_worker_skips_market_warmup_for_configured_symbols(monkeypatch):
    monkeypatch.setenv("RSI_WORKER_SYMBOLS", "BTCUSDT,ETHUSDT")
    binance = FakeBinance()
    worker = build_worker(binance)

    worker._aquecer_cache_mercados_binance()

    assert binance.carregar_mercados_calls == 0


def test_worker_calls_alert_callback_after_each_timeframe():
    binance = FakeBinance()
    worker = build_worker(binance)
    worker.running = True
    ordem: list[str] = []

    def processar_timeframe(*, intervalo: str, **_kwargs) -> dict:
        ordem.append(f"processar:{intervalo}")
        return {
            "results": [{"intervalo": intervalo}],
            "errors": [],
        }

    worker._processar_timeframe_com_retry = processar_timeframe
    worker._agendar_proxima_execucao = (
        lambda intervalo: ordem.append(f"agendar:{intervalo}")
    )

    resultados, erros = worker._processar_timeframes(
        intervalos=["5m", "15m"],
        symbols=["BTC/USDT"],
        tickers={"BTC/USDT": {}},
        on_timeframe_completed=lambda itens: ordem.append(
            f"alertar:{itens[0]['intervalo']}"
        ),
    )

    assert erros == []
    assert resultados == [
        {"intervalo": "5m"},
        {"intervalo": "15m"},
    ]
    assert ordem == [
        "processar:5m",
        "alertar:5m",
        "agendar:5m",
        "processar:15m",
        "alertar:15m",
        "agendar:15m",
    ]


def test_worker_forwards_each_saved_result_to_immediate_callback():
    binance = FakeBinance()
    recebidos: list[str] = []

    class FakeRSIService:
        TIMEFRAMES_PERMITIDOS = (
            "5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w", "1M",
        )
        market = SimpleNamespace()

        def __init__(self) -> None:
            self.binance = binance

        @staticmethod
        def processar_intervalo(*, on_result_completed, **_kwargs) -> dict:
            resultados = [
                {"symbol": "BTC/USDT", "intervalo": "5m", "saved": True},
                {"symbol": "ETH/USDT", "intervalo": "5m", "saved": True},
            ]
            for resultado in resultados:
                on_result_completed(resultado)
            return {"results": resultados, "errors": []}

    rsi_service = FakeRSIService()
    worker = RSIWorker(
        rsi_service_instance=rsi_service,
        binance=binance,
        market=rsi_service.market,
    )

    resultados, erros = worker._processar_timeframe(
        intervalo="5m",
        symbols=["BTC/USDT", "ETH/USDT"],
        tickers={"BTC/USDT": {}, "ETH/USDT": {}},
        on_result_completed=lambda resultado: recebidos.append(resultado["symbol"]),
    )

    assert erros == []
    assert [resultado["symbol"] for resultado in resultados] == recebidos


def test_worker_keeps_global_telegram_dispatch_budget():
    class FakeAlertService:
        max_dispatch_per_cycle = 2

        def __init__(self) -> None:
            self.next_delivery_id = 1
            self.dispatch_calls: list[dict] = []

        def registrar_resultados_com_entregas(self, resultados, *, rsi_por_symbol):
            delivery_id = self.next_delivery_id
            self.next_delivery_id += 1
            return (
                {"events_created": 1, "deliveries_created": 1},
                [delivery_id],
            )

        def despachar_pendentes(self, **kwargs):
            self.dispatch_calls.append(kwargs)
            return {"sent": 1, "retried": 0, "expired": 0, "skipped": 0}

    binance = FakeBinance()
    worker = build_worker(binance)
    alert_service = FakeAlertService()
    worker.alert_service = alert_service
    worker.running = True
    worker._obter_symbols = lambda: ["BTC/USDT"]
    worker._obter_tickers = lambda _symbols: {"BTC/USDT": {}}
    worker._precarregar_market_data = lambda _symbols: {}

    def processar_timeframes(*, on_result_completed, **_kwargs):
        for indice in range(3):
            on_result_completed({"symbol": f"COIN{indice}/USDT"})
        return [], []

    worker._processar_timeframes = processar_timeframes

    resultado = worker.processar_ciclo(intervalos_vencidos=["5m"])

    assert resultado["alerts"]["sent"] == 2
    assert alert_service.dispatch_calls == [
        {
            "limite": 2,
            "delivery_ids": [1],
            "expirar_pendentes": False,
        },
        {
            "limite": 1,
            "delivery_ids": [2],
            "expirar_pendentes": False,
        },
    ]


def test_worker_keeps_complete_ticker_request_without_symbol_configuration(monkeypatch):
    monkeypatch.delenv("RSI_WORKER_SYMBOLS", raising=False)
    binance = FakeBinance()

    worker = build_worker(binance)
    worker._obter_tickers(["BTC/USDT", "ETH/USDT"])

    assert binance.get_tickers_calls == [None]


def test_binance_exchange_fetches_only_spot_markets(monkeypatch):
    configurations: list[dict] = []

    class FakeExchange:
        def __init__(self, configuration: dict) -> None:
            configurations.append(configuration)

    monkeypatch.setattr(
        "services.binance_service.ccxt.binance",
        FakeExchange,
    )
    service = BinanceService()

    try:
        assert configurations[0]["options"]["fetchMarkets"] == {
            "types": ["spot"],
        }
    finally:
        service.close()


def test_selected_tickers_use_reduced_public_batch():
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict]:
            return [
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "104250.25",
                    "priceChangePercent": "3.82",
                    "quoteVolume": "42310000000",
                    "volume": "405850",
                    "closeTime": 1_777_000_000_000,
                },
                {
                    "symbol": "ETHUSDT",
                    "lastPrice": "3210.50",
                    "priceChangePercent": "-1.25",
                    "quoteVolume": "12000000000",
                    "volume": "3700000",
                    "closeTime": 1_777_000_000_000,
                },
            ]

    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict, float]] = []

        def get(
            self,
            url: str,
            *,
            params: dict,
            timeout: float,
        ) -> FakeResponse:
            self.calls.append((url, params, timeout))
            return FakeResponse()

    service = object.__new__(BinanceService)
    session = FakeSession()

    service.validar_symbol = FakeBinance().validar_symbol
    service._ticker_session = session
    service._executar_com_retry = (
        lambda func, *, operacao, **kwargs: func(**kwargs)
    )

    tickers = service.get_tickers(["BTCUSDT", "ETH/USDT", "BTC-USDT"])

    assert set(tickers) == {"BTC/USDT", "ETH/USDT"}
    assert tickers["BTC/USDT"] == {
        "symbol": "BTC/USDT",
        "last": "104250.25",
        "close": "104250.25",
        "percentage": "3.82",
        "quoteVolume": "42310000000",
        "baseVolume": "405850",
        "timestamp": 1_777_000_000_000,
    }
    assert session.calls == [
        (
            BinanceService.TICKERS_24H_URL,
            {"symbols": '["BTCUSDT","ETHUSDT"]'},
            BinanceService.TICKERS_REQUEST_TIMEOUT,
        )
    ]


def test_ohlcv_uses_reduced_public_endpoint():
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[list[str | int]]:
            return [
                [
                    1_777_000_000_000,
                    "100.0",
                    "105.0",
                    "99.0",
                    "102.5",
                    "1234.5",
                ]
            ]

    class FakeSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict, float]] = []

        def get(
            self,
            url: str,
            *,
            params: dict,
            timeout: float,
        ) -> FakeResponse:
            self.calls.append((url, params, timeout))
            return FakeResponse()

    service = object.__new__(BinanceService)
    session = FakeSession()
    service.validar_symbol = FakeBinance().validar_symbol
    service._ticker_session = session
    service._executar_com_retry = (
        lambda func, *, operacao, **kwargs: func(**kwargs)
    )

    candles = service.get_ohlcv("BTCUSDT", "5m", limit=20)

    assert candles == [[1_777_000_000_000, 100.0, 105.0, 99.0, 102.5, 1234.5]]
    assert session.calls == [
        (
            BinanceService.KLINES_URL,
            {"symbol": "BTCUSDT", "interval": "5m", "limit": 20},
            BinanceService.TICKERS_REQUEST_TIMEOUT,
        )
    ]
