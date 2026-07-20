"""Ficha do cliente — a tela que o operador abre quando o cliente liga.

Reúne num lugar só tudo do terceiro que a casa opera: cadastro e dirigentes,
carteira (ciclo novo g2 + legado), regularidade (da entidade E dos dirigentes),
prazos abertos, andamento recente, resumo da prestação de contas e o diário de
atendimento.
"""

from __future__ import annotations

import csv
import gzip
import json
from datetime import date, datetime

from app.carteira import ROTULOS, listar_entes, snapshot_mais_recente
from app.db import conectar


def _risco_orgaos(con, doc: str) -> list[dict]:
    """Base rate de desfecho dos ÓRGÃOS onde o cliente tem convênios.

    Transforma a tabela nacional (base_rates_orgao) em conselho por cliente:
    "seus convênios estão em Cidades (59% de morte histórica) e Saúde (4%)".
    O órgão de cada convênio vem do legado (convenio→proposta por ID_PROPOSTA);
    a taxa é a do regime LEGADO (o preditivo — o novo não tem finais).
    """
    snap = snapshot_mais_recente()
    if snap is None:
        return []
    leg = snap / doc / "legado"
    prop_csv, conv_csv = leg / "proposta.csv", leg / "convenio.csv"
    if not (prop_csv.exists() and conv_csv.exists()):
        return []
    orgao_de = {}
    with open(prop_csv, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            orgao_de[r.get("ID_PROPOSTA")] = (r.get("DESC_ORGAO_SUP") or "").strip()
    contagem: dict[str, int] = {}
    with open(conv_csv, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            o = orgao_de.get(r.get("ID_PROPOSTA"))
            if o:
                contagem[o] = contagem.get(o, 0) + 1
    if not contagem:
        return []
    orgs = list(contagem)
    rows = con.execute(
        "SELECT orgao, pct_morte, pct_sucesso, pct_ressalva, n, preditivo"
        " FROM base_rates_orgao WHERE regime='legado_pi424' AND orgao = ANY(%s)",
        (orgs,)).fetchall()
    br = {o: (m, s, res, n, p) for o, m, s, res, n, p in rows}

    # Funil (upstream): a odds de a proposta APROVAR, preferindo a regra vigente
    # (novo_pc33 preditivo) e caindo para o legado quando o novo é raso. Um
    # cliente decide a PRÓXIMA proposta pela regra de hoje — daí a preferência.
    fun: dict[str, dict] = {}
    try:
        frows = con.execute(
            "SELECT orgao, regime, pct_aprovada, pct_reprovada, n_resolvidas, preditivo"
            " FROM funil_orgao WHERE orgao = ANY(%s)", (orgs,)).fetchall()

        def _rank(regime: str, pred: bool) -> int:
            if regime == "novo_pc33" and pred:
                return 0
            if pred:
                return 1
            return 2 if regime == "novo_pc33" else 3

        for o, regime, apr, rep, nres, pred in frows:
            cand = {"regime": regime, "preditivo": pred, "n_resolvidas": nres,
                    "pct_aprovada": float(apr) if apr is not None else None,
                    "pct_reprovada": float(rep) if rep is not None else None}
            cur = fun.get(o)
            if cur is None or _rank(regime, pred) < _rank(cur["regime"], cur["preditivo"]):
                fun[o] = cand
    except Exception:  # noqa: BLE001 — funil_orgao pode faltar em deploy antigo
        con.rollback()
        fun = {}

    # Latência (art.97): quanto o concedente demora. Mesma preferência de regime
    # — o número que interessa é o do prazo vigente (novo_pc33).
    lat: dict[str, dict] = {}
    try:
        lrows = con.execute(
            "SELECT orgao, regime, mediana_dias, p90_dias, pct_acima_limite, limite_legal, preditivo"
            " FROM latencia_orgao WHERE orgao = ANY(%s)", (orgs,)).fetchall()

        def _rankL(regime: str, pred: bool) -> int:
            if regime == "novo_pc33" and pred:
                return 0
            if pred:
                return 1
            return 2 if regime == "novo_pc33" else 3

        for o, regime, med, p90, acima, limite, pred in lrows:
            cand = {"regime": regime, "preditivo": pred, "mediana_dias": med,
                    "p90_dias": p90, "limite_legal": limite,
                    "pct_acima_limite": float(acima) if acima is not None else None}
            cur = lat.get(o)
            if cur is None or _rankL(regime, pred) < _rankL(cur["regime"], cur["preditivo"]):
                lat[o] = cand
    except Exception:  # noqa: BLE001 — latencia_orgao pode faltar em deploy antigo
        con.rollback()
        lat = {}

    saida = []
    for o, cnt in sorted(contagem.items(), key=lambda x: -x[1]):
        m, s, res, n, p = br.get(o, (None, None, None, None, False))
        saida.append({"orgao": o, "convenios_do_cliente": cnt,
                      "pct_morte": float(m) if m is not None else None,
                      "pct_sucesso": float(s) if s is not None else None,
                      "pct_ressalva": float(res) if res is not None else None,
                      "base_n": n, "preditivo": p,
                      "funil": fun.get(o), "latencia": lat.get(o)})
    return saida


def _cadastro(con, doc: str) -> dict:
    r = con.execute(
        "SELECT doc, tipo_doc, nome, apelido, natureza, uf, municipio, operador, ativo, observacao"
        " FROM clientes WHERE doc=%s", (doc,)).fetchone()
    if not r:
        return {"doc": doc, "nome": ROTULOS.get(doc, doc), "na_carteira": False}
    cols = ["doc", "tipo_doc", "nome", "apelido", "natureza", "uf", "municipio", "operador", "ativo", "observacao"]
    c = dict(zip(cols, r))
    c["na_carteira"] = True
    c["pessoas"] = [dict(zip(["id", "cpf", "nome", "papel"], p)) for p in con.execute(
        "SELECT id, cpf, nome, papel FROM clientes_pessoas WHERE doc_cliente=%s AND ativo ORDER BY nome",
        (doc,))]
    return c


def _prazos(con, doc: str) -> list[dict]:
    cols = ["tipo", "instrumento", "data_limite", "descricao", "base_legal", "farol"]
    rows = con.execute(
        "SELECT tipo, instrumento, data_limite, descricao, base_legal, farol FROM marcos"
        " WHERE cnpj=%s AND farol <> 'ok'"
        " ORDER BY CASE farol WHEN 'acao_imediata' THEN 0 WHEN 'vencido' THEN 1 ELSE 2 END,"
        "          data_limite NULLS FIRST LIMIT 60", (doc,)).fetchall()
    saida = []
    hoje = date.today()
    for r in rows:
        d = dict(zip(cols, r))
        d["dias"] = (d["data_limite"] - hoje).days if d["data_limite"] else None
        d["data_limite"] = d["data_limite"].isoformat() if d["data_limite"] else None
        saida.append(d)
    return saida


def _andamento(con, doc: str) -> list[dict]:
    cols = ["rotulo", "tipo", "de", "para", "origem", "snapshot", "criado_em"]
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT rotulo, tipo, de, para, origem, snapshot::text, criado_em FROM eventos"
        " WHERE cnpj=%s ORDER BY id DESC LIMIT 25", (doc,))]


def _diario(con, doc: str) -> list[dict]:
    cols = ["id", "quando", "autor", "tipo", "texto", "referencia"]
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT id, quando, autor, tipo, texto, referencia FROM diario_cliente"
        " WHERE doc_cliente=%s ORDER BY quando DESC LIMIT 100", (doc,))]


def _pareceres(doc: str) -> list[dict]:
    """Pareceres do órgão sobre as propostas do cliente (o lado relacional da
    trilha: o que o CONCEDENTE decidiu, e quando). Do recorte g2."""
    snap = snapshot_mais_recente()
    if snap is None:
        return []
    arq = snap / doc / "parcerias" / "analise-proposta.jsonl.gz"
    if not arq.exists():
        return []
    out = []
    with gzip.open(arq, "rt", encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            a = json.loads(linha)
            ts = str(a.get("dh_analise_proposta") or "")
            if not ts:
                continue
            out.append({"ts": ts, "id_proposta": a.get("id_proposta"),
                        "resultado": (a.get("in_resultado_analise") or "").strip(),
                        "fase": (a.get("in_fase_analise") or "").strip(),
                        "parecer": (a.get("ds_parecer") or "").strip()})
    return out


_SIT_LEGIVEL = {
    "PROPOSTA_CADASTRADA": "Proposta cadastrada",
    "PROPOSTA_ENVIADA_ANALISE": "Proposta enviada para análise",
    "PROPOSTA_EM_ANALISE": "Proposta em análise",
    "PROPOSTA_EM_COMPLEMENTACAO": "Proposta em complementação",
    "PROPOSTA_COMPLEMENTADA_ENVIADA_ANALISE": "Complementação enviada para análise",
    "PROPOSTA_APROVADA": "Proposta aprovada",
    "PROPOSTA_REPROVADA": "Proposta reprovada",
    "PLANO_TRABALHO_APROVADO": "Plano de trabalho aprovado",
    "PLANO_TRABALHO_EM_ANALISE": "Plano de trabalho em análise",
    "ASSINADA": "Convênio assinado",
    "EM_EXECUCAO": "Em execução",
    "PRESTACAO_CONTAS_ENVIADA_ANALISE": "Prestação enviada para análise",
    "PRESTACAO_CONTAS_EM_ANALISE": "Prestação em análise",
    "PRESTACAO_CONTAS_APROVADA": "Prestação aprovada",
    "PRESTACAO_CONTAS_APROVADA_COM_RESSALVAS": "Prestação aprovada com ressalvas",
    "AGUARDANDO_PRESTACAO_CONTAS": "Aguardando prestação de contas",
    "CONVENIO_ANULADO": "Convênio anulado",
}


def _humaniza(sit: str) -> str:
    return _SIT_LEGIVEL.get(sit) or (sit or "").replace("_", " ").capitalize()


def _historico_legado(doc: str) -> list[dict]:
    """O trilho de verdade: cada transição de situação dos convênios/propostas do
    cliente, com data. Existe para todo cliente com histórico legado — é o que
    enche a trilha antes de os eventos D-1 e o diário começarem a acumular."""
    snap = snapshot_mais_recente()
    if snap is None:
        return []
    arq = snap / doc / "legado" / "historico_situacao.csv"
    if not arq.exists():
        return []
    out = []
    with open(arq, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            bruto = (row.get("DIA_HISTORICO_SIT") or "").strip()
            dt = None
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(bruto, fmt)
                    break
                except ValueError:
                    continue
            if dt is None:
                continue
            out.append({"ts": dt.isoformat(), "sit": (row.get("HISTORICO_SIT") or "").strip(),
                        "nr": (row.get("NR_CONVENIO") or "").strip()})
    return out


def trilha(doc: str) -> dict:
    """Uma linha do tempo única, do mais novo pro mais antigo, cruzando: o PROCESSO
    (transições de situação dos convênios do cliente), o que o SISTEMA detectou
    (diff D-1), o que a CASA fez (diário) e o que o ÓRGÃO decidiu (pareceres).
    É a história relacional do cliente num lugar só."""
    doc = "".join(c for c in doc if c.isdigit())
    itens: list[dict] = []
    for h in _historico_legado(doc):
        itens.append({"ts": h["ts"], "grupo": "processo", "icone": "📋",
                      "titulo": _humaniza(h["sit"]),
                      "sub": (f"instrumento {h['nr']}" if h["nr"] else ""), "tipo": "historico"})
    with conectar() as con:
        for rotulo, tipo, de, para, origem, snap, criado in con.execute(
            "SELECT rotulo, tipo, de, para, origem, snapshot::text, criado_em FROM eventos"
            " WHERE cnpj=%s ORDER BY criado_em DESC LIMIT 60", (doc,)):
            itens.append({"ts": criado.isoformat(), "grupo": "sistema",
                          "icone": "📩" if origem == "inbox" else "🔔", "titulo": rotulo,
                          "sub": (f"{de} → {para}" if de else (para or "")), "tipo": tipo})
        for quando, autor, tipo, texto in con.execute(
            "SELECT quando, autor, tipo, texto FROM diario_cliente"
            " WHERE doc_cliente=%s ORDER BY quando DESC LIMIT 60", (doc,)):
            itens.append({"ts": quando.isoformat(), "grupo": "atendimento", "icone": "✎",
                          "titulo": tipo, "sub": texto, "autor": autor, "tipo": tipo})
    for p in _pareceres(doc):
        sub = p["resultado"] or "análise"
        if p["fase"]:
            sub += f" · {p['fase']}"
        if p["parecer"]:
            sub += f" — {p['parecer'][:180]}"
        itens.append({"ts": p["ts"], "grupo": "orgao", "icone": "⚖",
                      "titulo": f"Parecer — Proposta {p['id_proposta']}", "sub": sub, "tipo": "parecer"})
    itens.sort(key=lambda x: (x["ts"] or "").replace(" ", "T"), reverse=True)
    return {"itens": itens[:45]}


def _triagens(con, doc: str) -> list[dict]:
    """O que o operador já tratou (fila) — parte da memória do atendimento."""
    cols = ["chave", "status", "nota", "operador", "atualizado_em"]
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT chave, status, nota, operador, atualizado_em FROM fila_status"
        " WHERE chave LIKE %s AND status <> 'aberto'"
        " ORDER BY atualizado_em DESC LIMIT 30", (f"%:{doc}:%",))]


def montar(doc: str) -> dict:
    doc = "".join(c for c in doc if c.isdigit())
    base = next((e for e in listar_entes()["entes"] if e["cnpj"] == doc), None)

    with conectar() as con:
        ficha = {
            "cadastro": _cadastro(con, doc),
            "prazos": _prazos(con, doc),
            "andamento": _andamento(con, doc),
            "diario": _diario(con, doc),
            "triagens": _triagens(con, doc),
            "risco_orgaos": _risco_orgaos(con, doc),
        }

    if base:
        ficha["carteira"] = {
            "parcerias": base.get("parcerias", {}),
            "legado": base.get("legado", {}),
            "especiais": base.get("especiais", {}),
            "emendas": base.get("emendas_indicadas", {}),
            "municipio": base.get("municipio"), "uf": base.get("uf"),
            "snapshot": base.get("data_atualizacao_api"),
        }
        ficha["regularidade"] = base.get("regularidade", {})
    else:
        ficha["carteira"] = {}
        ficha["regularidade"] = {"disponivel": False, "motivo": "sem recorte para este CNPJ"}

    p = ficha["carteira"].get("parcerias", {}) or {}
    lg = ficha["carteira"].get("legado", {}) or {}
    ficha["resumo"] = {
        "propostas": p.get("propostas", 0),
        "instrumentos_g2": p.get("instrumentos", 0),
        "instrumentos_legado_ativos": lg.get("ativos", 0),
        "prazos_abertos": len(ficha["prazos"]),
        "acao_imediata": sum(1 for x in ficha["prazos"] if x["farol"] == "acao_imediata"),
        "vencidos": sum(1 for x in ficha["prazos"] if x["farol"] == "vencido"),
        "impedido": bool((ficha["regularidade"] or {}).get("impedido")),
        "dirigentes": len((ficha["cadastro"] or {}).get("pessoas", [])),
    }
    return ficha


def anotar(doc: str, texto: str, tipo: str = "nota", autor: str | None = None,
           referencia: str | None = None) -> dict:
    doc = "".join(c for c in doc if c.isdigit())
    if not texto.strip():
        return {"ok": False, "erro": "texto vazio"}
    with conectar() as con:
        r = con.execute(
            "INSERT INTO diario_cliente (doc_cliente, autor, tipo, texto, referencia)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (doc, autor, tipo, texto.strip(), referencia)).fetchone()
        con.commit()
    return {"ok": True, "id": r[0]}


def cadastrar_pessoa(doc: str, cpf: str, nome: str, papel: str | None = None) -> dict:
    doc = "".join(c for c in doc if c.isdigit())
    cpf_d = "".join(c for c in cpf if c.isdigit())
    if len(cpf_d) != 11:
        return {"ok": False, "erro": "CPF deve ter 11 dígitos"}
    with conectar() as con:
        con.execute(
            "INSERT INTO clientes_pessoas (doc_cliente, cpf, nome, papel) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (doc_cliente, cpf) DO UPDATE SET nome=EXCLUDED.nome,"
            " papel=EXCLUDED.papel, ativo=true",
            (doc, cpf_d, nome.strip(), papel))
        con.commit()
    return {"ok": True, "cpf": cpf_d}
