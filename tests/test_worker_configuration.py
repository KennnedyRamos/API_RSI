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
