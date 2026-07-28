"""Camada de AÇÃO: transforma o diagnóstico do motor em peça pronta para enviar.

O motor diz "cobre o concedente, art. 97 vencido há 233 dias". Aqui isso vira o
OFÍCIO de cobrança pronto — e a diligência vira um esqueleto de resposta com o
que o órgão pediu já transcrito. Segue a decisão da F3: documento = markdown
colável (sem pdf-render/A1). O Tuiú faz o rascunho pesado; o operador revisa,
completa a assinatura e envia.

Fonte: os marcos que o motor JÁ produz (proposta_parada, complementacao_pendente)
mais o cadastro do cliente e, quando há, a proposta do recorte g2 (unidade
gestora, objeto íntegro). Sem inventar dado: o que falta vira campo a preencher.
"""

from __future__ import annotations

import gzip
import json
from datetime import date

from app.carteira import ROTULOS, snapshot_mais_recente
# a peça vai para um ÓRGÃO: enum cru do CSV ('PRESTACAO_CONTAS_ENVIADA_ANALISE')
# num ofício é desleixo que o leitor atribui ao remetente
from app.cliente_ficha import _humaniza
from app.db import conectar

_MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
          "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _hoje_extenso(municipio: str | None, uf: str | None, hoje: date) -> str:
    local = f"{municipio}/{uf}" if municipio and uf else (municipio or uf or "")
    data = f"{hoje.day} de {_MESES[hoje.month]} de {hoje.year}"
    return f"{local}, {data}".lstrip(", ")


def _cnpj_fmt(doc: str) -> str:
    d = "".join(c for c in (doc or "") if c.isdigit())
    if len(d) != 14:
        return doc
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _iso_br(s: str | None) -> str:
    s = (s or "")[:10]
    try:
        return date.fromisoformat(s).strftime("%d/%m/%Y")
    except ValueError:
        return s or "—"


def _proposta_g2(doc: str, id_proposta) -> dict:
    """Acha a proposta no recorte g2 para enriquecer (unidade gestora, objeto)."""
    snap = snapshot_mais_recente()
    if snap is None:
        return {}
    arq = snap / doc / "parcerias" / "proposta.jsonl.gz"
    if not arq.exists():
        return {}
    alvo = str(id_proposta)
    with gzip.open(arq, "rt", encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            p = json.loads(linha)
            if str(p.get("id_proposta")) == alvo:
                return p
    return {}


def _cliente(con, doc: str) -> dict:
    r = con.execute(
        "SELECT nome, apelido, municipio, uf FROM clientes WHERE doc=%s", (doc,)).fetchone()
    nome = (r[0] if r else None) or ROTULOS.get(doc, doc)
    cli = {"nome": nome, "municipio": r[2] if r else None, "uf": r[3] if r else None}
    # pega o representante em Python (evita LIKE com % literal no SQL parametrizado,
    # que o psycopg lê como placeholder): prioriza quem tem papel de dirigência.
    pessoas = con.execute(
        "SELECT nome, papel FROM clientes_pessoas WHERE doc_cliente=%s AND ativo ORDER BY nome",
        (doc,)).fetchall()

    def _rank(papel: str | None) -> int:
        pl = (papel or "").lower()
        return 0 if any(t in pl for t in ("repres", "presid", "dirig")) else 1

    pessoas.sort(key=lambda x: _rank(x[1]))
    rep = pessoas[0] if pessoas else None
    cli["representante"] = rep[0] if rep else None
    cli["papel_rep"] = (rep[1] if rep else None) or "representante legal"
    return cli


def _marco(con, doc: str, id_proposta, tipo: str) -> dict | None:
    r = con.execute(
        "SELECT descricao, base_legal, detalhes FROM marcos"
        " WHERE cnpj=%s AND instrumento=%s AND tipo=%s", (doc, str(id_proposta), tipo)).fetchone()
    if not r:
        return None
    det = r[2] if isinstance(r[2], dict) else json.loads(r[2] or "{}")
    return {"descricao": r[0], "base_legal": r[1], "detalhes": det}


def _assinatura(cli: dict, hoje: date) -> str:
    return (f"\n\n{_hoje_extenso(cli['municipio'], cli['uf'], hoje)}.\n\n"
            "______________________________________\n"
            f"{cli.get('representante') or '[nome do representante legal]'}\n"
            f"{cli['papel_rep']} — CPF: ____________________\n"
            f"{cli['nome']}")


def montar_cobranca(cli: dict, doc: str, id_proposta, det: dict, prop: dict, hoje: date) -> str:
    """Composição PURA do ofício (testável sem banco)."""
    dias = det.get("dias_em_analise")
    venc = det.get("vencido_ha_dias")
    limite = det.get("limite_informatizado", 60)
    objeto = (prop.get("ds_objeto") or det.get("objeto") or "—").strip()
    ug = (prop.get("nm_unidade_gestora") or "").strip() or "[unidade gestora concedente]"
    envio = _iso_br(prop.get("dt_envio_analise"))
    up = det.get("ultimo_parecer") or {}
    nota_parecer = (
        f"\n\n3. Registra-se que o último parecer emitido (fase {up.get('fase') or '—'}) "
        f"indicou o resultado \"{up.get('resultado') or '—'}\", sem que a decisão final "
        "sobreviesse no prazo legal."
        if up else "")
    return (
        f"**{cli['nome']}**  \n"
        f"CNPJ nº {_cnpj_fmt(doc)}\n\n"
        f"**Ofício de cobrança — Proposta nº {id_proposta}**\n\n"
        f"**A(o) {ug}**\n\n"
        f"**Assunto:** Requerimento de conclusão da análise da Proposta nº {id_proposta} — "
        f"art. 97 da Portaria Conjunta nº 33/2023.\n\n"
        "Senhor(a) Gestor(a),\n\n"
        f"1. A {cli['nome']}, inscrita no CNPJ sob o nº {_cnpj_fmt(doc)}, apresentou a "
        f"Proposta nº {id_proposta}, cujo objeto é \"{objeto}\", encaminhada para análise "
        f"em {envio}.\n\n"
        f"2. Decorridos {dias} dias do envio, a proposta permanece sem decisão. Nos termos "
        f"do art. 97, inciso I, e §1º, da Portaria Conjunta nº 33/2023, o prazo para análise "
        f"pelo concedente, no processamento informatizado, é de {limite} (sessenta) dias — "
        f"encontrando-se, portanto, **vencido há {venc} dias**."
        f"{nota_parecer}\n\n"
        f"{'4' if up else '3'}. Diante do exposto, requer-se a conclusão da análise da "
        "proposta no menor prazo possível, ou, subsidiariamente, a informação motivada sobre "
        "o que obsta a decisão, para fins de acompanhamento e de resguardo dos prazos do "
        "instrumento.\n\n"
        "Nestes termos, pede deferimento."
        f"{_assinatura(cli, hoje)}\n")


def cobranca_art97(doc: str, id_proposta, hoje: date | None = None) -> dict:
    """Ofício de cobrança da análise vencida — a peça que arma o art. 97."""
    hoje = hoje or date.today()
    doc = "".join(c for c in doc if c.isdigit())
    with conectar() as con:
        m = _marco(con, doc, id_proposta, "proposta_parada")
        if not m:
            return {"disponivel": False,
                    "erro": "não há marco de proposta parada (art. 97) para esta proposta"}
        cli = _cliente(con, doc)
    md = montar_cobranca(cli, doc, id_proposta, m["detalhes"], _proposta_g2(doc, id_proposta), hoje)
    return {"disponivel": True,
            "titulo": f"Cobrança art. 97 — Proposta {id_proposta}",
            "markdown": md}


def montar_diligencia(cli: dict, doc: str, id_proposta, det: dict, prop: dict, hoje: date) -> str:
    """Composição PURA da resposta à diligência (testável sem banco)."""
    up = det.get("ultimo_parecer") or {}
    parecer = (up.get("parecer") or "").strip()
    objeto = (prop.get("ds_objeto") or "").strip() or "—"
    fase = up.get("fase") or "—"
    exigencia = (f"> {parecer}\n" if parecer
                 else "> _(o parecer não trouxe texto; consultar a diligência no Transferegov)_\n")
    return (
        f"**{cli['nome']}**  \n"
        f"CNPJ nº {_cnpj_fmt(doc)}\n\n"
        f"**Resposta à diligência — Proposta nº {id_proposta}**\n\n"
        f"Em atenção à diligência da fase {fase}, referente à Proposta nº {id_proposta} "
        f"(objeto \"{objeto}\"), que solicitou:\n\n"
        f"{exigencia}\n"
        f"a {cli['nome']} manifesta-se e complementa:\n\n"
        "1. [Responder ponto a ponto o que foi exigido acima, anexando os documentos "
        "solicitados. Cada item da diligência = um item aqui.]\n\n"
        "2. [Se algum ponto não se aplica, justificar o motivo.]\n\n"
        "Permanecemos à disposição para os esclarecimentos que se fizerem necessários."
        f"{_assinatura(cli, hoje)}\n")


def resposta_diligencia(doc: str, id_proposta, hoje: date | None = None) -> dict:
    """Esqueleto de resposta à diligência/complementação, com o que o órgão pediu
    já transcrito — para o operador responder ponto a ponto, não do zero."""
    hoje = hoje or date.today()
    doc = "".join(c for c in doc if c.isdigit())
    with conectar() as con:
        m = _marco(con, doc, id_proposta, "complementacao_pendente")
        if not m:
            return {"disponivel": False,
                    "erro": "não há marco de complementação pendente para esta proposta"}
        cli = _cliente(con, doc)
    md = montar_diligencia(cli, doc, id_proposta, m["detalhes"], _proposta_g2(doc, id_proposta), hoje)
    return {"disponivel": True,
            "titulo": f"Resposta à diligência — Proposta {id_proposta}",
            "markdown": md}


def montar_cobranca_analise(cli: dict, doc: str, det: dict, hoje: date) -> str:
    """Composição PURA da cobrança do art. 97 no caso LEGADO (testável sem banco).

    Peça irmã da `montar_cobranca`, não a mesma: lá o marco é POR PROPOSTA do
    ciclo novo (`dias_em_analise`); aqui é um agregado por cliente — o motor
    junta todas as prestações paradas do convenente num marco só, com as piores
    em `piores[]`. Um ofício por prestação seria uma pilha de cartas idênticas
    para o mesmo órgão; uma carta que lista todas é o que se manda de verdade.
    """
    piores = det.get("piores") or []
    limite = det.get("limite_dias")
    total = det.get("total") or len(piores)
    linhas = "\n".join(
        f"| {p.get('instrumento')} | {_humaniza(p.get('situacao')) or '—'} | "
        f"{_iso_br(p.get('desde'))} | {p.get('dias')} |"
        for p in piores[:10])
    resto = (f"\n\n_(...e outras {total - len(piores[:10])} prestações na mesma situação.)_"
             if total > len(piores[:10]) else "")
    return (
        f"**{cli['nome']}**  \n"
        f"CNPJ nº {_cnpj_fmt(doc)}\n\n"
        f"**Ofício — cobrança de análise de prestação de contas (art. 97)**\n\n"
        f"Ao órgão concedente,\n\n"
        f"A {cli['nome']} apresentou as prestações de contas relacionadas abaixo, que "
        f"permanecem **aguardando análise** do concedente por prazo superior ao previsto "
        f"no art. 97 da Portaria Conjunta 33/2023 "
        f"({limite} dias para a análise convencional):\n\n"
        f"| Instrumento | Situação | Desde | Dias parados |\n"
        f"|---|---|---|---:|\n{linhas}{resto}\n\n"
        f"São **{total}** prestação(ões) nessa condição. Como o prazo de análise é do "
        f"concedente e já está vencido, o atraso não é imputável a esta entidade — o que "
        f"afasta os efeitos de inadimplência dele decorrentes.\n\n"
        f"Requer-se, assim, a conclusão da análise, ou a informação do prazo em que se dará, "
        f"nos termos do art. 97, I e § 1º."
        f"{_assinatura(cli, hoje)}\n")


def cobranca_analise(doc: str, id_proposta=None, hoje: date | None = None) -> dict:
    """Cobrança do art. 97 sobre as prestações paradas no concedente (legado).

    `id_proposta` é ignorado de propósito: o marco é do CLIENTE, não de um
    instrumento — a assinatura fica igual à das outras para caber no GERADORES.
    """
    hoje = hoje or date.today()
    doc = "".join(c for c in doc if c.isdigit())
    with conectar() as con:
        r = con.execute(
            "SELECT detalhes FROM marcos WHERE cnpj=%s AND tipo='analise_parada_concedente'"
            " AND farol <> 'ok' LIMIT 1", (doc,)).fetchone()
        if not r:
            return {"disponivel": False,
                    "erro": "não há prestação parada no concedente para este cliente"}
        det = r[0] if isinstance(r[0], dict) else json.loads(r[0] or "{}")
        cli = _cliente(con, doc)
    return {"disponivel": True,
            "titulo": f"Cobrança art. 97 — {det.get('total')} prestação(ões) parada(s)",
            "markdown": montar_cobranca_analise(cli, doc, det, hoje)}


GERADORES = {"cobranca-art97": cobranca_art97, "resposta-diligencia": resposta_diligencia,
             "cobranca-analise": cobranca_analise}

# Qual peça serve cada marco. É o mapa que a triagem consulta para dizer
# "minuta pronta" em vez de só "responda a diligência" — o operador chega no
# rascunho, não na tarefa em branco.
PECA_POR_MARCO = {
    "proposta_parada": ("cobranca-art97", "Ofício de cobrança (art. 97)"),
    "analise_parada_concedente": ("cobranca-analise", "Ofício de cobrança (art. 97)"),
    "complementacao_pendente": ("resposta-diligencia", "Resposta à diligência"),
    # prestação de contas não é ofício: a peça é o CHECKLIST do dossiê, que diz
    # documento a documento o que falta juntar (db/0024)
    "prestacao_contas": ("dossie", "Checklist do dossiê"),
}


def peca_de(tipo_marco: str, cnpj: str, instrumento, console_url: str) -> dict | None:
    """Onde está a peça pronta deste item — ou None quando não há."""
    achado = PECA_POR_MARCO.get(tipo_marco)
    if not achado:
        return None
    chave, titulo = achado
    if chave == "dossie":
        url = f"{console_url}/cliente.html?doc={cnpj}"
    else:
        url = f"{console_url}/api/minuta/{cnpj}?tipo={chave}&proposta={instrumento or '-'}"
    return {"tipo": chave, "titulo": titulo, "url": url}
