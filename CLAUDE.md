# WarrenSSH — contexto do projeto

Gerenciador de conexões SSH para Linux. Terminal nativo, organização em árvore
com herança de configuração. Inspirado no mRemoteNG, mas SSH-only e Linux-only.

## Stack (não reabrir sem bloqueio técnico real)
- Python 3.11+, GTK4 + libadwaita via PyGObject (`gi.repository`)
- Terminal: VTE (`gi.require_version("Vte", "3.91")`)
- Abas: Adw.TabView. Layout: Adw.OverlaySplitView.
- Árvore: Gtk.TreeListModel + Gtk.ListView + Gtk.TreeExpander.
  NUNCA usar Gtk.TreeView (deprecado no GTK4).
- Persistência: JSON. Segredos: libsecret (gi Secret). NUNCA salvar senha no JSON.
- Import de ~/.ssh/config via paramiko.SSHConfig.

## Licença
Projeto sob **GPL-3.0-or-later**. TODO arquivo `.py` novo começa, na PRIMEIRA
linha, com:

    # SPDX-License-Identifier: GPL-3.0-or-later

## Regras de código
- Type hints em tudo. dataclasses para modelos.
- Lógica de negócio (models/, ssh/) SEM dependência de GTK — testável isolada.
- UI só chama a lógica; não coloca regra de resolução dentro de widget.
- Sinais GTK conectados explicitamente; nada de lógica pesada no handler.
- Erros de SSH/spawn viram feedback visual (Adw.Toast), nunca crash silencioso.

## Herança (conceito central)
Cada propriedade de um nó ou tem valor local ou herda do pai (set `inherited`).
Resolução sobe a árvore até achar valor não-herdado. Ver models/resolver.py.

## Ambiente
Ubuntu 24.04, GTK 4.14, libadwaita 1.5. venv criado com
`python3 -m venv --system-site-packages .venv` (o `gi` vem do sistema).

## Estrutura
```
src/warrenssh/
  models/   node, store, resolver, editing, search, sample   <- sem GTK, testado
  ssh/      command (argv do ssh), config_import              <- sem GTK, testado
  ui/       window, sidebar, session_view, terminal, editor,
            import_dialog, theme
  secrets.py  wrapper libsecret
packaging/  manifesto flatpak, .desktop, metainfo
```

## Armadilhas já encontradas (não repetir)
- `Vte.Terminal.feed_child()` **também** emite o sinal `commit`. Sem um guarda de
  reentrância, o broadcast entre abas vira laço infinito. Ver `TerminalTab._injecting`.
- `Gtk.Widget.activate_action()` exige o nome COM prefixo: `"win.edit-node"`,
  não `"edit-node"`.
- `Adw.TabPage.set_icon()` quer um `Gio.Icon` (use `Gio.ThemedIcon.new`), não o
  `IconPaintable` que `Gtk.IconTheme.lookup_icon` devolve.
- A VTE entrega o status cru do `waitpid` em `child-exited`; converta com
  `os.waitstatus_to_exitcode` antes de mostrar ao usuário.
- GTK 4.14 não tem variáveis CSS (`var(--…)`) nem `color-mix`. Use as cores
  nomeadas do libadwaita (`@window_bg_color`) e `mix()`/`alpha()`.
- `box-shadow: inset` só aparece se o elemento tiver `padding` — senão os filhos
  cobrem a sombra.
- No `ssh_config`, o PRIMEIRO valor obtido vence: um `Host *` no topo do arquivo
  sobrepõe os blocos seguintes. O import reproduz isso de propósito.
- A cascata de herança QUEBRA se um nó intermediário não marca a chave como
  herdada. Por isso nós novos nascem herdando tudo (`new_child_defaults`).
- Importar QUALQUER submódulo de paramiko (inclusive `paramiko.config`) executa
  o `paramiko/__init__.py`, que puxa cryptography/nacl/bcrypt. Não dá para usar
  só o parser: o Flatpak precisa das wheels binárias das três.
- O runtime `org.gnome.Platform` **não** traz o VTE (verificado no Platform e no
  SDK 50): o manifesto o compila, junto com o simdutf, que o VTE 0.84 exige e o
  SDK não tem. O runtime TRAZ o `ssh` (OpenSSH 10.4).
- meson e cmake instalam em `/app/lib64` por padrão, mas o Flatpak procura
  typelibs em `/app/lib`. Passe `--libdir=lib` / `-DCMAKE_INSTALL_LIBDIR=lib`.
- Terminal dentro de um snap (VS Code) tem `XDG_DATA_HOME` redirecionado para
  `~/snap/<app>/<rev>/.local/share`, e `flatpak --user` instala em
  `$XDG_DATA_HOME/flatpak` — ou seja, dentro da sandbox do snap, invisível para o
  terminal do usuário. Sempre construir com
  `XDG_DATA_HOME=$HOME/.local/share flatpak-builder ...`.
- O SDK do GNOME já tem setuptools/wheel; instalá-los de novo falha ao tentar
  desinstalar os do sistema (`/usr` é read-only).

## Como rodar
python -m warrenssh   (ou `warrenssh` após instalar)

## Como testar
pytest -q   (lógica pura; não requer display)
