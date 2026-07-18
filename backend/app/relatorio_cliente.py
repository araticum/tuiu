"""Relatório periódico do cliente — a entrega do serviço.

Sai inteiro do que já está no banco e nos recortes: o que mudou no período, o
que a casa tratou, o que segue sob vigilância e o que depende do cliente.

Três seções, nessa ordem, porque é a ordem do interesse de quem recebe:
  1. **Precisa de você** — o que só o cliente resolve (decisão, documento, ato)
  2. **Sob nossa vigilância** — prazos monitorados, com base legal
  3. **O que fizemos** — atendimentos e itens tratados no período

Saída em markdown (decisão de simplicidade: sem PDF/assinatura) — para colar
em e-mail ou imprimir pelo navegador.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.carteira import ROTULOS, listar_entes
from app.db import conectar

# Marcos cuja solução depende do cliente (não adianta a casa cobrar sozinha)
DEPENDE_DO_CLIENTE = {
    "prestacao_contas": "reunir e conferir a documentação da prestação",
    "complementacao_pendente": "fornecer os documentos/esclarecimentos exigidos",
    "impedimento_cadastro": "sanar a pendência que gerou o impedimento",
    "relatorio_gestao_pix": "confirmar os dados de execução para o relatório",
    "etapa_cronograma": "executar/comprovar a etapa pactuada",
}


def _brl(v) -> str:
    return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _dbr(d) -> str:
    if not d:
        return "—"
    s = str(d)[:10]
    return f"{s[8:10]}/{s[5:7]}/{s[:4]}"


def montar(doc: str, dias: int = 30) -> dict:
    doc = "".join(c for c in doc if c.isdigit())
    inicio = datetime.now(timezone.utc) - timedelta(days=dias)
    hoje = date.today()

    with conectar() as con:
        cad = con.execute(
            "SELECT nome, apelido, uf, municipio, operador FROM clientes WHERE doc=%s", (doc,)).fetchone()
        nome = (cad[1] or cad[0]) if cad else ROTULOS.get(doc, doc)
        oficial = cad[0] if cad else nome

        marcos = [dict(zip(["tipo", "instrumento", "data_limite", "descricao", "base_legal", "farol"], r))
                  for r in con.execute(
                      "SELECT tipo, instrumento, data_limite, descricao, base_legal, farol"
                      " FROM marcos WHERE cnpj=%s AND farol <> 'ok'"
                      " ORDER BY CASE farol WHEN 'acao_imediata' THEN 0 WHEN 'vencido' THEN 1 ELSE 2 END,"
                      "          data_limite NULLS FIRST", (doc,))]

        eventos = [dict(zip(["rotulo", "tipo", "de", "para", "origem", "criado_em"], r))
                   for r in con.execute(
                       "SELECT rotulo, tipo, de, para, origem, criado_em FROM eventos"
                       " WHERE cnpj=%s AND criado_em >= %s ORDER BY id DESC", (doc, inicio))]

        tratados = [dict(zip(["chave", "status", "nota", "quando"], r))
                    for r in con.execute(
                        "SELECT chave, status, nota, atualizado_em FROM fila_status"
                        " WHERE chave LIKE %s AND status IN ('resolvido','em_andamento')"
                        "   AND atualizado_em >= %s ORDER BY atualizado_em DESC",
                        (f"%:{doc}:%", inicio))]

        diario = [dict(zip(["quando", "tipo", "texto", "autor"], r))
                  for r in con.execute(
                      "SELECT quando, tipo, texto, autor FROM diario_cliente"
                      " WHERE doc_cliente=%s AND quando >= %s ORDER BY quando DESC", (doc, inicio))]

    ente = next((e for e in listar_entes()["entes"] if e["cnpj"] == doc), {}) or {}
    parcerias = ente.get("parcerias", {}) or {}
    legado = ente.get("legado", {}) or {}
    reg = ente.get("regularidade", {}) or {}

    precisa_cliente = [m for m in marcos if m["tipo"] in DEPENDE_DO_CLIENTE]
    vigilancia = [m for m in marcos if m["tipo"] not in DEPENDE_DO_CLIENTE]

    return {
        "cnpj": doc, "nome": nome, "razao_social": oficial,
        "uf": ente.get("uf"), "municipio": ente.get("municipio"),
        "operador": cad[4] if cad else None,
        "periodo_dias": dias, "de": inicio.date().isoformat(), "ate": hoje.isoformat(),
        "carteira": {
            "propostas": parcerias.get("propostas", 0),
            "por_situacao": parcerias.get("por_situacao", {}),
            "instrumentos_ativos": legado.get("ativos", 0),
            "saldo": (parcerias.get("saldo_conta_corrente", 0) or 0)
                     + (parcerias.get("saldo_investimento", 0) or 0),
        },
        "regularidade": {"impedido": bool(reg.get("impedido")),
                         "fontes": {k: v.get("registros", 0) for k, v in (reg.get("fontes") or {}).items()}},
        "precisa_do_cliente": precisa_cliente,
        "sob_vigilancia": vigilancia,
        "mudancas": eventos,
        "tratados": tratados,
        "diario": diario,
    }


def markdown(r: dict) -> str:
    L = [f"# {r['nome']} — acompanhamento no Transferegov.br", "",
         f"**Período:** {_dbr(r['de'])} a {_dbr(r['ate'])} ({r['periodo_dias']} dias)  ",
         f"**Entidade:** {r['razao_social']} · CNPJ {r['cnpj']}"
         + (f" · {r['municipio']}/{r['uf']}" if r.get("municipio") else ""),
         (f"**Responsável pelo acompanhamento:** {r['operador']}" if r.get("operador") else ""), ""]

    # 1) o que depende do cliente
    L += ["## 1. Precisa de você", ""]
    if r["precisa_do_cliente"]:
        for m in r["precisa_do_cliente"][:15]:
            acao = DEPENDE_DO_CLIENTE.get(m["tipo"], "providenciar")
            prazo = f" — prazo {_dbr(m['data_limite'])}" if m["data_limite"] else ""
            urg = {"acao_imediata": "🔴 urgente", "vencido": "🔴 vencido", "atencao": "🟡"}.get(m["farol"], "")
            L += [f"- {urg} **{acao}** · {m['descricao']}{prazo}",
                  f"  <sub>{m['base_legal']}</sub>"]
    else:
        L.append("Nada pendente do seu lado neste período. ✅")
    L.append("")

    # 2) o que a casa vigia
    L += ["## 2. Sob nossa vigilância", ""]
    if r["sob_vigilancia"]:
        L.append(f"Acompanhamos **{len(r['sob_vigilancia'])}** prazo(s)/situação(ões). Os mais próximos:")
        L.append("")
        for m in r["sob_vigilancia"][:10]:
            prazo = _dbr(m["data_limite"]) if m["data_limite"] else "sem data"
            L.append(f"- {prazo} — {m['descricao']}")
    else:
        L.append("Nenhum prazo aberto no momento.")
    L.append("")

    # 3) o que fizemos
    L += ["## 3. O que fizemos no período", ""]
    if r["diario"]:
        for d in r["diario"][:20]:
            L.append(f"- {_dbr(str(d['quando']))} — **{d['tipo']}**: {d['texto']}")
    if r["tratados"]:
        L.append(f"- {len(r['tratados'])} item(ns) da fila tratados"
                 f" ({sum(1 for t in r['tratados'] if t['status'] == 'resolvido')} resolvidos)")
    if r["mudancas"]:
        L.append(f"- {len(r['mudancas'])} mudança(s) detectada(s) no Transferegov:")
        for e in r["mudancas"][:8]:
            trans = f"{e['de']} → {e['para']}" if e["de"] else (e["para"] or "")
            L.append(f"  - {e['rotulo']} {('· ' + str(trans)[:60]) if trans else ''}")
    if not (r["diario"] or r["tratados"] or r["mudancas"]):
        L.append("Monitoramento ativo, sem ocorrências no período.")
    L.append("")

    # panorama
    c, reg = r["carteira"], r["regularidade"]
    L += ["## Panorama", "",
          f"- Propostas no ciclo atual: **{c['propostas']}**"
          + (f" ({', '.join(f'{k}: {v}' for k, v in c['por_situacao'].items())})" if c["por_situacao"] else ""),
          f"- Instrumentos ativos no histórico: **{c['instrumentos_ativos']}**",
          f"- Saldo em contas específicas: **{_brl(c['saldo'])}**",
          ("- 🔴 **Consta impedimento** em cadastro federal" if reg["impedido"]
           else "- ✅ Sem impedimento em CEPIM/CEIS/CNEP"),
          "", "---", "",
          "<sub>Elaborado a partir de dados públicos oficiais do Transferegov.br e do Portal da "
          "Transparência, conferidos diariamente. Prazos e bases legais conforme a norma vigente na "
          "data de cada instrumento.</sub>"]
    return "\n".join(x for x in L if x is not None)
