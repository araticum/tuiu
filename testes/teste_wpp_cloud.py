"""Suíte do canal WhatsApp oficial (Cloud API) e da mensagem autossuficiente.

O que estes testes protegem, em ordem de dano:

1. **Formato de parâmetro de template.** A Meta recusa valor com quebra de
   linha, tabulação, mais de 4 espaços seguidos ou vazio (erro 132000). Como o
   corpo do evento vem de texto livre do Transferegov (parecer do órgão, razão
   social), um `\\n` no meio derruba o alerta inteiro — e derruba calado, no
   dia em que o prazo importava.
2. **Autossuficiência.** A mensagem tem que carregar instrumento, transição,
   prazo, próximo passo e exigência — mais o link da ficha. Se o contexto sumir,
   o operador recebe um aviso que não permite decidir nada; se o link divergir
   entre texto e template, o erro só aparece no celular de quem recebeu.
3. **Nada sai sem configuração.** Sem token/phone id o canal responde erro, não
   exceção — o evento segue na outbox.

Não toca a rede: tudo roda em DRYRUN. Não precisa de banco.

    py -3 -m pytest testes/teste_wpp_cloud.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import wpp_cloud  # noqa: E402
from app.notificador import link_cliente, mensagem, parametros_template  # noqa: E402


@pytest.fixture(autouse=True)
def _cloud_em_dryrun(monkeypatch):
    monkeypatch.setenv("TUIU_WPP_TOKEN", "TESTE")
    monkeypatch.setenv("TUIU_WPP_PHONE_ID", "000000")
    monkeypatch.setenv("TUIU_WPP_DRYRUN", "1")


EVENTO = {
    "id": 21, "cnpj": "60453032000174", "ente": "FUNDACAO FACULDADE DE MEDICINA",
    "dominio": "convenio_legado", "chave": "850704", "rotulo": "Convênio/CR 850704",
    "tipo": "mudanca", "de": "Prestação de Contas em Análise",
    "para": "Prestação de Contas em Complementação", "snapshot": "2026-07-25",
    "origem": None, "detalhe": None,
}
CONTEXTO = {
    "bola": "convenente", "prazo": "14/08/2026", "prazo_dias": "em 18d",
    "proximo_passo": "Enviar a complementação exigida",
    "exigencia": "Apresentar\nextrato bancário\tcompleto    e    a conciliação",
}


# ---------------------------------------------------------------- número
@pytest.mark.parametrize("bruto, esperado", [
    ("61999990000", "5561999990000"),      # celular sem DDI -> completa 55
    ("6133334444", "556133334444"),        # fixo sem DDI
    ("+55 (61) 99999-0000", "5561999990000"),
    ("5561999990000", "5561999990000"),    # já normalizado, não duplica o 55
    ("351912345678", "351912345678"),      # estrangeiro passa intacto
    ("", ""),
])
def test_normaliza_numero(bruto, esperado):
    assert wpp_cloud.normalizar_numero(bruto) == esperado


# ------------------------------------------------------------ parâmetro
@pytest.mark.parametrize("bruto", [
    "com\nquebra", "com\ttab", "com\r\nCRLF", "espaços          demais",
])
def test_parametro_nunca_leva_formato_recusado(bruto):
    limpo = wpp_cloud.limpar_parametro(bruto)
    assert "\n" not in limpo and "\r" not in limpo and "\t" not in limpo
    assert "     " not in limpo   # 5+ espaços seguidos


def test_parametro_vazio_vira_travessao():
    """Parâmetro em branco é recusado no envio — o alerta não pode morrer por isso."""
    for vazio in (None, "", "   ", "\n\n"):
        assert wpp_cloud.limpar_parametro(vazio) == "—"


def test_parametro_longo_e_truncado():
    limpo = wpp_cloud.limpar_parametro("x" * 900)
    assert len(limpo) <= wpp_cloud.LIMITE_PARAMETRO and limpo.endswith("…")


# ------------------------------------------------------------- template
def test_template_tem_cinco_parametros_todos_validos():
    params = parametros_template(EVENTO, CONTEXTO)
    assert len(params) == 5
    for p in params:
        limpo = wpp_cloud.limpar_parametro(p)
        assert limpo and limpo != "—" or p == "—"
        assert "\n" not in limpo


def test_template_carrega_o_que_decide():
    """O alerta precisa bastar-se: instrumento, transição, prazo, próximo passo,
    exigência — e o link da ficha."""
    params = parametros_template(EVENTO, CONTEXTO)
    junto = " ".join(params)
    for esperado in ("Convênio/CR 850704", "Prestação de Contas em Análise",
                     "Prestação de Contas em Complementação", "14/08/2026",
                     "Enviar a complementação exigida", "extrato bancário",
                     "FUNDACAO FACULDADE DE MEDICINA", "25/07/2026",
                     "cliente.html?doc=60453032000174"):
        assert esperado in junto, f"sumiu da mensagem: {esperado}"


def test_link_do_template_e_do_texto_sao_o_mesmo(monkeypatch):
    """Duas fontes de URL divergiriam caladas — o erro só apareceria no celular
    de quem recebeu. Por isso as duas saem de TUIU_CONSOLE_URL."""
    import importlib

    from app import notificador
    monkeypatch.setenv("TUIU_CONSOLE_URL", "https://outro.exemplo.net/")
    importlib.reload(notificador)
    try:
        esperado = "https://outro.exemplo.net/cliente.html?doc=60453032000174"
        assert notificador.link_cliente(EVENTO["cnpj"]) == esperado   # sem barra dupla
        assert esperado in notificador.parametros_template(EVENTO, CONTEXTO)[4]
        assert esperado in notificador.mensagem(EVENTO, CONTEXTO)
    finally:
        monkeypatch.delenv("TUIU_CONSOLE_URL", raising=False)
        importlib.reload(notificador)


def test_link_aponta_para_a_ficha_do_cliente():
    """Ficha, não mesa: a /mesa.html não lê query param e abriria o backlog
    inteiro da carteira em vez do caso avisado."""
    assert link_cliente("60453032000174").endswith("/cliente.html?doc=60453032000174")


def test_exigencia_com_quebra_de_linha_sobrevive_ao_envio():
    """O parecer do órgão vem com \\n e \\t do CSV — o caso que quebraria de verdade."""
    ok, detalhe = wpp_cloud.enviar_template("61999990000", parametros_template(EVENTO, CONTEXTO))
    assert ok and detalhe.startswith("DRYRUN ")
    payload = json.loads(detalhe[len("DRYRUN "):])
    assert payload["to"] == "5561999990000"
    assert payload["template"]["language"]["code"] == "pt_BR"
    for p in payload["template"]["components"][0]["parameters"]:
        assert p["type"] == "text"
        assert "\n" not in p["text"] and "\t" not in p["text"] and p["text"].strip()


@pytest.mark.parametrize("tipo, de, para, trecho", [
    ("mudanca", "Em execução", "Aguardando Prestação de Contas", "→"),
    ("novo", None, "Proposta/Plano de Trabalho Aprovado", "situação:"),
    ("incremento", "8", "11", "total agora: 11"),
])
def test_todos_os_tipos_de_evento_geram_template_valido(tipo, de, para, trecho):
    ev = {**EVENTO, "tipo": tipo, "de": de, "para": para}
    params = parametros_template(ev, {})
    assert len(params) == 5 and trecho in params[2]
    assert params[3].startswith("dados de")   # sem contexto, sobra a data — nunca vazio
    assert params[4].startswith("http")
    assert wpp_cloud.enviar_template("61999990000", params)[0]


def test_evento_de_inbox_tambem_vira_template():
    ev = {**EVENTO, "origem": "inbox", "rotulo": "Diligência recebida",
          "para": "Solicitamos complementação da prestação de contas",
          "detalhe": {"prazos": ["10/08/2026"]}}
    params = parametros_template(ev, {})
    assert len(params) == 5
    assert "e-mail" in params[2] and "10/08/2026" in params[3]
    assert params[4].startswith("http")


def test_marco_cumprido_nunca_vira_prazo_na_mensagem():
    """Marco `ok` (prestação JÁ entregue) tem data_limite no passado — a data da
    entrega. Anunciá-la como vencimento reencena o alarme falso de 19/07, quando
    o motor acusava atraso de 77% de quem tinha cumprido.

    O `contexto()` já filtra por farol; aqui se trava o efeito: um contexto de
    marco cumprido diz de quem é a bola, nunca 'vencido há N dias'.
    """
    cumprido = {"bola": "concedente", "proximo_passo": "Acompanhar a análise do órgão"}
    params = parametros_template(EVENTO, cumprido)
    assert "Bola com o concedente" in params[3]
    for proibido in ("vencido", "Prazo:", "vence hoje"):
        assert proibido not in params[3], f"marco cumprido não pode falar de {proibido}"
    assert "vencido" not in mensagem(EVENTO, cumprido)


# ---------------------------------------------------------------- travas
def test_sem_configuracao_devolve_erro_e_nao_levanta(monkeypatch):
    monkeypatch.delenv("TUIU_WPP_TOKEN", raising=False)
    monkeypatch.delenv("TUIU_WPP_DRYRUN", raising=False)
    assert not wpp_cloud.configurado()
    ok, detalhe = wpp_cloud.enviar_template("61999990000", ["a", "b", "c", "d", "e", "f"])
    assert not ok and "não configurada" in detalhe


@pytest.mark.parametrize("numero", ["", "abc", "---"])
def test_numero_invalido_nao_envia(numero):
    ok, detalhe = wpp_cloud.enviar_template(numero, ["a", "b", "c", "d", "e", "f"])
    assert not ok and "inválido" in detalhe


def test_template_sem_parametros_nao_envia():
    ok, detalhe = wpp_cloud.enviar_template("61999990000", [])
    assert not ok and "sem parâmetros" in detalhe


# ------------------------------------------------------- texto da outbox
def test_texto_da_outbox_tem_o_mesmo_conteudo_do_template():
    txt = mensagem(EVENTO, CONTEXTO)
    for esperado in ("FUNDACAO FACULDADE DE MEDICINA", "Convênio/CR 850704",
                     "→", "Prazo: 14/08/2026 (em 18d)", "Próximo passo:",
                     "Exigência do órgão:", "25/07/2026", "D-1",
                     "cliente.html?doc=60453032000174"):
        assert esperado in txt, f"sumiu da outbox: {esperado}"
