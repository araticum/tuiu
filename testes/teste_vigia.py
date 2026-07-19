"""Suíte da vigília normativa — a peça que impede a regra de apodrecer.

O produto vende prazo com base legal citada. Regra desatualizada não dá erro:
dá resposta errada com ar de certa. Estes testes travam o que fez a vigília
falhar em silêncio na primeira versão.

    py -3 -m pytest testes/teste_vigia.py -q
"""

from __future__ import annotations

import re
import sys

import pytest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ingest" / "normas"))

from vigia_dou import CABECALHO, TERMOS, _plano, _tag  # noqa: E402


def test_texto_normalizado_antes_de_casar():
    """A causa do primeiro fracasso: marcação inline parte a expressão e o
    regex no XML cru não casa — a vigília dizia 'nenhuma norma' com norma na
    frente."""
    cru = "<p>Portaria <i>Conjunta</i> MGI/<b>MF</b>/CGU nº 33</p>"
    assert not re.search(TERMOS["PC 33/2023"], cru, re.I), "no cru, falha (é o bug)"
    assert re.search(TERMOS["PC 33/2023"], _plano(cru), re.I), "normalizado, casa"


def test_plano_tira_marcacao_e_espaco():
    assert _plano("  <a href='x'>Portaria</a>\n\n  Conjunta  ") == "Portaria Conjunta"


def test_tag_aceita_atributo_na_abertura():
    """A Imprensa varia entre `<Identifica>` e `<Identifica id="...">`."""
    assert _tag("<Identifica>PORTARIA N 1</Identifica>", "Identifica") == "PORTARIA N 1"
    assert _tag('<Identifica id="a">PORTARIA N 2</Identifica>', "Identifica") == "PORTARIA N 2"
    assert _tag("<Ementa>Altera algo</Ementa>", "Identifica") is None


def test_cabecalho_serve_de_reserva_sem_identifica():
    texto = ("Portaria Conjunta MGI/MF/CGU Nº 45, DE 10 DE julho DE 2026 "
             "Altera a Portaria Conjunta MGI/MF/CGU nº 33, de 30 de agosto de 2023")
    m = CABECALHO.search(texto)
    assert m and "45" in m.group(1), "pega o cabeçalho, não a norma alterada"


@pytest.mark.parametrize("trecho,rotulo", [
    ("institui o Transferegov.br para", "transferegov"),
    ("transferências de recursos da União", "transferência da União"),
    ("convênios e contratos de repasse", "convênio/contrato de repasse"),
    ("Portaria Conjunta MGI/MF/CGU nº 33, de 30", "PC 33/2023"),
    ("Portaria Conjunta MGI/MF/CGU nº 28, de 21", "PC 28/2024"),
    ("Portaria Interministerial nº 424, de 2016", "PI 424/2016"),
    ("Decreto nº 11.531, de 16 de maio", "Decreto 11.531"),
    ("Lei nº 13.019, de 2014", "MROSC"),
])
def test_termos_pegam_o_que_importa(trecho, rotulo):
    assert re.search(TERMOS[rotulo], _plano(trecho), re.I)


def test_termo_nao_pega_norma_de_outro_assunto():
    """Peneira ampla, mas não a ponto de trazer o DOU inteiro."""
    fora = _plano("Portaria nº 12 que dispõe sobre horário de funcionamento do protocolo")
    assert not [r for r, p in TERMOS.items() if re.search(p, fora, re.I)]
