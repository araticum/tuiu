"""Suíte das referências documentais — onde o papel de verdade está.

O parecer da g2 muitas vezes é só um ponteiro ("Parecer Técnico nº
184/2024-COPP/…/MS"); o documento mora fora do dado aberto. Medido no recorte de
28/07 sobre 31 parcerias: 16 têm processo SEI, 11 têm publicação no DOU, e
`nu_externo` nunca vem preenchido.

O que estes testes protegem:

1. **Link que exige captcha vem ROTULADO.** A consulta pública do SEI é
   captcha-gated (medido em sei.saude.gov.br e sei.mma.gov.br), e aqui não se
   quebra captcha em hipótese nenhuma. Entregar o link sem dizer isso faria
   alguém esperar por um robô que não existe.
2. **Formato do nº do processo.** A busca do SEI só aceita pontuado; mandar
   cru devolve "não encontrado" e o operador conclui que o processo não existe.
3. **A janela do INLABS é declarada.** ~180 dias (medido: 29/04 responde,
   29/01 não). Publicação mais velha não é "sem texto", é fora de alcance.

    py -3 -m pytest testes/teste_referencias.py -q
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.referencias import JANELA_INLABS_DIAS, _dou, _sei, em_texto, formatar_sei  # noqa: E402

HOJE = date(2026, 7, 28)


# ------------------------------------------------------------------- SEI
def test_formata_o_processo_como_a_busca_espera():
    assert formatar_sei("25000157186202484") == "25000.157186/2024-84"


@pytest.mark.parametrize("torto", ["", "123", None, "abc"])
def test_numero_torto_nao_e_forcado(torto):
    """Inventar formato para número estranho geraria link que não acha nada."""
    assert formatar_sei(torto) == str(torto or "")


def test_link_do_sei_diz_que_exige_captcha():
    r = _sei("25000157186202484")
    assert "captcha" in r["exige"].lower()
    assert r["url"].endswith("25000.157186/2024-84")
    assert r["orgao"] == "Ministério da Saúde"


def test_orgao_nao_mapeado_nao_gera_link_errado():
    """Melhor sem link do que um link para o SEI do órgão errado."""
    r = _sei("99999123456202401")
    assert r["url"] is None and "não mapeado" in r["nota"]


# ------------------------------------------------------------------- DOU
def test_publicacao_recente_e_recuperavel():
    pub = {"dt_publicacao": (HOJE - timedelta(days=30)).isoformat(),
           "ds_numero_dou": "120", "nr_pagina_dou": 44, "ds_documento_publicado": "Portaria X"}
    r = _dou(pub, HOJE)
    assert r["texto_recuperavel"] is True and r["exige"] is None


def test_publicacao_antiga_diz_que_esta_fora_de_alcance():
    """Fora da janela não é "sem texto" — é fora de alcance, e a diferença
    decide se alguém vai procurar ou desistir."""
    pub = {"dt_publicacao": (HOJE - timedelta(days=JANELA_INLABS_DIAS + 1)).isoformat(),
           "ds_numero_dou": "246", "nr_pagina_dou": 277, "ds_documento_publicado": "Portaria SE/MS 730"}
    r = _dou(pub, HOJE)
    assert r["texto_recuperavel"] is False and "INLABS" in r["exige"]
    assert r["url"], "sem texto automático, o link da edição ainda resolve para o humano"


def test_data_estranha_nao_levanta():
    r = _dou({"dt_publicacao": "sem data"}, HOJE)
    assert r["texto_recuperavel"] is False


def test_link_da_edicao_usa_data_brasileira():
    r = _dou({"dt_publicacao": "2024-12-27"}, HOJE)
    assert "data=27-12-2024" in r["url"]


# --------------------------------------------------------------- texto
def test_texto_para_o_redator_diz_onde_o_parecer_esta():
    linhas = em_texto([_sei("25000157186202484"),
                       _dou({"dt_publicacao": "2026-07-01", "ds_numero_dou": "1",
                             "nr_pagina_dou": 9, "ds_documento_publicado": "Portaria Y"}, HOJE)])
    junto = " ".join(linhas)
    assert "25000.157186/2024-84" in junto and "parecer integral" in junto
    assert "01/07/2026" in junto and "Portaria Y" in junto


def test_sem_referencia_devolve_lista_vazia():
    assert em_texto([]) == []
