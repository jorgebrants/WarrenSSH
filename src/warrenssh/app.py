# SPDX-License-Identifier: GPL-3.0-or-later
"""Classe da aplicação Adw."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from warrenssh import APP_ID  # noqa: E402
from warrenssh.ui.theme import AccentProvider  # noqa: E402
from warrenssh.ui.window import WarrenSSHWindow  # noqa: E402


class WarrenSSHApplication(Adw.Application):
    """Aplicação principal do WarrenSSH."""

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._window: WarrenSSHWindow | None = None
        self._accent: AccentProvider | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)
        _load_css()
        display = Gdk.Display.get_default()
        if display is not None:
            self._accent = AccentProvider()
            self._accent.attach(display)
        self._setup_actions()

    def do_activate(self) -> None:
        if self._window is None:
            self._window = WarrenSSHWindow(application=self)
        self._window.present()

    def _setup_actions(self) -> None:
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Primary>q"])


def _load_css() -> None:
    """Aplica o data/style.css ao display atual."""
    from importlib.resources import files

    display = Gdk.Display.get_default()
    if display is None:
        return

    css_path = files("warrenssh").joinpath("data/style.css")
    provider = Gtk.CssProvider()
    provider.load_from_path(str(css_path))
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
