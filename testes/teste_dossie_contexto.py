"""Suíte do contexto do redator — completo, fiel e ancorado.

O primeiro rascunho real saiu genérico porque o modelo só via o parecer. O
SEGUNDO, com contexto, saiu pior: o modelo passou a **responder ao contexto** —
escreveu um item declarando ciência das regras de Pix numa resposta de fundação
de pesquisa em saúde, e outro dizendo que "tomou conhecimento dos tutoriais".

A lição está travada aqui: contexto irrelevante não é neutro, ele convida a
resposta errada. Mais contexto ≠ melhor; contexto **relevante e com papel
declarado** é que é.

    py -3 -m pytest testes/teste_dossie_contexto.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.dossie_contexto import citacoes_soltas  # noqa: E402

CONTEXTO = (
    "===== EXIGÊNCIA DO ÓRGÃO =====\n"
    "Apresentar a prestação nos termos do art. 96 da Portaria Conjunta nº 33/2023.\n"
    "===== ACERVO OFICIAL =====\n"
    "[1] O prazo de análise é de 60 dias, conforme art. 97, I."
)


# ------------------------------------------------- citação não ancorada
def test_citacao_que_veio_do_contexto_nao_e_solta():
    resposta = "Nos termos do art. 96 da Portaria Conjunta nº 33/2023, apresentamos."
    assert citacoes_soltas(resposta, CONTEXTO) == []


def test_citacao_inventada_e_flagrada():
    """A alucinação mais cara aqui: sai parecendo com o produto e vai assinada
    para um órgão que conhece a norma melhor que nós."""
    resposta = "Conforme a Lei nº 8.666/1993 e o art. 42, apresentamos."
    soltas = citacoes_soltas(resposta, CONTEXTO)
    assert any("8.666" in s for s in soltas) and any("42" in s for s in soltas)


def test_diferenca_de_grafia_nao_vira_falso_alarme():
    """"art. 96" e "Art 96" são a mesma citação — acusar isso treinaria o
    operador a ignorar o aviso."""
    assert citacoes_soltas("Conforme Art 96 e ARTIGO 97, I.", CONTEXTO) == []


def test_resposta_sem_citacao_nao_reclama():
    assert citacoes_soltas("Apresentamos os documentos solicitados.", CONTEXTO) == []


@pytest.mark.parametrize("vazio", ["", None])
def test_entrada_vazia_nao_levanta(vazio):
    assert citacoes_soltas(vazio, CONTEXTO) == [] and citacoes_soltas("art. 5º", vazio) != []


# ------------------------------------------------------ blocos e filtros
def test_pix_fica_fora_das_regras(monkeypatch):
    """Pix é de ENTE (art. 166-A) e saiu do escopo em 18/07. Mandar junto fez o
    modelo declarar ciência de multa diária de Pix num ofício de fundação de
    pesquisa em saúde."""
    from app import dossie_contexto as dc

    capturado = {}

    class _Con:
        def execute(self, sql, args=None):
            capturado["sql"] = sql
            return []

    dc._bloco_regra(_Con(), __import__("datetime").date(2026, 7, 28))
    assert "regime <> 'especiais'" in capturado["sql"]


def test_busca_o_acervo_pelo_PEDIDO_nao_pelo_parecer_inteiro(monkeypatch):
    """O preâmbulo burocrático domina a similaridade e traz trecho de "cadastro
    de colegiado" para uma exigência de prestação de contas."""
    from app import dossie_contexto as dc

    consultas = []
    monkeypatch.setitem(sys.modules, "app.guia", type(sys)("app.guia"))
    sys.modules["app.guia"].buscar = lambda q, k=8: consultas.append(q) or {"resultados": []}

    parecer = ("Salienta-se que, conforme o dispositivo supracitado, na fase de admissibilidade. "
               "Solicitamos que o proponente apresente o extrato bancário conciliado.")
    dc._bloco_norma(parecer)
    assert consultas and "extrato bancário" in consultas[0]
    assert "Salienta-se" not in consultas[0]
