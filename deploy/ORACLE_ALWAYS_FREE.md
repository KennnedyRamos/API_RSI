# Deploy na Oracle Cloud Always Free

Este projeto usa uma única VM Oracle para a API Flask, o worker RSI e o
PostgreSQL. O worker já é contínuo e roda em um container próprio. Não inicie
também `workers/scheduler.py`, pois isso duplicaria o processamento.

O Render ficará reservado para o frontend estático. Antes dessa etapa, a API
precisa de uma URL HTTPS: um site HTTPS do Render não pode consultar uma API
HTTP.

## 1. Criar a VM

Na Oracle Cloud, crie uma instância **Always Free** com Ubuntu 24.04 e shape
**VM.Standard.A1.Flex**. Comece com **1 OCPU e 6 GB de RAM**. Não selecione
load balancer, banco gerenciado nem outro recurso pago. Consulte os
[limites oficiais Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
antes de criar a instância.

Na Network Security Group (ou Security List), permita apenas:

| Porta | Origem | Uso |
| --- | --- | --- |
| 22/TCP | seu IP público | SSH |
| 80/TCP | `0.0.0.0/0` | certificado HTTPS |
| 443/TCP | `0.0.0.0/0` | API e painel |

Não abra `5432`, `5000` nem `8000`. Depois de confirmar o SSH, replique as
regras no firewall UFW do Ubuntu.

## 2. Configurar HTTPS sem custo

Use um domínio seu ou um subdomínio gratuito, por exemplo DuckDNS. Aponte o
registro DNS para o IP público da VM e confirme a propagação:

```bash
nslookup api-seu-rsi.duckdns.org
```

O nome deve ser exatamente o valor de `CADDY_DOMAIN`. O Caddy obterá e
renovará automaticamente o certificado TLS quando o DNS e as portas 80/443
estiverem corretos.

## 3. Instalar Docker na VM

Conecte-se com a chave SSH criada no provisionamento:

```bash
ssh ubuntu@IP_PUBLICO_DA_VM
```

Instale Docker Engine e o plugin Docker Compose seguindo a
[documentação oficial para Ubuntu](https://docs.docker.com/engine/install/ubuntu/).
Depois, permita que o usuário `ubuntu` use Docker e conecte-se de novo:

```bash
sudo usermod -aG docker ubuntu
exit
```

Valide a instalação após reconectar:

```bash
docker --version
docker compose version
```

## 4. Preparar as variáveis de produção

```bash
git clone https://github.com/KennnedyRamos/API_RSI.git
cd API_RSI
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
openssl rand -hex 24
```

Edite `deploy/.env.production` com `nano`. Use a senha hexadecimal gerada em
`POSTGRES_PASSWORD` e também em `DATABASE_URL`; informe o domínio, o e-mail e
as variáveis reais do Telegram. Copie os valores manualmente, nunca envie seu
`.env` de desenvolvimento para a VM.

Confirme que o arquivo seguro não será versionado:

```bash
git status --short deploy/.env.production
```

O comando não deve mostrar saída.

## 5. Publicar e validar

```bash
docker compose --env-file deploy/.env.production up -d --build
docker compose --env-file deploy/.env.production ps
docker compose --env-file deploy/.env.production logs --tail=100 api worker
```

O serviço `migrate` aplica o `flask db upgrade` uma vez; API e worker só
iniciam depois disso. Valide externamente:

```bash
curl https://api-seu-rsi.duckdns.org/api/v1/health
curl https://api-seu-rsi.duckdns.org/api/v1/ready
```

O painel provisório estará em:

```text
https://api-seu-rsi.duckdns.org/dashboard
```

## Operação e backup

Ver logs:

```bash
docker compose --env-file deploy/.env.production logs -f worker
docker compose --env-file deploy/.env.production logs -f api
```

Antes de atualizar migrations, faça um backup:

```bash
mkdir -p backups
docker compose --env-file deploy/.env.production exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/rsi-$(date +%F-%H%M%S).sql
```

Atualize o código com:

```bash
git pull --ff-only
docker compose --env-file deploy/.env.production up -d --build
```

Para parar sem apagar o banco:

```bash
docker compose --env-file deploy/.env.production down
```

Nunca use `down -v` em produção: esse comando remove o volume PostgreSQL.

## Futuro frontend no Render

Quando a interface independente estiver pronta, crie no Render um **Static
Site** ligado ao GitHub. Depois, coloque a URL HTTPS exata dele em
`CORS_ALLOWED_ORIGINS` na VM e rode:

```bash
docker compose --env-file deploy/.env.production up -d
```

Se o novo frontend mantiver a rota `/dashboard`, atualize também
`DASHBOARD_PUBLIC_URL` para ele. Nunca use `CORS_ALLOWED_ORIGINS=*`.
