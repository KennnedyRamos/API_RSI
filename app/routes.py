import time
import ccxt
import logging
from flask import jsonify
from app.utils import calcular_rsi
from services.binance_service import exchange
from database.models import insert_rsi_data

logging.basicConfig(level=logging.DEBUG)

def init_routes(app):
    @app.route('/')
    def home():
        return "Bem-vindo à API de RSI para Criptomoedas!"

    def processar_intervalo(intervalo):
        periodo_rsi = 14
        results = []
        errors = []

        try:
            tickers = exchange.fetch_tickers()
            for symbol, ticker in tickers.items():
                if 'USDT' in symbol:
                    try:
                        candles = exchange.fetch_ohlcv(symbol, intervalo, limit=periodo_rsi + 1)
                        if len(candles) >= periodo_rsi + 1:
                            closes = [candle[4] for candle in candles]
                            rsi = calcular_rsi(closes, periodo_rsi)
                            timestamp = candles[-1][0]  
                            current_price = candles[-1][4]

                            rsi_status = ''
                            if rsi >= 70:
                                rsi_status = 'Sobrecompra'
                            elif rsi <= 30:
                                rsi_status = 'Sobrevenda'

                            insert_rsi_data(symbol, intervalo, rsi, timestamp, rsi_status, current_price)
                            
                            results.append(
                                {'symbol': symbol, 'intervalo': intervalo, 'rsi': round(rsi, 2), 'status': rsi_status, 'current_price': current_price}
                            )
                        else:
                            errors.append({
                                'symbol': symbol,
                                'intervalo': intervalo,
                                'error': 'Dados insuficientes',
                                'dados_disponiveis': len(candles),
                                'necessario': periodo_rsi + 1
                            })
                    except ccxt.NetworkError as e:
                        errors.append({'symbol': symbol, 'error': str(e)})
                    except ccxt.ExchangeError as e:
                        errors.append({'symbol': symbol, 'error': str(e)})
                    except Exception as e:
                        errors.append({'symbol': symbol, 'error': str(e)})
        except Exception as e:
            return {'error': str(e)}, 500

        return {'results': results, 'errors': errors}

    @app.route('/rsi/all', methods=['GET'])
    def rsi_all():
        intervalos = ['5m', '15m','30m' '1h', '4h', '12h', '1d', '1w', '1M']
        all_results = []
        all_errors = []
        start_time = time.time()

        for intervalo in intervalos:
            response = processar_intervalo(intervalo)
            all_results.extend(response['results'])
            all_errors.extend(response['errors'])

        end_time = time.time()
        return jsonify({
            'results': all_results,
            'errors': all_errors,
            'tempo_execucao': end_time - start_time
        })
