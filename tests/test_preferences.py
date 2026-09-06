# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes das preferências globais e do seu lugar na cascata."""

from __future__ import annotations

import json

import pytest

from warrenssh.models.node import new_connection, new_folder
from warrenssh.models.preferences import (
    APP_DEFAULTS,
    CORES_PADRAO,
    PALETA_PADRAO,
    PALETAS,
    Preferences,
    cor_padrao,
)
from warrenssh.models.resolver import resolve, resolve_all, resolve_effective
from warrenssh.models.store import Store


@pytest.fixture
def prefs(tmp_path):
    return Preferences(path=tmp_path / "preferences.json")


@pytest.fixture
def arvore(tmp_path, prefs):
    store = Store(tmp_path / "tree.json", preferences=prefs)
    pasta = store.add(new_folder("Pasta"))
    conn = store.add(new_connection("srv", parent_id=pasta.id, properties={"host": "h"}))
    return store, pasta, conn, prefs


# ------------------------------------------------------------------- cascata


def test_global_vale_quando_ninguem_definiu(arvore):
    store, _pasta, conn, prefs = arvore
    assert resolve_effective(conn, "user", store) is None
    prefs.set_default("user", "operador")
    assert resolve_effective(conn, "user", store) == "operador"


def test_arvore_vence_o_global(arvore):
    store, _pasta, conn, prefs = arvore
    prefs.set_default("user", "operador")
    conn.properties["user"] = "especifico"
    assert resolve_effective(conn, "user", store) == "especifico"


def test_pasta_vence_o_global(arvore):
    store, pasta, conn, prefs = arvore
    prefs.set_default("user", "global")
    pasta.properties["user"] = "da-pasta"
    conn.inherited.add("user")
    assert resolve_effective(conn, "user", store) == "da-pasta"


def test_fabrica_vale_quando_nem_global_existe(arvore):
    store, _pasta, conn, _prefs = arvore
    assert resolve_effective(conn, "port", store) == 22          # DEFAULTS
    assert resolve_effective(conn, "cursor_shape", store) == "block"


def test_global_sobrepoe_a_fabrica(arvore):
    store, _pasta, conn, prefs = arvore
    prefs.set_default("port", 2222)
    assert resolve_effective(conn, "port", store) == 2222


def test_resolve_puro_nao_enxerga_o_global(arvore):
    """O editor precisa distinguir 'herdado do pai' de 'veio do global'."""
    store, _pasta, conn, prefs = arvore
    prefs.set_default("user", "operador")
    assert resolve(conn, "user", store) is None
    assert resolve_effective(conn, "user", store) == "operador"


def test_resolve_all_com_defaults_usa_o_global(arvore):
    store, _pasta, conn, prefs = arvore
    prefs.set_default("font", "Fira Code 12")
    efetivo = resolve_all(conn, store, with_defaults=True)
    assert efetivo["font"] == "Fira Code 12"
    assert efetivo["port"] == 22


def test_store_sem_preferencias_explicitas_ainda_resolve(tmp_path):
    store = Store(tmp_path / "t.json")
    conn = store.add(new_connection("srv", properties={"host": "h"}))
    assert resolve_effective(conn, "port", store) == 22


# ---------------------------------------------------------------- comportamento


def test_app_cai_no_valor_de_fabrica(prefs):
    assert prefs.get_app("theme") == "system"
    assert prefs.get_app("confirm_close_tab") is True
    assert prefs.get_app("auto_reconnect") is False


def test_app_aceita_alteracao(prefs):
    prefs.set_app("theme", "dark")
    assert prefs.get_app("theme") == "dark"


def test_app_com_none_volta_ao_padrao(prefs):
    prefs.set_app("theme", "dark")
    prefs.set_app("theme", None)
    assert prefs.get_app("theme") == APP_DEFAULTS["theme"]


def test_chave_desconhecida_devolve_none(prefs):
    assert prefs.get_app("nao-existe") is None


# --------------------------------------------------------------------- paleta


def test_paleta_padrao(prefs):
    assert prefs.palette() == PALETAS[PALETA_PADRAO]
    assert len(prefs.palette()) == 16


def test_paleta_por_nome(prefs):
    prefs.set_default("palette_name", "Nord")
    assert prefs.palette() == PALETAS["Nord"]


def test_nome_invalido_cai_no_padrao(prefs):
    prefs.set_default("palette_name", "nao-existe")
    assert prefs.palette() == PALETAS[PALETA_PADRAO]


def test_paleta_propria_vence_o_nome(prefs):
    minha = tuple(f"#{i:02x}{i:02x}{i:02x}" for i in range(16))
    prefs.set_default("palette_name", "Nord")
    prefs.set_default("palette", list(minha))
    assert prefs.palette() == minha


def test_paleta_com_tamanho_errado_e_ignorada(prefs):
    prefs.set_default("palette", ["#000000", "#ffffff"])
    assert prefs.palette() == PALETAS[PALETA_PADRAO]


def test_todas_as_paletas_tem_16_cores_validas():
    import re

    for nome, cores in PALETAS.items():
        assert len(cores) == 16, nome
        assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in cores), nome


# --------------------------------------------------------------- persistência


def test_roundtrip(tmp_path):
    p = Preferences(path=tmp_path / "prefs.json")
    p.set_default("font", "Monospace 12")
    p.set_app("theme", "dark")
    p.save_json()

    lido = Preferences(path=tmp_path / "prefs.json")
    lido.load_json()
    assert lido.default_for("font") == "Monospace 12"
    assert lido.get_app("theme") == "dark"


def test_arquivo_ausente_da_valores_de_fabrica(tmp_path):
    p = Preferences(path=tmp_path / "nao-existe.json")
    p.load_json()
    assert p.defaults == {} and p.get_app("theme") == "system"


def test_arquivo_corrompido_nao_impede_o_app_de_abrir(tmp_path):
    alvo = tmp_path / "prefs.json"
    alvo.write_text("{isso não é json")
    p = Preferences(path=alvo)
    p.load_json()
    assert p.get_app("theme") == "system"


def test_save_cria_o_diretorio(tmp_path):
    p = Preferences(path=tmp_path / "a" / "b" / "prefs.json")
    p.set_app("theme", "light")
    p.save_json()
    assert json.loads(p.path.read_text())["app"]["theme"] == "light"


def test_set_default_com_none_remove(prefs):
    prefs.set_default("font", "X 10")
    prefs.set_default("font", None)
    assert prefs.default_for("font") is None


# ------------------------------------------------------- cores de fábrica


def test_cor_padrao_por_esquema():
    """Texto claro sobre fundo escuro, e o inverso — nunca preto no preto."""
    assert cor_padrao("foreground_color", escuro=True) == "#ffffff"
    assert cor_padrao("background_color", escuro=True) == "#1d1d1d"
    assert cor_padrao("foreground_color", escuro=False) == "#1d1d1d"
    assert cor_padrao("background_color", escuro=False) == "#fafafa"


@pytest.mark.parametrize("escuro", [True, False])
def test_texto_e_fundo_nunca_sao_iguais(escuro):
    """O bug que apareceu na UI: os dois campos vinham com a mesma cor."""
    assert cor_padrao("foreground_color", escuro) != cor_padrao("background_color", escuro)


def test_cor_padrao_de_chave_desconhecida():
    assert cor_padrao("nao-existe", escuro=True) == "#000000"


def test_cores_padrao_cobrem_os_dois_esquemas():
    import re

    for esquema, cores in CORES_PADRAO.items():
        assert set(cores) == {"foreground_color", "background_color"}, esquema
        assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in cores.values()), esquema
