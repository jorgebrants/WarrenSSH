# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da montagem do argv do ssh."""

from __future__ import annotations

import os

import pytest

from warrenssh.ssh.command import (
    CommandError,
    build_ssh_argv,
    default_ssh_command,
    describe,
)


def test_minimo_so_host():
    assert build_ssh_argv({"host": "192.0.2.1"}) == ["ssh", "192.0.2.1"]


def test_usuario_vira_user_arroba_host():
    assert build_ssh_argv({"host": "srv", "user": "operador"}) == ["ssh", "operador@srv"]


def test_porta_padrao_e_omitida():
    assert build_ssh_argv({"host": "srv", "port": 22}) == ["ssh", "srv"]


def test_porta_diferente_entra_com_p():
    assert build_ssh_argv({"host": "srv", "port": 2222}) == ["ssh", "-p", "2222", "srv"]


def test_porta_como_string_e_aceita():
    assert build_ssh_argv({"host": "srv", "port": "2222"})[:3] == ["ssh", "-p", "2222"]


@pytest.mark.parametrize("port", ["abc", 0, 70000, -1])
def test_porta_invalida_falha(port):
    with pytest.raises(CommandError):
        build_ssh_argv({"host": "srv", "port": port})


def test_identity_file_expande_til():
    argv = build_ssh_argv({"host": "srv", "identity_file": "~/.ssh/id_ed25519"})
    assert argv[1] == "-i"
    assert argv[2] == os.path.expanduser("~/.ssh/id_ed25519")
    assert "~" not in argv[2]


def test_proxy_jump_vira_dash_j():
    argv = build_ssh_argv({"host": "srv", "proxy_jump": "bastion.example.com"})
    assert argv == ["ssh", "-J", "bastion.example.com", "srv"]


def test_request_pty_vira_dash_t():
    assert "-t" in build_ssh_argv({"host": "srv", "request_pty": True})
    assert "-t" not in build_ssh_argv({"host": "srv", "request_pty": False})


def test_extra_args_como_lista():
    argv = build_ssh_argv({"host": "srv", "extra_ssh_args": ["-o", "StrictHostKeyChecking=no"]})
    assert argv == ["ssh", "-o", "StrictHostKeyChecking=no", "srv"]


def test_extra_args_como_string_usa_shlex():
    argv = build_ssh_argv({"host": "srv", "extra_ssh_args": "-o 'ServerAliveInterval 30'"})
    assert argv == ["ssh", "-o", "ServerAliveInterval 30", "srv"]


def test_startup_command_vai_depois_do_destino():
    argv = build_ssh_argv({"host": "srv", "user": "root", "startup_command": "tmux attach"})
    assert argv == ["ssh", "root@srv", "tmux attach"]


def test_conexao_completa_mantem_a_ordem_das_opcoes():
    argv = build_ssh_argv(
        {
            "host": "192.0.2.1",
            "port": 2222,
            "user": "operador",
            "identity_file": "/tmp/key",
            "proxy_jump": "bastion.example.com",
            "request_pty": True,
            "extra_ssh_args": ["-o", "ConnectTimeout=5"],
            "startup_command": "htop",
            "charset": "UTF-8",          # props de terminal não entram no argv
            "scrollback_lines": 10000,
        }
    )
    assert argv == [
        "ssh",
        "-p", "2222",
        "-i", "/tmp/key",
        "-J", "bastion.example.com",
        "-t",
        "-o", "ConnectTimeout=5",
        "operador@192.0.2.1",
        "htop",
    ]


def test_sem_host_falha():
    with pytest.raises(CommandError):
        build_ssh_argv({"user": "root"})
    with pytest.raises(CommandError):
        build_ssh_argv({"host": "   "})


@pytest.mark.parametrize("campo", ["host", "user", "proxy_jump"])
def test_valor_comecando_com_hifen_e_recusado(campo):
    props = {"host": "srv", campo: "-oProxyCommand=touch /tmp/x"}
    with pytest.raises(CommandError):
        build_ssh_argv(props)


def test_valores_vazios_sao_ignorados():
    argv = build_ssh_argv(
        {"host": "srv", "user": "", "identity_file": "  ", "proxy_jump": None, "port": None}
    )
    assert argv == ["ssh", "srv"]


def test_describe_cita_o_que_precisa():
    argv = build_ssh_argv({"host": "srv", "startup_command": "echo oi mundo"})
    assert describe(argv) == "ssh srv 'echo oi mundo'"


def test_binario_customizado():
    argv = build_ssh_argv({"host": "srv"}, ssh_binary="/usr/bin/ssh")
    assert argv[0] == "/usr/bin/ssh"


# ------------------------------------------------- como invocar o ssh no ambiente


def test_default_ssh_command_respeita_a_variavel(monkeypatch):
    monkeypatch.setenv("WARRENSSH_SSH_BINARY", "/opt/bin/ssh -F /etc/meu_config")
    assert default_ssh_command() == ["/opt/bin/ssh", "-F", "/etc/meu_config"]


def test_default_ssh_command_usa_o_ssh_do_path(monkeypatch):
    monkeypatch.delenv("WARRENSSH_SSH_BINARY", raising=False)
    monkeypatch.setattr("warrenssh.ssh.command.shutil.which", lambda nome: "/usr/bin/ssh")
    assert default_ssh_command() == ["ssh"]


def test_sem_ssh_no_sandbox_usa_o_host_via_flatpak_spawn(monkeypatch):
    """Se o runtime do Flatpak não trouxer ssh, chamamos o do host."""
    monkeypatch.delenv("WARRENSSH_SSH_BINARY", raising=False)
    monkeypatch.setattr(
        "warrenssh.ssh.command.shutil.which",
        lambda nome: "/usr/bin/flatpak-spawn" if nome == "flatpak-spawn" else None,
    )
    monkeypatch.setattr("warrenssh.ssh.command.os.path.exists", lambda p: True)
    assert default_ssh_command() == ["flatpak-spawn", "--host", "ssh"]


def test_sem_ssh_e_sem_sandbox_deixa_o_spawn_falhar(monkeypatch):
    monkeypatch.delenv("WARRENSSH_SSH_BINARY", raising=False)
    monkeypatch.setattr("warrenssh.ssh.command.shutil.which", lambda nome: None)
    monkeypatch.setattr("warrenssh.ssh.command.os.path.exists", lambda p: False)
    assert default_ssh_command() == ["ssh"]


def test_ssh_command_prefixa_o_argv():
    argv = build_ssh_argv(
        {"host": "srv", "port": 2222}, ssh_command=["flatpak-spawn", "--host", "ssh"]
    )
    assert argv == ["flatpak-spawn", "--host", "ssh", "-p", "2222", "srv"]


def test_ssh_command_vazio_falha():
    with pytest.raises(CommandError):
        build_ssh_argv({"host": "srv"}, ssh_command=[])
