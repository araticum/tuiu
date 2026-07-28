"""Suíte da conferência de parcela — "a parcela saiu?".

Pergunta do dono (28/07): `parcela_prevista` era o único acionável sem peça, e
faltava definir qual documento conferir. A resposta veio da medição: o mapa da
g2 documenta a cadeia NE→DH→OP→OB, mas no recorte da carteira **três dos quatro
elos estão vazios** (empenho 0, documento-hábil 0, ordem-pagamento 0). Sobra o
extrato bancário — 405 lançamentos em 4 entes.

O que estes testes protegem:

1. **Ausência de dado não é ausência de fato.** Sem conta no recorte, a peça NÃO
   diz "não saiu" — diz que não dá para afirmar. Cobrar o órgão por engano custa
   a relação que o produto existe para cuidar.
2. **Crédito de valor diferente não é liberação.** Pode ser parcial ou parcelas
   somadas; a conciliação é do operador, que tem o contexto.
3. **A janela começa no mês da referência.** O cronograma não traz dia; dinheiro
   público atrasa, não adianta.

    py -3 -m pytest testes/teste_conferencia.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import conferencia  # noqa: E402

ITEM = {"id_proposta_cronograma_item": 77, "id_proposta": 555,
        "nr_ref_mes_data_especif": 6, "nr_ref_ano_data_especif": 2026,
        "vl_cronograma_desembolso": 510713.85, "origem_recurso": "Federal"}
CONTA = {"id_parceria_conta": 348, "id_parceria": 353, "nm_banco": "Banco do Brasil",
         "tx_numero": "697", "tx_conta": "861928", "nm_conta": "Conta Movimentação",
         "tx_descricao": "Ativa", "tx_detalhamento": None}
PARCERIA = {"id_parceria": 353, "id_proposta": 555}


def _monta(monkeypatch, extrato):
    dados = {"cronograma-desembolso": [ITEM], "parceria": [PARCERIA],
             "parceria-conta": [CONTA], "extrato-bancario": extrato}
    monkeypatch.setattr(conferencia, "_linhas", lambda doc, rota: dados.get(rota, []))


def _lanc(valor, quando="2026-06-22T00:00:00", tipo="Crédito"):
    return {"id_parceria_conta": 348, "in_transacao": tipo,
            "dt_movimento_lancamento_extrato_bancario": quando,
            "vl_lancamento_extrato_bancario": valor, "nm_tipo_operacao": "Movimento do Dia"}


def test_credito_no_valor_previsto_e_liberada(monkeypatch):
    _monta(monkeypatch, [_lanc(510713.85)])
    assert conferencia.conferir("123", 77)["veredito"] == "liberada"


def test_centavo_de_diferenca_ainda_e_a_parcela(monkeypatch):
    """Tarifa e arredondamento não podem virar cobrança indevida."""
    _monta(monkeypatch, [_lanc(510700.00)])
    assert conferencia.conferir("123", 77)["veredito"] == "liberada"


def test_valor_bem_diferente_pede_conciliacao_nao_veredito(monkeypatch):
    _monta(monkeypatch, [_lanc(100000.00)])
    d = conferencia.conferir("123", 77)
    assert d["veredito"] == "credito_divergente" and len(d["creditos"]) == 1


def test_sem_credito_nenhum_e_cobranca(monkeypatch):
    _monta(monkeypatch, [])
    assert conferencia.conferir("123", 77)["veredito"] == "sem_credito"


def test_sem_conta_no_recorte_nao_afirma_que_nao_saiu(monkeypatch):
    """A trava que mais protege: ausência de dado ≠ ausência de fato."""
    monkeypatch.setattr(conferencia, "_linhas",
                        lambda doc, rota: {"cronograma-desembolso": [ITEM]}.get(rota, []))
    d = conferencia.conferir("123", 77)
    assert d["veredito"] == "sem_conta"
    md = conferencia.markdown("123", 77)["markdown"]
    assert "não prova que o recurso não saiu" in md


def test_debito_nunca_conta_como_liberacao(monkeypatch):
    _monta(monkeypatch, [_lanc(510713.85, tipo="Débito")])
    assert conferencia.conferir("123", 77)["veredito"] == "sem_credito"


def test_credito_anterior_ao_mes_da_parcela_nao_conta(monkeypatch):
    """Dinheiro que entrou ANTES da referência é de outra parcela."""
    _monta(monkeypatch, [_lanc(510713.85, quando="2026-05-30T00:00:00")])
    assert conferencia.conferir("123", 77)["veredito"] == "sem_credito"


def test_credito_atrasado_conta(monkeypatch):
    """Dinheiro público atrasa; a janela é aberta para a frente."""
    _monta(monkeypatch, [_lanc(510713.85, quando="2026-09-02T00:00:00")])
    assert conferencia.conferir("123", 77)["veredito"] == "liberada"


@pytest.mark.parametrize("quebrado, erro", [
    ({**ITEM, "nr_ref_mes_data_especif": None}, "mês/ano"),
    ({**ITEM, "nr_ref_mes_data_especif": 13}, "mês/ano"),
])
def test_parcela_sem_referencia_util_informa(monkeypatch, quebrado, erro):
    monkeypatch.setattr(conferencia, "_linhas",
                        lambda doc, rota: {"cronograma-desembolso": [quebrado]}.get(rota, []))
    d = conferencia.conferir("123", 77)
    assert d["disponivel"] is False and erro in d["erro"]


def test_parcela_inexistente_nao_levanta(monkeypatch):
    _monta(monkeypatch, [])
    assert conferencia.conferir("123", 999)["disponivel"] is False


def test_peca_mostra_conta_valor_e_o_que_fazer(monkeypatch):
    _monta(monkeypatch, [_lanc(510713.85)])
    md = conferencia.markdown("123", 77)["markdown"]
    for esperado in ("Banco do Brasil", "861928", "R$ 510.713,85", "O que fazer", "proposta nº 555"):
        assert esperado in md, f"sumiu da peça: {esperado}"


def test_aviso_do_banco_aparece_quando_ha(monkeypatch):
    conta = {**CONTA, "tx_detalhamento": "Conta apta a receber créditos, mas não a débitos."}
    dados = {"cronograma-desembolso": [ITEM], "parceria": [PARCERIA],
             "parceria-conta": [conta], "extrato-bancario": []}
    monkeypatch.setattr(conferencia, "_linhas", lambda doc, rota: dados.get(rota, []))
    assert "não a débitos" in conferencia.markdown("123", 77)["markdown"]
