"""Suíte da pseudonimização — a trava que autoriza mandar texto para fora.

Decisão do dono (28/07): a redação vai para a DeepInfra, mas tratando o dado na
entrada para retirar e na saída para recompor. Isto aqui é a condição do envio,
não um detalhe de qualidade: se um identificador escapa, dado de terceiro sai da
casa — e é o tipo de coisa que não dá para desfazer depois.

O que estes testes travam:

1. **Nada de conhecido sobra.** Nome, CNPJ, CPF, e-mail e telefone somem, nas
   grafias em que de fato aparecem (o parecer escreve "Fundação X", o cadastro
   guarda "FUNDACAO X").
2. **A volta é fiel.** Recompor devolve o original, inclusive se o modelo
   "limpar" `[[X]]` para `[X]`.
3. **Marcador comido é detectado.** Modelo que perde um `[[CLIENTE]]` devolve
   texto que parece pronto e está furado.

    py -3 -m pytest testes/teste_anonimo.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.anonimo import mascarar, perdidos, recompor, vazou  # noqa: E402

CONHECIDOS = {"CLIENTE": "Fundação Faculdade de Medicina",
              "REPRESENTANTE": "Fabrizio Pellicelli"}

PARECER = (
    "A proposta da FUNDACAO FACULDADE DE MEDICINA, CNPJ 60.453.032/0001-74, "
    "foi colocada em diligência. O representante Fabrizio Pellicelli deve "
    "responder até 20/04/2026 pelo e-mail contato@fmusp.org.br ou (11) 3061-7000. "
    "Servidor responsável: CPF 123.456.789-01."
)


def test_nada_conhecido_sobra_no_texto():
    """A checagem que autoriza o envio."""
    saida, mapa = mascarar(PARECER, CONHECIDOS)
    assert vazou(saida, mapa) == []
    for proibido in ("FACULDADE DE MEDICINA", "60.453.032", "Pellicelli",
                     "fmusp.org.br", "123.456.789"):
        assert proibido not in saida, f"escapou: {proibido}"


def test_pega_o_nome_na_grafia_do_parecer_e_na_do_cadastro():
    """O cadastro tem "Fundação Faculdade de Medicina"; o parecer escreve tudo
    em caixa alta e sem acento. Cobrir só uma das grafias é máscara de teatro."""
    saida, _ = mascarar("A Fundação Faculdade de Medicina e a FUNDACAO FACULDADE DE MEDICINA",
                        CONHECIDOS)
    assert "Medicina" not in saida and saida.count("[[CLIENTE]]") == 2


def test_nome_longo_primeiro_para_nao_sobrar_pedaco():
    """Se o curto for trocado antes, o resto do nome longo fica em claro."""
    saida, _ = mascarar("FUNDACAO FACULDADE DE MEDICINA pede",
                        {"CURTO": "FUNDACAO", "CLIENTE": "FUNDACAO FACULDADE DE MEDICINA"})
    assert "FACULDADE" not in saida


def test_recompor_devolve_a_forma_CANONICA_nao_a_do_parecer():
    """`recompor` roda na RESPOSTA do modelo, nunca no texto de entrada — então
    a propriedade não é "volta idêntico", é "volta com o nome oficial".

    O parecer escreve "FUNDACAO FACULDADE DE MEDICINA" em caixa alta e sem
    acento; o marcador devolve o nome do cadastro, que é o que deve constar de
    um ofício. Ida e volta idênticas exigiriam um marcador por grafia, e aí o
    modelo leria duas entidades onde há uma.
    """
    saida, mapa = mascarar(PARECER, CONHECIDOS)
    volta = recompor(saida, mapa)
    assert "Fundação Faculdade de Medicina" in volta
    assert "60.453.032/0001-74" in volta and "Fabrizio Pellicelli" in volta
    assert "[[" not in volta


def test_volta_mesmo_se_o_modelo_limpar_o_colchete_duplo():
    """Modelo às vezes normaliza [[X]] para [X]; recusar por isso jogaria fora
    um texto bom."""
    _, mapa = mascarar(PARECER, CONHECIDOS)
    resposta = "Prezados, a [CLIENTE] informa que o CNPJ [CNPJ_1] está regular."
    volta = recompor(resposta, mapa)
    assert "Fundação Faculdade de Medicina" in volta and "60.453.032/0001-74" in volta


def test_marcador_comido_pelo_modelo_e_detectado():
    saida, mapa = mascarar(PARECER, CONHECIDOS)
    assert perdidos(saida, mapa) == []
    assert "[[CLIENTE]]" in perdidos("resposta sem o marcador do cliente", mapa)


def test_marcador_desconhecido_na_resposta_fica_como_esta():
    """Modelo que inventa [[FULANO]] não pode virar KeyError nem sumiço mudo."""
    _, mapa = mascarar(PARECER, CONHECIDOS)
    assert "[[INVENTADO]]" in recompor("texto com [[INVENTADO]]", mapa)


@pytest.mark.parametrize("cnpj", ["60.453.032/0001-74", "60453032000174"])
def test_cnpj_com_e_sem_pontuacao(cnpj):
    saida, mapa = mascarar(f"inscrita sob o nº {cnpj}.", {})
    assert cnpj not in saida and vazou(saida, mapa) == []


def test_mesmo_identificador_repetido_usa_um_marcador_so():
    saida, mapa = mascarar("CNPJ 60.453.032/0001-74 e de novo 60.453.032/0001-74", {})
    assert saida.count("[[CNPJ_1]]") == 2 and len(mapa) == 1


def test_texto_sem_nada_identificavel_passa_intacto():
    texto = "Apresentar o extrato bancário completo e a conciliação."
    saida, mapa = mascarar(texto, {})
    assert saida == texto and mapa == {}


@pytest.mark.parametrize("vazio", ["", None])
def test_entrada_vazia_nao_levanta(vazio):
    saida, mapa = mascarar(vazio, CONHECIDOS)
    assert saida == "" and mapa == {} and recompor(vazio, {}) == ""


def test_conhecido_vazio_e_ignorado():
    """Cliente sem representante cadastrado não pode virar marcador de string vazia,
    que substituiria em TODA posição do texto."""
    saida, mapa = mascarar("texto qualquer", {"REPRESENTANTE": "", "OUTRO": None})
    assert saida == "texto qualquer" and mapa == {}
