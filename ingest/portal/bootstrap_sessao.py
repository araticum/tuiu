"""Bootstrap da sessão — o ÚNICO passo humano, e acontece uma vez só.

Por que existe: o gov.br protege o **login** com hCaptcha (gate humano
deliberado). Não se contorna. Então a autenticação inicial é feita por uma
pessoa, **uma vez**, e a partir daí quem é dono e mantenedor da sessão é o
container (ver `sessao_estado.py`): ele restaura, mantém viva, sobrevive ao
próprio restart e mede quanto tempo a sessão dura.

Não é "manter uma janela aberta": a janela pode ser fechada assim que o estado
for salvo.

Uso (na máquina do operador, com navegador visível):

    py -3 ingest/portal/bootstrap_sessao.py

Abre o Transferegov, espera você logar (gov.br), e ao detectar a área
autenticada salva `storage_state.json`. Depois é só levar esse arquivo para o
volume do container:

    scp data/sessao/storage_state.json pedro@10.0.0.42:~/
    ssh pedro@10.0.0.42 'docker run --rm -v tuiu_sessao:/d -v ~/storage_state.json:/s:ro \\
        alpine sh -c "cp /s /d/storage_state.json"'
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sessao_estado as E  # noqa: E402
from sessao_operador import LEITURAS, _parece_login  # noqa: E402

ALVO = "https://discricionarias.transferegov.sistema.gov.br/"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--espera-max", type=int, default=600,
                    help="segundos aguardando o login (default 10 min)")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    print("Abrindo o Transferegov. Faça o login gov.br nesta janela (inclusive o captcha).")
    print("Assim que a área autenticada aparecer, o estado é salvo e a janela pode fechar.\n")

    with sync_playwright() as pw:
        nav = pw.chromium.launch(headless=False)
        ctx = nav.new_context(locale="pt-BR")
        p = ctx.new_page()
        p.goto(ALVO, wait_until="domcontentloaded", timeout=60000)

        limite = time.time() + args.espera_max
        autenticado = False
        while time.time() < limite:
            time.sleep(5)
            try:
                if not _parece_login(p.url, p.title()):
                    # confirma acessando a área alvo
                    p.goto(ALVO, wait_until="domcontentloaded", timeout=45000)
                    time.sleep(3)
                    if not _parece_login(p.url, p.title()):
                        autenticado = True
                        break
            except Exception:  # noqa: BLE001 — janela pode estar navegando
                continue
            print(f"  aguardando login… ({int(limite - time.time())}s)")

        if not autenticado:
            print("\nNão detectei a área autenticada. Nada foi salvo.")
            nav.close()
            return 1

        E.marcar_bootstrap()
        meta = E.salvar(ctx)
        print(f"\nSessão capturada: {meta['cookies']} cookie(s) em {E.ARQ_ESTADO}")
        print("A partir daqui o container mantém a sessão sozinho. Pode fechar a janela.")
        nav.close()
        return 0


if __name__ == "__main__":
    sys.exit(main())
