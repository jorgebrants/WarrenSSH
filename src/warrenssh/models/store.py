# SPDX-License-Identifier: GPL-3.0-or-later
"""Armazenamento da árvore de nós: índice em memória + persistência JSON."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

from warrenssh.models.node import Node

SCHEMA_VERSION = 1


def default_path() -> Path:
    """Caminho do tree.json, respeitando XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "warrenssh" / "tree.json"


class Store:
    """Mantém os nós indexados por id e cuida da ordem entre irmãos."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_path()
        self._nodes: dict[str, Node] = {}

    # ------------------------------------------------------------------ acesso

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    def __iter__(self) -> Iterator[Node]:
        return iter(self._nodes.values())

    def get(self, node_id: str | None) -> Node | None:
        """Devolve o nó ou None (aceita None para simplificar a subida na árvore)."""
        if node_id is None:
            return None
        return self._nodes.get(node_id)

    def parent_of(self, node: Node) -> Node | None:
        return self.get(node.parent_id)

    def children(self, parent_id: str | None) -> list[Node]:
        """Filhos diretos ordenados por position e, em empate, por nome."""
        kids = [n for n in self._nodes.values() if n.parent_id == parent_id]
        kids.sort(key=lambda n: (n.position, n.name.casefold()))
        return kids

    def roots(self) -> list[Node]:
        return self.children(None)

    def descendants(self, node_id: str) -> list[Node]:
        """Todos os descendentes, em pré-ordem."""
        out: list[Node] = []
        for child in self.children(node_id):
            out.append(child)
            out.extend(self.descendants(child.id))
        return out

    def path_to(self, node: Node) -> list[Node]:
        """Cadeia da raiz até o nó (inclusive)."""
        chain = [node]
        seen = {node.id}
        parent = self.parent_of(node)
        while parent is not None and parent.id not in seen:
            chain.append(parent)
            seen.add(parent.id)
            parent = self.parent_of(parent)
        chain.reverse()
        return chain

    # ------------------------------------------------------------------ escrita

    def add(self, node: Node, *, position: int | None = None) -> Node:
        """Insere um nó. Sem position explícita, vai para o fim dos irmãos."""
        if node.id in self._nodes:
            raise ValueError(f"nó já existe: {node.id}")
        if node.parent_id is not None and node.parent_id not in self._nodes:
            raise KeyError(f"pai inexistente: {node.parent_id}")
        siblings = self.children(node.parent_id)
        node.position = len(siblings) if position is None else position
        self._nodes[node.id] = node
        if position is not None:
            self._reindex(node.parent_id, moved=node)
        return node

    def remove(self, node_id: str) -> list[Node]:
        """Remove o nó e toda a sua subárvore. Devolve o que saiu."""
        node = self._nodes.get(node_id)
        if node is None:
            return []
        removed = [node, *self.descendants(node_id)]
        for n in removed:
            self._nodes.pop(n.id, None)
        self._reindex(node.parent_id)
        return removed

    def move(self, node_id: str, new_parent_id: str | None, position: int | None = None) -> None:
        """Reparenta/reordena um nó, recusando mover para dentro da própria subárvore."""
        node = self._nodes[node_id]
        if new_parent_id is not None:
            parent = self._nodes.get(new_parent_id)
            if parent is None:
                raise KeyError(f"pai inexistente: {new_parent_id}")
            if parent.is_connection:
                raise ValueError("conexões não podem ter filhos")
            if new_parent_id == node_id or any(
                d.id == new_parent_id for d in self.descendants(node_id)
            ):
                raise ValueError("não é possível mover um nó para dentro dele mesmo")

        old_parent_id = node.parent_id
        node.parent_id = new_parent_id
        siblings = [n for n in self.children(new_parent_id) if n.id != node_id]
        node.position = len(siblings) if position is None else position
        self._reindex(new_parent_id, moved=node)
        if old_parent_id != new_parent_id:
            self._reindex(old_parent_id)

    def _reindex(self, parent_id: str | None, moved: Node | None = None) -> None:
        """Normaliza as positions dos irmãos para 0..n-1 sem buracos."""
        siblings = [n for n in self._nodes.values() if n.parent_id == parent_id]
        # `moved` entra à frente de quem tem a mesma position, para o insert valer.
        siblings.sort(key=lambda n: (n.position, n is not moved, n.name.casefold()))
        for index, sibling in enumerate(siblings):
            sibling.position = index

    # -------------------------------------------------------------- persistência

    def to_dict(self) -> dict[str, Any]:
        ordered = self.roots() + [d for r in self.roots() for d in self.descendants(r.id)]
        return {"version": SCHEMA_VERSION, "nodes": [n.to_dict() for n in ordered]}

    def load_dict(self, data: dict[str, Any]) -> None:
        self._nodes = {}
        for raw in data.get("nodes") or []:
            node = Node.from_dict(raw)
            self._nodes[node.id] = node
        # Um parent_id órfão viraria um nó invisível: promove para raiz.
        for node in self._nodes.values():
            if node.parent_id is not None and node.parent_id not in self._nodes:
                node.parent_id = None

    def load_json(self, path: Path | None = None) -> None:
        """Carrega do disco. Arquivo ausente = árvore vazia (primeira execução)."""
        target = path or self.path
        try:
            raw = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._nodes = {}
            return
        self.load_dict(json.loads(raw))

    def save_json(self, path: Path | None = None) -> None:
        """Grava de forma atômica (tmp + rename) para não perder a árvore num crash."""
        target = path or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tree-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
