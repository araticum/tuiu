"""Ficha do cliente — a tela que o operador abre quando o cliente liga.

Reúne num lugar só tudo do terceiro que a casa opera: cadastro e dirigentes,
carteira (ciclo novo g2 + legado), regularidade (da entidade E dos dirigentes),
prazos abertos, andamento recente, resumo da prestação de contas e o diário de
atendimento.
"""

from __future__ import annotations

import json
from datetime import date

from app.carteira import ROTULOS, listar_entes
from app.db import conectar


def _cadastro(con, doc: str) -> dict:
    r = con.execute(
        "SELECT doc, tipo_doc, nome, apelido, natureza, uf, municipio, operador, ativo, observacao"
        " FROM clientes WHERE doc=%s", (doc,)).fetchone()
    if not r:
        return {"doc": doc, "nome": ROTULOS.get(doc, doc), "na_carteira": False}
    cols = ["doc", "tipo_doc", "nome", "apelido", "natureza", "uf", "municipio", "operador", "ativo", "observacao"]
    c = dict(zip(cols, r))
    c["na_carteira"] = True
    c["pessoas"] = [dict(zip(["id", "cpf", "nome", "papel"], p)) for p in con.execute(
        "SELECT id, cpf, nome, papel FROM clientes_pessoas WHERE doc_cliente=%s AND ativo ORDER BY nome",
        (doc,))]
    return c


def _prazos(con, doc: str) -> list[dict]:
    cols = ["tipo", "instrumento", "data_limite", "descricao", "base_legal", "farol"]
    rows = con.execute(
        "SELECT tipo, instrumento, data_limite, descricao, base_legal, farol FROM marcos"
        " WHERE cnpj=%s AND farol <> 'ok'"
        " ORDER BY CASE farol WHEN 'acao_imediata' THEN 0 WHEN 'vencido' THEN 1 ELSE 2 END,"
        "          data_limite NULLS FIRST LIMIT 60", (doc,)).fetchall()
    saida = []
    hoje = date.today()
    for r in rows:
        d = dict(zip(cols, r))
        d["dias"] = (d["data_limite"] - hoje).days if d["data_limite"] else None
        d["data_limite"] = d["data_limite"].isoformat() if d["data_limite"] else None
        saida.append(d)
    return saida


def _andamento(con, doc: str) -> list[dict]:
    cols = ["rotulo", "tipo", "de", "para", "origem", "snapshot", "criado_em"]
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT rotulo, tipo, de, para, origem, snapshot::text, criado_em FROM eventos"
        " WHERE cnpj=%s ORDER BY id DESC LIMIT 25", (doc,))]


def _diario(con, doc: str) -> list[dict]:
    cols = ["id", "quando", "autor", "tipo", "texto", "referencia"]
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT id, quando, autor, tipo, texto, referencia FROM diario_cliente"
        " WHERE doc_cliente=%s ORDER BY quando DESC LIMIT 100", (doc,))]


def _triagens(con, doc: str) -> list[dict]:
    """O que o operador já tratou (fila) — parte da memória do atendimento."""
    cols = ["chave", "status", "nota", "operador", "atualizado_em"]
    return [dict(zip(cols, r)) for r in con.execute(
        "SELECT chave, status, nota, operador, atualizado_em FROM fila_status"
        " WHERE chave LIKE %s AND status <> 'aberto'"
        " ORDER BY atualizado_em DESC LIMIT 30", (f"%:{doc}:%",))]


def montar(doc: str) -> dict:
    doc = "".join(c for c in doc if c.isdigit())
    base = next((e for e in listar_entes()["entes"] if e["cnpj"] == doc), None)

    with conectar() as con:
        ficha = {
            "cadastro": _cadastro(con, doc),
            "prazos": _prazos(con, doc),
            "andamento": _andamento(con, doc),
            "diario": _diario(con, doc),
            "triagens": _triagens(con, doc),
        }

    if base:
        ficha["carteira"] = {
            "parcerias": base.get("parcerias", {}),
            "legado": base.get("legado", {}),
            "especiais": base.get("especiais", {}),
            "emendas": base.get("emendas_indicadas", {}),
            "municipio": base.get("municipio"), "uf": base.get("uf"),
            "snapshot": base.get("data_atualizacao_api"),
        }
        ficha["regularidade"] = base.get("regularidade", {})
    else:
        ficha["carteira"] = {}
        ficha["regularidade"] = {"disponivel": False, "motivo": "sem recorte para este CNPJ"}

    p = ficha["carteira"].get("parcerias", {}) or {}
    lg = ficha["carteira"].get("legado", {}) or {}
    ficha["resumo"] = {
        "propostas": p.get("propostas", 0),
        "instrumentos_g2": p.get("instrumentos", 0),
        "instrumentos_legado_ativos": lg.get("ativos", 0),
        "prazos_abertos": len(ficha["prazos"]),
        "acao_imediata": sum(1 for x in ficha["prazos"] if x["farol"] == "acao_imediata"),
        "vencidos": sum(1 for x in ficha["prazos"] if x["farol"] == "vencido"),
        "impedido": bool((ficha["regularidade"] or {}).get("impedido")),
        "dirigentes": len((ficha["cadastro"] or {}).get("pessoas", [])),
    }
    return ficha


def anotar(doc: str, texto: str, tipo: str = "nota", autor: str | None = None,
           referencia: str | None = None) -> dict:
    doc = "".join(c for c in doc if c.isdigit())
    if not texto.strip():
        return {"ok": False, "erro": "texto vazio"}
    with conectar() as con:
        r = con.execute(
            "INSERT INTO diario_cliente (doc_cliente, autor, tipo, texto, referencia)"
            " VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (doc, autor, tipo, texto.strip(), referencia)).fetchone()
        con.commit()
    return {"ok": True, "id": r[0]}


def cadastrar_pessoa(doc: str, cpf: str, nome: str, papel: str | None = None) -> dict:
    doc = "".join(c for c in doc if c.isdigit())
    cpf_d = "".join(c for c in cpf if c.isdigit())
    if len(cpf_d) != 11:
        return {"ok": False, "erro": "CPF deve ter 11 dígitos"}
    with conectar() as con:
        con.execute(
            "INSERT INTO clientes_pessoas (doc_cliente, cpf, nome, papel) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (doc_cliente, cpf) DO UPDATE SET nome=EXCLUDED.nome,"
            " papel=EXCLUDED.papel, ativo=true",
            (doc, cpf_d, nome.strip(), papel))
        con.commit()
    return {"ok": True, "cpf": cpf_d}
