"""Puxa os dirigentes (QSA) dos clientes a partir de dado aberto da Receita.

Por que importa: no MROSC, **dirigente impedido contamina a entidade**. A regra
já estava implementada no Tuiú e nunca tinha sido exercitada, porque
`clientes_pessoas` estava vazia e não havia fonte.

Fonte: quadro de sócios e administradores do CNPJ (dado aberto da Receita
Federal), servido por BrasilAPI, com MinhaReceita de reserva.

⚠️ O CPF vem **MASCARADO** (`***790718**` — só os 6 dígitos do meio). Isso é bom
para privacidade (guardamos menos) e ruim para a consulta de sanção, que exige
documento inteiro. Por isso a checagem de impedimento passou a ser por NOME, com
os dígitos visíveis servindo de confirmação contra homônimo — ver
`ingest/transparencia/coletar_regularidade.py`.

Uso:
    python ferramentas/dirigentes.py              # todos os clientes ativos
    python ferramentas/dirigentes.py --cnpj 20069629000103
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.db import conectar, migrar  # noqa: E402

FONTES = ("https://brasilapi.com.br/api/cnpj/v1/{}", "https://minhareceita.org/{}")
INTERVALO = 1.5   # APIs públicas e gratuitas: ir devagar é educação e sobrevivência
_CTX = ssl.create_default_context()


def _buscar(cnpj: str) -> dict | None:
    for molde in FONTES:
        try:
            req = urllib.request.Request(molde.format(cnpj),
                                         headers={"User-Agent": "tuiu/1.0 (gestao de convenios)"})
            with urllib.request.urlopen(req, timeout=45, context=_CTX) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:      # sem pressa; a próxima fonte ou a próxima volta resolve
                time.sleep(5)
            continue
        except Exception:  # noqa: BLE001
            continue
    return None


def _pessoas(dados: dict) -> list[dict]:
    saida = []
    for s in (dados.get("qsa") or []):
        nome = (s.get("nome_socio") or "").strip()
        if not nome:
            continue
        # guarda o CPF como vem: MASCARADO. Não temos, nem queremos, o completo.
        cpf = (s.get("cnpj_cpf_do_socio") or "").strip()
        saida.append({"nome": nome, "cpf": cpf or "(sem documento)",
                      "papel": (s.get("qualificacao_socio") or "sócio/administrador").strip()})
    return saida


def sincronizar(docs: list[str]) -> dict:
    migrar()
    resumo = {"clientes": 0, "pessoas": 0, "sem_fonte": []}
    with conectar() as con:
        for i, doc in enumerate(docs):
            if i:
                time.sleep(INTERVALO)
            dados = _buscar(doc)
            if not dados:
                resumo["sem_fonte"].append(doc)
                print(f"  {doc}: fonte indisponível", flush=True)
                continue
            pessoas = _pessoas(dados)
            for p in pessoas:
                con.execute(
                    "INSERT INTO clientes_pessoas (doc_cliente, cpf, nome, papel)"
                    " VALUES (%s,%s,%s,%s)"
                    " ON CONFLICT (doc_cliente, cpf) DO UPDATE SET nome=EXCLUDED.nome,"
                    " papel=EXCLUDED.papel, ativo=true",
                    (doc, p["cpf"], p["nome"], p["papel"]))
            con.commit()
            resumo["clientes"] += 1
            resumo["pessoas"] += len(pessoas)
            print(f"  {doc}: {len(pessoas)} dirigente(s) — "
                  + ", ".join(f"{p['nome'][:26]} ({p['papel'][:18]})" for p in pessoas[:3]),
                  flush=True)
    return resumo


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cnpj", action="append", default=[])
    args = ap.parse_args()

    if args.cnpj:
        docs = ["".join(c for c in x if c.isdigit()) for x in args.cnpj]
    else:
        with conectar() as con:
            docs = [r[0] for r in con.execute(
                "SELECT doc FROM clientes WHERE ativo AND tipo_doc='CNPJ' ORDER BY doc")]

    print(f"buscando dirigentes de {len(docs)} cliente(s)…")
    r = sincronizar(docs)
    print(f"\n{r['clientes']} cliente(s), {r['pessoas']} dirigente(s) gravado(s)")
    if r["sem_fonte"]:
        print(f"sem fonte para {len(r['sem_fonte'])}: {', '.join(r['sem_fonte'][:6])}")


if __name__ == "__main__":
    main()
