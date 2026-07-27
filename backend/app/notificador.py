"""Despachante de notificações (F1.5) — leva eventos de andamento aos canais.

Canais (plugáveis, idempotentes por evento+canal+endereço):
  - outbox   : sempre — persiste a mensagem (status 'pendente').
  - webhook  : se houver destinatário canal='webhook' (ou TUIU_WEBHOOK_URL) —
               POST JSON do evento. É o "webhook de saída" para plugar onde quiser.
  - whatsapp : **Cloud API oficial da Meta** (`app/wpp_cloud.py`), alerta por
               TEMPLATE aprovado no número cadastrado em `destinatarios`.
               TUIU_WPP_DRYRUN=1 monta e não envia.
  - seriema  : grupo INTERNO de operação (não chega ao cliente).

**A mensagem é autossuficiente** (decisão do dono, 27/07/2026): o console é
loopback e não há URL que abra no celular, então nada de "veja na mesa" — o que
o operador precisa para decidir vai no corpo (instrumento, transição, prazo,
próximo passo e a exigência do órgão), puxado de `marcos`.

Idempotência: a entrega é RESERVADA e comitada antes do envio. A Cloud API não
tem dedup por chave (a sessão Seriema tinha), então sem a reserva uma queda no
meio do laço faria o mesmo alerta tocar de novo o telefone de alguém no dia
seguinte. O preço é que entrega em 'erro' não é retentada sozinha — reenvio é
ato deliberado, como já era.

Uso:
    py -3 backend/app/notificador.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import seriema, wpp_cloud  # noqa: E402
from app.carteira import nome_exibicao, nomes_carteira  # noqa: E402
from app.config import envio_externo_liberado  # noqa: E402
from app.db import conectar  # noqa: E402

WEBHOOK_URL = os.environ.get("TUIU_WEBHOOK_URL", "").strip()
# O console está publicado desde 20/07 — o link abre no celular e cai na tela de
# login do Tuiú. Fica em env porque a URL é a MESMA nos dois caminhos (texto e
# template): duas fontes divergiriam calado, e o erro só apareceria no celular
# de quem recebeu.
CONSOLE_URL = os.environ.get("TUIU_CONSOLE_URL", "https://tuiu.araticum.net").strip().rstrip("/")

ICONE = {"novo": "🆕", "mudanca": "🔔", "incremento": "➕"}
TIPO_LEGIVEL = {"novo": "novo instrumento", "mudanca": "mudança de andamento",
                "incremento": "novo lançamento"}


def _br(d) -> str:
    return d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d or "")


def link_cliente(cnpj: str) -> str:
    """Ficha do cliente — cadastro, carteira, prazos, andamento e trilha.

    É a `/cliente.html?doc=`, não a mesa: a mesa não lê query param, então um
    link para ela abriria o backlog inteiro da carteira, não o caso avisado.
    """
    return f"{CONSOLE_URL}/cliente.html?doc={cnpj}"


def contexto(con, cnpj: str, instrumento: str) -> dict:
    """O que o operador precisa saber junto com a mudança: prazo, de quem é a
    bola, próximo passo e a exigência do órgão.

    Prefere o marco ABERTO mais urgente, mas cai no marco `ok` quando não há
    nenhum aberto — senão a mensagem mais comum da carteira ("prestação enviada
    para análise") chegaria sem uma linha sequer de contexto, que foi o que o
    primeiro teste com dado real mostrou.

    🔴 **Marco `ok` nunca vira prazo.** Ele tem `data_limite` no passado (a data
    em que a prestação foi entregue), e anunciá-la como vencimento reencena o
    alarme falso de 19/07, quando o motor acusava atraso de quem cumpriu. Com
    `ok` sai só de quem é a bola e o próximo passo.

    Degrada para {} se `marcos`/`regras_acao` ainda não existirem — contexto é
    enriquecimento, nunca pode impedir o aviso de sair.
    """
    if not instrumento:
        return {}
    try:
        from app.fila import _acoes
        linha = con.execute(
            "SELECT tipo, data_limite, detalhes, farol FROM marcos"
            " WHERE cnpj=%s AND instrumento=%s"
            " ORDER BY (farol = 'ok'), data_limite NULLS FIRST LIMIT 1",
            (cnpj, instrumento)).fetchone()
        if not linha:
            return {}
        tipo, limite, det, farol = linha
        det = det or {}
        ultimo = det.get("ultimo_parecer")
        acoes = _acoes(con)
    except Exception:  # noqa: BLE001
        con.rollback()
        return {}

    ctx = {"bola": det.get("bola_com") or "convenente",
           "proximo_passo": acoes.get(tipo, "Analisar")}
    if limite and farol != "ok":
        dias = (limite - date.today()).days
        ctx["prazo"] = _br(limite)
        ctx["prazo_dias"] = f"vencido há {-dias}d" if dias < 0 else (
            "vence hoje" if dias == 0 else f"em {dias}d")
    if isinstance(ultimo, dict) and (ultimo.get("parecer") or "").strip():
        ctx["exigencia"] = ultimo["parecer"].strip()[:400]
    return ctx


def _transicao(ev: dict) -> str:
    if ev["tipo"] == "mudanca":
        return f"{ev['de'] or '(sem situação)'} → {ev['para'] or '(sem situação)'}"
    if ev["tipo"] == "novo":
        return f"situação: {ev['para'] or '(sem situação)'}"
    return f"total agora: {ev['para']}"


def _linhas_contexto(ctx: dict) -> list[str]:
    linhas = []
    if ctx.get("prazo"):
        linhas.append(f"Prazo: {ctx['prazo']} ({ctx['prazo_dias']}) · bola com o {ctx['bola']}")
    elif ctx.get("bola"):
        linhas.append(f"Bola com o {ctx['bola']}")
    if ctx.get("proximo_passo"):
        linhas.append(f"Próximo passo: {ctx['proximo_passo']}")
    if ctx.get("exigencia"):
        linhas.append(f"Exigência do órgão: {ctx['exigencia']}")
    return linhas


def mensagem(ev: dict, ctx: dict | None = None) -> str:
    """Texto para outbox/webhook/seriema — o mesmo conteúdo que vai no template."""
    ctx = ctx or {}
    if ev.get("origem") == "inbox":
        det = ev.get("detalhe") or {}
        prazos = (det.get("prazos") or []) if isinstance(det, dict) else []
        linha_prazo = f"\nPrazo citado: {', '.join(prazos)}" if prazos else ""
        return (f"📩 {ev['ente']}\n{ev['rotulo']}\n\"{(ev['para'] or '')[:120]}\"{linha_prazo}\n"
                f"(notificação do Transferegov por e-mail)\n— Tuiú")
    ic = ICONE.get(ev["tipo"], "🔔")
    corpo = "\n".join([f"{ev['rotulo']}", _transicao(ev)] + _linhas_contexto(ctx))
    return (f"{ic} {ev['ente']}\n{corpo}\n"
            f"Abrir: {link_cliente(ev['cnpj'])}\n"
            f"(andamento no Transferegov · dados de {_br_iso(ev['snapshot'])} · D-1)\n— Tuiú")


def _br_iso(iso: str) -> str:
    partes = str(iso or "")[:10].split("-")
    return "/".join(reversed(partes)) if len(partes) == 3 else str(iso)


def parametros_template(ev: dict, ctx: dict | None = None) -> list[str]:
    """Os {{1}}..{{5}} do template `aviso_tuiu` (corpo em ferramentas/template_wpp.py).

    Uma linha por parâmetro: a Meta recusa quebra de linha dentro do valor, então
    o contexto operacional inteiro entra concatenado no {{4}}.

    São CINCO — a Meta rejeita template com variáveis demais para o tamanho do
    texto fixo (erro 2388293) e a versão de 7 foi recusada. Por isso o tipo do
    evento vai junto da situação no {{3}} e a data do dado fecha o {{4}}: nada
    saiu da mensagem, só mudou de campo.
    """
    ctx = ctx or {}
    data = f"dados de {_br_iso(ev['snapshot'])}"
    if ev.get("origem") == "inbox":
        det = ev.get("detalhe") if isinstance(ev.get("detalhe"), dict) else {}
        prazos = (det or {}).get("prazos") or []
        prazo = f"Prazo citado: {', '.join(prazos)} · " if prazos else ""
        return [ev["ente"], ev["rotulo"],
                f"notificação por e-mail: {(ev['para'] or '')[:160]}",
                f"{prazo}{data}", link_cliente(ev["cnpj"])]
    return [ev["ente"], ev["rotulo"],
            f"{TIPO_LEGIVEL.get(ev['tipo'], 'andamento')}: {_transicao(ev)}",
            " · ".join(_linhas_contexto(ctx) + [data]),
            link_cliente(ev["cnpj"])]


def _post_json(url: str, payload: dict, headers: dict | None = None) -> tuple[bool, str]:
    dados = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=dados, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return True, f"{r.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _registrar(con, evento_id: int, canal: str, endereco: str | None, msg: str,
               status: str, detalhe: str | None = None) -> int | None:
    """Grava (ou reserva) a entrega. Devolve o id novo, ou None se já existia —
    e "já existia" é a trava que impede o mesmo alerta de sair duas vezes."""
    cur = con.execute(
        "INSERT INTO entregas (evento_id, canal, endereco, mensagem, status, detalhe, enviado_em)"
        " VALUES (%s,%s,%s,%s,%s,%s, CASE WHEN %s='enviado' THEN now() END)"
        " ON CONFLICT (evento_id, canal, endereco) DO NOTHING RETURNING id",
        (evento_id, canal, endereco or "", msg, status, detalhe, status))
    linha = cur.fetchone()
    return linha[0] if linha else None


def _concluir(con, entrega_id: int, ok: bool, detalhe: str) -> None:
    con.execute(
        "UPDATE entregas SET status=%s, detalhe=%s,"
        " enviado_em = CASE WHEN %s THEN now() ELSE enviado_em END WHERE id=%s",
        ("enviado" if ok else "erro", detalhe, ok, entrega_id))


def _enviar(canal: str, endereco: str, ev: dict, msg: str, ctx: dict) -> tuple[bool, str]:
    if canal == "webhook":
        return _post_json(endereco, {"evento": ev, "mensagem": msg, "contexto": ctx})
    if canal == "whatsapp":
        # alerta proativo -> template aprovado; ver app/wpp_cloud.py
        return wpp_cloud.enviar_template(endereco, parametros_template(ev, ctx))
    if canal == "seriema":
        # os campos vão estruturados: no transporte de nuvem o texto formatado
        # não serve (template não aceita quebra de linha) e remontá-lo de volta
        # em campos seria adivinhação
        return seriema.enviar_grupo(msg, chave_entrega=f"evento-{ev['id']}",
                                    parametros=parametros_template(ev, ctx))
    return False, f"canal desconhecido: {canal}"


def _canais_liberados(con, cnpj: str) -> list[tuple[str, str]]:
    """Destinos que PODEM receber agora. Duas travas em série por canal (a geral
    e a do próprio canal) — ver app.config. A outbox não passa por aqui: ela é
    registro interno, não contato com ninguém.

    A carteira tem organizações reais que nunca pediram para receber nada, então
    o padrão é lista vazia e ligar é ato deliberado, registrado em
    `configuracoes_log`.
    """
    destinos: list[tuple[str, str]] = []

    if envio_externo_liberado("whatsapp"):   # alcança o CLIENTE
        destinos += con.execute(
            "SELECT canal, endereco FROM destinatarios"
            " WHERE ativo AND canal='whatsapp' AND cnpj IN (%s,'*')", (cnpj,)).fetchall()

    if envio_externo_liberado("webhook"):    # sistema externo
        destinos += con.execute(
            "SELECT canal, endereco FROM destinatarios"
            " WHERE ativo AND canal='webhook' AND cnpj IN (%s,'*')", (cnpj,)).fetchall()
        if WEBHOOK_URL:
            destinos.append(("webhook", WEBHOOK_URL))

    if envio_externo_liberado("seriema") and seriema.configurado():
        # grupo INTERNO de operação — não chega ao cliente
        destinos.append(("seriema", "grupo-operacao"))

    return destinos


def despachar() -> dict:
    contagem = {"outbox": 0, "webhook": 0, "whatsapp": 0, "seriema": 0,
                "so_outbox": 0, "erros": 0}
    with conectar() as con:
        # eventos ainda sem NENHUMA entrega
        eventos = con.execute(
            "SELECT id, cnpj, ente, dominio, chave, rotulo, instrumento, tipo, de, para,"
            " snapshot::text, origem, detalhe"
            " FROM eventos e WHERE NOT EXISTS (SELECT 1 FROM entregas x WHERE x.evento_id=e.id)"
            "   AND cnpj <> 'nao_atribuido'"
            " ORDER BY id").fetchall()
        cols = ["id", "cnpj", "ente", "dominio", "chave", "rotulo", "instrumento", "tipo",
                "de", "para", "snapshot", "origem", "detalhe"]
        # o `ente` gravado no evento pode ser o CNPJ cru (eventos criados antes do
        # fix de 27/07) — resolver AQUI conserta o que já está na base, sem
        # reescrever histórico
        nomes = nomes_carteira()
        for row in eventos:
            ev = dict(zip(cols, row))
            ev["ente"] = nome_exibicao(ev["cnpj"], ev["ente"], nomes)
            # `instrumento` é a chave que casa com `marcos` — e não é sempre a
            # chave do diff (na parceria, o marco é indexado pela PROPOSTA). Cai
            # na chave para os eventos gravados antes de db/0027.
            ctx = ({} if ev["chave"] == "#count"     # contador não tem instrumento
                   else contexto(con, ev["cnpj"], ev["instrumento"] or ev["chave"]))
            msg = mensagem(ev, ctx)

            if _registrar(con, ev["id"], "outbox", None, msg, "pendente"):
                contagem["outbox"] += 1

            dests = _canais_liberados(con, ev["cnpj"])
            if not dests:
                contagem["so_outbox"] += 1

            # RESERVA e commit antes de qualquer envio: se o processo morrer no
            # meio, a entrega já existe e o alerta não toca o telefone de novo
            reservas = [(_registrar(con, ev["id"], canal, endereco, msg, "enviando"), canal, endereco)
                        for canal, endereco in dests]
            con.commit()

            for entrega_id, canal, endereco in reservas:
                if entrega_id is None:   # outra execução já cuidou desta
                    continue
                ok, det = _enviar(canal, endereco, ev, msg, ctx)
                _concluir(con, entrega_id, ok, det)
                contagem[canal] = contagem.get(canal, 0) + 1
                contagem["erros"] += (not ok)
            con.commit()
    return contagem


def main():
    r = despachar()
    print("entregas:", ", ".join(f"{k}={v}" for k, v in r.items()
                                 if k not in ("so_outbox", "erros")) or "nada novo")
    if r.get("erros"):
        print(f"  {r['erros']} entrega(s) com ERRO — veja `detalhe` em `entregas` "
              f"(reenvio é ato deliberado, não retenta sozinho)")
    if r.get("so_outbox"):
        # dizer isto em voz alta: silêncio de canal desligado não pode ser
        # confundido com "não havia nada para avisar"
        print(f"  {r['so_outbox']} evento(s) ficaram SÓ na outbox — envio externo desligado "
              f"(ligue em /notificacoes.html)")


if __name__ == "__main__":
    main()
