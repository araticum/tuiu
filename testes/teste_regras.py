"""Suíte do motor de regras — a rede de proteção do que o produto vende.

O Tuiú vende prazo com base legal citada. Um erro aqui não é bug de software:
é dano ao cliente (prazo perdido, prestação rejeitada, CEPIM). Estes testes
travam o comportamento dos pontos que mais custam se quebrarem.

Roda contra o banco real (as regras semeadas em db/0002 e db/0003) — de
propósito: assim o teste protege também o SEED, não só o código.

    py -3 -m pytest testes/teste_regras.py -q
"""

from __future__ import annotations

import gzip
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.db import conectar, migrar, regra_vigente  # noqa: E402
from app.motor_prazos import (CORTE_REGIME_NOVO, _farol, _marco_analise_parada,  # noqa: E402
                              _marcos_g2)
from app.prestacao import _regime  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _banco():
    migrar()


@pytest.fixture(scope="module")
def con():
    with conectar() as c:
        yield c


# ---------------------------------------------------------------- versionamento

def test_regra_resolve_pela_data_e_nao_pela_mais_nova(con):
    """A promessa central do motor: a regra aplicada é a VIGENTE NA DATA do
    instrumento. O saneamento mudou de 45 para 30 dias pela PC 45/2026
    (DOU 15/07/2026) — instrumento analisado antes disso segue com 45."""
    antes = regra_vigente(con, "prazo_saneamento_impropriedades", "completo_pc33", date(2026, 7, 10))
    depois = regra_vigente(con, "prazo_saneamento_impropriedades", "completo_pc33", date(2026, 7, 20))
    assert antes and depois, "as duas redações precisam estar semeadas"
    assert antes["valor"]["dias"] == 45, "antes de 15/07/2026 o saneamento era 45 dias"
    assert depois["valor"]["dias"] == 30, "a PC 45/2026 reduziu para 30 dias"
    assert "45" in antes["base_legal"] or "original" in antes["base_legal"].lower()
    assert "45/2026" in depois["base_legal"], "a base legal precisa citar a portaria que mudou"


def test_prazo_de_apresentacao_e_60_dias_nos_dois_regimes(con):
    hoje = date.today()
    for regime in ("completo_pc33", "legado_pi424"):
        r = regra_vigente(con, "prazo_prestacao_contas_apresentacao", regime, hoje)
        assert r, f"sem regra de apresentação para {regime}"
        assert r["valor"]["dias"] == 60
        assert "art. 96" in r["base_legal"] or "424" in r["base_legal"]


def test_guarda_documental_difere_por_regime(con):
    hoje = date.today()
    novo = regra_vigente(con, "guarda_documental", "completo_pc33", hoje)
    legado = regra_vigente(con, "guarda_documental", "legado_pi424", hoje)
    assert novo["valor"]["anos"] == 5
    assert legado["valor"]["anos"] == 10, "o regime legado guarda o dobro — erro caro se trocar"


def test_regra_fora_de_vigencia_nao_e_devolvida(con):
    """Defeso eleitoral tem janela fechada: fora dela, não pode vazar."""
    dentro = regra_vigente(con, "defeso_eleitoral", "geral", date(2026, 8, 1))
    fora = regra_vigente(con, "defeso_eleitoral", "geral", date(2026, 12, 1))
    assert dentro, "01/08/2026 está dentro do defeso (04/07 a 04/10)"
    assert fora is None, "dezembro está fora da janela e não pode devolver regra"


# ------------------------------------------------------------------- regimes

@pytest.mark.parametrize("assinatura,valor,esperado", [
    (date(2020, 5, 1), 5_000_000, "legado_pi424"),      # antes do corte: legado, valor irrelevante
    (date(2023, 8, 31), 100_000, "legado_pi424"),       # véspera do corte
    (date(2023, 9, 1), 5_000_000, "completo_pc33"),     # no corte, acima do teto
    (date(2024, 3, 10), 1_000_000, "simplificado_pc28"),  # abaixo do teto
    (date(2024, 3, 10), 1_576_882.20, "simplificado_pc28"),  # exatamente no teto: incluído
    (date(2024, 3, 10), 1_576_882.21, "completo_pc33"),   # um centavo acima: completo
])
def test_classificacao_de_regime(assinatura, valor, esperado):
    teto = 1_576_882.20
    regime, base = _regime(assinatura, valor, teto)
    assert regime == esperado, f"{assinatura} / {valor} deveria ser {esperado}"
    assert base, "todo regime precisa vir com a base legal declarada"


def test_corte_do_regime_novo_e_01_09_2023():
    """Data de virada do Decreto 11.531/2023 — se mudar, todo o histórico
    é reclassificado silenciosamente."""
    assert CORTE_REGIME_NOVO == date(2023, 9, 1)


def test_sem_valor_conhecido_cai_no_completo():
    """Na dúvida, o regime mais exigente — errar para o lado seguro."""
    regime, _ = _regime(date(2024, 1, 1), None, 1_576_882.20)
    assert regime == "completo_pc33"


# --------------------------------------------------------------------- farol

def test_farol_marca_limites_certos():
    hoje = date(2026, 7, 18)
    assert _farol(hoje - timedelta(days=1), hoje) == "vencido"
    assert _farol(hoje, hoje) == "atencao", "vence hoje ainda é atenção, não vencido"
    assert _farol(hoje + timedelta(days=90), hoje) == "atencao", "90 dias é o limite da atenção"
    assert _farol(hoje + timedelta(days=91), hoje) == "ok"
    assert _farol(None, hoje) == "acao_imediata", "sem data = agir agora"


# ------------------------------------------------- marcos do ciclo novo (g2)

def _escrever(dir_: Path, nome: str, linhas: list[dict]):
    dir_.mkdir(parents=True, exist_ok=True)
    with gzip.open(dir_ / f"{nome}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for l in linhas:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")


@pytest.fixture
def recorte(tmp_path):
    """Recorte sintético com um caso de cada coisa que o motor deriva."""
    hoje = date.today()
    p = tmp_path / "parcerias"
    _escrever(p, "proposta", [
        {"id_proposta": 1, "situacao_proposta": "Em Análise",
         "dt_envio_analise": (hoje - timedelta(days=200)).isoformat(), "ds_objeto": "parada antiga"},
        {"id_proposta": 2, "situacao_proposta": "Em Análise",
         "dt_envio_analise": (hoje - timedelta(days=70)).isoformat(), "ds_objeto": "parada recente"},
        {"id_proposta": 3, "situacao_proposta": "Em Análise",
         "dt_envio_analise": (hoje - timedelta(days=10)).isoformat(), "ds_objeto": "recente demais"},
        {"id_proposta": 4, "situacao_proposta": "Em Complementação", "ds_objeto": "bola com a gente"},
    ])
    _escrever(p, "meta-proposta", [
        {"id_proposta": 1, "nm_meta": "Meta 1", "etapas_proposta": [
            {"cd_etapa": "01.01", "nm_etapa": "Etapa vencida",
             "dt_fim": (hoje - timedelta(days=5)).isoformat()},
            {"cd_etapa": "01.02", "nm_etapa": "Etapa futura",
             "dt_fim": (hoje + timedelta(days=200)).isoformat()},
        ]}])
    _escrever(p, "cronograma-desembolso", [
        {"id_proposta_cronograma_item": 10, "id_proposta": 1,
         "nr_ref_mes_data_especif": 2, "nr_ref_ano_data_especif": 2024,
         "vl_cronograma_desembolso": 50000.0, "origem_recurso": "Concedente"},
    ])
    return tmp_path


def test_proposta_parada_e_sempre_do_orgao(recorte):
    """Proposta parada é cobrança do concedente — acompanhamento, nunca 'agir
    agora' por mais tempo que fique parada (regra do especialista, 07/2026): a
    bola é do órgão, então não escala à emergência do cliente."""
    marcos = _marcos_g2("00000000000000", "Teste", recorte, date.today())
    paradas = {m["detalhes"]["dias_em_analise"]: m for m in marcos if m["tipo"] == "proposta_parada"}
    assert 200 in paradas and paradas[200]["farol"] == "atencao", "bola do órgão não vira emergência do cliente"
    assert 70 in paradas and paradas[70]["farol"] == "atencao", ">=60 dias vira marco de cobrança"
    assert paradas[200]["detalhes"]["bola_com"] == "concedente"
    assert 10 not in paradas, "10 dias em análise é normal e não vira marco"


def test_complementacao_pendente_e_sempre_acao_imediata(recorte):
    marcos = _marcos_g2("00000000000000", "Teste", recorte, date.today())
    compl = [m for m in marcos if m["tipo"] == "complementacao_pendente"]
    assert len(compl) == 1
    assert compl[0]["farol"] == "acao_imediata", "a bola está com o convenente"
    assert compl[0]["data_limite"] is None


def test_parcela_prevista_vira_ultimo_dia_do_mes(recorte):
    marcos = _marcos_g2("00000000000000", "Teste", recorte, date.today())
    parcelas = [m for m in marcos if m["tipo"] == "parcela_prevista"]
    assert len(parcelas) == 1
    assert parcelas[0]["data_limite"] == date(2024, 2, 29), "fev/2024 é bissexto — 29, não 28"
    assert parcelas[0]["farol"] == "vencido"


def test_etapa_futura_nao_alarma_e_vencida_alarma(recorte):
    marcos = _marcos_g2("00000000000000", "Teste", recorte, date.today())
    etapas = {m["instrumento"]: m for m in marcos if m["tipo"] == "etapa_cronograma"}
    assert etapas["1/01.01"]["farol"] == "vencido"
    assert etapas["1/01.02"]["farol"] == "ok"


def test_todo_marco_carrega_base_legal(recorte):
    """Sem base legal o alerta não sustenta cobrança — é requisito de produto."""
    for m in _marcos_g2("00000000000000", "Teste", recorte, date.today()):
        assert m["base_legal"], f"marco {m['tipo']} sem base legal"
        assert m["descricao"], f"marco {m['tipo']} sem descrição"


# ------------------------------------ prazo que corre contra o CONCEDENTE (art. 97)

def _historico(dir_cnpj: Path, linhas: list[tuple]):
    leg = dir_cnpj / "legado"
    leg.mkdir(parents=True, exist_ok=True)
    with open(leg / "historico_situacao.csv", "w", newline="", encoding="utf-8-sig") as fh:
        fh.write("NR_CONVENIO;DIA_HISTORICO_SIT;HISTORICO_SIT;DIAS_HISTORICO_SIT\n")
        for nr, quando, sit, dias in linhas:
            fh.write(f"{nr};{quando};{sit};{dias}\n")


def test_analise_parada_so_conta_o_que_passou_do_prazo(con, tmp_path):
    """O art. 97 dá 180 dias (convencional) ao órgão. Abaixo disso não há o que
    cobrar; o corte usa o prazo MAIOR porque o dado não diz a modalidade."""
    _historico(tmp_path, [
        ("111", "01/01/2013 10:00:00", "PRESTACAO_CONTAS_EM_ANALISE", 4878),
        ("222", "01/01/2024 10:00:00", "PRESTACAO_CONTAS_ENVIADA_ANALISE", 200),
        ("333", "01/06/2026 10:00:00", "PRESTACAO_CONTAS_EM_ANALISE", 30),    # dentro do prazo
        ("444", "01/01/2020 10:00:00", "EM_EXECUCAO", 2000),                  # não é análise
        ("555", "01/01/2020 10:00:00", "AGUARDANDO_PRESTACAO_CONTAS", 2000),  # bola do CLIENTE
    ])
    marcos = _marco_analise_parada(con, "00000000000000", "Teste", tmp_path, date.today())
    assert len(marcos) == 1, "sai UM marco por cliente, não um por instrumento"
    d = marcos[0]["detalhes"]
    assert d["total"] == 2, "só 111 e 222 passaram dos 180 dias"
    assert d["piores"][0]["instrumento"] == "111", "ordena do mais parado para o menos"
    assert d["alem_da_prorrogacao"] == 1, "só o de 4878 dias passa de 360 (180 prorrogado)"


def test_analise_parada_cobra_o_orgao_e_nao_o_cliente(con, tmp_path):
    _historico(tmp_path, [("999", "01/01/2015 10:00:00", "PRESTACAO_CONTAS_EM_ANALISE", 3000)])
    m = _marco_analise_parada(con, "00000000000000", "Teste", tmp_path, date.today())[0]
    assert "art. 97" in m["base_legal"]
    assert "do órgão, não do convenente" in m["base_legal"], "a quem o prazo pertence é o ponto"
    assert m["farol"] == "atencao", "é alavanca de cobrança, não emergência do cliente"
    assert m["data_limite"] is None


def test_sem_historico_nao_inventa_marco(con, tmp_path):
    assert _marco_analise_parada(con, "00000000000000", "Teste", tmp_path, date.today()) == []


# ------------------------------------------------ parecer do orgao (analise-proposta)

def test_proposta_rejeitada_vira_marco_com_o_motivo(con, tmp_path):
    """Rejeitada não gerava marco nenhum — a proposta morria em silêncio. Com o
    parecer, a decisão de reapresentar deixa de ser adivinhação."""
    p = tmp_path / "parcerias"
    _escrever(p, "proposta", [
        {"id_proposta": 7, "situacao_proposta": "Rejeitada", "ds_objeto": "obra X"},
    ])
    _escrever(p, "analise-proposta", [
        {"id_proposta": 7, "dh_analise_proposta": "2024-01-01T10:00:00",
         "in_resultado_analise": "Rejeitada", "in_fase_analise": "Plano de Trabalho",
         "ds_parecer": "Planilha orcamentaria sem composicao de custos unitarios."},
        {"id_proposta": 7, "dh_analise_proposta": "2026-05-05T10:00:00",
         "in_resultado_analise": "Rejeitada", "in_fase_analise": "Plano de Trabalho",
         "ds_parecer": "PARECER MAIS RECENTE: memorial descritivo ausente."},
    ])
    marcos = _marcos_g2("00000000000000", "Teste", tmp_path, date.today())
    rej = [m for m in marcos if m["tipo"] == "proposta_rejeitada"]
    assert len(rej) == 1
    assert "MAIS RECENTE" in rej[0]["descricao"], "usa o parecer mais novo, não o primeiro"
    assert rej[0]["detalhes"]["ultimo_parecer"]["resultado"] == "Rejeitada"
    assert rej[0]["farol"] == "atencao", "é decisão a tomar, não prazo correndo"


def test_proposta_parada_diz_o_que_o_orgao_pediu(con, tmp_path):
    hoje = date.today()
    p = tmp_path / "parcerias"
    _escrever(p, "proposta", [
        {"id_proposta": 9, "situacao_proposta": "Em Análise",
         "dt_envio_analise": (hoje - timedelta(days=200)).isoformat(), "ds_objeto": "parada"},
    ])
    _escrever(p, "analise-proposta", [
        {"id_proposta": 9, "dh_analise_proposta": "2026-01-01T10:00:00",
         "in_resultado_analise": "Em Complementação", "in_fase_analise": "Proposta",
         "ds_parecer": "Justificar a escolha do fornecedor."},
    ])
    m = [x for x in _marcos_g2("00000000000000", "Teste", tmp_path, hoje)
         if x["tipo"] == "proposta_parada"][0]
    assert "Em Complementação" in m["descricao"], "cobrar sem saber o que pediram é pedido no escuro"
    assert m["detalhes"]["ultimo_parecer"]["parecer"].startswith("Justificar")


def test_proposta_parada_invoca_art97_pela_regra_vigente(con, tmp_path):
    """Parada em análise não é 'acompanhamento': é o art. 97 correndo contra o
    concedente (60d informatizado). Com `con`, o marco cita a regra vigente e
    diz há quantos dias o prazo LEGAL estourou — a munição da cobrança."""
    hoje = date.today()
    p = tmp_path / "parcerias"
    _escrever(p, "proposta", [
        {"id_proposta": 5, "situacao_proposta": "Em Análise",
         "dt_envio_analise": (hoje - timedelta(days=90)).isoformat(), "ds_objeto": "x"},
    ])
    m = [x for x in _marcos_g2("00000000000000", "Teste", tmp_path, hoje, con)
         if x["tipo"] == "proposta_parada"][0]
    assert "art. 97" in m["base_legal"]
    assert "do concedente, não do proponente" in m["base_legal"]
    assert m["detalhes"]["limite_informatizado"] == 60
    assert m["detalhes"]["vencido_ha_dias"] == 30, "90 − 60 = 30 dias além do art. 97"
    assert "vencido há 30 dias" in m["descricao"]
    assert m["farol"] == "atencao", "passou dos 60 mas não dos 180 — cobrança, não emergência do cliente"


def test_sem_analise_o_marco_continua_saindo(con, tmp_path):
    """Ausência de parecer não pode suprimir o marco — só empobrece a descrição."""
    p = tmp_path / "parcerias"
    _escrever(p, "proposta", [{"id_proposta": 11, "situacao_proposta": "Rejeitada"}])
    m = [x for x in _marcos_g2("00000000000000", "Teste", tmp_path, date.today())
         if x["tipo"] == "proposta_rejeitada"]
    assert len(m) == 1 and "sem parecer publicado" in m[0]["descricao"]


def test_purga_de_orfaos_nao_apaga_com_carteira_vazia(tmp_path):
    """Guarda: se a carteira falhar em carregar, apagar tudo transformaria erro
    de leitura em perda de dado."""
    import sys as _s
    _s.path.insert(0, str(RAIZ / "ingest" / "transferegov_g2"))
    from recorte_ente import _purgar_orfaos

    (tmp_path / "11111111111111").mkdir()
    (tmp_path / "22222222222222").mkdir()
    _purgar_orfaos(tmp_path, [])
    assert len(list(tmp_path.iterdir())) == 2, "carteira vazia não purga nada"
    _purgar_orfaos(tmp_path, ["11111111111111"])
    restantes = {d.name for d in tmp_path.iterdir()}
    assert restantes == {"11111111111111"}, "purga só quem saiu da carteira"
