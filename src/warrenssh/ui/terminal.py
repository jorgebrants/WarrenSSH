# SPDX-License-Identifier: GPL-3.0-or-later
"""Aba de terminal: um Vte.Terminal rodando o ssh da conexão."""

from __future__ import annotations

import os
import shutil
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from warrenssh import secrets  # noqa: E402
from warrenssh.askpass import ENV_NODE_ID  # noqa: E402
from warrenssh.models.node import Node  # noqa: E402
from warrenssh.models.preferences import (  # noqa: E402
    PALETA_PADRAO,
    PALETAS,
    cor_padrao,
)
from warrenssh.ssh.command import CommandError, build_ssh_argv, describe  # noqa: E402
from warrenssh.ssh.known_hosts import is_known  # noqa: E402

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

#: Formas de cursor que o VTE aceita, na ordem em que aparecem na UI.
CURSOR_SHAPES = {
    "block": "BLOCK",
    "ibeam": "IBEAM",
    "underline": "UNDERLINE",
}


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

    def __init__(
        self, node: Node, resolved: dict[str, Any], preferences: Any = None
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.node = node
        self.resolved = dict(resolved)
        self.preferences = preferences
        self._reconnect_source = 0
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

        self._setup_actions()
        self._setup_context_menu()
        self._setup_shortcuts()

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

    # -------------------------------------------------------- menu e atalhos

    def _setup_actions(self) -> None:
        """Ações do terminal, no grupo `term` — uma instância por aba."""
        grupo = Gio.SimpleActionGroup()
        for nome, handler in (
            ("copy", lambda *_: self.copy_selection()),
            ("paste", lambda *_: self.paste_clipboard()),
            ("select-all", lambda *_: self.terminal.select_all()),
            ("clear", lambda *_: self.clear()),
            ("reconnect", lambda *_: self.reconnect()),
            ("zoom-in", lambda *_: self.zoom(1.1)),
            ("zoom-out", lambda *_: self.zoom(1 / 1.1)),
            ("zoom-reset", lambda *_: self.zoom(None)),
        ):
            acao = Gio.SimpleAction.new(nome, None)
            acao.connect("activate", handler)
            grupo.add_action(acao)
        self._actions = grupo
        self.insert_action_group("term", grupo)

        # "Copiar" só faz sentido com algo selecionado.
        self.terminal.connect("selection-changed", self._on_selection_changed)
        self._on_selection_changed()

    def _on_selection_changed(self, *_args: object) -> None:
        acao = self._actions.lookup_action("copy")
        if acao is not None:
            acao.set_enabled(self.terminal.get_has_selection())

    def _setup_context_menu(self) -> None:
        menu = Gio.Menu()

        area = Gio.Menu()
        area.append("Copiar", "term.copy")
        area.append("Colar", "term.paste")
        area.append("Selecionar tudo", "term.select-all")
        menu.append_section(None, area)

        zoom = Gio.Menu()
        zoom.append("Aumentar", "term.zoom-in")
        zoom.append("Diminuir", "term.zoom-out")
        zoom.append("Tamanho normal", "term.zoom-reset")
        menu.append_section(None, zoom)

        sessao = Gio.Menu()
        sessao.append("Limpar", "term.clear")
        sessao.append("Reconectar", "term.reconnect")
        sessao.append("Fechar aba", "win.close-tab")
        menu.append_section(None, sessao)

        self._popover = Gtk.PopoverMenu.new_from_model(menu)
        self._popover.set_parent(self.terminal)
        self._popover.set_has_arrow(False)
        self._popover.set_halign(Gtk.Align.START)

        gesto = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesto.connect("pressed", self._on_secondary_click)
        self.terminal.add_controller(gesto)

    def _on_secondary_click(
        self, _gesto: Gtk.GestureClick, _n: int, x: float, y: float
    ) -> None:
        rect = Gdk.Rectangle()
        rect.x, rect.y = int(x), int(y)
        rect.width = rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _setup_shortcuts(self) -> None:
        """Atalhos no padrão de terminal (Ctrl+Shift+C/V).

        Fase CAPTURE porque a VTE consome o teclado: sem isso o atalho nunca
        chegaria até aqui.
        """
        controlador = Gtk.ShortcutController()
        controlador.set_scope(Gtk.ShortcutScope.LOCAL)
        controlador.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        for atalho, acao in (
            ("<Primary><Shift>c", "term.copy"),
            ("<Primary><Shift>v", "term.paste"),
            ("<Primary><Shift>a", "term.select-all"),
            ("<Primary>plus", "term.zoom-in"),
            ("<Primary>equal", "term.zoom-in"),
            ("<Primary>minus", "term.zoom-out"),
            ("<Primary>0", "term.zoom-reset"),
        ):
            controlador.add_shortcut(
                Gtk.Shortcut(
                    trigger=Gtk.ShortcutTrigger.parse_string(atalho),
                    action=Gtk.NamedAction.new(acao),
                )
            )
        self.add_controller(controlador)

    # ------------------------------------------------------- área de transferência

    def copy_selection(self) -> None:
        if self.terminal is not None and self.terminal.get_has_selection():
            self.terminal.copy_clipboard_format(Vte.Format.TEXT)

    def paste_clipboard(self) -> None:
        if self.terminal is not None:
            self.terminal.paste_clipboard()

    def clear(self) -> None:
        """Limpa a tela e o histórico, sem derrubar a sessão."""
        if self.terminal is not None:
            self.terminal.reset(False, True)

    def zoom(self, fator: float | None) -> None:
        """Ajusta o tamanho da fonte. `None` volta ao padrão."""
        if self.terminal is None:
            return
        atual = self.terminal.get_font_scale()
        novo = 1.0 if fator is None else max(0.5, min(4.0, atual * fator))
        self.terminal.set_font_scale(novo)

    # ------------------------------------------------------------------ aparência

    def _apply_appearance(self) -> None:
        """Cores e scrollback a partir das propriedades resolvidas."""
        assert self.terminal is not None
        scrollback = self.resolved.get("scrollback_lines") or 10000
        try:
            self.terminal.set_scrollback_lines(int(scrollback))
        except (TypeError, ValueError):
            self.terminal.set_scrollback_lines(10000)
        self.terminal.set_scroll_on_output(bool(self.resolved.get("scroll_on_output")))
        self.terminal.set_scroll_on_keystroke(
            self.resolved.get("scroll_on_keystroke", True) is not False
        )
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_audible_bell(bool(self.resolved.get("audible_bell")))
        self._apply_font()
        self._apply_cursor()

        fg, bg = self._resolve_colors()
        nome = str(self.resolved.get("palette_name") or PALETA_PADRAO)
        cores = PALETAS.get(nome, PALETAS[PALETA_PADRAO])
        self.terminal.set_colors(_rgba(fg), _rgba(bg), [_rgba(c) for c in cores])

    def reload_appearance(self, resolved: dict[str, Any]) -> None:
        """Troca a aparência de uma sessão viva, sem reconectar."""
        self.resolved = dict(resolved)
        if self.terminal is not None:
            self._apply_appearance()

    def _apply_font(self) -> None:
        """Fonte do terminal. Sem valor definido, segue a fonte monoespaçada do sistema."""
        assert self.terminal is not None
        descricao = str(self.resolved.get("font") or "").strip()
        if descricao:
            self.terminal.set_font(Pango.FontDescription.from_string(descricao))
        else:
            self.terminal.set_font(None)

    def _apply_cursor(self) -> None:
        assert self.terminal is not None
        forma = str(self.resolved.get("cursor_shape") or "block").lower()
        self.terminal.set_cursor_shape(
            getattr(Vte.CursorShape, CURSOR_SHAPES.get(forma, "BLOCK"))
        )
        piscar = self.resolved.get("cursor_blink", True) is not False
        self.terminal.set_cursor_blink_mode(
            Vte.CursorBlinkMode.ON if piscar else Vte.CursorBlinkMode.OFF
        )

    def _resolve_colors(self) -> tuple[str, str]:
        """Cores do terminal: o esquema define a base, o nó pode sobrepor.

        Assim uma pasta inteira ("Produção") pode ter fundo próprio, e cada
        conexão herda — dá para reconhecer onde se está pela cor da tela.
        """
        scheme = str(self.resolved.get("color_scheme") or "system").lower()
        dark = (
            Adw.StyleManager.get_default().get_dark() if scheme == "system" else scheme == "dark"
        )
        return (
            _cor_valida(self.resolved.get("foreground_color"))
            or cor_padrao("foreground_color", dark),
            _cor_valida(self.resolved.get("background_color"))
            or cor_padrao("background_color", dark),
        )

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
            self._spawn_env(),
            GLib.SpawnFlags.DEFAULT,
            None,  # child_setup
            None,  # child_setup_data
            -1,  # timeout: sem limite
            None,  # cancellable
            self._on_spawned,
        )
        self.terminal.feed(f"\x1b[2mWarrenSSH: {describe(argv)}\x1b[0m\r\n".encode())

    def _spawn_env(self) -> list[str] | None:
        """Ambiente do ssh. `None` = herda o do app, sem senha automática.

        A senha só entra quando há uma guardada no chaveiro E o host já teve a
        chave aceita. Com host novo, o ssh precisa perguntar sobre a chave — e
        essa pergunta também passaria pelo askpass, que se recusa a respondê-la.
        """
        if self.preferences is not None and not self.preferences.get_app(
            "use_saved_passwords"
        ):
            return None
        if not secrets.has_password(self.node.id) and not secrets.has_password(
            self.node.id, kind=secrets.KIND_PASSPHRASE
        ):
            return None
        if not is_known(self.resolved.get("host", ""), self.resolved.get("port")):
            return None

        helper = shutil.which("warrenssh-askpass")
        if helper is None:
            return None

        ambiente = dict(os.environ)
        ambiente["SSH_ASKPASS"] = helper
        ambiente["SSH_ASKPASS_REQUIRE"] = "force"
        ambiente[ENV_NODE_ID] = self.node.id
        return [f"{chave}={valor}" for chave, valor in ambiente.items()]

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
        self._maybe_auto_reconnect(code)

    def _maybe_auto_reconnect(self, code: int) -> None:
        """Reconecta sozinho quando a sessão cai — não quando o usuário sai dela.

        Código 0 é saída limpa (`exit`, `logout`): insistir aí seria brigar com
        quem quis encerrar.
        """
        if code == 0 or self.preferences is None:
            return
        if not self.preferences.get_app("auto_reconnect"):
            return
        try:
            espera = max(1, int(self.preferences.get_app("auto_reconnect_delay") or 3))
        except (TypeError, ValueError):
            espera = 3
        self._show_banner(f"Sessão caiu. Reconectando em {espera}s…")
        self._reconnect_source = GLib.timeout_add_seconds(espera, self._do_auto_reconnect)

    def _do_auto_reconnect(self) -> bool:
        self._reconnect_source = 0
        if self.get_mapped():          # a aba ainda existe?
            self.reconnect()
        return False

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
        if self._reconnect_source:
            GLib.source_remove(self._reconnect_source)
            self._reconnect_source = 0
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


def _cor_valida(valor: Any) -> str | None:
    """Aceita a cor só se o GDK souber interpretá-la; senão, cai no padrão."""
    if not valor:
        return None
    texto = str(valor).strip()
    return texto if Gdk.RGBA().parse(texto) else None


def _rgba(spec: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.parse(spec)
    return color
