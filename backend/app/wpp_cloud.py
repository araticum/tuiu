"""Canal WhatsApp oficial — Cloud API da Meta (decisão do dono, 27/07/2026).

Por que o caminho oficial e não a sessão Seriema: a sessão só sabe falar com
GRUPO (`isGroupJid` recusa qualquer JID que não termine em `@g.us`) e a única
instância de pé no araticum é a de PRODUÇÃO do oasis.v2, que a decisão de 18/07
manda não encostar. Falar com o número de uma pessoa exige a Cloud API.

**Template, não texto livre.** O nosso caso é aviso proativo — mudou o
andamento, avisa — e isso cai FORA da janela de 24h, onde a Meta só entrega
mensagem de template aprovado. Texto livre só passa se a pessoa nos escreveu nas
últimas 24h; fica aqui para teste e resposta, nunca para o alerta.

O texto do template a cadastrar está em `docs/motor-eventos-notificacao.md`.
Enquanto ele não for aprovado, `TUIU_WPP_DRYRUN=1` valida o payload inteiro sem
envio — dá para fechar o pipe hoje e só virar a chave quando a Meta liberar.

Config (env / .env / cofre DPAPI):
    TUIU_WPP_TOKEN      token do System User do app — NUNCA no git
    TUIU_WPP_PHONE_ID   Phone Number ID do remetente (o id, não o telefone)
    TUIU_WPP_TEMPLATE   nome do template aprovado (default tuiu_andamento)
    TUIU_WPP_IDIOMA     código de idioma do template (default pt_BR)
    TUIU_WPP_VERSAO     versão da Graph API (default v21.0)
    TUIU_WPP_DRYRUN=1   monta o payload e não envia (teste)

Sem token/phone_id o canal fica inativo e o evento segue só na outbox.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

BASE_GRAPH = "https://graph.facebook.com"
# A Meta recusa parâmetro de template com quebra de linha, tabulação ou mais de
# 4 espaços seguidos (erro 132000, "parameter format mismatch"). A quebra de
# linha vive no CORPO do template, nunca no valor que mandamos.
PROIBIDO_EM_PARAMETRO = re.compile(r"[\r\n\t]+|\s{5,}")
LIMITE_PARAMETRO = 300   # a Meta aceita 1024; 300 é o que ainda se lê no celular


def _cfg(nome: str, default: str = "") -> str:
    return (os.environ.get(nome) or default).strip()


def configurado() -> bool:
    return bool(_cfg("TUIU_WPP_TOKEN") and _cfg("TUIU_WPP_PHONE_ID"))


def dry_run() -> bool:
    return _cfg("TUIU_WPP_DRYRUN") in ("1", "true", "yes")


def template_nome() -> str:
    return _cfg("TUIU_WPP_TEMPLATE", "tuiu_andamento")


def falta() -> str | None:
    """O que impede o canal de funcionar — vai para a tela de notificações."""
    ausentes = [n for n in ("TUIU_WPP_TOKEN", "TUIU_WPP_PHONE_ID") if not _cfg(n)]
    return f"{' e '.join(ausentes)} no host" if ausentes else None


def normalizar_numero(bruto: str) -> str:
    """E.164 sem '+' — o formato que a Cloud API espera em `to`.

    Só completa o 55 quando o número tem cara de brasileiro sem DDI (10 ou 11
    dígitos). Número que já venha com DDI passa intacto: adivinhar país de um
    telefone estrangeiro erraria calado.
    """
    digitos = re.sub(r"\D", "", bruto or "")
    return f"55{digitos}" if len(digitos) in (10, 11) else digitos


def limpar_parametro(texto: str | None) -> str:
    """Deixa o valor no formato que a Meta aceita. Nunca devolve vazio: parâmetro
    em branco é recusado no envio, então some vira travessão."""
    limpo = PROIBIDO_EM_PARAMETRO.sub(" · ", str(texto or "").strip())
    limpo = re.sub(r"\s+", " ", limpo).strip(" ·").strip()
    if len(limpo) > LIMITE_PARAMETRO:
        limpo = limpo[: LIMITE_PARAMETRO - 1].rstrip() + "…"
    return limpo or "—"


def _post(payload: dict, timeout: float) -> tuple[bool, str]:
    if not configurado():
        return False, "Cloud API não configurada (TUIU_WPP_TOKEN/_PHONE_ID)"
    corpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if dry_run():
        # INTEIRO, não truncado: o DRYRUN existe para conferir o payload, e
        # cortar no meio devolvia JSON quebrado — inútil para inspecionar. O
        # tamanho já é limitado por LIMITE_PARAMETRO.
        return True, "DRYRUN " + corpo.decode("utf-8", "replace")

    url = f"{BASE_GRAPH}/{_cfg('TUIU_WPP_VERSAO', 'v21.0')}/{_cfg('TUIU_WPP_PHONE_ID')}/messages"
    req = urllib.request.Request(url, data=corpo, method="POST", headers={
        "Authorization": f"Bearer {_cfg('TUIU_WPP_TOKEN')}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resposta = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        # o corpo do erro da Meta é o que diz o motivo real (template não
        # aprovado, número fora da lista, janela de 24h fechada) — sem ele o
        # diagnóstico vira adivinhação
        bruto = e.read()[:400].decode("utf-8", "replace")
        try:
            err = json.loads(bruto).get("error", {})
            return False, f"Meta {err.get('code')}: {err.get('message')}"
        except Exception:  # noqa: BLE001
            return False, f"HTTP {e.code}: {bruto}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"

    ids = resposta.get("messages") or []
    if not ids:
        return False, f"resposta sem message id: {str(resposta)[:160]}"
    return True, str(ids[0].get("id") or "enviado")


def enviar_template(destino: str, parametros: list[str], timeout: float = 20.0) -> tuple[bool, str]:
    """Mensagem de template — o caminho do alerta proativo. Nunca levanta.

    `parametros` entram em ordem nos {{1}}..{{n}} do corpo aprovado; a contagem
    tem que bater exatamente com a do template, senão a Meta recusa.
    """
    numero = normalizar_numero(destino)
    if not numero:
        return False, f"número inválido: {destino!r}"
    if not parametros:
        return False, "template sem parâmetros"
    return _post({
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "template",
        "template": {
            "name": template_nome(),
            "language": {"code": _cfg("TUIU_WPP_IDIOMA", "pt_BR")},
            "components": [{
                "type": "body",
                "parameters": [{"type": "text", "text": limpar_parametro(p)} for p in parametros],
            }],
        },
    }, timeout)


def enviar_texto(destino: str, texto: str, timeout: float = 20.0) -> tuple[bool, str]:
    """Texto livre — SÓ entrega dentro da janela de 24h (a pessoa falou com a
    gente). Serve para teste e resposta; o alerta diário usa template."""
    numero = normalizar_numero(destino)
    if not numero:
        return False, f"número inválido: {destino!r}"
    if not (texto or "").strip():
        return False, "mensagem vazia"
    return _post({
        "messaging_product": "whatsapp", "to": numero, "type": "text",
        "text": {"preview_url": False, "body": texto.strip()},
    }, timeout)
