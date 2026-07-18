"""Despachante de notificações (F1.5) — leva eventos de andamento aos canais.

Canais (plugáveis, idempotentes por evento+canal+endereço):
  - outbox   : sempre — persiste a mensagem WhatsApp-ready (status 'pendente').
  - webhook  : se houver destinatário canal='webhook' (ou TUIU_WEBHOOK_URL) —
               POST JSON do evento. É o "webhook de saída" para plugar onde quiser.
  - whatsapp : se houver destinatário canal='whatsapp' E provider configurado —
               envia via WhatsApp Cloud API PRÓPRIA (TUIU_WPP_TOKEN + _PHONE_ID).
               Nunca toca a Seriema de produção do oasis.v2 (decisão do dono:
               instância própria só na F5). TUIU_WPP_DRYRUN=1 = monta o payload
               e não envia (para testar sem disparar de verdade).

Uso:
    py -3 backend/app/notificador.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import conectar  # noqa: E402

WEBHOOK_URL = os.environ.get("TUIU_WEBHOOK_URL", "").strip()
WPP_TOKEN = os.environ.get("TUIU_WPP_TOKEN", "").strip()
WPP_PHONE_ID = os.environ.get("TUIU_WPP_PHONE_ID", "").strip()
WPP_API = os.environ.get("TUIU_WPP_API", "https://graph.facebook.com/v20.0")
WPP_DRYRUN = os.environ.get("TUIU_WPP_DRYRUN", "").strip() in ("1", "true", "yes")

ICONE = {"novo": "🆕", "mudanca": "🔔", "incremento": "➕"}


def mensagem(ev: dict) -> str:
    if ev.get("origem") == "inbox":
        det = ev.get("detalhe") or {}
        prazos = (det.get("prazos") or []) if isinstance(det, dict) else []
        linha_prazo = f"\nPrazo citado: {', '.join(prazos)}" if prazos else ""
        return (f"📩 {ev['ente']}\n{ev['rotulo']}\n\"{(ev['para'] or '')[:120]}\"{linha_prazo}\n"
                f"(notificação do Transferegov por e-mail)\n— Tuiú")
    ic = ICONE.get(ev["tipo"], "🔔")
    if ev["tipo"] == "mudanca":
        corpo = f"{ev['rotulo']}\n{ev['de']} → {ev['para']}"
    elif ev["tipo"] == "novo":
        corpo = f"{ev['rotulo']} (novo)\nsituação: {ev['para']}"
    else:
        corpo = ev["rotulo"]
    return (f"{ic} {ev['ente']}\n{corpo}\n"
            f"(andamento no Transferegov · dados de {ev['snapshot']} · D-1)\n— Tuiú")


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


def _enviar_whatsapp(to: str, msg: str) -> tuple[bool, str]:
    if not (WPP_TOKEN and WPP_PHONE_ID):
        return False, "provider WhatsApp não configurado (TUIU_WPP_TOKEN/_PHONE_ID)"
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text",
               "text": {"preview_url": False, "body": msg}}
    if WPP_DRYRUN:
        return True, "DRYRUN " + json.dumps(payload, ensure_ascii=False)
    return _post_json(f"{WPP_API}/{WPP_PHONE_ID}/messages", payload,
                      {"Authorization": f"Bearer {WPP_TOKEN}"})


def _registrar(con, evento_id: int, canal: str, endereco: str | None, msg: str,
               status: str, detalhe: str | None) -> bool:
    cur = con.execute(
        "INSERT INTO entregas (evento_id, canal, endereco, mensagem, status, detalhe, enviado_em)"
        " VALUES (%s,%s,%s,%s,%s,%s, CASE WHEN %s='enviado' THEN now() END)"
        " ON CONFLICT (evento_id, canal, endereco) DO NOTHING RETURNING id",
        (evento_id, canal, endereco or "", msg, status, detalhe, status))
    return cur.fetchone() is not None


def despachar() -> dict:
    contagem = {"outbox": 0, "webhook": 0, "whatsapp": 0}
    with conectar() as con:
        # eventos ainda sem NENHUMA entrega
        eventos = con.execute(
            "SELECT id, cnpj, ente, dominio, chave, rotulo, tipo, de, para, snapshot::text, origem, detalhe"
            " FROM eventos e WHERE NOT EXISTS (SELECT 1 FROM entregas x WHERE x.evento_id=e.id)"
            "   AND cnpj <> 'nao_atribuido'"
            " ORDER BY id").fetchall()
        cols = ["id", "cnpj", "ente", "dominio", "chave", "rotulo", "tipo", "de", "para",
                "snapshot", "origem", "detalhe"]
        for row in eventos:
            ev = dict(zip(cols, row))
            msg = mensagem(ev)

            if _registrar(con, ev["id"], "outbox", None, msg, "pendente", None):
                contagem["outbox"] += 1

            dests = con.execute(
                "SELECT canal, endereco FROM destinatarios WHERE ativo AND cnpj IN (%s,'*')",
                (ev["cnpj"],)).fetchall()
            if WEBHOOK_URL:
                dests.append(("webhook", WEBHOOK_URL))

            for canal, endereco in dests:
                if canal == "webhook":
                    ok, det = _post_json(endereco, {"evento": ev, "mensagem": msg})
                elif canal == "whatsapp":
                    ok, det = _enviar_whatsapp(endereco, msg)
                else:
                    ok, det = False, f"canal desconhecido: {canal}"
                if _registrar(con, ev["id"], canal, endereco, msg,
                              "enviado" if ok else "erro", det):
                    contagem[canal] = contagem.get(canal, 0) + 1
        con.commit()
    return contagem


def main():
    r = despachar()
    print("entregas:", ", ".join(f"{k}={v}" for k, v in r.items()) or "nada novo")


if __name__ == "__main__":
    main()
