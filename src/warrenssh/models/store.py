# SPDX-License-Identifier: GPL-3.0-or-later
"""Armazenamento da árvore de nós: índice em memória + persistência JSON."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from warrenssh.models.node import Node
from warrenssh.models.preferences import Preferences

SCHEMA_VERSION = 1

#: Quantas cópias antigas da árvore manter ao lado do arquivo.
BACKUPS_MANTIDOS = 3


class StoreError(RuntimeError):
    """Problema ao ler a árvore que o usuário precisa saber."""


def default_path() -> Path:
    """Caminho do tree.json, respeitando XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "warrenssh" / "tree.json"


class Store:
    """Mantém os nós indexados por id e cuida da ordem entre irmãos."""

    def __init__(self, path: Path | None = None, preferences: Preferences | None = None) -> None:
        self.path = path or default_path()
        self._nodes: dict[str, Node] = {}
        #: Topo da cascata: consultado quando ninguém na árvore definiu a chave.
        self.preferences = preferences if preferences is not None else Preferences()

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
        """Carrega do disco. Arquivo ausente = árvore vazia (primeira execução).

        Um arquivo ilegível não pode impedir o app de abrir — mas também não
        pode ser silenciosamente sobrescrito por uma árvore vazia. Então ele é
        posto de lado com um nome datado, tentamos o backup mais recente, e o
        problema sobe como `StoreError` para virar aviso na tela.
        """
        target = path or self.path
        try:
            raw = target.read_text(encoding="utf-8")
        except (FileNotFoundError, IsADirectoryError):
            self._nodes = {}
            return

        try:
            self.load_dict(json.loads(raw))
            return
        except (json.JSONDecodeError, TypeError, AttributeError, KeyError, ValueError) as exc:
            self._nodes = {}
            quarentena = self._por_em_quarentena(target)
            recuperado = self._tentar_backups(target)
            if recuperado is not None:
                raise StoreError(
                    f"O arquivo da árvore estava ilegível e foi guardado em "
                    f"{quarentena.name}. Recuperei a cópia de {recuperado.name}."
                ) from exc
            raise StoreError(
                f"O arquivo da árvore estava ilegível ({exc}). Ele foi guardado em "
                f"{quarentena.name} e comecei com uma árvore vazia."
            ) from exc

    def _por_em_quarentena(self, target: Path) -> Path:
        """Tira o arquivo ruim do caminho, sem apagá-lo."""
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        destino = target.with_name(f"{target.name}.ilegivel-{carimbo}")
        try:
            shutil.move(str(target), str(destino))
        except OSError:
            pass
        return destino

    def _tentar_backups(self, target: Path) -> Path | None:
        """Carrega o backup mais recente que ainda faça sentido."""
        for backup in self._backups(target):
            try:
                self.load_dict(json.loads(backup.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, TypeError, AttributeError, ValueError):
                continue
            return backup
        return None

    @staticmethod
    def _backups(target: Path) -> list[Path]:
        """Backups do mais novo para o mais antigo."""
        try:
            achados = sorted(
                target.parent.glob(f"{target.name}.bak*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []
        return achados

    def save_json(self, path: Path | None = None) -> None:
        """Grava de forma atômica (tmp + rename) para não perder a árvore num crash."""
        target = path or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        self._rotacionar_backups(target)
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

    def duplicate(self, node_id: str) -> Node | None:
        """Copia um nó (e a subárvore, se for pasta) ao lado do original."""
        original = self.get(node_id)
        if original is None:
            return None

        copia = self._copiar(original, original.parent_id, sufixo=" (cópia)")
        self.move(copia.id, copia.parent_id, position=original.position + 1)
        return copia

    def _copiar(self, node: Node, parent_id: str | None, sufixo: str = "") -> Node:
        import uuid

        novo = Node(
            id=str(uuid.uuid4()),
            parent_id=parent_id,
            kind=node.kind,
            name=node.name + sufixo,
            properties=dict(node.properties),
            inherited=set(node.inherited),
            position=node.position,
        )
        self._nodes[novo.id] = novo
        for filho in self.children(node.id):
            self._copiar(filho, novo.id)
        return novo

    # ------------------------------------------------------------ exportar

    def export_json(self, path: Path | str) -> None:
        """Grava a árvore num arquivo à escolha, para backup ou para levar embora.

        Só a estrutura: senhas ficam no chaveiro e não saem daqui.
        """
        destino = Path(path)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def import_json(self, path: Path | str, *, replace: bool = False) -> list[Node]:
        """Traz nós de um arquivo exportado. Devolve o que entrou.

        Sem `replace`, os nós chegam com ids novos e vão para o fim da árvore —
        assim importar duas vezes não sobrescreve nada nem colide com ids
        existentes.
        """
        origem = Path(path)
        try:
            dados = json.loads(origem.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Não deu para ler {origem.name}: {exc}") from exc

        brutos = dados.get("nodes") if isinstance(dados, dict) else None
        if not isinstance(brutos, list):
            raise StoreError(f"{origem.name} não parece uma árvore do WarrenSSH.")

        if replace:
            self.load_dict(dados)
            return list(self._nodes.values())

        return self._mesclar(brutos)

    def _mesclar(self, brutos: list[Any]) -> list[Node]:
        """Insere os nós com ids novos, preservando a hierarquia entre eles."""
        import uuid

        traducao: dict[str, str] = {}
        importados: list[Node] = []
        for bruto in brutos:
            try:
                node = Node.from_dict(bruto)
            except (KeyError, TypeError, ValueError):
                continue  # linha estragada não invalida o arquivo inteiro
            antigo, node.id = node.id, str(uuid.uuid4())
            traducao[antigo] = node.id
            importados.append(node)

        for node in importados:
            # pai fora do lote importado vira raiz, para nada ficar órfão
            node.parent_id = traducao.get(node.parent_id or "", None)
            self._nodes[node.id] = node

        for parent_id in {n.parent_id for n in importados}:
            self._reindex(parent_id)
        return importados

    def _rotacionar_backups(self, target: Path) -> None:
        """Guarda a versão atual antes de sobrescrever, mantendo as N últimas."""
        if not target.exists():
            return
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            shutil.copy2(target, target.with_name(f"{target.name}.bak-{carimbo}"))
        except OSError:
            return  # não poder fazer backup não pode impedir de salvar
        for antigo in self._backups(target)[BACKUPS_MANTIDOS:]:
            antigo.unlink(missing_ok=True)
