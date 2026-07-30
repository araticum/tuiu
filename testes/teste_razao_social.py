"""Suíte da razão social — conserta a exibição, nunca inventa dado.

Decisão do dono (30/07/2026): *"não validamos erros de plataforma, mesmo que
oficial"*, e a correção fica **só na apresentação** para a conferência contra a
origem seguir trivial.

O que estes testes protegem, na ordem em que doem:

1. **Não inventar acento.** Palavra fora do léxico sai sem acento. Acentuar por
   palpite erraria o nome registrado de uma pessoa jurídica — falsear dado é
   exatamente o que a regra recusa, e errar "para o bem" continua sendo errar.
2. **Não estragar o que já está certo.** Rótulo escrito à mão passa intacto.
3. **A dívida do léxico não fica invisível.** `pendencias()` entrega a lista.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest  # noqa: E402

from app.razao_social import LEXICO, exibir, pendencias  # noqa: E402


# ------------------------------------------------- o que ele conserta
@pytest.mark.parametrize("bruto,esperado", [
    ("FUNDACAO COORDENACAO DE PROJETOS,PESQUISAS E ESTUDOS TECNOLOGICOS",
     "Fundação Coordenação de Projetos, Pesquisas e Estudos Tecnológicos"),
    ("IRMANDADE DA SANTA CASA DE MISERICORDIA DE SAO PAULO",
     "Irmandade da Santa Casa de Misericórdia de São Paulo"),
    ("ASSOCIACAO DE APOIO AS POPULACOES DO SEMI ARIDO",
     "Associação de Apoio as Populações do Semi Árido"),
])
def test_conserta_caixa_e_acento_do_lexico(bruto, esperado):
    assert exibir(bruto) == esperado


def test_palavra_de_ligacao_fica_minuscula_no_meio_e_maiuscula_na_abertura():
    assert exibir("DE OLHO NO PROJETO").startswith("De ")
    assert " de " in exibir("INSTITUTO DE ARTE")


def test_sigla_nao_vira_palavra():
    """`UFMA` em caixa baixa seria pior do que o problema original."""
    assert "UFMA" in exibir("UNIVERSIDADE FEDERAL DO MARANHAO - UFMA")
    assert "SUS" in exibir("APOIO AO SUS")


def test_numeral_romano_sobrevive():
    assert exibir("HOSPITAL PIO XII").endswith("XII")


def test_virgula_ganha_espaco():
    assert "Projetos, Pesquisas" in exibir("PROJETOS,PESQUISAS")


# ------------------------------------------------- o que ele NÃO faz
def test_nao_inventa_acento_fora_do_lexico():
    """`CRIANCA` não está no léxico: sai "Crianca", não "Criança".

    Parece pior, e é melhor: acento adivinhado num nome registrado é dado
    falseado, que é exatamente o que a regra do dono recusa. A palavra aparece em
    `pendencias()` para virar entrada por decisão."""
    saida = exibir("ASSOCIACAO DE ASSISTENCIA A CRIANCA")
    assert "Crianca" in saida and "Criança" not in saida
    assert any(p["palavra"] == "CRIANCA" for p in pendencias("ASSOCIACAO A CRIANCA"))


def test_nao_reprocessa_rotulo_escrito_a_mao():
    """Rótulo nosso já vem correto; passar de novo só estragaria."""
    for rotulo in ("Águas Lindas de Goiás/GO — prefeitura (ente)",
                   "Assoc. das Pioneiras Sociais/DF — OSC",
                   "Cooperativa Lixo Não/SP — cooperativa"):
        assert exibir(rotulo) == rotulo


def test_nao_mexe_em_caixa_mista():
    """Só o padrão da plataforma (CAIXA ALTA) é o erro que se recusou a validar."""
    assert exibir("Instituto BR Arte") == "Instituto BR Arte"


def test_vazio_e_nulo_nao_explodem():
    assert exibir(None) == "" and exibir("") == "" and exibir("   ") == ""


def test_truncamento_da_origem_passa_intacto():
    """`DESENVOL` vem cortado da plataforma. Expandir seria adivinhar palavra
    inteira, não repor acento — risco muito maior, e fora do contrato."""
    assert "Desenvol" in exibir("FUNDO DE DESENVOL SOCIAL")


# ------------------------------------------------- a dívida visível
def test_pendencias_marca_suspeita_de_acento():
    p = {x["palavra"]: x["suspeita"] for x in pendencias("HOSPITAL DE CLINICAS DE LONDRINA")}
    assert p["CLINICAS"] is True, "-icas quase sempre leva acento"
    assert p["LONDRINA"] is False, "topônimo sem acento não é suspeita"


def test_pendencias_pega_ao_e_cedilha():
    """Os dois furos que a primeira heurística deixou passar calada."""
    assert any(x["palavra"] == "MARANHAO" and x["suspeita"] for x in pendencias("DO MARANHAO"))
    assert any(x["palavra"] == "CRIANCA" and x["suspeita"] for x in pendencias("A CRIANCA"))


def test_pendencias_nao_reclama_do_que_o_lexico_cobre():
    assert pendencias("FUNDACAO DE SAUDE") == []


def test_pendencias_ignora_rotulo_a_mao():
    assert pendencias("Águas Lindas de Goiás/GO — prefeitura (ente)") == []


# ------------------------------------------------- integridade do léxico
def test_lexico_so_tem_chave_em_caixa_alta_sem_acento():
    """Chave acentuada nunca casaria: a busca é pela forma que a plataforma manda."""
    import unicodedata
    for chave in LEXICO:
        assert chave == chave.upper(), chave
        assert not any(unicodedata.category(c) == "Mn"
                       for c in unicodedata.normalize("NFD", chave)), chave


def test_lexico_muda_de_fato_cada_entrada():
    """Entrada que não altera nada é ruído — e esconde erro de digitação."""
    for chave, valor in LEXICO.items():
        assert valor.upper() != chave or chave == "DR", f"{chave} -> {valor}"
