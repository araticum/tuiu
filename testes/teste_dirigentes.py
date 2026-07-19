"""Suíte do impedimento de dirigente (MROSC).

Dizer a um cliente que o presidente dele está sancionado — por engano — é um
estrago sério e difícil de desfazer. Estes testes travam a defesa contra
homônimo, que é o risco central de buscar por NOME.

    py -3 -m pytest testes/teste_dirigentes.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ingest" / "transparencia"))

from regularidade_terceiro import _digitos_visiveis, _mesmo_nome, _nome_do_registro  # noqa: E402


@pytest.mark.parametrize("entrada,esperado", [
    ("***790718**", "790718"),
    ("123.456.789-01", "12345678901"),
    ("", ""), (None, ""), ("(sem documento)", ""),
])
def test_digitos_visiveis(entrada, esperado):
    assert _digitos_visiveis(entrada) == esperado


@pytest.mark.parametrize("a,b,igual", [
    ("JOÃO DA SILVA", "JOAO DA SILVA", True),        # acento não pode separar
    ("joão  da   silva", "JOAO DA SILVA", True),     # caixa e espaço extra
    ("JOÃO DA SILVA.", "JOAO DA SILVA", True),       # pontuação
    ("JOAO DA SILVA", "JOAO DA SILVA JUNIOR", False),  # sufixo é outra pessoa
    ("JOAO DA SILVA", "", False),
    ("", "", False),                                  # vazio nunca casa com vazio
])
def test_comparacao_de_nome(a, b, igual):
    assert _mesmo_nome(a, b) is igual


def test_nome_do_registro_procura_nos_formatos_da_api():
    assert _nome_do_registro({"sancionado": {"nome": "FULANO"}}) == "FULANO"
    assert _nome_do_registro({"pessoa": {"nome": "BELTRANO"}}) == "BELTRANO"
    assert _nome_do_registro({"outro": {"nome": "X"}}) == ""


def test_cpf_visivel_confirma_dentro_do_completo():
    """A regra de casamento: os dígitos que a Receita mostra têm que aparecer no
    documento do registro de sanção."""
    visiveis = _digitos_visiveis("***790718**")
    assert visiveis in _digitos_visiveis("123.790.718-45")
    assert visiveis not in _digitos_visiveis("999.999.999-99")
