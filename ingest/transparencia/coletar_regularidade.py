"""Coleta a regularidade dos TERCEIROS monitorados (CEPIM/CEIS/CNEP).

Substitui a coleta de CAUC (que media obrigação fiscal do ENTE) — ver a
correção de escopo no plano §1. Grava `regularidade.json` por ente no recorte,
no mesmo lugar que a carteira lê.

Uso:
    py -3 ingest/transparencia/coletar_regularidade.py
    py -3 ingest/transparencia/coletar_regularidade.py --cnpj 20069629000103
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from regularidade_terceiro import consultar  # noqa: E402


def snapshot_recente() -> Path:
    rec = RAIZ / "data" / "recortes"
    for d in sorted(rec.iterdir(), reverse=True):
        if d.is_dir() and any((s / "carteira.json").exists() for s in d.iterdir() if s.is_dir()):
            return d
    sys.exit("sem recortes")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cnpj", action="append", default=[])
    args = ap.parse_args()

    snap = snapshot_recente()
    cnpjs = ["".join(c for c in x if c.isdigit()) for x in args.cnpj] or [
        d.name for d in sorted(snap.iterdir()) if d.is_dir() and (d / "carteira.json").exists()]

    for cnpj in cnpjs:
        r = consultar(cnpj)
        r["coletado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        r["disponivel"] = True
        (snap / cnpj).mkdir(parents=True, exist_ok=True)
        (snap / cnpj / "regularidade.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        marca = "IMPEDIDO" if r["impedido"] else "ok"
        fontes = " ".join(f"{k}={v['registros']}" for k, v in r["fontes"].items())
        print(f"  {cnpj}: {marca} | {fontes}" + (f" | avisos={len(r['avisos'])}" if r["avisos"] else ""))
    print(f"\nregularidade (CEPIM/CEIS/CNEP) em {snap}")


if __name__ == "__main__":
    main()
