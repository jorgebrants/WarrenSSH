# SPDX-License-Identifier: GPL-3.0-or-later
"""Testes do helper de SSH_ASKPASS."""

from __future__ import annotations

import pytest

from warrenssh import askpass


@pytest.fixture
def chaveiro_falso(monkeypatch):
    """Substitui o chaveiro, para os testes não dependerem do libsecret."""
    guardado = {("no-1", "password"): "senha-do-login", ("no-1", "passphrase"): "frase-da-chave"}

    class SecretsFalso:
        KIND_PASSWORD = "password"
        KIND_PASSPHRASE = "passphrase"
        SecretsError = RuntimeError

        @staticmethod
        def lookup_password(node_id, *, kind="password"):
            return guardado.get((node_id, kind))

    monkeypatch.setitem(__import__("sys").modules, "warrenssh.secrets", SecretsFalso)
    return SecretsFalso


CONFIRMACOES = [
    "Are you sure you want to continue connecting (yes/no/[fingerprint])? ",
    "Please type 'yes', 'no' or the fingerprint: ",
    "The authenticity of host 'srv' can't be established.\n"
    "Are you sure you want to continue connecting (yes/no)? ",
]


@pytest.mark.parametrize("prompt", CONFIRMACOES)
def test_nunca_responde_confirmacao(prompt, chaveiro_falso):
    """Aceitar a chave de um host é decisão do usuário, não do gerenciador.

    Além do risco, responder algo que não seja `yes`/`no` põe o ssh num laço
    infinito de re-perguntas — comprovado na prática.
    """
    assert askpass.responder(prompt, "no-1") is None


def test_senha_de_login(chaveiro_falso):
    assert askpass.responder("jorge@srv's password: ", "no-1") == "senha-do-login"


def test_passphrase_de_chave(chaveiro_falso):
    assert (
        askpass.responder("Enter passphrase for key '/home/x/.ssh/id_ed25519': ", "no-1")
        == "frase-da-chave"
    )


def test_sem_node_id_nao_responde(chaveiro_falso):
    assert askpass.responder("password: ", None) is None
    assert askpass.responder("password: ", "") is None


def test_no_sem_segredo_guardado(chaveiro_falso):
    assert askpass.responder("password: ", "no-desconhecido") is None


def test_main_devolve_1_quando_nao_responde(chaveiro_falso, monkeypatch, capsys):
    monkeypatch.delenv(askpass.ENV_NODE_ID, raising=False)
    assert askpass.main(["password: "]) == 1
    assert capsys.readouterr().out == ""


def test_main_escreve_a_senha_no_stdout(chaveiro_falso, monkeypatch, capsys):
    monkeypatch.setenv(askpass.ENV_NODE_ID, "no-1")
    assert askpass.main(["password: "]) == 0
    assert capsys.readouterr().out == "senha-do-login\n"


def test_main_sem_argumento_nao_quebra(chaveiro_falso, monkeypatch):
    monkeypatch.setenv(askpass.ENV_NODE_ID, "no-1")
    assert askpass.main([]) == 0  # prompt vazio não é confirmação: devolve a senha
