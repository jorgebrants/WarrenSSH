# SPDX-License-Identifier: GPL-3.0-or-later
"""Importa o `confCons.xml` do mRemoteNG. Sem GTK.

O mRemoteNG guarda tudo num XML de `Node`s: `Container` vira pasta e
`Connection` vira conexão. Ele carrega dezenas de atributos de RDP, VNC e ICA
que não nos dizem respeito — lemos só o punhado que faz sentido para SSH.

**Senhas não são importadas.** O mRemoteNG as cifra com AES, e o WarrenSSH não
tem dependência de criptografia (de propósito). O import conta quantas ficaram
para trás para o usuário saber o que recadastrar.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NAMESPACE = "http://mremoteng.org"

#: Protocolos que viram conexão. O resto é contado e deixado de fora.
PROTOCOLOS_SSH = frozenset({"SSH2", "SSH1", "SSH"})

#: Atributo do mRemoteNG -> propriedade do nó.
CAMPOS: dict[str, str] = {
    "Hostname": "host",
    "Username": "user",
    "Port": "port",
}

#: `Inherit*` do mRemoteNG -> a mesma propriedade, quando marcado como herdado.
HERANCA: dict[str, str] = {
    "InheritHostname": "host",
    "InheritUsername": "user",
    "InheritPort": "port",
}

#: Só promove um valor à pasta se ele cobrir pelo menos esta fatia dos filhos.
LIMIAR_HERANCA = 0.6


class MRemoteNGError(ValueError):
    """Arquivo que não dá para ler como export do mRemoteNG."""


@dataclass
class ImportedNode:
    """Um nó lido do XML, antes de virar `Node` do WarrenSSH."""

    name: str
    kind: str  # "folder" | "connection"
    properties: dict[str, Any] = field(default_factory=dict)
    inherited: set[str] = field(default_factory=set)
    children: list["ImportedNode"] = field(default_factory=list)


@dataclass
class ImportResult:
    """O que veio do arquivo, e o que ficou de fora."""

    roots: list[ImportedNode] = field(default_factory=list)
    conexoes: int = 0
    pastas: int = 0
    ignorados: dict[str, int] = field(default_factory=dict)
    com_senha: int = 0
    promovidos: dict[str, int] = field(default_factory=dict)

    def resumo(self) -> str:
        partes = [f"{self.conexoes} conexão(ões)", f"{self.pastas} pasta(s)"]
        if self.ignorados:
            fora = ", ".join(f"{n} de {p}" for p, n in sorted(self.ignorados.items()))
            partes.append(f"fora: {fora}")
        if self.com_senha:
            partes.append(f"{self.com_senha} senha(s) não vieram (cifradas)")
        return " · ".join(partes)


def parse_file(path: Path | str) -> ImportResult:
    """Lê o arquivo e devolve a árvore, sem tocar no Store."""
    try:
        raiz = ET.parse(str(path)).getroot()
    except (OSError, ET.ParseError) as exc:
        raise MRemoteNGError(f"Não deu para ler o arquivo: {exc}") from exc

    if not raiz.tag.endswith("Connections"):
        raise MRemoteNGError(
            "Isto não parece um confCons.xml do mRemoteNG "
            f"(elemento raiz: {raiz.tag})."
        )

    resultado = ImportResult()
    resultado.roots = [
        no for filho in raiz if _e_node(filho)
        for no in [_ler(filho, resultado)] if no is not None
    ]
    return resultado


def apply_inheritance(resultado: ImportResult) -> ImportResult:
    """Promove para cada pasta os valores que a maioria dos filhos repete.

    É o que transforma um export plano no idioma do WarrenSSH: em vez de 350
    conexões repetindo o mesmo usuário, a pasta passa a defini-lo e as conexões
    o herdam — trocar depois vira uma edição só.
    """
    for raiz in resultado.roots:
        _promover(raiz, resultado)
    return resultado


def import_into(
    store: Any,
    resultado: ImportResult,
    *,
    folder_name: str = "Importado do mRemoteNG",
) -> list[Any]:
    """Cria os nós no Store, sob uma pasta própria. Devolve o que entrou."""
    from warrenssh.models.node import new_connection, new_folder

    raiz = store.add(new_folder(folder_name))
    criados: list[Any] = [raiz]
    for no in resultado.roots:
        criados.extend(_criar(store, no, raiz.id, new_folder, new_connection))
    return criados


def _criar(store: Any, no: ImportedNode, parent_id: str, new_folder, new_connection) -> list[Any]:
    fabrica = new_folder if no.kind == "folder" else new_connection
    node = store.add(
        fabrica(
            no.name,
            parent_id=parent_id,
            properties=dict(no.properties),
            inherited=set(no.inherited),
        )
    )
    criados = [node]
    for filho in no.children:
        criados.extend(_criar(store, filho, node.id, new_folder, new_connection))
    return criados


# --------------------------------------------------------------------- leitura


def _e_node(elemento: ET.Element) -> bool:
    return elemento.tag == "Node" or elemento.tag == f"{{{NAMESPACE}}}Node"


def _ler(elemento: ET.Element, resultado: ImportResult) -> ImportedNode | None:
    nome = (elemento.get("Name") or "").strip() or "(sem nome)"
    tipo = (elemento.get("Type") or "").strip()

    if tipo == "Container":
        # Containers do mRemoteNG carregam os padrões do protocolo deles — que
        # costuma ser RDP, com Port=3389. Importar isso faria as conexões SSH
        # herdarem a porta errada, então a pasta entra só com o nome; os valores
        # comuns vêm depois, de `apply_inheritance`, olhando as conexões reais.
        pasta = ImportedNode(name=nome, kind="folder")
        for filho in elemento:
            if not _e_node(filho):
                continue
            lido = _ler(filho, resultado)
            if lido is not None:
                pasta.children.append(lido)
        resultado.pastas += 1
        return pasta

    protocolo = (elemento.get("Protocol") or "").strip().upper()
    if protocolo not in PROTOCOLOS_SSH:
        resultado.ignorados[protocolo or "(sem protocolo)"] = (
            resultado.ignorados.get(protocolo or "(sem protocolo)", 0) + 1
        )
        return None

    if (elemento.get("Password") or "").strip():
        resultado.com_senha += 1

    conexao = ImportedNode(name=nome, kind="connection")
    conexao.properties.update(_propriedades(elemento))
    conexao.inherited.update(_herdadas(elemento))
    resultado.conexoes += 1
    return conexao


def _propriedades(elemento: ET.Element) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for atributo, chave in CAMPOS.items():
        bruto = (elemento.get(atributo) or "").strip()
        if not bruto:
            continue
        if chave == "port":
            try:
                porta = int(bruto)
            except ValueError:
                continue
            if porta != 22:          # 22 é o padrão; não precisa gravar
                props["port"] = porta
        else:
            props[chave] = bruto
    return props


def _herdadas(elemento: ET.Element) -> set[str]:
    return {
        chave
        for atributo, chave in HERANCA.items()
        if (elemento.get(atributo) or "").strip().lower() == "true"
    }


# ------------------------------------------------------------------ herança


def _promover(pasta: ImportedNode, resultado: ImportResult) -> None:
    """Sobe para a pasta o valor dominante entre os filhos diretos."""
    for filho in pasta.children:
        if filho.kind == "folder":
            _promover(filho, resultado)

    conexoes = [f for f in pasta.children if f.kind == "connection"]
    if len(conexoes) < 2:
        return

    for chave in ("user", "port"):
        valores = [c.properties.get(chave) for c in conexoes]
        presentes = [v for v in valores if v is not None]
        if not presentes:
            continue

        dominante = max(set(presentes), key=presentes.count)
        if presentes.count(dominante) / len(conexoes) < LIMIAR_HERANCA:
            continue

        pasta.properties[chave] = dominante
        promovidos = 0
        for conexao in conexoes:
            if conexao.properties.get(chave) == dominante:
                del conexao.properties[chave]
                conexao.inherited.add(chave)
                promovidos += 1
        if promovidos:
            resultado.promovidos[chave] = resultado.promovidos.get(chave, 0) + promovidos
