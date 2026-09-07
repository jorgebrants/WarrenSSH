# SPDX-License-Identifier: GPL-3.0-or-later
"""Janela principal: sidebar da árvore + área de sessões."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

from warrenssh.models.editing import new_child_defaults  # noqa: E402
from warrenssh.models.node import Node, new_node  # noqa: E402
from warrenssh.models.sample import populate_example  # noqa: E402
from warrenssh.models.store import Store, StoreError  # noqa: E402
from warrenssh import secrets  # noqa: E402
from warrenssh.ui.editor import NodeEditor  # noqa: E402
from warrenssh.ui.import_dialog import ImportDialog  # noqa: E402
from warrenssh.ui.mremoteng_dialog import MRemoteNGDialog  # noqa: E402
from warrenssh.ui.preferences import PreferencesDialog  # noqa: E402
from warrenssh.ui.session_view import SessionView  # noqa: E402
from warrenssh.ui.sidebar import Sidebar  # noqa: E402

#: Atalhos de teclado da janela.
ACCELS: dict[str, list[str]] = {
    "win.reconnect-tab": ["<Primary><Shift>t"],
    "win.close-tab": ["<Primary>w"],
    "win.focus-search": ["<Primary>k"],
    "win.toggle-broadcast": ["<Primary><Shift>Return"],
    "win.new-connection": ["<Primary>n"],
    "win.new-folder": ["<Primary><Shift>n"],
    "win.preferences": ["<Primary>comma"],
    "win.toggle-theme": ["<Primary><Shift>b"],
    "win.duplicate-node": ["<Primary>d"],
    "win.move-up": ["<Primary><Shift>Up"],
    "win.move-down": ["<Primary><Shift>Down"],
}


class WarrenSSHWindow(Adw.ApplicationWindow):
    """Adw.OverlaySplitView: conexões à esquerda, sessões à direita."""

    def __init__(self, store: Store | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.set_title("WarrenSSH")
        self.set_default_size(1100, 700)

        self.store = store if store is not None else _load_store()
        self._toasts = Adw.ToastOverlay()

        self._editor: NodeEditor | None = None
        self._import_dialog: ImportDialog | None = None
        self._prefs_dialog: PreferencesDialog | None = None
        self._mremoteng_dialog: MRemoteNGDialog | None = None
        self._sidebar = Sidebar(self.store)
        self._sidebar.connect("connection-activated", self._on_connection_activated)
        self._sidebar.connect("tree-changed", lambda *_: self._persist())

        self._sessions = SessionView(self.store)
        self._sessions.connect("session-error", lambda _v, msg: self.toast(msg))
        self._sessions.connect("broadcast-changed", self._on_broadcast_changed)
        self._sessions.connect("sessions-changed", self._on_sessions_changed)

        self._split_view = Adw.OverlaySplitView(
            sidebar_width_fraction=0.25,
            min_sidebar_width=220,
            max_sidebar_width=420,
        )
        self._split_view.set_sidebar(self._build_sidebar())
        self._split_view.set_content(self._build_content())

        self._toasts.set_child(self._split_view)
        self.set_content(self._toasts)
        self._setup_actions()
        self._apply_preferences()
        self.connect("close-request", self._on_close_request)
        # Em "seguir o sistema", o tema muda sem passar por nós: o ícone do
        # botão precisa acompanhar (ex.: agendamento noturno do GNOME).
        Adw.StyleManager.get_default().connect(
            "notify::dark", lambda *_: self._update_theme_button()
        )

    # ------------------------------------------------------------------ montagem

    def _build_sidebar(self) -> Gtk.Widget:
        header = Adw.HeaderBar(show_end_title_buttons=False)
        header.set_title_widget(Adw.WindowTitle(title="Conexões"))

        criar = Gio.Menu()
        criar.append("Nova pasta", "win.new-folder")
        criar.append("Nova conexão", "win.new-connection")
        header.pack_end(
            Gtk.MenuButton(
                icon_name="list-add-symbolic",
                tooltip_text="Adicionar",
                menu_model=criar,
            )
        )

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._sidebar)
        toolbar.add_css_class("warrenssh-sidebar")
        return toolbar

    def _build_content(self) -> Gtk.Widget:
        header = Adw.HeaderBar(show_start_title_buttons=False)
        header.set_title_widget(Adw.WindowTitle(title="WarrenSSH"))

        sidebar_button = Gtk.ToggleButton(
            icon_name="sidebar-show-symbolic",
            tooltip_text="Mostrar/ocultar conexões",
        )
        self._split_view.bind_property(
            "show-sidebar",
            sidebar_button,
            "active",
            GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE,
        )
        header.pack_start(sidebar_button)

        self._broadcast_button = Gtk.ToggleButton(
            icon_name="network-transmit-symbolic",
            tooltip_text="Enviar o que for digitado para todas as abas (Ctrl+Shift+Enter)",
        )
        self._broadcast_button.connect("toggled", self._on_broadcast_button_toggled)
        header.pack_start(self._broadcast_button)

        self._theme_button = Gtk.Button()
        self._theme_button.connect("clicked", lambda *_: self._toggle_theme())
        header.pack_end(self._theme_button)

        menu = Gio.Menu()
        arvore = Gio.Menu()
        arvore.append("Importar do ~/.ssh/config", "win.import-ssh-config")
        arvore.append("Importar do mRemoteNG…", "win.import-mremoteng")
        arvore.append("Importar árvore…", "win.import-tree")
        arvore.append("Exportar árvore…", "win.export-tree")
        menu.append_section(None, arvore)

        resto = Gio.Menu()
        resto.append("Preferências", "win.preferences")
        resto.append("Sair", "app.quit")
        menu.append_section(None, resto)
        header.pack_end(
            Gtk.MenuButton(
                icon_name="open-menu-symbolic", tooltip_text="Menu", menu_model=menu
            )
        )

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._sessions)
        return toolbar

    # -------------------------------------------------------------------- ações

    def _on_broadcast_button_toggled(self, button: Gtk.ToggleButton) -> None:
        if button.get_active() != self._sessions.broadcast:
            self._toggle_broadcast()

    def toast(self, message: str) -> None:
        """Feedback visual — erros nunca viram crash silencioso."""
        self._toasts.add_toast(Adw.Toast(title=message, timeout=3))

    def _on_connection_activated(self, _sidebar: Sidebar, node: Node) -> None:
        self._sessions.open_session(node)

    # ------------------------------------------------------------ ações da árvore

    def _setup_actions(self) -> None:
        for name, handler in (
            ("new-folder", lambda *_: self._create_node("folder")),
            ("new-connection", lambda *_: self._create_node("connection")),
            ("edit-node", lambda *_: self._edit_selected()),
            ("delete-node", lambda *_: self._delete_selected()),
            ("import-ssh-config", lambda *_: self._import_ssh_config()),
            ("preferences", lambda *_: self._open_preferences()),
            ("toggle-theme", lambda *_: self._toggle_theme()),
            ("duplicate-node", lambda *_: self._duplicate_selected()),
            ("move-up", lambda *_: self._sidebar.move_selected(-1)),
            ("move-down", lambda *_: self._sidebar.move_selected(+1)),
            ("export-tree", lambda *_: self._export_tree()),
            ("import-tree", lambda *_: self._import_tree()),
            ("import-mremoteng", lambda *_: self._import_mremoteng()),
            ("reconnect-tab", lambda *_: self._sessions.reconnect_current()),
            ("close-tab", lambda *_: self._sessions.close_current()),
            ("focus-search", lambda *_: self._sidebar.focus_search()),
            ("toggle-broadcast", lambda *_: self._toggle_broadcast()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

        app = self.get_application()
        if app is not None:
            for nome, atalhos in ACCELS.items():
                app.set_accels_for_action(nome, atalhos)

    def _target_parent(self) -> Node | None:
        """Onde um nó novo deve nascer: dentro da pasta selecionada, ou ao lado."""
        selected = self._sidebar.selected_node()
        if selected is None:
            return None
        if selected.kind == "folder":
            return selected
        return self.store.get(selected.parent_id)

    def _create_node(self, kind: str) -> None:
        parent = self._target_parent()
        node = new_node(
            kind,
            "Nova pasta" if kind == "folder" else "Nova conexão",
            parent_id=parent.id if parent else None,
            inherited=new_child_defaults(parent, kind),
        )
        self._open_editor(node, is_new=True)

    def _edit_selected(self) -> None:
        node = self._sidebar.selected_node()
        if node is None:
            self.toast("Selecione um item na árvore para editar.")
            return
        self._open_editor(node, is_new=False)

    def _open_editor(self, node: Node, *, is_new: bool) -> None:
        # A referência precisa viver enquanto o diálogo estiver aberto: sem ela o
        # wrapper Python é coletado e o diálogo some antes de aparecer.
        self._editor = NodeEditor(node, self.store, is_new=is_new)
        self._editor.connect("saved", self._on_node_saved)
        self._editor.connect("closed", self._on_editor_closed)
        self._editor.present(self)

    def _on_editor_closed(self, *_args: object) -> None:
        self._editor = None

    def _on_node_saved(self, _editor: NodeEditor, node: Node, is_new: bool) -> None:
        if is_new:
            self.store.add(node)
        self._persist()
        self._sidebar.reload()
        self._sidebar.select_node_id(node.id)
        self.toast(f"“{node.name}” salvo.")

    def _toggle_broadcast(self) -> None:
        ligado = self._sessions.toggle_broadcast()
        self._broadcast_button.set_active(ligado)
        self.toast(
            "Broadcast ligado: o que você digitar vai para todas as abas."
            if ligado
            else "Broadcast desligado."
        )

    def _on_broadcast_changed(self, _view: SessionView, ligado: bool) -> None:
        self._broadcast_button.set_active(ligado)
        # Ligado, o botão assume o acento: o estado precisa saltar aos olhos.
        if ligado:
            self._broadcast_button.add_css_class("suggested-action")
        else:
            self._broadcast_button.remove_css_class("suggested-action")

    def _on_close_request(self, *_args: object) -> bool:
        """Confirma antes de fechar a janela com sessões vivas."""
        vivas = [t for t in self._sessions.terminal_tabs() if t.is_running]
        if not vivas or not self.store.preferences.get_app("confirm_quit"):
            return False  # segue o fechamento

        nomes = ", ".join(f"“{t.node.name}”" for t in vivas[:3])
        resto = f" e mais {len(vivas) - 3}" if len(vivas) > 3 else ""
        dialogo = Adw.AlertDialog(
            heading="Sair com sessões abertas?",
            body=f"{len(vivas)} sessão(ões) ainda conectada(s): {nomes}{resto}.",
        )
        dialogo.add_response("cancel", "Continuar aqui")
        dialogo.add_response("quit", "Sair")
        dialogo.set_response_appearance("quit", Adw.ResponseAppearance.DESTRUCTIVE)
        dialogo.set_default_response("cancel")
        dialogo.set_close_response("cancel")
        dialogo.connect("response", self._on_quit_response)
        dialogo.present(self)
        return True  # segura o fechamento até a resposta

    def _on_quit_response(self, _d: Adw.AlertDialog, resposta: str) -> None:
        if resposta != "quit":
            return
        for tab in self._sessions.terminal_tabs():
            tab.close()
        self.destroy()

    def _toggle_theme(self) -> None:
        """Alterna claro/escuro pelo botão do canto superior direito.

        Vale também quando a preferência está em "seguir o sistema": neste caso
        assumimos o oposto do tema que está valendo agora, e a escolha passa a
        ser explícita (o menu de Preferências devolve o automático).
        """
        escuro_agora = Adw.StyleManager.get_default().get_dark()
        self.store.preferences.set_app("theme", "light" if escuro_agora else "dark")
        try:
            self.store.preferences.save_json()
        except OSError as exc:
            self.toast(f"Não deu para salvar a preferência: {exc}")
        self._apply_preferences()

    def _update_theme_button(self) -> None:
        """O ícone mostra o tema para o qual o clique leva, não o atual."""
        if not hasattr(self, "_theme_button"):
            return
        escolha = str(self.store.preferences.get_app("theme"))
        escuro = Adw.StyleManager.get_default().get_dark()
        vai_para_escuro = not escuro

        self._theme_button.set_icon_name(
            "weather-clear-night-symbolic" if vai_para_escuro else "weather-clear-symbolic"
        )
        alvo = "escuro" if vai_para_escuro else "claro"
        seguindo = " (agora seguindo o sistema)" if escolha == "system" else ""
        self._theme_button.set_tooltip_text(
            f"Mudar para o tema {alvo}{seguindo} — Ctrl+Shift+B"
        )

    def _on_sessions_changed(self, *_args: object) -> None:
        """Acende na árvore as conexões que estão abertas."""
        self._sidebar.set_active_nodes(
            {t.node.id for t in self._sessions.terminal_tabs() if t.is_running}
        )

    def _duplicate_selected(self) -> None:
        node = self._sidebar.selected_node()
        if node is None:
            self.toast("Selecione um item para duplicar.")
            return
        copia = self.store.duplicate(node.id)
        if copia is None:
            return
        self._persist()
        self._sidebar.reload()
        self._sidebar.select_node_id(copia.id)
        self.toast(f"“{copia.name}” criado.")

    # ------------------------------------------------------ exportar/importar

    def _export_tree(self) -> None:
        dialogo = Gtk.FileDialog(
            title="Exportar árvore",
            initial_name="warrenssh-arvore.json",
        )
        dialogo.save(self, None, self._on_export_escolhido)

    def _on_export_escolhido(self, dialogo: Gtk.FileDialog, resultado: object) -> None:
        try:
            arquivo = dialogo.save_finish(resultado)
        except GLib.Error:
            return  # cancelado
        if arquivo is None or arquivo.get_path() is None:
            return
        try:
            self.store.export_json(arquivo.get_path())
        except OSError as exc:
            self.toast(f"Não deu para exportar: {exc}")
            return
        self.toast("Árvore exportada. As senhas continuam só no chaveiro.")

    def _import_tree(self) -> None:
        dialogo = Gtk.FileDialog(title="Importar árvore")
        dialogo.open(self, None, self._on_import_escolhido)

    def _on_import_escolhido(self, dialogo: Gtk.FileDialog, resultado: object) -> None:
        try:
            arquivo = dialogo.open_finish(resultado)
        except GLib.Error:
            return
        if arquivo is None or arquivo.get_path() is None:
            return
        try:
            importados = self.store.import_json(arquivo.get_path())
        except StoreError as exc:
            self.toast(str(exc))
            return
        self._persist()
        self._sidebar.reload()
        self.toast(f"{len(importados)} item(ns) importado(s).")

    def _import_mremoteng(self) -> None:
        filtro = Gtk.FileFilter(name="confCons.xml do mRemoteNG")
        filtro.add_pattern("*.xml")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(filtro)

        dialogo = Gtk.FileDialog(title="Importar do mRemoteNG", filters=filtros)
        dialogo.open(self, None, self._on_mremoteng_escolhido)

    def _on_mremoteng_escolhido(self, dialogo: Gtk.FileDialog, resultado: object) -> None:
        from warrenssh.ssh.mremoteng import MRemoteNGError, apply_inheritance, parse_file

        try:
            arquivo = dialogo.open_finish(resultado)
        except GLib.Error:
            return
        if arquivo is None or arquivo.get_path() is None:
            return

        caminho = arquivo.get_path()
        try:
            lido = apply_inheritance(parse_file(caminho))
        except MRemoteNGError as exc:
            self.toast(str(exc))
            return

        self._mremoteng_dialog = MRemoteNGDialog(self.store, caminho, lido)
        self._mremoteng_dialog.connect("imported", self._on_mremoteng_importado)
        self._mremoteng_dialog.connect(
            "closed", lambda *_: setattr(self, "_mremoteng_dialog", None)
        )
        self._mremoteng_dialog.present(self)

    def _on_mremoteng_importado(self, _dialogo: object, quantos: int) -> None:
        self._persist()
        self._sidebar.reload()
        self.toast(f"{quantos} item(ns) importado(s) do mRemoteNG.")

    def _open_preferences(self) -> None:
        self._prefs_dialog = PreferencesDialog(self.store.preferences)
        self._prefs_dialog.connect("changed", lambda *_: self._apply_preferences())
        self._prefs_dialog.connect("closed", self._on_prefs_closed)
        self._prefs_dialog.present(self)

    def _on_prefs_closed(self, *_args: object) -> None:
        self._prefs_dialog = None

    def _apply_preferences(self) -> None:
        """Reflete na hora o que mudou: tema, clique da árvore e sessões abertas."""
        prefs = self.store.preferences

        escolha = {
            "light": Adw.ColorScheme.FORCE_LIGHT,
            "dark": Adw.ColorScheme.FORCE_DARK,
        }.get(str(prefs.get_app("theme")), Adw.ColorScheme.DEFAULT)
        Adw.StyleManager.get_default().set_color_scheme(escolha)

        self._sidebar.set_single_click(bool(prefs.get_app("activate_on_single_click")))
        self._sessions.refresh_appearance()
        self._update_theme_button()

    def _import_ssh_config(self) -> None:
        self._import_dialog = ImportDialog(self.store)
        self._import_dialog.connect("imported", self._on_imported)
        self._import_dialog.connect("closed", self._on_import_closed)
        self._import_dialog.present(self)

    def _on_import_closed(self, *_args: object) -> None:
        self._import_dialog = None

    def _on_imported(self, _dialog: ImportDialog, quantidade: int) -> None:
        self._persist()
        self._sidebar.reload()
        self.toast(f"{quantidade} conexão(ões) importada(s).")

    def _delete_selected(self) -> None:
        node = self._sidebar.selected_node()
        if node is None:
            self.toast("Selecione um item na árvore para excluir.")
            return

        filhos = len(self.store.descendants(node.id))
        detalhe = (
            f"“{node.name}” e {filhos} item(ns) dentro dela serão removidos."
            if filhos
            else f"“{node.name}” será removido."
        )
        dialog = Adw.AlertDialog(heading="Excluir?", body=detalhe)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("delete", "Excluir")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_response, node)
        dialog.present(self)

    def _on_delete_response(self, _dialog: Adw.AlertDialog, response: str, node: Node) -> None:
        if response != "delete":
            return
        removidos = self.store.remove(node.id)
        for removido in removidos:
            secrets.delete_all(removido.id)
        self._persist()
        self._sidebar.reload()
        self.toast(f"“{node.name}” excluído.")

    def _persist(self) -> None:
        """Grava a árvore; falha de disco vira toast, nunca crash silencioso."""
        try:
            self.store.save_json()
        except OSError as exc:
            self.toast(f"Não deu para salvar a árvore: {exc}")


def _load_store() -> Store:
    """Carrega a árvore do disco; na primeira execução, mostra um exemplo."""
    store = Store()
    store.load_json()
    if len(store) == 0:
        populate_example(store)
    return store
