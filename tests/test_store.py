# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do Store: ordem, movimentação, remoção e persistência JSON."""

from __future__ import annotations

import json

import pytest

from warrenssh.models.node import Node, new_connection, new_folder
from warrenssh.models.store import Store, StoreError


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


# ------------------------------------------------- robustez do arquivo


def test_arquivo_ilegivel_nao_impede_de_abrir(tmp_path):
    alvo = tmp_path / "tree.json"
    alvo.write_text("{isso não é json")
    store = Store(alvo)
    with pytest.raises(StoreError):
        store.load_json()
    assert len(store) == 0            # abriu, mesmo que vazio


def test_arquivo_ilegivel_vai_para_quarentena(tmp_path):
    """Nunca sobrescrever em silêncio: o arquivo ruim é preservado."""
    alvo = tmp_path / "tree.json"
    alvo.write_text("{corrompido")
    store = Store(alvo)
    with pytest.raises(StoreError):
        store.load_json()
    quarentena = list(tmp_path.glob("tree.json.ilegivel-*"))
    assert len(quarentena) == 1
    assert quarentena[0].read_text() == "{corrompido"


def test_recupera_do_backup_mais_recente(tmp_path):
    alvo = tmp_path / "tree.json"
    store = Store(alvo)
    store.add(new_folder("Original"))
    store.save_json()
    store.add(new_folder("Segunda"))
    store.save_json()                 # gera backup com a versão anterior

    alvo.write_text("{corrompido")
    recuperado = Store(alvo)
    with pytest.raises(StoreError, match="Recuperei"):
        recuperado.load_json()
    assert [n.name for n in recuperado.roots()]   # veio algo do backup


def test_backups_sao_rotacionados(tmp_path):
    import time

    alvo = tmp_path / "tree.json"
    for i in range(6):
        store = Store(alvo)
        if alvo.exists():
            try:
                store.load_json()
            except StoreError:
                pass
        store.add(new_folder(f"P{i}"))
        store.save_json()
        time.sleep(1.01)              # o carimbo tem resolução de segundo
    assert len(list(tmp_path.glob("tree.json.bak-*"))) <= 3


def test_salvar_sem_arquivo_anterior_nao_cria_backup(tmp_path):
    store = Store(tmp_path / "tree.json")
    store.add(new_folder("Nova"))
    store.save_json()
    assert list(tmp_path.glob("tree.json.bak-*")) == []


# ------------------------------------------------------ exportar/importar


def test_export_e_import(tmp_path):
    origem = Store(tmp_path / "a.json")
    pasta = origem.add(new_folder("Servidores", properties={"user": "op"}))
    origem.add(new_connection("web", parent_id=pasta.id, properties={"host": "192.0.2.1"}))
    origem.export_json(tmp_path / "saida.json")

    destino = Store(tmp_path / "b.json")
    importados = destino.import_json(tmp_path / "saida.json")
    assert {n.name for n in importados} == {"Servidores", "web"}
    raiz = next(n for n in destino.roots() if n.name == "Servidores")
    assert [n.name for n in destino.children(raiz.id)] == ["web"]


def test_import_preserva_o_que_ja_existia(tmp_path):
    origem = Store(tmp_path / "a.json")
    origem.add(new_folder("Nova"))
    origem.export_json(tmp_path / "saida.json")

    destino = Store(tmp_path / "b.json")
    destino.add(new_folder("Antiga"))
    destino.import_json(tmp_path / "saida.json")
    assert {n.name for n in destino.roots()} == {"Antiga", "Nova"}


def test_import_duas_vezes_nao_colide(tmp_path):
    origem = Store(tmp_path / "a.json")
    origem.add(new_folder("Pasta"))
    origem.export_json(tmp_path / "saida.json")

    destino = Store(tmp_path / "b.json")
    destino.import_json(tmp_path / "saida.json")
    destino.import_json(tmp_path / "saida.json")
    ids = [n.id for n in destino]
    assert len(ids) == len(set(ids))          # ids novos, sem colisão
    assert len(destino.roots()) == 2


def test_import_com_replace_troca_a_arvore(tmp_path):
    origem = Store(tmp_path / "a.json")
    origem.add(new_folder("Importada"))
    origem.export_json(tmp_path / "saida.json")

    destino = Store(tmp_path / "b.json")
    destino.add(new_folder("Some"))
    destino.import_json(tmp_path / "saida.json", replace=True)
    assert [n.name for n in destino.roots()] == ["Importada"]


def test_import_de_arquivo_invalido(tmp_path):
    (tmp_path / "lixo.json").write_text('{"outra": "coisa"}')
    store = Store(tmp_path / "t.json")
    with pytest.raises(StoreError):
        store.import_json(tmp_path / "lixo.json")


def test_import_de_arquivo_ausente(tmp_path):
    store = Store(tmp_path / "t.json")
    with pytest.raises(StoreError):
        store.import_json(tmp_path / "nao-existe.json")


def test_import_pula_no_estragado_e_mantem_o_resto(tmp_path):
    import json

    bom = new_folder("Boa").to_dict()
    (tmp_path / "meio.json").write_text(json.dumps({"nodes": [bom, "não é um nó", 42]}))
    store = Store(tmp_path / "t.json")
    importados = store.import_json(tmp_path / "meio.json")
    assert [n.name for n in importados] == ["Boa"]


# ------------------------------------------------------------- duplicar


def test_duplicar_conexao(store):
    pasta = store.add(new_folder("Pasta"))
    conn = store.add(
        new_connection("srv", parent_id=pasta.id, properties={"host": "h"}, inherited={"user"})
    )
    copia = store.duplicate(conn.id)
    assert copia is not None
    assert copia.name == "srv (cópia)"
    assert copia.id != conn.id
    assert copia.properties == conn.properties and copia.inherited == conn.inherited
    assert copia.parent_id == conn.parent_id


def test_copia_fica_logo_abaixo_do_original(store):
    pasta = store.add(new_folder("Pasta"))
    a = store.add(new_connection("a", parent_id=pasta.id))
    store.add(new_connection("b", parent_id=pasta.id))
    store.duplicate(a.id)
    assert [n.name for n in store.children(pasta.id)] == ["a", "a (cópia)", "b"]


def test_duplicar_pasta_leva_a_subarvore(store):
    pasta = store.add(new_folder("Grupo"))
    store.add(new_connection("um", parent_id=pasta.id))
    sub = store.add(new_folder("Sub", parent_id=pasta.id))
    store.add(new_connection("dois", parent_id=sub.id))

    copia = store.duplicate(pasta.id)
    filhos = store.children(copia.id)
    assert sorted(n.name for n in filhos) == ["Sub", "um"]
    subcopia = next(n for n in filhos if n.name == "Sub")
    assert [n.name for n in store.children(subcopia.id)] == ["dois"]


def test_copia_e_independente_do_original(store):
    conn = store.add(new_connection("srv", properties={"host": "original"}))
    copia = store.duplicate(conn.id)
    copia.properties["host"] = "mudado"
    assert conn.properties["host"] == "original"


def test_duplicar_id_inexistente(store):
    assert store.duplicate("nao-existe") is None
