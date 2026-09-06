# SPDX-License-Identifier: GPL-3.0-or-later
"""Senhas e passphrases no chaveiro do sistema (libsecret).

Regra do projeto: segredo NUNCA vai para o tree.json — lá fica só o id do nó,
que é a chave de busca no chaveiro.
"""

from __future__ import annotations

import gi

gi.require_version("Secret", "1")

from gi.repository import GLib, Secret  # noqa: E402

from warrenssh import APP_ID  # noqa: E402

#: Tipos de segredo que um nó pode ter.
KIND_PASSWORD = "password"
KIND_PASSPHRASE = "passphrase"

SCHEMA = Secret.Schema.new(
    APP_ID,
    Secret.SchemaFlags.NONE,
    {
        "node_id": Secret.SchemaAttributeType.STRING,
        "kind": Secret.SchemaAttributeType.STRING,
    },
)


class SecretsError(RuntimeError):
    """Chaveiro indisponível ou trancado."""


def is_available() -> bool:
    """Diz se há um serviço de chaveiro respondendo (não há em toda sessão)."""
    try:
        Secret.Service.get_sync(Secret.ServiceFlags.NONE, None)
    except GLib.Error:
        return False
    return True


def store_password(node_id: str, secret: str, *, kind: str = KIND_PASSWORD, label: str = "") -> None:
    """Grava (ou substitui) o segredo de um nó."""
    if not secret:
        delete_password(node_id, kind=kind)
        return
    try:
        Secret.password_store_sync(
            SCHEMA,
            _attributes(node_id, kind),
            Secret.COLLECTION_DEFAULT,
            label or f"WarrenSSH — {kind} ({node_id})",
            secret,
            None,
        )
    except GLib.Error as exc:
        raise SecretsError(f"não deu para gravar no chaveiro: {exc.message}") from exc


def lookup_password(node_id: str, *, kind: str = KIND_PASSWORD) -> str | None:
    """Busca o segredo de um nó. None quando não existe."""
    try:
        return Secret.password_lookup_sync(SCHEMA, _attributes(node_id, kind), None)
    except GLib.Error as exc:
        raise SecretsError(f"não deu para ler o chaveiro: {exc.message}") from exc


def delete_password(node_id: str, *, kind: str = KIND_PASSWORD) -> bool:
    """Remove o segredo. Devolve se havia algo para remover."""
    try:
        return Secret.password_clear_sync(SCHEMA, _attributes(node_id, kind), None)
    except GLib.Error as exc:
        raise SecretsError(f"não deu para limpar o chaveiro: {exc.message}") from exc


def delete_all(node_id: str) -> None:
    """Limpa todos os segredos de um nó — usado quando o nó é excluído."""
    for kind in (KIND_PASSWORD, KIND_PASSPHRASE):
        try:
            delete_password(node_id, kind=kind)
        except SecretsError:
            pass  # excluir um nó não pode falhar por causa do chaveiro


def has_password(node_id: str, *, kind: str = KIND_PASSWORD) -> bool:
    try:
        return lookup_password(node_id, kind=kind) is not None
    except SecretsError:
        return False


def _attributes(node_id: str, kind: str) -> dict[str, str]:
    return {"node_id": node_id, "kind": kind}
