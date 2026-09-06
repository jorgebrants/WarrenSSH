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
- Import de ~/.ssh/config por parser próprio (ssh/ssh_config.py). O projeto
  NÃO tem dependências de runtime: só a biblioteca padrão do Python.

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

## Terminal
- Menu de contexto (botão direito) e atalhos vivem em `TerminalTab`, no grupo de
  ações `term.*` — um `Gio.SimpleActionGroup` por aba.
- O `Gtk.ShortcutController` do terminal usa fase CAPTURE: a VTE consome o
  teclado, e sem isso os atalhos nunca chegariam.
- Cores: `color_scheme` (system/dark/light) dá a base; `foreground_color` e
  `background_color` do nó sobrepõem. Como são herdáveis, uma pasta pinta todas
  as conexões dentro dela.

## Senha automática (SSH_ASKPASS)
`askpass.py` é chamado pelo ssh com o prompt em argv[1] e devolve o segredo do
chaveiro pelo stdout. `TerminalTab._spawn_env()` só o ativa quando há segredo E
`known_hosts.is_known(host, port)` — ver ssh/known_hosts.py.

## Herança (conceito central)
Cada propriedade de um nó ou tem valor local ou herda do pai (set `inherited`).
Resolução sobe a árvore até achar valor não-herdado. Ver models/resolver.py.

A cascata completa é: **conexão → pasta → raiz → preferências globais → DEFAULTS**.
- `resolve()` percorre SÓ a árvore (o editor precisa distinguir "herdado do pai"
  de "veio do global").
- `resolve_effective()` / `resolve_all(with_defaults=True)` completam com as
  preferências e depois com os padrões de fábrica.
- `Store.preferences` é o objeto `Preferences`; quem monta um Store à mão em
  teste ganha um padrão vazio.

## Preferências (models/preferences.py, ui/preferences.py)
Dois blocos no mesmo arquivo JSON (`~/.config/warrenssh/preferences.json`):
`defaults` entra na cascata (mesmos nomes das propriedades de nó) e `app` é
comportamento do programa (tema, confirmações, reconexão) e fica fora dela.
Alterar uma preferência salva na hora e chama `window._apply_preferences()`,
que reaplica tema, clique da árvore e a aparência das sessões abertas.

## Ambiente
Ubuntu 24.04, GTK 4.14, libadwaita 1.5. venv criado com
`python3 -m venv --system-site-packages .venv` (o `gi` vem do sistema).

## Estrutura
```
src/warrenssh/
  models/   node, store, resolver, editing, search, sample   <- sem GTK, testado
  ssh/      command (argv do ssh), ssh_config (parser), config_import
                                                            <- sem GTK, testado
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
- O GTK esmaece todo widget desabilitado. Num seletor de cor isso exibe uma cor
  falsa: por isso a linha de cor tem uma `Gtk.DrawingArea` ao lado, que mostra a
  cor efetiva de verdade e nunca é desabilitada.
- Popovers e `Adw.Dialog` exigem grab de foco: no display de teste (sem WM
  dando foco) eles existem e respondem por API, mas não aparecem em capturas de
  tela. Validar por estrutura/estado, não por screenshot.
- Probes que abrem o app em sequência precisam de `Gio.ApplicationFlags.NON_UNIQUE`:
  o nome D-Bus da instância anterior sobrevive alguns instantes, e a nova
  instância vira "remota", delega o activate e sai sem abrir janela.
- No `ssh_config`, o PRIMEIRO valor obtido vence: um `Host *` no topo do arquivo
  sobrepõe os blocos seguintes. O import reproduz isso de propósito.
- A cascata de herança QUEBRA se um nó intermediário não marca a chave como
  herdada. Por isso nós novos nascem herdando tudo (`new_child_defaults`).
- Importar QUALQUER submódulo de paramiko (inclusive `paramiko.config`) executa
  o `paramiko/__init__.py`, que puxa cryptography/nacl/bcrypt — 20 MB e wheels
  presas a uma arquitetura, só para ler um arquivo de texto. Por isso o parser
  virou nosso (ssh/ssh_config.py). Não reintroduzir a dependência.
- O runtime `org.gnome.Platform` **não** traz o VTE (verificado no Platform e no
  SDK 50): o manifesto o compila, junto com o simdutf, que o VTE 0.84 exige e o
  SDK não tem. O runtime TRAZ o `ssh` (OpenSSH 10.4).
- meson e cmake instalam em `/app/lib64` por padrão, mas o Flatpak procura
  typelibs em `/app/lib`. Passe `--libdir=lib` / `-DCMAKE_INSTALL_LIBDIR=lib`.
- Com `SSH_ASKPASS_REQUIRE=force`, o prompt de chave de host TAMBÉM vai para o
  askpass. Responder qualquer coisa que não seja `yes`/`no`/fingerprint põe o ssh
  num laço infinito de re-perguntas (medido: 60 mil chamadas em segundos). Por
  isso `askpass.responder()` recusa toda confirmação, e a senha automática só é
  ligada para host já conhecido.
- `--filesystem=~/.ssh:ro` NÃO basta: o ssh precisa gravar no `known_hosts`, ou
  pergunta sobre a chave do servidor a cada conexão. Daí o
  `--filesystem=~/.ssh/known_hosts:create` em separado.
- `pkill -f <padrão>` casa também com o shell que o executa: um `pkill -f "algo"`
  cujo padrão apareça na própria linha de comando mata o próprio processo.
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
