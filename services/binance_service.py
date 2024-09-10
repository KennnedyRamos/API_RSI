import ccxt

exchange = ccxt.binance({
    'rateLimit': 1200,
    'enableRateLimit': True,
})

def fetch_tickers():
    return exchange.fetch_tickers()
