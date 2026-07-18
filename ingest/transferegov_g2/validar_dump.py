"""Valida um dump do /parcerias: conta linhas dos .jsonl[.gz] no disco e confere
com o total_items re-consultado ao vivo na API (independe do _manifest.json,
que reflete só a última execução — runs parciais/retomados são consolidados aqui).

Uso:
    python validar_dump.py data/parcerias/2026-07-17
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

from g2_parcerias import ROTAS, _get_json, _url_rota, data_atualizacao


def contar_linhas(arquivo: Path) -> int:
    abrir = gzip.open if arquivo.suffix == ".gz" else open
    with abrir(arquivo, "rt", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    pasta = Path(sys.argv[1])
    if not pasta.is_dir():
        print(f"pasta não existe: {pasta}")
        return 2

    print(f"data_ultima_atualizacao da API agora: {data_atualizacao()}")
    divergencias = 0
    faltando = 0
    total_geral = 0
    for rota in ROTAS:
        nome = rota.replace("_", "-")
        arquivo = next(
            (p for p in (pasta / f"{nome}.jsonl.gz", pasta / f"{nome}.jsonl") if p.exists()),
            None,
        )
        if arquivo is None:
            print(f"[AUSENTE]    {rota}")
            faltando += 1
            continue
        linhas = contar_linhas(arquivo)
        total_geral += linhas
        esperado = _get_json(_url_rota(rota, 1, {}))["total_items"]
        if linhas == esperado:
            print(f"[OK]         {rota}: {linhas:,}")
        else:
            print(f"[DIVERGENTE] {rota}: disco={linhas:,} api={esperado:,}")
            divergencias += 1

    print(f"\ntotal no disco: {total_geral:,} linhas | divergências: {divergencias} | ausentes: {faltando}")
    return 1 if (divergencias or faltando) else 0


if __name__ == "__main__":
    sys.exit(main())
