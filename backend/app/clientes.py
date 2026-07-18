"""Carteira de clientes do operador (terceiros que receberam verba pública).

Semeia/atualiza a tabela `clientes` a partir dos recortes já feitos e permite
marcar quem é CLIENTE (terceiro que a casa opera) e quem é apenas contraparte
(o ente público do outro lado do instrumento).
"""

from __future__ import annotations

import json

from app.carteira import ROTULOS, snapshot_mais_recente
from app.db import conectar

# Terceiros que a casa opera (o resto dos recortes é contraparte/contexto).
CLIENTES_PADRAO = {
    "20069629000103": "Ecos da Natureza",
    "37113180000128": "Pioneiras Sociais",
    "31883355000108": "Coop. Lixo Não",
}


def semear() -> dict:
    """Cria/atualiza os clientes a partir do snapshot mais recente."""
    snap = snapshot_mais_recente()
    if snap is None:
        return {"erro": "sem recortes"}
    criados = 0
    with conectar() as con:
        for sub in sorted(snap.iterdir()):
            cj = sub / "carteira.json"
            if not (sub.is_dir() and cj.exists()):
                continue
            c = json.loads(cj.read_text(encoding="utf-8"))
            doc = c["cnpj"]
            if doc not in CLIENTES_PADRAO:
                continue  # contraparte não entra na carteira de clientes
            con.execute(
                "INSERT INTO clientes (doc, tipo_doc, nome, apelido, uf, municipio)"
                " VALUES (%s,'CNPJ',%s,%s,%s,%s)"
                " ON CONFLICT (doc) DO UPDATE SET nome=EXCLUDED.nome, apelido=EXCLUDED.apelido,"
                " uf=EXCLUDED.uf, municipio=EXCLUDED.municipio",
                (doc, c.get("nome") or ROTULOS.get(doc, doc), CLIENTES_PADRAO[doc],
                 c.get("uf"), c.get("municipio")))
            criados += 1
        con.commit()
        total = con.execute("SELECT count(*) FROM clientes").fetchone()[0]
    return {"semeados": criados, "clientes_na_base": total}


def listar() -> dict:
    with conectar() as con:
        cols = ["doc", "tipo_doc", "nome", "apelido", "natureza", "uf", "municipio", "operador", "ativo"]
        clientes = [dict(zip(cols, r)) for r in con.execute(
            "SELECT doc, tipo_doc, nome, apelido, natureza, uf, municipio, operador, ativo"
            " FROM clientes ORDER BY apelido NULLS LAST, nome")]
        for c in clientes:
            c["pessoas"] = [dict(zip(["cpf", "nome", "papel"], p)) for p in con.execute(
                "SELECT cpf, nome, papel FROM clientes_pessoas WHERE doc_cliente=%s AND ativo",
                (c["doc"],))]
    return {"clientes": clientes}


if __name__ == "__main__":
    from app.db import migrar
    print("migracoes:", migrar() or "nenhuma nova")
    print(semear())
