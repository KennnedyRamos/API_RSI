# RSI Radar

[![CI](https://github.com/KennnedyRamos/API_RSI/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/KennnedyRamos/API_RSI/actions/workflows/ci.yml)
![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-API-000000?logo=flask&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)

> Plataforma de monitoramento de **RSI(14)** para pares cripto cotados em USDT, com dashboard web, histórico em PostgreSQL e alertas no Telegram orientados ao fechamento de candles.

> Indicador técnico educacional. Não constitui recomendação de compra ou venda.

## O que este projeto resolve

Monitorar muitos pares e períodos manualmente é lento e favorece alertas repetidos ou atrasados. O RSI Radar coleta candles públicos da Binance, calcula o RSI com suavização de Wilder e transforma apenas transições relevantes em eventos persistidos e notificações Telegram.

- Calcula RSI(14) somente com candles fechados, evitando sinais baseados em candle ainda em formação.
- Monitora `5m`, `15m`, `30m`, `1h`, `4h`, `12h`, `1d`, `1w` e `1M`.
- Detecta entrada em sobrecompra (`RSI anterior < 70` e atual `>= 70`) e sobrevenda (`RSI anterior > 30` e atual `<= 30`).
- Evita spam: permanecer acima de 70 ou abaixo de 30 não gera nova mensagem.
- Descarta alertas com mais de um minuto, em vez de entregar uma oportunidade vencida.
- Mostra os RSI complementares do ativo na mensagem Telegram e no dashboard.

## Arquitetura

```text
Binance REST ───────────────┐
                           ├──► RSI Worker (candle fechado)
CoinGecko (cache assíncrono)┘             │
                                          ├──► rsi_data: histórico
                                          ├──► rsi_snapshots: estado atual
                                          ├──► signal_events: transições
                                          └──► notification_deliveries: outbox
                                                             │
                                                     Telegram Bot API

PostgreSQL ◄──────────────────── API Flask ◄──────────── Dashboard web
                                      │
                           health, readiness e worker healthcheck
```

O ranking e o market cap da CoinGecko são enriquecimentos opcionais: eles usam cache e atualização em segundo plano para não atrasar o caminho crítico Binance → RSI → Telegram.

## Funcionalidades

- Dashboard responsivo em `/dashboard`, com filtros por período, tipo/força de sinal, busca de par e gráficos de RSI/preço.
- API REST versionada, com health e readiness checks para operação em containers.
- Outbox persistente e idempotente para Telegram, com retry, expiração e recuperação de envios interrompidos.
- Atualização do dashboard a cada 5 segundos; o dado técnico continua orientado ao fechamento do candle, não a tick-by-tick.
- Modo reduzido para Oracle E2 Micro (10 pares líquidos) e arquitetura Docker pronta para Oracle Cloud Always Free.
- Healthcheck do worker por heartbeat, para distinguir API saudável de coleta parada no Docker.

## Stack

| Camada | Tecnologias |
| --- | --- |
| Backend | Python 3.11, Flask, Gunicorn |
| Dados | PostgreSQL, SQLAlchemy, Alembic |
| Mercado | Binance Public REST API, CoinGecko cacheado |
| Alertas | Telegram Bot API |
| Interface | HTML, CSS e JavaScript sem framework pesado |
| Operação | Docker Compose, Caddy, Oracle Cloud Always Free, GitHub Actions |

## Executar localmente

Pré-requisitos: Python 3.11+, PostgreSQL acessível e internet para as APIs públicas. Não é necessária uma API key da Binance para o fluxo atual.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edite apenas o arquivo local `.env`, preenchendo pelo menos `DATABASE_URL`. Depois aplique as migrations:

```powershell
.\.venv\Scripts\python.exe -m flask --app main:app db upgrade
```

Em dois terminais separados:

```powershell
# API e dashboard
.\.venv\Scripts\python.exe main.py

# Coleta contínua e alertas
.\.venv\Scripts\python.exe worker.py
```

Abra [http://127.0.0.1:5000/dashboard](http://127.0.0.1:5000/dashboard).

## Configurar o Telegram

1. Crie o bot no BotFather e adicione-o ao grupo desejado.
2. Descubra o `chat_id` do grupo.
3. Preencha os valores somente no `.env` local ou em `deploy/.env.production` na VM:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=SEU_TOKEN_SECRETO
TELEGRAM_CHAT_ID=-1001234567890
APP_TIMEZONE=America/Sao_Paulo
```

Nunca versione token, chat ID de produção, chave SSH ou `.env`. Caso um token seja exposto em conversa, log ou commit, revogue-o no BotFather e gere outro.

## API

| Endpoint | Finalidade |
| --- | --- |
| `GET /api/v1/health` | Liveness da API. |
| `GET /api/v1/ready` | Readiness com verificação do PostgreSQL. |
| `GET /api/v1/rsi?intervalo=1h&limite=20` | Histórico recente de RSI. |
| `GET /api/v1/rsi/BTCUSDT?intervalo=1h` | Último RSI salvo de um par. |
| `GET /api/v1/signals/current?intervalo=1h` | Estado atual, um sinal por par, ordenado por força. |
| `GET /api/v1/history/BTCUSDT?intervalo=1h` | Série cronológica para o gráfico RSI. |
| `GET /api/v1/market/BTCUSDT/candles?intervalo=1h` | Candles de preço via backend. |
| `GET /api/v1/symbols?q=BTC` | Busca pares existentes no histórico. |
| `GET /api/v1/meta/timeframes` | Períodos aceitos. |

As rotas legadas permanecem disponíveis por compatibilidade. Os parâmetros `limit`/`timeframe` também são aceitos como aliases de `limite`/`intervalo`.

## Deploy gratuito

O repositório oferece dois perfis de operação:

| Ambiente | Uso recomendado | Cobertura |
| --- | --- | --- |
| Oracle E2 Micro (1 GB) | Solução temporária e econômica | 10 pares líquidos configurados, todos os períodos |
| Oracle A1 Flex (6 GB) | Ambiente alvo Always Free | Mais folga para API, worker e PostgreSQL; expansão gradual após medir latência |

Guias disponíveis:

- [Oracle Always Free](deploy/ORACLE_ALWAYS_FREE.md)
- [Modo temporário E2 Micro](deploy/ORACLE_E2_MICRO_TEMPORARY.md)
- [Retry de provisionamento A1](deploy/ORACLE_A1_PROVISION_RETRY.md)

Na E2, mantenha `RSI_WORKER_SYMBOLS` limitado. Ter 6 GB de RAM não elimina o gargalo de rede: hoje cada par/período exige uma consulta de candles. Antes de habilitar todos os pares, valide o tempo P95 do ciclo de 5 minutos abaixo de 45 segundos.

## Qualidade

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app database services workers tests main.py worker.py migrations\env.py --no-cache --select F,E9
.\.venv\Scripts\python.exe -m pip check
```

O GitHub Actions executa a suíte de testes e a análise estática em cada push e pull request para `main`.

## Decisões de confiabilidade

- **Candle fechado:** evita alterar sinais por oscilação intraperíodo.
- **Outbox persistente:** o evento e a notificação são registrados antes da chamada externa; reprocessamentos não duplicam a criação da entrega.
- **Alertas recentes:** filas antigas são expiradas após um minuto para não enviar sinais defasados.
- **Recuperação de envio:** itens parados em `SENDING` voltam para retry após o lease expirar. A entrega é *at-least-once*, pois a API Telegram não possui uma chave de idempotência para confirmar uma resposta perdida.
- **Enriquecimento não bloqueante:** ranking/market cap podem aparecer como `N/D` em uma indisponibilidade externa, mas isso não interrompe o RSI nem a entrega do alerta.

## Limitações e próximos passos

- A varredura completa de todos os pares por REST, de forma serial, não atende uma promessa de alerta inferior a um minuto. O modo atual prioriza uma lista configurada de pares líquidos.
- Uma evolução para grande escala deve usar perfis de prioridade, concorrência com contexto/sessões isolados ou WebSocket de klines fechados.
- O histórico precisa de política de retenção, agregação ou particionamento antes de crescer para milhões de candles.
- O endpoint de candles deve ganhar cache curto e rate limiting antes de receber tráfego público alto.
- Ainda não há licença aberta definida. Escolha uma licença antes de aceitar reutilização ou contribuições externas.

## Para portfólio

O RSI Radar demonstra uma solução de ponta a ponta com integração de APIs externas, cálculo técnico, modelagem PostgreSQL, entrega idempotente de notificações, interface web e operação com containers/CI. A descrição sugerida para o repositório é:
