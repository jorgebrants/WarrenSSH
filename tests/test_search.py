# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da busca na árvore."""

from __future__ import annotations

import pytest

from warrenssh.models.node import new_connection, new_folder
from warrenssh.models.search import node_matches, normalize, row_matches
from warrenssh.models.store import Store


@pytest.fixture
def tree(tmp_path):
    store = Store(tmp_path / "tree.json")
    producao = store.add(new_folder("Producao"))
    web = store.add(
        new_connection("web-01", parent_id=producao.id, properties={"host": "192.0.2.11"})
    )
    banco = store.add(
        new_connection("banco-01", parent_id=producao.id, properties={"host": "192.0.2.12"})
    )
    solta = store.add(new_connection("avulsa", properties={"host": "198.51.100.1"}))
    return store, producao, web, banco, solta


def test_casa_por_nome(tree):
    _store, _producao, web, _banco, _solta = tree
    assert node_matches(web, "web")
    assert node_matches(web, "WEB-01".casefold())
    assert not node_matches(web, "banco")


def test_casa_por_host(tree):
    _store, _producao, web, _banco, _solta = tree
    assert node_matches(web, "192.0.2.11")
    assert not node_matches(web, "192.0.2.12")


def test_pasta_sem_host_nao_quebra(tree):
    _store, producao, *_ = tree
    assert not node_matches(producao, "192.0.2")


def test_texto_vazio_casa_tudo(tree):
    _store, producao, web, *_ = tree
    assert node_matches(producao, "")
    assert node_matches(web, "")


def test_pasta_fica_visivel_quando_um_filho_casa(tree):
    store, producao, web, banco, solta = tree
    assert row_matches(producao, store, "web")   # pasta dá contexto
    assert row_matches(web, store, "web")
    assert not row_matches(banco, store, "web")
    assert not row_matches(solta, store, "web")


def test_buscar_a_pasta_mostra_o_conteudo(tree):
    store, producao, web, banco, solta = tree
    assert row_matches(producao, store, "producao")
    assert row_matches(web, store, "producao")
    assert row_matches(banco, store, "producao")
    assert not row_matches(solta, store, "producao")


def test_busca_por_host_alcanca_a_pasta(tree):
    store, producao, _web, banco, _solta = tree
    assert row_matches(producao, store, "192.0.2.12")
    assert row_matches(banco, store, "192.0.2.12")


def test_sem_resultado(tree):
    store, producao, web, banco, solta = tree
    assert not any(row_matches(n, store, "zzz") for n in (producao, web, banco, solta))


def test_normalize():
    assert normalize("  Web-01  ") == "web-01"
    assert normalize("") == ""
