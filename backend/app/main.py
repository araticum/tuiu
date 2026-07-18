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

app = FastAPI(title="Tuiú", version="0.0.1-f0")


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


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "static", html=True))
