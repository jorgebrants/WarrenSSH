# SPDX-License-Identifier: GPL-3.0-or-later
"""Preferências globais. Sem GTK.

São duas coisas diferentes no mesmo arquivo:

- `defaults`: o **topo da cascata de herança**. Uma conexão que não define nem
  herda uma propriedade cai aqui antes de cair no padrão de fábrica. É por isso
  que "global" quer dizer "o valor de quem não definiu o seu", e não uma segunda
  fonte de verdade competindo com a árvore.
- `app`: comportamento do programa (tema, confirmações, reconexão). Não tem nada
  a ver com a árvore, então fica fora da cascata.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

#: Paletas ANSI prontas. A primeira é a que o app usava fixa no código.
PALETAS: dict[str, tuple[str, ...]] = {
    "Adwaita": (
        "#241f31", "#c01c28", "#2ec27e", "#f5c211",
        "#1e78e4", "#9841bb", "#0ab9dc", "#c0bfbc",
        "#5e5c64", "#ed333b", "#57e389", "#f8e45c",
        "#51a1ff", "#c061cb", "#4fd2fd", "#f6f5f4",
    ),
    "Solarized": (
        "#073642", "#dc322f", "#859900", "#b58900",
        "#268bd2", "#d33682", "#2aa198", "#eee8d5",
        "#002b36", "#cb4b16", "#586e75", "#657b83",
        "#839496", "#6c71c4", "#93a1a1", "#fdf6e3",
    ),
    "Nord": (
        "#3b4252", "#bf616a", "#a3be8c", "#ebcb8b",
        "#81a1c1", "#b48ead", "#88c0d0", "#e5e9f0",
        "#4c566a", "#bf616a", "#a3be8c", "#ebcb8b",
        "#81a1c1", "#b48ead", "#8fbcbb", "#eceff4",
    ),
    "Gruvbox": (
        "#282828", "#cc241d", "#98971a", "#d79921",
        "#458588", "#b16286", "#689d6a", "#a89984",
        "#928374", "#fb4934", "#b8bb26", "#fabd2f",
        "#83a598", "#d3869b", "#8ec07c", "#ebdbb2",
    ),
    "Tango": (
        "#2e3436", "#cc0000", "#4e9a06", "#c4a000",
        "#3465a4", "#75507b", "#06989a", "#d3d7cf",
        "#555753", "#ef2929", "#8ae234", "#fce94f",
        "#729fcf", "#ad7fa8", "#34e2e2", "#eeeeec",
    ),
}

PALETA_PADRAO = "Adwaita"

#: Cores de fábrica do terminal, por esquema. É o que aparece quando ninguém
#: definiu cor própria — e o que os seletores da UI precisam mostrar.
CORES_PADRAO: dict[str, dict[str, str]] = {
    "dark": {"foreground_color": "#ffffff", "background_color": "#1d1d1d"},
    "light": {"foreground_color": "#1d1d1d", "background_color": "#fafafa"},
}


def cor_padrao(key: str, escuro: bool) -> str:
    """Cor de fábrica de um campo, conforme o esquema em uso."""
    return CORES_PADRAO["dark" if escuro else "light"].get(key, "#000000")

#: Comportamento do programa, com os valores de fábrica.
APP_DEFAULTS: dict[str, Any] = {
    "theme": "system",                  # system | light | dark
    "confirm_close_tab": True,          # avisar ao fechar aba com sessão viva
    "confirm_quit": True,               # avisar ao sair com sessões abertas
    "auto_reconnect": False,            # reconectar sozinho quando a sessão cai
    "auto_reconnect_delay": 3,          # segundos antes de tentar
    "use_saved_passwords": True,        # ligar/desligar o SSH_ASKPASS
    "activate_on_single_click": False,  # um clique conecta, em vez de dois
}

APP_CHOICES: dict[str, tuple[str, ...]] = {"theme": ("system", "light", "dark")}


@dataclass
class Preferences:
    """Preferências globais, com persistência própria."""

    path: Path | None = None
    defaults: dict[str, Any] = field(default_factory=dict)
    app: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = default_path()

    # ------------------------------------------------------------------ leitura

    def default_for(self, key: str) -> Any:
        """Valor global de uma propriedade da cascata (None se não houver)."""
        return self.defaults.get(key)

    def get_app(self, key: str) -> Any:
        """Opção de comportamento, caindo no valor de fábrica."""
        valor = self.app.get(key)
        return APP_DEFAULTS.get(key) if valor is None else valor

    def palette(self) -> tuple[str, ...]:
        """Os 16 tons ANSI: os do usuário, os do esquema escolhido, ou o padrão."""
        propria = self.defaults.get("palette")
        if isinstance(propria, (list, tuple)) and len(propria) == 16:
            return tuple(str(c) for c in propria)
        nome = str(self.defaults.get("palette_name") or PALETA_PADRAO)
        return PALETAS.get(nome, PALETAS[PALETA_PADRAO])

    # ------------------------------------------------------------------ escrita

    def set_default(self, key: str, value: Any) -> None:
        """Grava (ou remove, com None) um padrão da cascata."""
        if value is None:
            self.defaults.pop(key, None)
        else:
            self.defaults[key] = value

    def set_app(self, key: str, value: Any) -> None:
        if value is None:
            self.app.pop(key, None)
        else:
            self.app[key] = value

    # -------------------------------------------------------------- persistência

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "defaults": dict(self.defaults),
            "app": dict(self.app),
        }

    def load_dict(self, data: dict[str, Any]) -> None:
        self.defaults = dict(data.get("defaults") or {})
        self.app = dict(data.get("app") or {})

    def load_json(self, path: Path | None = None) -> None:
        """Carrega do disco. Arquivo ausente ou corrompido = valores de fábrica."""
        alvo = path or self.path
        assert alvo is not None
        try:
            self.load_dict(json.loads(alvo.read_text(encoding="utf-8")))
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            self.defaults, self.app = {}, {}
        except (json.JSONDecodeError, TypeError, AttributeError):
            # Preferências ilegíveis não podem impedir o app de abrir.
            self.defaults, self.app = {}, {}

    def save_json(self, path: Path | None = None) -> None:
        """Grava de forma atômica, como a árvore."""
        alvo = path or self.path
        assert alvo is not None
        alvo.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        fd, temporario = tempfile.mkstemp(dir=str(alvo.parent), prefix=".prefs-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporario, alvo)
        except BaseException:
            Path(temporario).unlink(missing_ok=True)
            raise


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "warrenssh" / "preferences.json"
