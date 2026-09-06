# SPDX-License-Identifier: GPL-3.0-or-later
"""Diálogo de preferências globais.

O que está em "Terminal" e "Conexão" são **padrões**: valem para quem não
definiu o seu na árvore. Qualquer pasta ou conexão pode sobrescrevê-los, e o
editor do nó mostra de onde veio cada valor.
"""

from __future__ import annotations

from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GObject, Gtk, Pango  # noqa: E402

from warrenssh.models.preferences import (  # noqa: E402
    PALETA_PADRAO,
    PALETAS,
    Preferences,
    cor_padrao,
)

TEMAS = (("system", "Seguir o sistema"), ("light", "Claro"), ("dark", "Escuro"))
CURSORES = (("block", "Bloco"), ("ibeam", "Barra"), ("underline", "Sublinhado"))
ESQUEMAS = (("system", "Seguir o sistema"), ("dark", "Escuro"), ("light", "Claro"))


class PreferencesDialog(Adw.PreferencesDialog):
    """Preferências do WarrenSSH, salvas a cada alteração."""

    __gtype_name__ = "WarrenSSHPreferencesDialog"

    __gsignals__ = {
        # Emitido a cada mudança, para a janela reagir na hora.
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, preferences: Preferences) -> None:
        super().__init__()
        self.prefs = preferences
        #: Seletores de cor, para atualizar quando o esquema muda.
        self._cores: dict[str, Gtk.ColorDialogButton] = {}
        #: True enquanto a própria UI se atualiza. `set_rgba()` emite
        #: `notify::rgba` igual a um clique do usuário: sem este guarda, mostrar
        #: a cor do esquema a gravaria como se tivesse sido escolhida — e o
        #: esquema perderia o efeito para sempre.
        self._sincronizando = False
        self.set_title("Preferências")
        self.set_search_enabled(True)
        # Sem limite, o diálogo cresce com o conteúdo e passa da altura de telas
        # de notebook; com isto ele rola por dentro.
        self.set_content_width(600)
        self.set_content_height(620)

        self._sincronizando = True
        try:
            self.add(self._pagina_terminal())
            self.add(self._pagina_conexao())
            self.add(self._pagina_programa())
        finally:
            self._sincronizando = False

    # ------------------------------------------------------------------ páginas

    def _pagina_terminal(self) -> Adw.PreferencesPage:
        pagina = Adw.PreferencesPage(
            title="Terminal", icon_name="utilities-terminal-symbolic", name="terminal"
        )

        texto = Adw.PreferencesGroup(
            title="Texto",
            description="Valem para as conexões que não definirem o seu.",
        )
        texto.add(self._linha_fonte())
        texto.add(
            self._linha_escolha("cursor_shape", "Cursor", CURSORES, padrao="block")
        )
        texto.add(self._linha_switch("cursor_blink", "Cursor piscando", padrao=True))
        pagina.add(texto)

        cores = Adw.PreferencesGroup(title="Cores")
        cores.add(
            self._linha_escolha(
                "color_scheme", "Esquema", ESQUEMAS, padrao="system",
                ao_mudar=self._atualizar_cores,
            )
        )
        cores.add(self._linha_cor("foreground_color", "Cor do texto"))
        cores.add(self._linha_cor("background_color", "Cor do fundo"))
        cores.add(self._linha_paleta())
        pagina.add(cores)

        rolagem = Adw.PreferencesGroup(title="Rolagem e histórico")
        rolagem.add(
            self._linha_numero(
                "scrollback_lines", "Linhas de histórico", minimo=0, maximo=1_000_000,
                passo=1000, padrao=10000,
                subtitulo="0 desliga o histórico",
            )
        )
        rolagem.add(
            self._linha_switch("scroll_on_keystroke", "Ir para o fim ao digitar", padrao=True)
        )
        rolagem.add(
            self._linha_switch("scroll_on_output", "Ir para o fim a cada saída", padrao=False)
        )
        pagina.add(rolagem)

        outros = Adw.PreferencesGroup(title="Outros")
        outros.add(self._linha_switch("audible_bell", "Som de alerta (bell)", padrao=False))
        pagina.add(outros)
        return pagina

    def _pagina_conexao(self) -> Adw.PreferencesPage:
        pagina = Adw.PreferencesPage(
            title="Conexão", icon_name="network-server-symbolic", name="conexao"
        )

        grupo = Adw.PreferencesGroup(
            title="SSH",
            description="Aplicados a toda conexão que não definir o seu.",
        )
        grupo.add(
            self._linha_numero(
                "server_alive_interval", "Manter viva (keepalive)", minimo=0, maximo=3600,
                passo=10, padrao=0,
                subtitulo="Segundos entre sinais de vida. 0 desliga. Evita a queda "
                          "de sessões ociosas atrás de NAT e firewall.",
            )
        )
        grupo.add(
            self._linha_switch(
                "forward_agent", "Encaminhar o agente SSH (-A)", padrao=False,
                subtitulo="Deixa o servidor usar suas chaves para saltar adiante. "
                          "Só ligue em servidores em que você confia.",
            )
        )
        grupo.add(self._linha_switch("compression", "Compressão (-C)", padrao=False))
        pagina.add(grupo)

        extras = Adw.PreferencesGroup(title="Padrões")
        extras.add(self._linha_texto("user", "Usuário", "seu-usuario"))
        extras.add(self._linha_texto("identity_file", "Chave privada", "~/.ssh/id_ed25519"))
        extras.add(self._linha_texto("extra_ssh_args", "Argumentos extras", "-o ConnectTimeout=5"))
        pagina.add(extras)
        return pagina

    def _pagina_programa(self) -> Adw.PreferencesPage:
        pagina = Adw.PreferencesPage(
            title="Programa", icon_name="preferences-system-symbolic", name="programa"
        )

        aparencia = Adw.PreferencesGroup(title="Aparência")
        aparencia.add(self._linha_app_escolha("theme", "Tema da janela", TEMAS))
        pagina.add(aparencia)

        sessoes = Adw.PreferencesGroup(title="Sessões")
        sessoes.add(
            self._linha_app_switch("confirm_close_tab", "Avisar ao fechar aba conectada")
        )
        sessoes.add(
            self._linha_app_switch("confirm_quit", "Avisar ao sair com sessões abertas")
        )
        sessoes.add(
            self._linha_app_switch(
                "auto_reconnect", "Reconectar automaticamente",
                subtitulo="Tenta de novo quando a sessão cai sozinha.",
            )
        )
        pagina.add(sessoes)

        arvore = Adw.PreferencesGroup(title="Árvore")
        arvore.add(
            self._linha_app_switch(
                "activate_on_single_click", "Conectar com um clique",
                subtitulo="Sem isso, é preciso clicar duas vezes.",
            )
        )
        pagina.add(arvore)

        segredos = Adw.PreferencesGroup(
            title="Segredos",
            description="As senhas ficam no chaveiro do sistema, nunca no arquivo da árvore.",
        )
        segredos.add(
            self._linha_app_switch(
                "use_saved_passwords", "Usar a senha guardada no login",
                subtitulo="Só vale para servidores já conhecidos: em host novo, "
                          "a chave precisa ser aceita por você primeiro.",
            )
        )
        pagina.add(segredos)
        return pagina

    # ------------------------------------------------------------------ linhas

    def _linha_fonte(self) -> Adw.ActionRow:
        linha = Adw.ActionRow(
            title="Fonte", subtitle="Vazio: a fonte monoespaçada do sistema"
        )
        botao = Gtk.FontDialogButton(
            dialog=Gtk.FontDialog(title="Fonte do terminal"), valign=Gtk.Align.CENTER
        )
        atual = self.prefs.default_for("font")
        if atual:
            botao.set_font_desc(Pango.FontDescription.from_string(str(atual)))
        botao.connect("notify::font-desc", self._on_fonte)
        linha.add_suffix(botao)

        limpar = Gtk.Button(
            icon_name="edit-clear-symbolic", tooltip_text="Usar a fonte do sistema",
            valign=Gtk.Align.CENTER, has_frame=False,
        )
        limpar.connect("clicked", lambda *_: self._set_default("font", None))
        linha.add_suffix(limpar)
        self._botao_fonte = botao
        return linha

    def _on_fonte(self, botao: Gtk.FontDialogButton, *_a: object) -> None:
        desc = botao.get_font_desc()
        self._set_default("font", desc.to_string() if desc is not None else None)

    def _linha_paleta(self) -> Adw.ComboRow:
        nomes = list(PALETAS)
        linha = Adw.ComboRow(
            title="Paleta ANSI",
            subtitle="As 16 cores que os programas do terminal usam",
            model=Gtk.StringList.new(nomes),
        )
        atual = str(self.prefs.default_for("palette_name") or PALETA_PADRAO)
        linha.set_selected(nomes.index(atual) if atual in nomes else 0)
        linha.connect(
            "notify::selected",
            lambda row, _p: self._set_default("palette_name", nomes[row.get_selected()]),
        )
        return linha

    def _linha_cor(self, key: str, titulo: str) -> Adw.ActionRow:
        linha = Adw.ActionRow(title=titulo, subtitle="Vazio: segue o esquema")
        botao = Gtk.ColorDialogButton(
            dialog=Gtk.ColorDialog(title=titulo, with_alpha=False), valign=Gtk.Align.CENTER
        )
        self._cores[key] = botao
        botao.set_rgba(_rgba(self._cor_atual(key)))
        botao.connect("notify::rgba", lambda b, _p: self._set_default(key, _hex(b.get_rgba())))
        linha.add_suffix(botao)

        limpar = Gtk.Button(
            icon_name="edit-clear-symbolic", tooltip_text="Seguir o esquema",
            valign=Gtk.Align.CENTER, has_frame=False,
        )
        limpar.connect("clicked", lambda *_: self._limpar_cor(key))
        linha.add_suffix(limpar)
        return linha

    def _limpar_cor(self, key: str) -> None:
        """Apaga a cor própria: o campo volta a seguir o esquema."""
        self._set_default(key, None)
        self._sincronizando = True
        try:
            self._cores[key].set_rgba(_rgba(cor_padrao(key, self._esquema_escuro())))
        finally:
            self._sincronizando = False

    def _cor_atual(self, key: str) -> str:
        """A cor a exibir: a definida ou, na falta dela, a de fábrica do esquema."""
        definida = self.prefs.default_for(key)
        if definida:
            return str(definida)
        return cor_padrao(key, self._esquema_escuro())

    def _esquema_escuro(self) -> bool:
        """O esquema escolhido, resolvendo 'seguir o sistema' para o tema real."""
        esquema = str(self.prefs.default_for("color_scheme") or "system").lower()
        if esquema in ("dark", "light"):
            return esquema == "dark"
        return Adw.StyleManager.get_default().get_dark()

    def _atualizar_cores(self) -> None:
        """Reflete nos seletores a troca de esquema, quando não há cor própria."""
        self._sincronizando = True
        try:
            for key, botao in self._cores.items():
                if not self.prefs.default_for(key):
                    botao.set_rgba(_rgba(cor_padrao(key, self._esquema_escuro())))
        finally:
            self._sincronizando = False

    def _linha_switch(
        self, key: str, titulo: str, *, padrao: bool, subtitulo: str = ""
    ) -> Adw.SwitchRow:
        valor = self.prefs.default_for(key)
        linha = Adw.SwitchRow(
            title=titulo, subtitle=subtitulo, active=padrao if valor is None else bool(valor)
        )
        linha.connect("notify::active", lambda r, _p: self._set_default(key, r.get_active()))
        return linha

    def _linha_numero(
        self, key: str, titulo: str, *, minimo: int, maximo: int, passo: int,
        padrao: int, subtitulo: str = "",
    ) -> Adw.SpinRow:
        valor = self.prefs.default_for(key)
        linha = Adw.SpinRow(
            title=titulo,
            subtitle=subtitulo,
            adjustment=Gtk.Adjustment(
                lower=minimo, upper=maximo, step_increment=passo, page_increment=passo * 10
            ),
        )
        linha.set_value(padrao if valor is None else int(valor))
        linha.connect(
            "notify::value",
            lambda r, _p: self._set_default(key, int(r.get_value()) or None),
        )
        return linha

    def _linha_texto(self, key: str, titulo: str, dica: str) -> Adw.EntryRow:
        linha = Adw.EntryRow(title=titulo)
        atual = self.prefs.default_for(key)
        if isinstance(atual, (list, tuple)):
            atual = " ".join(str(p) for p in atual)
        linha.set_text(str(atual or ""))
        linha.set_tooltip_text(f"Ex.: {dica}")
        linha.connect("changed", lambda r: self._set_texto(key, r.get_text()))
        return linha

    def _set_texto(self, key: str, texto: str) -> None:
        from warrenssh.models.editing import EditingError, parse_value

        try:
            self._set_default(key, parse_value(key, texto))
        except EditingError:
            pass  # valor pela metade enquanto se digita: só ignora

    def _linha_escolha(
        self,
        key: str,
        titulo: str,
        opcoes: tuple[tuple[str, str], ...],
        *,
        padrao: str,
        ao_mudar: Callable[[], None] | None = None,
    ) -> Adw.ComboRow:
        valores = [v for v, _ in opcoes]
        linha = Adw.ComboRow(
            title=titulo, model=Gtk.StringList.new([r for _, r in opcoes])
        )
        atual = str(self.prefs.default_for(key) or padrao)
        linha.set_selected(valores.index(atual) if atual in valores else 0)

        def escolheu(row: Adw.ComboRow, _p: object) -> None:
            self._set_default(key, valores[row.get_selected()])
            if ao_mudar is not None:
                ao_mudar()

        linha.connect("notify::selected", escolheu)
        return linha

    def _linha_app_switch(self, key: str, titulo: str, *, subtitulo: str = "") -> Adw.SwitchRow:
        linha = Adw.SwitchRow(
            title=titulo, subtitle=subtitulo, active=bool(self.prefs.get_app(key))
        )
        linha.connect("notify::active", lambda r, _p: self._set_app(key, r.get_active()))
        return linha

    def _linha_app_escolha(
        self, key: str, titulo: str, opcoes: tuple[tuple[str, str], ...]
    ) -> Adw.ComboRow:
        valores = [v for v, _ in opcoes]
        linha = Adw.ComboRow(title=titulo, model=Gtk.StringList.new([r for _, r in opcoes]))
        atual = str(self.prefs.get_app(key))
        linha.set_selected(valores.index(atual) if atual in valores else 0)
        linha.connect(
            "notify::selected",
            lambda row, _p: self._set_app(key, valores[row.get_selected()]),
        )
        return linha

    # ------------------------------------------------------------------ escrita

    def _set_default(self, key: str, valor: Any) -> None:
        if self._sincronizando:
            return  # a UI está se ajustando sozinha; não é escolha do usuário
        self.prefs.set_default(key, valor)
        self._salvar()

    def _set_app(self, key: str, valor: Any) -> None:
        self.prefs.set_app(key, valor)
        self._salvar()

    def _salvar(self) -> None:
        try:
            self.prefs.save_json()
        except OSError as exc:
            self.add_toast(Adw.Toast(title=f"Não deu para salvar: {exc}", timeout=4))
            return
        self.emit("changed")


def _rgba(spec: str) -> Gdk.RGBA:
    cor = Gdk.RGBA()
    if not cor.parse(spec):
        cor.parse("#000000")
    return cor


def _hex(cor: Gdk.RGBA) -> str:
    return "#%02x%02x%02x" % (
        round(cor.red * 255), round(cor.green * 255), round(cor.blue * 255)
    )
