"""Suíte do parse do parecer — o que a PLATAFORMA cobra de quem opera.

Escopo (dono, 28/07): o Tuiú operacionaliza o Transferegov, **não** a execução do
serviço. Daqui sai "o órgão exigiu X, responda até tal dia, senão arquiva" — o
mérito técnico do objeto é de quem recebeu a verba.

O defeito consertado: `ds_parecer` era cortado TRÊS vezes (600 no motor, 400 na
mesa, 300 no WhatsApp), sempre pelo COMEÇO. Sobrava o preâmbulo burocrático e
sumia o fim, que é onde mora a consequência. Num parecer real de 811 chars,
chegava "…em atendimento ao prazo previst" e sumia "resultará no ARQUIVAMENTO".

Os textos abaixo são pareceres REAIS da /analise-proposta (28/07/2026).

    py -3 -m pytest testes/teste_parecer.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.parecer import extrair, resumo  # noqa: E402

COMPLEMENTACAO = (
    "A proposta foi colocada em diligência para complementação. Solicitamos que o "
    "proponente realize os ajustes necessários conforme as orientações fornecidas e, "
    "em seguida, reenvie a proposta para continuidade da análise no prazo de 10 dias "
    "corridos, até o dia 20/04/2026, em atendimento ao prazo previsto no Art. 21 da "
    "Portaria GM/MMA nº 1250/2024.Salienta-se que, conforme previsto no dispositivo "
    "supracitado, na fase de admissibilidade caberá a solicitação de uma única "
    "diligência ao proponente, de modo que o não cumprimento dos ajustes solicitados "
    "pelo MMA ou o envio da proposta ajustada fora do prazo resultará no arquivamento "
    "da proposta.Uma vez arquivada a proposta, o convenente poderá reapresentar a "
    "proposta mediante novo cadastramento no módulo Gestão de Parcerias da Plataforma "
    "Transferegov.br."
)
REJEICAO_CURTA = ("A proposta foi rejeitada considerando o não atendimento à requisitos "
                  "obrigatórios conforme parecer em anexo.")


# ------------------------------------------------------------------ prazo
def test_extrai_prazo_em_dias_e_data():
    d = extrair(COMPLEMENTACAO)
    assert d["prazo_dias"] == 10 and d["prazo_contagem"] == "corridos"
    assert d["prazo_data"] == "20/04/2026"


def test_extrai_onde_sem_cortar_no_meio_da_palavra():
    assert extrair(COMPLEMENTACAO)["onde"] == "Gestão de Parcerias da Plataforma Transferegov"


# ----------------------------------------------------------- consequência
def test_consequencia_comeca_no_gatilho_nao_no_preambulo():
    """O defeito que este módulo existe para consertar: a frase certa começa em
    'Salienta-se que, conforme previsto no dispositivo supracitado…' e o desfecho
    fica lá no fim. Cortar pelo começo enterrava a notícia de novo."""
    c = extrair(COMPLEMENTACAO)["consequencia"]
    assert "arquivamento" in c
    assert not c.lstrip("…").startswith("Salienta-se")


def test_resumo_cabe_no_whatsapp_com_o_que_faz_agir():
    r = resumo(COMPLEMENTACAO, 300)
    assert len(r) <= 300
    for esperado in ("diligência", "10 dias", "20/04/2026", "arquivamento"):
        assert esperado in r, f"sumiu do resumo: {esperado}"


def test_ordem_e_a_da_decisao():
    """Pedido, prazo, consequência — o que fazer, até quando, o que acontece
    se não fizer."""
    r = resumo(COMPLEMENTACAO, 300)
    assert r.index("diligência") < r.index("Prazo:") < r.index("Se não cumprir:")


def test_o_corte_antigo_perdia_justamente_a_consequencia():
    """Regressão do comportamento anterior, para ninguém 'simplificar' de volta."""
    assert "arquivamento" not in COMPLEMENTACAO[:300]
    assert "arquivamento" in resumo(COMPLEMENTACAO, 300)


# --------------------------------------------------------------- degrada
def test_sem_campo_reconhecido_devolve_o_texto():
    """O parse pode falhar; a informação não pode sumir."""
    cru = "Texto sem nenhum padrão conhecido de prazo ou consequência."
    assert resumo(cru) == cru


def test_rejeicao_curta_passa_inteira():
    r = resumo(REJEICAO_CURTA, 300)
    assert "não atendimento à requisitos" in r and len(r) <= 300


@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_vazio_nao_levanta(vazio):
    assert resumo(vazio) == "" and extrair(vazio) == {}


def test_limite_e_respeitado_sempre():
    for limite in (80, 160, 300, 400):
        assert len(resumo(COMPLEMENTACAO, limite)) <= limite


@pytest.mark.parametrize("texto, dias, contagem", [
    ("no prazo de 10 dias corridos, até o dia 20/04/2026", 10, "corridos"),
    ("no prazo de 30 (trinta) dias úteis a contar", 30, "úteis"),
    ("no prazo de 5 dias, sem mais", 5, None),
])
def test_prazo_nao_confunde_dias_com_o_dia_da_data(texto, dias, contagem):
    """Regressão: a versão frouxa do regex casava o `dias` com o "dia" de "até o
    dia", achava o prazo e perdia a contagem — errando calada."""
    d = extrair(texto)
    assert d["prazo_dias"] == dias
    assert d.get("prazo_contagem") == contagem


def test_nao_inventa_campo():
    """Nada de prazo deduzido: só sai o que está escrito."""
    d = extrair(REJEICAO_CURTA)
    assert "prazo_dias" not in d and "prazo_data" not in d
