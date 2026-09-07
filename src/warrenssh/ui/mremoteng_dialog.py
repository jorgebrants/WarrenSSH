# SPDX-License-Identifier: GPL-3.0-or-later
"""Prévia do import do mRemoteNG: mostra o que vem antes de mexer na árvore."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GObject, Gtk  # noqa: E402

from warrenssh.models.store import Store  # noqa: E402
from warrenssh.ssh.mremoteng import (  # noqa: E402
    ImportResult,
    apply_inheritance,
    import_into,
    parse_file,
)


class MRemoteNGDialog(Adw.Dialog):
    """Confirma o import e deixa escolher se a herança será aproveitada."""

    __gtype_name__ = "WarrenSSHMRemoteNGDialog"

    __gsignals__ = {
        # (quantidade de nós criados)
        "imported": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, store: Store, caminho: str, resultado: ImportResult) -> None:
        super().__init__()
        self.store = store
        self.caminho = caminho
        self.resultado = resultado

        self.set_title("Importar do mRemoteNG")
        self.set_content_width(560)
        self.set_content_height(560)

        header = Adw.HeaderBar(show_end_title_buttons=False)
        cancelar = Gtk.Button(label="Cancelar")
        cancelar.connect("clicked", lambda *_: self.close())
        header.pack_start(cancelar)

        self._importar = Gtk.Button(label=f"Importar {resultado.conexoes}")
        self._importar.add_css_class("suggested-action")
        self._importar.set_sensitive(resultado.conexoes > 0)
        self._importar.connect("clicked", self._on_importar)
        header.pack_end(self._importar)

        self._toasts = Adw.ToastOverlay(child=self._corpo())
        barra = Adw.ToolbarView()
        barra.add_top_bar(header)
        barra.set_content(self._toasts)
        self.set_child(barra)

    # ------------------------------------------------------------------ corpo

    def _corpo(self) -> Gtk.Widget:
        r = self.resultado
        if r.conexoes == 0:
            return Adw.StatusPage(
                icon_name="dialog-warning-symbolic",
                title="Nada para importar",
                description="Não encontrei conexões SSH neste arquivo.",
            )

        pagina = Adw.PreferencesPage()

        achado = Adw.PreferencesGroup(title="O que encontrei")
        achado.add(_linha("Conexões SSH", str(r.conexoes)))
        achado.add(_linha("Pastas", str(r.pastas)))
        for protocolo, quantos in sorted(r.ignorados.items()):
            achado.add(
                _linha(
                    f"Conexões {protocolo}",
                    f"{quantos} — ficam de fora",
                    "O WarrenSSH é só SSH.",
                )
            )
        if r.com_senha:
            achado.add(
                _linha(
                    "Senhas",
                    f"{r.com_senha} não vêm",
                    "O mRemoteNG as cifra; recadastre no editor e elas vão para o chaveiro.",
                )
            )
        pagina.add(achado)

        heranca = Adw.PreferencesGroup(
            title="Aproveitar a herança",
            description=(
                "O mRemoteNG repete o mesmo usuário e porta em cada conexão. "
                "O WarrenSSH pode pôr esses valores na pasta e deixar as conexões "
                "herdarem — daí trocar o usuário depois vira uma edição só."
            ),
        )
        self._usar_heranca = Adw.SwitchRow(
            title="Agrupar valores repetidos nas pastas", active=True
        )
        self._usar_heranca.connect("notify::active", lambda *_: self._atualizar_previa())
        heranca.add(self._usar_heranca)
        self._previa = Adw.ActionRow(title="Efeito")
        heranca.add(self._previa)
        pagina.add(heranca)

        self._arvore = Adw.PreferencesGroup(title="Prévia")
        pagina.add(self._arvore)

        self._atualizar_previa()
        return pagina

    def _atualizar_previa(self) -> None:
        r = apply_inheritance(parse_file(self.caminho)) if self._usar_heranca.get_active() else (
            parse_file(self.caminho)
        )
        self.resultado = r

        if r.promovidos:
            efeito = ", ".join(
                f"{quantos} × {chave}" for chave, quantos in sorted(r.promovidos.items())
            )
            self._previa.set_subtitle(f"{efeito} passam a vir da pasta")
        else:
            self._previa.set_subtitle(
                "Cada conexão guarda o próprio valor" if not self._usar_heranca.get_active()
                else "Nada repetido o bastante para agrupar"
            )

        for antiga in getattr(self, "_linhas_arvore", []):
            self._arvore.remove(antiga)
        self._linhas_arvore = []
        for linha in _resumir(r):
            item = Adw.ActionRow(title=linha[0], subtitle=linha[1])
            self._arvore.add(item)
            self._linhas_arvore.append(item)

    # ------------------------------------------------------------------ ação

    def _on_importar(self, *_args: object) -> None:
        try:
            criados = import_into(self.store, self.resultado)
        except (ValueError, KeyError) as exc:
            self._toasts.add_toast(Adw.Toast(title=f"Falhou: {exc}", timeout=4))
            return
        self.emit("imported", len(criados))
        self.close()


def _linha(titulo: str, valor: str, subtitulo: str = "") -> Adw.ActionRow:
    linha = Adw.ActionRow(title=titulo, subtitle=subtitulo)
    rotulo = Gtk.Label(label=valor, valign=Gtk.Align.CENTER)
    rotulo.add_css_class("dim-label")
    linha.add_suffix(rotulo)
    return linha


def _resumir(resultado: ImportResult, limite: int = 8) -> list[tuple[str, str]]:
    """Algumas linhas da árvore, para o usuário reconhecer o que vem."""
    linhas: list[tuple[str, str]] = []

    def descer(no: object, nivel: int) -> None:
        if len(linhas) >= limite:
            return
        recuo = "    " * nivel
        if no.kind == "folder":  # type: ignore[attr-defined]
            quantos = len(no.children)  # type: ignore[attr-defined]
            detalhe = ", ".join(f"{k}={v}" for k, v in sorted(no.properties.items()))  # type: ignore[attr-defined]
            linhas.append(
                (f"{recuo}📁 {no.name}", f"{quantos} item(ns)" + (f" · {detalhe}" if detalhe else ""))  # type: ignore[attr-defined]
            )
        else:
            herdado = ", ".join(sorted(no.inherited))  # type: ignore[attr-defined]
            props = ", ".join(f"{k}={v}" for k, v in sorted(no.properties.items()))  # type: ignore[attr-defined]
            linhas.append(
                (f"{recuo}{no.name}", props + (f" · herda: {herdado}" if herdado else ""))  # type: ignore[attr-defined]
            )
        for filho in no.children:  # type: ignore[attr-defined]
            descer(filho, nivel + 1)

    for raiz in resultado.roots:
        descer(raiz, 0)

    total = resultado.conexoes + resultado.pastas
    if total > len(linhas):
        linhas.append(("…", f"e mais {total - len(linhas)} item(ns)"))
    return linhas
