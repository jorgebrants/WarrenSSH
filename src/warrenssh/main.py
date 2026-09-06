# SPDX-License-Identifier: GPL-3.0-or-later
"""Entrypoint do WarrenSSH."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Cria a aplicação e entrega o controle ao loop do GTK."""
    from warrenssh.app import WarrenSSHApplication

    app = WarrenSSHApplication()
    return app.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
