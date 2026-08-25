# RSI Radar

Plataforma de monitoramento de RSI para pares cripto cotados em USDT. Ela calcula o indicador em candles fechados, mantém o histórico no PostgreSQL, mostra os sinais em um painel web e pode avisar um grupo do Telegram quando ocorre uma entrada em sobrecompra ou sobrevenda.

> Indicador técnico. Não constitui recomendação de compra ou venda.

## Como funciona

```text
Binance + CoinGecko
        │
        ▼
  RSIWorker (candle fechado)
        │
        ├── rsi_data              histórico RSI
        ├── rsi_snapshots         estado atual por par/timeframe
        ├── signal_events         entrada nas zonas RSI
        └── notification_deliveries (outbox)
                  │
                  ▼
              Telegram
                  │
                  ▼
           API Flask + /dashboard
```

Um estado contínuo acima de 70 ou abaixo de 30 não gera spam. O bot recebe apenas transições:

- `ENTER_OVERBOUGHT`: RSI anterior `< 70` e RSI atual `>= 70`;
- `ENTER_OVERSOLD`: RSI anterior `> 30` e RSI atual `<= 30`.

## Pré-requisitos

- Python 3.11+
- PostgreSQL
- Uma conta/instância da Binance acessível pelo CCXT
- Opcionalmente, um bot e grupo do Telegram

## Instalação

No PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edite `.env` e informe ao menos `DATABASE_URL`. Depois aplique as migrações:

```powershell
.\.venv\Scripts\python.exe -m flask --app main:app db upgrade
```

> A migração mais recente cria `rsi_snapshots`, `signal_events` e `notification_deliveries`, além de preencher o snapshot com o histórico existente. Faça backup do banco antes de atualizar qualquer ambiente de produção.

## Executar

Em terminais separados:

```powershell
# API e painel
.\.venv\Scripts\python.exe main.py

# Worker contínuo, alinhado ao fechamento dos candles
.\.venv\Scripts\python.exe worker.py
```

Abra [http://127.0.0.1:5000/dashboard](http://127.0.0.1:5000/dashboard).

## Hospedagem gratuita

Para produção sem custo mensal, a arquitetura preparada é Oracle Cloud Always
Free para API, worker e PostgreSQL, com o Render reservado ao futuro frontend
estático. Consulte o [guia de deploy na Oracle](deploy/ORACLE_ALWAYS_FREE.md).
Enquanto a A1 de 6 GB não tiver capacidade, há também um
[modo temporário para a E2 Micro de 1 GB](deploy/ORACLE_E2_MICRO_TEMPORARY.md).
Com autorização explícita, use o
[retry automático de criação da A1](deploy/ORACLE_A1_PROVISION_RETRY.md) para
tentar provisioná-la periodicamente sem migrar a conta para Pay As You Go.

## Configurar o Telegram

1. Crie o bot no BotFather e adicione-o ao grupo desejado.
2. Descubra o `chat_id` do grupo.
3. Preencha, apenas no `.env` local/seguro:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=COLE_O_TOKEN_AQUI
TELEGRAM_CHAT_ID=-1001234567890
APP_TIMEZONE=America/Sao_Paulo
```

Nunca versione token ou chat ID de produção. Se `TELEGRAM_ENABLED=false`, a API e o painel continuam funcionando e nenhum POST é feito ao Telegram.

## Principais endpoints

| Endpoint | Uso |
| --- | --- |
| `GET /api/v1/health` | Health check da API. |
| `GET /api/v1/rsi?intervalo=1h&limite=20` | Histórico recente de RSI. |
| `GET /api/v1/rsi/BTCUSDT?intervalo=1h` | Último RSI salvo para um par. |
| `GET /api/v1/signals/current?intervalo=1h` | Um sinal atual por par, ordenado por força. |
| `GET /api/v1/history/BTCUSDT?intervalo=1h` | Histórico cronológico para o gráfico RSI. |
| `GET /api/v1/market/BTCUSDT/candles?intervalo=1h` | Candles da Binance para o gráfico de preço. |
| `GET /api/v1/symbols?q=BTC` | Busca pares presentes no histórico. |
| `GET /api/v1/meta/timeframes` | Lista de timeframes aceitos. |

As rotas legadas também aceitam `limite`/`intervalo`; `limit`/`timeframe` são aceitos como aliases para facilitar integrações.

## Testes e qualidade

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app database services workers tests main.py worker.py migrations\env.py --no-cache --select F,E9
```

## Observações de produto

- O gráfico de RSI usa o histórico persistido no PostgreSQL.
- O gráfico de preço busca candles pelo backend na Binance, sem expor a exchange diretamente ao navegador.
- O ranking depende da cobertura disponível na CoinGecko; valores ausentes são exibidos como `N/D`.
