# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes dos túneis de porta."""

from __future__ import annotations

import pytest

from warrenssh.ssh.tunnels import (
    DYNAMIC,
    LOCAL,
    REMOTE,
    TunnelError,
    describe,
    normalize,
    parse_spec,
    to_args,
    to_spec,
)

LOCAL_OK = {"type": LOCAL, "listen_port": 5432, "host": "localhost", "host_port": 5432}


# ---------------------------------------------------------------- validação


def test_local_completo():
    assert normalize(LOCAL_OK) == LOCAL_OK


def test_portas_como_texto_viram_numero():
    t = normalize({"type": LOCAL, "listen_port": "8080", "host": "w", "host_port": "80"})
    assert t["listen_port"] == 8080 and t["host_port"] == 80


def test_dinamico_dispensa_destino():
    assert normalize({"type": DYNAMIC, "listen_port": 1080}) == {
        "type": DYNAMIC, "listen_port": 1080
    }


def test_tipo_padrao_e_local():
    assert normalize({"listen_port": 1, "host": "h", "host_port": 2})["type"] == LOCAL


def test_bind_opcional():
    t = normalize({**LOCAL_OK, "bind": "0.0.0.0"})
    assert t["bind"] == "0.0.0.0"


@pytest.mark.parametrize("porta", [0, 65536, -1, "abc", None, ""])
def test_porta_invalida(porta):
    with pytest.raises(TunnelError):
        normalize({**LOCAL_OK, "listen_port": porta})


def test_tipo_desconhecido():
    with pytest.raises(TunnelError):
        normalize({**LOCAL_OK, "type": "mágico"})


def test_sem_destino_no_local():
    with pytest.raises(TunnelError):
        normalize({"type": LOCAL, "listen_port": 8080})


def test_dois_pontos_no_host_e_recusado():
    """`:` separa campos na sintaxe do ssh: deixar passar quebraria o comando."""
    with pytest.raises(TunnelError):
        normalize({**LOCAL_OK, "host": "servidor:80"})
    with pytest.raises(TunnelError):
        normalize({**LOCAL_OK, "bind": "a:b"})


def test_nao_dicionario():
    with pytest.raises(TunnelError):
        normalize("8080:localhost:80")


# ------------------------------------------------------------------- argv


def test_to_args_dos_tres_tipos():
    assert to_args(
        [
            LOCAL_OK,
            {"type": REMOTE, "listen_port": 9000, "host": "localhost", "host_port": 3000},
            {"type": DYNAMIC, "listen_port": 1080},
        ]
    ) == ["-L", "5432:localhost:5432", "-R", "9000:localhost:3000", "-D", "1080"]


def test_to_args_vazio():
    assert to_args([]) == [] and to_args(None) == []


def test_to_spec_com_bind():
    assert to_spec(normalize({**LOCAL_OK, "bind": "0.0.0.0"})) == "0.0.0.0:5432:localhost:5432"
    assert to_spec(normalize({"type": DYNAMIC, "listen_port": 1080, "bind": "0.0.0.0"})) == (
        "0.0.0.0:1080"
    )


def test_um_tunel_ruim_derruba_a_lista():
    with pytest.raises(TunnelError):
        to_args([LOCAL_OK, {"type": LOCAL, "listen_port": 0}])


# ------------------------------------------------------------------ texto


def test_parse_spec_local():
    assert parse_spec("8080:intranet:80") == {
        "type": LOCAL, "listen_port": 8080, "host": "intranet", "host_port": 80
    }


def test_parse_spec_com_bind():
    t = parse_spec("0.0.0.0:8080:intranet:80")
    assert t["bind"] == "0.0.0.0" and t["listen_port"] == 8080


def test_parse_spec_dinamico():
    assert parse_spec("1080", DYNAMIC) == {"type": DYNAMIC, "listen_port": 1080}
    assert parse_spec("0.0.0.0:1080", DYNAMIC)["bind"] == "0.0.0.0"


@pytest.mark.parametrize("texto", ["8080", "8080:host", "a:b:c:d:e", ""])
def test_parse_spec_invalido(texto):
    with pytest.raises(TunnelError):
        parse_spec(texto)


def test_ida_e_volta_texto():
    for spec in ("5432:localhost:5432", "0.0.0.0:8080:web:80"):
        assert to_spec(parse_spec(spec)) == spec


# --------------------------------------------------------------- descrição


def test_describe_explica_o_sentido():
    assert "aqui →" in describe(LOCAL_OK)
    assert "no servidor →" in describe(
        {"type": REMOTE, "listen_port": 9000, "host": "localhost", "host_port": 3000}
    )
    assert "SOCKS" in describe({"type": DYNAMIC, "listen_port": 1080})
