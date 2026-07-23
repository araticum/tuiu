"""Indexa o acervo oficial: PDF → texto → trechos → embedding local → Postgres.

Extrai com PyMuPDF, agrupa páginas em trechos de ~900 caracteres (os tutoriais têm
pouco texto por página — são muitas telas), embeda com um modelo multilíngue ONNX
rodando no próprio host (sem chave, sem custo, ~300 MB residentes) e grava em
`guia_trechos`, onde o FTS português é gerado automaticamente.

Escolha do modelo: MiniLM multilíngue (384d, 220 MB) em vez do e5-large (2,2 GB)
porque este host roda a PRODUÇÃO do veredas com 16 GB — não se come a RAM do
vizinho. A perda de qualidade é compensada pela busca híbrida (semântica + FTS).

    python ingest/manuais/indexar_manuais.py            # indexa tudo (idempotente)
    python ingest/manuais/indexar_manuais.py --limite 5 # amostra, p/ testar
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

ACERVO = Path("/mnt/dados-gov/tuiu-manuais")
MODELO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
ALVO_CHARS = 900          # tamanho de trecho: pergunta típica cabe numa resposta
MIN_CHARS = 120           # abaixo disso é legenda de print, não conteúdo


def _trechos_do_pdf(caminho: Path) -> list[dict]:
    """Agrupa páginas até ~ALVO_CHARS, guardando o intervalo de páginas."""
    import fitz
    try:
        doc = fitz.open(caminho)
    except Exception as exc:  # noqa: BLE001 — PDF corrompido não derruba o lote
        print(f"    ! não abriu: {exc}")
        return []
    saida, buf, p_ini = [], "", None
    for n, pagina in enumerate(doc, 1):
        try:
            t = " ".join((pagina.get_text() or "").split())
        except Exception:  # noqa: BLE001
            t = ""
        if not t:
            continue
        if p_ini is None:
            p_ini = n
        buf = (buf + " " + t).strip()
        if len(buf) >= ALVO_CHARS:
            saida.append({"texto": buf[:2000], "pagina_ini": p_ini, "pagina_fim": n})
            buf, p_ini = "", None
    if buf and len(buf) >= MIN_CHARS:
        saida.append({"texto": buf[:2000], "pagina_ini": p_ini, "pagina_fim": len(doc)})
    doc.close()
    return saida


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--limite", type=int, default=0, help="indexa só N documentos (teste)")
    args = ap.parse_args()

    from app.db import conectar, migrar
    migrar()

    manifesto = json.loads((ACERVO / "manifesto.json").read_text(encoding="utf-8"))
    docs = [m for m in manifesto if m.get("arquivo") and Path(m["arquivo"]).exists()]
    if args.limite:
        docs = docs[: args.limite]
    print(f"documentos: {len(docs)}")

    # 1) extrai e monta os trechos
    trechos: list[dict] = []
    for i, d in enumerate(docs, 1):
        ts = _trechos_do_pdf(Path(d["arquivo"]))
        for t in ts:
            t.update({"fonte": "manual", "modulo": d.get("modulo"), "etapa": d.get("etapa"),
                      "papel": d.get("papel"), "documento": d.get("titulo"),
                      "arquivo": d.get("arquivo"), "url": d.get("url")})
        trechos += ts
        print(f"  [{i}/{len(docs)}] {len(ts):>4} trechos · {(d.get('titulo') or '')[:56]}")
    print(f"trechos: {len(trechos)}")
    if not trechos:
        return

    # 2) embeda local (ONNX) — a 1ª execução baixa o modelo
    from fastembed import TextEmbedding
    print(f"embedando com {MODELO} …")
    modelo = TextEmbedding(model_name=MODELO)
    vetores = list(modelo.embed([t["texto"] for t in trechos], batch_size=64))
    print(f"vetores: {len(vetores)} × {len(vetores[0])}d")

    # 3) grava (substitui só a fonte 'manual' — o guia próprio é indexado à parte)
    with conectar() as con:
        con.execute("DELETE FROM guia_trechos WHERE fonte='manual'")
        for t, v in zip(trechos, vetores):
            con.execute(
                "INSERT INTO guia_trechos (fonte, modulo, etapa, papel, documento,"
                " pagina_ini, pagina_fim, arquivo, url, texto, vetor)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (t["fonte"], t["modulo"], t["etapa"], t["papel"], t["documento"],
                 t["pagina_ini"], t["pagina_fim"], t["arquivo"], t["url"], t["texto"],
                 [float(x) for x in v]))
        con.commit()
        n = con.execute("SELECT count(*) FROM guia_trechos WHERE fonte='manual'").fetchone()[0]
    print(f"indexados {n} trechos de manual")


if __name__ == "__main__":
    main()
