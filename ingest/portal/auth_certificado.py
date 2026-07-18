"""Autenticação por certificado A1 (e-CPF) — camada ISOLADA, só login.

## Fronteira (decisão do dono, 18/07)

O certificado serve **exclusivamente para autenticar a leitura** do Transferegov.
**Nada é assinado com ele.** Este módulo não expõe — e não deve ganhar — nenhuma
função de assinatura. Ele produz um contexto de browser autenticado e entrega;
quem lê é o `sessao_operador`, que é read-only por construção.

## A fortaleza em volta do A1

1. **PIN nunca na imagem, nunca em código**: vem do cofre DPAPI
   (`TUIU_A1_SENHA` / `segredos.py`) ou de arquivo montado em runtime.
2. **Arquivo do certificado montado read-only** e nunca copiado para dentro do
   container (`:ro` no compose).
3. **Sem rota de assinatura**: este módulo só chama `new_context(client_certificates=...)`.
   Nenhuma API de assinar é importada aqui.
4. **Auditoria**: toda autenticação (e falha) é registrada com quando e por quê.
5. **Validade vigiada**: `dias_para_expirar()` alarma antes de o A1 vencer —
   sem isso a falha é silenciosa e o monitor "para de ver mudança" sem avisar.
6. **Sessão longa > re-login**: quem chama deve reautenticar só quando a sessão
   cair de fato (ver `sessao_loop`), não em intervalo fixo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ORIGEM = "https://sso.acesso.gov.br"  # onde o certificado é apresentado


def _auditar(evento: dict) -> None:
    pasta = RAIZ / "data" / "sessao"
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / "auth.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**evento, "quando": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                            ensure_ascii=False) + "\n")


def _senha() -> str | None:
    """PIN do A1: env (injetado em runtime) ou cofre DPAPI. Nunca hardcode."""
    direto = os.environ.get("TUIU_A1_SENHA")
    if direto:
        return direto
    arquivo = os.environ.get("TUIU_A1_SENHA_ARQUIVO")
    if arquivo and Path(arquivo).exists():
        return Path(arquivo).read_text(encoding="utf-8").strip()
    try:
        import sys
        sys.path.insert(0, r"C:\Users\pedro\Desktop\Flumen\ferramentas")
        from segredos import get
        return get("TUIU_A1_SENHA")
    except BaseException:  # noqa: BLE001 — segredos.py faz sys.exit() se falta keyring
        return None


def caminho_certificado() -> Path | None:
    p = os.environ.get("TUIU_A1_PFX")
    return Path(p) if p and Path(p).exists() else None


def dias_para_expirar() -> int | None:
    """Vigia a validade do A1 — a falha por expiração é silenciosa e enganosa."""
    pfx = caminho_certificado()
    senha = _senha()
    if not (pfx and senha):
        return None
    try:
        from cryptography.hazmat.primitives.serialization import pkcs12
        _, cert, _ = pkcs12.load_key_and_certificates(pfx.read_bytes(), senha.encode())
        if cert is None:
            return None
        fim = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after
        if fim.tzinfo is None:
            fim = fim.replace(tzinfo=timezone.utc)
        return (fim - datetime.now(timezone.utc)).days
    except Exception as exc:  # noqa: BLE001
        _auditar({"acao": "validade", "erro": str(exc)[:200]})
        return None


def contexto_autenticado(pw, headless: bool = True):
    """Devolve (contexto, aviso). O contexto sai com o A1 anexado à origem do
    gov.br — o login em si acontece quando a página do SSO é acessada.

    NÃO assina nada. NÃO deve ganhar função de assinatura."""
    pfx, senha = caminho_certificado(), _senha()
    if not pfx:
        return None, "certificado não configurado (TUIU_A1_PFX)"
    if not senha:
        return None, "PIN do certificado ausente (TUIU_A1_SENHA / cofre)"

    dias = dias_para_expirar()
    if dias is not None and dias < 0:
        _auditar({"acao": "auth", "ok": False, "motivo": "certificado expirado"})
        return None, f"certificado EXPIRADO há {-dias} dias"

    navegador = pw.chromium.launch(headless=headless, args=["--disable-dev-shm-usage"])
    contexto = navegador.new_context(
        client_certificates=[{"origin": ORIGEM, "pfxPath": str(pfx), "passphrase": senha}],
        locale="pt-BR",
    )
    _auditar({"acao": "auth", "ok": True, "origem": ORIGEM, "dias_para_expirar": dias,
              "modo": "headless" if headless else "janela"})
    aviso = None
    if dias is not None and dias <= 30:
        aviso = f"certificado A1 expira em {dias} dias — renovar"
    return contexto, aviso


if __name__ == "__main__":
    d = dias_para_expirar()
    pfx = caminho_certificado()
    print(f"certificado: {pfx or 'NÃO configurado (TUIU_A1_PFX)'}")
    print(f"PIN no cofre/env: {'sim' if _senha() else 'NÃO'}")
    print(f"dias para expirar: {d if d is not None else 'desconhecido'}")
