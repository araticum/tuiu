"""Onboarding de cliente — entra na carteira por comando, não por commit.

Dado um CNPJ, o comando: valida, descobre o nome na fonte oficial, cadastra na
tabela `clientes`, roda o pipeline completo daquele cliente (recorte g2 +
legado detru + regularidade CEPIM/CEIS/CNEP + prazos) e deixa ele aparecendo no
cockpit, na fila e com ficha própria.

Uso:
    py -3 ferramentas/onboarding.py 20069629000103
    py -3 ferramentas/onboarding.py 20069629000103 --apelido "Ecos" --operador pedro
    py -3 ferramentas/onboarding.py --listar
    py -3 ferramentas/onboarding.py 20069629000103 --desativar
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(RAIZ / "ingest" / "transferegov_g2"))

from app.db import conectar, migrar  # noqa: E402


def _digitos(v: str) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _valido(cnpj: str) -> bool:
    """Validação real de CNPJ (dígitos verificadores) — evita cadastrar lixo."""
    c = _digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False
    for tam in (12, 13):
        pesos = list(range(tam - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(int(c[i]) * pesos[i] for i in range(tam))
        dv = (soma * 10) % 11
        dv = 0 if dv == 10 else dv
        if dv != int(c[tam]):
            return False
    return True


def _dados_oficiais(cnpj: str) -> dict:
    """Nome/UF/município do cliente, direto da g2 (fonte oficial)."""
    from g2_parcerias import BASE, _get_json
    try:
        r = _get_json(f"{BASE}/proposta?cnpj_ente_recebedor={cnpj}&pagina=1&tamanho_da_pagina=1")
        d = (r.get("data") or [{}])[0]
        return {"nome": d.get("nm_ente_recebedor"), "uf": d.get("sg_uf_recebedor"),
                "municipio": d.get("nm_municipio_recebedor"),
                "natureza": d.get("nm_natureza_juridica"), "propostas": r.get("total_items", 0)}
    except Exception as exc:  # noqa: BLE001
        return {"erro": str(exc)[:120]}


def cadastrar(cnpj: str, apelido: str | None, operador: str | None) -> dict:
    doc = _digitos(cnpj)
    if not _valido(doc):
        return {"ok": False, "erro": f"CNPJ inválido: {cnpj}"}
    oficial = _dados_oficiais(doc)
    if not oficial.get("nome"):
        return {"ok": False, "erro": "CNPJ sem propostas na g2 — confira "
                                     f"(retorno: {oficial.get('erro') or 'nada encontrado'})"}
    migrar()
    with conectar() as con:
        con.execute(
            "INSERT INTO clientes (doc, tipo_doc, nome, apelido, natureza, uf, municipio, operador)"
            " VALUES (%s,'CNPJ',%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (doc) DO UPDATE SET nome=EXCLUDED.nome,"
            " apelido=COALESCE(EXCLUDED.apelido, clientes.apelido),"
            " natureza=EXCLUDED.natureza, uf=EXCLUDED.uf, municipio=EXCLUDED.municipio,"
            " operador=COALESCE(EXCLUDED.operador, clientes.operador), ativo=true",
            (doc, oficial["nome"], apelido, oficial.get("natureza"),
             oficial.get("uf"), oficial.get("municipio"), operador))
        con.commit()
    return {"ok": True, "doc": doc, **oficial}


def _rodar(rotulo: str, cmd: list[str]) -> bool:
    print(f"  → {rotulo}…", end=" ", flush=True)
    r = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    print("ok" if r.returncode == 0 else f"FALHOU (rc={r.returncode})")
    if r.returncode != 0:
        print("     ", (r.stderr or r.stdout or "")[-200:].replace("\n", " "))
    return r.returncode == 0


def pipeline(doc: str) -> None:
    py = sys.executable
    _rodar("recorte g2", [py, "ingest/transferegov_g2/recorte_ente.py", "--cnpj", doc])
    _rodar("legado detru", [py, "ingest/transferegov_g2/detru_recorte.py", "--cnpj", doc])
    _rodar("regularidade", [py, "ingest/transparencia/coletar_regularidade.py", "--cnpj", doc])
    _rodar("prazos", [py, "backend/app/motor_prazos.py"])
    _rodar("eventos (baseline)", [py, "backend/app/eventos.py"])


def listar() -> None:
    migrar()
    with conectar() as con:
        linhas = con.execute(
            "SELECT doc, COALESCE(apelido, nome), natureza, uf, operador, ativo"
            " FROM clientes ORDER BY ativo DESC, 2").fetchall()
    if not linhas:
        print("carteira vazia — cadastre com: py -3 ferramentas/onboarding.py <cnpj>")
        return
    for doc, nome, nat, uf, op, ativo in linhas:
        print(f"  [{'ativo' if ativo else 'inativo'}] {nome[:38]:38} {doc} {uf or '--'} "
              f"| {(nat or '')[:24]:24} | operador: {op or '—'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("cnpj", nargs="?")
    ap.add_argument("--apelido")
    ap.add_argument("--operador")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--desativar", action="store_true")
    ap.add_argument("--sem-pipeline", action="store_true", help="só cadastra, não coleta")
    args = ap.parse_args()

    if args.listar or not args.cnpj:
        listar()
        return

    doc = _digitos(args.cnpj)
    if args.desativar:
        migrar()
        with conectar() as con:
            con.execute("UPDATE clientes SET ativo=false WHERE doc=%s", (doc,))
            con.commit()
        print(f"cliente {doc} desativado (dados preservados)")
        return

    r = cadastrar(doc, args.apelido, args.operador)
    if not r["ok"]:
        print("ERRO:", r["erro"])
        sys.exit(1)
    print(f"cadastrado: {r['nome']} ({r['doc']}) · {r.get('municipio') or '—'}/{r.get('uf') or '—'}")
    print(f"  natureza: {r.get('natureza')} · propostas na g2: {r.get('propostas')}")
    if args.sem_pipeline:
        return
    print("\nrodando o pipeline do cliente:")
    pipeline(doc)
    print("\npronto — o cliente já aparece no cockpit, na fila e tem ficha própria.")


if __name__ == "__main__":
    main()
