# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da lógica do editor: herança liga/desliga e conversão de tipos."""

from __future__ import annotations

import pytest

from warrenssh.models.editing import (
    EditingError,
    apply_edits,
    can_inherit,
    effective_placeholder,
    fields_for,
    format_value,
    new_child_defaults,
    parse_value,
    set_inherited,
    set_value,
)
from warrenssh.models.node import new_connection, new_folder
from warrenssh.models.resolver import resolve
from warrenssh.models.store import Store


@pytest.fixture
def tree(tmp_path):
    store = Store(tmp_path / "tree.json")
    pasta = store.add(
        new_folder("Producao", properties={"user": "operador", "proxy_jump": "bastion", "port": 22})
    )
    conn = store.add(
        new_connection(
            "srv1",
            parent_id=pasta.id,
            properties={"host": "192.0.2.1"},
            inherited={"user", "port", "proxy_jump"},
        )
    )
    return store, pasta, conn


# ------------------------------------------------------------------ herança


def test_desligar_heranca_usa_o_valor_local(tree):
    store, _pasta, conn = tree
    set_inherited(conn, "user", False, store)
    set_value(conn, "user", "deploy")
    assert "user" not in conn.inherited
    assert resolve(conn, "user", store) == "deploy"


def test_religar_heranca_volta_ao_valor_do_pai(tree):
    store, _pasta, conn = tree
    set_inherited(conn, "user", False, store)
    set_value(conn, "user", "deploy")
    set_inherited(conn, "user", True, store)
    assert resolve(conn, "user", store) == "operador"
    # O rascunho local fica guardado para o caso de o usuário voltar atrás.
    assert conn.properties["user"] == "deploy"
    set_inherited(conn, "user", False, store)
    assert resolve(conn, "user", store) == "deploy"


def test_no_raiz_nao_pode_herdar(tree):
    store, pasta, _conn = tree
    assert can_inherit(pasta, "user", store) is False
    with pytest.raises(EditingError):
        set_inherited(pasta, "user", True, store)


def test_host_nunca_e_herdavel(tree):
    store, _pasta, conn = tree
    assert can_inherit(conn, "host", store) is False
    with pytest.raises(EditingError):
        set_inherited(conn, "host", True, store)


def test_placeholder_mostra_o_valor_do_pai(tree):
    store, _pasta, conn = tree
    assert effective_placeholder(conn, "user", store) == "operador"
    assert effective_placeholder(conn, "identity_file", store) == ""


def test_pasta_nao_tem_campo_host():
    assert "host" not in fields_for("folder")
    assert "host" in fields_for("connection")


def test_filho_novo_herda_tudo_que_pode(tree):
    store, pasta, _conn = tree
    padrao = new_child_defaults(pasta, "connection")
    assert "user" in padrao and "port" in padrao
    assert "host" not in padrao  # host é sempre local
    assert new_child_defaults(None, "folder") == set()  # raiz não tem de quem herdar


# ------------------------------------------------------- conversão de tipos


@pytest.mark.parametrize(
    "key,texto,esperado",
    [
        ("port", "2222", 2222),
        ("port", " 22 ", 22),
        ("scrollback_lines", "5000", 5000),
        ("user", "  root  ", "root"),
        ("user", "", None),
        ("identity_file", "   ", None),
        ("color_scheme", "dark", "dark"),
        ("extra_ssh_args", "-o ConnectTimeout=5", ["-o", "ConnectTimeout=5"]),
        ("extra_ssh_args", "-o 'ServerAliveInterval 30'", ["-o", "ServerAliveInterval 30"]),
        ("extra_ssh_args", "", None),
        ("request_pty", True, True),
        ("request_pty", False, False),
    ],
)
def test_parse_value(key, texto, esperado):
    assert parse_value(key, texto) == esperado


@pytest.mark.parametrize(
    "key,texto",
    [
        ("port", "abc"),
        ("port", "0"),
        ("port", "70000"),
        ("scrollback_lines", "-1"),
        ("color_scheme", "roxo"),
        ("extra_ssh_args", "-o 'aspas nao fechadas"),
    ],
)
def test_parse_value_invalido(key, texto):
    with pytest.raises(EditingError):
        parse_value(key, texto)


@pytest.mark.parametrize(
    "key,valor,esperado",
    [
        ("port", 2222, "2222"),
        ("user", None, ""),
        ("extra_ssh_args", ["-o", "ServerAliveInterval 30"], "-o 'ServerAliveInterval 30'"),
        ("request_pty", True, "sim"),
        ("request_pty", False, "não"),
    ],
)
def test_format_value(key, valor, esperado):
    assert format_value(key, valor) == esperado


def test_format_e_parse_sao_ida_e_volta_para_lista():
    original = ["-o", "ProxyCommand=nc %h %p"]
    assert parse_value("extra_ssh_args", format_value("extra_ssh_args", original)) == original


def test_set_value_vazio_remove_a_chave(tree):
    _store, _pasta, conn = tree
    conn.properties["user"] = "x"
    set_value(conn, "user", "")
    assert "user" not in conn.properties


# --------------------------------------------------------------- apply_edits


def test_apply_edits_grava_nome_valores_e_heranca(tree):
    store, _pasta, conn = tree
    apply_edits(
        conn,
        {"host": "192.0.2.9", "port": "2222", "user": "deploy"},
        inherited={"proxy_jump"},
        store=store,
        name="  srv1-renomeado  ",
    )
    assert conn.name == "srv1-renomeado"
    assert conn.properties["port"] == 2222
    assert conn.inherited == {"proxy_jump"}
    assert resolve(conn, "user", store) == "deploy"
    assert resolve(conn, "proxy_jump", store) == "bastion"


def test_apply_edits_nao_grava_nada_se_algo_falhar(tree):
    store, _pasta, conn = tree
    antes_nome, antes_props = conn.name, dict(conn.properties)
    with pytest.raises(EditingError):
        apply_edits(
            conn,
            {"host": "192.0.2.9", "port": "porta-errada"},
            inherited=set(),
            store=store,
            name="novo",
        )
    assert conn.name == antes_nome
    assert conn.properties == antes_props


def test_apply_edits_recusa_nome_vazio(tree):
    store, _pasta, conn = tree
    with pytest.raises(EditingError):
        apply_edits(conn, {}, inherited=set(), store=store, name="   ")


def test_apply_edits_recusa_campo_invalido_para_pasta(tree):
    store, pasta, _conn = tree
    with pytest.raises(EditingError):
        apply_edits(pasta, {"host": "x"}, inherited=set(), store=store)


def test_apply_edits_recusa_heranca_impossivel(tree):
    store, pasta, _conn = tree
    with pytest.raises(EditingError):
        apply_edits(pasta, {}, inherited={"user"}, store=store)


def test_parse_value_bool_none_continua_none():
    """None significa 'sem valor local'; só um bool de verdade vira False."""
    assert parse_value("request_pty", None) is None
    assert parse_value("request_pty", False) is False
