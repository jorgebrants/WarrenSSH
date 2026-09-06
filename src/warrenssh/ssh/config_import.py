# SPDX-License-Identifier: GPL-3.0-or-later
"""Importa hosts do ~/.ssh/config para a árvore. Sem GTK."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from warrenssh.models.editing import NON_INHERITABLE, fields_for
from warrenssh.models.node import Node, new_connection, new_folder
from warrenssh.models.store import Store
from warrenssh.ssh.ssh_config import SSHConfig

IMPORT_FOLDER_NAME = "Importado do ~/.ssh/config"

#: Diretiva do ssh_config -> propriedade do nó. As chaves vêm em minúsculas.
DIRECTIVE_MAP: dict[str, str] = {
    "hostname": "host",
    "user": "user",
    "port": "port",
    "identityfile": "identity_file",
    "proxyjump": "proxy_jump",
}


@dataclass
class ImportedHost:
    """Um `Host` do ssh_config já traduzido para propriedades do WarrenSSH."""

    name: str
    properties: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """Linha curta para o preview: 'nome → user@host:port'."""
        host = self.properties.get("host", self.name)
        destino = f"{self.properties['user']}@{host}" if self.properties.get("user") else host
        port = self.properties.get("port")
        if port and port != 22:
            destino += f":{port}"
        jump = self.properties.get("proxy_jump")
        return f"{self.name} → {destino}" + (f" via {jump}" if jump else "")


def default_config_path() -> Path:
    return Path(os.path.expanduser("~/.ssh/config"))


def display_config_path() -> str:
    """Caminho como o usuário o conhece: `~/.ssh/config`, não o absoluto."""
    return _contract_home(str(default_config_path()))


def parse_config_text(text: str) -> list[ImportedHost]:
    """Lê um ssh_config e devolve um ImportedHost por `Host` concreto.

    Padrões com curinga (`Host *`, `Host *.interno`) emprestam valores aos
    demais, mas não viram conexão.
    """
    return _hosts_de(SSHConfig.from_text(text))


def parse_config_file(path: Path | str | None = None) -> list[ImportedHost]:
    """Lê o arquivo do disco, seguindo `Include`. Ausente = nada a importar."""
    target = Path(path) if path is not None else default_config_path()
    return _hosts_de(SSHConfig.from_file(target))


def _hosts_de(config: SSHConfig) -> list[ImportedHost]:
    hosts: list[ImportedHost] = []
    for name in config.host_names():
        properties = _properties_for(config, name)
        if properties.get("host"):
            hosts.append(ImportedHost(name=name, properties=properties))
    return hosts


def import_into(
    store: Store,
    hosts: Iterable[ImportedHost],
    *,
    folder_name: str = IMPORT_FOLDER_NAME,
) -> tuple[Node, list[Node], list[ImportedHost]]:
    """Cria/reusa a pasta de importação e adiciona os hosts que ainda não existem.

    Devolve (pasta, nós criados, hosts pulados por já existirem lá).
    """
    folder = next(
        (n for n in store.roots() if n.kind == "folder" and n.name == folder_name),
        None,
    )
    if folder is None:
        folder = store.add(new_folder(folder_name))

    existentes = {child.name for child in store.children(folder.id)}
    criados: list[Node] = []
    pulados: list[ImportedHost] = []

    herdaveis = [key for key in fields_for("connection") if key not in NON_INHERITABLE]
    for host in hosts:
        if host.name in existentes:
            pulados.append(host)
            continue
        node = new_connection(
            host.name,
            parent_id=folder.id,
            properties=dict(host.properties),
            # O que o ssh_config não disse, a pasta pode preencher depois.
            inherited={key for key in herdaveis if key not in host.properties},
        )
        store.add(node)
        criados.append(node)
        existentes.add(host.name)

    return folder, criados, pulados


# --------------------------------------------------------------------- internos


def _contract_home(path: str) -> str:
    """Mantém o caminho na forma portátil entre máquinas (`~/...`)."""
    home = os.path.expanduser("~")
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def _properties_for(config: SSHConfig, name: str) -> dict[str, Any]:
    """Resolve um host (com os curingas já aplicados) e traduz as diretivas."""
    lookup = config.lookup(name)
    properties: dict[str, Any] = {}

    for directive, key in DIRECTIVE_MAP.items():
        value = lookup.get(directive)
        if value in (None, "", []):
            continue
        if key == "identity_file":
            value = value[0] if isinstance(value, (list, tuple)) else value
            value = _contract_home(str(value))
        if key == "port":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        properties[key] = value

    # `Host srv` sem HostName: o próprio nome é o endereço.
    properties.setdefault("host", name)

    if str(lookup.get("requesttty", "")).lower() in ("yes", "force"):
        properties["request_pty"] = True

    return properties
