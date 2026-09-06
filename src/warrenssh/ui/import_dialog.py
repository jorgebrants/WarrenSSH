# SPDX-License-Identifier: GPL-3.0-or-later
"""Preview do import do ~/.ssh/config: mostra o que vai entrar antes de aplicar."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk  # noqa: E402

from warrenssh.models.store import Store  # noqa: E402
from warrenssh.ssh.config_import import (  # noqa: E402
    ImportedHost,
    display_config_path,
    import_into,
    parse_config_file,
)


class ImportDialog(Adw.Dialog):
    """Lista os hosts encontrados e deixa escolher quais importar."""

    __gtype_name__ = "WarrenSSHImportDialog"

    __gsignals__ = {
        # (quantidade importada) — a janela persiste e recarrega a árvore.
        "imported": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.store = store
        self.hosts: list[ImportedHost] = parse_config_file()
        self._checks: dict[str, Gtk.CheckButton] = {}

        self.set_title("Importar do ~/.ssh/config")
        self.set_content_width(560)
        self.set_content_height(620)

        header = Adw.HeaderBar(show_end_title_buttons=False)
        cancelar = Gtk.Button(label="Cancelar")
        cancelar.connect("clicked", lambda *_: self.close())
        header.pack_start(cancelar)

        self._import_button = Gtk.Button(label="Importar")
        self._import_button.add_css_class("suggested-action")
        self._import_button.connect("clicked", self._on_import_clicked)
        self._import_button.set_sensitive(bool(self.hosts))
        header.pack_end(self._import_button)

        self._toasts = Adw.ToastOverlay(child=self._build_body())
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._toasts)
        self.set_child(toolbar)
        self._update_button()

    # ------------------------------------------------------------------ montagem

    def _build_body(self) -> Gtk.Widget:
        if not self.hosts:
            return Adw.StatusPage(
                icon_name="dialog-information-symbolic",
                title="Nada para importar",
                description=(
                    f"Não encontrei hosts em {display_config_path()}.\n"
                    "Padrões com curinga (Host *) não viram conexões."
                ),
            )

        page = Adw.PreferencesPage()
        ja_existem = self._existing_names()
        novos = [h for h in self.hosts if h.name not in ja_existem]

        grupo = Adw.PreferencesGroup(
            title=f"{len(self.hosts)} host(s) em {display_config_path()}",
            description=(
                f"{len(novos)} ainda não estão na árvore. "
                "Os já importados vêm desmarcados."
            ),
        )

        marcar_todos = Gtk.Button(label="Inverter seleção", valign=Gtk.Align.CENTER)
        marcar_todos.connect("clicked", self._on_toggle_all)
        grupo.set_header_suffix(marcar_todos)

        for host in self.hosts:
            existe = host.name in ja_existem
            row = Adw.ActionRow(
                title=host.name,
                subtitle=host.summary() + (" — já importado" if existe else ""),
            )
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=not existe)
            check.connect("toggled", lambda *_: self._update_button())
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self._checks[host.name] = check
            grupo.add(row)

        page.add(grupo)
        return page

    def _existing_names(self) -> set[str]:
        from warrenssh.ssh.config_import import IMPORT_FOLDER_NAME

        folder = next(
            (n for n in self.store.roots() if n.kind == "folder" and n.name == IMPORT_FOLDER_NAME),
            None,
        )
        if folder is None:
            return set()
        return {child.name for child in self.store.children(folder.id)}

    # -------------------------------------------------------------------- ações

    def selected_hosts(self) -> list[ImportedHost]:
        return [h for h in self.hosts if self._checks[h.name].get_active()]

    def _on_toggle_all(self, *_args: object) -> None:
        for check in self._checks.values():
            check.set_active(not check.get_active())

    def _update_button(self) -> None:
        if not self.hosts:
            return
        quantidade = len(self.selected_hosts())
        self._import_button.set_label(
            f"Importar {quantidade}" if quantidade else "Importar"
        )
        self._import_button.set_sensitive(quantidade > 0)

    def _on_import_clicked(self, *_args: object) -> None:
        escolhidos = self.selected_hosts()
        if not escolhidos:
            return
        _folder, criados, _pulados = import_into(self.store, escolhidos)
        self.emit("imported", len(criados))
        self.close()
