# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do Store: ordem, movimentação, remoção e persistência JSON."""

from __future__ import annotations

import json

import pytest

from warrenssh.models.node import Node, new_connection, new_folder
from warrenssh.models.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "tree.json")


def test_add_atribui_positions_sequenciais(store):
    pasta = store.add(new_folder("Pasta"))
    a = store.add(new_connection("a", parent_id=pasta.id))
    b = store.add(new_connection("b", parent_id=pasta.id))
    c = store.add(new_connection("c", parent_id=pasta.id))
    assert [n.position for n in (a, b, c)] == [0, 1, 2]
    assert [n.name for n in store.children(pasta.id)] == ["a", "b", "c"]


def test_add_com_position_insere_no_meio(store):
    pasta = store.add(new_folder("Pasta"))
    store.add(new_connection("a", parent_id=pasta.id))
    store.add(new_connection("c", parent_id=pasta.id))
    store.add(new_connection("b", parent_id=pasta.id), position=1)
    assert [n.name for n in store.children(pasta.id)] == ["a", "b", "c"]


def test_add_recusa_id_duplicado_e_pai_inexistente(store):
    pasta = store.add(new_folder("Pasta"))
    with pytest.raises(ValueError):
        store.add(pasta)
    with pytest.raises(KeyError):
        store.add(new_connection("orfa", parent_id="nao-existe"))


def test_remove_leva_a_subarvore_junto(store):
    raiz = store.add(new_folder("raiz"))
    sub = store.add(new_folder("sub", parent_id=raiz.id))
    folha = store.add(new_connection("folha", parent_id=sub.id))
    outra = store.add(new_connection("outra", parent_id=raiz.id))

    removidos = store.remove(sub.id)
    assert {n.id for n in removidos} == {sub.id, folha.id}
    assert folha.id not in store
    assert outra.id in store
    assert store.children(raiz.id) == [outra]
    assert outra.position == 0  # posições reindexadas


def test_remove_de_id_inexistente_nao_quebra(store):
    assert store.remove("nada") == []


def test_move_reparenta_e_reordena(store):
    a = store.add(new_folder("A"))
    b = store.add(new_folder("B"))
    conn = store.add(new_connection("conn", parent_id=a.id))

    store.move(conn.id, b.id)
    assert conn.parent_id == b.id
    assert store.children(a.id) == []
    assert store.children(b.id) == [conn]


def test_move_recusa_ciclo(store):
    raiz = store.add(new_folder("raiz"))
    sub = store.add(new_folder("sub", parent_id=raiz.id))
    with pytest.raises(ValueError):
        store.move(raiz.id, sub.id)
    with pytest.raises(ValueError):
        store.move(raiz.id, raiz.id)


def test_move_recusa_pai_conexao(store):
    conn = store.add(new_connection("conn"))
    pasta = store.add(new_folder("pasta"))
    with pytest.raises(ValueError):
        store.move(pasta.id, conn.id)


def test_move_para_posicao_especifica(store):
    pasta = store.add(new_folder("Pasta"))
    a = store.add(new_connection("a", parent_id=pasta.id))
    b = store.add(new_connection("b", parent_id=pasta.id))
    c = store.add(new_connection("c", parent_id=pasta.id))

    store.move(c.id, pasta.id, position=0)
    assert [n.name for n in store.children(pasta.id)] == ["c", "a", "b"]
    assert [n.position for n in (c, a, b)] == [0, 1, 2]


def test_path_to_da_raiz_ate_o_no(store):
    raiz = store.add(new_folder("raiz"))
    sub = store.add(new_folder("sub", parent_id=raiz.id))
    folha = store.add(new_connection("folha", parent_id=sub.id))
    assert [n.name for n in store.path_to(folha)] == ["raiz", "sub", "folha"]


def test_roundtrip_json(store, tmp_path):
    raiz = store.add(new_folder("Producao", properties={"user": "operador"}))
    conn = store.add(
        new_connection(
            "srv1",
            parent_id=raiz.id,
            properties={"host": "192.0.2.1"},
            inherited={"user", "port"},
        )
    )
    store.save_json()

    recarregado = Store(tmp_path / "tree.json")
    recarregado.load_json()
    voltou = recarregado.get(conn.id)
    assert voltou is not None
    assert voltou.properties == {"host": "192.0.2.1"}
    assert voltou.inherited == {"user", "port"}  # lista no JSON, set na memória
    assert [n.name for n in recarregado.roots()] == ["Producao"]


def test_save_cria_diretorio_e_arquivo_legivel(tmp_path):
    store = Store(tmp_path / "fundo" / "do" / "poco" / "tree.json")
    store.add(new_folder("Pasta"))
    store.save_json()
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["nodes"][0]["name"] == "Pasta"


def test_load_de_arquivo_ausente_da_arvore_vazia(tmp_path):
    store = Store(tmp_path / "nao-existe.json")
    store.load_json()
    assert len(store) == 0


def test_load_promove_orfao_para_raiz(store):
    store.load_dict(
        {
            "version": 1,
            "nodes": [
                Node("x", "pai-sumiu", "connection", "orfa", {}, set(), 0).to_dict(),
            ],
        }
    )
    assert store.get("x").parent_id is None
    assert [n.name for n in store.roots()] == ["orfa"]
