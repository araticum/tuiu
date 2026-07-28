"""O contexto que o redator manda ao modelo — completo, fiel e ancorado.

Pedido do dono (28/07). O primeiro rascunho real saiu genérico ("a entidade
tomará as providências cabíveis") por um motivo simples: o modelo recebia
**só o texto do parecer**. Sem instrumento, sem prazo, sem dinheiro, sem norma,
não há como redigir peça de verdade — e o que sobra é redação vazia, que é
justamente o que não se manda para um órgão.

Este módulo junta o que a casa **já sabe** sobre o caso, cada bloco com a
origem declarada, e nada além disso:

    exigência   o parecer + o que `app.parecer` extraiu dele
    instrumento nº, objeto, unidade gestora, situação (recorte g2)
    prazo       data-limite, dias, base legal (tabela `marcos`)
    dinheiro    repasse, desembolsado, %, saldo a devolver (`execucao_convenio`)
    dossiê      o que JÁ está reunido e o que falta (`dossie`, db/0024)
    norma       trechos do acervo oficial, numerados (`guia`, busca híbrida)
    regra       a versão vigente NA DATA do instrumento (`regras_normativas`)

## Ancorado quer dizer verificável

Cada bloco é rotulado com a fonte, e o prompt manda citar. Depois da resposta,
`citacoes_soltas()` procura no texto gerado toda citação legal (artigo,
portaria, lei, IN) que **não aparece em lugar nenhum do contexto** — modelo
citando norma que ninguém forneceu é a alucinação mais cara possível aqui,
porque parece exatamente com o produto.

## Fiel quer dizer que a lacuna aparece como lacuna

O que não sabemos vira campo a preencher, nunca suposição. Um `[informar o nº
do empenho]` no rascunho custa trinta segundos do operador; um número inventado
custa a credibilidade da peça inteira — e ela vai assinada.
"""

from __future__ import annotations

import re
from datetime import date

CITACAO = re.compile(
    r"\b(?:art(?:igo)?\.?\s*\d+[º°]?(?:\s*,?\s*(?:inciso\s*)?[IVXLC]+)?"
    r"|portaria\s+(?:conjunta\s+)?(?:[A-Z/]+\s+)?n?[º°]?\s*[\d./-]+"
    r"|lei\s+n?[º°]?\s*[\d./-]+"
    r"|decreto\s+n?[º°]?\s*[\d./-]+"
    r"|IN\s+[A-Z]*\s*n?[º°]?\s*[\d./-]+)", re.I)

TRECHOS_NORMA = 4      # menos e melhor: seis trechos fracos afogaram o pedido


def _num(v) -> str:
    return (f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if v is not None else "—")


def _br(d) -> str:
    return d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else (str(d or "—")[:10] or "—")


def _bloco_instrumento(con, doc: str, instrumento: str) -> list[str]:
    r = con.execute(
        "SELECT tipo, descricao, base_legal, data_limite, farol, detalhes FROM marcos"
        " WHERE cnpj=%s AND instrumento=%s ORDER BY (farol='ok'), data_limite NULLS LAST",
        (doc, str(instrumento))).fetchall()
    if not r:
        return []
    linhas = [f"Instrumento nº {instrumento}."]
    for tipo, desc, base, limite, farol, det in r[:4]:
        det = det or {}
        prazo = f" · prazo {_br(limite)}" if limite and farol != "ok" else ""
        linhas.append(f"- [{tipo}] {desc} (base: {base}){prazo}"
                      + (f" · bola com o {det.get('bola_com')}" if det.get("bola_com") else ""))
        if det.get("situacao"):
            linhas.append(f"  situação registrada: {det['situacao']}")
    return linhas


def _bloco_dinheiro(con, doc: str, instrumento: str) -> list[str]:
    r = con.execute(
        "SELECT vl_repasse, vl_desembolsado, vl_saldo_reman_tesouro, vl_saldo_conta,"
        " inicio_vigencia, fim_vigencia FROM execucao_convenio"
        " WHERE cnpj=%s AND instrumento=%s", (doc, str(instrumento))).fetchone()
    if not r:
        return []
    rep, des, devolver, conta, ini, fim = r
    pct = f" ({round(100 * float(des) / float(rep), 1)}% do repasse)" if rep and des else ""
    return [f"Repasse: {_num(rep)} · desembolsado: {_num(des)}{pct}",
            f"Saldo a devolver ao Tesouro: {_num(devolver)} · saldo em conta: {_num(conta)}",
            f"Vigência: {_br(ini)} a {_br(fim)}"]


def _bloco_dossie(doc: str, instrumento: str) -> list[str]:
    try:
        from app.dossie import checklist_estado
        d = checklist_estado(doc, str(instrumento))
    except Exception:  # noqa: BLE001 — dossiê é enriquecimento, não pode derrubar
        return []
    itens = d.get("itens") or []
    if not itens:
        return []
    feitos = [i for i in itens if i.get("feito")]
    faltam = [i for i in itens if not i.get("feito")]
    linhas = [f"Dossiê: {len(feitos)} de {len(itens)} itens reunidos."]
    if feitos:
        linhas.append("JÁ TEMOS: " + "; ".join(i.get("rotulo") or i.get("item") for i in feitos))
    if faltam:
        linhas.append("AINDA FALTA: " + "; ".join(i.get("rotulo") or i.get("item") for i in faltam))
    return linhas


def _bloco_refs(doc: str, instrumento: str, hoje: date) -> list[str]:
    """Onde o papel está. Vale citar numa peça: é referência VERIFICÁVEL, e
    citar o nº do processo mostra ao órgão que sabemos de que caso se trata."""
    try:
        from app.referencias import do_instrumento, em_texto
        return em_texto(do_instrumento(doc, instrumento, hoje))
    except Exception:  # noqa: BLE001
        return []


def _bloco_norma(exigencia: str) -> tuple[list[str], list[str]]:
    """Trechos do acervo oficial que ancoram a resposta. Devolve (linhas, fontes)."""
    try:
        from app.guia import buscar
        from app.parecer import extrair
        # busca pelo PEDIDO, não pelo parecer inteiro: o preâmbulo burocrático
        # domina a similaridade e traz trecho de "cadastro de colegiado" para
        # uma exigência de prestação de contas — foi o que aconteceu.
        alvo = (extrair(exigencia).get("pedido") or exigencia)[:300]
        hits = (buscar(alvo, k=TRECHOS_NORMA) or {}).get("resultados") or []
    except Exception:  # noqa: BLE001 — sem acervo, redige sem âncora e o prompt avisa
        return [], []
    linhas, fontes = [], []
    for n, h in enumerate(hits, 1):
        linhas.append(f"[{n}] ({h.get('documento')} · {h.get('etapa') or '—'})\n{h.get('trecho')}")
        fontes.append(h.get("documento") or "")
    return linhas, fontes


def _bloco_regra(con, hoje: date) -> list[str]:
    """A regra VIGENTE na data — a tabela é versionada de propósito (o
    saneamento era 45d até 14/07/2026 e virou 30d pela PC 45/2026), e citar a
    regra morta num ofício é o erro que o versionamento existe para evitar."""
    linhas = []
    for parametro, regime, valor, base in con.execute(
            "SELECT parametro, regime, valor, base_legal FROM regras_normativas"
            " WHERE vigencia_inicio <= %s AND (vigencia_fim IS NULL OR vigencia_fim >= %s)"
            # `especiais` é Pix, que é de ENTE (art. 166-A) e saiu do escopo em
            # 18/07. Mandar junto fez o modelo declarar, num ofício de fundação
            # de pesquisa em saúde, ciência da multa diária de Pix — contexto
            # irrelevante não é neutro, ele convida a resposta errada.
            "   AND regime <> 'especiais'"
            " ORDER BY parametro", (hoje, hoje)):
        linhas.append(f"- {parametro} ({regime}): {valor} — {base}")
    return linhas[:8]


def montar(con, doc: str, instrumento: str, exigencia: str, hoje: date | None = None) -> dict:
    """O dossiê do caso, em blocos rotulados pela origem."""
    hoje = hoje or date.today()
    norma, fontes = _bloco_norma(exigencia)
    blocos = {
        "EXIGÊNCIA DO ÓRGÃO (texto do parecer)": [exigencia],
        "INSTRUMENTO E PRAZOS (motor de prazos do Tuiú)": _bloco_instrumento(con, doc, instrumento),
        "EXECUÇÃO FINANCEIRA (dados abertos SICONV/detru)": _bloco_dinheiro(con, doc, instrumento),
        "DOCUMENTAÇÃO JÁ REUNIDA (dossiê interno)": _bloco_dossie(doc, instrumento),
        "REFERÊNCIAS DOCUMENTAIS (processo SEI, publicação no DOU)": _bloco_refs(doc, instrumento, hoje),
        "REGRAS VIGENTES NESTA DATA (tabela versionada)": _bloco_regra(con, hoje),
        "ACERVO OFICIAL — cite por [n] (manuais e portarias do Transferegov)": norma,
    }
    texto = "\n\n".join(f"===== {titulo} =====\n" + "\n".join(linhas)
                        for titulo, linhas in blocos.items() if linhas)
    return {"texto": texto, "blocos": {k: v for k, v in blocos.items() if v}, "fontes": fontes}


def citacoes_soltas(resposta: str, contexto: str) -> list[str]:
    """Citações legais na resposta que NÃO aparecem no contexto fornecido.

    Modelo citando norma que ninguém deu é a alucinação mais cara aqui: sai
    parecendo exatamente com o produto, e vai assinada para um órgão que
    conhece a norma melhor que nós.
    """
    def _chave(s: str) -> str:
        # "ARTIGO 97, I" e "art. 97, I" são a MESMA citação. Acusar diferença de
        # grafia treina o operador a ignorar o aviso — e aí o dia da citação
        # inventada de verdade passa junto.
        s = re.sub(r"\bartigos?\b", "art", s.lower())
        s = re.sub(r"\binciso\b", "", s)
        return re.sub(r"[^a-z0-9]", "", s)

    no_contexto = {_chave(c) for c in CITACAO.findall(contexto or "")}
    soltas = []
    for c in CITACAO.findall(resposta or ""):
        if _chave(c) not in no_contexto:
            soltas.append(c.strip())
    return sorted(set(soltas))
