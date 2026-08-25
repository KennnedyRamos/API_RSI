# Deploy manual na Oracle Cloud Always Free

Este projeto executa API Flask, worker RSI e PostgreSQL em uma única VM
Oracle. A configuração indicada para produção é a **VM.Standard.A1.Flex**
Always Free com **1 OCPU e 6 GB de RAM**.

> Não use a E2 Micro de 1 GB como destino final para API + worker + banco.
> Ela é insuficiente para a coleta contínua de todos os pares e timeframes.
> Em caso de espera por capacidade A1, há um modo temporário reduzido em
> [ORACLE_E2_MICRO_TEMPORARY.md](ORACLE_E2_MICRO_TEMPORARY.md).

O worker já é contínuo. Não inicie `workers/scheduler.py` junto com
`worker.py`, pois isso duplicaria o processamento.

## 1. Criar a VM

No Console Oracle, selecione:

- Shape: `VM.Standard.A1.Flex`;
- Recursos: 1 OCPU e 6 GB de RAM;
- Imagem: Ubuntu 24.04 **ou** Oracle Linux 9;
- Rede: a VCN e a subnet pública existentes podem ser reutilizadas;
- Endereço IP público: habilitado.

Não escolha load balancer, banco gerenciado ou qualquer recurso pago. A
escolha de disco padrão da imagem é suficiente para iniciar o projeto;
o volume PostgreSQL fica persistido no Docker da própria VM.

Na Security List ou NSG da Oracle, permita somente:

| Porta | Origem | Uso |
| --- | --- | --- |
| 22/TCP | Seu IP público | SSH |
| 80/TCP | `0.0.0.0/0` | Emissão e renovação do certificado HTTPS |
| 443/TCP | `0.0.0.0/0` | API e painel |

Não exponha as portas `5432`, `5000` ou `8000`.

## 2. Configurar um domínio HTTPS gratuito

Use um domínio seu ou um subdomínio gratuito, como DuckDNS. Crie um registro
`A` apontando para o IP público da VM. O nome escolhido será usado em
`CADDY_DOMAIN`.

Antes de publicar os containers, confirme a resolução:

```bash
nslookup api-seu-rsi.duckdns.org
```

O Caddy obtém e renova o certificado TLS automaticamente quando o DNS aponta
para a VM e as portas 80/443 estão liberadas.

## 3. Conectar e preparar o sistema operacional

O usuário SSH depende da imagem escolhida:

```bash
# Ubuntu 24.04
ssh ubuntu@IP_PUBLICO_DA_VM

# Oracle Linux 9
ssh opc@IP_PUBLICO_DA_VM
```

Instale Docker Engine e o plugin Docker Compose de acordo com a documentação
oficial da imagem escolhida:

- [Docker no Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Docker no CentOS / Oracle Linux](https://docs.docker.com/engine/install/centos/)

Depois da instalação, habilite Docker e adicione o usuário da VM ao grupo:

```bash
# Use ubuntu na imagem Ubuntu; use opc na imagem Oracle Linux.
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
# ou: sudo usermod -aG docker opc
exit
```

Reconecte-se por SSH e valide:

```bash
uname -m
docker --version
docker compose version
```

O resultado de `uname -m` deve ser `aarch64` ou `arm64`.

Também replique as regras de rede no firewall da VM:

```bash
# Ubuntu
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Oracle Linux
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

## 4. Baixar o projeto e criar o ambiente de produção

```bash
git clone https://github.com/KennnedyRamos/API_RSI.git
cd API_RSI
cp deploy/.env.production.example deploy/.env.production
chmod 600 deploy/.env.production
```

Edite somente `deploy/.env.production` na VM:

```bash
nano deploy/.env.production
```

Preencha obrigatoriamente:

- `POSTGRES_PASSWORD`: gere uma senha hexadecimal segura;
- `DATABASE_URL`: use a **mesma** senha e mantenha o host interno `db:5432`;
- `CADDY_DOMAIN`: seu domínio já apontado para a VM;
- `CADDY_EMAIL`: seu e-mail real para o certificado TLS.

Gere uma senha segura assim:

```bash
openssl rand -hex 24
```

Deixe `TELEGRAM_ENABLED=false` até configurar um token seguro e o chat de
destino. Nunca copie o `.env` de desenvolvimento nem envie o arquivo de
produção ao GitHub.

## 5. Validar antes de iniciar

O pré-check não cria nem remove recursos. Ele valida arquitetura ARM64,
Docker, Compose e campos obrigatórios do ambiente:

```bash
bash deploy/preflight_oracle_a1.sh deploy/.env.production
```

O resultado esperado é:

```text
OK: VM ARM64, Docker Compose e configuração de produção validados.
```

Se o script avisar sobre DNS, corrija o registro `A` antes de iniciar Caddy.

## 6. Publicar e validar

```bash
docker compose --env-file deploy/.env.production up -d --build
docker compose --env-file deploy/.env.production ps
docker compose --env-file deploy/.env.production logs --tail=100 migrate api worker caddy
```

O serviço `migrate` executa `flask db upgrade` uma vez. API e worker só
iniciam quando o banco estiver saudável e a migration concluir.

Valide externamente:

```bash
curl https://api-seu-rsi.duckdns.org/api/v1/health
curl https://api-seu-rsi.duckdns.org/api/v1/ready
```

O painel provisório estará em:

```text
https://api-seu-rsi.duckdns.org/dashboard
```

## Operação, atualização e backup

Ver logs:

```bash
docker compose --env-file deploy/.env.production logs -f worker
docker compose --env-file deploy/.env.production logs -f api
```

Antes de migrations ou atualizações, faça um backup:

```bash
mkdir -p backups
docker compose --env-file deploy/.env.production exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/rsi-$(date +%F-%H%M%S).sql
```

Atualize de forma segura:

```bash
git pull --ff-only
bash deploy/preflight_oracle_a1.sh deploy/.env.production
docker compose --env-file deploy/.env.production up -d --build
```

Para parar sem apagar o banco:

```bash
docker compose --env-file deploy/.env.production down
```

Nunca use `docker compose down -v` em produção: ele remove o volume
PostgreSQL.

## Futuro frontend no Render

Quando a interface independente estiver pronta, crie no Render um Static Site
ligado ao GitHub. Depois, coloque a URL HTTPS exata dele em
`CORS_ALLOWED_ORIGINS` na VM e execute:

```bash
docker compose --env-file deploy/.env.production up -d
```

Se o frontend substituir o painel provisório, atualize também
`DASHBOARD_PUBLIC_URL`. Nunca use `CORS_ALLOWED_ORIGINS=*`.
