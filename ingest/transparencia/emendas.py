"""Emendas parlamentares (Portal da Transparência) → lake.

O pipeline do DINHEIRO: emenda financia transferência. Cada registro traz autor
(parlamentar), localidade, função/subfunção e a execução (empenhado/liquidado/
pago). Serve para prever volume futuro de transferência e mapear parlamentar→OSC.

O bulk `download-de-dados/emendas` do Portal está quebrado (HTTP 500 persistente
em 19/07/2026), então puxamos pela `api-de-dados/emendas` (paginada 15/pág, com
a chave e o freio de rate-limit do cliente). Uma passada por ano.

Uso:
    python ingest/transparencia/emendas.py --anos 2015-2026 --out data/emendas
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliente_transparencia import _chave, _get  # noqa: E402


def puxar_ano(ano: int, chave: str) -> list[dict]:
    linhas, pagina = [], 1
    while True:
        lote, erro = _get("emendas", {"ano": ano, "pagina": pagina}, chave)
        if erro:
            print(f"  {ano} pág {pagina}: erro {erro[:60]}", flush=True)
            break
        if not lote:
            break
        linhas.extend(lote)
        if len(lote) < 15:      # última página (page size fixo 15)
            break
        pagina += 1
        if pagina % 100 == 0:
            print(f"  {ano}: {len(linhas):,} até a pág {pagina}", flush=True)
    return linhas


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--anos", default="2015-2026", help="intervalo AAAA-AAAA")
    ap.add_argument("--out", default="data/emendas")
    args = ap.parse_args()

    ini, _, fim = args.anos.partition("-")
    anos = range(int(ini), int(fim or ini) + 1)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chave = _chave()

    total = 0
    manifesto = {}
    for ano in anos:
        linhas = puxar_ano(ano, chave)
        arq = out / f"emendas-{ano}.jsonl.gz"
        with gzip.open(arq, "wt", encoding="utf-8") as fh:
            for l in linhas:
                fh.write(json.dumps(l, ensure_ascii=False) + "\n")
        manifesto[str(ano)] = len(linhas)
        total += len(linhas)
        print(f"{ano}: {len(linhas):,} emendas → {arq.name}", flush=True)

    (out / "_manifest.json").write_text(json.dumps(manifesto, indent=2), encoding="utf-8")
    print(f"\ntotal: {total:,} emendas em {len(list(anos))} ano(s)")


if __name__ == "__main__":
    main()
