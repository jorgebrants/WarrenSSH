# SPDX-License-Identifier: GPL-3.0-or-later
"""Editor de nó: cada campo com um interruptor 'herdar do pai'.

A promessa de UX do WarrenSSH mora aqui: quando a herança está ligada, o campo
fica desabilitado e mostra, em cinza, o valor efetivo que veio de cima. Zero
mistério sobre de onde cada valor está vindo.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk  # noqa: E402

from warrenssh.models.editing import (  # noqa: E402
    BOOL_FIELDS,
    CHOICE_FIELDS,
    FIELD_LABELS,
    EditingError,
    apply_edits,
    can_inherit,
    effective_placeholder,
    fields_for,
    format_value,
)
from warrenssh.models.resolver import resolve_source  # noqa: E402
from warrenssh.models.node import Node  # noqa: E402
from warrenssh.models.store import Store  # noqa: E402
from warrenssh import secrets  # noqa: E402

#: Marca "já existe um segredo guardado" sem exibir o segredo em si.
_SECRET_PLACEHOLDER = "\u2022" * 8

FIELD_HINTS: dict[str, str] = {
    "identity_file": "~/.ssh/id_ed25519",
    "proxy_jump": "usuario@bastion:22",
    "extra_ssh_args": "-o ConnectTimeout=5",
    "startup_command": "tmux attach",
}


class NodeEditor(Adw.Dialog):
    """Diálogo de criação/edição de um nó."""

    __gtype_name__ = "WarrenSSHNodeEditor"

    __gsignals__ = {
        # (node, is_new) — a janela grava no Store e recarrega a árvore.
        "saved": (GObject.SignalFlags.RUN_FIRST, None, (object, bool)),
    }

    def __init__(self, node: Node, store: Store, *, is_new: bool = False) -> None:
        super().__init__()
        self.node = node
        self.store = store
        self.is_new = is_new
        self._rows: dict[str, _FieldRow] = {}

        titulo = _dialog_title(node, is_new)
        self.set_title(titulo)
        self.set_content_width(560)
        self.set_content_height(680)

        header = Adw.HeaderBar(show_end_title_buttons=False)
        cancelar = Gtk.Button(label="Cancelar")
        cancelar.connect("clicked", lambda *_: self.close())
        salvar = Gtk.Button(label="Salvar")
        salvar.add_css_class("suggested-action")
        salvar.connect("clicked", self._on_save_clicked)
        header.pack_start(cancelar)
        header.pack_end(salvar)

        self._toasts = Adw.ToastOverlay(child=self._build_page())
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self._toasts)
        self.set_child(toolbar)

    # ------------------------------------------------------------------ montagem

    def _build_page(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()

        identificacao = Adw.PreferencesGroup(title="Identificação")
        self._name_row = Adw.EntryRow(title="Nome")
        self._name_row.set_text(self.node.name)
        identificacao.add(self._name_row)

        caminho = " › ".join(n.name for n in self.store.path_to(self.node)[:-1])
        if caminho:
            local = Adw.ActionRow(title="Dentro de", subtitle=caminho)
            local.add_css_class("property")
            identificacao.add(local)
        page.add(identificacao)

        grupo = Adw.PreferencesGroup(
            title="Conexão",
            description=(
                "O interruptor à direita faz o campo herdar do pai. "
                "Ligado, o campo mostra em cinza o valor que vem de cima."
            ),
        )
        for key in fields_for(self.node.kind):
            row = _FieldRow(self.node, key, self.store)
            self._rows[key] = row
            grupo.add(row.widget)
        page.add(grupo)

        if self.node.kind == "connection":
            page.add(self._build_secrets_group())
        return page

    def _build_secrets_group(self) -> Adw.PreferencesGroup:
        """Senha e passphrase vão para o chaveiro — nunca para o tree.json."""
        disponivel = secrets.is_available()
        grupo = Adw.PreferencesGroup(
            title="Segredos",
            description=(
                "Guardados no chaveiro do sistema (libsecret), fora do arquivo da árvore."
                if disponivel
                else "Nenhum chaveiro disponível nesta sessão — os campos estão desativados."
            ),
        )

        self._password_row = Adw.PasswordEntryRow(title="Senha")
        self._passphrase_row = Adw.PasswordEntryRow(title="Passphrase da chave")
        self._secret_rows = {
            secrets.KIND_PASSWORD: self._password_row,
            secrets.KIND_PASSPHRASE: self._passphrase_row,
        }

        for kind, row in self._secret_rows.items():
            row.set_sensitive(disponivel)
            if disponivel and secrets.has_password(self.node.id, kind=kind):
                # Não exibimos o segredo: mostramos que existe e deixamos trocar.
                row.set_text(_SECRET_PLACEHOLDER)
            grupo.add(row)

        self._secrets_available = disponivel
        return grupo

    def _save_secrets(self) -> None:
        if not getattr(self, "_secrets_available", False):
            return
        for kind, row in self._secret_rows.items():
            texto = row.get_text()
            if texto == _SECRET_PLACEHOLDER:
                continue  # inalterado
            try:
                secrets.store_password(
                    self.node.id, texto, kind=kind, label=f"WarrenSSH — {self.node.name}"
                )
            except secrets.SecretsError as exc:
                self._toasts.add_toast(Adw.Toast(title=str(exc), timeout=4))

    # -------------------------------------------------------------------- salvar

    def _on_save_clicked(self, *_args: object) -> None:
        edits = {key: row.local_value() for key, row in self._rows.items()}
        inherited = {key for key, row in self._rows.items() if row.is_inherited()}
        try:
            apply_edits(
                self.node, edits, inherited, self.store, name=self._name_row.get_text()
            )
        except EditingError as exc:
            self._toasts.add_toast(Adw.Toast(title=str(exc), timeout=4))
            return
        self._save_secrets()
        self.emit("saved", self.node, self.is_new)
        self.close()


class _FieldRow:
    """Uma linha do editor: widget de valor + interruptor de herança."""

    def __init__(self, node: Node, key: str, store: Store) -> None:
        self.node = node
        self.key = key
        self.store = store
        self.label = FIELD_LABELS.get(key, key)

        # Rascunho local: preservado enquanto o campo estiver herdando.
        self._draft = format_value(key, node.properties.get(key))
        self._draft_bool = bool(node.properties.get(key))
        self._had_value = key in node.properties
        self._touched = False
        self._syncing = False

        self.widget = self._build_row()
        self.switch: Gtk.Switch | None = None

        if can_inherit(node, key, store):
            self.switch = Gtk.Switch(
                valign=Gtk.Align.CENTER,
                tooltip_text=f"Herdar {self.label.lower()} do pai",
                active=key in node.inherited,
            )
            self.switch.connect("notify::active", self._on_inherit_toggled)
            self.widget.add_suffix(self.switch)

        self._sync()

    # ------------------------------------------------------------------ widgets

    def _build_row(self) -> Adw.PreferencesRow:
        if self.key in BOOL_FIELDS:
            row = Adw.ActionRow(title=self.label)
            self._check = Gtk.CheckButton(valign=Gtk.Align.CENTER, active=self._draft_bool)
            self._check.connect("toggled", self._on_user_changed)
            row.add_suffix(self._check)
            row.set_activatable_widget(self._check)
            return row

        if self.key in CHOICE_FIELDS:
            options = CHOICE_FIELDS[self.key]
            row = Adw.ComboRow(title=self.label, model=Gtk.StringList.new(list(options)))
            current = self.node.properties.get(self.key)
            row.set_selected(options.index(current) if current in options else 0)
            row.connect("notify::selected", self._on_user_changed)
            self._combo = row
            return row

        row = Adw.EntryRow(title=self.label)
        row.set_text(self._draft)
        hint = FIELD_HINTS.get(self.key)
        if hint:
            row.set_tooltip_text(f"Ex.: {hint}")
        self._entry = row
        return row

    # ------------------------------------------------------------------- estado

    def _on_user_changed(self, *_args: object) -> None:
        """Distingue 'o usuário mexeu' de 'a UI se sincronizou sozinha'."""
        if not self._syncing:
            self._touched = True

    def is_inherited(self) -> bool:
        return self.switch is not None and self.switch.get_active()

    def local_value(self) -> Any:
        """O valor local do campo — o rascunho, quando a herança está ligada.

        Campos de escolha e booleanos sempre têm um estado no widget; gravá-lo
        sem o usuário ter mexido encheria o JSON de valores locais falsos. Por
        isso só devolvem valor se já tinham um ou se foram tocados.
        """
        if self.key in BOOL_FIELDS:
            if not (self._had_value or self._touched):
                return None
            return self._draft_bool if self.is_inherited() else self._check.get_active()

        if self.key in CHOICE_FIELDS:
            if not (self._had_value or self._touched):
                return None
            if self.is_inherited():
                return self._draft or None
            selected = self._combo.get_selected_item()
            return selected.get_string() if selected is not None else None

        return self._draft if self.is_inherited() else self._entry.get_text()

    def _on_inherit_toggled(self, *_args: object) -> None:
        if self.is_inherited():
            # Guarda o que o usuário tinha digitado antes de mostrar o valor do pai.
            if self.key in BOOL_FIELDS:
                self._draft_bool = self._check.get_active()
            elif self.key in CHOICE_FIELDS:
                item = self._combo.get_selected_item()
                self._draft = item.get_string() if item is not None else ""
            else:
                self._draft = self._entry.get_text()
        self._sync()

    def _sync(self) -> None:
        """Reflete o estado da herança no widget de valor."""
        self._syncing = True
        try:
            self._sync_widgets()
        finally:
            self._syncing = False

    def _sync_widgets(self) -> None:
        inherited = self.is_inherited()
        herdado = effective_placeholder(self.node, self.key, self.store)

        if self.switch is not None:
            self.switch.set_tooltip_text(self._inherit_tooltip(inherited))

        if self.key in BOOL_FIELDS:
            self._check.set_sensitive(not inherited)
            self._check.set_active(herdado == "sim" if inherited else self._draft_bool)
            self.widget.set_subtitle(f"Herdado do pai: {herdado or '—'}" if inherited else "")
            _dim(self._check, inherited)
            return

        if self.key in CHOICE_FIELDS:
            self._combo.set_sensitive(not inherited)
            options = CHOICE_FIELDS[self.key]
            alvo = herdado if inherited else self._draft
            self._combo.set_selected(options.index(alvo) if alvo in options else 0)
            self._combo.set_subtitle(f"Herdado do pai: {herdado or '—'}" if inherited else "")
            _dim(self._combo, inherited)
            return

        self._entry.set_editable(not inherited)
        self._entry.set_text(herdado if inherited else self._draft)
        _dim(self._entry, inherited)


    def _inherit_tooltip(self, inherited: bool) -> str:
        """Diz de qual nó o valor está vindo — a herança deixa de ser mistério."""
        if not inherited:
            return f"Herdar {self.label.lower()} do pai"
        parent = self.store.get(self.node.parent_id)
        origem = resolve_source(parent, self.key, self.store) if parent else None
        if origem is None:
            return "Herdando, mas nenhum ancestral define este campo"
        return f"Herdado de “{origem.name}”"


def _dim(widget: Gtk.Widget, dim: bool) -> None:
    """Acinzenta o valor herdado — a pista visual de 'isso não é seu'."""
    if dim:
        widget.add_css_class("dim-label")
    else:
        widget.remove_css_class("dim-label")


def _dialog_title(node: Node, is_new: bool) -> str:
    tipo = "pasta" if node.kind == "folder" else "conexão"
    return f"Nova {tipo}" if is_new else f"Editar {tipo}"
