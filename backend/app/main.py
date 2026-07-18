"""Tuiú — backend F0 (walking skeleton).

Serve a Carteira dos entes recortados (data/recortes) + a tela v0 estática.
Rodar da raiz do repo:

    py -3 -m uvicorn app.main:app --app-dir backend --port 8600
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app.carteira import listar_entes, snapshot_mais_recente
from app.cockpit import montar as montar_cockpit
from app.db import conectar

app = FastAPI(title="Tuiú", version="0.2.0-cockpit")


@app.get("/api/cockpit")
def cockpit():
    return montar_cockpit()


@app.get("/api/saude")
def saude():
    snap = snapshot_mais_recente()
    return {"ok": True, "snapshot": snap.name if snap else None}


@app.get("/api/entes")
def entes():
    return listar_entes()


@app.get("/api/entes/{cnpj}")
def ente(cnpj: str):
    alvo = "".join(c for c in cnpj if c.isdigit())
    for e in listar_entes()["entes"]:
        if e["cnpj"] == alvo:
            return e
    raise HTTPException(404, f"ente {alvo} sem recorte — rode o ingest primeiro")


@app.get("/api/marcos")
def marcos(farol: str | None = None):
    try:
        with conectar() as con:
            sql = ("SELECT cnpj, ente, fonte, instrumento, tipo, data_limite, descricao,"
                   " base_legal, farol, snapshot FROM marcos")
            args: tuple = ()
            if farol:
                sql += " WHERE farol = %s"
                args = (farol,)
            sql += (" ORDER BY CASE farol WHEN 'acao_imediata' THEN 0 WHEN 'vencido' THEN 1"
                    " WHEN 'atencao' THEN 2 ELSE 3 END, data_limite NULLS FIRST")
            cols = ["cnpj", "ente", "fonte", "instrumento", "tipo", "data_limite",
                    "descricao", "base_legal", "farol", "snapshot"]
            return {"disponivel": True,
                    "marcos": [dict(zip(cols, r)) for r in con.execute(sql, args)]}
    except Exception as exc:  # noqa: BLE001 — banco fora = agenda indisponível, app segue
        return {"disponivel": False, "erro": str(exc), "marcos": []}


@app.get("/api/eventos")
def eventos(cnpj: str | None = None, limite: int = 200):
    try:
        with conectar() as con:
            sql = ("SELECT id, cnpj, ente, dominio, chave, rotulo, tipo, de, para,"
                   " snapshot::text, criado_em FROM eventos")
            args: tuple = ()
            if cnpj:
                sql += " WHERE cnpj = %s"
                args = ("".join(c for c in cnpj if c.isdigit()),)
            sql += " ORDER BY id DESC LIMIT %s"
            args += (limite,)
            cols = ["id", "cnpj", "ente", "dominio", "chave", "rotulo", "tipo",
                    "de", "para", "snapshot", "criado_em"]
            return {"disponivel": True, "eventos": [dict(zip(cols, r)) for r in con.execute(sql, args)]}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "eventos": []}


@app.get("/api/entregas")
def entregas(canal: str | None = None):
    try:
        with conectar() as con:
            sql = ("SELECT e.id, e.canal, e.endereco, e.mensagem, e.status, e.detalhe,"
                   " e.criado_em, e.enviado_em FROM entregas e")
            args: tuple = ()
            if canal:
                sql += " WHERE e.canal = %s"
                args = (canal,)
            sql += " ORDER BY e.id DESC LIMIT 100"
            cols = ["id", "canal", "endereco", "mensagem", "status", "detalhe",
                    "criado_em", "enviado_em"]
            return {"disponivel": True, "entregas": [dict(zip(cols, r)) for r in con.execute(sql, args)]}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "entregas": []}


@app.get("/api/alertas")
def alertas():
    try:
        with conectar() as con:
            rows = con.execute(
                "SELECT a.id, a.gatilho, a.canal, a.mensagem, a.criado_em, a.enviado_em"
                " FROM alertas a ORDER BY a.id DESC LIMIT 100").fetchall()
            cols = ["id", "gatilho", "canal", "mensagem", "criado_em", "enviado_em"]
            return {"disponivel": True, "alertas": [dict(zip(cols, r)) for r in rows]}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "alertas": []}


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "static", html=True))
