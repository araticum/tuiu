"""Conferência de parcela — o documento que responde "a parcela saiu?".

Pergunta do dono (28/07): `parcela_prevista` era o único marco acionável sem
peça, e faltava definir **qual documento conferir**. A resposta veio da medição,
não do desenho: o mapa da g2 documenta a cadeia NE → DH → OP → OB, mas no
recorte da carteira **três dos quatro elos estão vazios**.

    cronograma-desembolso   70 linhas em 6 entes   (a parcela prevista)
    empenho-parceria         0
    documento-habil          0
    ordem-pagamento          0
    extrato-bancario       405 linhas em 4 entes   ← o único que existe

Então o documento a conferir é o **extrato bancário da conta da parceria**.
Conferir o que não existe seria teatro: a peça diz o que dá para verificar hoje
e nomeia o que falta, em vez de fingir uma cadeia completa.

Caminho no recorte: `proposta` → `parceria` (id_proposta) → `parceria-conta`
(id_parceria) → `extrato-bancario` (id_parceria_conta).

## O que a peça conclui

A parcela vem com mês/ano e valor — o cronograma **não tem dia**, então o motor
usa o último dia do mês e a conferência procura crédito **naquele mês e depois**
(dinheiro público costuma atrasar, nunca adiantar). Três desfechos:

- **crédito compatível** — a parcela saiu; nada a cobrar;
- **crédito de valor diferente** — saiu parcial ou somado a outra; mostra os
  lançamentos e deixa a conciliação para o operador, que é quem sabe;
- **nenhum crédito** — aí sim é cobrança, e o ofício do art. 97 já existe.

Nunca afirma "não saiu" quando a conta não tem extrato no recorte: ausência de
dado não é ausência de fato, e essa distinção é a diferença entre cobrar com
razão e cobrar errado.
"""

from __future__ import annotations

import calendar
import gzip
import json
from datetime import date

from app.carteira import snapshot_mais_recente

TOLERANCIA = 0.02      # 2% — arredondamento de tarifa/centavo, não parcela parcial


def _linhas(doc: str, rota: str) -> list[dict]:
    snap = snapshot_mais_recente()
    if snap is None:
        return []
    arq = snap / doc / "parcerias" / f"{rota}.jsonl.gz"
    if not arq.exists():
        return []
    with gzip.open(arq, "rt", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _contas_da_proposta(doc: str, id_proposta) -> list[dict]:
    alvo = str(id_proposta)
    parcerias = {str(p.get("id_parceria")) for p in _linhas(doc, "parceria")
                 if str(p.get("id_proposta")) == alvo}
    return [c for c in _linhas(doc, "parceria-conta")
            if str(c.get("id_parceria")) in parcerias]


def _creditos(doc: str, contas: list[dict], desde: date) -> list[dict]:
    ids = {str(c.get("id_parceria_conta")) for c in contas}
    out = []
    for e in _linhas(doc, "extrato-bancario"):
        if str(e.get("id_parceria_conta")) not in ids:
            continue
        if (e.get("in_transacao") or "").lower() != "crédito":
            continue
        quando = str(e.get("dt_movimento_lancamento_extrato_bancario") or "")[:10]
        try:
            if date.fromisoformat(quando) < desde:
                continue
        except ValueError:
            continue
        out.append({"quando": quando, "valor": float(e.get("vl_lancamento_extrato_bancario") or 0),
                    "tipo": e.get("nm_tipo_operacao")})
    return sorted(out, key=lambda x: x["quando"])


def conferir(doc: str, id_item_cronograma) -> dict:
    """Estado da parcela contra o extrato. Não levanta; degrada informando."""
    doc = "".join(c for c in (doc or "") if c.isdigit())
    alvo = str(id_item_cronograma)
    item = next((c for c in _linhas(doc, "cronograma-desembolso")
                 if str(c.get("id_proposta_cronograma_item")) == alvo), None)
    if item is None:
        return {"disponivel": False, "erro": "parcela não encontrada no recorte"}

    mes, ano = item.get("nr_ref_mes_data_especif"), item.get("nr_ref_ano_data_especif")
    try:
        # mesmo cálculo do motor: o cronograma não traz dia
        prevista = date(int(ano), int(mes), calendar.monthrange(int(ano), int(mes))[1])
        desde = date(int(ano), int(mes), 1)
    except (TypeError, ValueError):
        return {"disponivel": False, "erro": "parcela sem mês/ano de referência"}

    valor = float(item.get("vl_cronograma_desembolso") or 0)
    contas = _contas_da_proposta(doc, item.get("id_proposta"))
    creditos = _creditos(doc, contas, desde)
    compativel = [c for c in creditos if valor and abs(c["valor"] - valor) <= valor * TOLERANCIA]

    if not contas:
        veredito = "sem_conta"
    elif compativel:
        veredito = "liberada"
    elif creditos:
        veredito = "credito_divergente"
    else:
        veredito = "sem_credito"

    return {"disponivel": True, "veredito": veredito, "prevista": prevista.isoformat(),
            "valor": valor, "origem": item.get("origem_recurso"),
            "id_proposta": item.get("id_proposta"), "contas": contas,
            "creditos": creditos, "compativel": compativel}


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _br(iso: str) -> str:
    return "/".join(reversed(iso[:10].split("-"))) if iso else "—"


VEREDITOS = {
    "liberada": ("✅ Parcela LOCALIZADA no extrato", "Nada a cobrar."),
    "credito_divergente": ("⚠️ Há crédito, mas em valor diferente do previsto",
                           "Conciliar: pode ser liberação parcial, ou parcelas somadas "
                           "num lançamento só."),
    "sem_credito": ("🔴 NENHUM crédito no período",
                    "Cobrar a liberação junto ao concedente."),
    "sem_conta": ("❔ Conta da parceria não está no recorte",
                  "Sem extrato não dá para afirmar que não saiu — conferir no Transferegov "
                  "antes de cobrar."),
}


def markdown(doc: str, id_item_cronograma) -> dict:
    """A peça: o que era esperado, o que o extrato mostra, e o que fazer."""
    d = conferir(doc, id_item_cronograma)
    if not d.get("disponivel"):
        return d
    titulo, acao = VEREDITOS[d["veredito"]]

    contas = "\n".join(
        f"- {c.get('nm_banco')} · ag. {c.get('tx_numero')} · c/c {c.get('tx_conta')}"
        f" — {c.get('nm_conta')} ({c.get('tx_descricao')})"
        + (f"\n  > ⚠️ {c.get('tx_detalhamento')}" if c.get("tx_detalhamento") else "")
        for c in d["contas"]) or "- _(nenhuma conta de parceria no recorte)_"

    lancamentos = "\n".join(
        f"| {_br(c['quando'])} | {_brl(c['valor'])} | {c['tipo'] or '—'} |"
        for c in d["creditos"]) or "| — | _nenhum crédito no período_ | — |"

    return {"disponivel": True, "veredito": d["veredito"],
            "titulo": f"Conferência de parcela — {_brl(d['valor'])} prevista para {_br(d['prevista'])}",
            "markdown": (
                f"## {titulo}\n\n"
                f"**O que estava pactuado:** {_brl(d['valor'])}, referência "
                f"{_br(d['prevista'])[3:]} (origem: {d.get('origem') or '—'}), "
                f"proposta nº {d.get('id_proposta')}.\n\n"
                f"**Conta(s) da parceria:**\n{contas}\n\n"
                f"**Créditos no extrato a partir de {_br(d['prevista'])[3:]}:**\n\n"
                f"| Data | Valor | Operação |\n|---|---:|---|\n{lancamentos}\n\n"
                f"**O que fazer:** {acao}\n\n"
                f"---\n_Conferido contra o extrato bancário da conta da parceria — único elo "
                f"da cadeia NE→DH→OP→OB presente no dado aberto desta carteira. Ausência de "
                f"lançamento aqui não prova que o recurso não saiu; prova que não consta._\n")}
