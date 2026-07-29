"""Suíte da TRIAGEM — o resumo do dia (correção de produto do Danilo, 27/07).

O que estes testes protegem, na ordem em que doem:

1. **Silêncio em dia sem ação.** Se nada exige o operador, nada é enviado.
   Mensagem diária de "não há nada" treina a pessoa a ignorar o canal, e aí o
   dia que importa passa batido junto.
2. **O que está com o ÓRGÃO não vira tarefa.** É a distinção que matou o alarme
   falso de 77% em 19/07; repeti-la aqui é o coração da triagem.
3. **O denominador não pode mentir.** "De N mudanças, K pedem você" só vale se N
   contar tudo — inclusive o que a mesa não mostra por estar `farol='ok'`. Foi
   assim que a contagem de "com o órgão" nasceu zerada.
4. **Parâmetro de template continua sendo uma linha.** Item com quebra de linha
   derruba a mensagem inteira na Meta (erro 132000).

    py -3 -m pytest testes/teste_resumo_diario.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import resumo_diario as rd  # noqa: E402

CONSOLE = "https://tuiu.araticum.net"


def _item(rank=1, cliente="FUNDACAO EXEMPLO", instrumento="850704", dias=18,
          passo="Montar e enviar a prestação de contas"):
    return {"cnpj": "00000000000191", "cliente": cliente, "instrumento": instrumento,
            "rotulo": f"Convênio/CR {instrumento}", "rank": rank, "faixa": "PC vencida",
            "dias": dias, "passo": passo, "de": "Em execução", "para": "Aguardando PC"}


def _r(acionaveis, mudancas=8, com_orgao=2, sem_marco=0):
    return {"dia": "2026-07-25", "mudancas": mudancas, "acionaveis": acionaveis,
            "com_orgao": com_orgao, "sem_marco": sem_marco, "mesa_aberta": 396}


# -------------------------------------------------- o dia quieto também fala
def test_dia_sem_acao_ainda_manda_mensagem(monkeypatch):
    """Silêncio não distingue "nada mudou" de "o pipe quebrou".

    Era a regra antiga (nada acionável = nada enviado) e ela custou caro: três
    dias de entrega recusada pela Meta passaram como se fossem dias quietos.
    Quem espera a mensagem não tem como saber a diferença — então ela sai.
    """
    monkeypatch.setattr(rd, "montar", lambda dia=None: _r([], mudancas=12, com_orgao=12))
    monkeypatch.setattr(rd, "frescor", lambda dia=None: {"conferido": True, "fresco": True})
    r = rd.enviar(previa=True)
    assert r["quieto"] is True
    assert r["texto"] and len(r["parametros"]) == 5
    assert all(p.strip() for p in r["parametros"]), "Meta recusa parâmetro vazio"


@pytest.mark.parametrize("f,esperado", [
    ({"conferido": False}, "não deu para confirmar"),
    ({"conferido": True, "fresco": False, "api": "2026-07-24"}, "não atualizou"),
    ({"conferido": True, "fresco": True}, "atualizou"),
])
def test_dia_quieto_diz_QUAL_silencio_e(monkeypatch, f, esperado):
    """"Nada mudou" e "a fonte não atualizou" são fatos diferentes.

    Tranquilidade medida vs. ignorância. Vender a segunda como a primeira é a
    mentira mais cara que este produto pode contar.
    """
    monkeypatch.setattr(rd, "montar", lambda dia=None: _r([], mudancas=0, com_orgao=0))
    monkeypatch.setattr(rd, "frescor", lambda dia=None: f)
    cabeca = rd.enviar(previa=True)["parametros"][0]
    assert esperado in cabeca.lower(), cabeca


def test_dia_com_acao_monta_a_mensagem(monkeypatch):
    monkeypatch.setattr(rd, "montar", lambda dia=None: _r([_item()]))
    r = rd.enviar(previa=True)
    assert r["motivo"] == "prévia" and r["texto"] and len(r["parametros"]) == 5


# ------------------------------------------------------------- o conteúdo
def test_cabeca_traz_o_numerador_e_o_denominador():
    """É a frase do Danilo: 'de 200 mudanças, 5 precisam de você'."""
    p = rd.parametros(_r([_item(), _item(instrumento="931212")]), CONSOLE)
    assert "8 mudança(s)" in p[0] and "2 pede(m) sua ação" in p[0]


def test_sobra_vira_travessao_nao_item_inventado():
    p = rd.parametros(_r([_item()]), CONSOLE)
    assert p[1].startswith("FUNDACAO") and p[2] == "—" and p[3] == "—"


def test_alem_do_topo_manda_para_a_mesa():
    p = rd.parametros(_r([_item(instrumento=str(i)) for i in range(7)]), CONSOLE)
    assert "E mais 4 na mesa." == p[4]


def test_quando_nada_sobra_diz_o_que_esta_com_o_orgao():
    p = rd.parametros(_r([_item()], com_orgao=5), CONSOLE)
    assert "5 mudança(s) estão com o órgão" in p[4]


@pytest.mark.parametrize("dias, esperado", [(-30, "vencido há 30d"), (0, "hoje"), (18, "em 18d")])
def test_prazo_legivel(dias, esperado):
    assert esperado in rd.linha_item(_item(dias=dias))


def test_item_cabe_em_uma_linha_e_no_limite():
    """Parâmetro com \n derruba a mensagem inteira na Meta (erro 132000)."""
    linha = rd.linha_item(_item(cliente="X" * 300, passo="Y" * 300))
    assert "\n" not in linha and len(linha) <= rd.LIMITE_ITEM


def test_texto_leva_o_link_da_mesa_nao_o_do_cliente():
    """O resumo é da carteira inteira; link de cliente levaria a um só."""
    t = rd.texto(_r([_item()]), CONSOLE)
    assert f"{CONSOLE}/mesa.html" in t and "cliente.html" not in t


def test_todo_parametro_sobrevive_a_limpeza_da_meta():
    from app import wpp_cloud
    for p in rd.parametros(_r([_item(cliente="Nome\ncom quebra")]), CONSOLE):
        limpo = wpp_cloud.limpar_parametro(p)
        assert limpo and "\n" not in limpo


# ----------------------------------------------------- faixas acionáveis
def test_vigilancia_nao_entra_na_triagem():
    """Faixa 5 (vigência encerrando) e 6 (acompanhar) são vigilância, não
    tarefa — entrariam às centenas e devolveriam a enxurrada."""
    assert 5 not in rd.FAIXAS_ACIONAVEIS and 6 not in rd.FAIXAS_ACIONAVEIS
    assert {0, 1, 8} <= rd.FAIXAS_ACIONAVEIS


def test_ordena_por_urgencia_e_depois_por_prazo():
    itens = [_item(rank=8, dias=5), _item(rank=0, dias=90), _item(rank=0, dias=2)]
    r = _r(sorted(itens, key=lambda i: (i["rank"], i["dias"])))
    p = rd.parametros(r, CONSOLE)
    assert "em 2d" in p[1] and "em 90d" in p[2] and "em 5d" in p[3]
