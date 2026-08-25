from __future__ import annotations

from types import SimpleNamespace

from workers.rsi_worker import RSIWorker


class FakeBinance:
    def __init__(self) -> None:
        self.get_usdt_symbols_calls = 0

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
