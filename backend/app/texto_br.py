"""Português correto no que sai do sistema — norma culta, sem atalho.

Regra da casa (decisão do dono, 29/07/2026): **nada que chegue a uma pessoa sai
fora da norma culta.** Não é preciosismo. Metade do que este produto escreve vai
para um órgão público — ofício de cobrança do art. 97, resposta a diligência — e
a outra metade vai para quem opera dinheiro público. Concordância errada num
ofício desqualifica o pedido antes de alguém ler o mérito.

## O que este módulo existe para matar

**O plural entre parênteses.** `"{n} mudança(s)"` é fuga: o número é conhecido na
hora de escrever, então "1 mudança" ou "3 mudanças" é decidível e o parêntese só
transfere para o leitor um trabalho que era nosso. Pior quando arrasta o verbo:
`"1 mudança(s) estão com o órgão"` foi o que saiu no WhatsApp em 29/07.

**A abreviação de conveniência.** `"(em 9d)"`, `"(vencido há 3d)"` — cabia
inteiro, foi encurtado por hábito de terminal. Em mensagem para pessoa, `9d` não
é português.

**O corte no meio da palavra.** `texto[:40]` produziu
`"FUNDACAO COORDENACAO DE PROJETOS,PESQUIS"`. Truncar é legítimo quando o limite
é real (parâmetro de template da Meta), cortar sílaba não é.

## O que este módulo NÃO faz

Não inventa acento em dado de origem. Razão social vem do Transferegov em caixa
alta e sem acento (`FUNDACAO`), e "corrigir" nome registrado de pessoa jurídica
seria falsear um dado, não melhorar a redação. O que se corrige é a NOSSA prosa
ao redor dele.

Não tem motor de morfologia. `qtd()` exige singular E plural do chamador de
propósito: um pluralizador automático erraria em `item -> itens`, `cidadão ->
cidadãos`, `mês -> meses`, e errar calado é pior do que obrigar a escrever os
dois. Português tem irregularidade demais para adivinhação.
"""

from __future__ import annotations

import re

RETICENCIA = "…"          # o caractere próprio, não três pontos
# pontuação que não pode ficar pendurada antes da reticência
CAUDA_FEIA = " ,;:·—-–/("


def qtd(n: int, singular: str, plural: str) -> str:
    """`3, "mudança", "mudanças"` -> `"3 mudanças"`. Com 1, concorda no singular.

    Zero vai para o plural, que é a forma correta em português ("0 mudanças",
    como "nenhuma mudança" — nunca "0 mudança"). Negativo idem, pelo módulo:
    "-1 dia" e não "-1 dias".
    """
    return f"{n} {singular if abs(n) == 1 else plural}"


def verbo(n: int, singular: str, plural: str) -> str:
    """Concorda o verbo com a quantidade: `1 -> "está"`, `3 -> "estão"`."""
    return singular if abs(n) == 1 else plural


def prazo_texto(dias: int | None) -> str:
    """O prazo por extenso, do jeito que se fala.

    `None` devolve string vazia — sem prazo apurado, o silêncio é honesto e
    inventar "sem prazo" afirmaria o que não se mediu.
    """
    if dias is None:
        return ""
    if dias == 0:
        return "vence hoje"
    if dias < 0:
        return f"vencido há {qtd(-dias, 'dia', 'dias')}"
    return f"em {qtd(dias, 'dia', 'dias')}"


def encurtar(texto: str, limite: int) -> str:
    """Encurta SEM cortar palavra, e sem deixar pontuação pendurada.

    O limite conta a reticência: o chamador pede 40 e recebe no máximo 40, senão
    o cuidado com o texto estouraria o parâmetro do template — que é um limite de
    verdade, imposto pela Meta, e não uma preferência.

    Palavra única mais longa que o limite é cortada mesmo: melhor uma palavra
    truncada do que devolver só a reticência.
    """
    texto = re.sub(r"\s+", " ", (texto or "").strip())
    if len(texto) <= limite:
        return texto
    if limite <= 1:
        return RETICENCIA[:limite]
    corte = texto[: limite - 1]
    espaco = corte.rfind(" ")
    if espaco > 0:
        corte = corte[:espaco]
    return corte.rstrip(CAUDA_FEIA) + RETICENCIA


def arejar(texto: str) -> str:
    """Conserta pontuação grudada que vem do dado de origem.

    `"PROJETOS,PESQUISAS"` -> `"PROJETOS, PESQUISAS"`. É a única intervenção que
    se faz em razão social: espaço depois de vírgula é regra de pontuação, não
    reescrita do nome. Acento que falta na origem fica faltando — ver o cabeçalho.
    """
    texto = re.sub(r"([,;:])(?=\S)", r"\1 ", (texto or "").strip())
    return re.sub(r"\s+", " ", texto)
