# SPDX-License-Identifier: GPL-3.0-or-later
"""Helper de `SSH_ASKPASS`: entrega ao ssh a senha guardada no chaveiro.

O ssh chama este programa com o texto do prompt em `argv[1]` e lê a resposta do
stdout. Assim a senha nunca passa pelo terminal nem pela linha de comando.

Regra de ouro: **confirmações nunca são respondidas aqui.** Se o ssh perguntar
sobre a autenticidade de uma chave de host, este helper recusa — decidir isso é
do usuário, não do gerenciador de senhas. (E responder qualquer coisa que não
seja `yes`/`no` põe o ssh num laço infinito de re-perguntas.)
"""

from __future__ import annotations

import os
import re
import sys

#: Prompts de confirmação, que este helper se recusa a responder.
_CONFIRMACAO = re.compile(
    r"yes/no|please type|fingerprint\]|continue connecting", re.IGNORECASE
)

#: Prompts de passphrase de chave; o resto é senha de login.
_PASSPHRASE = re.compile(r"passphrase", re.IGNORECASE)

#: Variável em que o WarrenSSH informa de qual nó é a sessão.
ENV_NODE_ID = "WARRENSSH_NODE_ID"


def responder(prompt: str, node_id: str | None) -> str | None:
    """Decide a resposta para um prompt. `None` significa 'não vou responder'."""
    if not node_id or _CONFIRMACAO.search(prompt):
        return None

    from warrenssh import secrets

    kind = secrets.KIND_PASSPHRASE if _PASSPHRASE.search(prompt) else secrets.KIND_PASSWORD
    try:
        return secrets.lookup_password(node_id, kind=kind)
    except secrets.SecretsError:
        return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    prompt = args[0] if args else ""

    resposta = responder(prompt, os.environ.get(ENV_NODE_ID))
    if resposta is None:
        # Sem resposta: o ssh cai no comportamento padrão (falha ou pergunta).
        return 1

    sys.stdout.write(resposta + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
