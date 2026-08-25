#!/usr/bin/env python3
"""Tenta provisionar uma Oracle A1 gratuita até a Oracle aceitar a criação.

Este utilitário é propositalmente separado do monitor de capacidade: ele cria
uma VM somente quando é executado explicitamente pela tarefa agendada local.
Ele não remove nem altera instâncias existentes e interrompe a própria tarefa
após a Oracle aceitar uma criação ou encontrar uma A1 já criada com o mesmo nome.
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


class RetryError(RuntimeError):
    """Erro seguro para a saída da tarefa agendada."""


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


def append_log(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        raise RetryError("A configuração OCI local não foi encontrada.")

    try:
        config = oci.config.from_file(
            file_location=str(config_file),
            profile_name=profile,
        )
        oci.config.validate_config(config)
    except Exception as exc:
        raise RetryError("Não foi possível validar a configuração OCI local.") from exc

    return config


def resolve_availability_domain(
    identity_client: Any,
    tenancy_id: str,
    requested_domain: str | None,
) -> str:
    domains = identity_client.list_availability_domains(tenancy_id).data
    if not domains:
        raise RetryError("Nenhum domínio de disponibilidade foi encontrado.")

    if requested_domain:
        expected = requested_domain.casefold()
        for domain in domains:
            candidates = (domain.name, getattr(domain, "display_name", None))
            if any(candidate and candidate.casefold() == expected for candidate in candidates):
                return domain.name
        raise RetryError("O domínio de disponibilidade informado não existe na região.")

    if len(domains) == 1:
        return domains[0].name

    raise RetryError(
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
        raise RetryError(
            "Não foi possível identificar unicamente a subnet configurada para a A1."
        )
    return matches[0]


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
    raise RetryError("Nenhuma imagem Oracle Linux 9 compatível com a A1 foi encontrada.")


def existing_a1(compute_client: Any, tenancy_id: str, display_name: str) -> Any | None:
    ignored_states = {"TERMINATED", "TERMINATING"}
    for instance in compute_client.list_instances(tenancy_id).data:
        if (
            instance.display_name == display_name
            and instance.shape == SHAPE
            and instance.lifecycle_state not in ignored_states
        ):
            return instance
    return None


def is_capacity_error(exc: Exception) -> bool:
    message = getattr(exc, "message", "")
    code = getattr(exc, "code", "")
    combined = f"{message} {code}".casefold()
    return "out of host capacity" in combined or "host capacity" in combined


def disable_scheduled_task(task_name: str) -> str:
    if os.name != "nt":
        return "tarefa não desativada: este comando requer Windows"

    result = subprocess.run(
        ["schtasks.exe", "/Change", "/TN", task_name, "/Disable"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return "tarefa agendada desativada"
    return "não foi possível desativar automaticamente a tarefa agendada"


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
        help="Tarefa Windows a desativar após uma criação aceita.",
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
    config = load_oci_config(args.config_file, args.profile)
    tenancy_id = config["tenancy"]
    identity_client = oci.identity.IdentityClient(config)
    compute_client = oci.core.ComputeClient(config)
    network_client = oci.core.VirtualNetworkClient(config)

    existing = existing_a1(compute_client, tenancy_id, args.display_name)
    if existing:
        return {
            "checked_at": now_iso(),
            "outcome": "INSTANCE_ALREADY_EXISTS",
            "detail": f"{existing.lifecycle_state}: {existing.id}",
            "instance_id": existing.id,
            "disable_task": True,
        }

    if not args.ssh_public_key.exists():
        raise RetryError("A chave pública SSH configurada não foi encontrada.")

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
        raise RetryError("A chave pública SSH configurada está vazia.")

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
    try:
        instance = compute_client.launch_instance(launch_details).data
    except oci.exceptions.ServiceError as exc:
        if is_capacity_error(exc):
            return {
                "checked_at": now_iso(),
                "outcome": "OUT_OF_HOST_CAPACITY",
                "detail": "a Oracle ainda não liberou capacidade para a A1",
                **selection,
                "disable_task": False,
            }
        raise RetryError(
            f"A Oracle recusou a criação (HTTP {exc.status}, código {exc.code})."
        ) from exc

    return {
        "checked_at": now_iso(),
        "outcome": "LAUNCH_ACCEPTED",
        "detail": f"{instance.lifecycle_state}: {instance.id}",
        "instance_id": instance.id,
        **selection,
        "disable_task": True,
    }


def main() -> int:
    args = parse_arguments()
    try:
        with exclusive_lock(args.lock_file):
            result = run(args)
            if result.pop("disable_task"):
                result["task_action"] = disable_scheduled_task(args.task_name)
            write_json(args.state_file, result)
            append_log(args.log_file, result)
            print(json.dumps(result, ensure_ascii=False))
            return 0
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
