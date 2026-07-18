"""Parser de e-mail de notificação do Transferegov (F1.6).

SEGURANÇA — o e-mail é CONTEÚDO NÃO-CONFIÁVEL:
  - só e-mails de remetente na allowlist viram evento (o resto = `confiavel:false`,
    fica registrado como suspeito, nunca notifica);
  - o parser APENAS extrai e classifica — nunca executa nada, nunca segue link
    (links são removidos e contados);
  - nenhuma instrução contida no corpo é obedecida.

Extrai: remetente, assunto, data, tipo do evento (diligência, complementação,
prestação de contas, aprovação, impedimento, prazo…), instrumentos citados
(convênio/proposta/plano Pix), CNPJ e prazos. Puro stdlib.

⚠️ Os padrões (domínios e frases) são um ponto de partida e precisam ser
calibrados contra e-mails REAIS do Transferegov — marcados com CALIBRAR.
"""

from __future__ import annotations

import email
import os
import re
import unicodedata
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

# CALIBRAR: domínios remetentes confiáveis (confirmar com e-mails reais).
REMETENTES_OK = set(
    d.strip().lower() for d in os.environ.get(
        "TUIU_INBOX_REMETENTES",
        "transferegov.gestao.gov.br,gestao.gov.br,economia.gov.br,serpro.gov.br,in.gov.br",
    ).split(",") if d.strip()
)

# Gate de relevância: mesmo de remetente confiável, o e-mail só vira evento se
# for SOBRE o Transferegov (tem instrumento OU um destes termos). Resolve o
# achado do `serpro.gov.br` — domínio de infra que também manda FGTS etc.
RELEVANTE_TERMOS = (
    "transferegov", "convenio", "contrato de repasse", "plano de acao",
    "prestacao de contas", "termo de fomento", "termo de colaboracao",
    "plano de trabalho", "instrumento", "parceria", "emenda parlamentar",
    "transferencia especial", "diligencia", "concedente", "convenente",
)

# CALIBRAR: baldes de classificação por palavra-chave (sem acento, minúsculo).
BALDES = [
    ("diligencia", ("diligencia",)),
    ("complementacao", ("complementacao", "complemente", "complementar a proposta", "complementar o plano")),
    ("prestacao_contas", ("prestacao de contas", "prestacao de conta")),
    ("impedimento", ("impedid", "impedimento")),
    ("rejeicao", ("rejeit", "reprovad", "indeferid")),
    ("aprovacao", ("aprovad", "deferid", "homologad")),
    ("assinatura", ("assinatura", "assinar o", "pendente de assinatura")),
    ("prazo", ("vence em", "prazo final", "expira", "vencimento")),
    ("liberacao", ("liberacao de recurso", "ordem bancaria", "pagamento efetuad")),
]

_RE_TAGS = re.compile(r"<[^>]+>")
_RE_LINK = re.compile(r"https?://[^\s\"'>)]+", re.I)
_RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_RE_PLANO = re.compile(r"\b0903\d{4}-\d?-?\d{5,6}\b")                 # 09032025-080453 / 09032025-2-086198
_RE_CONVENIO = re.compile(r"\bn[ºo°\.]?\s?\d{5,7}/\d{4}\b", re.I)    # nº 848253/2024
_RE_PROPOSTA = re.compile(r"proposta\s+n?[ºo°\.]?\s?(\d{3,7}/?\d{0,4})", re.I)
_RE_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def _decodifica(v: str | None) -> str:
    if not v:
        return ""
    try:
        return str(make_header(decode_header(v)))
    except Exception:
        return v


def _texto(msg: email.message.Message) -> str:
    """Prefere text/plain; cai para text/html sem tags."""
    plano, html = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html"):
            continue
        try:
            corpo = part.get_payload(decode=True) or b""
            txt = corpo.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if ct == "text/plain":
            plano += txt + "\n"
        else:
            html += txt + "\n"
    if plano.strip():
        return plano
    return _RE_TAGS.sub(" ", html)


def _classificar(assunto: str, corpo: str) -> str:
    alvo = _sem_acento(assunto + " " + corpo)
    for tipo, chaves in BALDES:
        if any(c in alvo for c in chaves):
            return tipo
    return "notificacao"


def _instrumentos(txt: str) -> dict:
    planos = sorted(set(_RE_PLANO.findall(txt)))
    convenios = sorted(set(m.strip() for m in _RE_CONVENIO.findall(txt)))
    propostas = sorted(set(_RE_PROPOSTA.findall(txt)))
    return {"planos_pix": planos, "convenios": convenios, "propostas": propostas}


def parse_email(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw)
    remetente = parseaddr(_decodifica(msg.get("From")))[1].lower()
    dominio = remetente.split("@")[-1] if "@" in remetente else ""
    confiavel = any(dominio == d or dominio.endswith("." + d) for d in REMETENTES_OK)

    assunto = _decodifica(msg.get("Subject"))
    corpo = _texto(msg)
    links = _RE_LINK.findall(corpo)
    corpo_sem_link = _RE_LINK.sub("[link removido]", corpo)

    try:
        data = parsedate_to_datetime(msg.get("Date")).date().isoformat()
    except Exception:
        data = None

    cnpjs = sorted({re.sub(r"\D", "", c) for c in _RE_CNPJ.findall(corpo) if len(re.sub(r"\D", "", c)) == 14})
    to = parseaddr(_decodifica(msg.get("Delivered-To") or msg.get("To")))[1].lower()

    instrumentos = _instrumentos(corpo)
    tem_instrumento = any(instrumentos.values())
    alvo_rel = _sem_acento(assunto + " " + corpo_sem_link)
    relevante = tem_instrumento or any(t in alvo_rel for t in RELEVANTE_TERMOS)

    return {
        "message_id": (msg.get("Message-ID") or "").strip() or f"sem-id:{hash((remetente, assunto, data))}",
        "remetente": remetente, "confiavel": confiavel, "relevante": relevante,
        "assunto": assunto, "data": data, "para": to,
        "tipo": _classificar(assunto, corpo),
        "instrumentos": instrumentos,
        "cnpjs": cnpjs,
        "prazos": sorted(set(_RE_DATA.findall(corpo_sem_link))),
        "links_removidos": len(links),
        "resumo": (assunto or corpo_sem_link.strip()[:120]).strip(),
    }


if __name__ == "__main__":
    import sys
    for caminho in sys.argv[1:]:
        with open(caminho, "rb") as fh:
            p = parse_email(fh.read())
        rot = "OK" if p["confiavel"] and p["relevante"] else ("IRRELEVANTE" if p["confiavel"] else "SUSPEITO")
        print(f"[{rot}] {p['remetente']} | {p['tipo']} | "
              f"{p['assunto'][:60]} | instr={p['instrumentos']} | cnpj={p['cnpjs']} | prazos={p['prazos']}")
