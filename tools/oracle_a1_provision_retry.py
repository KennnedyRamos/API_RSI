#!/usr/bin/env python3
"""Tenta provisionar uma Oracle A1 gratuita até que exista uma A1 utilizável.

Este utilitário é propositalmente separado do monitor de capacidade: ele cria
uma VM somente quando é executado explicitamente pela tarefa agendada local.
Ele não remove nem altera instâncias existentes e interrompe a própria tarefa
quando confirma uma A1 fora do estado transitório de provisionamento.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

try:
    import oci
except ImportError as exc:  # pragma: no cover - depende da instalação local
    raise SystemExit(
        "O SDK OCI não está instalado. Execute: "
        ".\\.venv\\Scripts\\python.exe -m pip install oci"
    ) from exc


SHAPE = "VM.Standard.A1.Flex"
OCPUS = 1
MEMORY_GB = 6
DEFAULT_DISPLAY_NAME = "rsi-radar-api-6gb"
DEFAULT_SUBNET_NAME = "rsi-radar-public-subnet"
DEFAULT_TASK_NAME = "RSI Radar - Provisionar Oracle A1 6GB"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RsiRadar"
DEFAULT_STATE_FILE = APP_DIR / "oracle-a1-provision-retry-state.json"
DEFAULT_LOG_FILE = APP_DIR / "oracle-a1-provision-retry.log"
DEFAULT_LOCK_FILE = APP_DIR / "oracle-a1-provision-retry.lock"
LOCK_STALE_SECONDS = 15 * 60
RETRY_TOKEN_TTL_SECONDS = 23 * 60 * 60
MAX_LOG_BYTES = 512 * 1024
LOG_TAIL_BYTES = 128 * 1024
TRANSIENT_INSTANCE_STATES = {"PROVISIONING", "STARTING", "TERMINATING"}


class RetryError(RuntimeError):
    """Erro seguro para a saída da tarefa agendada."""


class PermanentRetryError(RetryError):
    """Erro que exige intervenção humana antes de uma nova tentativa."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    """Lê o estado anterior sem tornar um arquivo corrompido bloqueante."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def append_log(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= MAX_LOG_BYTES:
        with path.open("rb") as existing_log:
            existing_log.seek(-LOG_TAIL_BYTES, os.SEEK_END)
            tail = existing_log.read().decode("utf-8", errors="replace")
        temporary = path.with_suffix(".tmp")
        temporary.write_text("[log anterior truncado]\n" + tail, encoding="utf-8")
        temporary.replace(path)
    summary = (
        f"{result['checked_at']} | {result['outcome']}"
        f" | {result.get('detail', '')}".rstrip()
    )
    with path.open("a", encoding="utf-8") as log_file:
        log_file.write(summary + "\n")


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Evita duas tentativas locais concorrentes de criar a mesma VM."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        age = time.time() - path.stat().st_mtime
        if age > LOCK_STALE_SECONDS:
            path.unlink()
    except FileNotFoundError:
        pass

    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RetryError("Outra tentativa local ainda está em execução.") from exc

    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
            lock_file.write(str(os.getpid()))
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def load_oci_config(config_file: Path, profile: str) -> dict[str, str]:
    if not config_file.exists():
        raise PermanentRetryError("A configuração OCI local não foi encontrada.")

    try:
        config = oci.config.from_file(
            file_location=str(config_file),
            profile_name=profile,
        )
        oci.config.validate_config(config)
    except Exception as exc:
        raise PermanentRetryError(
            "Não foi possível validar a configuração OCI local."
        ) from exc

    return config


def resolve_availability_domain(
    identity_client: Any,
    tenancy_id: str,
    requested_domain: str | None,
) -> str:
    domains = identity_client.list_availability_domains(tenancy_id).data
    if not domains:
        raise PermanentRetryError("Nenhum domínio de disponibilidade foi encontrado.")

    if requested_domain:
        expected = requested_domain.casefold()
        for domain in domains:
            candidates = (domain.name, getattr(domain, "display_name", None))
            if any(candidate and candidate.casefold() == expected for candidate in candidates):
                return domain.name
        raise PermanentRetryError(
            "O domínio de disponibilidade informado não existe na região."
        )

    if len(domains) == 1:
        return domains[0].name

    raise PermanentRetryError(
        "A região possui mais de um domínio de disponibilidade; informe "
        "--availability-domain para escolher um explicitamente."
    )


def find_subnet(network_client: Any, tenancy_id: str, subnet_name: str) -> Any:
    matches = [
        subnet
        for subnet in network_client.list_subnets(tenancy_id).data
        if subnet.display_name == subnet_name
    ]
    if len(matches) != 1:
        raise PermanentRetryError(
            "Não foi possível identificar unicamente a subnet configurada para a A1."
        )
    subnet = matches[0]
    if getattr(subnet, "prohibit_public_ip_on_vnic", False):
        raise PermanentRetryError(
            "A subnet selecionada bloqueia IP público e não serve para este deploy."
        )
    return subnet


def latest_oracle_linux_9_image(compute_client: Any, tenancy_id: str) -> Any:
    images = compute_client.list_images(
        tenancy_id,
        operating_system="Oracle Linux",
        operating_system_version="9",
        shape=SHAPE,
        sort_by="TIMECREATED",
        sort_order="DESC",
    ).data
    for image in images:
        if image.lifecycle_state == "AVAILABLE":
            return image
    raise PermanentRetryError(
        "Nenhuma imagem Oracle Linux 9 compatível com a A1 foi encontrada."
    )


def active_a1_instances(compute_client: Any, tenancy_id: str) -> list[Any]:
    """Lista todas as A1 ativas, inclusive quando a API precisa de paginação."""

    ignored_states = {"TERMINATED", "TERMINATING"}
    response = oci.pagination.list_call_get_all_results(
        compute_client.list_instances,
        tenancy_id,
    )
    return [
        instance
        for instance in response.data
        if instance.shape == SHAPE and instance.lifecycle_state not in ignored_states
    ]


def instance_result(instance: Any, *, same_display_name: bool) -> dict[str, Any]:
    state = instance.lifecycle_state
    if state in TRANSIENT_INSTANCE_STATES:
        outcome = "INSTANCE_PROVISIONING" if same_display_name else "OTHER_A1_PROVISIONING"
        detail = f"{state}: aguardando a instância A1 já solicitada"
        disable_task = False
    else:
        outcome = "INSTANCE_ALREADY_EXISTS" if same_display_name else "OTHER_A1_ALREADY_EXISTS"
        detail = f"{state}: uma A1 ativa já ocupa a capacidade da conta"
        disable_task = True
    return {
        "checked_at": now_iso(),
        "outcome": outcome,
        "detail": detail,
        "instance_id": instance.id,
        "disable_task": disable_task,
    }


def retry_token_from_state(state: dict[str, Any]) -> str:
    """Reutiliza o token durante 23 h em casos de resposta inconclusiva."""

    token = state.get("opc_retry_token")
    requested_at = state.get("launch_requested_at")
    if isinstance(token, str) and isinstance(requested_at, str):
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(requested_at)
        except (TypeError, ValueError):
            age = None
        if age is not None and 0 <= age.total_seconds() < RETRY_TOKEN_TTL_SECONDS:
            return token
    return uuid4().hex


def pending_launch_result(
    token: str,
    requested_at: str,
    selection: dict[str, Any],
    *,
    outcome: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "checked_at": now_iso(),
        "outcome": outcome,
        "detail": detail,
        "opc_retry_token": token,
        "launch_requested_at": requested_at,
        **selection,
        "disable_task": False,
    }


def is_capacity_error(exc: Exception) -> bool:
    message = getattr(exc, "message", "")
    code = getattr(exc, "code", "")
    combined = f"{message} {code}".casefold()
    return "out of host capacity" in combined or "host capacity" in combined


def is_permanent_service_error(exc: Any) -> bool:
    return getattr(exc, "status", None) in {400, 401, 403, 404}


def disable_scheduled_task(task_name: str) -> tuple[bool, str]:
    if os.name != "nt":
        return False, "tarefa não desativada: este comando requer Windows"

    result = subprocess.run(
        ["schtasks.exe", "/Change", "/TN", task_name, "/Disable"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True, "tarefa agendada desativada"
    return False, "não foi possível desativar automaticamente a tarefa agendada"


def parse_arguments() -> argparse.Namespace:
    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    parser = argparse.ArgumentParser(
        description="Tenta criar uma VM Oracle A1 gratuita de 1 OCPU e 6 GB."
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=user_profile / ".oci" / "config",
        help="Arquivo local de configuração OCI.",
    )
    parser.add_argument("--profile", default="DEFAULT", help="Perfil OCI a utilizar.")
    parser.add_argument(
        "--display-name",
        default=DEFAULT_DISPLAY_NAME,
        help="Nome destinado à nova instância A1.",
    )
    parser.add_argument(
        "--subnet-name",
        default=DEFAULT_SUBNET_NAME,
        help="Nome exato da subnet pública existente.",
    )
    parser.add_argument(
        "--ssh-public-key",
        type=Path,
        default=user_profile / ".ssh" / "rsi_radar_oracle_ed25519.pub",
        help="Chave pública SSH a instalar na nova VM.",
    )
    parser.add_argument(
        "--availability-domain",
        help="Opcional; omitido quando a região tem somente um AD.",
    )
    parser.add_argument(
        "--task-name",
        default=DEFAULT_TASK_NAME,
        help="Tarefa Windows a desativar após confirmar a criação da instância.",
    )
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida os recursos selecionados sem criar uma VM.",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    previous_state = read_json(args.state_file)
    config = load_oci_config(args.config_file, args.profile)
    tenancy_id = config["tenancy"]
    identity_client = oci.identity.IdentityClient(config)
    compute_client = oci.core.ComputeClient(config)
    network_client = oci.core.VirtualNetworkClient(config)

    existing_instances = active_a1_instances(compute_client, tenancy_id)
    matching_instance = next(
        (instance for instance in existing_instances if instance.display_name == args.display_name),
        None,
    )
    if matching_instance:
        return instance_result(matching_instance, same_display_name=True)
    if existing_instances:
        return instance_result(existing_instances[0], same_display_name=False)

    if not args.ssh_public_key.exists():
        raise PermanentRetryError("A chave pública SSH configurada não foi encontrada.")

    availability_domain = resolve_availability_domain(
        identity_client,
        tenancy_id,
        args.availability_domain,
    )
    subnet = find_subnet(network_client, tenancy_id, args.subnet_name)
    image = latest_oracle_linux_9_image(compute_client, tenancy_id)

    selection = {
        "availability_domain": availability_domain,
        "subnet_id": subnet.id,
        "image_id": image.id,
        "image_name": image.display_name,
    }
    if args.dry_run:
        return {
            "checked_at": now_iso(),
            "outcome": "DRY_RUN",
            "detail": "recursos validados; nenhuma VM foi criada",
            **selection,
            "disable_task": False,
        }

    ssh_key = args.ssh_public_key.read_text(encoding="utf-8").strip()
    if not ssh_key:
        raise PermanentRetryError("A chave pública SSH configurada está vazia.")

    launch_details = oci.core.models.LaunchInstanceDetails(
        availability_domain=availability_domain,
        compartment_id=tenancy_id,
        display_name=args.display_name,
        shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=OCPUS,
            memory_in_gbs=MEMORY_GB,
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            source_type="image",
            image_id=image.id,
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=subnet.id,
            assign_public_ip=True,
        ),
        metadata={"ssh_authorized_keys": ssh_key},
    )
    retry_token = retry_token_from_state(previous_state)
    requested_at = now_iso()
    write_json(
        args.state_file,
        pending_launch_result(
            retry_token,
            requested_at,
            selection,
            outcome="LAUNCH_REQUEST_PENDING",
            detail="solicitação de criação enviada; aguardando a resposta da Oracle",
        ),
    )
    try:
        instance = compute_client.launch_instance(
            launch_details,
            opc_retry_token=retry_token,
        ).data
    except oci.exceptions.ServiceError as exc:
        if is_capacity_error(exc):
            return {
                "checked_at": now_iso(),
                "outcome": "OUT_OF_HOST_CAPACITY",
                "detail": "a Oracle ainda não liberou capacidade para a A1",
                **selection,
                "disable_task": False,
            }
        if is_permanent_service_error(exc):
            raise PermanentRetryError(
                f"A Oracle recusou a criação (HTTP {exc.status}, código {exc.code})."
            ) from exc
        return pending_launch_result(
            retry_token,
            requested_at,
            selection,
            outcome="LAUNCH_UNCONFIRMED",
            detail=(
                "a resposta da Oracle foi inconclusiva; a próxima tentativa usará "
                "o mesmo token de idempotência"
            ),
        )
    except Exception:
        return pending_launch_result(
            retry_token,
            requested_at,
            selection,
            outcome="LAUNCH_UNCONFIRMED",
            detail=(
                "a conexão terminou sem confirmação; a próxima tentativa usará "
                "o mesmo token de idempotência"
            ),
        )

    return {
        "checked_at": now_iso(),
        "outcome": "LAUNCH_ACCEPTED",
        "detail": f"{instance.lifecycle_state}: {instance.id}",
        "instance_id": instance.id,
        "opc_retry_token": retry_token,
        "launch_requested_at": requested_at,
        **selection,
        "disable_task": False,
    }


def finalize_result(args: argparse.Namespace, result: dict[str, Any]) -> int:
    """Persiste o resultado e torna falha a desativação da tarefa visível."""

    exit_code = 0
    if result.pop("disable_task", False):
        disabled, task_action = disable_scheduled_task(args.task_name)
        result["task_action"] = task_action
        if not disabled:
            result["task_disable_failed"] = True
            exit_code = 1

    write_json(args.state_file, result)
    append_log(args.log_file, result)
    printable_result = {
        key: value for key, value in result.items() if key != "opc_retry_token"
    }
    print(json.dumps(printable_result, ensure_ascii=False))
    return exit_code


def main() -> int:
    args = parse_arguments()
    try:
        with exclusive_lock(args.lock_file):
            result = run(args)
            if args.dry_run:
                printable_result = {
                    key: value for key, value in result.items() if key != "opc_retry_token"
                }
                print(json.dumps(printable_result, ensure_ascii=False))
                return 0
            return finalize_result(args, result)
    except PermanentRetryError as exc:
        result = {
            "checked_at": now_iso(),
            "outcome": "ERROR_PERMANENT",
            "detail": str(exc),
            "disable_task": True,
        }
        exit_code = finalize_result(args, result)
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1 if exit_code == 0 else exit_code
    except RetryError as exc:
        result = {
            "checked_at": now_iso(),
            "outcome": "ERROR",
            "detail": str(exc),
        }
        write_json(args.state_file, result)
        append_log(args.log_file, result)
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    except Exception:
        result = {
            "checked_at": now_iso(),
            "outcome": "ERROR",
            "detail": "falha inesperada ao tentar criar a Oracle A1",
        }
        write_json(args.state_file, result)
        append_log(args.log_file, result)
        print("ERRO: falha inesperada ao tentar criar a Oracle A1.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
