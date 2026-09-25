"""Suíte da norma culta — o que sai do sistema é português correto.

Regra da casa (dono, 29/07/2026): nada que chegue a uma pessoa sai fora da norma
culta. Estes testes existem porque o erro é silencioso: `"1 mudança(s) estão com
o órgão"` foi entregue no WhatsApp e nenhum teste reclamou.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest  # noqa: E402

from app.texto_br import arejar, encurtar, prazo_texto, qtd, verbo  # noqa: E402


# ------------------------------------------------------- concordância nominal
@pytest.mark.parametrize("n,esperado", [
    (1, "1 mudança"),
    (2, "2 mudanças"),
    (0, "0 mudanças"),      # zero é plural em português, não "0 mudança"
    (-1, "-1 mudança"),     # concorda pelo módulo
])
def test_qtd_concorda_com_o_numero(n, esperado):
    assert qtd(n, "mudança", "mudanças") == esperado


def test_qtd_nao_adivinha_plural_irregular():
    """O chamador passa os dois de propósito: `item -> itens` quebraria
    qualquer regra automática de `+s`, e errar calado é pior."""
    assert qtd(1, "item", "itens") == "1 item"
    assert qtd(9, "item", "itens") == "9 itens"


def test_verbo_concorda():
    assert verbo(1, "está", "estão") == "está"
    assert verbo(3, "está", "estão") == "estão"


# ---------------------------------------------------------------- o prazo
@pytest.mark.parametrize("dias,esperado", [
    (0, "vence hoje"),
    (1, "em 1 dia"),        # não "em 1 dias"
    (9, "em 9 dias"),
    (-1, "vencido há 1 dia"),
    (-233, "vencido há 233 dias"),
    (None, ""),             # sem prazo apurado, silêncio — não "sem prazo"
])
def test_prazo_por_extenso(dias, esperado):
    assert prazo_texto(dias) == esperado


def test_prazo_nunca_abrevia():
    """`(em 9d)` era o que saía. `9d` não é português."""
    assert "d)" not in prazo_texto(9) and "dias" in prazo_texto(9)


# ------------------------------------------------------------- o truncamento
def test_encurtar_nao_corta_palavra_no_meio():
    """`[:40]` produziu 'PROJETOS,PESQUIS'. Truncar é legítimo, cortar sílaba não."""
    r = encurtar("FUNDACAO COORDENACAO DE PROJETOS, PESQUISAS E ESTUDOS", 40)
    assert len(r) <= 40
    assert r.endswith("…") and "PESQUIS…" not in r
    # a vírgula sai junto: pontuação pendurada antes da reticência é o mesmo
    # descuido, um caractere adiante
    assert r.rstrip("…").split()[-1] in ("FUNDACAO", "COORDENACAO", "DE", "PROJETOS")


def test_encurtar_respeita_o_limite_com_a_reticencia():
    """O limite é da Meta, não nosso: 300 é 300 contando a reticência."""
    for limite in (1, 2, 5, 40, 300):
        assert len(encurtar("palavra " * 80, limite)) <= limite


def test_encurtar_nao_deixa_pontuacao_pendurada():
    assert not encurtar("Instituto de Arte, Cultura e Memoria", 22).rstrip("…").endswith(",")


def test_encurtar_devolve_o_texto_quando_cabe():
    assert encurtar("caber inteiro", 40) == "caber inteiro"


def test_encurtar_corta_palavra_unica_gigante():
    """Sem espaço não há fronteira: melhor palavra cortada que só reticência."""
    r = encurtar("A" * 100, 10)
    assert len(r) == 10 and r.endswith("…")


# ------------------------------------------------------------- a pontuação
def test_arejar_poe_espaco_depois_da_virgula():
    assert arejar("PROJETOS,PESQUISAS") == "PROJETOS, PESQUISAS"


def test_arejar_nao_inventa_acento():
    """Razão social vem sem acento do Transferegov. Corrigir nome registrado de
    pessoa jurídica seria falsear dado, não melhorar redação."""
    assert arejar("FUNDACAO") == "FUNDACAO"


def test_arejar_nao_duplica_espaco_ja_existente():
    assert arejar("PROJETOS, PESQUISAS") == "PROJETOS, PESQUISAS"
