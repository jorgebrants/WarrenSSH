# SPDX-License-Identifier: GPL-3.0-or-later
"""Regras de edição de um nó: liga/desliga herança e converte tipos.

Fica fora da UI de propósito — o editor só chama estas funções, e elas são
testáveis sem GTK.
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from warrenssh.models.node import Node
from warrenssh.models.resolver import resolve_inherited
from warrenssh.models.store import Store

#: Campos que aparecem no editor, na ordem, com rótulo e tipo.
FIELD_LABELS: dict[str, str] = {
    "host": "Host",
    "user": "Usuário",
    "port": "Porta",
    "identity_file": "Chave privada",
    "proxy_jump": "Bastion (ProxyJump)",
    "server_alive_interval": "Manter viva (segundos)",
    "forward_agent": "Encaminhar o agente SSH",
    "compression": "Compressão",
    "tunnels": "Túneis de porta",
    "request_pty": "Forçar PTY (-t)",
    "extra_ssh_args": "Argumentos extras do ssh",
    "startup_command": "Comando inicial",
    "charset": "Codificação",
    "scrollback_lines": "Linhas de histórico",
    "color_scheme": "Esquema de cores",
    "foreground_color": "Cor do texto",
    "background_color": "Cor do fundo",
    "font": "Fonte",
}

#: `host` identifica a máquina: herdar não faz sentido, e pastas não têm host.
NON_INHERITABLE: frozenset[str] = frozenset({"host"})

BOOL_FIELDS: frozenset[str] = frozenset({"request_pty", "forward_agent", "compression"})
INT_FIELDS: frozenset[str] = frozenset(
    {"port", "scrollback_lines", "server_alive_interval"}
)
LIST_FIELDS: frozenset[str] = frozenset({"extra_ssh_args"})
TUNNEL_FIELDS: frozenset[str] = frozenset({"tunnels"})
CHOICE_FIELDS: dict[str, tuple[str, ...]] = {"color_scheme": ("system", "dark", "light")}
COLOR_FIELDS: frozenset[str] = frozenset({"foreground_color", "background_color"})

#: `#rgb` ou `#rrggbb`, com ou sem o `#`.
_COR = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class EditingError(ValueError):
    """Valor digitado que não dá para converter."""


def fields_for(kind: str) -> list[str]:
    """Campos exibidos para pastas (perfil de grupo) e para conexões."""
    if kind == "folder":
        return [key for key in FIELD_LABELS if key not in NON_INHERITABLE]
    return list(FIELD_LABELS)


def can_inherit(node: Node, key: str, store: Store) -> bool:
    """Só faz sentido herdar o que é herdável e quando existe um pai."""
    return key not in NON_INHERITABLE and store.get(node.parent_id) is not None


def set_inherited(node: Node, key: str, inherit: bool, store: Store) -> None:
    """Liga/desliga a herança de uma chave.

    Ao ligar, o valor local é preservado no `properties` (serve de rascunho se o
    usuário voltar atrás); `resolve` o ignora enquanto a chave estiver herdada.
    """
    if inherit:
        if not can_inherit(node, key, store):
            raise EditingError(f"{key} não pode ser herdado neste nó")
        node.inherited.add(key)
    else:
        node.inherited.discard(key)


def set_value(node: Node, key: str, raw: Any) -> Any:
    """Grava um valor local já convertido para o tipo do campo."""
    value = parse_value(key, raw)
    if value is None:
        node.properties.pop(key, None)
    else:
        node.properties[key] = value
    return value


def effective_placeholder(node: Node, key: str, store: Store) -> str:
    """O que o pai ofereceria — texto cinza que o editor mostra ao herdar."""
    return format_value(key, resolve_inherited(node, key, store))


def parse_value(key: str, raw: Any) -> Any:
    """Texto da UI -> valor tipado. String vazia significa 'sem valor local'."""
    if key in BOOL_FIELDS:
        return None if raw is None else bool(raw)

    if isinstance(raw, str):
        raw = raw.strip()
        if raw == "":
            return None

    if raw is None:
        return None

    if key in INT_FIELDS:
        try:
            number = int(raw)
        except (TypeError, ValueError) as exc:
            raise EditingError(f"{FIELD_LABELS.get(key, key)}: número inválido ({raw!r})") from exc
        if key == "port" and not 1 <= number <= 65535:
            raise EditingError("Porta deve ficar entre 1 e 65535")
        if key == "scrollback_lines" and number < 0:
            raise EditingError("Linhas de histórico não pode ser negativo")
        if key == "server_alive_interval" and not 0 <= number <= 3600:
            raise EditingError("Manter viva: use de 0 a 3600 segundos")
        return number

    if key in LIST_FIELDS:
        if isinstance(raw, (list, tuple)):
            return [str(part) for part in raw] or None
        try:
            parts = shlex.split(str(raw))
        except ValueError as exc:  # aspas não fechadas
            raise EditingError(f"{FIELD_LABELS.get(key, key)}: {exc}") from exc
        return parts or None

    if key in TUNNEL_FIELDS:
        return _parse_tuneis(raw)

    if key in COLOR_FIELDS:
        return _parse_cor(str(raw))

    if key in CHOICE_FIELDS:
        text = str(raw)
        if text not in CHOICE_FIELDS[key]:
            raise EditingError(f"{FIELD_LABELS.get(key, key)}: opção inválida ({text!r})")
        return text

    return str(raw)


def _parse_tuneis(raw: Any) -> list[dict[str, Any]] | None:
    """Valida cada túnel da lista; um só inválido recusa tudo, com o motivo."""
    from warrenssh.ssh.tunnels import TunnelError, normalize

    if not raw:
        return None
    if not isinstance(raw, (list, tuple)):
        raise EditingError("Túneis: esperava uma lista")
    try:
        return [normalize(t) for t in raw] or None
    except TunnelError as exc:
        raise EditingError(f"Túneis: {exc}") from exc


def _parse_cor(texto: str) -> str:
    """Normaliza uma cor para `#rrggbb`, aceitando `#rgb` e a forma sem `#`."""
    casamento = _COR.match(texto.strip())
    if casamento is None:
        raise EditingError(f"Cor inválida: {texto!r} (use #rrggbb, ex.: #1d1d1d)")
    digitos = casamento.group(1).lower()
    if len(digitos) == 3:
        digitos = "".join(d * 2 for d in digitos)
    return f"#{digitos}"


def format_value(key: str, value: Any) -> str:
    """Valor tipado -> texto da UI."""
    if value is None:
        return ""
    if key in LIST_FIELDS and isinstance(value, (list, tuple)):
        return " ".join(shlex.quote(str(part)) for part in value)
    if key in BOOL_FIELDS:
        return "sim" if value else "não"
    if key in TUNNEL_FIELDS and isinstance(value, (list, tuple)):
        from warrenssh.ssh.tunnels import FLAGS, to_spec

        return ", ".join(f"{FLAGS[t['type']]} {to_spec(t)}" for t in value)
    return str(value)


def apply_edits(
    node: Node,
    edits: dict[str, Any],
    inherited: set[str],
    store: Store,
    *,
    name: str | None = None,
) -> None:
    """Aplica de uma vez o que o editor coletou. Valida tudo antes de gravar."""
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise EditingError("O nome não pode ficar vazio")

    allowed = set(fields_for(node.kind))
    parsed: dict[str, Any] = {}
    for key, raw in edits.items():
        if key not in allowed:
            raise EditingError(f"campo desconhecido para {node.kind}: {key}")
        parsed[key] = parse_value(key, raw)

    for key in inherited:
        if not can_inherit(node, key, store):
            raise EditingError(f"{key} não pode ser herdado neste nó")

    # Só toca no nó depois que tudo validou — nada de estado meio-gravado.
    if name is not None:
        node.name = name.strip()
    for key, value in parsed.items():
        if value is None:
            node.properties.pop(key, None)
        else:
            node.properties[key] = value
    node.inherited = {key for key in inherited if key in allowed}


def new_child_defaults(parent: Node | None, kind: str) -> set[str]:
    """Um filho novo herda tudo o que puder: a cascata do avô precisa fluir.

    Sem isso, um elo não-herdado no meio interromperia a subida (ver
    tests/test_resolver.py::test_cadeia_quebra_se_o_intermediario_nao_herda).
    """
    if parent is None:
        return set()
    return {key for key in fields_for(kind) if key not in NON_INHERITABLE}
