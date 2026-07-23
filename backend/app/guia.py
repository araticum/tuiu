"""Busca do guia — HÍBRIDA: semântica local + FTS português, fundidas por RRF.

Por que híbrida: a semântica acha o que o usuário quis dizer ("como peço o
dinheiro" → "liberação de repasse / ordem de pagamento"); o FTS acha o termo
exato que o manual usa (OBTV, PAD/PAC, TR, SICONV). Sozinhas erram em lados
opostos; fundidas por Reciprocal Rank Fusion recuperam muito mais.

Por que cosseno em Python: a imagem do banco (postgres:16-alpine) não tem
pgvector. O corpus é pequeno (~milhares de trechos × 384d ≈ dezenas de MB), então
a matriz cabe em memória e o produto interno é instantâneo. Sem infra nova.

O modelo (MiniLM multilíngue, ~300 MB residentes) é carregado sob demanda e fica
em cache no processo — este host roda a produção do veredas, então não se carrega
modelo grande nem no import.
"""

from __future__ import annotations

from app.db import conectar

MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
K_RRF = 60          # constante padrão do Reciprocal Rank Fusion

# Viés de ranking por fonte. O guia é a camada de RESPOSTA (escrito para responder
# pergunta, com prazo e base legal); o manual é o detalhe do passo a passo. Sem
# isso, 2.575 trechos de tutorial afogam 30 passagens curadas e quem pergunta
# "qual o prazo" recebe print de tela em vez do artigo.
PESO_FONTE = {"guia": 1.8, "norma": 1.4, "manual": 1.0}

_modelo = None
_ids: list[int] = []
_fontes: dict[int, str] = {}
_matriz = None
_carga: int | None = None


def _embedder():
    global _modelo
    if _modelo is None:
        from fastembed import TextEmbedding
        _modelo = TextEmbedding(model_name=MODELO)
    return _modelo


def _vetores(con):
    """Matriz normalizada em cache; recarrega se o índice mudou de tamanho."""
    global _ids, _fontes, _matriz, _carga
    n = con.execute("SELECT count(*) FROM guia_trechos WHERE vetor IS NOT NULL").fetchone()[0]
    if _matriz is not None and _carga == n:
        return _ids, _matriz
    import numpy as np
    ids, vs, fontes = [], [], {}
    for i, f, v in con.execute(
            "SELECT id, fonte, vetor FROM guia_trechos WHERE vetor IS NOT NULL ORDER BY id"):
        ids.append(i)
        vs.append(v)
        fontes[i] = f
    _fontes = fontes
    if not ids:
        _ids, _matriz, _carga = [], None, n
        return _ids, _matriz
    m = np.asarray(vs, dtype="float32")
    m /= (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    _ids, _matriz, _carga = ids, m, n
    return _ids, _matriz


def _permitidos(con, etapa: str | None, papel: str | None) -> set[int] | None:
    if not etapa and not papel:
        return None
    cond, params = [], []
    if etapa:
        cond.append("etapa = %s")
        params.append(etapa)
    if papel:
        cond.append("(papel = %s OR papel = 'geral')")
        params.append(papel)
    rows = con.execute(
        "SELECT id FROM guia_trechos WHERE " + " AND ".join(cond), params).fetchall()
    return {r[0] for r in rows}


COLS = ["id", "fonte", "modulo", "etapa", "papel", "documento",
        "pagina_ini", "pagina_fim", "arquivo", "url", "texto"]


def buscar(q: str, k: int = 8, etapa: str | None = None, papel: str | None = None) -> dict:
    q = (q or "").strip()
    if len(q) < 3:
        return {"resultados": [], "erro": "pergunta muito curta"}
    import numpy as np
    with conectar() as con:
        ok = _permitidos(con, etapa, papel)
        ids, matriz = _vetores(con)

        pontos: dict[int, float] = {}
        if matriz is not None and len(ids):
            qv = np.asarray(list(_embedder().embed([q]))[0], dtype="float32")
            qv /= (np.linalg.norm(qv) + 1e-9)
            sims = matriz @ qv
            for rank, pos in enumerate(np.argsort(-sims)[: k * 4]):
                i = ids[int(pos)]
                if ok is None or i in ok:
                    peso = PESO_FONTE.get(_fontes.get(i, "manual"), 1.0)
                    pontos[i] = pontos.get(i, 0.0) + peso / (K_RRF + rank)

        for rank, (i, _r) in enumerate(con.execute(
                "SELECT id, ts_rank(tsv, plainto_tsquery('portuguese', tuiu_norm(%s))) r"
                " FROM guia_trechos"
                " WHERE tsv @@ plainto_tsquery('portuguese', tuiu_norm(%s))"
                " ORDER BY r DESC LIMIT %s", (q, q, k * 4)).fetchall()):
            if ok is None or i in ok:
                peso = PESO_FONTE.get(_fontes.get(i, "manual"), 1.0)
                pontos[i] = pontos.get(i, 0.0) + peso / (K_RRF + rank)

        if not pontos:
            return {"resultados": []}
        melhores = sorted(pontos, key=lambda i: -pontos[i])[:k]
        rows = con.execute(
            "SELECT " + ", ".join(COLS) + " FROM guia_trechos WHERE id = ANY(%s)",
            (melhores,)).fetchall()
        por_id = {r[0]: dict(zip(COLS, r)) for r in rows}

    saida = []
    for i in melhores:
        r = por_id.get(i)
        if not r:
            continue
        r["score"] = round(pontos[i], 5)
        r["trecho"] = r.pop("texto")
        saida.append(r)
    return {"resultados": saida}


def etapas() -> list[dict]:
    """Esqueleto de navegação: as etapas do pipeline, com quanto há de cada."""
    with conectar() as con:
        return [{"etapa": e, "modulo": m, "trechos": n, "documentos": d}
                for e, m, n, d in con.execute(
                    "SELECT etapa, min(modulo), count(*), count(DISTINCT documento)"
                    " FROM guia_trechos WHERE etapa IS NOT NULL AND etapa <> ''"
                    " GROUP BY etapa ORDER BY min(modulo), etapa")]
