# SPDX-License-Identifier: GPL-3.0-or-later
"""Consulta ao known_hosts: o host já teve a chave aceita? Sem GTK."""

from __future__ import annotations

import shutil
import subprocess


def alvo(host: str, port: int | str | None = None) -> str:
    """Como o OpenSSH nomeia o host no known_hosts (porta fora da 22 entre `[]`)."""
    try:
        numero = int(port) if port not in (None, "") else 22
    except (TypeError, ValueError):
        numero = 22
    return host if numero == 22 else f"[{host}]:{numero}"


def is_known(host: str, port: int | str | None = None, *, timeout: float = 5.0) -> bool:
    """Diz se a chave do host já está registrada.

    Na dúvida (sem `ssh-keygen`, erro ou demora) devolve False: o caminho seguro
    é deixar o ssh perguntar ao usuário.
    """
    if not host:
        return False
    binario = shutil.which("ssh-keygen")
    if binario is None:
        return False
    try:
        resultado = subprocess.run(
            [binario, "-F", alvo(host, port)],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return resultado.returncode == 0
