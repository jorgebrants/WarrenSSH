# WarrenSSH

Gerenciador de conexões SSH para Linux: organização em árvore com **herança de
configuração** (inspirada no mRemoteNG), terminal nativo VTE e interface GTK4 +
libadwaita.

- **Linux only**, **SSH only** — o terminal *é* o produto.
- Árvore de pastas e conexões; cada propriedade pode ter valor local ou herdar do pai.
- Segredos em `libsecret`, nunca no JSON.
- Import de `~/.ssh/config`.

## Requisitos

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 \
     gir1.2-adw-1 gir1.2-vte-3.91 gir1.2-secret-1 python3-venv
```

## Ambiente de desenvolvimento

```bash
python3 -m venv --system-site-packages .venv   # --system-site-packages é essencial pro `gi`
source .venv/bin/activate
pip install -e ".[dev]"
```

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

### Atualizando a versão do paramiko no manifesto

```bash
python3 -c "
import json, urllib.request
m = json.load(urllib.request.urlopen('https://pypi.org/pypi/paramiko/json'))
w = next(u for u in m['urls'] if u['packagetype'] == 'bdist_wheel')
print(m['info']['version']); print(w['url']); print(w['digests']['sha256'])
"
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
| `Ctrl+Q` | sair |

## Licença

GPL-3.0-or-later. Veja [LICENSE](LICENSE).
