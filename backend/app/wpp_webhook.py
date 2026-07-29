"""Webhook do WhatsApp Cloud API — a única porta de ENTRADA da Meta.

Responde duas perguntas que hoje não têm resposta nenhuma: **quem escreveu para
o número** e **se a janela de 24h está aberta**. No Cloud API a entrada só chega
por push; não existe rota para consultar histórico, então o que não for gravado
aqui se perde para sempre.

## Por que esta rota é pública (e por que isso é aceitável)

Os servidores da Meta precisam alcançá-la, então ela não pode ficar atrás da
sessão do console — é a quarta exceção do `PUBLICO` em `main.py`, e a única
aberta a POST. A troca é que ela **não confia em ninguém**:

- todo POST é autenticado por `X-Hub-Signature-256` = HMAC-SHA256 do corpo CRU
  com o App Secret. Quem não tem o segredo não forja chamada válida;
- comparação em tempo constante (`compare_digest`);
- **fail-closed**: sem `TUIU_WPP_APP_SECRET` configurado a rota RECUSA tudo, em
  vez de aceitar sem verificar. Na dúvida, fechado — mesma regra do `app.config`;
- o corpo é lido como bytes e verificado ANTES de virar JSON: assinar o texto
  reserializado validaria uma coisa e gravaria outra.

## Minimização

O texto da mensagem **não é lido nem gravado** — a tabela `wpp_entrada` nem tem
coluna para ele (ver `db/0026`). O que se guarda é remetente, id, status e
horário. Isso basta para as duas perguntas e esvazia o dano de um vazamento.

Config:
    TUIU_WPP_APP_SECRET     App Secret do app na Meta (Configurações > Básico)
    TUIU_WPP_VERIFY_TOKEN   string que nós escolhemos, conferida no handshake

Uso: as rotas vivem em `main.py` (`/api/wpp/webhook`).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from app.db import conectar

JANELA_HORAS = 24        # janela de atendimento da Meta: 24h desde a última entrada
PREFIXO_ASSINATURA = "sha256="


def _cfg(nome: str) -> str:
    return (os.environ.get(nome) or "").strip()


def configurado() -> bool:
    return bool(_cfg("TUIU_WPP_APP_SECRET"))


def token_verificacao() -> str:
    return _cfg("TUIU_WPP_VERIFY_TOKEN")


def assinatura_confere(corpo: bytes, cabecalho: str | None) -> bool:
    """HMAC-SHA256 do corpo cru com o App Secret, em tempo constante.

    Sem segredo configurado devolve False (fail-closed): rota que aceita porque
    "ainda não configuramos" é rota aberta ao mundo.
    """
    segredo = _cfg("TUIU_WPP_APP_SECRET")
    if not segredo or not cabecalho or not cabecalho.startswith(PREFIXO_ASSINATURA):
        return False
    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho[len(PREFIXO_ASSINATURA):].strip())


def _carimbo(bruto) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(bruto), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def extrair(payload: dict) -> list[dict]:
    """Achata o envelope da Meta nos metadados que guardamos.

    O formato é `entry[].changes[].value.{messages,statuses}[]`. O texto da
    mensagem existe em `messages[].text.body` e é DELIBERADAMENTE ignorado.
    """
    from app.wpp_cloud import chave_numero

    linhas: list[dict] = []
    for entrada in payload.get("entry") or []:
        for mudanca in entrada.get("changes") or []:
            valor = mudanca.get("value") or {}
            for msg in valor.get("messages") or []:
                linhas.append({
                    "tipo": "mensagem", "numero": chave_numero(msg.get("from")),
                    "wamid": msg.get("id"), "status": None, "erro": None,
                    "carimbo": _carimbo(msg.get("timestamp")),
                })
            for st in valor.get("statuses") or []:
                erros = st.get("errors") or []
                linhas.append({
                    "tipo": "status", "numero": chave_numero(st.get("recipient_id")),
                    "wamid": st.get("id"), "status": st.get("status"),
                    "erro": (erros[0].get("title") if erros else None),
                    "carimbo": _carimbo(st.get("timestamp")),
                })
    return [linha for linha in linhas if linha["numero"]]


def registrar(payload: dict) -> dict:
    """Grava o que chegou. A Meta reentrega quando não recebe 200, então o
    índice único absorve a repetição — dupla contagem inflaria a janela."""
    linhas = extrair(payload)
    if not linhas:
        return {"gravados": 0, "repetidos": 0}
    gravados = 0
    with conectar() as con:
        for linha in linhas:
            cur = con.execute(
                "INSERT INTO wpp_entrada (tipo, numero, wamid, status, erro, carimbo)"
                " VALUES (%(tipo)s,%(numero)s,%(wamid)s,%(status)s,%(erro)s,%(carimbo)s)"
                " ON CONFLICT DO NOTHING RETURNING id", linha)
            gravados += cur.fetchone() is not None
        con.commit()
    return {"gravados": gravados, "repetidos": len(linhas) - gravados}


def janela_aberta(numero: str) -> bool:
    """Se a pessoa escreveu nas últimas 24h, texto livre entrega; fora disso, só
    template aprovado. Antes desta tabela isso era adivinhação — o envio falhava
    e o erro da Meta era a primeira notícia."""
    from app import wpp_cloud
    # chave_numero, não normalizar_numero: o que está gravado veio da Meta, sem
    # o nono dígito. Comparar com a forma de ENVIO nunca casaria.
    alvo = wpp_cloud.chave_numero(wpp_cloud.normalizar_numero(numero))
    if not alvo:
        return False
    try:
        with conectar() as con:
            # make_interval, NÃO `interval '%s hours'`: dentro de literal o
            # placeholder não é substituído, o Postgres lê o lixo como 1 hora e a
            # janela encolhe de 24h para 1h — errando calado, que é o pior modo.
            r = con.execute(
                "SELECT 1 FROM wpp_entrada WHERE tipo='mensagem' AND numero=%s"
                " AND recebido_em > now() - make_interval(hours => %s) LIMIT 1",
                (alvo, JANELA_HORAS)).fetchone()
        return r is not None
    except Exception:  # noqa: BLE001 — tabela ainda não migrada: não afirma nada
        return False


WAMID = __import__("re").compile(r"wamid\.[A-Za-z0-9+/=_-]+")


def recibos(detalhes: list[str | None]) -> dict[str, dict]:
    """wamid -> último recibo da Meta, para os wamids citados em `entregas.detalhe`.

    `enviado` só diz que a Meta ACEITOU a mensagem; entregue e lido só se sabe
    pelo webhook. Sem isto o console mostrava "enviado" para sempre, inclusive
    quando o aparelho do destinatário nunca recebeu.

    O wamid é extraído do texto porque é onde ele está: o `detalhe` guarda o
    retorno cru do provedor, e no fan-out da equipe são vários numa linha só.
    """
    ids = {m for d in detalhes for m in WAMID.findall(d or "")}
    if not ids:
        return {}
    try:
        with conectar() as con:
            linhas = con.execute(
                "SELECT DISTINCT ON (wamid) wamid, status, erro, recebido_em FROM wpp_entrada"
                " WHERE tipo='status' AND wamid = ANY(%s)"
                " ORDER BY wamid, recebido_em DESC", (list(ids),)).fetchall()
    except Exception:  # noqa: BLE001 — recibo é enfeite, não pode derrubar a tela
        return {}
    return {w: {"status": s, "erro": e, "em": r.isoformat()} for w, s, e, r in linhas}


def falhas_recentes(horas: int = 48, silencioso: bool = True) -> list[dict]:
    """Entregas que a Meta ACEITOU e depois recusou.

    `enviar` devolver um wamid só prova que a API aceitou — a recusa vem
    depois, pelo webhook. Foi assim que três dias de produção passaram com a
    cadeia registrando "enviado" e ninguém recebendo nada: a conta estava com
    "Business eligibility payment issue" e o erro só existia aqui.

    A ironia é que o canal que avisaria é o mesmo que está quebrado — por isso
    isto também vai para o log da cadeia e para a tela de notificações.

    `silencioso=True` (tela) engole erro de banco: recibo é diagnóstico, não pode
    derrubar a página. A CADEIA passa False — ali lista vazia significaria "nada
    falhou", que é exatamente a mentira que este módulo existe para não contar.
    """
    try:
        with conectar() as con:
            linhas = con.execute(
                "SELECT numero, status, erro, recebido_em FROM wpp_entrada"
                " WHERE tipo='status' AND status='failed'"
                "   AND recebido_em > now() - make_interval(hours => %s)"
                " ORDER BY recebido_em DESC", (horas,)).fetchall()
    except Exception:  # noqa: BLE001
        if not silencioso:
            raise
        return []
    return [{"numero": n, "status": s, "erro": e, "em": q.isoformat()} for n, s, e, q in linhas]


def quem_escreveu(horas: int = 168) -> list[dict]:
    """Quem mandou mensagem para o número, e quando. Sem conteúdo — não existe."""
    limite = datetime.now(timezone.utc) - timedelta(hours=horas)
    with conectar() as con:
        linhas = con.execute(
            "SELECT numero, count(*), max(recebido_em) FROM wpp_entrada"
            " WHERE tipo='mensagem' AND recebido_em > %s"
            " GROUP BY numero ORDER BY max(recebido_em) DESC", (limite,)).fetchall()
    return [{"numero": n, "mensagens": q, "ultima": u.isoformat(),
             "janela_aberta": (datetime.now(timezone.utc) - u) < timedelta(hours=JANELA_HORAS)}
            for n, q, u in linhas]
