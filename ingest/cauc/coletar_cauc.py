"""Coleta a regularidade (CAUC) dos entes monitorados e grava por recorte.

Escreve data/recortes/<snapshot>/<cnpj>/regularidade.json com o vínculo ao CAUC
(id do ente, resolvido pelo endpoint aberto) e o estado do extrato dos 26 itens
(pendente de captcha nesta fase — coleta completa via doc-extractor na sequência).
Fail-safe: ente que não resolve fica {disponivel:false}, não derruba os demais.

Uso:
    py -3 ingest/cauc/coletar_cauc.py           # todos os CNPJs do snapshot mais recente
    py -3 ingest/cauc/coletar_cauc.py --cnpj 34925198000136
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliente_cauc import consultar  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
RECORTES = RAIZ / "data" / "recortes"


def snapshot_recente() -> Path:
    dirs = [d for d in sorted(RECORTES.iterdir(), reverse=True)
            if d.is_dir() and any(s.is_dir() for s in d.iterdir())] if RECORTES.exists() else []
    if not dirs:
        sys.exit("sem recortes — rode o ingest de entes antes")
    return dirs[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cnpj", action="append", default=[])
    args = ap.parse_args()

    snap = snapshot_recente()
    cnpjs = [("".join(c for c in x if c.isdigit())) for x in args.cnpj] or [
        d.name for d in sorted(snap.iterdir()) if d.is_dir() and (d / "carteira.json").exists()
    ]
    for cnpj in cnpjs:
        r = consultar(cnpj)
        r["coletado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (snap / cnpj).mkdir(parents=True, exist_ok=True)
        (snap / cnpj / "regularidade.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        ente = r.get("ente_cauc", {})
        print(f"{cnpj}: {'OK' if r['disponivel'] else 'FALHA'} "
              f"CAUC id={ente.get('id')} extrato={r.get('extrato', {}).get('estado', '-')}")
    print(f"\nregularidade em {snap}")


if __name__ == "__main__":
    main()
