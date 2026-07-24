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

import json
import os
import urllib.request

from app.db import conectar  # também carrega o .env (chave da DeepInfra)

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


DEEPINFRA = os.environ.get("DEEPINFRA_BASE_URL") or "https://api.deepinfra.com/v1/openai"
# V4-Flash: 1M de contexto (cabe a base cacheada) + cache automático por prefixo
# (cached 0,2×, write grátis). Trocável por env sem mexer no código.
MODELO_CHAT = os.environ.get("TUIU_GUIA_MODELO", "deepseek-ai/DeepSeek-V4-Flash")

SISTEMA = """Você é o assistente do Tuiú, que orienta quem executa transferências da \
União como TERCEIRO (OSC/entidade privada sem fins lucrativos) em parceria com órgão federal.

REGRAS DURAS:
1. Responda SOMENTE com o que estiver nos TRECHOS fornecidos. Não use conhecimento próprio.
2. Se a resposta não estiver nos trechos, diga exatamente o que falta e sugira em qual etapa \
procurar. NÃO invente prazo, artigo, número de portaria nem passo de sistema.
3. Cite a fonte de cada afirmação com o número do trecho, assim: [1], [2].
4. Quando houver PRAZO, diga sempre DE QUEM é o prazo (do convenente ou do concedente) e a base \
legal — confundir isso é o erro mais caro do setor.
5. Português do Brasil, direto e prático. Sem enrolação, sem repetir a pergunta. Se couber passo \
a passo, use lista curta.
6. Regra muda por regime (PI 424 antigo · PC 33 completo · PC 28 simplificado): se a resposta \
depender do regime, diga isso."""


_base_txt: str | None = None
_base_carga: int | None = None
# Base MÉDIA (decisão do dono): equilíbrio qualidade × velocidade. ~1,1M chars ≈
# 400k tokens de base cacheada — a frio ~25s, a quente ~4s (contra 54s/7-25s da
# base cheia de 770k). O que não cabe NÃO some: a busca roda sobre o índice
# COMPLETO e traz por pergunta (o holofote backfilla). Guia sempre entra.
# Português tokeniza a ~2,73 chars/token; V4-Flash tem 1M de contexto.
BASE_MAX_CHARS = 1_100_000


def _base(con) -> str:
    """A base cacheada do modelo: guia inteiro + o quanto do manual couber no teto.

    V4-Flash tem 1M de contexto e cache automático por prefixo (cached = 0,2×,
    cache-write grátis). A base é um prefixo idêntico a cada chamada: a 1ª paga
    cheio, as seguintes pagam 20%. Guia primeiro (alto sinal), depois os manuais
    por módulo/etapa até o teto. Cache em memória; recarrega se o índice mudar."""
    global _base_txt, _base_carga
    n = con.execute("SELECT count(*) FROM guia_trechos").fetchone()[0]
    if _base_txt is not None and _base_carga == n:
        return _base_txt
    partes, tot = [], 0
    for fonte, modulo, etapa, documento, texto in con.execute(
            "SELECT fonte, modulo, etapa, documento, texto FROM guia_trechos"
            " ORDER BY (fonte <> 'guia'), modulo, etapa, id"):
        p = f"[{fonte} · {etapa or modulo} · {documento}]\n{texto}"
        if fonte != "guia" and tot + len(p) > BASE_MAX_CHARS:
            continue   # não cabe na base; a recuperação por pergunta cobre
        partes.append(p)
        tot += len(p) + 2
    _base_txt = "\n\n".join(partes)
    _base_carga = n
    return _base_txt


SISTEMA_CAG = SISTEMA + """

Você recebe ABAIXO o ACERVO COMPLETO (guia próprio + manuais oficiais do
Transferegov) como sua base de conhecimento. Responda com base nele. Depois do
acervo vêm as PASSAGENS MAIS RELEVANTES para a pergunta, numeradas — cite-as por
[n] quando as usar. Se a resposta não estiver no acervo, diga isso."""


def perguntar(q: str, k: int = 6) -> dict:
    """Cache-augmented generation: o acervo inteiro é a base (prefixo cacheado);
    a recuperação local dá o holofote (passagens numeradas) e as fontes com PDF.
    Só a redação vai à DeepInfra. Sem chave, degrada para os trechos."""
    q = (q or "").strip()
    if len(q) < 3:
        return {"resposta": None, "erro": "pergunta muito curta", "fontes": []}
    hits = buscar(q, k=k).get("resultados", [])
    chave = os.environ.get("DEEPINFRA_API_KEY")
    if not chave:
        return {"resposta": None, "fontes": hits,
                "erro": "sem DEEPINFRA_API_KEY — mostrando só os trechos encontrados"}

    with conectar() as con:
        base = _base(con)
    sistema = SISTEMA_CAG + "\n\n===== ACERVO (base de conhecimento) =====\n" + base
    holofote = "\n\n".join(
        f"[{n}] ({h['documento']} · {h.get('etapa') or '—'})\n{h['trecho']}"
        for n, h in enumerate(hits, 1)) or "(sem passagens em destaque)"
    corpo = json.dumps({
        "model": MODELO_CHAT,
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content":
                      f"PASSAGENS MAIS RELEVANTES (cite por [n]):\n{holofote}\n\nPERGUNTA: {q}"}],
        "temperature": 0.2, "max_tokens": 900,
    }).encode()
    req = urllib.request.Request(f"{DEEPINFRA}/chat/completions", data=corpo, headers={
        "Authorization": f"Bearer {chave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        texto = (d.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        uso = d.get("usage") or {}
    except Exception as exc:  # noqa: BLE001 — LLM fora do ar não tira a busca do ar
        return {"resposta": None, "fontes": hits, "erro": f"falha na geração: {exc}"}
    cacheados = (uso.get("prompt_tokens_details") or {}).get("cached_tokens")
    return {"resposta": texto or None, "fontes": hits, "modelo": MODELO_CHAT,
            "tokens": uso.get("total_tokens"), "tokens_entrada": uso.get("prompt_tokens"),
            "tokens_cacheados": cacheados, "tokens_saida": uso.get("completion_tokens")}


def etapas() -> list[dict]:
    """Esqueleto de navegação: as etapas do pipeline, com quanto há de cada."""
    with conectar() as con:
        return [{"etapa": e, "modulo": m, "trechos": n, "documentos": d}
                for e, m, n, d in con.execute(
                    "SELECT etapa, min(modulo), count(*), count(DISTINCT documento)"
                    " FROM guia_trechos WHERE etapa IS NOT NULL AND etapa <> ''"
                    " GROUP BY etapa ORDER BY min(modulo), etapa")]
