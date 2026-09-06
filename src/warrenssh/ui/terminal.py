# SPDX-License-Identifier: GPL-3.0-or-later
"""Aba de terminal: um Vte.Terminal rodando o ssh da conexão."""

from __future__ import annotations

import os
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, GObject, Gtk  # noqa: E402

from warrenssh.models.node import Node  # noqa: E402
from warrenssh.ssh.command import CommandError, build_ssh_argv, describe  # noqa: E402

try:
    gi.require_version("Vte", "3.91")
    from gi.repository import Vte

    VTE_AVAILABLE = True
except (ImportError, ValueError):  # pragma: no cover - depende do sistema
    Vte = None  # type: ignore[assignment]
    VTE_AVAILABLE = False

VTE_MISSING_HINT = (
    "O terminal precisa do VTE para GTK4. Instale com:\n"
    "sudo apt install gir1.2-vte-3.91"
)

#: Paleta base (16 cores ANSI), estilo Adwaita Dark do GNOME Terminal.
ANSI_PALETTE = (
    "#241f31", "#c01c28", "#2ec27e", "#f5c211",
    "#1e78e4", "#9841bb", "#0ab9dc", "#c0bfbc",
    "#5e5c64", "#ed333b", "#57e389", "#f8e45c",
    "#51a1ff", "#c061cb", "#4fd2fd", "#f6f5f4",
)
DARK_FG, DARK_BG = "#ffffff", "#1d1d1d"
LIGHT_FG, LIGHT_BG = "#1d1d1d", "#fafafa"


class TerminalTab(Gtk.Box):
    """Terminal de uma sessão, com faixa de reconexão quando o ssh sai."""

    __gtype_name__ = "WarrenSSHTerminalTab"

    __gsignals__ = {
        # (mensagem) — problema que merece um toast na janela.
        "session-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # (código de saída) — o processo ssh terminou.
        "session-exited": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        # (texto) — o usuário digitou algo nesta aba (origem do broadcast).
        "user-typed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, node: Node, resolved: dict[str, Any]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.node = node
        self.resolved = dict(resolved)
        self.is_running = False
        self._pid = -1
        # A VTE emite "commit" também para o que entra por feed_child; sem este
        # guarda, duas abas em broadcast ecoariam uma na outra sem parar.
        self._injecting = False

        self._banner = Adw.Banner(button_label="Reconectar", revealed=False)
        self._banner.connect("button-clicked", lambda *_: self.reconnect())
        self.append(self._banner)

        if not VTE_AVAILABLE:
            self.terminal = None
            self.append(
                Adw.StatusPage(
                    icon_name="dialog-warning-symbolic",
                    title="VTE não encontrado",
                    description=VTE_MISSING_HINT,
                    vexpand=True,
                )
            )
            return

        self.terminal = Vte.Terminal(vexpand=True, hexpand=True)
        self.terminal.add_css_class("warrenssh-terminal")
        self._apply_appearance()
        self.terminal.connect("child-exited", self._on_child_exited)
        self.terminal.connect("commit", self._on_commit)

        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True,
            child=self.terminal,
        )
        self.append(scroller)

        # Sessões abertas acompanham a troca de claro/escuro do sistema.
        self._style_manager = Adw.StyleManager.get_default()
        self._style_handler = self._style_manager.connect(
            "notify::dark", lambda *_: self._apply_appearance()
        )
        self.connect("unrealize", self._on_unrealize)
        self.connect("map", self._on_first_map)

    # ------------------------------------------------------------------ aparência

    def _apply_appearance(self) -> None:
        """Cores e scrollback a partir das propriedades resolvidas."""
        assert self.terminal is not None
        scrollback = self.resolved.get("scrollback_lines") or 10000
        try:
            self.terminal.set_scrollback_lines(int(scrollback))
        except (TypeError, ValueError):
            self.terminal.set_scrollback_lines(10000)
        self.terminal.set_scroll_on_output(False)
        self.terminal.set_scroll_on_keystroke(True)
        self.terminal.set_mouse_autohide(True)

        scheme = str(self.resolved.get("color_scheme") or "system").lower()
        dark = (
            Adw.StyleManager.get_default().get_dark() if scheme == "system" else scheme == "dark"
        )
        fg, bg = (DARK_FG, DARK_BG) if dark else (LIGHT_FG, LIGHT_BG)
        palette = [_rgba(color) for color in ANSI_PALETTE]
        self.terminal.set_colors(_rgba(fg), _rgba(bg), palette)

    # ------------------------------------------------------------------ execução

    def _on_first_map(self, *_args: object) -> None:
        """O spawn espera o widget existir na tela para o PTY nascer do tamanho certo."""
        self.disconnect_by_func(self._on_first_map)
        self.connect_session()

    def connect_session(self) -> None:
        """Dispara o ssh de forma assíncrona (nunca bloqueia a UI)."""
        if self.terminal is None or self.is_running:
            return
        try:
            argv = build_ssh_argv(self.resolved)
        except CommandError as exc:
            self._show_banner(f"Não deu para montar o comando: {exc}")
            self.emit("session-error", str(exc))
            return

        self._banner.set_revealed(False)
        self.is_running = True
        self.terminal.spawn_async(
            Vte.PtyFlags.DEFAULT,
            None,  # cwd: herda o do app
            argv,
            None,  # envv: herda o ambiente
            GLib.SpawnFlags.DEFAULT,
            None,  # child_setup
            None,  # child_setup_data
            -1,  # timeout: sem limite
            None,  # cancellable
            self._on_spawned,
        )
        self.terminal.feed(f"\x1b[2mWarrenSSH: {describe(argv)}\x1b[0m\r\n".encode())

    def _on_spawned(
        self, _terminal: object, pid: int, error: GLib.Error | None, *_user_data: object
    ) -> None:
        if error is not None:
            self.is_running = False
            message = f"Falha ao iniciar o ssh: {error.message}"
            self._show_banner(message)
            self.emit("session-error", message)
            return
        self._pid = pid

    def _on_child_exited(self, _terminal: object, status: int) -> None:
        # A VTE entrega o status cru do waitpid; o usuário quer ver o código do ssh.
        self.is_running = False
        self._pid = -1
        code = _exit_code(status)
        self._show_banner(
            "Sessão encerrada." if code == 0 else f"Sessão encerrada (código {code})."
        )
        self.emit("session-exited", code)

    def reconnect(self) -> None:
        """Limpa a tela e sobe a sessão de novo."""
        if self.terminal is None:
            return
        self.terminal.reset(True, True)
        self.connect_session()

    def _on_unrealize(self, *_args: object) -> None:
        if self._style_handler:
            self._style_manager.disconnect(self._style_handler)
            self._style_handler = 0

    def close(self) -> None:
        """Encerra o processo filho, se houver."""
        if self.terminal is not None and self._pid > 0:
            try:
                self.terminal.get_pty().close()
            except Exception:  # pragma: no cover - PTY já pode ter morrido
                pass

    # -------------------------------------------------------------------- entrada

    def feed_input(self, text: str) -> None:
        """Injeta texto no processo remoto — o canal de chegada do broadcast."""
        if self.terminal is None or not self.is_running:
            return
        self._injecting = True
        try:
            self.terminal.feed_child(text.encode())
        finally:
            self._injecting = False

    def _on_commit(self, _terminal: object, text: str, _size: int) -> None:
        """Texto entrando no processo filho.

        A VTE não distingue o que o usuário digitou do que veio por
        `feed_child`, então `_injecting` faz essa separação: sem ela, o texto
        replicado voltaria como se fosse digitação e o broadcast viraria laço.
        """
        if self.is_running and not self._injecting:
            self.emit("user-typed", text)

    def set_broadcast_target(self, active: bool) -> None:
        """Marca visualmente que esta aba recebe o que é digitado em outra."""
        if active:
            self.add_css_class("warrenssh-broadcast")
        else:
            self.remove_css_class("warrenssh-broadcast")

    def _show_banner(self, message: str) -> None:
        self._banner.set_title(message)
        self._banner.set_revealed(True)


def _exit_code(status: int) -> int:
    """Traduz o wait status do waitpid em código de saída (negativo = sinal)."""
    try:
        return os.waitstatus_to_exitcode(status)
    except ValueError:  # status que o Python não sabe classificar
        return status


def _rgba(spec: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.parse(spec)
    return color
