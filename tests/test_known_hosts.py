# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes da consulta ao known_hosts."""

from __future__ import annotations

import pytest

from warrenssh.ssh import known_hosts


@pytest.mark.parametrize(
    "host,port,esperado",
    [
        ("srv", None, "srv"),
        ("srv", 22, "srv"),
        ("srv", "22", "srv"),
        ("srv", 5027, "[srv]:5027"),
        ("192.0.2.1", "2222", "[192.0.2.1]:2222"),
        ("srv", "porta-errada", "srv"),   # valor inválido cai no padrão
        ("srv", "", "srv"),
    ],
)
def test_alvo(host, port, esperado):
    assert known_hosts.alvo(host, port) == esperado


def test_host_vazio_nunca_e_conhecido():
    assert known_hosts.is_known("") is False


def test_sem_ssh_keygen_assume_desconhecido(monkeypatch):
    """Na dúvida, deixar o ssh perguntar é o caminho seguro."""
    monkeypatch.setattr(known_hosts.shutil, "which", lambda _: None)
    assert known_hosts.is_known("srv") is False


def test_erro_do_subprocesso_assume_desconhecido(monkeypatch):
    monkeypatch.setattr(known_hosts.shutil, "which", lambda _: "/usr/bin/ssh-keygen")

    def explode(*_a, **_k):
        raise OSError("falhou")

    monkeypatch.setattr(known_hosts.subprocess, "run", explode)
    assert known_hosts.is_known("srv") is False


def test_timeout_assume_desconhecido(monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(known_hosts.shutil, "which", lambda _: "/usr/bin/ssh-keygen")

    def estoura(*_a, **_k):
        raise sp.TimeoutExpired("ssh-keygen", 5)

    monkeypatch.setattr(known_hosts.subprocess, "run", estoura)
    assert known_hosts.is_known("srv") is False


def test_conhecido_quando_ssh_keygen_encontra(monkeypatch):
    monkeypatch.setattr(known_hosts.shutil, "which", lambda _: "/usr/bin/ssh-keygen")

    class Resultado:
        returncode = 0

    monkeypatch.setattr(known_hosts.subprocess, "run", lambda *a, **k: Resultado())
    assert known_hosts.is_known("srv", 5027) is True


def test_desconhecido_quando_ssh_keygen_nao_encontra(monkeypatch):
    monkeypatch.setattr(known_hosts.shutil, "which", lambda _: "/usr/bin/ssh-keygen")

    class Resultado:
        returncode = 1

    monkeypatch.setattr(known_hosts.subprocess, "run", lambda *a, **k: Resultado())
    assert known_hosts.is_known("srv") is False
