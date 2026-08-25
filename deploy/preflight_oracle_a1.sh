#!/usr/bin/env bash
# Valida uma VM Oracle A1 antes de iniciar os containers de produção.
# Não cria, remove nem modifica recursos da Oracle ou do Docker.

set -euo pipefail

env_file="${1:-deploy/.env.production}"

fail() {
    printf 'ERRO: %s\n' "$*" >&2
    exit 1
}

warn() {
    printf 'AVISO: %s\n' "$*" >&2
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Comando obrigatório não encontrado: $1"
}

read_env_value() {
    local key="$1"
    local line
    line=$(grep -E "^${key}=" "$env_file" | head -n 1 || true)
    printf '%s' "${line#*=}"
}

require_env_value() {
    local key="$1"
    local value
    value=$(read_env_value "$key")

    [[ -n "$value" ]] || fail "Defina $key em $env_file."
    [[ "$value" != *"SUBSTITUA"* ]] || fail "Substitua o valor de exemplo de $key em $env_file."
    [[ "$value" != *"seu-rsi"* ]] || fail "Substitua o domínio de exemplo em $key."
}

architecture=$(uname -m)
case "$architecture" in
    aarch64|arm64)
        architecture_label="ARM64"
        ;;
    x86_64|amd64)
        [[ "${PRECHECK_ALLOW_X86:-false}" == "true" ]] || fail \
            "Esta VM não é ARM64 (arquitetura detectada: $architecture). Use uma Oracle A1."
        architecture_label="x86_64 (modo E2 Micro temporário)"
        ;;
    *) fail "Esta VM não é ARM64 (arquitetura detectada: $architecture). Use uma Oracle A1." ;;
esac

require_command docker
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin não está disponível."
[[ -f "$env_file" ]] || fail "Arquivo de produção não encontrado: $env_file"

require_env_value POSTGRES_PASSWORD
require_env_value DATABASE_URL
require_env_value CADDY_DOMAIN
require_env_value CADDY_EMAIL

database_url=$(read_env_value DATABASE_URL)
[[ "$database_url" == *"@db:5432/"* ]] || fail \
    "DATABASE_URL deve apontar para o host interno db:5432."

telegram_enabled=$(read_env_value TELEGRAM_ENABLED)
if [[ "$telegram_enabled" =~ ^(1|true|yes|on)$ ]]; then
    require_env_value TELEGRAM_BOT_TOKEN
    require_env_value TELEGRAM_CHAT_ID
fi

caddy_domain=$(read_env_value CADDY_DOMAIN)
if command -v getent >/dev/null 2>&1; then
    getent ahostsv4 "$caddy_domain" >/dev/null 2>&1 || warn \
        "O DNS de $caddy_domain ainda não resolve nesta VM. O Caddy não conseguirá emitir HTTPS até ele apontar para o IP público."
fi

ENV_FILE="$env_file" docker compose --env-file "$env_file" config --quiet

printf 'OK: VM %s, Docker Compose e configuração de produção validados.\n' "$architecture_label"
