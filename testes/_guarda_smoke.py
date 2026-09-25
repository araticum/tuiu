"""Trava dos smokes: script que apaga tabela inteira exige banco PRÓPRIO.

`smoke_eventos.py` roda `DELETE FROM entidades_estado` **sem WHERE** — 6.012
linhas em produção — e planta um destinatário curinga `'*'` no canal que fala
com o CLIENTE. Isso é correto para um banco descartável e catastrófico para o
banco real.

O problema é que ele **viaja para o host**: `ops/deploy_araticum.sh:36` põe
`testes` no tar, e lá `TUIU_DSN` aponta para produção. `pytest.ini` não coleta
`smoke_*`, então a única barreira era o nome do arquivo — e nome não impede
ninguém de digitar `python testes/smoke_eventos.py` numa sessão ssh.

A trava é dizer o banco NA MÃO, e ele tem que ser outro:

    TUIU_SMOKE_DSN=postgresql://postgres@localhost:5432/tuiu_smoke \
        py -3 testes/smoke_eventos.py
    py -3 testes/smoke_eventos.py postgresql://postgres@localhost:5432/tuiu_smoke

Recusar por padrão é a única forma que sobrevive ao descuido: quem tem pressa
não lê docstring, mas lê a mensagem de erro que o impediu.
"""

from __future__ import annotations

import os
import sys

# marcas do banco de produção — segunda camada, caso alguém exporte TUIU_DSN
# diferente na sessão e mesmo assim aponte para o host
MARCAS_DE_PRODUCAO = ("10.0.0.42", ":25432", "araticum.net")


def exigir_banco_de_teste() -> str:
    """Devolve o DSN descartável e o instala em `TUIU_DSN`. Ou sai, sem apagar nada.

    Chame ANTES de importar `app.db` — ele resolve o DSN no import.
    """
    alvo = (os.environ.get("TUIU_SMOKE_DSN")
            or (sys.argv[1] if len(sys.argv) > 1 and "://" in sys.argv[1] else "")).strip()
    ambiente = (os.environ.get("TUIU_DSN") or "").strip()

    if not alvo:
        sys.exit(
            "RECUSADO: este smoke apaga tabelas inteiras e não recebeu um banco próprio.\n"
            "  Passe um DSN descartável:  TUIU_SMOKE_DSN=postgresql://.../tuiu_smoke\n"
            "  ou como argumento:         py -3 " + sys.argv[0] + " postgresql://.../tuiu_smoke\n"
            "  (nunca o banco de trabalho — ele apaga entidades_estado sem WHERE)")
    if ambiente and alvo == ambiente:
        sys.exit(f"RECUSADO: o DSN passado é o MESMO de TUIU_DSN ({_mascarar(alvo)}).\n"
                 "  Um smoke destrutivo precisa de banco separado, não do banco de trabalho.")
    for marca in MARCAS_DE_PRODUCAO:
        if marca in alvo:
            sys.exit(f"RECUSADO: o DSN aponta para produção (contém '{marca}').")

    os.environ["TUIU_DSN"] = alvo
    print(f"[smoke] banco descartável: {_mascarar(alvo)}", flush=True)
    return alvo


def _mascarar(dsn: str) -> str:
    """Nunca imprime senha: DSN vai para log e log vai para o chat."""
    import re
    return re.sub(r"//[^@/]*@", "//***@", dsn)
