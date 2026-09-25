"""Pseudonimização reversível — o que sai daqui não identifica ninguém.

Decisão do dono (28/07): a redação da resposta ao parecer vai para a DeepInfra,
mas **tratando o dado na entrada para retirar e na saída para recompor**. O
processador externo nunca vê de quem é o caso: recebe `[[CLIENTE]]`,
`[[CNPJ]]`, `[[PESSOA_1]]`, devolve o texto com os mesmos marcadores, e a
recomposição acontece aqui dentro.

Diferente de `ferramentas/mascarar_recortes.py`, que reduz nome a iniciais para
GRAVAR em disco: aquilo é irreversível de propósito. Aqui a volta é o objetivo,
então o mapa existe — em memória, no escopo da chamada, nunca persistido.

## Duas travas, e a primeira é a que importa

- **`vazou()`** — depois de mascarar, nenhum identificador conhecido pode
  sobrar no texto. É a checagem que autoriza o envio; falhou, não manda.
- **`perdidos()`** — todo marcador que foi tem que voltar. Modelo que come um
  `[[CLIENTE]]` devolve texto que parece pronto e está furado.

## O que este módulo NÃO resolve

Pseudonimizar reduz o risco, não o zera: o corpo do parecer pode identificar por
contexto (objeto do convênio, valor exato, número do edital). Por isso o teto
segue sendo o do gate — e por isso o `PRIVACY.md` §2 é respondido antes de
ligar, não depois.
"""

from __future__ import annotations

import re
import unicodedata

CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
TELEFONE = re.compile(r"\b(?:\+55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b")

# `[[X]]` e não `<X>` ou `{X}`: colchete duplo sobrevive melhor à reescrita do
# modelo (não é sintaxe de nada) e a recomposição ainda aceita `[X]` solto,
# porque modelo às vezes "limpa" a duplicação.
MARCADOR = "[[{}]]"
_ACHA_MARCADOR = re.compile(r"\[\[([A-Z_0-9]+)\]\]|\[([A-Z_0-9]+)\]")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _variantes(valor: str) -> list[str]:
    """Como o mesmo nome costuma aparecer: o parecer escreve "Fundação X", o
    cadastro guarda "FUNDACAO X". Sem cobrir isso, o nome escapa em uma das
    grafias e a máscara vira teatro."""
    base = valor.strip()
    formas = {base, base.upper(), base.title(), _sem_acento(base),
              _sem_acento(base).upper(), _sem_acento(base).title()}
    # do mais longo para o mais curto: senão "FUNDACAO" consome o prefixo de
    # "FUNDACAO FACULDADE DE MEDICINA" e sobra "FACULDADE DE MEDICINA" em claro
    return sorted((f for f in formas if len(f) >= 4), key=len, reverse=True)


def mascarar(texto: str, conhecidos: dict[str, str] | None = None) -> tuple[str, dict[str, str]]:
    """Troca identificadores por marcadores. Devolve (texto, mapa marcador->original).

    `conhecidos` são os que sabemos de antemão (cliente, representante, órgão),
    aplicados primeiro por serem os mais perigosos e os que a regex não pega.
    Depois vem a varredura de formato — CNPJ, CPF, e-mail, telefone — que
    alcança o que estava escondido no meio do parecer.
    """
    texto = str(texto or "")
    mapa: dict[str, str] = {}

    # do valor mais LONGO para o mais curto, ENTRE os conhecidos e não só dentro
    # de cada um: com "FUNDACAO" trocado antes de "FUNDACAO FACULDADE DE
    # MEDICINA", sobrava "FACULDADE DE MEDICINA" em claro no texto que sai.
    itens = sorted((conhecidos or {}).items(),
                   key=lambda kv: len(str(kv[1] or "")), reverse=True)
    for rotulo, valor in itens:
        if not str(valor or "").strip():
            continue
        marcador = MARCADOR.format(rotulo)
        for forma in _variantes(str(valor)):
            if forma in texto:
                texto = texto.replace(forma, marcador)
                mapa[marcador] = str(valor)

    for rotulo, padrao in (("CNPJ", CNPJ), ("CPF", CPF), ("EMAIL", EMAIL), ("TELEFONE", TELEFONE)):
        vistos: dict[str, str] = {}
        for achado in padrao.findall(texto):
            if achado in vistos:
                continue
            marcador = MARCADOR.format(f"{rotulo}_{len(vistos) + 1}")
            vistos[achado] = marcador
            mapa[marcador] = achado
        for original, marcador in vistos.items():
            texto = texto.replace(original, marcador)

    return texto, mapa


def recompor(texto: str, mapa: dict[str, str]) -> str:
    """Devolve os originais. Aceita `[[X]]` e `[X]` — modelo às vezes "limpa" a
    duplicação, e recusar por isso jogaria fora um texto bom."""
    def _troca(m: re.Match) -> str:
        nome = m.group(1) or m.group(2)
        return mapa.get(MARCADOR.format(nome), m.group(0))
    return _ACHA_MARCADOR.sub(_troca, str(texto or ""))


def vazou(texto: str, mapa: dict[str, str]) -> list[str]:
    """Identificadores que SOBRARAM depois de mascarar. Tem que ser [].

    É esta lista que autoriza o envio: não é conferência de qualidade, é a
    condição de não mandar dado de terceiro para fora.
    """
    restos = []
    for original in mapa.values():
        for forma in _variantes(original):
            if forma in texto:
                restos.append(original)
                break
    for padrao in (CNPJ, CPF, EMAIL):
        restos += padrao.findall(texto)
    return sorted(set(restos))


def perdidos(texto: str, mapa: dict[str, str]) -> list[str]:
    """Marcadores que foram e não voltaram — o modelo comeu."""
    return sorted(m for m in mapa if m not in texto
                  and m.replace("[[", "[").replace("]]", "]") not in texto)
