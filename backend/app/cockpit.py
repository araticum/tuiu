"""Cockpit (visão unificada) — o "uma coisa só" do Tuiú.

Junta, por ente e no topo, o que importa para agir: prioridades (ação imediata +
vencidos), saúde da carteira e andamento recente. Assembla sobre o que já existe
(carteira.listar_entes + marcos + eventos), degradando sem banco.
"""

from __future__ import annotations

from app.carteira import listar_entes

try:
    from app.db import conectar
except Exception:  # noqa: BLE001
    conectar = None


def _marcos_por_ente(con) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for cnpj, farol, n in con.execute(
            "SELECT cnpj, farol, count(*) FROM marcos GROUP BY 1,2"):
        out.setdefault(cnpj, {})[farol] = n
    return out


def _eventos_por_ente(con) -> dict[str, list]:
    out: dict[str, list] = {}
    cols = ["rotulo", "tipo", "de", "para", "origem", "snapshot"]
    for r in con.execute(
            "SELECT cnpj, rotulo, tipo, de, para, origem, snapshot::text FROM eventos"
            " ORDER BY id DESC LIMIT 300"):
        out.setdefault(r[0], [])
        if len(out[r[0]]) < 4:
            out[r[0]].append(dict(zip(cols, r[1:])))
    return out


def _prioridades(con, limite: int = 15) -> list[dict]:
    # "Agir agora" = só o que o CONVENENTE pode resolver. O que espera decisão do
    # concedente (proposta parada, parcela não liberada, análise atrasada) é
    # acompanhamento, não prioridade — fica de fora daqui (Danilo, 07/2026).
    cols = ["cnpj", "ente", "tipo", "instrumento", "data_limite", "descricao", "base_legal", "farol"]
    rows = con.execute(
        "SELECT cnpj, ente, tipo, instrumento, data_limite, descricao, base_legal, farol"
        " FROM marcos WHERE farol IN ('acao_imediata','vencido')"
        "   AND COALESCE(detalhes->>'bola_com','convenente') <> 'concedente'"
        " ORDER BY CASE farol WHEN 'acao_imediata' THEN 0 ELSE 1 END, data_limite NULLS FIRST"
        " LIMIT %s", (limite,)).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def montar() -> dict:
    base = listar_entes()
    entes_out = []
    marcos, eventos, prioridades, totais = {}, {}, [], {}

    nomes: dict[str, str] = {}
    if conectar is not None:
        try:
            with conectar() as con:
                marcos = _marcos_por_ente(con)
                eventos = _eventos_por_ente(con)
                prioridades = _prioridades(con)
                # nome do cliente p/ os cards não ficarem intitulados por CNPJ
                nomes = {r[0]: (r[1] or r[2]) for r in con.execute(
                    "SELECT doc, apelido, nome FROM clientes WHERE ativo")}
                v = con.execute(
                    "SELECT count(*) FILTER (WHERE farol='acao_imediata'),"
                    "       count(*) FILTER (WHERE farol='vencido'),"
                    "       count(*) FILTER (WHERE farol='atencao')"
                    " FROM marcos").fetchone()
                nev = con.execute("SELECT count(*) FROM eventos").fetchone()[0]
                totais = {"acao_imediata": v[0], "vencido": v[1], "atencao": v[2], "eventos": nev}
        except Exception as exc:  # noqa: BLE001 — sem banco, cockpit ainda mostra a carteira
            totais = {"erro": str(exc)}

    for e in base["entes"]:
        cnpj = e["cnpj"]
        p, esp, em, lg = e.get("parcerias", {}), e.get("especiais", {}), e.get("emendas_indicadas", {}), e.get("legado", {})
        prest_vencidas = sum(1 for x in lg.get("prestacoes", []) if x.get("farol") == "vencido")
        entes_out.append({
            "cnpj": cnpj, "rotulo": nomes.get(cnpj) or e.get("rotulo") or e.get("nome") or cnpj,
            "municipio": e.get("municipio"), "uf": e.get("uf"),
            "saude": {
                "instrumentos_ativos": lg.get("ativos", 0),
                "repasse_ativos": lg.get("contratos_repasse_ativos", 0),
                "saldo": (p.get("saldo_conta_corrente", 0) or 0) + (p.get("saldo_investimento", 0) or 0),
                "emendas_valor": em.get("valor_total", 0),
                "impedimentos_pix": len(esp.get("impedidos", [])),
                "prestacoes_vencidas": prest_vencidas,
                "cauc_vinculo": bool((e.get("regularidade") or {}).get("disponivel")),
            },
            "marcos": marcos.get(cnpj, {}),
            "andamento": eventos.get(cnpj, []),
        })

    return {"snapshot": base["snapshot"], "totais": totais,
            "prioridades": prioridades, "entes": entes_out}
