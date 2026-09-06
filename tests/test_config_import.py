# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do import do ~/.ssh/config."""

from __future__ import annotations

import pytest

from warrenssh.models.resolver import resolve
from warrenssh.models.store import Store
from warrenssh.ssh.config_import import (
    IMPORT_FOLDER_NAME,
    import_into,
    parse_config_file,
    parse_config_text,
)

CONFIG = """
# comentário no topo
Host bastion
    HostName bastion.example.com
    User operador
    Port 2222
    IdentityFile ~/.ssh/id_ed25519

Host web-01
    HostName 192.0.2.11
    ProxyJump bastion
    RequestTTY yes

Host web-02 web-03
    HostName 192.0.2.12

Host sem-hostname

Host *.interno
    User interno

# Convenção do OpenSSH: o curinga vem por último, porque o primeiro valor vence.
Host *
    ServerAliveInterval 30
    User padrao
"""


@pytest.fixture
def hosts():
    return parse_config_text(CONFIG)


def test_ignora_curingas(hosts):
    nomes = [h.name for h in hosts]
    assert "*" not in nomes
    assert "*.interno" not in nomes


def test_le_todos_os_hosts_concretos(hosts):
    assert [h.name for h in hosts] == [
        "bastion",
        "web-01",
        "web-02",
        "web-03",
        "sem-hostname",
    ]


def test_mapeia_as_diretivas(hosts):
    bastion = next(h for h in hosts if h.name == "bastion")
    assert bastion.properties["host"] == "bastion.example.com"
    assert bastion.properties["user"] == "operador"
    assert bastion.properties["port"] == 2222
    assert bastion.properties["identity_file"].endswith("id_ed25519")


def test_proxy_jump_e_request_tty(hosts):
    servidor = next(h for h in hosts if h.name == "web-01")
    assert servidor.properties["proxy_jump"] == "bastion"
    assert servidor.properties["request_pty"] is True


def test_host_sem_hostname_usa_o_proprio_nome(hosts):
    node = next(h for h in hosts if h.name == "sem-hostname")
    assert node.properties["host"] == "sem-hostname"


def test_linha_com_varios_nomes_vira_varias_conexoes(hosts):
    dois = [h for h in hosts if h.name in ("web-02", "web-03")]
    assert len(dois) == 2
    assert all(h.properties["host"] == "192.0.2.12" for h in dois)


def test_valores_do_host_curinga_sao_aplicados(hosts):
    """`Host *` no fim define User padrao para quem não declarou o seu."""
    servidor = next(h for h in hosts if h.name == "web-01")
    assert servidor.properties["user"] == "padrao"
    # E não atropela quem declarou.
    assert next(h for h in hosts if h.name == "bastion").properties["user"] == "operador"


def test_curinga_no_topo_vence_como_no_openssh():
    """No ssh_config o PRIMEIRO valor obtido vence: um `Host *` no topo do
    arquivo sobrepõe os blocos seguintes. Reproduzimos essa semântica em vez de
    'consertá-la', para o import bater com o que o `ssh` de fato faria."""
    hosts = parse_config_text(
        "Host *\n    User padrao\n\nHost srv\n    HostName 1.2.3.4\n    User operador\n"
    )
    assert hosts[0].properties["user"] == "padrao"


def test_summary_e_legivel(hosts):
    bastion = next(h for h in hosts if h.name == "bastion")
    servidor = next(h for h in hosts if h.name == "web-01")
    assert bastion.summary() == "bastion → operador@bastion.example.com:2222"
    assert servidor.summary() == "web-01 → padrao@192.0.2.11 via bastion"


def test_config_vazio_ou_so_comentarios():
    assert parse_config_text("") == []
    assert parse_config_text("# nada aqui\n\n") == []


def test_arquivo_ausente_nao_quebra(tmp_path):
    assert parse_config_file(tmp_path / "nao-existe") == []


def test_le_do_disco(tmp_path):
    caminho = tmp_path / "config"
    caminho.write_text(CONFIG, encoding="utf-8")
    assert [h.name for h in parse_config_file(caminho)] == [
        "bastion",
        "web-01",
        "web-02",
        "web-03",
        "sem-hostname",
    ]


def test_sintaxe_com_igual():
    hosts = parse_config_text("Host=srv\n    HostName=1.2.3.4\n")
    assert [h.name for h in hosts] == ["srv"]
    assert hosts[0].properties["host"] == "1.2.3.4"


# ----------------------------------------------------------------- import_into


def test_import_into_cria_pasta_e_conexoes(tmp_path, hosts):
    store = Store(tmp_path / "tree.json")
    pasta, criados, pulados = import_into(store, hosts)

    assert pasta.name == IMPORT_FOLDER_NAME
    assert pasta.kind == "folder"
    assert len(criados) == 5
    assert pulados == []
    assert [n.name for n in store.children(pasta.id)][:2] == ["bastion", "web-01"]


def test_import_into_e_idempotente(tmp_path, hosts):
    store = Store(tmp_path / "tree.json")
    import_into(store, hosts)
    pasta, criados, pulados = import_into(store, hosts)

    assert criados == []
    assert len(pulados) == 5
    assert len(store.children(pasta.id)) == 5  # nada duplicado
    assert len([n for n in store.roots()]) == 1  # nem a pasta


def test_importado_herda_o_que_o_config_nao_disse(tmp_path, hosts):
    store = Store(tmp_path / "tree.json")
    pasta, criados, _ = import_into(store, hosts)
    servidor = next(n for n in criados if n.name == "web-01")

    # O config não deu identity_file: fica herdável para a pasta preencher depois.
    assert "identity_file" in servidor.inherited
    pasta.properties["identity_file"] = "/tmp/chave-do-grupo"
    assert resolve(servidor, "identity_file", store) == "/tmp/chave-do-grupo"

    # O que veio do config é local e não é sobrescrito pela pasta.
    assert "proxy_jump" not in servidor.inherited
    pasta.properties["proxy_jump"] = "outro-bastion"
    assert resolve(servidor, "proxy_jump", store) == "bastion"


def test_host_nunca_e_marcado_como_herdado(tmp_path, hosts):
    store = Store(tmp_path / "tree.json")
    _pasta, criados, _ = import_into(store, hosts)
    assert all("host" not in n.inherited for n in criados)


def test_identity_file_volta_para_o_formato_com_til(hosts):
    """O paramiko expande `~`; o JSON guarda a forma portátil."""
    bastion = next(h for h in hosts if h.name == "bastion")
    assert bastion.properties["identity_file"] == "~/.ssh/id_ed25519"


def test_identity_file_fora_do_home_fica_absoluto():
    hosts = parse_config_text("Host srv\n    HostName 1.2.3.4\n    IdentityFile /etc/keys/id\n")
    assert hosts[0].properties["identity_file"] == "/etc/keys/id"
