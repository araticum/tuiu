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
from regularidade_terceiro import consultar, consultar_pessoa  # noqa: E402


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
    sys.path.insert(0, str(RAIZ / "backend"))
    from app.carteira import docs_ativos

    ativos = docs_ativos()
    cnpjs = ["".join(c for c in x if c.isdigit()) for x in args.cnpj] or [
        d.name for d in sorted(snap.iterdir())
        if d.is_dir() and (d / "carteira.json").exists() and (not ativos or d.name in ativos)]

    # dirigentes cadastrados (PF): no MROSC, dirigente impedido contamina a entidade
    pessoas: dict[str, list] = {}
    try:
        sys.path.insert(0, str(RAIZ / "backend"))
        from app.db import conectar
        with conectar() as con:
            for doc, cpf, nome, papel in con.execute(
                    "SELECT doc_cliente, cpf, nome, papel FROM clientes_pessoas WHERE ativo"):
                pessoas.setdefault(doc, []).append({"cpf": cpf, "nome": nome, "papel": papel})
    except Exception as exc:  # noqa: BLE001 — sem banco, segue só com a entidade
        print(f"  (dirigentes não consultados: {exc})")

    for cnpj in cnpjs:
        r = consultar(cnpj)
        r["coletado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        r["disponivel"] = True

        r["dirigentes"] = []
        for p in pessoas.get(cnpj, []):
            # por NOME, nao por CPF: o QSA da Receita entrega o CPF mascarado e
            # `codigoSancionado` exige o documento inteiro — mandar 6 digitos
            # devolveria vazio, parecendo "nada consta" sem ter consultado.
            rp = consultar_pessoa(p["nome"], p["cpf"])
            r["dirigentes"].append({**p, "impedido": rp["impedido"],
                                    "a_confirmar": len(rp["a_confirmar"]),
                                    "fontes": {k: v["registros"] for k, v in rp["fontes"].items()}})
            if rp["impedido"]:
                r["impedido"] = True
                r.setdefault("avisos", []).append(
                    f"dirigente {p['nome']} ({p['papel'] or 'sem papel'}) consta em cadastro de sanção")
            elif rp["a_confirmar"]:
                # homonimo possivel: nao acusa sozinho, mas nao esconde
                r.setdefault("avisos", []).append(
                    f"dirigente {p['nome']}: {len(rp['a_confirmar'])} sanção(ões) com o mesmo nome "
                    f"e sem CPF no registro — CONFERIR manualmente")
        (snap / cnpj).mkdir(parents=True, exist_ok=True)
        (snap / cnpj / "regularidade.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        marca = "IMPEDIDO" if r["impedido"] else "ok"
        fontes = " ".join(f"{k}={v['registros']}" for k, v in r["fontes"].items())
        print(f"  {cnpj}: {marca} | {fontes}" + (f" | avisos={len(r['avisos'])}" if r["avisos"] else ""))
    print(f"\nregularidade (CEPIM/CEIS/CNEP) em {snap}")


if __name__ == "__main__":
    main()
