"""Rede de proteção do MOAT: base_rates, funil e latência.

Estes motores classificam por padrão de string (SIT LIKE '%APROVAD%') e corte de
regime (data < 2023-09-01). Um rótulo renomeado na origem, ou uma borda de data
que desliza, faz o número sair ERRADO EM SILÊNCIO — o pecado "confiante-e-errado"
que o produto inteiro combate. Aqui a lógica REAL (o SQL, não uma cópia em Python)
roda contra um lake sintético em memória, com os limiares abaixados para a fixture
caber. Validado por mutação: mude um bucket e um teste fica vermelho.
"""

import sys
from pathlib import Path

import duckdb
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ingest" / "lake"))
import base_rates  # noqa: E402
import funil  # noqa: E402
import funil_acao  # noqa: E402
import latencia  # noqa: E402

LEGADO = "01/01/2015"   # antes do corte 2023-09-01
NOVO = "01/06/2024"     # depois do corte


def _con():
    """Lake sintético: só as colunas que os motores tocam."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE proposta (id_proposta INT, natureza_juridica TEXT,"
                " desc_orgao_sup TEXT, dia_proposta TEXT, sit_proposta TEXT)")
    con.execute("CREATE TABLE convenio (id_proposta INT, nr_convenio TEXT,"
                " dia_assin_conv TEXT, sit_convenio TEXT)")
    con.execute("CREATE TABLE historico_situacao (id_proposta INT, nr_convenio TEXT,"
                " historico_sit TEXT, dias_historico_sit TEXT, dia_historico_sit TEXT)")
    con.execute("CREATE TABLE programa (id_programa INT, acao_orcamentaria TEXT,"
                " nome_programa TEXT, ano_disponibilizacao TEXT)")
    con.execute("CREATE TABLE programa_proposta (id_programa INT, id_proposta INT)")
    return con


def _prop(con, idp, orgao, *, nat="Organização da Sociedade Civil",
          dia=LEGADO, sit=None):
    con.execute("INSERT INTO proposta VALUES (?,?,?,?,?)", [idp, nat, orgao, dia, sit])


def _conv(con, idp, nr, *, dia=LEGADO, sit=None):
    con.execute("INSERT INTO convenio VALUES (?,?,?,?)", [idp, nr, dia, sit])


# ----------------------------------------------------------------- base_rates

def test_base_rates_classifica_desfecho_e_ordem_ressalva_antes_de_sucesso():
    con = _con()
    buckets = (["Prestação de Contas Aprovada com Ressalvas"] * 2  # ressalva (vem 1º)
               + ["Prestação de Contas Aprovada"] * 3               # sucesso
               + ["Convênio Anulado"] * 4                           # morte
               + ["Em Execução"] * 1)                               # em_curso
    for i, sit in enumerate(buckets, 1):
        _prop(con, i, "MIN A")
        _conv(con, i, f"C{i}", sit=sit)
    linhas = base_rates.computar_em(con, min_n=1)
    assert len(linhas) == 1
    orgao, regime, n, suc, res, mor, curso, paradas, mediana = linhas[0]
    assert (orgao, regime, n) == ("MIN A", "legado_pi424", 10)
    assert (suc, res, mor, curso) == (30.0, 20.0, 40.0, 10.0), \
        "Aprovada com Ressalvas é ressalva, NÃO sucesso — a ordem do CASE importa"


def test_base_rates_separa_regime_pelo_corte():
    con = _con()
    _prop(con, 1, "MIN B"); _conv(con, 1, "C1", dia=LEGADO, sit="Aprovada")
    _prop(con, 2, "MIN B"); _conv(con, 2, "C2", dia=NOVO, sit="Aprovada")
    regimes = {r[1] for r in base_rates.computar_em(con, min_n=1)}
    assert regimes == {"legado_pi424", "novo_pc33"}, "o corte 2023-09-01 separa os dois"


def test_base_rates_prestacao_parada_mediana():
    con = _con()
    _prop(con, 1, "MIN C"); _conv(con, 1, "111", sit="Em Execução")
    for dias in (100, 200, 300):
        con.execute("INSERT INTO historico_situacao VALUES (?,?,?,?,?)",
                    [1, "111", "PRESTACAO_CONTAS_EM_ANALISE", str(dias), None])
    linha = base_rates.computar_em(con, min_n=1)[0]
    assert linha[7] == 3 and linha[8] == 200, "3 prestações paradas, mediana 200 dias"


def test_base_rates_so_osc():
    con = _con()
    _prop(con, 1, "MIN D", nat="Administração Pública Municipal")
    _conv(con, 1, "C1", sit="Aprovada")
    assert base_rates.computar_em(con, min_n=1) == [], "ente público não entra (produto é de OSC)"


# ----------------------------------------------------------------------- funil

def test_funil_classifica_aprovada_reprovada_em_curso():
    con = _con()
    sits = (["Proposta/Plano de Trabalho Aprovados"] * 6      # aprovada
            + ["Proposta/Plano de Trabalho Rejeitados"] * 4   # reprovada
            + ["Proposta/Plano de Trabalho em Análise"] * 5)  # em_curso (fora da taxa)
    for i, s in enumerate(sits, 1):
        _prop(con, i, "MIN E", dia=NOVO, sit=s)
    linha = funil.computar_em(con, min_linha=1)[0]
    orgao, regime, n_total, n_res, apr, rep, curso = linha
    assert (n_total, n_res) == (15, 10), "resolvidas = aprovadas + reprovadas, sem as em análise"
    assert (apr, rep) == (60.0, 40.0), "6/10 aprova, 4/10 reprova"


def test_funil_virou_convenio_conta_como_aprovada():
    con = _con()
    # sit diria 'em curso', mas existe convênio -> aprovada (virou_conv)
    _prop(con, 1, "MIN F", dia=NOVO, sit="Proposta/Plano de Trabalho em Análise")
    _conv(con, 1, "C1", dia=NOVO, sit="Em execução")
    linha = funil.computar_em(con, min_linha=1)[0]
    assert linha[4] == 100.0, "proposta que virou convênio conta como aprovada"


def test_funil_regime_novo_e_preditivo_pela_data_da_proposta():
    con = _con()
    _prop(con, 1, "MIN G", dia=LEGADO, sit="Aprovados")
    _prop(con, 2, "MIN G", dia=NOVO, sit="Aprovados")
    regimes = {r[1] for r in funil.computar_em(con, min_linha=1)}
    assert regimes == {"legado_pi424", "novo_pc33"}


# -------------------------------------------------------------------- latência

def _hist(con, idp, sit, quando):
    con.execute("INSERT INTO historico_situacao VALUES (?,?,?,?,?)",
                [idp, None, sit, None, quando])


def test_latencia_mede_par_enviada_ate_decisao():
    con = _con()
    _prop(con, 1, "MIN H", dia=NOVO)
    _hist(con, 1, "PROPOSTA_ENVIADA_ANALISE", "01/06/2024 10:00:00")
    _hist(con, 1, "PLANO_TRABALHO_APROVADO", "10/07/2024 10:00:00")  # +39 dias
    linha = latencia.computar_em(con, min_linha=1)[0]
    regime, orgao, n, mediana, p90, acima = linha
    assert (orgao, regime, n) == ("MIN H", "novo_pc33", 1)
    assert mediana == 39, "01/06 -> 10/07 = 39 dias"


def test_latencia_parseia_datetime_com_hora():
    """Regressão do gotcha real: DIA_HISTORICO_SIT é 'dd/mm/yyyy HH:MM:SS'.
    Parsear só a data zerava tudo (t0/t1 vazios) — este teste falha se voltar."""
    con = _con()
    _prop(con, 1, "MIN I", dia=NOVO)
    _hist(con, 1, "PROPOSTA_ENVIADA_ANALISE", "01/06/2024 23:59:59")
    _hist(con, 1, "PROPOSTA_REPROVADA", "01/09/2024 00:00:01")  # ~92 dias
    linhas = latencia.computar_em(con, min_linha=1)
    assert len(linhas) == 1, "com hora no timestamp o par tem que ser encontrado"
    assert linhas[0][5] == 100.0, "92 dias > 60 -> 100% acima do art. 97"


def test_latencia_ignora_proposta_sem_decisao():
    con = _con()
    _prop(con, 1, "MIN J", dia=NOVO)
    _hist(con, 1, "PROPOSTA_ENVIADA_ANALISE", "01/06/2024 10:00:00")  # nunca decidida
    assert latencia.computar_em(con, min_linha=1) == [], "sem decisão não há latência a medir"


# ----------------------------------------------------- funil por ação (drill-down)

def _prog(con, id_programa, acao, nome, dup=1):
    for _ in range(dup):  # dup simula a multiplicação (~405x) da tabela programa
        con.execute("INSERT INTO programa VALUES (?,?,?,?)", [id_programa, acao, nome, "2024"])

def _liga(con, id_programa, id_proposta):
    con.execute("INSERT INTO programa_proposta VALUES (?,?)", [id_programa, id_proposta])


def test_funil_acao_conta_proposta_distinta_apesar_da_duplicacao():
    con = _con()
    _prog(con, 10, "A001", "Programa Bom", dup=3)    # tabela programa multiplicada
    _prog(con, 20, "B002", "Programa Ruim", dup=3)
    for i in range(1, 4):                             # ação A001: 3 propostas, aprovadas
        _prop(con, i, "MIN K", dia=NOVO, sit="Aprovados"); _liga(con, 10, i)
    for i in range(4, 7):                             # ação B002: 3 propostas, reprovadas
        _prop(con, i, "MIN K", dia=NOVO, sit="Rejeitados"); _liga(con, 20, i)
    rows = {r[1]: r for r in funil_acao.computar_em(con, min_linha=1)}
    # (orgao, acao, nome, regime, n_total, n_res, pct_aprovada, pct_reprovada)
    assert rows["A001"][5] == 3 and rows["A001"][6] == 100.0, "3 propostas DISTINTAS (não 9 pela dup)"
    assert rows["B002"][6] == 0.0, "ação B002 reprova 100%"
    assert rows["A001"][2] == "Programa Bom", "rótulo do programa"


def test_funil_acao_ignora_acao_placeholder():
    con = _con()
    _prog(con, 30, "00000000", "sem ação")
    for i in range(1, 4):
        _prop(con, i, "MIN L", dia=NOVO, sit="Aprovados"); _liga(con, 30, i)
    assert funil_acao.computar_em(con, min_linha=1) == [], "ação-placeholder 00000000 fica de fora"


def test_funil_acao_limpa_mojibake_do_nome():
    assert funil_acao._limpar_nome("ESTRUTURA??O DE UNIDADES") == "ESTRUTURAO DE UNIDADES"
    assert funil_acao._limpar_nome("ATEN��O") == "ATENO"
    assert funil_acao._limpar_nome("  Programa X  ") == "Programa X"
