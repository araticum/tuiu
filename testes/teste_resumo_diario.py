"""Suíte da TRIAGEM — o resumo do dia (correção de produto do Danilo, 27/07).

O que estes testes protegem, na ordem em que doem:

1. **Dia sem ação também fala, dizendo QUAL silêncio é.** A regra antiga era o
   contrário (nada acionável = nada enviado) e custou três dias de entrega
   recusada pela Meta passando por dias quietos. "Nada mudou", "a fonte não
   atualizou" e "o pipe quebrou" são fatos diferentes; o silêncio não desempata.
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


def _r(acionaveis, mudancas=8, com_orgao=2, sem_marco=0, aberto=None):
    aberto = aberto or []
    return {"dia": "2026-07-25", "mudancas": mudancas, "acionaveis": acionaveis,
            "aberto": aberto,
            "vencidos": sum(1 for i in acionaveis + aberto if (i["dias"] or 0) < 0),
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


# ------------------------------------------- notícia E saldo, não só notícia
def test_dia_sem_movimento_mostra_o_que_esta_aberto():
    """O falso negativo que o cliente reclamou.

    Pendência parada há três anos não muda de estado, logo não vira evento. A
    versão antiga mandava "nada exige sua ação" com a mesa cheia de prazo
    vencido — quanto mais esquecida a pendência, menos chance de aparecer.
    """
    r = _r([], mudancas=0, com_orgao=0, aberto=[_item(dias=-1137), _item(dias=-540)])
    p = rd.parametros(r, CONSOLE)
    assert "Nenhuma mudança hoje" in p[0] and "2 pendências seguem abertas" in p[0]
    assert p[1].startswith("FUNDACAO") and "vencido há 1137 dias" in p[1]
    assert "nada exige" not in " ".join(p).lower()


def test_nao_diz_que_nada_mudou_quando_a_mudanca_foi_do_orgao():
    """Caso real de 20/08: 6 mudanças, todas com o concedente, 0 acionáveis.

    "Nenhuma mudança hoje" seria falso — o que não houve foi mudança NOSSA."""
    p = rd.parametros(_r([], mudancas=6, com_orgao=6, aberto=[_item(dias=-90)]), CONSOLE)
    assert "Nenhuma mudança" not in p[0]
    assert "6 mudanças hoje, nenhuma exige sua ação" in p[0]


def test_diz_nenhuma_mudanca_so_quando_de_fato_nao_houve():
    p = rd.parametros(_r([], mudancas=0, com_orgao=0, aberto=[_item(dias=-90)]), CONSOLE)
    assert p[0].startswith("Nenhuma mudança hoje")


def test_noticia_vem_antes_do_saldo():
    """O que mudou hoje abre a lista; o aberto completa. Inverter enterraria a
    novidade sob anos de passivo."""
    novo, velho = _item(instrumento="111", dias=30), _item(instrumento="222", dias=-900)
    fila = rd.fila(_r([novo], aberto=[velho]))
    assert fila[0]["instrumento"] == "111" and fila[1]["instrumento"] == "222"


def test_item_que_mudou_hoje_nao_se_repete_no_saldo(monkeypatch):
    """`montar` monta as duas listas da mesma mesa: sem o corte, o item do dia
    apareceria duas vezes e o denominador mentiria."""
    fonte = (RAIZ / "backend" / "app" / "resumo_diario.py").read_text(encoding="utf-8")
    assert "ja_listado" in fonte and "chave not in ja_listado" in fonte


def test_cauda_diz_quantas_estao_vencidas():
    """É o número que mede a dívida — sem ele o saldo vira lista sem tamanho."""
    r = _r([_item(dias=-10)], aberto=[_item(dias=-20), _item(dias=5)])
    assert "2 estão com o prazo vencido" in rd.cauda_de(r)


def test_dia_realmente_vazio_continua_quieto(monkeypatch):
    """Quieto agora exige as DUAS listas vazias — mas quando estão, o caminho
    honesto de frescor continua valendo."""
    monkeypatch.setattr(rd, "montar", lambda dia=None: _r([], mudancas=0, com_orgao=0))
    monkeypatch.setattr(rd, "frescor", lambda dia=None: {"conferido": True, "fresco": True})
    assert rd.enviar(previa=True)["quieto"] is True


def test_com_saldo_aberto_NAO_e_dia_quieto(monkeypatch):
    monkeypatch.setattr(rd, "montar", lambda dia=None: _r([], mudancas=0, aberto=[_item(dias=-90)]))
    monkeypatch.setattr(rd, "frescor", lambda dia=None: {"conferido": True, "fresco": True})
    assert rd.enviar(previa=True)["quieto"] is False


# ------------------------------------------------------------- o conteúdo
def test_cabeca_traz_o_numerador_e_o_denominador():
    """É a frase do Danilo: 'de 200 mudanças, 5 precisam de você'."""
    p = rd.parametros(_r([_item(), _item(instrumento="931212")]), CONSOLE)
    # norma culta, não plural entre parênteses: o número é conhecido aqui, então
    # a concordância é decidível e "(s)/(m)" só empurra o trabalho para o leitor
    assert "8 mudanças" in p[0] and "2 pedem sua ação" in p[0]
    assert "(s)" not in p[0] and "(m)" not in p[0]


def test_sobra_vira_travessao_nao_item_inventado():
    p = rd.parametros(_r([_item()]), CONSOLE)
    assert p[1].startswith("FUNDACAO") and p[2] == "—" and p[3] == "—"


def test_alem_do_topo_manda_para_a_mesa():
    p = rd.parametros(_r([_item(instrumento=str(i)) for i in range(7)]), CONSOLE)
    assert p[4].startswith("Mais 4 na mesa.")


def test_quando_nada_sobra_diz_o_que_esta_com_o_orgao():
    p = rd.parametros(_r([_item()], com_orgao=5), CONSOLE)
    assert "5 mudanças estão com o órgão" in p[4]


@pytest.mark.parametrize("dias, esperado", [
    (-30, "vencido há 30 dias"), (-1, "vencido há 1 dia"),
    (0, "vence hoje"), (1, "em 1 dia"), (18, "em 18 dias"),
])
def test_prazo_legivel(dias, esperado):
    """Por extenso. `9d` não é português — e cabia inteiro."""
    assert esperado in rd.linha_item(_item(dias=dias))


def test_singular_nao_sai_com_verbo_no_plural():
    """Foi o que o WhatsApp entregou em 29/07: "1 mudança(s) estão com o órgão"."""
    p = rd.parametros(_r([_item()], com_orgao=1), CONSOLE)
    assert "1 mudança está com o órgão" in p[4]


def test_nenhum_parametro_traz_plural_hedgeado():
    """A varredura que faltava: o erro é silencioso e nenhum teste reclamava."""
    for r in (_r([_item()], mudancas=1, com_orgao=1), _r([_item(), _item("2")], com_orgao=9)):
        for campo in rd.parametros(r, CONSOLE):
            assert "(s)" not in campo and "(m)" not in campo and "(ns)" not in campo, campo


def test_cliente_longo_nao_e_cortado_no_meio_da_palavra():
    """`[:40]` produzia "PROJETOS,PESQUIS" — sílaba cortada e vírgula grudada."""
    linha = rd.linha_item(_item(cliente="FUNDACAO COORDENACAO DE PROJETOS,PESQUISAS E ESTUDOS"))
    assert "PESQUIS " not in linha and "PROJETOS,PESQUISAS" not in linha
    assert "PROJETOS, " in linha or linha.split(" ·")[0].endswith("…")


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
    assert "em 2 dias" in p[1] and "em 90 dias" in p[2] and "em 5 dias" in p[3]
