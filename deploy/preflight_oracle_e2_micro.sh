#!/usr/bin/env bash
# Executa o pre-check de produção para a E2 Micro x86_64 temporária.

set -euo pipefail

PRECHECK_ALLOW_X86=true exec bash "$(dirname "$0")/preflight_oracle_a1.sh" "$@"
