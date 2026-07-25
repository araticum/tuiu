"""Configuração pelo ADMIN — o especialista incrementa a plataforma sem código.

Duas famílias nesta leva:
  - regras_situacao : como o motor classifica a situação do instrumento (é
                      prestação do cliente? do órgão? ignora?). Muda o que vira
                      alarme na fila/cockpit a partir da PRÓXIMA rodada do motor.
  - regras_acao     : o "próximo passo" que o operador lê na fila, por tipo.

Toda escrita passa por aqui (nunca direto no SQL da UI) para normalizar o padrão
igual o motor (`_norm`) e barrar valores fora do domínio. Gate de admin fica no
middleware; este módulo assume que quem chegou pode escrever.
"""

from __future__ import annotations

import unicodedata

from app.db import conectar

FASES = ("convenente", "concedente", "ignorar")


def _norm(s: str | None) -> str:
    """Mesma normalização do motor (minúscula, sem acento) — o padrão é casado
    como substring contra a situação já normalizada."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or ""))
                   if unicodedata.category(c) != "Mn").lower().strip()


# ------------------------------------------------------------------ situações
def listar_situacoes() -> dict:
    with conectar() as con:
        cols = ["id", "padrao", "fase", "nota", "ativo", "criado_por", "atualizado_em"]
        linhas = [dict(zip(cols, r)) for r in con.execute(
            "SELECT id, padrao, fase, nota, ativo, criado_por, atualizado_em"
            " FROM regras_situacao ORDER BY ativo DESC, fase, padrao")]
    for r in linhas:
        r["atualizado_em"] = r["atualizado_em"].isoformat() if r["atualizado_em"] else None
    return {"situacoes": linhas, "fases": list(FASES)}


def salvar_situacao(padrao: str, fase: str, nota: str | None,
                    por: str | None, rid: int | None = None, ativo: bool = True) -> dict:
    if fase not in FASES:
        return {"ok": False, "erro": f"fase inválida (use {', '.join(FASES)})"}
    p = _norm(padrao)
    if len(p) < 3:
        return {"ok": False, "erro": "padrão muito curto (mín. 3 caracteres)"}
    with conectar() as con:
        if rid:
            n = con.execute(
                "UPDATE regras_situacao SET padrao=%s, fase=%s, nota=%s, ativo=%s,"
                " atualizado_em=now() WHERE id=%s",
                (p, fase, nota, ativo, rid)).rowcount
            if not n:
                return {"ok": False, "erro": "regra não encontrada"}
        else:
            con.execute(
                "INSERT INTO regras_situacao (padrao, fase, nota, criado_por)"
                " VALUES (%s,%s,%s,%s)"
                " ON CONFLICT (padrao) DO UPDATE SET fase=EXCLUDED.fase, nota=EXCLUDED.nota,"
                " ativo=true, atualizado_em=now()",
                (p, fase, nota, por))
        con.commit()
    return {"ok": True, "padrao": p, "fase": fase}


def remover_situacao(rid: int) -> dict:
    """Desativa (não apaga: preserva o rastro de quem classificou e por quê)."""
    with conectar() as con:
        n = con.execute("UPDATE regras_situacao SET ativo=false, atualizado_em=now()"
                        " WHERE id=%s", (rid,)).rowcount
        con.commit()
    return {"ok": bool(n)}


def situacoes_no_dado() -> dict:
    """Vocabulário REAL de situações no acervo (não só as que viraram marco), para
    o admin classificar sem digitar. Marca cada uma com a fase que a regra atual
    lhe daria — as `None` são as descobertas (sem regra), candidatas a classificar."""
    from app.motor_prazos import _fase_prestacao, carregar_regras_situacao
    with conectar() as con:
        regras = carregar_regras_situacao(con)
        vistas = [r[0] for r in con.execute(
            "SELECT DISTINCT valor FROM entidades_estado"
            " WHERE dominio IN ('convenio_legado','proposta_g2')"
            "   AND valor IS NOT NULL AND length(trim(valor)) > 0"
            " ORDER BY 1")]
    itens = [{"situacao": s, "fase": _fase_prestacao(s, regras)} for s in vistas]
    return {"situacoes": itens,
            "sem_regra": sum(1 for i in itens if i["fase"] is None)}


# --------------------------------------------------------------------- ações
def listar_acoes() -> dict:
    with conectar() as con:
        cols = ["tipo", "proximo_passo", "nota", "atualizado_em"]
        linhas = [dict(zip(cols, r)) for r in con.execute(
            "SELECT tipo, proximo_passo, nota, atualizado_em FROM regras_acao ORDER BY tipo")]
    for r in linhas:
        r["atualizado_em"] = r["atualizado_em"].isoformat() if r["atualizado_em"] else None
    return {"acoes": linhas}


def salvar_acao(tipo: str, proximo_passo: str, nota: str | None, por: str | None) -> dict:
    tipo = (tipo or "").strip()
    passo = (proximo_passo or "").strip()
    if not tipo or not passo:
        return {"ok": False, "erro": "tipo e próximo passo são obrigatórios"}
    with conectar() as con:
        con.execute(
            "INSERT INTO regras_acao (tipo, proximo_passo, nota, criado_por)"
            " VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (tipo) DO UPDATE SET proximo_passo=EXCLUDED.proximo_passo,"
            " nota=EXCLUDED.nota, atualizado_em=now()",
            (tipo, passo, nota, por))
        con.commit()
    return {"ok": True, "tipo": tipo}
