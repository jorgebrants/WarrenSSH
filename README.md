# WarrenSSH

Gerenciador de conexões SSH para Linux: organização em árvore com **herança de
configuração** (inspirada no mRemoteNG), terminal nativo VTE e interface GTK4 +
libadwaita.

- **Linux only**, **SSH only** — o terminal *é* o produto.
- Árvore de pastas e conexões; cada propriedade pode ter valor local ou herdar do pai.
- Segredos em `libsecret`, nunca no JSON.
- Import de `~/.ssh/config`, inclusive com `Include`.
- Import do `confCons.xml` do mRemoteNG, aproveitando a herança.
- Túneis de porta (`-L`, `-R`, `-D`) por conexão ou por pasta.
- Arrastar para reorganizar a árvore, duplicar itens, exportar e importar.
- Ponto verde nas conexões com sessão aberta.
- Botão de tema claro/escuro no canto superior direito.

## Requisitos

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
     gir1.2-adw-1 gir1.2-vte-3.91 gir1.2-secret-1 python3-venv
```

## Ambiente de desenvolvimento

```bash
python3 -m venv --system-site-packages .venv   # --system-site-packages é essencial pro `gi`
source .venv/bin/activate
pip install -e ".[dev]"                        # só pytest; o app não tem dependências
```

O WarrenSSH não usa nenhuma biblioteca Python de terceiros em tempo de execução
— apenas a biblioteca padrão e o `gi` do sistema.

## Rodar

```bash
python -m warrenssh
```

## Testar

```bash
pytest -q
```

## Empacotamento Flatpak

O runtime GNOME traz GTK4, libadwaita, libsecret e o `ssh` (OpenSSH 10.4), mas
**não** o VTE — o manifesto o compila junto com o `simdutf`, que o VTE 0.84 exige.
Build testado no Ubuntu 24.04 com runtime GNOME 50.

```bash
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

# Confira a versão estável do runtime e ajuste `runtime-version` no manifesto:
flatpak remote-ls flathub --runtime | grep org.gnome.Platform

flatpak install flathub org.gnome.Platform//50 org.gnome.Sdk//50

# Build e instalação local
flatpak-builder --user --install --force-clean build packaging/io.github.jorgebrants.WarrenSSH.yaml
# (o build compila o VTE; leva alguns minutos na primeira vez)
flatpak run io.github.jorgebrants.WarrenSSH
```

> **Se o terminal estiver dentro de um snap** (o do VS Code, por exemplo),
> `XDG_DATA_HOME` aponta para `~/snap/<app>/<rev>/.local/share`. Como
> `flatpak --user` instala em `$XDG_DATA_HOME/flatpak`, o app e o runtime inteiro
> vão parar dentro da sandbox do snap, e o `flatpak run` de um terminal normal
> responde **"não instalado"**. Force o caminho certo:
>
> ```bash
> XDG_DATA_HOME=$HOME/.local/share flatpak-builder --user --install --force-clean \
>     build packaging/io.github.jorgebrants.WarrenSSH.yaml
> ```
>
> Se já instalou no lugar errado, dá para mover em vez de baixar tudo de novo
> (os symlinks exportados são relativos):
>
> ```bash
> mv ~/snap/code/*/.local/share/flatpak/* ~/.local/share/flatpak/
> flatpak repair --user
> ```

Na primeira instalação, o Flatpak avisa que `~/.local/share/flatpak/exports/share`
não está no `XDG_DATA_DIRS`: o app só aparece no menu de aplicativos depois de um
logout/login. Pela linha de comando funciona na hora.

### Permissões concedidas e por quê

| Permissão | Motivo |
|---|---|
| `--share=network` | abrir conexões SSH |
| `--socket=ssh-auth` | reaproveitar chaves já carregadas no `ssh-agent` |
| `--filesystem=~/.ssh:ro` | ler chaves e importar o `~/.ssh/config` |
| `--talk-name=org.freedesktop.secrets` | guardar senhas no chaveiro (libsecret) |
| `--socket=wayland` / `fallback-x11` / `--device=dri` | a janela em si |

A árvore fica em `~/.var/app/io.github.jorgebrants.WarrenSSH/config/warrenssh/tree.json`
quando rodando via Flatpak, e em `~/.config/warrenssh/tree.json` fora dele.

### Trocando o binário do ssh

Para apontar para outro binário (ou embrulhar o comando), use:

```bash
WARRENSSH_SSH_BINARY="/usr/bin/ssh -F /caminho/config" warrenssh
```

## Vindo do mRemoteNG

Menu → **Importar do mRemoteNG…**, aponte para o `confCons.xml`. A prévia mostra
o que vem antes de mexer na árvore.

Só conexões SSH são importadas — RDP e VNC são contados e deixados de fora. As
**senhas não vêm**: o mRemoteNG as cifra com AES, e o WarrenSSH não tem
dependência de criptografia. Recadastre-as no editor e elas vão para o chaveiro.

A opção **"Agrupar valores repetidos nas pastas"** é o que traduz um export do
mRemoteNG para o idioma daqui: onde a maioria das conexões de uma pasta repete o
mesmo usuário ou porta, esse valor sobe para a pasta e as conexões passam a
herdá-lo. Num arquivo real de 377 conexões, isso tirou 351 usuários e 347 portas
repetidos — trocar o usuário depois vira uma edição só.

## Túneis de porta

Cada conexão (ou pasta) pode declarar túneis, que sobem junto com a sessão:

| Tipo | Opção | O que faz |
|---|---|---|
| Local | `-L` | abre uma porta **aqui** que sai **lá** — ex.: alcançar um banco que só escuta em `localhost` do servidor |
| Remoto | `-R` | abre uma porta **lá** que volta para **cá** |
| SOCKS | `-D` | proxy para navegar como se estivesse na rede do servidor |

No editor há uma linha "Túneis de porta": escolha o tipo e escreva
`5432:localhost:5432` (ou só a porta, no SOCKS). Como é herdável, uma pasta pode
definir os túneis de toda uma frota.

## Segurança dos seus dados

- A árvore é gravada de forma atômica, e as **3 versões anteriores** ficam
  guardadas como `tree.json.bak-<data>`.
- Se o arquivo corromper, ele é posto de lado como `tree.json.ilegivel-<data>`,
  o backup mais recente é recuperado e o app avisa — em vez de não abrir.
- **Exportar árvore…** e **Importar árvore…** no menu. A exportação leva só a
  estrutura: senhas continuam no chaveiro.

## Preferências globais

`Ctrl+,` ou menu → **Preferências**. Três páginas:

- **Terminal** — fonte, cursor, cores, paleta ANSI (Adwaita, Solarized, Nord,
  Gruvbox, Tango), histórico, rolagem e bell.
- **Conexão** — keepalive, encaminhamento do agente, compressão, e padrões de
  usuário/chave/argumentos.
- **Programa** — tema da janela, avisos ao fechar aba e ao sair, reconexão
  automática, conectar com um clique, e a senha automática.

O que está em **Terminal** e **Conexão** não é uma segunda configuração
competindo com a árvore: são o **topo da cascata de herança**. A resolução de
uma propriedade fica assim:

```
conexão → pasta → … → raiz → preferências globais → padrão de fábrica
```

Ou seja, "global" quer dizer "o valor de quem não definiu o seu". Qualquer pasta
ou conexão continua podendo sobrescrever, e o editor do nó mostra de onde veio
cada valor. Mudanças valem na hora, inclusive em sessões já abertas.

Guardadas em `~/.config/warrenssh/preferences.json`, separadas da árvore.

## Senha automática

A senha guardada no chaveiro é entregue ao `ssh` pelo mecanismo `SSH_ASKPASS` do
próprio OpenSSH: o `warrenssh-askpass` lê o chaveiro e responde ao prompt. A
senha não passa pelo terminal nem pela linha de comando.

Ela só é usada quando **as duas** condições valem:

1. há segredo guardado para aquela conexão;
2. o host já está no `known_hosts`.

A segunda condição não é capricho. Com `SSH_ASKPASS_REQUIRE=force`, a pergunta
"the authenticity of host can't be established" também vai para o askpass — e
responder isso automaticamente anularia a proteção contra ataques de
intermediário. Então o helper **recusa** qualquer confirmação, e num host novo o
WarrenSSH nem liga a senha automática: você aceita a chave e digita a senha uma
vez, e a partir daí é automático.

Para desligar por completo, apague a senha no editor da conexão.

## Ícone

A arte-fonte (1024×1024, fundo já removido) fica em
`packaging/icons/io.github.jorgebrants.WarrenSSH.source.png`. Os tamanhos do
tema hicolor saem dela:

```python
from PIL import Image
base = Image.open("packaging/icons/io.github.jorgebrants.WarrenSSH.source.png")
for t in (16, 24, 32, 48, 64, 128, 256, 512):
    base.resize((t, t), Image.LANCZOS).save(
        f"packaging/icons/{t}x{t}/io.github.jorgebrants.WarrenSSH.png", optimize=True)
```

## Atalhos

| Atalho | Ação |
|---|---|
| `Ctrl+K` | focar a busca |
| `Ctrl+N` | nova conexão |
| `Ctrl+Shift+N` | nova pasta |
| `Ctrl+W` | fechar a aba |
| `Ctrl+Shift+T` | reconectar a aba |
| `Ctrl+Shift+Enter` | ligar/desligar broadcast |
| `Ctrl+Shift+C` | copiar a seleção do terminal |
| `Ctrl+Shift+V` | colar no terminal |
| `Ctrl+Shift+A` | selecionar tudo no terminal |
| `Ctrl+ +` / `Ctrl+ -` / `Ctrl+0` | aumentar, diminuir e restaurar a fonte |
| `Ctrl+Q` | sair |
| `Ctrl+D` | duplicar o item selecionado |
| `Ctrl+Shift+↑` / `↓` | mover o item na árvore |
| `Ctrl+,` | preferências |
| `Ctrl+Shift+B` | alternar tema claro/escuro |

## Licença

GPL-3.0-or-later. Veja [LICENSE](LICENSE).
