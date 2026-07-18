"""Leitor da sessão do OPERADOR no Transferegov — attach, nunca login.

## Por que existe

A plataforma **só aceita CPF como operador**. Mesmo com contrato empresa →
Araticum, quem opera é uma pessoa física (o titular do gov.br), logada no
portal. Não há como um sistema "se cadastrar" como operador nem há API
transacional para convenente. Logo, o que dá para automatizar com segurança é
**ler a sessão que o próprio operador abriu**.

## Contrato de segurança (aplicado em código, não só documentado)

1. **Nunca autentica.** Este módulo não digita usuário, senha, código 2FA nem
   toca em credencial. O operador faz login **manualmente** na janela dele.
   Se a sessão não estiver autenticada, o leitor avisa e para.
2. **Somente leitura, por construção.** A API pública deste módulo só navega
   (GET) e extrai. Não existe função de clique, preenchimento ou envio — o
   protocolo de qualquer ato no Transferegov continua sendo **humano**.
3. **Allowlist de domínio.** Só navega em domínios do Transferegov/gov.br
   listados; qualquer outra URL é recusada.
4. **Trilha de auditoria.** Toda navegação e extração fica registrada em
   `data/sessao/<data>/auditoria.jsonl`.
5. **Opt-in explícito.** Só roda com `TUIU_SESSAO_ATIVA=1`.

## Como o operador prepara a janela (uma vez por dia de trabalho)

    chrome.exe --remote-debugging-port=9222 --user-data-dir="D:\\tuiu\\.perfil-operador"
    (na janela que abrir: acessar o Transferegov e fazer login gov.br normalmente)

Depois:  py -3 ingest/portal/sessao_operador.py --descobrir
         py -3 ingest/portal/sessao_operador.py            # leitura das páginas configuradas

`--descobrir` salva a estrutura da página autenticada para calibrarmos os
extratores (nunca vimos o DOM logado — a calibração é na primeira sessão real).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CDP = os.environ.get("TUIU_CDP_URL", "http://127.0.0.1:9222")

DOMINIOS_OK = (
    "transferegov.sistema.gov.br",
    "transferegov.gestao.gov.br",
    "gov.br/transferegov",
)

# Páginas autenticadas de interesse do operador. CALIBRAR na 1ª sessão real —
# os caminhos abaixo são os do portal público/SPA e servem de ponto de partida.
LEITURAS = [
    {"nome": "portal", "url": "https://portal.transferegov.sistema.gov.br/portal/home"},
    {"nome": "discricionarias", "url": "https://discricionarias.transferegov.sistema.gov.br/"},
]


def _auditar(registro: dict) -> None:
    pasta = RAIZ / "data" / "sessao" / date.today().isoformat()
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / "auditoria.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**registro,
                             "quando": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                            ensure_ascii=False) + "\n")


def _permitida(url: str) -> bool:
    return any(d in url for d in DOMINIOS_OK)


def _parece_login(url: str, titulo: str) -> bool:
    alvo = f"{url} {titulo}".lower()
    return any(t in alvo for t in ("idp.", "/login", "sso", "acesso.gov.br", "entrar com gov.br"))


def _pasta_saida() -> Path:
    p = RAIZ / "data" / "sessao" / date.today().isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p


def ler(descobrir: bool = False) -> dict:
    if os.environ.get("TUIU_SESSAO_ATIVA") != "1":
        return {"ok": False, "erro": "desligado — defina TUIU_SESSAO_ATIVA=1 para habilitar"}

    from playwright.sync_api import sync_playwright

    saida = _pasta_saida()
    resultado = {"ok": True, "lidas": [], "avisos": []}

    with sync_playwright() as pw:
        try:
            navegador = pw.chromium.connect_over_cdp(CDP)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "erro": f"não achei a janela do operador em {CDP}: {exc}. "
                                         "Abra o Chrome com --remote-debugging-port=9222 e faça login."}

        ctx = navegador.contexts[0] if navegador.contexts else None
        if ctx is None:
            return {"ok": False, "erro": "janela sem contexto — abra uma aba e faça login"}
        pagina = ctx.pages[0] if ctx.pages else ctx.new_page()

        for leitura in LEITURAS:
            url = leitura["url"]
            if not _permitida(url):
                resultado["avisos"].append(f"recusada (fora da allowlist): {url}")
                continue
            try:
                # SOMENTE navegação GET + extração. Nada de clique/preenchimento.
                pagina.goto(url, wait_until="domcontentloaded", timeout=45000)
                pagina.wait_for_timeout(2500)  # SPA monta
                titulo, atual = pagina.title(), pagina.url
                texto = pagina.inner_text("body")[:200000]
            except Exception as exc:  # noqa: BLE001
                _auditar({"acao": "ler", "url": url, "erro": str(exc)[:200]})
                resultado["avisos"].append(f"falhou em {leitura['nome']}: {str(exc)[:120]}")
                continue

            autenticada = not _parece_login(atual, titulo)
            _auditar({"acao": "ler", "nome": leitura["nome"], "url": url, "url_final": atual,
                      "titulo": titulo, "autenticada": autenticada, "bytes_texto": len(texto)})

            if not autenticada:
                resultado["avisos"].append(
                    f"{leitura['nome']}: sessão NÃO autenticada (caiu no login) — "
                    "faça o login gov.br manualmente na janela e rode de novo")
                continue

            (saida / f"{leitura['nome']}.txt").write_text(texto, encoding="utf-8")
            if descobrir:
                (saida / f"{leitura['nome']}.html").write_text(pagina.content()[:2000000], encoding="utf-8")
                estrutura = pagina.evaluate("""() => {
                    const sel = (s) => Array.from(document.querySelectorAll(s)).slice(0,60)
                        .map(e => (e.innerText||'').trim().slice(0,90)).filter(Boolean);
                    return {titulos: sel('h1,h2,h3'), tabelas: document.querySelectorAll('table').length,
                            links: sel('a[href]').slice(0,40), abas: sel('[role=tab], .nav-link')};
                }""")
                (saida / f"{leitura['nome']}.estrutura.json").write_text(
                    json.dumps(estrutura, ensure_ascii=False, indent=2), encoding="utf-8")

            resultado["lidas"].append({"nome": leitura["nome"], "titulo": titulo,
                                       "url_final": atual, "chars": len(texto),
                                       "pendencias_detectadas": _pendencias(texto)})
    resultado["saida"] = str(saida)
    return resultado


_PADROES_PENDENCIA = [
    (r"pend[êe]ncia[s]?", "pendência"),
    (r"aguardando\s+complementa", "complementação"),
    (r"dilig[êe]ncia", "diligência"),
    (r"prazo\s+(?:final|expira|vence)", "prazo"),
    (r"prestaç[ãa]o\s+de\s+contas", "prestação de contas"),
]


def _pendencias(texto: str) -> list[str]:
    """Sinais na página autenticada. Heurística — calibrar com o DOM real."""
    achados = []
    baixo = texto.lower()
    for padrao, rotulo in _PADROES_PENDENCIA:
        if re.search(padrao, baixo):
            achados.append(rotulo)
    return achados


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--descobrir", action="store_true",
                    help="salva HTML e estrutura para calibrar os extratores")
    args = ap.parse_args()

    r = ler(descobrir=args.descobrir)
    if not r.get("ok"):
        print("ERRO:", r["erro"])
        sys.exit(1)
    for l in r["lidas"]:
        print(f"  [{l['nome']}] {l['titulo'][:60]} | {l['chars']} chars"
              + (f" | sinais: {', '.join(l['pendencias_detectadas'])}" if l["pendencias_detectadas"] else ""))
    for a in r["avisos"]:
        print("  aviso:", a)
    print("saida:", r["saida"])


if __name__ == "__main__":
    main()
