"""Seriema — cliente de notificação WhatsApp, importado do oasis.v2 para o Tuiú.

Porte fiel do contrato do `internal_session` (serviço de sessão WhatsApp
próprio): POST assinado por HMAC v1 em `{base}/messages/group`. Mesmo esquema
canônico do original — se um dia apontar para a mesma sessão, funciona sem
adaptação. Aqui em **stdlib pura** (sem httpx) e síncrono, no espírito
"simples" do Tuiú.

Config (env / .env / cofre DPAPI):
    TUIU_SERIEMA_BASE_URL   ex.: http://127.0.0.1:8080
    TUIU_SERIEMA_SECRET     segredo compartilhado com a sessão
    TUIU_SERIEMA_KEY_ID     default "current"
    TUIU_SERIEMA_GROUP_ID   grupo destino
    TUIU_SERIEMA_SENDER     número remetente (rótulo)
    TUIU_SERIEMA_DRYRUN=1   monta e não envia (teste)

Sem base/secret configurados o canal fica inativo e o evento segue só na outbox.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request

VERSAO_ASSINATURA = "v1"
CAMINHO_GRUPO = "/messages/group"
H_KEY_ID = "X-Seriema-WhatsApp-Key-Id"
H_TIMESTAMP = "X-Seriema-WhatsApp-Timestamp"
H_NONCE = "X-Seriema-WhatsApp-Nonce"
H_BODY_SHA = "X-Seriema-WhatsApp-Body-SHA256"
H_ASSINATURA = "X-Seriema-WhatsApp-Signature"


def _cfg(nome: str, default: str = "") -> str:
    return (os.environ.get(nome) or default).strip()


def configurado() -> bool:
    return bool(_cfg("TUIU_SERIEMA_BASE_URL") and _cfg("TUIU_SERIEMA_SECRET"))


def dry_run() -> bool:
    return _cfg("TUIU_SERIEMA_DRYRUN") in ("1", "true", "yes")


def _corpo(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def _cabecalhos_assinados(secret: str, metodo: str, caminho: str, corpo: bytes,
                          key_id: str = "current") -> dict[str, str]:
    """Assinatura canônica idêntica à do Seriema:
    key_id\\n timestamp\\n nonce\\n METODO\\n caminho\\n sha256(corpo)."""
    ts = int(time.time())
    nonce = secrets.token_hex(16)
    body_sha = hashlib.sha256(corpo).hexdigest()
    canonico = "\n".join([key_id, str(ts), nonce, metodo.upper(), caminho, body_sha])
    assinatura = hmac.new(secret.encode(), canonico.encode(), hashlib.sha256).hexdigest()
    return {
        H_KEY_ID: key_id, H_TIMESTAMP: str(ts), H_NONCE: nonce,
        H_BODY_SHA: body_sha, H_ASSINATURA: f"{VERSAO_ASSINATURA}={assinatura}",
        "Content-Type": "application/json",
    }


def enviar_grupo(texto: str, chave_entrega: str, timeout: float = 15.0) -> tuple[bool, str]:
    """Envia ao grupo configurado. Retorna (ok, detalhe). Nunca levanta."""
    texto = (texto or "").strip()
    if not texto:
        return False, "mensagem vazia"
    if not chave_entrega:
        return False, "delivery_key ausente"
    if not configurado():
        return False, "Seriema não configurado (TUIU_SERIEMA_BASE_URL/_SECRET)"

    payload = {
        "group_id": _cfg("TUIU_SERIEMA_GROUP_ID"),
        "text": texto,
        "delivery_key": chave_entrega,
        "sender_number": _cfg("TUIU_SERIEMA_SENDER"),
    }
    corpo = _corpo(payload)
    if dry_run():
        return True, "DRYRUN " + corpo.decode("utf-8", "replace")[:400]

    url = _cfg("TUIU_SERIEMA_BASE_URL").rstrip("/") + CAMINHO_GRUPO
    cabecalhos = _cabecalhos_assinados(_cfg("TUIU_SERIEMA_SECRET"), "POST", CAMINHO_GRUPO,
                                       corpo, _cfg("TUIU_SERIEMA_KEY_ID", "current"))
    req = urllib.request.Request(url, data=corpo, method="POST", headers=cabecalhos)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resposta = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read()[:160].decode('utf-8', 'replace')}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"
    if not (isinstance(resposta, dict) and resposta.get("ok") is True):
        return False, f"sessao recusou: {str(resposta)[:160]}"
    return True, str(resposta.get("provider_message_id") or "enviado")
