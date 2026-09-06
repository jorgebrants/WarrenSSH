# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolução em cascata: o coração do WarrenSSH.

Cada propriedade de um nó ou tem valor local, ou herda do pai. Resolver uma
chave é subir a árvore até encontrar o primeiro nó que não a marca como herdada.
"""

from __future__ import annotations

from typing import Any

from warrenssh.models.node import CONNECTION_KEYS, DEFAULTS, Node
from warrenssh.models.store import Store


def resolve(node: Node, key: str, store: Store) -> Any:
    """Valor efetivo de `key` para `node`, subindo a cadeia de herança.

    Só a árvore: o padrão global entra em `resolve_effective`/`resolve_all`, para
    que o editor consiga distinguir "herdado do pai" de "veio do global".
    """
    current: Node | None = node
    seen: set[str] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if key not in current.inherited:
            return current.properties.get(key)
        parent = store.get(current.parent_id)
        if parent is None:
            # Marcado como herdado mas sem pai: cai no valor local, se houver.
            return current.properties.get(key)
        current = parent
    return None


def resolve_source(node: Node, key: str, store: Store) -> Node | None:
    """De qual nó o valor efetivo veio (útil pro editor mostrar a origem)."""
    current: Node | None = node
    seen: set[str] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if key not in current.inherited:
            return current if key in current.properties else None
        parent = store.get(current.parent_id)
        if parent is None:
            return current if key in current.properties else None
        current = parent
    return None


def resolve_inherited(node: Node, key: str, store: Store) -> Any:
    """Valor que o pai ofereceria — o placeholder cinza do editor."""
    parent = store.get(node.parent_id)
    if parent is None:
        return None
    return resolve(parent, key, store)


def resolve_effective(node: Node, key: str, store: Store) -> Any:
    """O valor que o app realmente usa: árvore → preferências globais → fábrica."""
    valor = resolve(node, key, store)
    if valor is not None:
        return valor
    preferencias = getattr(store, "preferences", None)
    if preferencias is not None:
        global_ = preferencias.default_for(key)
        if global_ is not None:
            return global_
    return DEFAULTS.get(key)


def resolve_all(node: Node, store: Store, *, with_defaults: bool = False) -> dict[str, Any]:
    """Dict efetivo do nó: chaves de conexão com valor, mais chaves extras locais."""
    keys = list(CONNECTION_KEYS)
    for ancestor in store.path_to(node):
        for key in list(ancestor.properties) + list(ancestor.inherited):
            if key not in keys:
                keys.append(key)

    resolved: dict[str, Any] = {}
    for key in keys:
        value = resolve(node, key, store) if not with_defaults else resolve_effective(node, key, store)
        if value is not None:
            resolved[key] = value
    return resolved
