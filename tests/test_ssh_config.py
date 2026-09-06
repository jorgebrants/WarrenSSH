# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do parser de ssh_config (o que substituiu o paramiko)."""

from __future__ import annotations

import pytest

from warrenssh.ssh.ssh_config import SSHConfig, tem_curinga


def parse(texto: str) -> SSHConfig:
    return SSHConfig.from_text(texto)


# ------------------------------------------------------------------- sintaxe


def test_chave_valor_com_espaco():
    c = parse("Host srv\n    HostName 1.2.3.4\n")
    assert c.lookup("srv")["hostname"] == "1.2.3.4"


def test_chave_valor_com_igual():
    c = parse("Host=srv\nHostName=1.2.3.4\n")
    assert c.lookup("srv")["hostname"] == "1.2.3.4"


def test_igual_com_espacos_ao_redor():
    c = parse("Host srv\n  HostName = 1.2.3.4\n")
    assert c.lookup("srv")["hostname"] == "1.2.3.4"


def test_chave_sem_distincao_de_caixa():
    c = parse("HOST srv\n  hostname 1.2.3.4\n  UsEr root\n")
    assert c.lookup("srv") == {"hostname": "1.2.3.4", "user": "root"}


def test_comentarios_e_linhas_vazias():
    c = parse("# comentario\n\nHost srv\n\n  # outro\n  User root  # no fim da linha\n")
    assert c.lookup("srv")["user"] == "root"


def test_valor_entre_aspas():
    c = parse('Host srv\n  IdentityFile "/caminho com espaco/id"\n')
    assert c.lookup("srv")["identityfile"] == ["/caminho com espaco/id"]


def test_linha_sem_valor_e_ignorada():
    c = parse("Host srv\n  HostName\n  User root\n")
    resolvido = c.lookup("srv")
    assert "hostname" not in resolvido
    assert resolvido["user"] == "root"


def test_config_vazio():
    assert parse("").lookup("qualquer") == {}
    assert parse("# so comentario\n").host_names() == []


# ------------------------------------------------------------- precedência


def test_primeiro_valor_vence():
    """Regra central do OpenSSH: o primeiro valor obtido é o que vale."""
    c = parse("Host srv\n  User primeiro\n\nHost srv\n  User segundo\n")
    assert c.lookup("srv")["user"] == "primeiro"


def test_curinga_no_topo_sobrepoe_blocos_seguintes():
    c = parse("Host *\n  User padrao\n\nHost srv\n  User especifico\n")
    assert c.lookup("srv")["user"] == "padrao"


def test_curinga_no_fim_so_preenche_o_que_falta():
    c = parse("Host srv\n  User especifico\n\nHost *\n  User padrao\n  Port 2222\n")
    resolvido = c.lookup("srv")
    assert resolvido["user"] == "especifico"
    assert resolvido["port"] == "2222"


def test_diretivas_antes_do_primeiro_host_valem_para_todos():
    c = parse("Compression yes\n\nHost srv\n  User root\n")
    assert c.lookup("srv")["compression"] == "yes"
    assert c.lookup("outro")["compression"] == "yes"


# ---------------------------------------------------------------- curingas


@pytest.mark.parametrize(
    "padrao,host,casa",
    [
        ("*", "qualquer", True),
        ("web-*", "web-01", True),
        ("web-*", "banco-01", False),
        ("web-0?", "web-01", True),
        ("web-0?", "web-011", False),
        ("*.exemplo.com", "a.exemplo.com", True),
        ("*.exemplo.com", "exemplo.com", False),
    ],
)
def test_casamento_de_padroes(padrao, host, casa):
    c = parse(f"Host {padrao}\n  User marcado\n")
    assert ("user" in c.lookup(host)) is casa


def test_negacao_exclui_o_bloco():
    c = parse("Host * !web-01\n  User geral\n")
    assert c.lookup("banco-01")["user"] == "geral"
    assert "user" not in c.lookup("web-01")


def test_varios_padroes_na_mesma_linha():
    c = parse("Host web-01 web-02 banco-*\n  User comum\n")
    for host in ("web-01", "web-02", "banco-09"):
        assert c.lookup(host)["user"] == "comum"
    assert "user" not in c.lookup("outro")


def test_colchete_e_literal_nao_classe_de_caracteres():
    """O ssh_config não tem `[seq]`; o colchete é caractere comum."""
    c = parse("Host web-[01]\n  User marcado\n")
    assert c.lookup("web-[01]")["user"] == "marcado"
    assert "user" not in c.lookup("web-0")


# ------------------------------------------------------------ multivalorados


def test_identityfile_acumula_entre_blocos():
    c = parse(
        "Host srv\n  IdentityFile ~/.ssh/id_um\n\n"
        "Host *\n  IdentityFile ~/.ssh/id_dois\n"
    )
    assert c.lookup("srv")["identityfile"] == ["~/.ssh/id_um", "~/.ssh/id_dois"]


def test_identityfile_acumula_no_mesmo_bloco():
    c = parse("Host srv\n  IdentityFile ~/a\n  IdentityFile ~/b\n")
    assert c.lookup("srv")["identityfile"] == ["~/a", "~/b"]


def test_til_nao_e_expandido():
    """Guardamos a forma portátil; quem expande é o ssh, na hora de conectar."""
    c = parse("Host srv\n  IdentityFile ~/.ssh/id_ed25519\n")
    assert c.lookup("srv")["identityfile"] == ["~/.ssh/id_ed25519"]


# ------------------------------------------------------------------- blocos


def test_match_e_ignorado():
    """Match depende de contexto de execução que não temos ao importar."""
    c = parse("Match user root\n  Port 2222\n\nHost srv\n  User root\n")
    assert "port" not in c.lookup("srv")
    assert c.lookup("srv")["user"] == "root"


def test_bloco_encerra_no_proximo_host():
    c = parse("Host a\n  User ua\n\nHost b\n  User ub\n")
    assert c.lookup("a")["user"] == "ua"
    assert c.lookup("b")["user"] == "ub"


def test_host_names_ignora_curingas_e_repeticoes():
    c = parse("Host a\nHost *\nHost b a\nHost *.interno\nHost !negado\n")
    assert c.host_names() == ["a", "b"]


def test_tem_curinga():
    assert tem_curinga("*")
    assert tem_curinga("web-?")
    assert tem_curinga("!web")
    assert not tem_curinga("web-01")


# ------------------------------------------------------------------ arquivos


def test_from_file_ausente_nao_quebra(tmp_path):
    assert SSHConfig.from_file(tmp_path / "nao-existe").host_names() == []


def test_from_file_le_do_disco(tmp_path):
    (tmp_path / "config").write_text("Host srv\n  HostName 1.2.3.4\n")
    c = SSHConfig.from_file(tmp_path / "config")
    assert c.lookup("srv")["hostname"] == "1.2.3.4"


def test_include_relativo(tmp_path):
    (tmp_path / "config").write_text("Include extras\n\nHost local\n  User eu\n")
    (tmp_path / "extras").write_text("Host remoto\n  HostName 9.9.9.9\n")
    c = SSHConfig.from_file(tmp_path / "config")
    assert c.host_names() == ["remoto", "local"]
    assert c.lookup("remoto")["hostname"] == "9.9.9.9"


def test_include_com_curinga(tmp_path):
    (tmp_path / "config.d").mkdir()
    (tmp_path / "config").write_text("Include config.d/*.conf\n")
    (tmp_path / "config.d" / "a.conf").write_text("Host um\n  HostName 1.1.1.1\n")
    (tmp_path / "config.d" / "b.conf").write_text("Host dois\n  HostName 2.2.2.2\n")
    (tmp_path / "config.d" / "ignorar.txt").write_text("Host tres\n  HostName 3.3.3.3\n")
    c = SSHConfig.from_file(tmp_path / "config")
    assert c.host_names() == ["um", "dois"]


def test_include_ciclico_nao_trava(tmp_path):
    (tmp_path / "a").write_text("Include b\nHost ha\n  User x\n")
    (tmp_path / "b").write_text("Include a\nHost hb\n  User y\n")
    c = SSHConfig.from_file(tmp_path / "a")  # não pode entrar em laço infinito
    assert "ha" in c.host_names() and "hb" in c.host_names()


def test_include_ausente_e_ignorado(tmp_path):
    (tmp_path / "config").write_text("Include nao-existe\nHost srv\n  User root\n")
    c = SSHConfig.from_file(tmp_path / "config")
    assert c.lookup("srv")["user"] == "root"


def test_include_nao_e_seguido_em_from_text():
    """Sem um arquivo de origem, não há caminho base para resolver o Include."""
    c = SSHConfig.from_text("Include qualquer\nHost srv\n  User root\n")
    assert c.lookup("srv")["user"] == "root"
