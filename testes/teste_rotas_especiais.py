"""As rotas da API /especiais usam HÍFEN — e o teste diz por quê.

Entre 27 e 28/08/2026 a API pública do Transferegov renomeou todas as rotas de
`/especiais` de `_` para `-` (`beneficiarios_especiais` → `beneficiarios-especiais`).
O recorte diário passou a receber 404 no primeiro elo e a cadeia ficou 27 dias parada
em silêncio. Este teste fixa a grafia no código (offline) e, quando se pede, confere
contra o OpenAPI ao vivo (`TUIU_TESTE_REDE=1`).
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
FONTE = (RAIZ / "ingest" / "transferegov_g2" / "recorte_ente.py").read_text(encoding="utf-8")
ROTAS = dict(re.findall(r'^ROTA_([A-Z_]+) = "([^"]+)"$', FONTE, flags=re.M))


def test_rotas_especiais_declaradas_com_hifen():
    assert set(ROTAS) == {"BENEFICIARIOS", "PLANOS_ACAO", "RELATORIOS_GESTAO", "PLANOS_TRABALHO"}
    for nome, rota in ROTAS.items():
        assert "_" not in rota and rota.endswith("-especiais"), f"{nome}: {rota!r} — a API usa hífen"


def test_nenhuma_rota_especial_antiga_sobrou_no_codigo():
    """Grafia antiga em string = chamada que volta 404."""
    antigas = re.compile(r'"(beneficiarios|planos_acao|relatorios_gestao|planos_trabalho)_especiais"')
    for arq in [RAIZ / "ingest" / "transferegov_g2" / "recorte_ente.py",
                RAIZ / "ferramentas" / "radar_comercial.py"]:
        assert not antigas.search(arq.read_text(encoding="utf-8")), arq.name


@pytest.mark.skipif(os.environ.get("TUIU_TESTE_REDE") != "1", reason="rede: TUIU_TESTE_REDE=1 para conferir ao vivo")
def test_rotas_existem_no_openapi_ao_vivo():
    req = urllib.request.Request(
        "https://api-publica.transferegov.gestao.gov.br/especiais/openapi.json",
        headers={"User-Agent": "tuiu-ingest/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        caminhos = set(json.load(r)["paths"])
    for rota in ROTAS.values():
        assert f"/{rota}" in caminhos, f"/{rota} sumiu do OpenAPI — a API renomeou de novo?"
