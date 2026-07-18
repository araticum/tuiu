"""Smoke do inbox parser (F1.6): confiança por remetente + atribuição + defesa.

Roda sobre as fixtures sintéticas. Garante:
  - e-mail de domínio confiável e atribuível vira evento origem='inbox';
  - e-mail fora da allowlist (phishing/injeção) NÃO vira evento (suspeito);
  - nenhuma instrução embutida no corpo é obedecida (só extraímos texto).
Não usa IMAP nem rede.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(RAIZ / "ingest" / "inbox"))

from app.db import conectar, migrar  # noqa: E402
import coletar_inbox  # noqa: E402
from parser_email import parse_email  # noqa: E402

FIX = RAIZ / "testes" / "fixtures" / "inbox"


def main():
    migrar()
    with conectar() as con:
        con.execute("DELETE FROM eventos WHERE origem='inbox'")
        con.commit()
        entes = coletar_inbox._entes_monitorados(con)
        res = {}
        for eml in sorted(FIX.glob("*.eml")):
            p = parse_email(eml.read_bytes())
            r = coletar_inbox.registrar(con, p, entes)
            res[eml.name] = (r, p["confiavel"], p["tipo"], p["cnpjs"])
        con.commit()
        n_inbox = con.execute("SELECT count(*) FROM eventos WHERE origem='inbox'").fetchone()[0]

    ok = True
    for nome, (r, conf, tipo, cnpjs) in res.items():
        print(f"  {nome}: {r} (confiavel={conf}, tipo={tipo}, cnpj={cnpjs})")
    # asserções
    phishing = [v for k, v in res.items() if "phishing" in k]
    if phishing and phishing[0][0] != "suspeito":
        print("FALHOU: phishing deveria ser suspeito"); ok = False
    if n_inbox != 2:
        print(f"FALHOU: esperava 2 eventos inbox, veio {n_inbox}"); ok = False
    if any(r[0] == "atribuido" and not r[1] for r in res.values()):
        print("FALHOU: evento atribuido de remetente nao confiavel"); ok = False

    # limpa
    with conectar() as con:
        con.execute("DELETE FROM eventos WHERE origem='inbox'"); con.commit()

    print("OK" if ok else "FALHAS ACIMA")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
