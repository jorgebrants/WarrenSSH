# SPDX-License-Identifier: GPL-3.0-or-later
"""Túneis de porta do SSH (-L, -R, -D). Sem GTK.

Três tipos, com significados bem diferentes:

- **local** (`-L`): abre uma porta AQUI que sai LÁ. É como se traz um banco de
  dados que só escuta em `localhost` do servidor para a sua máquina.
- **remoto** (`-R`): abre uma porta LÁ que volta para CÁ.
- **dinâmico** (`-D`): um proxy SOCKS aqui, e toda a navegação sai pelo servidor.

Guardamos os túneis como dicionários (e não como a string do ssh) para a
interface poder editar campo a campo e validar antes de tentar conectar — uma
sintaxe errada faz o ssh recusar a conexão inteira.
"""

from __future__ import annotations

from typing import Any, Iterable

LOCAL = "local"
REMOTE = "remote"
DYNAMIC = "dynamic"

TIPOS: tuple[str, ...] = (LOCAL, REMOTE, DYNAMIC)

ROTULOS: dict[str, str] = {
    LOCAL: "Local (-L)",
    REMOTE: "Remoto (-R)",
    DYNAMIC: "SOCKS (-D)",
}

#: Opção do ssh para cada tipo.
FLAGS: dict[str, str] = {LOCAL: "-L", REMOTE: "-R", DYNAMIC: "-D"}


class TunnelError(ValueError):
    """Túnel mal descrito — melhor avisar do que deixar o ssh recusar tudo."""


def normalize(bruto: Any) -> dict[str, Any]:
    """Valida um túnel e devolve a forma canônica.

    Campos: `type`, `listen_port`, e — fora do dinâmico — `host` e `host_port`.
    `bind` é opcional e diz em que endereço escutar (por padrão só `localhost`).
    """
    if not isinstance(bruto, dict):
        raise TunnelError(f"túnel inválido: {bruto!r}")

    tipo = str(bruto.get("type") or LOCAL).lower()
    if tipo not in TIPOS:
        raise TunnelError(f"tipo de túnel desconhecido: {tipo!r}")

    tunel: dict[str, Any] = {
        "type": tipo,
        "listen_port": _porta(bruto.get("listen_port"), "porta de escuta"),
    }

    bind = str(bruto.get("bind") or "").strip()
    if bind:
        _sem_dois_pontos(bind, "endereço de escuta")
        tunel["bind"] = bind

    if tipo == DYNAMIC:
        return tunel

    host = str(bruto.get("host") or "").strip()
    if not host:
        raise TunnelError("túnel sem destino: informe o host")
    _sem_dois_pontos(host, "host de destino")
    tunel["host"] = host
    tunel["host_port"] = _porta(bruto.get("host_port"), "porta de destino")
    return tunel


def to_args(tuneis: Iterable[Any]) -> list[str]:
    """Converte a lista de túneis nos argumentos do ssh."""
    argv: list[str] = []
    for bruto in tuneis or ():
        tunel = normalize(bruto)
        argv += [FLAGS[tunel["type"]], to_spec(tunel)]
    return argv


def to_spec(tunel: dict[str, Any]) -> str:
    """A string no formato que o ssh espera."""
    bind = tunel.get("bind")
    escuta = f"{bind}:{tunel['listen_port']}" if bind else str(tunel["listen_port"])
    if tunel["type"] == DYNAMIC:
        return escuta
    return f"{escuta}:{tunel['host']}:{tunel['host_port']}"


def describe(tunel: dict[str, Any]) -> str:
    """Frase curta para a interface, dizendo o que o túnel faz."""
    t = normalize(tunel)
    escuta = f"{t.get('bind', 'localhost')}:{t['listen_port']}"
    if t["type"] == DYNAMIC:
        return f"proxy SOCKS em {escuta}"
    if t["type"] == LOCAL:
        return f"{escuta} aqui → {t['host']}:{t['host_port']} visto do servidor"
    return f"{escuta} no servidor → {t['host']}:{t['host_port']} visto daqui"


def parse_spec(texto: str, tipo: str = LOCAL) -> dict[str, Any]:
    """Lê a forma textual do ssh (`8080:localhost:80`) e devolve o túnel."""
    partes = [p.strip() for p in str(texto).strip().split(":") if p.strip() != ""]
    if tipo == DYNAMIC:
        if len(partes) == 1:
            return normalize({"type": tipo, "listen_port": partes[0]})
        if len(partes) == 2:
            return normalize({"type": tipo, "bind": partes[0], "listen_port": partes[1]})
        raise TunnelError(f"SOCKS espera 'porta' ou 'endereço:porta': {texto!r}")

    if len(partes) == 3:
        return normalize(
            {"type": tipo, "listen_port": partes[0], "host": partes[1], "host_port": partes[2]}
        )
    if len(partes) == 4:
        return normalize(
            {
                "type": tipo,
                "bind": partes[0],
                "listen_port": partes[1],
                "host": partes[2],
                "host_port": partes[3],
            }
        )
    raise TunnelError(
        f"esperado 'porta:host:porta' (ou 'endereço:porta:host:porta'): {texto!r}"
    )


# --------------------------------------------------------------------- helpers


def _porta(valor: Any, campo: str) -> int:
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError) as exc:
        raise TunnelError(f"{campo} inválida: {valor!r}") from exc
    if not 1 <= numero <= 65535:
        raise TunnelError(f"{campo} fora da faixa 1-65535: {numero}")
    return numero


def _sem_dois_pontos(valor: str, campo: str) -> None:
    """`:` separa os campos na sintaxe do ssh; deixar passar quebraria o resto."""
    if ":" in valor:
        raise TunnelError(f"{campo} não pode conter ':': {valor!r}")
