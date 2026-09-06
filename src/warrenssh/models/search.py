# SPDX-License-Identifier: GPL-3.0-or-later
"""Regra de busca na árvore. Sem GTK — a sidebar só a consome."""

from __future__ import annotations

from warrenssh.models.node import Node
from warrenssh.models.store import Store


def node_matches(node: Node, text: str) -> bool:
    """Casa por nome ou host — os dois jeitos de procurar uma máquina."""
    if not text:
        return True
    if text in node.name.casefold():
        return True
    host = node.properties.get("host")
    return bool(host) and text in str(host).casefold()


def row_matches(node: Node, store: Store, text: str) -> bool:
    """Decide se um nó continua visível durante a busca.

    Além do próprio nó, aceita quem tem um descendente que casa (a pasta fica
    para dar contexto) e quem está sob um ancestral que casa (buscar a pasta
    mostra o conteúdo dela).
    """
    if not text:
        return True
    if node_matches(node, text):
        return True
    if any(node_matches(a, text) for a in store.path_to(node)[:-1]):
        return True
    return any(node_matches(child, text) for child in store.descendants(node.id))


def normalize(text: str) -> str:
    return text.strip().casefold()
