"""Remediação: apaga nome de pessoa física dos recortes JÁ gravados.

A máscara no `recorte_ente._grava` vale da próxima gravação em diante. Os
recortes que já estão em disco continuam com o nome do beneficiário de cada
pagamento em claro — prestador, empregado, bolsista das OSCs. Sem finalidade
escrita, isso é o D1 do gate sendo violado retroativamente.

Reescreve os `.jsonl.gz` no lugar, preservando tudo o mais (contagem, valores,
datas — o que de fato usamos). Idempotente: rodar de novo não muda nada.

    python ferramentas/mascarar_recortes.py --conferir   # só relata
    python ferramentas/mascarar_recortes.py              # aplica
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ingest" / "transferegov_g2"))

from recorte_ente import CAMPOS_NOME_PF, _mascara_nome  # noqa: E402


def _ja_mascarado(v) -> bool:
    """"J. D. S." — só iniciais e pontos. Evita mascarar duas vezes."""
    s = str(v or "").strip()
    return bool(s) and all(p.endswith(".") and len(p) <= 2 for p in s.split())


def processar(caminho: Path, aplicar: bool) -> tuple[int, int]:
    linhas, achados = 0, 0
    saida = []
    with gzip.open(caminho, "rt", encoding="utf-8") as fh:
        for l in fh:
            d = json.loads(l)
            linhas += 1
            mexeu = False
            for campo in CAMPOS_NOME_PF:
                v = d.get(campo)
                if v and str(v).lower() not in ("none", "null") and not _ja_mascarado(v):
                    d[campo] = _mascara_nome(v)
                    mexeu = True
            achados += bool(mexeu)
            saida.append(d)
    if aplicar and achados:
        tmp = caminho.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            for d in saida:
                fh.write(json.dumps(d, ensure_ascii=False) + "\n")
        tmp.replace(caminho)   # troca atômica: nunca deixa o arquivo pela metade
    return linhas, achados


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--conferir", action="store_true", help="só relata, não altera")
    ap.add_argument("--raiz", default=str(RAIZ / "data" / "recortes"))
    args = ap.parse_args()

    base = Path(args.raiz)
    if not base.exists():
        sys.exit(f"sem recortes em {base}")

    arquivos = sorted(base.rglob("*.jsonl.gz"))
    tot_lin = tot_ach = tot_arq = 0
    for arq in arquivos:
        linhas, achados = processar(arq, aplicar=not args.conferir)
        tot_lin += linhas
        tot_ach += achados
        if achados:
            tot_arq += 1
            print(f"  {'[conferir] ' if args.conferir else ''}{achados:6d} linha(s) com nome de PF"
                  f"  {arq.relative_to(base)}")
    verbo = "encontradas" if args.conferir else "mascaradas"
    print(f"\n{len(arquivos)} arquivo(s) varridos, {tot_lin:,} linha(s); "
          f"{tot_ach:,} {verbo} em {tot_arq} arquivo(s)")
    if args.conferir and tot_ach:
        print("rode sem --conferir para aplicar")


if __name__ == "__main__":
    main()
