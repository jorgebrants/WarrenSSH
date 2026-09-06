# SPDX-License-Identifier: GPL-3.0-or-later
"""Cor de acento do WarrenSSH, ajustada ao tema claro/escuro em uso.

O GTK CSS não tem consulta de tema, então as cores que precisam mudar com o
tema ficam num provider próprio, recarregado quando o sistema alterna.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

#: Teal do WarrenSSH. Dois tons: o escuro passa contraste sobre fundo claro,
#: o claro passa sobre fundo escuro — o mesmo acento, legível dos dois lados.
ACCENT_LIGHT = {"bg": "#0f7d87", "fg": "#ffffff", "text": "#0a626a"}
ACCENT_DARK = {"bg": "#1a97a3", "fg": "#00272b", "text": "#5fd3dd"}

_TEMPLATE = """
@define-color accent_bg_color {bg};
@define-color accent_fg_color {fg};
@define-color accent_color {text};
"""


class AccentProvider:
    """Mantém o acento em dia com o tema do sistema."""

    def __init__(self) -> None:
        self._provider = Gtk.CssProvider()
        self._style_manager = Adw.StyleManager.get_default()
        self._style_manager.connect("notify::dark", lambda *_: self.refresh())

    def attach(self, display: Gdk.Display) -> None:
        Gtk.StyleContext.add_provider_for_display(
            display, self._provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
        self.refresh()

    def refresh(self) -> None:
        palette = ACCENT_DARK if self._style_manager.get_dark() else ACCENT_LIGHT
        self._provider.load_from_string(_TEMPLATE.format(**palette))
