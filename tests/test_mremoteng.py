# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do import do mRemoteNG (XML sintético, nunca um export real)."""

from __future__ import annotations

import pytest

from warrenssh.models.resolver import resolve
from warrenssh.models.store import Store
from warrenssh.ssh.mremoteng import (
    MRemoteNGError,
    apply_inheritance,
    import_into,
    parse_file,
)

XML = """<?xml version="1.0" encoding="utf-8"?>
<Connections xmlns="http://mremoteng.org" Name="Conexões" ConfVersion="2.6">
  <Node Name="Producao" Type="Container" Protocol="RDP" Port="3389">
    <Node Name="web-01" Type="Connection" Protocol="SSH2"
          Hostname="192.0.2.11" Username="operador" Port="22" />
    <Node Name="web-02" Type="Connection" Protocol="SSH2"
          Hostname="192.0.2.12" Username="operador" Port="22" />
    <Node Name="web-03" Type="Connection" Protocol="SSH2"
          Hostname="192.0.2.13" Username="operador" Port="2222" />
    <Node Name="banco" Type="Connection" Protocol="SSH2"
          Hostname="192.0.2.20" Username="dba" Port="22" Password="Aq3f/cifrada==" />
  </Node>
  <Node Name="Windows" Type="Connection" Protocol="RDP" Hostname="192.0.2.99" />
  <Node Name="Antigo" Type="Connection" Protocol="VNC" Hostname="192.0.2.98" />
</Connections>
"""


@pytest.fixture
def arquivo(tmp_path):
    alvo = tmp_path / "confCons.xml"
    alvo.write_text(XML, encoding="utf-8")
    return alvo


# ------------------------------------------------------------------ leitura


def test_le_a_estrutura(arquivo):
    r = parse_file(arquivo)
    assert r.conexoes == 4
    assert r.pastas == 1
    assert [n.name for n in r.roots] == ["Producao"]
    assert [f.name for f in r.roots[0].children] == ["web-01", "web-02", "web-03", "banco"]


def test_mapeia_os_campos(arquivo):
    web = parse_file(arquivo).roots[0].children[0]
    assert web.properties["host"] == "192.0.2.11"
    assert web.properties["user"] == "operador"


def test_porta_padrao_nao_e_gravada(arquivo):
    filhos = parse_file(arquivo).roots[0].children
    assert "port" not in filhos[0].properties      # era 22
    assert filhos[2].properties["port"] == 2222


def test_protocolos_nao_ssh_ficam_de_fora(arquivo):
    r = parse_file(arquivo)
    assert r.ignorados == {"RDP": 1, "VNC": 1}
    assert all(n.name not in ("Windows", "Antigo") for n in r.roots)


def test_container_com_protocolo_rdp_ainda_vira_pasta(arquivo):
    """O mRemoteNG põe Protocol nas pastas; isso não as descarta."""
    assert parse_file(arquivo).roots[0].kind == "folder"


def test_conta_senhas_que_ficaram_para_tras(arquivo):
    """Não descriptografamos: o usuário precisa saber quantas recadastrar."""
    assert parse_file(arquivo).com_senha == 1


def test_resumo_legivel(arquivo):
    resumo = parse_file(arquivo).resumo()
    assert "4 conexão(ões)" in resumo and "RDP" in resumo and "senha" in resumo


def test_arquivo_que_nao_e_mremoteng(tmp_path):
    alvo = tmp_path / "outro.xml"
    alvo.write_text("<?xml version='1.0'?><Outra/>")
    with pytest.raises(MRemoteNGError):
        parse_file(alvo)


def test_xml_quebrado(tmp_path):
    alvo = tmp_path / "ruim.xml"
    alvo.write_text("<Connections><Node")
    with pytest.raises(MRemoteNGError):
        parse_file(alvo)


def test_arquivo_ausente(tmp_path):
    with pytest.raises(MRemoteNGError):
        parse_file(tmp_path / "nao-existe.xml")


def test_respeita_heranca_ja_marcada(tmp_path):
    alvo = tmp_path / "c.xml"
    alvo.write_text(
        '<Connections xmlns="http://mremoteng.org">'
        '<Node Name="P" Type="Container" Username="chefe">'
        '<Node Name="c" Type="Connection" Protocol="SSH2" Hostname="h" InheritUsername="True"/>'
        "</Node></Connections>"
    )
    filho = parse_file(alvo).roots[0].children[0]
    assert "user" in filho.inherited


# ----------------------------------------------------------------- herança


def test_valor_repetido_sobe_para_a_pasta(arquivo):
    r = apply_inheritance(parse_file(arquivo))
    pasta = r.roots[0]
    assert pasta.properties["user"] == "operador"        # 3 de 4 conexões
    web = pasta.children[0]
    assert "user" not in web.properties and "user" in web.inherited


def test_quem_diverge_mantem_o_seu(arquivo):
    r = apply_inheritance(parse_file(arquivo))
    banco = next(c for c in r.roots[0].children if c.name == "banco")
    assert banco.properties["user"] == "dba"
    assert "user" not in banco.inherited


def test_valor_minoritario_nao_sobe(tmp_path):
    """Sem maioria clara, promover só embaralharia as coisas."""
    alvo = tmp_path / "c.xml"
    alvo.write_text(
        '<Connections xmlns="http://mremoteng.org"><Node Name="P" Type="Container">'
        + "".join(
            f'<Node Name="c{i}" Type="Connection" Protocol="SSH2" '
            f'Hostname="h{i}" Username="u{i}"/>'
            for i in range(4)
        )
        + "</Node></Connections>"
    )
    r = apply_inheritance(parse_file(alvo))
    assert "user" not in r.roots[0].properties


def test_pasta_com_uma_conexao_nao_promove(tmp_path):
    alvo = tmp_path / "c.xml"
    alvo.write_text(
        '<Connections xmlns="http://mremoteng.org"><Node Name="P" Type="Container">'
        '<Node Name="c" Type="Connection" Protocol="SSH2" Hostname="h" Username="u"/>'
        "</Node></Connections>"
    )
    r = apply_inheritance(parse_file(alvo))
    assert "user" not in r.roots[0].properties


def test_conta_quantos_foram_promovidos(arquivo):
    r = apply_inheritance(parse_file(arquivo))
    assert r.promovidos["user"] == 3


# ------------------------------------------------------------------- store


def test_import_into_cria_a_arvore(arquivo, tmp_path):
    store = Store(tmp_path / "tree.json")
    criados = import_into(store, parse_file(arquivo))
    assert len(criados) == 6                      # pasta raiz + Producao + 4 conexões
    raiz = next(n for n in store.roots() if n.name == "Importado do mRemoteNG")
    producao = store.children(raiz.id)[0]
    assert [n.name for n in store.children(producao.id)] == [
        "web-01", "web-02", "web-03", "banco"
    ]


def test_heranca_funciona_de_verdade_apos_importar(arquivo, tmp_path):
    """O teste que importa: a conexão resolve o usuário subindo até a pasta."""
    store = Store(tmp_path / "tree.json")
    import_into(store, apply_inheritance(parse_file(arquivo)))
    raiz = next(n for n in store.roots() if n.name.startswith("Importado"))
    producao = store.children(raiz.id)[0]
    web = next(n for n in store.children(producao.id) if n.name == "web-01")
    assert resolve(web, "user", store) == "operador"
    assert web.properties.get("user") is None      # veio da pasta, não é local


def test_pasta_nao_herda_os_padroes_de_rdp(arquivo):
    """Container do mRemoteNG traz Port=3389 do RDP; importar isso quebraria
    todas as conexões SSH que herdassem a porta."""
    r = parse_file(arquivo)
    assert r.roots[0].properties == {}


def test_promocao_sobrescreve_valor_da_pasta(tmp_path):
    """O valor dominante entre as conexões vale mais que o padrão do container."""
    alvo = tmp_path / "c.xml"
    alvo.write_text(
        '<Connections xmlns="http://mremoteng.org">'
        '<Node Name="P" Type="Container" Protocol="RDP" Port="3389" Username="administrator">'
        '<Node Name="a" Type="Connection" Protocol="SSH2" Hostname="h1" Username="op" Port="2222"/>'
        '<Node Name="b" Type="Connection" Protocol="SSH2" Hostname="h2" Username="op" Port="2222"/>'
        "</Node></Connections>"
    )
    r = apply_inheritance(parse_file(alvo))
    assert r.roots[0].properties["port"] == 2222        # não 3389
    assert r.roots[0].properties["user"] == "op"        # não administrator


def test_conexao_importada_resolve_a_porta_certa(tmp_path):
    alvo = tmp_path / "c.xml"
    alvo.write_text(
        '<Connections xmlns="http://mremoteng.org">'
        '<Node Name="P" Type="Container" Protocol="RDP" Port="3389">'
        '<Node Name="a" Type="Connection" Protocol="SSH2" Hostname="h1"/>'
        '<Node Name="b" Type="Connection" Protocol="SSH2" Hostname="h2"/>'
        "</Node></Connections>"
    )
    store = Store(tmp_path / "tree.json")
    import_into(store, apply_inheritance(parse_file(alvo)))
    raiz = next(n for n in store.roots() if n.name.startswith("Importado"))
    pasta = store.children(raiz.id)[0]
    conexao = store.children(pasta.id)[0]
    from warrenssh.models.resolver import resolve_effective

    assert resolve_effective(conexao, "port", store) == 22    # o padrão do SSH
