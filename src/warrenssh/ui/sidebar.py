# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar: a árvore de conexões no idioma moderno do GTK4.

Gtk.TreeListModel + Gtk.ListView + Gtk.TreeExpander. Nada de Gtk.TreeView.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, Gio, GObject, Graphene, Gtk, Pango  # noqa: E402

from warrenssh.models.node import Node  # noqa: E402
from warrenssh.models.search import normalize, row_matches  # noqa: E402
from warrenssh.models.store import Store  # noqa: E402

FOLDER_ICON = "folder-symbolic"
CONNECTION_ICON = "network-server-symbolic"


class NodeObject(GObject.Object):
    """Casca GObject em volta do Node — o Gio.ListStore só aceita GObjects."""

    __gtype_name__ = "WarrenSSHNodeObject"

    def __init__(self, node: Node) -> None:
        super().__init__()
        self.node = node

    @GObject.Property(type=str)
    def name(self) -> str:  # usado pela busca da Fase 6
        return self.node.name


class Sidebar(Gtk.Box):
    """Árvore de pastas e conexões ligada a um Store."""

    __gtype_name__ = "WarrenSSHSidebar"

    __gsignals__ = {
        # Emitido no double-click/Enter sobre uma conexão.
        "connection-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # Emitido quando a seleção muda (None quando nada está selecionado).
        "node-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self, store: Store) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._store = store
        self._root_model = Gio.ListStore(item_type=NodeObject)

        self._tree_model = Gtk.TreeListModel.new(
            self._root_model,
            False,  # passthrough: queremos os TreeListRow
            False,  # autoexpand
            self._create_children_model,
        )
        self._search_text = ""
        self._filter = Gtk.CustomFilter.new(self._match_row)
        self._filter_model = Gtk.FilterListModel(model=self._tree_model, filter=self._filter)
        self._selection = Gtk.SingleSelection(model=self._filter_model, autoselect=False)
        self._selection.connect("selection-changed", self._on_selection_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)

        self._list_view = Gtk.ListView(model=self._selection, factory=factory)
        self._list_view.add_css_class("navigation-sidebar")
        self._list_view.connect("activate", self._on_row_activated)

        self._menu = Gio.Menu()
        criar = Gio.Menu()
        criar.append("Nova pasta", "win.new-folder")
        criar.append("Nova conexão", "win.new-connection")
        self._menu.append_section(None, criar)
        editar = Gio.Menu()
        editar.append("Editar…", "win.edit-node")
        editar.append("Excluir", "win.delete-node")
        self._menu.append_section(None, editar)

        self._popover = Gtk.PopoverMenu.new_from_model(self._menu)
        self._popover.set_parent(self._list_view)
        self._popover.set_has_arrow(False)
        self._popover.set_halign(Gtk.Align.START)

        self.search_entry = Gtk.SearchEntry(
            placeholder_text="Buscar por nome ou host",
            margin_start=6,
            margin_end=6,
            margin_top=6,
            margin_bottom=6,
        )
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("stop-search", lambda entry: entry.set_text(""))
        self.append(self.search_entry)

        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True,
            child=self._list_view,
        )
        self.append(scroller)

        self.reload()

    # ------------------------------------------------------------------ modelo

    @property
    def store(self) -> Store:
        return self._store

    def reload(self) -> None:
        """Reconstrói o modelo a partir do Store, preservando a seleção se possível."""
        selected = self.selected_node()
        self._root_model.remove_all()
        for node in self._store.roots():
            self._root_model.append(NodeObject(node))
        self.expand_roots()
        if selected is not None:
            self.select_node_id(selected.id)

    def set_search_text(self, text: str) -> None:
        """Filtra a árvore por nome ou host. Vazio volta ao estado normal."""
        text = normalize(text)
        if text == self._search_text:
            return
        buscando_antes = bool(self._search_text)
        self._search_text = text

        # Filtrar só alcança linhas que existem no modelo: durante a busca a
        # árvore fica toda expandida, e ao limpar volta ao estado de sempre.
        self._tree_model.set_autoexpand(bool(text))
        if text:
            self._expand_all()
        elif buscando_antes:
            self._collapse_all()
            self.expand_roots()

        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self.set_search_text(entry.get_text())

    def focus_search(self) -> None:
        self.search_entry.grab_focus()

    def _match_row(self, row: object) -> bool:
        return row_matches(row.get_item().node, self._store, self._search_text)

    def _expand_all(self) -> None:
        # Expandir cria linhas novas, então percorre até estabilizar.
        while True:
            mudou = False
            for position in range(self._tree_model.get_n_items()):
                row = self._tree_model.get_item(position)
                if row is not None and row.is_expandable() and not row.get_expanded():
                    row.set_expanded(True)
                    mudou = True
            if not mudou:
                return

    def _collapse_all(self) -> None:
        for position in reversed(range(self._tree_model.get_n_items())):
            row = self._tree_model.get_item(position)
            if row is not None and row.get_expanded():
                row.set_expanded(False)

    def set_single_click(self, ativo: bool) -> None:
        """Um clique conecta, em vez de dois."""
        self._list_view.set_single_click_activate(ativo)

    def expand_roots(self) -> None:
        """Deixa as pastas de primeiro nível abertas — a árvore nasce legível."""
        for position in range(self._root_model.get_n_items()):
            row = self._tree_model.get_item(position)
            if row is not None and row.is_expandable():
                row.set_expanded(True)

    def _create_children_model(self, item: GObject.Object) -> Gio.ListModel | None:
        """Filhos de um nó — None sinaliza folha (conexões nunca expandem)."""
        node = item.node  # type: ignore[attr-defined]
        if node.kind != "folder":
            return None
        children = self._store.children(node.id)
        if not children:
            return None
        model = Gio.ListStore(item_type=NodeObject)
        for child in children:
            model.append(NodeObject(child))
        return model

    # -------------------------------------------------------------------- linhas

    def _on_factory_setup(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        icon = Gtk.Image()
        label = Gtk.Label(xalign=0.0, ellipsize=Pango.EllipsizeMode.END)
        box.append(icon)
        box.append(label)

        expander = Gtk.TreeExpander(child=box)
        item.set_child(expander)

        # Botão secundário abre o menu de contexto da linha sob o cursor.
        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_row_secondary_click, item)
        expander.add_controller(gesture)

    def _on_factory_bind(self, _factory: Gtk.SignalListItemFactory, item: Gtk.ListItem) -> None:
        expander = item.get_child()
        row = item.get_item()  # Gtk.TreeListRow
        expander.set_list_row(row)

        node = row.get_item().node
        box = expander.get_child()
        icon, label = box.get_first_child(), box.get_last_child()
        icon.set_from_icon_name(FOLDER_ICON if node.kind == "folder" else CONNECTION_ICON)
        label.set_text(node.name)
        label.set_tooltip_text(_row_tooltip(node))

    # -------------------------------------------------------------------- eventos

    def _on_row_activated(self, _list_view: Gtk.ListView, position: int) -> None:
        row = self._filter_model.get_item(position)
        if row is None:
            return
        node = row.get_item().node
        if node.kind == "folder":
            row.set_expanded(not row.get_expanded())
            return
        self.emit("connection-activated", node)

    def _on_row_secondary_click(
        self,
        gesture: Gtk.GestureClick,
        _n_press: int,
        x: float,
        y: float,
        item: Gtk.ListItem,
    ) -> None:
        position = item.get_position()
        if position != Gtk.INVALID_LIST_POSITION:
            self._selection.set_selected(position)

        widget = gesture.get_widget()
        ok, point = widget.compute_point(self._list_view, Graphene.Point().init(x, y))
        rect = Gdk.Rectangle()
        rect.x, rect.y = (int(point.x), int(point.y)) if ok else (0, 0)
        rect.width = rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _on_selection_changed(self, *_args: object) -> None:
        self.emit("node-selected", self.selected_node())

    # -------------------------------------------------------------------- seleção

    def selected_node(self) -> Node | None:
        row = self._selection.get_selected_item()
        if row is None:
            return None
        return row.get_item().node

    def select_node_id(self, node_id: str) -> bool:
        """Seleciona um nó já visível na lista. Devolve se conseguiu."""
        for position in range(self._filter_model.get_n_items()):
            row = self._filter_model.get_item(position)
            if row.get_item().node.id == node_id:
                self._selection.set_selected(position)
                return True
        return False


def _row_tooltip(node: Node) -> str | None:
    if node.kind == "folder":
        return None
    host = node.properties.get("host")
    return f"{node.name} — {host}" if host else node.name
