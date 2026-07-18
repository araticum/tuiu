"""Cliente CAUC — ⚠️ FORA DO ESCOPO desde a correção de 18/07/2026.

O CAUC mede a regularidade fiscal do **ENTE** (RREO/RGF, Fundeb, SIAFIC,
mínimos de saúde/educação). O cliente do Tuiú é o **TERCEIRO EXECUTOR**, que
não tem essas obrigações — a regularidade que o trava é CEPIM/CEIS/CNEP, em
`ingest/transparencia/regularidade_terceiro.py`. Este módulo fica preservado
(funciona, mapeia a API) caso um dia atendamos entes; **não está na cadeia
diária**.

Regularidade fiscal do ente no Sistema de Informações
sobre Requisitos Fiscais (sti.tesouro.gov.br, IN STN/MF 8/2025, 26 itens).

Mapa da API descoberto do bundle Angular em 18/07/2026 (base same-origin `/ng`):
  ABERTOS (sem captcha):
    GET /ng/ente-estabelecimento/obter-por-texto?texto=<cnpj|nome>  -> resolve id do ente
    GET /ng/captcha/public-key                                       -> sitekey hCaptcha
  CAPTCHA-GATED (extrato completo dos 26 itens):
    POST /ng/captcha/validate?h-captcha-response=<token>  -> jwt
    (extrato/detalhe consomem o jwt) — precisa resolver hCaptcha.

Estratégia (plano §4/§9): a resolução do extrato completo fica atrás do
doc-extractor (Playwright, host BR, solver de captcha plugável), fail-safe. Este
cliente entrega HOJE o que é aberto (resolver o ente por CNPJ) e deixa o gancho
do extrato explícito. Sem chave; só GET nos abertos. Degrada sem quebrar.
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request

BASE = "https://sti.tesouro.gov.br/ng"
UA = {"Accept": "application/json", "User-Agent": "araticum-tuiu-cauc/0.1"}

# GOTCHA (18/07/2026): sti.tesouro.gov.br apresenta certificado com hostname
# MISMATCH (curl exige -k). Como é endpoint público de LEITURA (CNPJ -> id, sem
# credencial nem dado sensível), toleramos o mismatch com um contexto próprio.
# Rever se o Tesouro corrigir o cert. NUNCA reusar este contexto para endpoints
# autenticados ou de escrita.
_CTX_INSEGURO = ssl.create_default_context()
_CTX_INSEGURO.check_hostname = False
_CTX_INSEGURO.verify_mode = ssl.CERT_NONE


def _get(path: str, timeout: int = 25):
    req = urllib.request.Request(f"{BASE}{path}", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            corpo = r.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:  # cert mismatch conhecido do Tesouro
        if not isinstance(getattr(exc, "reason", None), ssl.SSLError):
            raise
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX_INSEGURO) as r:
            corpo = r.read().decode("utf-8", "replace")
    return json.loads(corpo)


def resolver_ente(cnpj: str) -> dict | None:
    """CNPJ -> {id, nome} do ente no CAUC (endpoint aberto). None se não achar."""
    doc = "".join(c for c in cnpj if c.isdigit())
    mascara = f"{doc[:2]}.{doc[2:5]}.{doc[5:8]}/{doc[8:12]}-{doc[12:]}" if len(doc) == 14 else doc
    try:
        dados = _get(f"/ente-estabelecimento/obter-por-texto?texto={urllib.parse.quote(mascara)}").get("dados", [])
    except Exception:
        return None
    for d in dados:
        if mascara in (d.get("nome") or "") or doc in (d.get("nome") or "").replace(".", "").replace("/", "").replace("-", ""):
            return {"id": d["id"], "nome": d["nome"], "estabelecimento": d.get("isEstabelecimento", False)}
    return dados[0] and {"id": dados[0]["id"], "nome": dados[0]["nome"]} if dados else None


def sitekey_captcha() -> str | None:
    try:
        req = urllib.request.Request(f"{BASE}/captcha/public-key",
                                     headers={**UA, "Accept": "text/plain"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode().strip()
        except urllib.error.URLError as exc:
            if not isinstance(getattr(exc, "reason", None), ssl.SSLError):
                raise
            with urllib.request.urlopen(req, timeout=20, context=_CTX_INSEGURO) as r:
                return r.read().decode().strip()
    except Exception:
        return None


def consultar(cnpj: str) -> dict:
    """Situação de regularidade do ente. Nesta fase resolve o ente (aberto) e
    marca o extrato como pendente de captcha (a resolver via doc-extractor)."""
    ente = resolver_ente(cnpj)
    if ente is None:
        return {"cnpj": cnpj, "disponivel": False, "motivo": "ente não localizado no CAUC"}
    return {
        "cnpj": cnpj, "disponivel": True, "ente_cauc": ente,
        "extrato": {"estado": "pendente_captcha",
                    "obtido_via": None,
                    "nota": "extrato dos 26 itens é captcha-gated (hCaptcha); "
                            "coleta via doc-extractor na integração F2",
                    "sitekey": sitekey_captcha()},
        "base_legal": "IN STN/MF nº 8/2025 (26 itens do CAUC)",
    }


if __name__ == "__main__":
    import sys

    for cnpj in (sys.argv[1:] or ["34925198000136", "01616520000196", "07460294000183"]):
        r = consultar(cnpj)
        ente = r.get("ente_cauc", {})
        print(f"{cnpj}: {'OK' if r['disponivel'] else 'FALHA'} "
              f"id={ente.get('id')} {ente.get('nome', r.get('motivo'))}")
