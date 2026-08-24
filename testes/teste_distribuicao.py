"""Suíte da distribuição da fila — repartir trabalho entre pessoas.

O que estes testes protegem, na ordem em que doem:

1. **A soma fecha.** Arredondar cada fatia perde ou inventa item; com 278 itens e
   5 pessoas, sumir com um é sumir com trabalho de alguém.
2. **Não toca em quem já tem dono.** Tirar item da mão de quem já começou é
   reequilíbrio, não distribuição — e fazer isso por acidente destrói a mesa.
3. **É determinístico.** "Por que este item é meu?" precisa ter resposta, e
   resposta que muda a cada execução não é resposta.
4. **A gravidade é repartida.** Cortar a fila ordenada em blocos daria todos os
   piores casos para a primeira fatia.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest  # noqa: E402

from app.distribuicao import _quotas_hare, _urgencia, planejar  # noqa: E402


def _cota(login, pct, nome=None):
    return {"login": login, "nome": nome or login, "percentual": pct,
            "ativo": True, "carga_atual": 0}


def _item(cnpj, instr, rank=1, dias=-10):
    return {"chave": f"prazo:{cnpj}:pc:{instr}:-", "cnpj": cnpj, "instrumento": instr,
            "rank": rank, "dias": dias, "faixa": "PC vencida", "cliente": f"Cliente {cnpj}",
            "responsavel": None}


# ------------------------------------------------------------ a soma fecha
@pytest.mark.parametrize("total", [1, 7, 100, 278, 1000])
def test_maior_resto_nunca_perde_nem_inventa_item(total):
    """Com 3 pessoas em 33,33% cada, arredondar perderia item em quase todo total."""
    q = _quotas_hare(total, [_cota("a", 33.34), _cota("b", 33.33), _cota("c", 33.33)])
    assert sum(q.values()) == total


def test_cota_desigual_e_respeitada():
    q = _quotas_hare(100, [_cota("a", 50), _cota("b", 30), _cota("c", 20)])
    assert q == {"a": 50, "b": 30, "c": 20}


def test_sobra_vai_para_a_maior_fracao_cortada():
    """10 itens em 3 partes iguais: 3,33 cada. Alguém tem que levar o décimo."""
    q = _quotas_hare(10, [_cota("a", 33.34), _cota("b", 33.33), _cota("c", 33.33)])
    assert sum(q.values()) == 10 and max(q.values()) == 4


def test_sem_elegivel_ou_sem_item_nao_explode():
    assert _quotas_hare(10, []) == {}
    assert _quotas_hare(0, [_cota("a", 100)]) == {}
    assert _quotas_hare(10, [_cota("a", 0)]) == {}


# --------------------------------------------------------- não toca em dono
def test_item_com_dono_fica_de_fora(monkeypatch):
    """A regra que mais protege a mesa."""
    import app.distribuicao as d
    itens = [_item("1", "100"), dict(_item("2", "200"), responsavel="ja_tem")]
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("a", 100)])
    monkeypatch.setattr(d, "sem_dono", lambda c=None: [i for i in itens if not i["responsavel"]])
    p = d.planejar()
    chaves = [i["chave"] for v in p["plano"].values() for i in v]
    assert chaves == ["prazo:1:pc:100:-"]


# --------------------------------------------------------- determinismo
def test_duas_execucoes_dao_o_mesmo_resultado(monkeypatch):
    import app.distribuicao as d
    itens = [_item(str(c), str(900 + c), rank=c % 3, dias=-c) for c in range(1, 31)]
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("a", 50), _cota("b", 30), _cota("c", 20)])
    monkeypatch.setattr(d, "sem_dono", lambda c=None: list(itens))
    um, dois = d.planejar(), d.planejar()
    assert {k: [i["chave"] for i in v] for k, v in um["plano"].items()} == \
           {k: [i["chave"] for i in v] for k, v in dois["plano"].items()}


def test_empate_nao_depende_da_ordem_do_dicionario(monkeypatch):
    """Cotas idênticas: o desempate é pelo login, não pela ordem de inserção."""
    import app.distribuicao as d
    monkeypatch.setattr(d, "sem_dono", lambda c=None: [_item("1", "100")])
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("z", 50), _cota("a", 50)])
    um = {k: [i["chave"] for i in v] for k, v in d.planejar()["plano"].items()}
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("a", 50), _cota("z", 50)])
    dois = {k: [i["chave"] for i in v] for k, v in d.planejar()["plano"].items()}
    assert um == dois


def test_quem_nao_recebeu_nao_aparece_no_plano(monkeypatch):
    """`len(dado[k])` num defaultdict CRIA a chave: o plano saía com listas vazias
    em nome de gente que não entrou na rodada, e a tela lia isso como
    "recebeu zero"."""
    import app.distribuicao as d
    monkeypatch.setattr(d, "sem_dono", lambda c=None: [_item("1", "100")])
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("a", 50), _cota("z", 50)])
    p = d.planejar()
    assert all(v for v in p["plano"].values()), "plano não pode ter entrada vazia"
    assert len(p["plano"]) == 1
    # o desvio, sim, mostra os dois — é ele que responde "e o fulano?"
    assert {x["login"] for x in p["desvio"]} == {"a", "z"}


# --------------------------------------------------- gravidade repartida
def test_ninguem_leva_todos_os_piores_casos(monkeypatch):
    """Sem intercalar, quem tem a primeira fatia recebe só faixa 0."""
    import app.distribuicao as d
    itens = [_item(str(c), str(900 + c), rank=0, dias=-1000 + c) for c in range(1, 11)]
    itens += [_item(str(c), str(900 + c), rank=3, dias=30) for c in range(11, 21)]
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("a", 50), _cota("b", 50)])
    monkeypatch.setattr(d, "sem_dono", lambda c=None: list(itens))
    p = d.planejar(agrupar_por_cliente=False)
    for login, recebidos in p["plano"].items():
        graves = sum(1 for i in recebidos if i["dias"] is not None and i["dias"] < -100)
        assert 3 <= graves <= 7, f"{login} levou {graves} dos 10 casos graves"


def test_gravidade_e_repartida_TAMBEM_agrupando(monkeypatch):
    """O modo padrão é agrupado, e era justamente ele que concentrava.

    Medido no dado real antes da correção: com cotas 50/30/20 sobre 163 itens, a
    primeira pessoa levou 18 dos 19 casos vencidos há mais de um ano e a terceira
    levou zero. A cota fechava exata e a carga era desumana — o defeito não
    aparecia em número nenhum do painel.
    """
    import app.distribuicao as d
    itens = [_item(f"c{c}", "1", rank=0, dias=-1000 + c) for c in range(20)]
    itens += [_item(f"d{c}", "1", rank=3, dias=60) for c in range(80)]
    monkeypatch.setattr(d, "_elegiveis",
                        lambda: [_cota("a", 50), _cota("b", 30), _cota("c", 20)])
    monkeypatch.setattr(d, "sem_dono", lambda c=None: list(itens))
    p = d.planejar(agrupar_por_cliente=True)
    graves = {k: sum(1 for i in v if i["dias"] is not None and i["dias"] < -900)
              for k, v in p["plano"].items()}
    assert len(graves) == 3, "todos precisam receber alguma coisa"
    assert min(graves.values()) >= 1, f"alguém ficou sem caso grave nenhum: {graves}"
    assert max(graves.values()) <= 12, f"alguém concentrou os casos graves: {graves}"


# --------------------------------------------------- agrupar por cliente
def test_cliente_nao_e_repartido_entre_pessoas(monkeypatch):
    """Espalhar um cliente obriga várias pessoas a aprender o mesmo cliente."""
    import app.distribuicao as d
    itens = [_item("111", str(i)) for i in range(6)] + [_item("222", str(i)) for i in range(6)]
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("a", 50), _cota("b", 50)])
    monkeypatch.setattr(d, "sem_dono", lambda c=None: list(itens))
    p = d.planejar(agrupar_por_cliente=True)
    for recebidos in p["plano"].values():
        assert len({i["cliente"] for i in recebidos}) == 1


def test_desvio_do_agrupamento_e_relatado_nao_escondido(monkeypatch):
    """Cliente grande demais estoura a cota. O número tem que aparecer."""
    import app.distribuicao as d
    itens = [_item("111", str(i)) for i in range(9)] + [_item("222", "0")]
    monkeypatch.setattr(d, "_elegiveis", lambda: [_cota("a", 50), _cota("b", 50)])
    monkeypatch.setattr(d, "sem_dono", lambda c=None: list(itens))
    p = d.planejar(agrupar_por_cliente=True)
    assert any(x["diferenca"] != 0 for x in p["desvio"]), "desvio real precisa aparecer"
    assert sum(x["recebe"] for x in p["desvio"]) == 10


# ----------------------------------------------------------- as travas
def test_sem_cota_nenhuma_nao_distribui(monkeypatch):
    import app.distribuicao as d
    monkeypatch.setattr(d, "_elegiveis", lambda: [])
    monkeypatch.setattr(d, "sem_dono", lambda c=None: [_item("1", "100")])
    p = d.planejar()
    assert p["ok"] is False and "cota" in p["erro"]


def test_soma_diferente_de_cem_e_recusada(monkeypatch):
    """A trava que impede distribuir 'quase tudo' e deixar resto órfão calado."""
    import app.distribuicao as d
    monkeypatch.setattr(d, "responsaveis_disponiveis",
                        lambda: [{"login": "a", "nome": "A"}, {"login": "b", "nome": "B"}])
    r = d.gravar_cotas({"a": 50, "b": 30})
    assert r["ok"] is False and "100%" in r["erro"]


def test_percentual_fora_da_faixa_e_recusado(monkeypatch):
    import app.distribuicao as d
    monkeypatch.setattr(d, "responsaveis_disponiveis", lambda: [{"login": "a", "nome": "A"}])
    assert d.gravar_cotas({"a": 120})["ok"] is False
    assert d.gravar_cotas({"a": -5})["ok"] is False


def test_nao_grava_cota_para_quem_nao_e_operador(monkeypatch):
    import app.distribuicao as d
    monkeypatch.setattr(d, "responsaveis_disponiveis", lambda: [{"login": "a", "nome": "A"}])
    r = d.gravar_cotas({"a": 50, "fantasma": 50})
    assert r["ok"] is False and "fantasma" in r["erro"]


def test_urgencia_ordena_do_mais_grave_para_o_menos():
    a, b = _item("1", "1", rank=0, dias=-500), _item("2", "2", rank=1, dias=-900)
    assert _urgencia(a) < _urgencia(b), "faixa manda antes do prazo"
