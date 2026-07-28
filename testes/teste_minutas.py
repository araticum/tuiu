"""Rede de proteção da CAMADA DE AÇÃO (minutas).

O ofício de cobrança arma o art. 97 com um número; a resposta transcreve o que o
órgão pediu. Se a citação legal, os dias ou a numeração dos parágrafos quebrarem,
a peça vai errada para o concedente. Testa a composição PURA (sem banco)."""

import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
from app.minutas import (  # noqa: E402
    _cnpj_fmt, _hoje_extenso, _iso_br, montar_cobranca, montar_diligencia,
)

HOJE = date(2026, 7, 20)
CLI = {"nome": "ASSOCIACAO X", "municipio": "SALVADOR", "uf": "BA",
       "representante": "FULANO DE TAL", "papel_rep": "Presidente"}
DOC = "08929748000185"


def test_cnpj_formata():
    assert _cnpj_fmt("08929748000185") == "08.929.748/0001-85"
    assert _cnpj_fmt("123") == "123"  # entrada torta não é forçada


def test_iso_br():
    assert _iso_br("2025-10-01T16:08:48") == "01/10/2025"
    assert _iso_br(None) == "—"


def test_hoje_extenso():
    assert _hoje_extenso("SALVADOR", "BA", HOJE) == "SALVADOR/BA, 20 de julho de 2026"


def test_cobranca_cita_art97_e_os_dias():
    det = {"dias_em_analise": 292, "vencido_ha_dias": 232, "limite_informatizado": 60,
           "objeto": "Compostagem"}
    prop = {"ds_objeto": "Centro de compostagem", "nm_unidade_gestora": "FUNASA",
            "dt_envio_analise": "2025-10-01T10:00:00"}
    md = montar_cobranca(CLI, DOC, 22059, det, prop, HOJE)
    assert "art. 97, inciso I, e §1º, da Portaria Conjunta nº 33/2023" in md
    assert "vencido há 232 dias" in md
    assert "Decorridos 292 dias" in md
    assert "08.929.748/0001-85" in md
    assert "FUNASA" in md
    assert "Centro de compostagem" in md, "usa o objeto íntegro da g2, não o truncado do marco"
    assert "FULANO DE TAL" in md and "Presidente" in md
    assert "CPF: ____" in md, "LGPD: a assinatura não expõe CPF — é campo a preencher"


def test_cobranca_numera_paragrafo_final_conforme_ha_parecer():
    base = {"dias_em_analise": 100, "vencido_ha_dias": 40, "limite_informatizado": 60}
    sem = montar_cobranca(CLI, DOC, 1, base, {}, HOJE)
    com = montar_cobranca(CLI, DOC, 1,
                          {**base, "ultimo_parecer": {"fase": "Proposta", "resultado": "Em Análise"}},
                          {}, HOJE)
    assert "\n3. Diante do exposto" in sem, "sem parecer: o pedido é o item 3"
    assert "\n4. Diante do exposto" in com, "com parecer: a nota vira 3 e o pedido é 4"
    assert "unidade gestora concedente" in sem, "sem UG na proposta -> placeholder, não vazio"


def test_diligencia_transcreve_o_parecer():
    det = {"ultimo_parecer": {"fase": "Proposta", "parecer": "Anexar 3 orçamentos."}}
    md = montar_diligencia(CLI, DOC, 5, det, {"ds_objeto": "Obra"}, HOJE)
    assert "> Anexar 3 orçamentos." in md, "o que o órgão pediu entra citado (blockquote)"
    assert "Resposta à diligência — Proposta nº 5" in md
    assert "SALVADOR/BA, 20 de julho de 2026" in md


def test_diligencia_sem_parecer_nao_quebra():
    md = montar_diligencia(CLI, DOC, 5, {}, {}, HOJE)
    assert "consultar a diligência no Transferegov" in md


# --------------------------------------- cobrança do art. 97 no caso LEGADO
def test_cobranca_do_legado_lista_todas_as_prestacoes_paradas():
    """Peça irmã da do ciclo novo, não a mesma: aqui o marco é um AGREGADO por
    cliente (`piores[]`), não por proposta. Um ofício por prestação seria uma
    pilha de cartas idênticas para o mesmo órgão."""
    from datetime import date

    from app.minutas import montar_cobranca_analise

    cli = {"nome": "ENTIDADE EXEMPLO", "municipio": "Brasília", "uf": "DF",
           "representante": "Fulano de Tal", "papel_rep": "Presidente"}
    det = {"limite_dias": 180, "total": 17, "piores": [
        {"instrumento": "897963", "dias": 1124, "desde": "2023-06-30",
         "situacao": "PRESTACAO_CONTAS_ENVIADA_ANALISE"},
        {"instrumento": "909906", "dias": 1051, "desde": "2023-09-11",
         "situacao": "PRESTACAO_CONTAS_ENVIADA_ANALISE"},
    ]}
    md = montar_cobranca_analise(cli, "03686998000118", det, date(2026, 7, 28))

    assert "art. 97" in md and "180 dias" in md
    assert "897963" in md and "1124" in md
    assert "**17**" in md, "o total tem que aparecer, não só as piores"
    # a carta lista o que tem e DECLARA quantas ficaram de fora — omitir o resto
    # faria o órgão responder só as duas listadas
    assert "e outras 15" in md
    # enum cru do CSV não pode ir num ofício para o órgão
    assert "PRESTACAO_CONTAS_ENVIADA_ANALISE" not in md
    assert "CPF: ____" in md, "assinatura sem CPF preenchido (LGPD)"


def test_peca_de_cobre_os_marcos_que_tem_rascunho():
    from app.minutas import peca_de
    C = "https://tuiu.araticum.net"
    assert peca_de("analise_parada_concedente", "123", None, C)["tipo"] == "cobranca-analise"
    assert peca_de("proposta_parada", "123", "555", C)["tipo"] == "cobranca-art97"
    assert peca_de("complementacao_pendente", "123", "555", C)["tipo"] == "resposta-diligencia"
    assert peca_de("prestacao_contas", "123", "9", C)["url"].endswith("cliente.html?doc=123")
    # a parcela não pede ofício, pede CONFERIR se o dinheiro entrou — e o
    # documento é o extrato da conta (os outros elos da cadeia estão vazios)
    assert peca_de("parcela_prevista", "123", "9", C)["tipo"] == "conferencia-parcela"
    assert peca_de("tipo_que_nao_existe", "123", "9", C) is None
