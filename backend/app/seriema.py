"""Seriema — canal INTERNO de operação (não chega ao cliente), dois transportes.

    internal_session  POST assinado por HMAC v1 em `{base}/messages/group`,
                      contra o sidecar de sessão WhatsApp próprio. Porte fiel do
                      contrato do oasis.v2 — se um dia apontar para a mesma
                      sessão, funciona sem adaptação. Fala com GRUPO.
    cloud_api         a API oficial da Meta (via `app.wpp_cloud`), uma mensagem
                      de template por número em `TUIU_SERIEMA_CLOUD_DESTINOS`.

Por que os dois: a Cloud API **não envia para grupo** — lá "o grupo" vira a
lista de quem opera. E o sidecar de sessão não está de pé no araticum, o que
deixava este canal inerte e o alarme de cadeia quebrada mudo (foi o buraco de
22/07). Com `cloud_api` o aviso interno sai sem sidecar nenhum.

Config (env / .env / cofre DPAPI):
    TUIU_SERIEMA_PROVIDER        internal_session (padrão) | cloud_api
    TUIU_SERIEMA_DRYRUN=1        monta e não envia (teste)
    -- internal_session --
    TUIU_SERIEMA_BASE_URL        ex.: http://127.0.0.1:8080
    TUIU_SERIEMA_SECRET          segredo compartilhado com a sessão
    TUIU_SERIEMA_KEY_ID          default "current"
    TUIU_SERIEMA_GROUP_ID        grupo destino
    TUIU_SERIEMA_SENDER          número remetente (rótulo)
    -- cloud_api --
    TUIU_SERIEMA_CLOUD_DESTINOS  números de quem opera, separados por vírgula

O transporte da nuvem reaproveita as credenciais de `TUIU_WPP_*` de propósito:
são o MESMO número e o MESMO token: duplicar em outro prefixo criaria duas
verdades que divergem calado no dia em que uma for rotacionada.

Sem configuração o canal fica inativo e o evento segue só na outbox.
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

from app import wpp_cloud

VERSAO_ASSINATURA = "v1"
CAMINHO_GRUPO = "/messages/group"
H_KEY_ID = "X-Seriema-WhatsApp-Key-Id"
H_TIMESTAMP = "X-Seriema-WhatsApp-Timestamp"
H_NONCE = "X-Seriema-WhatsApp-Nonce"
H_BODY_SHA = "X-Seriema-WhatsApp-Body-SHA256"
H_ASSINATURA = "X-Seriema-WhatsApp-Signature"


PROVEDOR_SESSAO = "internal_session"
PROVEDOR_NUVEM = "cloud_api"


def _cfg(nome: str, default: str = "") -> str:
    return (os.environ.get(nome) or default).strip()


def provedor() -> str:
    """Transporte em uso. Valor estranho cai na sessão — instalação existente
    não pode trocar de transporte sozinha por causa de um typo no env."""
    escolhido = _cfg("TUIU_SERIEMA_PROVIDER", PROVEDOR_SESSAO).lower()
    return escolhido if escolhido in (PROVEDOR_SESSAO, PROVEDOR_NUVEM) else PROVEDOR_SESSAO


def destinos_nuvem() -> list[str]:
    return [d.strip() for d in _cfg("TUIU_SERIEMA_CLOUD_DESTINOS").split(",") if d.strip()]


def falta_config() -> str | None:
    """O que impede ESTE canal de enviar agora. None = pronto.

    O painel mostra isto, então tem que nomear a variável que falta: com dois
    transportes, um texto fixo vira mentira na tela de quem opera.
    """
    if provedor() == PROVEDOR_NUVEM:
        ausentes = [n for n, v in (("TUIU_WPP_TOKEN", _cfg("TUIU_WPP_TOKEN")),
                                   ("TUIU_WPP_PHONE_ID", _cfg("TUIU_WPP_PHONE_ID")),
                                   ("TUIU_SERIEMA_CLOUD_DESTINOS", ",".join(destinos_nuvem())))
                    if not v]
    else:
        ausentes = [n for n, v in (("TUIU_SERIEMA_BASE_URL", _cfg("TUIU_SERIEMA_BASE_URL")),
                                   ("TUIU_SERIEMA_SECRET", _cfg("TUIU_SERIEMA_SECRET")))
                    if not v]
    return " e ".join(ausentes) + " no host" if ausentes else None


def configurado() -> bool:
    return falta_config() is None


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


def _enviar_nuvem(texto: str, parametros: list[str], timeout: float,
                  template: str | None = None) -> tuple[bool, str]:
    """Uma mensagem por número de quem opera.

    **Texto livre quando a janela de 24h está aberta; template quando fechada.**
    Não é contorno de template pendente: para o canal INTERNO o texto livre é
    melhor mensagem — cabe quebra de linha e o link de cada peça, coisas que o
    parâmetro de template não aceita. O template existe para o dia em que
    ninguém da equipe escreveu nas últimas 24h.

    Falha se QUALQUER destino falhar: aviso que chega pela metade é aviso
    quebrado, e a entrega tem que ficar registrada como erro para alguém olhar.
    """
    from app import wpp_webhook

    destinos = destinos_nuvem()
    entregues, erros = [], []
    for destino in destinos:
        if texto and wpp_webhook.janela_aberta(destino):
            ok, detalhe = wpp_cloud.enviar_texto(destino, texto, timeout=timeout)
            detalhe = f"texto livre · {detalhe}"
        else:
            ok, detalhe = wpp_cloud.enviar_template(destino, parametros, timeout=timeout,
                                                    template=template)
        (entregues if ok else erros).append(f"{destino}: {detalhe}")
    if erros:
        return False, f"{len(erros)}/{len(destinos)} falharam — " + " | ".join(erros)
    return True, " | ".join(entregues)


def enviar_grupo(texto: str, chave_entrega: str, parametros: list[str] | None = None,
                 timeout: float = 15.0, template: str | None = None) -> tuple[bool, str]:
    """Envia a quem opera. Retorna (ok, detalhe). Nunca levanta.

    `parametros` são os campos do template, exigidos no transporte de nuvem
    porque fora da janela de 24h só template entrega. Sem eles, o envio é
    RECUSADO em vez de remontar os campos a partir do texto formatado:
    desmontar a mensagem de volta adivinha, e adivinhar o nome do cliente num
    aviso operacional é pior do que não mandar.

    Dentro da janela, o `texto` é preferido — ver `_enviar_nuvem`.
    """
    texto = (texto or "").strip()
    if not texto:
        return False, "mensagem vazia"
    if not chave_entrega:
        return False, "delivery_key ausente"
    if not configurado():
        return False, f"Seriema não configurado — falta {falta_config()}"

    if provedor() == PROVEDOR_NUVEM:
        if not parametros:
            return False, "transporte cloud_api exige `parametros` do template"
        return _enviar_nuvem(texto, parametros, timeout, template)

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
