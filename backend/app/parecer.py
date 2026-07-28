"""Parse do parecer do órgão — o que a PLATAFORMA cobra de quem opera.

Escopo, definido pelo dono em 28/07/2026: o Tuiú operacionaliza o Transferegov,
**não** a execução do serviço. Então daqui sai *"o órgão exigiu X, responda até
tal dia, senão arquiva"* — nunca uma opinião sobre o mérito técnico do objeto,
que é de quem recebeu a verba.

## O defeito que isto conserta

`ds_parecer` vem com até 4,2 mil caracteres e era cortado TRÊS vezes até chegar
em quem opera: 600 no motor, 400 na mesa/notificador, 300 no parâmetro do
WhatsApp. Como todo corte era pelo COMEÇO, o que sobrava era a abertura
burocrática e o que sumia era o fim — justamente onde mora a consequência.

Medido num parecer real de complementação (811 chars):

    chegava  "…realize os ajustes necessários … no prazo de 10 dias corridos,
              até o dia 20/04/2026, em atendimento ao prazo previst"   ← corta no meio
    sumia    "o não cumprimento … resultará no ARQUIVAMENTO da proposta"

Trezentos caracteres é o que se lê no celular. A questão nunca foi o tamanho:
era gastar o orçamento com o preâmbulo em vez do que faz agir.

## Como extrai

Determinístico, sem modelo de linguagem: o texto é administrativo e repetitivo,
e regra explícita erra de forma previsível — dá para ver o que ela não pegou.
Cada campo é OPCIONAL e o texto cru fica guardado inteiro; quando nada casa, o
chamador cai no começo do parecer, que é o comportamento de hoje.
"""

from __future__ import annotations

import re

# O texto vem sem espaço depois do ponto ("proposta.Uma vez arquivada"), então
# quebrar em ". " perderia frase. Corta no ponto seguido de maiúscula/acentuada.
FIM_DE_FRASE = re.compile(r"(?<=[.;:])(?=[A-ZÁÂÃÀÉÊÍÓÔÕÚÇ])|(?<=[.;:])\s+")

# o miolo opcional é SÓ o parêntese por extenso ("10 (dez) dias"). Uma versão
# anterior aceitava qualquer coisa ali (`[^)]{0,20}`) e engolia " dias corridos,
# até o", casando o `dias?` com o "dia" de "até o dia" — o prazo era achado, mas
# a contagem sumia. Regex frouxa erra calada.
PRAZO_DIAS = re.compile(r"prazo de\s+(\d{1,3})(?:\s*\([^)]{1,20}\))?\s*dias?"
                        r"(?:\s+(corridos|úteis|uteis))?", re.I)
PRAZO_DATA = re.compile(r"at[ée]\s+(?:o\s+dia\s+)?(\d{2}/\d{2}/\d{4})", re.I)

# ordem importa: a consequência é o que move o operador, então é procurada antes
CONSEQUENCIA = re.compile(
    r"\b(resultar[áa]|acarretar[áa]|implicar[áa]|sob pena|ser[áa] arquivad|"
    r"arquivamento|desabilita[çc][ãa]o|indeferimento|cancelamento|"
    r"n[ãa]o ser[áa] analisad)", re.I)
PEDIDO = re.compile(
    r"\b(solicitamos|solicita-se|dever[áa]|deve apresentar|apresentar|"
    r"complementa[çc][ãa]o|dilig[êe]ncia|ajustes?|corrigir|reenvi|regulariz)", re.I)
ONDE = re.compile(r"m[óo]dulo\s+([A-Za-zÀ-ÿ]+(?:\s+(?:de|da|do|e)?\s*[A-Za-zÀ-ÿ]+){0,3})", re.I)

LIMITE_FRASE = 220


def _frases(texto: str) -> list[str]:
    limpo = " ".join(str(texto or "").split())
    return [f.strip() for f in FIM_DE_FRASE.split(limpo) if f and f.strip()]


def _corta(frase: str) -> str:
    return frase[:LIMITE_FRASE - 1].rstrip() + "…" if len(frase) > LIMITE_FRASE else frase


def _trecho(frase: str, m: re.Match) -> str:
    """Recorta A PARTIR do gatilho, não do começo da frase.

    A frase administrativa é longa e começa em preâmbulo ("Salienta-se que,
    conforme previsto no dispositivo supracitado, na fase de admissibilidade…"),
    com o desfecho — *resultará no arquivamento* — lá no fim. Cortar pelo começo
    enterrava a notícia outra vez, que é justamente o defeito que este módulo
    existe para consertar.
    """
    if len(frase) <= LIMITE_FRASE:
        return frase
    ini = max(0, m.start())
    fim = ini + LIMITE_FRASE - 1
    trecho = frase[ini:fim].rstrip()
    return ("…" if ini else "") + trecho + ("…" if fim < len(frase) else "")


def extrair(texto: str) -> dict:
    """Campos procedimentais do parecer. Todos opcionais — nada é inventado."""
    frases = _frases(texto)
    inteiro = " ".join(frases)
    out: dict = {}

    if m := PRAZO_DIAS.search(inteiro):
        out["prazo_dias"] = int(m.group(1))
        if m.group(2):
            out["prazo_contagem"] = m.group(2).lower().replace("uteis", "úteis")
    if m := PRAZO_DATA.search(inteiro):
        out["prazo_data"] = m.group(1)
    if m := ONDE.search(inteiro):
        out["onde"] = m.group(1).strip()

    for f in frases:
        if "consequencia" not in out and (m := CONSEQUENCIA.search(f)):
            out["consequencia"] = _trecho(f, m)
        if "pedido" not in out and (m := PEDIDO.search(f)):
            out["pedido"] = _corta(f)     # o pedido costuma abrir a frase
    return out


def resumo(texto: str, limite: int = 300) -> str:
    """A linha que vai para a mesa e para o WhatsApp.

    Ordem deliberada — **pedido, prazo, consequência**: é a sequência em que o
    operador decide (o que fazer, até quando, o que acontece se não fizer). Sem
    nenhum campo reconhecido, devolve o começo do texto, que é o que já se fazia:
    o parse pode falhar, a informação não pode sumir.
    """
    d = extrair(texto)
    partes = []
    if d.get("pedido"):
        partes.append(d["pedido"])
    if d.get("prazo_data") or d.get("prazo_dias"):
        prazo = "Prazo: "
        if d.get("prazo_dias"):
            prazo += f"{d['prazo_dias']} dias {d.get('prazo_contagem', '')}".strip()
        if d.get("prazo_data"):
            prazo += (" · " if d.get("prazo_dias") else "") + f"até {d['prazo_data']}"
        partes.append(prazo)
    if d.get("consequencia"):
        partes.append(f"Se não cumprir: {d['consequencia']}")

    texto_final = " · ".join(partes) if partes else " ".join(_frases(texto))
    return texto_final[:limite - 1].rstrip() + "…" if len(texto_final) > limite else texto_final
