# Worker RSI

O worker é o processo contínuo que agenda a coleta após o fechamento dos candles e persiste os resultados no PostgreSQL.

## Regras do ciclo

- Processa apenas os períodos vencidos: `5m`, `15m`, `30m`, `1h`, `4h`, `12h`, `1d`, `1w` e `1M`.
- Aguarda uma pequena margem após o fechamento do candle para a Binance consolidar o dado.
- Calcula RSI somente com candle fechado.
- Envia alertas Telegram apenas para a entrada na zona de sobrecompra ou sobrevenda.
- Atualiza ranking e market cap em segundo plano; uma falha da CoinGecko não bloqueia RSI, banco ou Telegram.
- Atualiza um arquivo de heartbeat. No Docker, esse sinal alimenta o healthcheck do serviço `worker`.

## Capacidade e perfil de coleta

O processamento atual faz uma consulta REST de candles por par e período. Em uma E2 Micro, use uma lista explícita de pares líquidos:

```env
RSI_WORKER_SYMBOLS=BTC/USDT,ETH/USDT,BNB/USDT,SOL/USDT,XRP/USDT,ADA/USDT,DOGE/USDT,TRX/USDT,AVAX/USDT,LINK/USDT
```

Não habilite todos os pares apenas porque a VM possui mais memória. Primeiro meça a duração do ciclo de 5 minutos; o alvo operacional é P95 inferior a 45 segundos para preservar a janela de alerta de um minuto.

## Operação

```powershell
.\.venv\Scripts\python.exe worker.py
```

No Docker, acompanhe o processo e o healthcheck:

```bash
docker compose ps
docker compose logs --tail=100 -f worker
```
