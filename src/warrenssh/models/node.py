# SPDX-License-Identifier: GPL-3.0-or-later
"""Modelo de nó da árvore de conexões. Sem dependência de GTK."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

NodeKind = Literal["folder", "connection"]

#: Propriedades de uma conexão que participam da cascata de herança.
CONNECTION_KEYS: tuple[str, ...] = (
    "host",
    "port",
    "user",
    "identity_file",
    "proxy_jump",
    "request_pty",
    "extra_ssh_args",
    "startup_command",
    "charset",
    "scrollback_lines",
    "color_scheme",
)

#: Valores usados quando a cascata não produz nada para a chave.
DEFAULTS: dict[str, Any] = {
    "port": 22,
    "request_pty": False,
    "extra_ssh_args": [],
    "charset": "UTF-8",
    "scrollback_lines": 10000,
    "color_scheme": "system",
}


@dataclass
class Node:
    """Um nó da árvore: pasta (perfil de grupo) ou conexão SSH."""

    id: str
    parent_id: str | None
    kind: NodeKind
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    inherited: set[str] = field(default_factory=set)
    position: int = 0

    @property
    def is_folder(self) -> bool:
        return self.kind == "folder"

    @property
    def is_connection(self) -> bool:
        return self.kind == "connection"

    def to_dict(self) -> dict[str, Any]:
        """Forma serializável em JSON (o set vira lista ordenada)."""
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "kind": self.kind,
            "name": self.name,
            "properties": dict(self.properties),
            "inherited": sorted(self.inherited),
            "position": self.position,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        return cls(
            id=str(data["id"]),
            parent_id=data.get("parent_id"),
            kind=data.get("kind", "connection"),
            name=data.get("name", ""),
            properties=dict(data.get("properties") or {}),
            inherited=set(data.get("inherited") or ()),
            position=int(data.get("position", 0)),
        )


def new_node(
    kind: NodeKind,
    name: str,
    *,
    parent_id: str | None = None,
    properties: dict[str, Any] | None = None,
    inherited: set[str] | None = None,
    position: int = 0,
) -> Node:
    """Cria um nó com id uuid4."""
    return Node(
        id=str(uuid.uuid4()),
        parent_id=parent_id,
        kind=kind,
        name=name,
        properties=dict(properties or {}),
        inherited=set(inherited or ()),
        position=position,
    )


def new_folder(name: str, **kwargs: Any) -> Node:
    return new_node("folder", name, **kwargs)


def new_connection(name: str, **kwargs: Any) -> Node:
    return new_node("connection", name, **kwargs)
