"""Tuiú — backend F0 (walking skeleton).

Serve a Carteira dos entes recortados (data/recortes) + a tela v0 estática.
Rodar da raiz do repo:

    py -3 -m uvicorn app.main:app --app-dir backend --port 8600
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import auth
from app.carteira import listar_entes, snapshot_mais_recente
from app.cockpit import montar as montar_cockpit
from app.config import estado as estado_notificacoes
from app.config import gravar as gravar_config
from app.db import conectar

app = FastAPI(title="Tuiú", version="0.3.0-console")

# Lista de exceções EXPLÍCITA e curta. Tudo o mais exige sessão — o padrão é
# fechado, então esquecer de proteger uma rota nova não abre buraco.
PUBLICO = {"/login.html", "/api/login", "/api/sessao"}


def _ip(request: Request) -> str | None:
    # atrás de proxy/túnel o IP real vem no cabeçalho; sem ele, o do socket
    encaminhado = request.headers.get("x-forwarded-for", "")
    return (encaminhado.split(",")[0].strip() or None) if encaminhado else (
        request.client.host if request.client else None)


@app.middleware("http")
async def exigir_sessao(request: Request, call_next):
    caminho = request.url.path
    if caminho in PUBLICO:
        return await call_next(request)
    usuario = auth.sessao_valida(request.cookies.get(auth.COOKIE))
    if usuario is None:
        if caminho.startswith("/api/"):
            return JSONResponse({"erro": "nao autenticado"}, status_code=401)
        return RedirectResponse("/login.html", status_code=303)
    request.state.usuario = usuario
    return await call_next(request)


@app.post("/api/login")
def login(corpo: dict, request: Request, response: Response):
    token, msg = auth.autenticar(corpo.get("login", ""), corpo.get("senha", ""),
                                 ip=_ip(request), agente=request.headers.get("user-agent"))
    if not token:
        # 401 sem distinguir causa; o motivo detalhado fica em `acessos_log`
        raise HTTPException(401, msg)
    response.set_cookie(
        auth.COOKIE, token, httponly=True, samesite="lax",
        secure=os.environ.get("TUIU_COOKIE_SECURE") == "1",
        max_age=auth.DURACAO_SESSAO_H * 3600, path="/")
    return {"ok": True, **(auth.sessao_valida(token) or {})}


@app.post("/api/logout")
def logout(request: Request, response: Response):
    auth.encerrar(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE, path="/")
    return {"ok": True}


@app.get("/api/sessao")
def sessao(request: Request):
    """Público de propósito: a tela de login precisa saber se já há sessão e se
    existe algum usuário cadastrado."""
    u = auth.sessao_valida(request.cookies.get(auth.COOKIE))
    return {"autenticado": u is not None, "usuario": u, "ha_usuario": auth.ha_usuario()}


@app.post("/api/senha")
def senha(corpo: dict, request: Request):
    u = request.state.usuario
    ok, msg = auth.trocar_senha(u["login"], corpo.get("atual", ""), corpo.get("nova", ""))
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "mensagem": msg}


@app.get("/api/cockpit")
def cockpit():
    return montar_cockpit()


@app.get("/api/fila")
def fila(abertos: bool = True, cliente: str | None = None, so_clientes: bool = True):
    try:
        from app.fila import montar
        return {"disponivel": True, **montar(apenas_abertos=abertos, cliente=cliente,
                                             apenas_clientes=so_clientes)}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "itens": []}


@app.post("/api/fila/triar")
def fila_triar(payload: dict):
    from app.fila import triar
    return triar(payload.get("chave", ""), payload.get("status", ""),
                 payload.get("nota"), payload.get("operador"))


@app.get("/api/produtividade")
def produtividade(dias: int = 30, cliente: str | None = None):
    try:
        from app.produtividade import montar
        return {"disponivel": True, **montar(dias, cliente)}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc)}


@app.get("/api/relatorio/{doc}")
def relatorio(doc: str, dias: int = 30, formato: str = "md"):
    from fastapi.responses import PlainTextResponse

    from app.relatorio_cliente import markdown, montar
    dados = montar(doc, dias)
    if formato == "json":
        return dados
    return PlainTextResponse(markdown(dados), media_type="text/markdown; charset=utf-8")


@app.get("/api/cliente/{doc}")
def cliente_ficha(doc: str):
    try:
        from app.cliente_ficha import montar
        return {"disponivel": True, **montar(doc)}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc)}


@app.post("/api/cliente/{doc}/diario")
def cliente_anotar(doc: str, payload: dict):
    from app.cliente_ficha import anotar
    return anotar(doc, payload.get("texto", ""), payload.get("tipo", "nota"),
                  payload.get("autor"), payload.get("referencia"))


@app.post("/api/cliente/{doc}/pessoa")
def cliente_pessoa(doc: str, payload: dict):
    from app.cliente_ficha import cadastrar_pessoa
    return cadastrar_pessoa(doc, payload.get("cpf", ""), payload.get("nome", ""), payload.get("papel"))


@app.get("/api/clientes")
def clientes():
    try:
        from app.clientes import listar
        return listar()
    except Exception as exc:  # noqa: BLE001
        return {"clientes": [], "erro": str(exc)}


@app.get("/api/prestacao/{cnpj}")
def prestacao(cnpj: str):
    from app.prestacao import checklist
    return checklist(cnpj)


@app.get("/api/relatorio-gestao-pix/{cnpj}")
def relatorio_pix(cnpj: str, formato: str = "json"):
    from fastapi.responses import PlainTextResponse

    from app.prestacao import markdown_relatorio, relatorio_gestao_pix
    dados = relatorio_gestao_pix(cnpj)
    if formato == "md":
        return PlainTextResponse(markdown_relatorio(dados), media_type="text/markdown; charset=utf-8")
    return dados


@app.get("/api/dossie/{cnpj}")
def dossie_listar(cnpj: str, instrumento: str | None = None):
    from app.dossie import listar
    return listar(cnpj, instrumento)


@app.get("/api/verificacao")
def verificacao():
    snap = snapshot_mais_recente()
    arq = (snap / "_verificacao.json") if snap else None
    if arq and arq.exists():
        import json as _json
        return {"disponivel": True, **_json.loads(arq.read_text(encoding="utf-8"))}
    return {"disponivel": False, "motivo": "rode ingest/transferegov_g2/verificar.py"}


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


@app.get("/api/notificacoes")
def notificacoes():
    try:
        return {"disponivel": True, **estado_notificacoes()}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc)}


@app.post("/api/notificacoes")
def notificacoes_gravar(corpo: dict, request: Request):
    """Liga/desliga um canal. Só as chaves de notificação passam (app.config)."""
    chave, valor = corpo.get("chave"), corpo.get("valor")
    if chave is None or valor is None:
        raise HTTPException(400, "informe `chave` e `valor`")
    try:
        r = gravar_config(str(chave), str(valor), quem=request.state.usuario["login"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, **r, **estado_notificacoes()}


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "static", html=True))
