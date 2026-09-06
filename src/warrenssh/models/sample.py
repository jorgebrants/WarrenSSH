# SPDX-License-Identifier: GPL-3.0-or-later
"""Árvore de exemplo para a primeira execução (nada é gravado no disco)."""

from __future__ import annotations

from warrenssh.models.node import new_connection, new_folder
from warrenssh.models.store import Store


def populate_example(store: Store) -> Store:
    """Cria uma pasta 'Exemplo' com duas conexões que herdam o perfil da pasta."""
    exemplo = store.add(
        new_folder(
            "Exemplo",
            properties={"user": "root", "port": 22},
        )
    )
    store.add(
        new_connection(
            "localhost",
            parent_id=exemplo.id,
            properties={"host": "127.0.0.1", "request_pty": True},
            inherited={"port"},
        )
    )
    store.add(
        new_connection(
            "servidor-exemplo",
            parent_id=exemplo.id,
            properties={"host": "192.0.2.10"},
            inherited={"user", "port"},
        )
    )
    return store
