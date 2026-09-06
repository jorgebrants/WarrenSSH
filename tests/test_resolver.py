# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da resolução em cascata (lógica pura, sem GTK)."""

from __future__ import annotations

import pytest

from warrenssh.models.node import new_connection, new_folder
from warrenssh.models.resolver import (
    resolve,
    resolve_all,
    resolve_inherited,
    resolve_source,
)
from warrenssh.models.store import Store


@pytest.fixture
def tree(tmp_path):
    """raiz "Infra" > "Producao" > conexão "srv1"."""
    store = Store(tmp_path / "tree.json")
    raiz = store.add(new_folder("Infra", properties={"user": "root", "port": 22}))
    producao = store.add(
        new_folder(
            "Producao",
            parent_id=raiz.id,
            properties={"user": "operador", "proxy_jump": "bastion.example.com"},
            inherited={"port"},
        )
    )
    srv1 = store.add(
        new_connection(
            "srv1",
            parent_id=producao.id,
            properties={"host": "192.0.2.1"},
            inherited={"user", "port", "proxy_jump"},
        )
    )
    return store, raiz, producao, srv1


def test_valor_local(tree):
    store, _raiz, _hosp, srv1 = tree
    assert resolve(srv1, "host", store) == "192.0.2.1"


def test_heranca_um_nivel(tree):
    store, _raiz, _hosp, srv1 = tree
    assert resolve(srv1, "user", store) == "operador"
    assert resolve(srv1, "proxy_jump", store) == "bastion.example.com"


def test_heranca_dois_niveis(tree):
    store, _raiz, _hosp, srv1 = tree
    # srv1 herda port -> Producao herda port -> Infra define 22.
    assert resolve(srv1, "port", store) == 22


def test_override_no_meio_da_cadeia(tree):
    store, raiz, producao, srv1 = tree
    # Infra diz "root", mas Producao sobrescreve com valor local.
    assert resolve(raiz, "user", store) == "root"
    assert resolve(producao, "user", store) == "operador"
    assert resolve(srv1, "user", store) == "operador"

    # Desligar a herança no filho faz o valor local dele vencer.
    srv1.inherited.discard("user")
    srv1.properties["user"] = "deploy"
    assert resolve(srv1, "user", store) == "deploy"


def test_chave_ausente(tree):
    store, _raiz, _hosp, srv1 = tree
    assert resolve(srv1, "identity_file", store) is None
    assert resolve(srv1, "chave_que_nao_existe", store) is None


def test_herdado_sem_pai_cai_no_valor_local(tree):
    store, raiz, _hosp, _srv1 = tree
    raiz.inherited.add("user")
    assert resolve(raiz, "user", store) == "root"


def test_marcado_herdado_ignora_valor_local_obsoleto(tree):
    store, _raiz, _hosp, srv1 = tree
    srv1.properties["user"] = "resto-antigo"  # ainda em `inherited`
    assert resolve(srv1, "user", store) == "operador"


def test_resolve_source_aponta_a_origem(tree):
    store, raiz, producao, srv1 = tree
    assert resolve_source(srv1, "host", store) is srv1
    assert resolve_source(srv1, "user", store) is producao
    assert resolve_source(srv1, "port", store) is raiz
    assert resolve_source(srv1, "identity_file", store) is None


def test_resolve_inherited_e_o_placeholder_do_editor(tree):
    store, _raiz, _hosp, srv1 = tree
    # Mesmo com valor local, o editor mostra o que o pai ofereceria.
    srv1.inherited.discard("user")
    srv1.properties["user"] = "deploy"
    assert resolve(srv1, "user", store) == "deploy"
    assert resolve_inherited(srv1, "user", store) == "operador"


def test_resolve_all_monta_o_dict_efetivo(tree):
    store, _raiz, _hosp, srv1 = tree
    efetivo = resolve_all(srv1, store)
    assert efetivo == {
        "host": "192.0.2.1",
        "port": 22,
        "user": "operador",
        "proxy_jump": "bastion.example.com",
    }


def test_resolve_all_com_defaults(tree):
    store, _raiz, _hosp, srv1 = tree
    efetivo = resolve_all(srv1, store, with_defaults=True)
    assert efetivo["port"] == 22
    assert efetivo["charset"] == "UTF-8"
    assert efetivo["scrollback_lines"] == 10000
    assert efetivo["extra_ssh_args"] == []
    assert "identity_file" not in efetivo


def test_resolve_all_inclui_chave_fora_do_conjunto_padrao(tree):
    store, _raiz, producao, srv1 = tree
    producao.properties["banner_check"] = "off"
    srv1.inherited.add("banner_check")
    assert resolve_all(srv1, store)["banner_check"] == "off"


def test_cadeia_quebra_se_o_intermediario_nao_herda(tree):
    """Regra do modelo: cada nó decide. Um intermediário que não marca a chave
    como herdada encerra a subida com o próprio valor local (aqui, ausente)."""
    store, raiz, producao, srv1 = tree
    raiz.properties["startup_command"] = "tmux a"
    srv1.inherited.add("startup_command")
    assert "startup_command" not in producao.inherited
    assert resolve(srv1, "startup_command", store) is None

    producao.inherited.add("startup_command")  # religa o elo do meio
    assert resolve(srv1, "startup_command", store) == "tmux a"


def test_cadeia_longa(tree):
    store, _raiz, _hosp, srv1 = tree
    # Empilha 5 pastas herdando tudo entre Producao e uma nova conexão.
    parent = srv1.parent_id
    for i in range(5):
        pasta = store.add(new_folder(f"nivel{i}", parent_id=parent, inherited={"user", "port"}))
        parent = pasta.id
    folha = store.add(
        new_connection("folha", parent_id=parent, properties={"host": "h"}, inherited={"user"})
    )
    assert resolve(folha, "user", store) == "operador"
