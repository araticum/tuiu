"""Produtividade da fila — quanto tempo cada tipo de item leva para ser resolvido.

Mede com dois relógios que agora existem:
  `fila_visto.primeira_vez`  quando o item apareceu
  `fila_status.atualizado_em` quando o operador o resolveu

Responde ao que interessa numa operação de carteira:
  - tempo mediano de resolução por tipo (onde a casa é lenta)
  - o que está aberto e envelhecendo (backlog por idade)
  - throughput no período (quantos entraram × quantos saíram)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import conectar

# Rótulos sem símbolo matemático: o console do Windows é cp1252 e engasga em
# "≤" (gotcha recorrente da casa).
FAIXAS = [(1, "até 1 dia"), (3, "até 3 dias"), (7, "até 1 semana"), (30, "até 1 mês")]


def _faixa(dias: float) -> str:
    for limite, rotulo in FAIXAS:
        if dias <= limite:
            return rotulo
    return "mais de 1 mês"


def montar(dias: int = 30, cliente: str | None = None) -> dict:
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    filtro_cli = " AND v.cliente = %s" if cliente else ""
    args_cli: tuple = (cliente,) if cliente else ()

    with conectar() as con:
        # tempo de resolução por tipo (mediano e médio), no período
        resolucao = [dict(zip(["tipo", "resolvidos", "mediana_h", "media_h", "max_h"], r))
                     for r in con.execute(
                         "SELECT v.tipo, count(*),"
                         " ROUND((percentile_cont(0.5) WITHIN GROUP ("
                         "   ORDER BY EXTRACT(EPOCH FROM (s.atualizado_em - v.primeira_vez))/3600))::numeric, 1),"
                         " ROUND(AVG(EXTRACT(EPOCH FROM (s.atualizado_em - v.primeira_vez))/3600)::numeric, 1),"
                         " ROUND(MAX(EXTRACT(EPOCH FROM (s.atualizado_em - v.primeira_vez))/3600)::numeric, 1)"
                         " FROM fila_status s JOIN fila_visto v ON v.chave = s.chave"
                         " WHERE s.status = 'resolvido' AND s.atualizado_em >= %s" + filtro_cli +
                         " GROUP BY v.tipo ORDER BY 2 DESC", (desde,) + args_cli)]

        # backlog: o que está aberto, por idade
        abertos = [dict(zip(["tipo", "urgencia", "qtd", "idade_media_dias", "mais_antigo_dias"], r))
                   for r in con.execute(
                       "SELECT v.tipo, v.urgencia, count(*),"
                       " ROUND(AVG(EXTRACT(EPOCH FROM (now() - v.primeira_vez))/86400)::numeric, 1),"
                       " ROUND(MAX(EXTRACT(EPOCH FROM (now() - v.primeira_vez))/86400)::numeric, 1)"
                       " FROM fila_visto v"
                       " LEFT JOIN fila_status s ON s.chave = v.chave"
                       " WHERE COALESCE(s.status,'aberto') IN ('aberto','em_andamento')" + filtro_cli +
                       " GROUP BY v.tipo, v.urgencia ORDER BY 5 DESC NULLS LAST", args_cli)]

        # throughput: entraram × saíram no período
        entraram = con.execute(
            "SELECT count(*) FROM fila_visto v WHERE v.primeira_vez >= %s" + filtro_cli,
            (desde,) + args_cli).fetchone()[0]
        sairam = con.execute(
            "SELECT count(*) FROM fila_status s JOIN fila_visto v ON v.chave = s.chave"
            " WHERE s.status='resolvido' AND s.atualizado_em >= %s" + filtro_cli,
            (desde,) + args_cli).fetchone()[0]

        # distribuição por faixa de tempo (todos os resolvidos do período)
        tempos = [float(r[0]) for r in con.execute(
            "SELECT EXTRACT(EPOCH FROM (s.atualizado_em - v.primeira_vez))/86400"
            " FROM fila_status s JOIN fila_visto v ON v.chave = s.chave"
            " WHERE s.status='resolvido' AND s.atualizado_em >= %s" + filtro_cli,
            (desde,) + args_cli)]

    distribuicao: dict[str, int] = {}
    for t in tempos:
        r = _faixa(max(t, 0))
        distribuicao[r] = distribuicao.get(r, 0) + 1

    return {
        "periodo_dias": dias, "cliente": cliente,
        "throughput": {"entraram": entraram, "resolvidos": sairam,
                       "saldo": entraram - sairam,
                       "veredito": ("acumulando" if entraram > sairam
                                    else "em dia" if entraram == sairam else "reduzindo backlog")},
        "resolucao_por_tipo": resolucao,
        "backlog_por_tipo": abertos,
        "distribuicao_tempo": distribuicao,
        "total_aberto": sum(a["qtd"] for a in abertos),
    }
