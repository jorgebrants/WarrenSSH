# SPDX-License-Identifier: GPL-3.0-or-later
"""Constrói o argv do `ssh` a partir das propriedades resolvidas. Sem GTK."""

from __future__ import annotations

import os
import shlex
import shutil
from typing import Any, Iterable, Sequence

SSH_BINARY = "ssh"

#: Marca que o processo está dentro de um sandbox Flatpak.
FLATPAK_MARKER = "/.flatpak-info"


class CommandError(ValueError):
    """Propriedades insuficientes ou inseguras para montar o comando."""


def default_ssh_command() -> list[str]:
    """Como invocar o ssh neste ambiente.

    `WARRENSSH_SSH_BINARY` tem a palavra final. Fora isso, usamos o `ssh` do
    PATH; e se estivermos num Flatpak sem `ssh` dentro do sandbox, caímos no
    `ssh` do host via `flatpak-spawn` — que também dá acesso natural ao
    ssh-agent e ao ~/.ssh do usuário.
    """
    override = os.environ.get("WARRENSSH_SSH_BINARY")
    if override:
        return shlex.split(override)
    if shutil.which(SSH_BINARY):
        return [SSH_BINARY]
    if os.path.exists(FLATPAK_MARKER) and shutil.which("flatpak-spawn"):
        return ["flatpak-spawn", "--host", SSH_BINARY]
    # Sem ssh em lugar nenhum: deixamos o spawn falhar com erro visível.
    return [SSH_BINARY]


def build_ssh_argv(
    resolved: dict[str, Any],
    *,
    ssh_binary: str | None = None,
    ssh_command: Sequence[str] | None = None,
) -> list[str]:
    """Monta o argv do ssh a partir do dict devolvido por `resolve_all`.

    Espera as chaves: host (obrigatória), port, user, identity_file, proxy_jump,
    request_pty, extra_ssh_args, startup_command.
    """
    host = _clean(resolved.get("host"))
    if not host:
        raise CommandError("conexão sem host definido")
    _reject_option_like(host, "host")

    if ssh_command is not None:
        prefixo = list(ssh_command)
    elif ssh_binary is not None:
        prefixo = [ssh_binary]
    else:
        prefixo = default_ssh_command()
    if not prefixo:
        raise CommandError("comando do ssh vazio")

    argv: list[str] = list(prefixo)

    port = _as_port(resolved.get("port"))
    if port is not None and port != 22:
        argv += ["-p", str(port)]

    identity_file = _clean(resolved.get("identity_file"))
    if identity_file:
        argv += ["-i", os.path.expanduser(identity_file)]

    proxy_jump = _clean(resolved.get("proxy_jump"))
    if proxy_jump:
        _reject_option_like(proxy_jump, "proxy_jump")
        argv += ["-J", proxy_jump]

    if resolved.get("request_pty"):
        argv.append("-t")

    argv += _as_args(resolved.get("extra_ssh_args"))

    user = _clean(resolved.get("user"))
    if user:
        _reject_option_like(user, "user")
        argv.append(f"{user}@{host}")
    else:
        argv.append(host)

    startup_command = _clean(resolved.get("startup_command"))
    if startup_command:
        # Comando remoto: o ssh entrega a string inteira ao shell do outro lado.
        argv.append(startup_command)

    return argv


def describe(argv: Iterable[str]) -> str:
    """Versão legível do argv, para tooltip/log."""
    return " ".join(shlex.quote(part) for part in argv)


# --------------------------------------------------------------------- helpers


def _clean(value: Any) -> str:
    """Normaliza para string sem espaços nas pontas (None e 0 viram '')."""
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _as_port(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(f"porta inválida: {value!r}") from exc
    if not 1 <= port <= 65535:
        raise CommandError(f"porta fora da faixa 1-65535: {port}")
    return port


def _as_args(value: Any) -> list[str]:
    """Aceita lista de argumentos ou uma linha única no estilo shell."""
    if not value:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    return [str(part) for part in value]


def _reject_option_like(value: str, field: str) -> None:
    """Um valor começando com '-' viraria opção do ssh — recusa explícita."""
    if value.startswith("-"):
        raise CommandError(f"{field} não pode começar com '-': {value!r}")
