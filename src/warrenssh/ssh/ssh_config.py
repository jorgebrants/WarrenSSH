# SPDX-License-Identifier: GPL-3.0-or-later
"""Parser do formato ssh_config. Só biblioteca padrão, sem GTK.

Implementa o que o WarrenSSH precisa para importar `~/.ssh/config`, seguindo as
regras do OpenSSH:

- diretivas são `chave valor` ou `chave=valor`, com a chave sem distinção de caixa;
- um bloco `Host` vale até o próximo `Host`/`Match`, e casa por curinga
  (`*`, `?`) com suporte a negação (`!padrao`);
- **o primeiro valor obtido vence** — por isso a convenção de deixar `Host *`
  no fim do arquivo;
- `IdentityFile` acumula ao longo dos blocos que casam, em vez de ser substituído.

Diferenças deliberadas em relação ao OpenSSH: blocos `Match` são ignorados
(dependem de estado de execução — usuário final, resultado de comando — que não
temos ao importar), e nenhum token (`%h`, `%p`) é expandido.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path

#: Diretivas que acumulam valores em vez de só a primeira vencer.
MULTIVALORADAS: frozenset[str] = frozenset({"identityfile", "localforward", "remoteforward"})

#: Limite de profundidade de `Include`, para um ciclo não travar o app.
MAX_INCLUDE_DEPTH = 8

_LINHA = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_-]*)\s*(?:=\s*|\s+)(.+?)\s*$")


@dataclass
class Bloco:
    """Um `Host` do arquivo: os padrões que ele casa e o que define."""

    padroes: list[str]
    diretivas: list[tuple[str, str]] = field(default_factory=list)

    def casa(self, host: str) -> bool:
        """Casa se algum padrão positivo bate e nenhum negado bate."""
        positivo = False
        for padrao in self.padroes:
            if padrao.startswith("!"):
                if _casa_padrao(host, padrao[1:]):
                    return False
            elif _casa_padrao(host, padrao):
                positivo = True
        return positivo


class SSHConfig:
    """Um `ssh_config` já dividido em blocos, pronto para consulta."""

    def __init__(self) -> None:
        self._blocos: list[Bloco] = []

    # ------------------------------------------------------------------ leitura

    @classmethod
    def from_text(cls, text: str) -> SSHConfig:
        config = cls()
        config.parse(text.splitlines())
        return config

    @classmethod
    def from_file(cls, path: Path | str) -> SSHConfig:
        """Lê do disco, resolvendo `Include`. Arquivo ausente = config vazia."""
        config = cls()
        config._parse_file(Path(path), profundidade=0)
        return config

    def parse(self, linhas: list[str]) -> None:
        """Consome as linhas de um config. `Include` não é seguido aqui."""
        self._consumir(linhas, base=None, profundidade=MAX_INCLUDE_DEPTH)

    # ----------------------------------------------------------------- consulta

    def lookup(self, host: str) -> dict[str, str | list[str]]:
        """Valores efetivos para `host`, com as chaves em minúsculas."""
        resultado: dict[str, str | list[str]] = {}
        for bloco in self._blocos:
            if not bloco.casa(host):
                continue
            for chave, valor in bloco.diretivas:
                if chave in MULTIVALORADAS:
                    resultado.setdefault(chave, [])
                    lista = resultado[chave]
                    assert isinstance(lista, list)
                    lista.append(valor)
                elif chave not in resultado:
                    resultado[chave] = valor
        return resultado

    def host_names(self) -> list[str]:
        """Nomes concretos declarados em `Host`, na ordem e sem repetição.

        Padrões com curinga descrevem um conjunto, não uma máquina: só servem
        para emprestar valores aos demais.
        """
        nomes: list[str] = []
        vistos: set[str] = set()
        for bloco in self._blocos:
            for padrao in bloco.padroes:
                if tem_curinga(padrao) or padrao in vistos:
                    continue
                vistos.add(padrao)
                nomes.append(padrao)
        return nomes

    # ---------------------------------------------------------------- internos

    def _parse_file(self, caminho: Path, profundidade: int) -> None:
        try:
            texto = caminho.read_text(encoding="utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            return
        self._consumir(texto.splitlines(), base=caminho.parent, profundidade=profundidade)

    def _consumir(self, linhas: list[str], base: Path | None, profundidade: int) -> None:
        # Diretivas antes do primeiro `Host` valem para todos, como no OpenSSH.
        atual = Bloco(padroes=["*"])
        self._blocos.append(atual)

        for linha in linhas:
            item = _parse_linha(linha)
            if item is None:
                continue
            chave, valor = item

            if chave == "host":
                atual = Bloco(padroes=_tokenizar(valor))
                self._blocos.append(atual)
            elif chave == "match":
                # Match depende de contexto de execução; nada dentro dele se aplica.
                atual = Bloco(padroes=[])
                self._blocos.append(atual)
            elif chave == "include" and base is not None and profundidade < MAX_INCLUDE_DEPTH:
                self._incluir(valor, base, profundidade + 1)
            else:
                atual.diretivas.append((chave, valor))

    def _incluir(self, valor: str, base: Path, profundidade: int) -> None:
        """Resolve `Include`, que aceita curingas e caminhos relativos ao ~/.ssh."""
        for bruto in _tokenizar(valor):
            alvo = Path(bruto).expanduser()
            padrao = alvo if alvo.is_absolute() else base / alvo
            for encontrado in sorted(padrao.parent.glob(padrao.name)):
                if encontrado.is_file():
                    self._parse_file(encontrado, profundidade)


# --------------------------------------------------------------------- helpers


def tem_curinga(padrao: str) -> bool:
    """`*`, `?` e negações não descrevem uma máquina concreta."""
    return any(ch in padrao for ch in "*?!")


def _casa_padrao(host: str, padrao: str) -> bool:
    """Casamento literal do OpenSSH: só `*` e `?`, sem classes de caractere."""
    if not tem_curinga(padrao):
        return host == padrao
    # fnmatch entende `[seq]`, que o ssh_config não tem: escapa os colchetes.
    return fnmatch.fnmatchcase(host, padrao.replace("[", "[[]"))


def _parse_linha(linha: str) -> tuple[str, str] | None:
    """Devolve (chave em minúsculas, valor) ou None para linha sem conteúdo."""
    sem_comentario = linha.split("#", 1)[0]
    casamento = _LINHA.match(sem_comentario)
    if casamento is None:
        return None
    chave, valor = casamento.group(1).lower(), casamento.group(2).strip()
    return (chave, _sem_aspas(valor)) if valor else None


def _sem_aspas(valor: str) -> str:
    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
        return valor[1:-1]
    return valor


def _tokenizar(valor: str) -> list[str]:
    """Divide uma lista de padrões/caminhos, respeitando aspas."""
    tokens: list[str] = []
    for bruto in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', valor):
        limpo = _sem_aspas(bruto)
        if limpo:
            tokens.append(limpo)
    return tokens
