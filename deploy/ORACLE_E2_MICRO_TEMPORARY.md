# Uso temporário da Oracle E2 Micro (1 GB)

Use este modo apenas enquanto a capacidade da A1 de 6 GB não estiver
disponível. A E2 Micro tem memória e CPU muito menores, então o projeto opera
em uma cobertura reduzida: dez pares líquidos e todos os timeframes RSI.

## O que este modo mantém

- API e painel provisório;
- PostgreSQL persistente;
- worker contínuo;
- RSI nos timeframes `5m`, `15m`, `30m`, `1h`, `4h`, `12h`, `1d`, `1w` e `1M`;
- apenas `BTC`, `ETH`, `BNB`, `SOL`, `XRP`, `ADA`, `DOGE`, `TRX`, `AVAX` e
  `LINK` cotados em USDT por padrão.

Não é adequado para varrer todos os pares USDT ou para tráfego público alto.

## Preparar a VM

Use a VM `VM.Standard.E2.1.Micro` com Oracle Linux 9 e o usuário `opc`. Siga as
etapas de instalação de Docker e configuração do arquivo
`deploy/.env.production` no [guia principal](ORACLE_ALWAYS_FREE.md). No
arquivo de produção, mantenha `GUNICORN_WORKERS=1` e deixe Telegram desativado
até ter token e chat seguros.

## Validar e iniciar o modo micro

```bash
bash deploy/preflight_oracle_e2_micro.sh deploy/.env.production

docker compose -f compose.yml -f deploy/compose.micro.yml \
  --env-file deploy/.env.production up -d --build

docker compose -f compose.yml -f deploy/compose.micro.yml \
  --env-file deploy/.env.production ps
```

Observe memória e logs durante os primeiros ciclos:

```bash
free -m
docker stats --no-stream
docker compose -f compose.yml -f deploy/compose.micro.yml \
  --env-file deploy/.env.production logs --tail=100 worker
```

Se ocorrer reinício por memória ou o ciclo de 5 minutos atrasar, reduza a lista
no próprio `deploy/.env.production`:

```env
RSI_WORKER_SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT
```

## Migrar para A1 de 6 GB quando houver capacidade

Faça backup do banco na E2, crie a A1 e siga o guia principal sem o arquivo
`deploy/compose.micro.yml`. Na A1, remova `RSI_WORKER_SYMBOLS` e
`RSI_WORKER_INTERVALS` do ambiente para voltar a todos os pares USDT e todos
os timeframes.
