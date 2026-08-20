"""Tuiú — backend F0 (walking skeleton).

Serve a Carteira dos entes recortados (data/recortes) + a tela v0 estática.
Rodar da raiz do repo:

    py -3 -m uvicorn app.main:app --app-dir backend --port 8600
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
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
#
# `/api/wpp/webhook` é a ÚNICA rota pública que aceita POST. Está aqui porque os
# servidores da Meta precisam alcançá-la e não fazem login — não é descuido. Ela
# não confia em ninguém: exige HMAC-SHA256 do corpo cru com o App Secret e
# RECUSA tudo enquanto o segredo não estiver configurado (ver app.wpp_webhook).
PUBLICO = {"/login.html", "/api/login", "/api/sessao", "/api/wpp/webhook"}

# Chrome de UI compartilhado (CSS/JS/fontes) NÃO tem dado sensível — o dado vive
# atrás de /api. Servem sem sessão para qualquer papel; senão cliente/anônimo
# tomam 303/403 e o tema/nav não carregam. As PÁGINAS .html seguem fechadas.
ASSETS_PUBLICOS = {"/nav.js", "/tema.js", "/br.js", "/tuiu-cartorio.css", "/tuiu-fontes.css"}

# Permissões do papel `cliente`: (MÉTODO, prefixo). O método faz parte da
# permissão — sem ele, "pode ver /api/cliente/" virava "pode escrever em
# /api/cliente/{doc}/diario", que é o registro INTERNO de atendimento, e em
# /api/cliente/{doc}/pessoa. Foi assim na primeira versão: um cliente gravou
# no nosso diário e recebeu 200.
#
# Lista curta de propósito: rota nova nasce FECHADA para cliente (D3 do gate).
# Cockpit e fila ficam de fora — mostram a carteira inteira.
PERMISSOES_CLIENTE = (
    ("GET", "/api/sessao"),
    ("POST", "/api/logout"),
    ("POST", "/api/senha"),         # trocar a própria senha
    ("POST", "/api/perfil/login"),  # trocar o próprio login
    ("GET", "/api/cliente/"),      # só leitura da própria ficha
    ("GET", "/api/relatorio/"),
    ("GET", "/api/prestacao/"),
    ("GET", "/api/minuta/"),       # minuta de ação da própria carteira
    ("GET", "/api/guia"),          # o guia é conhecimento público (manuais oficiais)
    ("GET", "/guia.html"),
    ("GET", "/instrucoes.html"),   # pipeline estático — mesmo conhecimento público
    ("GET", "/cliente.html"),
    ("GET", "/login.html"),
)


def _cliente_pode(metodo: str, caminho: str) -> bool:
    return any(metodo == m and caminho.startswith(p) for m, p in PERMISSOES_CLIENTE)

# Rotas cujo primeiro segmento após o prefixo é o CNPJ do cliente.
PREFIXOS_COM_DOC = ("/api/cliente/", "/api/relatorio/", "/api/prestacao/",
                    "/api/relatorio-gestao-pix/", "/api/dossie/", "/api/entes/",
                    "/api/minuta/")


def _doc_do_caminho(caminho: str) -> str | None:
    for p in PREFIXOS_COM_DOC:
        if caminho.startswith(p):
            return caminho[len(p):].split("/")[0] or None
    return None


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
    if caminho in ASSETS_PUBLICOS or caminho.startswith("/fonts/"):
        return await call_next(request)
    usuario = auth.sessao_valida(request.cookies.get(auth.COOKIE))
    if usuario is None:
        if caminho.startswith("/api/"):
            return JSONResponse({"erro": "nao autenticado"}, status_code=401)
        return RedirectResponse("/login.html", status_code=303)

    if usuario.get("papel") == "cliente":
        if caminho == "/":
            return RedirectResponse(f"/cliente.html?doc={usuario['doc_cliente']}", status_code=303)
        if not _cliente_pode(request.method, caminho):
            return JSONResponse({"erro": "fora do seu acesso"}, status_code=403)
        doc = _doc_do_caminho(caminho)
        if doc and not auth.pode_ver(usuario, doc):
            # 403 e não 404: o CNPJ existe ou não, não é assunto de quem perguntou
            return JSONResponse({"erro": "fora do seu acesso"}, status_code=403)

    # Papel LEITOR: só leitura. Toda escrita é barrada, exceto a autogestão
    # mínima (sair, trocar a própria senha/login) — senão nem logout ele faz.
    if usuario.get("papel") == "leitor" and request.method not in ("GET", "HEAD", "OPTIONS") \
            and caminho not in ("/api/logout", "/api/senha", "/api/perfil/login"):
        return JSONResponse({"erro": "somente leitura"}, status_code=403)

    # Notificações são de OPERADOR (decisão do dono, 27/07). A tela mostra os
    # NÚMEROS de celular de quem opera e o estado dos canais: é superfície de
    # operação, não de leitura. `cliente` já não alcança (não está em
    # PERMISSOES_CLIENTE); esta trava fecha para `leitor`, que hoje lê tudo.
    if (caminho.startswith("/api/notificacoes") or caminho == "/notificacoes.html") \
            and usuario.get("papel") != "operador":
        if caminho.startswith("/api/"):
            return JSONResponse({"erro": "so operador"}, status_code=403)
        return RedirectResponse("/", status_code=303)

    # Configurar a plataforma (situações, ações) é de ADMIN — Pedro e Danilo.
    # Operador comum opera; admin calibra o motor. Fecha para todo o resto.
    if (caminho.startswith("/api/config") or caminho == "/config.html") \
            and not auth.e_admin(usuario):
        if caminho.startswith("/api/"):
            return JSONResponse({"erro": "so administrador"}, status_code=403)
        return RedirectResponse("/", status_code=303)

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
        # `Secure` é o PADRÃO, e desligar exige opt-in — mesma regra do
        # TUIU_TLS_INSECURE. Antes era o contrário: só marcava Secure se
        # TUIU_COOKIE_SECURE=1, variável que NUNCA existiu no host. O console
        # está publicado em https com dado de 50 organizações reais, e o cookie
        # de sessão saía sem a marca — bastava uma requisição http para ele
        # viajar em claro. Fail-open é o oposto do resto desta base.
        secure=os.environ.get("TUIU_COOKIE_INSEGURO") != "1",
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


@app.get("/api/responsaveis")
def api_responsaveis():
    """Para quem a mesa pode atribuir. Operador-only, como o resto da mesa."""
    from app.fila import responsaveis
    return {"responsaveis": responsaveis()}


@app.post("/api/fila/atribuir")
def fila_atribuir(payload: dict, request: Request):
    """Diz de quem é o item. `responsavel: null` devolve para a mesa.

    Quem ATRIBUIU sai da sessão, nunca do corpo: é campo de auditoria, e aceitar
    do cliente deixaria qualquer um assinar a atribuição com o nome de outro.
    O `responsavel` vem do corpo porque distribuir para terceiro é o caso normal.
    """
    from app.fila import atribuir
    quem = (getattr(request.state, "usuario", None) or {}).get("login")
    return atribuir(payload.get("chave", ""), payload.get("responsavel"), quem)


@app.get("/api/mesa")
def mesa(cliente: str | None = None):
    """Mesa de trabalho: backlog de prestação de contas priorizado por faixa
    (planilha "Prioridade" do Danilo). Operador-only — é a carteira inteira."""
    try:
        from app.mesa import montar
        return {"disponivel": True, **montar(cliente)}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "itens": []}


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


def _pagina_minuta(titulo: str, texto: str) -> str:
    import html
    t, esc = html.escape(titulo), html.escape(texto)
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{t}</title><style>"
        "body{background:#0b1017;color:#dbe6f4;font:14px/1.5 system-ui,Segoe UI,sans-serif;"
        "padding:24px;max-width:820px;margin:0 auto}h1{font-size:18px;margin:0 0 4px}"
        ".sub{color:#8ba3bf;font-size:12.5px;margin-bottom:14px}"
        "textarea{width:100%;height:60vh;background:#0d141d;color:#dbe6f4;border:1px solid #1e2a3a;"
        "border-radius:10px;padding:14px;font:13px/1.6 ui-monospace,Consolas,monospace;resize:vertical}"
        "button{background:#12324f;color:#dbe6f4;border:1px solid #4da3ff;border-radius:8px;"
        "padding:8px 16px;font-size:13px;cursor:pointer;margin-top:10px}"
        ".aviso{color:#e8b93c;font-size:12px;margin-top:10px}</style></head><body>"
        f"<h1>{t}</h1><div class=\"sub\">Rascunho gerado pelo Tuiú a partir dos dados oficiais. "
        "<b>Revise, complete a assinatura e envie você mesmo.</b></div>"
        f"<textarea id=\"t\" readonly>{esc}</textarea>"
        '<div><button onclick="c()">copiar texto</button></div>'
        '<div class="aviso">⚠️ Minuta — confira nomes, datas e o objeto antes de protocolar.</div>'
        "<script>function c(){var t=document.getElementById('t');t.select();"
        "navigator.clipboard&&navigator.clipboard.writeText(t.value);"
        "var b=document.querySelector('button');b.textContent='copiado \\u2713';"
        "setTimeout(function(){b.textContent='copiar texto'},1500);}</script></body></html>")


@app.get("/api/minuta/{doc}")
def minuta(doc: str, tipo: str = "cobranca-art97", proposta: str = "", formato: str = "html"):
    """Camada de ação: peça pronta (ofício de cobrança art.97, resposta a
    diligência) a partir dos marcos que o motor já produz. Operador e o próprio
    cliente (middleware confere o dono do CNPJ)."""
    from fastapi.responses import HTMLResponse, PlainTextResponse

    from app.minutas import GERADORES
    gerar = GERADORES.get(tipo)
    if gerar is None:
        raise HTTPException(404, "tipo de minuta desconhecido")
    # a cobrança do legado é do CLIENTE (agregado), não de um instrumento
    if not proposta and tipo != "cobranca-analise":
        raise HTTPException(400, "informe a proposta")
    d = gerar(doc, proposta)
    if not d.get("disponivel"):
        raise HTTPException(404, d.get("erro", "minuta indisponível"))
    if formato == "md":
        return PlainTextResponse(d["markdown"], media_type="text/markdown; charset=utf-8")
    return HTMLResponse(_pagina_minuta(d["titulo"], d["markdown"]))


@app.get("/api/cliente/{doc}")
def cliente_ficha(doc: str):
    try:
        from app.cliente_ficha import montar
        return {"disponivel": True, **montar(doc)}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc)}


@app.get("/api/cliente/{doc}/trilha")
def cliente_trilha(doc: str):
    try:
        from app.cliente_ficha import trilha
        return {"disponivel": True, **trilha(doc)}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "itens": []}


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


@app.get("/api/dossie/{cnpj}/checklist")
def dossie_checklist(cnpj: str, instrumento: str):
    """Checklist de dossiê da PC de um convênio (o "% dossiê" da planilha)."""
    from app.dossie import checklist_estado
    return checklist_estado(cnpj, instrumento)


@app.post("/api/dossie/marcar")
def dossie_marcar(corpo: dict, request: Request):
    from app.dossie import marcar_item
    r = marcar_item(corpo.get("cnpj", ""), corpo.get("instrumento", ""),
                    corpo.get("item", ""), bool(corpo.get("feito")),
                    request.state.usuario["login"])
    if not r.get("ok"):
        raise HTTPException(400, r.get("erro", "não marcou"))
    return r


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
            linhas = [dict(zip(cols, r)) for r in con.execute(sql, args)]

        # `enviado` só diz que a Meta aceitou. Entregue/lido vem do webhook.
        from app.wpp_webhook import WAMID, recibos
        mapa = recibos([l["detalhe"] for l in linhas])
        for l in linhas:
            recibo = [mapa[m] for m in WAMID.findall(l["detalhe"] or "") if m in mapa]
            l["recibo"] = max(recibo, key=lambda r: r["em"]) if recibo else None
        return {"disponivel": True, "entregas": linhas}
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


@app.get("/api/wpp/webhook")
def wpp_webhook_verificar(request: Request):
    """Handshake de cadastro da Meta: ela chama com um token que nós escolhemos
    e espera o `hub.challenge` de volta, em texto puro."""
    from app import wpp_webhook

    q = request.query_params
    esperado = wpp_webhook.token_verificacao()
    if not esperado or q.get("hub.verify_token") != esperado:
        # 403 sem detalhe: quem errou o token não merece saber se ele existe
        raise HTTPException(403, "verificacao recusada")
    return PlainTextResponse(q.get("hub.challenge") or "")


@app.post("/api/wpp/webhook")
async def wpp_webhook_receber(request: Request):
    """Entrada da Meta. Corpo lido como BYTES e autenticado ANTES de virar JSON —
    assinar o texto reserializado validaria uma coisa e gravaria outra.

    Sempre 200 no caminho feliz: erro faz a Meta reentregar em loop, e uma falha
    nossa de gravação não é problema dela.
    """
    from app import wpp_webhook

    corpo = await request.body()
    if not wpp_webhook.assinatura_confere(corpo, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "assinatura invalida")
    try:
        return {"ok": True, **wpp_webhook.registrar(json.loads(corpo or b"{}"))}
    except Exception as exc:  # noqa: BLE001
        print(f"[wpp_webhook] falha ao gravar: {exc}", file=sys.stderr)
        return {"ok": False}


@app.get("/api/wpp/entrada")
def wpp_entrada(horas: int = 168):
    """Quem escreveu para o número da API, e se a janela de 24h está aberta.
    Sem conteúdo de mensagem — não é guardado (ver db/0026)."""
    from app import wpp_webhook

    try:
        return {"disponivel": True, "contatos": wpp_webhook.quem_escreveu(horas),
                "webhook_configurado": wpp_webhook.configurado()}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "contatos": []}


@app.get("/api/normas")
def normas(pendentes: bool = False):
    try:
        with conectar() as con:
            sql = ("SELECT id, publicado_em, secao, identifica, orgao, ementa, termos,"
                   " tratada, tratada_em, tratada_por, nota FROM normas_vistas")
            if pendentes:
                sql += " WHERE NOT tratada"
            sql += " ORDER BY publicado_em DESC, id DESC LIMIT 200"
            cols = ["id", "publicado_em", "secao", "identifica", "orgao", "ementa", "termos",
                    "tratada", "tratada_em", "tratada_por", "nota"]
            linhas = [dict(zip(cols, r)) for r in con.execute(sql)]
            n = con.execute("SELECT count(*) FROM normas_vistas WHERE NOT tratada").fetchone()[0]
            m = con.execute("SELECT ate, atualizado_em FROM vigia_marcador"
                            " WHERE fonte='DOU'").fetchone()
        return {"disponivel": True, "normas": linhas, "pendentes": n,
                "varrido_ate": m[0].isoformat() if m else None,
                "ultima_varredura": m[1].isoformat() if m else None}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "normas": []}


@app.post("/api/normas/{norma_id}/tratar")
def norma_tratar(norma_id: int, corpo: dict, request: Request):
    """Marca que ALGUÉM avaliou o impacto em `regras_normativas`. O sistema não
    decide isso sozinho: versionar regra é ato consciente."""
    with conectar() as con:
        cur = con.execute(
            "UPDATE normas_vistas SET tratada=%s, tratada_em=now(), tratada_por=%s, nota=%s"
            " WHERE id=%s RETURNING id",
            (bool(corpo.get("tratada", True)), request.state.usuario["login"],
             (corpo.get("nota") or "").strip()[:500] or None, norma_id))
        achou = cur.fetchone()
        con.commit()
    if not achou:
        raise HTTPException(404, "norma nao encontrada")
    return {"ok": True}


# ------------------------------------------------------------------ contas
# Só operador chega aqui: o papel `cliente` não tem estes caminhos em
# PERMISSOES_CLIENTE, e o padrão do middleware é negar.

@app.get("/api/usuarios")
def usuarios_listar():
    return {"usuarios": auth.listar_usuarios()}


@app.post("/api/usuarios")
def usuarios_criar(corpo: dict, request: Request):
    """Operador cria uma conta escolhendo login, nome, PAPEL e SENHA."""
    u = request.state.usuario
    if u.get("papel") != "operador":
        raise HTTPException(403, "fora do seu acesso")
    ok, msg = auth.criar_conta(
        u["login"], corpo.get("minha_senha", ""),
        corpo.get("login", ""), corpo.get("nome", ""),
        corpo.get("papel", "operador"), corpo.get("senha", ""), corpo.get("doc_cliente"))
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "mensagem": msg}


@app.post("/api/usuarios/{alvo}/editar")
def usuarios_editar(alvo: str, corpo: dict, request: Request):
    """Operador edita nome, papel e/ou senha de uma conta."""
    u = request.state.usuario
    if u.get("papel") != "operador":
        raise HTTPException(403, "fora do seu acesso")
    ok, msg = auth.editar_usuario(
        u["login"], corpo.get("minha_senha", ""), alvo,
        nome=corpo.get("nome"), papel=corpo.get("papel"),
        senha=corpo.get("senha"), doc_cliente=corpo.get("doc_cliente"))
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "mensagem": msg}


@app.post("/api/usuarios/{alvo}/desativar")
def usuarios_desativar(alvo: str, corpo: dict, request: Request):
    u = request.state.usuario
    if u.get("papel") != "operador":
        raise HTTPException(403, "fora do seu acesso")
    ok, msg = auth.desativar(u["login"], alvo, corpo.get("minha_senha", ""))
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "mensagem": msg}


@app.post("/api/perfil/login")
def perfil_login(corpo: dict, request: Request, response: Response):
    """Troca o próprio login. A sessão sobrevive (o FK cascateia)."""
    u = request.state.usuario
    ok, msg = auth.trocar_login(u["login"], corpo.get("novo", ""), corpo.get("senha", ""))
    if not ok:
        raise HTTPException(400, msg)
    return {"ok": True, "login": msg}


@app.get("/api/base-rates")
def base_rates(request: Request):
    """Inteligência de desfecho por órgão × regime. Operador-only (é a carteira
    inteira do país, não um cliente)."""
    if request.state.usuario.get("papel") != "operador":
        raise HTTPException(403, "fora do seu acesso")

    def _limpar(rows, cols):
        return [dict(zip(cols, [str(x) if hasattr(x, "isoformat") else x for x in r])) for r in rows]

    try:
        with conectar() as con:
            cols = ["orgao", "regime", "n", "pct_sucesso", "pct_ressalva", "pct_morte",
                    "pct_em_curso", "prestacoes_paradas", "mediana_dias_parada", "preditivo",
                    "computado_em"]
            rows = con.execute(
                "SELECT " + ", ".join(cols) + " FROM base_rates_orgao"
                " ORDER BY preditivo DESC, pct_morte DESC NULLS LAST").fetchall()
            # funil (upstream): a tabela pode ainda não existir num deploy antigo
            fcols = ["orgao", "regime", "n_total", "n_resolvidas", "pct_aprovada",
                     "pct_reprovada", "pct_em_curso", "preditivo", "computado_em"]
            try:
                frows = con.execute(
                    "SELECT " + ", ".join(fcols) + " FROM funil_orgao"
                    " ORDER BY preditivo DESC, pct_reprovada DESC NULLS LAST").fetchall()
                funil = _limpar(frows, fcols)
            except Exception:  # noqa: BLE001
                con.rollback()
                funil = []
            # latência de análise (art.97): idem, tolera tabela ausente
            lcols = ["orgao", "regime", "n", "mediana_dias", "p90_dias",
                     "pct_acima_limite", "limite_legal", "preditivo", "computado_em"]
            try:
                lrows = con.execute(
                    "SELECT " + ", ".join(lcols) + " FROM latencia_orgao"
                    " ORDER BY preditivo DESC, mediana_dias DESC NULLS LAST").fetchall()
                latencia = _limpar(lrows, lcols)
            except Exception:  # noqa: BLE001
                con.rollback()
                latencia = []
            # funil por ação orçamentária (drill-down do órgão): idem
            acols = ["orgao", "acao", "nome", "regime", "n_total", "n_resolvidas",
                     "pct_aprovada", "pct_reprovada", "preditivo"]
            try:
                arows = con.execute(
                    "SELECT " + ", ".join(acols) + " FROM funil_acao"
                    " ORDER BY preditivo DESC, orgao, pct_aprovada").fetchall()
                funil_acao = _limpar(arows, acols)
            except Exception:  # noqa: BLE001
                con.rollback()
                funil_acao = []
            return {"disponivel": True, "base_rates": _limpar(rows, cols),
                    "funil": funil, "latencia": latencia, "funil_acao": funil_acao}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "base_rates": [],
                "funil": [], "latencia": [], "funil_acao": []}


@app.get("/api/guia/etapas")
def guia_etapas():
    """Esqueleto do pipeline (etapas do acervo oficial) para navegar o guia."""
    try:
        from app.guia import etapas
        return {"disponivel": True, "etapas": etapas()}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "etapas": []}


def _gravar_historico(request: Request, q: str, r: dict) -> None:
    """Grava a pergunta+resposta. Nunca derruba a resposta se o insert falhar."""
    import json as _json
    u = getattr(request.state, "usuario", None) or {}
    fontes = [{c: f.get(c) for c in ("id", "fonte", "documento", "etapa", "pagina_ini", "arquivo", "url")}
              for f in (r.get("fontes") or [])]
    try:
        with conectar() as con:
            con.execute(
                "INSERT INTO guia_historico (usuario, papel, doc_cliente, pergunta, resposta,"
                " modelo, fontes, tokens_entrada, tokens_cacheados, tokens_saida, erro)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (u.get("login"), u.get("papel"), u.get("doc_cliente"), q, r.get("resposta"),
                 r.get("modelo"), _json.dumps(fontes, ensure_ascii=False), r.get("tokens_entrada"),
                 r.get("tokens_cacheados"), r.get("tokens_saida"), r.get("erro")))
            con.commit()
    except Exception:  # noqa: BLE001 — histórico é registro, não pode quebrar o chat
        pass


@app.get("/api/guia/perguntar")
def guia_perguntar(request: Request, q: str = "", k: int = 6):
    """Chat do guia: responde ancorado no acervo, cita a fonte, e GRAVA no histórico."""
    try:
        from app.guia import perguntar
        r = {"disponivel": True, **perguntar(q, k=max(3, min(k, 10)))}
    except Exception as exc:  # noqa: BLE001
        r = {"disponivel": False, "erro": str(exc), "resposta": None, "fontes": []}
    if (q or "").strip():
        _gravar_historico(request, q.strip(), r)
    return r


@app.get("/api/guia/historico")
def guia_historico(request: Request, limite: int = 60):
    """Histórico do chat. Operador vê tudo; cliente vê só o dele (RBAC)."""
    u = request.state.usuario
    limite = max(1, min(limite, 200))
    cols = ["id", "quando", "usuario", "papel", "doc_cliente", "pergunta", "resposta",
            "modelo", "fontes", "tokens_entrada", "tokens_cacheados", "tokens_saida", "erro"]
    try:
        with conectar() as con:
            base = "SELECT " + ", ".join(cols) + " FROM guia_historico"
            if u.get("papel") == "operador":
                rows = con.execute(base + " ORDER BY quando DESC LIMIT %s", (limite,)).fetchall()
            else:
                rows = con.execute(base + " WHERE usuario=%s ORDER BY quando DESC LIMIT %s",
                                   (u.get("login"), limite)).fetchall()
        itens = [dict(zip(cols, [x.isoformat() if hasattr(x, "isoformat") else x for x in r]))
                 for r in rows]
        return {"disponivel": True, "itens": itens, "sou_operador": u.get("papel") == "operador"}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "itens": []}


@app.get("/api/guia/metricas")
def guia_metricas(request: Request):
    """Telinha do operador: uso do guia — volume, o que mais perguntam, e o custo
    (tokens → US$, com o desconto do cache). Operador-only."""
    if request.state.usuario.get("papel") != "operador":
        raise HTTPException(403, "métricas são do operador")
    # V4-Flash (DeepInfra): cents/token; cached input = 0,2×
    CI, CO, CACHE = 9e-6, 1.8e-5, 0.2
    try:
        with conectar() as con:
            tot, sem, hoje = con.execute(
                "SELECT count(*), count(*) FILTER (WHERE quando > now()-interval '7 days'),"
                "       count(*) FILTER (WHERE quando >= date_trunc('day', now()))"
                " FROM guia_historico").fetchone()
            ent, cac, sai, npg = con.execute(
                "SELECT coalesce(sum(tokens_entrada),0), coalesce(sum(tokens_cacheados),0),"
                "       coalesce(sum(tokens_saida),0), count(*) FROM guia_historico"
                " WHERE quando >= date_trunc('month', now())").fetchone()
            custo = ((ent - cac) * CI + cac * CI * CACHE + sai * CO) / 100.0
            top = [{"pergunta": p, "n": n} for p, n in con.execute(
                "SELECT min(pergunta), count(*) FROM guia_historico"
                " GROUP BY tuiu_norm(pergunta) ORDER BY 2 DESC, 1 LIMIT 12")]
            por_user = [{"usuario": u or "—", "papel": pl, "n": n} for u, pl, n in con.execute(
                "SELECT usuario, min(papel), count(*) FROM guia_historico"
                " GROUP BY usuario ORDER BY 3 DESC LIMIT 10")]
            sem_resp = con.execute(
                "SELECT count(*) FROM guia_historico WHERE resposta IS NULL").fetchone()[0]
        return {"disponivel": True, "total": tot, "semana": sem, "hoje": hoje,
                "mes": {"perguntas": npg, "custo_usd": round(custo, 4),
                        "tokens_entrada": int(ent), "tokens_cacheados": int(cac),
                        "tokens_saida": int(sai),
                        "cache_pct": round(100.0 * cac / ent) if ent else 0},
                "top": top, "por_usuario": por_user, "sem_resposta": sem_resp}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc)}


@app.get("/api/guia/conteudo")
def guia_conteudo():
    """O guia próprio (pipeline completo), para navegar por etapa."""
    import json as _json
    arq = Path(__file__).resolve().parents[2] / "ingest" / "manuais" / "guia_pipeline.json"
    try:
        return {"disponivel": True, **_json.loads(arq.read_text(encoding="utf-8"))}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "secoes": []}


@app.get("/api/guia/pdf/{trecho_id}")
def guia_pdf(trecho_id: int):
    """Serve o PDF oficial do acervo — a consulta na íntegra. Só de dentro da
    raiz do acervo: caminho vindo do banco não entra em FileResponse sem trava."""
    from fastapi.responses import FileResponse
    raiz = Path("/mnt/dados-gov/tuiu-manuais").resolve()
    with conectar() as con:
        r = con.execute("SELECT arquivo FROM guia_trechos WHERE id=%s", (trecho_id,)).fetchone()
    if not r or not r[0]:
        raise HTTPException(404, "este trecho não tem PDF (é do guia próprio)")
    p = Path(r[0]).resolve()
    if raiz not in p.parents or not p.exists():
        raise HTTPException(404, "arquivo fora do acervo")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@app.get("/api/guia/buscar")
def guia_buscar(q: str = "", k: int = 8, etapa: str = "", papel: str = ""):
    """Busca híbrida no acervo: semântica (embedding local) + FTS português."""
    try:
        from app.guia import buscar
        return {"disponivel": True,
                **buscar(q, k=max(1, min(k, 20)), etapa=etapa or None, papel=papel or None)}
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": str(exc), "resultados": []}


@app.get("/api/busca")
def busca(request: Request, q: str = ""):
    """Busca global do operador: acha cliente (nome/apelido/CNPJ), instrumento
    (proposta/convênio que aparece num marco) e órgão (inteligência). Tudo do
    tuiu-db, uma consulta por tipo, teto baixo — é o pulo pro item, não relatório."""
    if request.state.usuario.get("papel") != "operador":
        raise HTTPException(403, "busca é do operador")
    q = (q or "").strip()
    if len(q) < 2:
        return {"resultados": []}
    like = f"%{q}%"                                            # tuiu_norm normaliza os dois lados
    digitos = "".join(c for c in q if c.isdigit())
    # cláusula de CNPJ só quando há dígitos — NUL como sentinela estoura no PG
    cond = "tuiu_norm(nome) LIKE tuiu_norm(%s) OR tuiu_norm(apelido) LIKE tuiu_norm(%s)"
    params: list = [like, like]
    if len(digitos) >= 2:
        cond += " OR doc LIKE %s"
        params.append(f"%{digitos}%")
    out: list[dict] = []
    try:
        with conectar() as con:
            for doc, nome, apelido, mun, uf in con.execute(
                "SELECT doc, nome, apelido, municipio, uf FROM clientes"
                f" WHERE ativo AND ({cond}) ORDER BY nome LIMIT 8", params):
                sub = nome if (apelido and apelido != nome) else doc
                if mun:
                    sub += f" · {mun}/{uf}"
                out.append({"tipo": "cliente", "titulo": apelido or nome,
                            "sub": sub, "url": f"/cliente.html?doc={doc}"})
            for cnpj, ente, instr, tipo in con.execute(
                "SELECT DISTINCT ON (instrumento) cnpj, ente, instrumento, tipo FROM marcos"
                " WHERE instrumento IS NOT NULL AND (tuiu_norm(instrumento) LIKE tuiu_norm(%s)"
                "   OR tuiu_norm(descricao) LIKE tuiu_norm(%s)) LIMIT 6", (like, like)):
                out.append({"tipo": "instrumento", "titulo": str(instr),
                            "sub": f"{ente} · {tipo.replace('_', ' ')}",
                            "url": f"/cliente.html?doc={cnpj}"})
            for (orgao,) in con.execute(
                "SELECT DISTINCT orgao FROM base_rates_orgao WHERE tuiu_norm(orgao) LIKE tuiu_norm(%s)"
                " ORDER BY orgao LIMIT 5", (like,)):
                out.append({"tipo": "órgão", "titulo": orgao,
                            "sub": "inteligência do órgão", "url": "/inteligencia.html"})
    except Exception as exc:  # noqa: BLE001
        return {"resultados": [], "erro": str(exc)}
    return {"resultados": out}


# ------------------------------------------------------------- config (admin)
# O middleware já barra não-admin em /api/config* e /config.html; aqui só a lida.

@app.get("/api/config/situacoes")
def cfg_situacoes_listar():
    from app.config_admin import listar_situacoes
    return listar_situacoes()


@app.get("/api/config/situacoes/vocabulario")
def cfg_situacoes_vocab():
    """Situações reais no acervo e a fase que a regra atual lhes dá — as sem
    regra (fase null) são as candidatas a classificar."""
    from app.config_admin import situacoes_no_dado
    return situacoes_no_dado()


@app.post("/api/config/situacoes")
def cfg_situacao_salvar(corpo: dict, request: Request):
    from app.config_admin import salvar_situacao
    r = salvar_situacao(corpo.get("padrao", ""), corpo.get("fase", ""), corpo.get("nota"),
                        request.state.usuario["login"], corpo.get("id"),
                        bool(corpo.get("ativo", True)))
    if not r.get("ok"):
        raise HTTPException(400, r.get("erro", "não salvou"))
    return r


@app.delete("/api/config/situacoes/{rid}")
def cfg_situacao_remover(rid: int):
    from app.config_admin import remover_situacao
    return remover_situacao(rid)


@app.get("/api/config/acoes")
def cfg_acoes_listar():
    from app.config_admin import listar_acoes
    return listar_acoes()


@app.post("/api/config/acoes")
def cfg_acao_salvar(corpo: dict, request: Request):
    from app.config_admin import salvar_acao
    r = salvar_acao(corpo.get("tipo", ""), corpo.get("proximo_passo", ""),
                    corpo.get("nota"), request.state.usuario["login"])
    if not r.get("ok"):
        raise HTTPException(400, r.get("erro", "não salvou"))
    return r


@app.post("/api/config/reprocessar")
def cfg_reprocessar():
    """Aplica JÁ as regras: regera os marcos das carteiras (o que a cadeia diária
    faria às 09:30). Assim o admin vê o efeito da mudança na hora."""
    from app.motor_prazos import gerar_marcos
    try:
        return {"ok": True, **gerar_marcos()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "static", html=True))
