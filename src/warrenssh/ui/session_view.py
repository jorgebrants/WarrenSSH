# SPDX-License-Identifier: GPL-3.0-or-later
"""Área de sessões: Adw.TabView com uma aba por terminal."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GObject, Gtk  # noqa: E402

from warrenssh.models.node import Node  # noqa: E402
from warrenssh.models.resolver import resolve_all  # noqa: E402
from warrenssh.models.store import Store  # noqa: E402
from warrenssh.ui.terminal import TerminalTab  # noqa: E402


class SessionView(Gtk.Box):
    """Pilha de abas de terminal. Vazia, mostra a página de boas-vindas."""

    __gtype_name__ = "WarrenSSHSessionView"

    __gsignals__ = {
        # (mensagem) — a janela transforma em Adw.Toast.
        "session-error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        # (ligado) — o modo broadcast mudou.
        "broadcast-changed": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
    }

    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._store = store
        self._broadcast = False

        self.tab_view = Adw.TabView(vexpand=True)
        self.tab_view.connect("close-page", self._on_close_page)
        self.tab_view.connect("notify::n-pages", self._on_pages_changed)

        self.tab_bar = Adw.TabBar(view=self.tab_view, autohide=False)

        self._welcome = Adw.StatusPage(
            icon_name="utilities-terminal-symbolic",
            title="WarrenSSH",
            description="Escolha uma conexão na árvore para abrir uma sessão.",
            vexpand=True,
        )

        self._stack = Gtk.Stack()
        self._stack.add_named(self._welcome, "welcome")
        self._stack.add_named(self.tab_view, "sessions")

        self.append(self.tab_bar)
        self.append(self._stack)
        self._on_pages_changed()

    # -------------------------------------------------------------------- sessões

    def open_session(self, node: Node) -> Adw.TabPage | None:
        """Resolve as propriedades do nó e abre uma aba conectando por ssh."""
        if node.kind != "connection":
            return None

        resolved = resolve_all(node, self._store, with_defaults=True)
        tab = TerminalTab(node, resolved, self._store.preferences)
        tab.connect("session-error", lambda _t, msg: self.emit("session-error", msg))
        tab.connect("session-exited", self._on_session_exited)
        tab.connect("user-typed", self._on_user_typed)

        page = self.tab_view.append(tab)
        page.set_title(node.name)
        page.set_tooltip(_page_tooltip(node, resolved))
        page.set_icon(Gio.ThemedIcon.new("utilities-terminal-symbolic"))
        self.tab_view.set_selected_page(page)
        self._refresh_broadcast_marks()
        return page

    def refresh_appearance(self) -> None:
        """Reaplica fonte, cores e cursor nas sessões já abertas.

        As preferências são o topo da cascata, então mudá-las muda o valor
        efetivo de quem não definiu o seu — inclusive de quem já está conectado.
        """
        for tab in self.terminal_tabs():
            tab.reload_appearance(resolve_all(tab.node, self._store, with_defaults=True))

    def current_tab(self) -> TerminalTab | None:
        page = self.tab_view.get_selected_page()
        return page.get_child() if page is not None else None

    def terminal_tabs(self) -> list[TerminalTab]:
        pages = self.tab_view.get_pages()
        return [pages.get_item(i).get_child() for i in range(pages.get_n_items())]

    def close_current(self) -> None:
        page = self.tab_view.get_selected_page()
        if page is not None:
            self.tab_view.close_page(page)

    # ------------------------------------------------------------------ broadcast

    @property
    def broadcast(self) -> bool:
        return self._broadcast

    def set_broadcast(self, active: bool) -> None:
        """Liga/desliga o envio do que é digitado para todas as abas vivas."""
        if active == self._broadcast:
            return
        self._broadcast = active
        self._refresh_broadcast_marks()
        self.emit("broadcast-changed", active)

    def toggle_broadcast(self) -> bool:
        self.set_broadcast(not self._broadcast)
        return self._broadcast

    def _on_user_typed(self, origem: TerminalTab, text: str) -> None:
        """Replica a digitação nas demais abas conectadas."""
        if not self._broadcast:
            return
        for tab in self.terminal_tabs():
            if tab is not origem and tab.is_running:
                tab.feed_input(text)

    def _refresh_broadcast_marks(self) -> None:
        """Badge nas abas que estão no modo broadcast."""
        pages = self.tab_view.get_pages()
        for i in range(pages.get_n_items()):
            page = pages.get_item(i)
            tab = page.get_child()
            ativo = self._broadcast and tab.is_running
            page.set_indicator_icon(
                Gio.ThemedIcon.new("network-transmit-symbolic") if ativo else None
            )
            page.set_indicator_tooltip(
                "Recebe o que for digitado em qualquer aba" if ativo else ""
            )
            tab.set_broadcast_target(ativo)

    def reconnect_current(self) -> None:
        tab = self.current_tab()
        if tab is not None:
            tab.reconnect()

    # -------------------------------------------------------------------- eventos

    def _on_close_page(self, tab_view: Adw.TabView, page: Adw.TabPage) -> bool:
        child = page.get_child()
        if (
            isinstance(child, TerminalTab)
            and child.is_running
            and self._store.preferences.get_app("confirm_close_tab")
        ):
            self._confirmar_fechamento(page, child)
            return True  # a resposta do diálogo é que decide

        if isinstance(child, TerminalTab):
            child.close()
        tab_view.close_page_finish(page, True)
        return True

    def _confirmar_fechamento(self, page: Adw.TabPage, tab: TerminalTab) -> None:
        dialogo = Adw.AlertDialog(
            heading="Fechar a sessão?",
            body=f"“{tab.node.name}” ainda está conectada.",
        )
        dialogo.add_response("cancel", "Manter aberta")
        dialogo.add_response("close", "Fechar")
        dialogo.set_response_appearance("close", Adw.ResponseAppearance.DESTRUCTIVE)
        dialogo.set_default_response("cancel")
        dialogo.set_close_response("cancel")
        dialogo.connect("response", self._on_confirmacao, page, tab)
        dialogo.present(self)

    def _on_confirmacao(
        self, _d: Adw.AlertDialog, resposta: str, page: Adw.TabPage, tab: TerminalTab
    ) -> None:
        fechar = resposta == "close"
        if fechar:
            tab.close()
        self.tab_view.close_page_finish(page, fechar)

    def _on_session_exited(self, tab: TerminalTab, _status: int) -> None:
        page = self.tab_view.get_page(tab)
        if page is not None:
            page.set_title(f"{tab.node.name} (encerrada)")
        self._refresh_broadcast_marks()

    def _on_pages_changed(self, *_args: object) -> None:
        has_pages = self.tab_view.get_n_pages() > 0
        self._stack.set_visible_child_name("sessions" if has_pages else "welcome")
        self.tab_bar.set_visible(has_pages)


def _page_tooltip(node: Node, resolved: dict[str, object]) -> str:
    user, host = resolved.get("user"), resolved.get("host")
    destino = f"{user}@{host}" if user else str(host)
    return f"{node.name} — {destino}"
