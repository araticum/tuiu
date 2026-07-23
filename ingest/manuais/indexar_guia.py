"""Indexa o GUIA próprio (guia_pipeline.json) junto do acervo oficial.

O acervo oficial ensina a OPERAR o sistema; ele não responde "qual o prazo" nem
"o que faço quando rejeitam" — medido: essas perguntas voltavam fracas. O guia
cobre esse buraco, e é quebrado em passagens por TIPO (o que é / o que fazer /
prazos / armadilhas / o que o Tuiú faz) para que a pergunta caia na passagem
certa: quem pergunta prazo tem que cair na lista de prazos com a base legal.

    python ingest/manuais/indexar_guia.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))
GUIA = Path(__file__).resolve().parent / "guia_pipeline.json"
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def passagens(g: dict) -> list[dict]:
    saida = []
    regimes = "; ".join(f"{r['nome']}: {r['quando']} — {r['nota']}" for r in g.get("regimes", []))
    saida.append({"etapa": "0. Regimes", "documento": "Guia — regimes normativos",
                  "texto": f"Regimes que regem as transferências e como saber qual é o seu. {regimes}"})
    for s in g["secoes"]:
        et, faz = s["etapa"], s.get("tuiu_faz")
        saida.append({"etapa": et, "documento": f"Guia — {et}: o que é e o que fazer",
                      "texto": f"{et}. O que é: {s['o_que_e']} O que fazer: "
                               + " ".join(f"({i}) {p}" for i, p in enumerate(s.get("o_que_fazer", []), 1))})
        if s.get("prazos"):
            linhas = "; ".join(
                f"{p['o_que']}: {p['prazo']} (base legal: {p['base_legal']}; prazo do {p['de_quem']})"
                for p in s["prazos"])
            saida.append({"etapa": et, "documento": f"Guia — {et}: prazos e base legal",
                          "texto": f"Prazos da etapa {et}, com base legal e de quem é o prazo. {linhas}"})
        if s.get("armadilhas"):
            saida.append({"etapa": et, "documento": f"Guia — {et}: armadilhas",
                          "texto": f"Erros comuns e armadilhas na etapa {et}: "
                                   + " ".join(f"({i}) {a}" for i, a in enumerate(s["armadilhas"], 1))})
        if faz:
            saida.append({"etapa": et, "documento": f"Guia — {et}: o que o Tuiú faz por você",
                          "texto": f"Na etapa {et}, a plataforma Tuiú: {faz}"})
    return saida


def main():
    from app.db import conectar, migrar
    migrar()
    g = json.loads(GUIA.read_text(encoding="utf-8"))
    ps = passagens(g)
    print(f"passagens do guia: {len(ps)}")

    from fastembed import TextEmbedding
    modelo = TextEmbedding(model_name=MODELO)
    vetores = list(modelo.embed([p["texto"] for p in ps], batch_size=32))

    with conectar() as con:
        con.execute("DELETE FROM guia_trechos WHERE fonte='guia'")
        for p, v in zip(ps, vetores):
            con.execute(
                "INSERT INTO guia_trechos (fonte, modulo, etapa, papel, documento, texto, vetor)"
                " VALUES ('guia','guia',%s,'convenente',%s,%s,%s)",
                (p["etapa"], p["documento"], p["texto"], [float(x) for x in v]))
        con.commit()
        n = con.execute("SELECT count(*) FROM guia_trechos WHERE fonte='guia'").fetchone()[0]
    print(f"indexadas {n} passagens do guia")


if __name__ == "__main__":
    main()
