"""Suíte do webhook do WhatsApp — a única rota pública que aceita POST.

É a superfície mais exposta do console: a Meta precisa alcançá-la e não faz
login, então ela fica fora do gate de sessão. Tudo o que a protege é o que estes
testes travam.

1. **Fail-closed.** Sem App Secret configurado, RECUSA. Rota que aceita porque
   "ainda não configuramos" é rota aberta ao mundo — e o dia da configuração
   nunca é o dia do deploy.
2. **Assinatura sobre o corpo CRU.** Verificar o JSON reserializado validaria
   uma coisa e gravaria outra; um byte a mais no corpo tem que reprovar.
3. **Nenhum conteúdo de mensagem entra.** O texto vem no payload da Meta e é
   deliberadamente ignorado — a tabela nem tem coluna. Se alguém "melhorar" o
   extrator para guardar o texto, este teste cai.
4. **Handshake não vaza o token.** Token errado é 403 sem dica.

Não toca a rede. Só o último caso (janela de 24h) usa banco — validado por
mutação: repondo o `interval '%s hours'` original, ele reprova.

    py -3 -m pytest testes/teste_wpp_webhook.py -q
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import wpp_webhook  # noqa: E402

SEGREDO = "segredo-de-teste-do-app"

PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [{
        "id": "1380260874064611",
        "changes": [{
            "field": "messages",
            "value": {
                "messaging_product": "whatsapp",
                "metadata": {"display_phone_number": "556231902482",
                             "phone_number_id": "1163574160182752"},
                "contacts": [{"profile": {"name": "Pedro"}, "wa_id": "5561981366766"}],
                "messages": [{
                    "from": "5561981366766", "id": "wamid.ENTRADA1",
                    "timestamp": "1785000000", "type": "text",
                    # este texto NÃO pode sair daqui para lugar nenhum
                    "text": {"body": "assunto sigiloso do cliente"},
                }],
            },
        }],
    }],
}

PAYLOAD_STATUS = {
    "entry": [{"changes": [{"value": {"statuses": [
        {"id": "wamid.SAIDA1", "recipient_id": "5561981366766",
         "status": "delivered", "timestamp": "1785000100"},
        {"id": "wamid.SAIDA2", "recipient_id": "5561981366766",
         "status": "failed", "timestamp": "1785000200",
         "errors": [{"code": 131047, "title": "Re-engagement message"}]},
    ]}}]}],
}


def _assinar(corpo: bytes, segredo: str = SEGREDO) -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


@pytest.fixture
def com_segredo(monkeypatch):
    monkeypatch.setenv("TUIU_WPP_APP_SECRET", SEGREDO)
    monkeypatch.setenv("TUIU_WPP_VERIFY_TOKEN", "token-do-handshake")


# ------------------------------------------------------------ fail-closed
def test_sem_segredo_recusa_ate_assinatura_valida(monkeypatch):
    """A trava mais importante: enquanto não configurado, nada entra."""
    monkeypatch.delenv("TUIU_WPP_APP_SECRET", raising=False)
    corpo = json.dumps(PAYLOAD).encode()
    assert not wpp_webhook.configurado()
    assert not wpp_webhook.assinatura_confere(corpo, _assinar(corpo))


@pytest.mark.parametrize("cabecalho", [
    None, "", "sha256=", "abc", "sha1=deadbeef", "sha256=naoehex",
    "sha256=" + "0" * 64,
])
def test_assinatura_invalida_recusa(com_segredo, cabecalho):
    assert not wpp_webhook.assinatura_confere(json.dumps(PAYLOAD).encode(), cabecalho)


def test_assinatura_valida_aceita(com_segredo):
    corpo = json.dumps(PAYLOAD).encode()
    assert wpp_webhook.assinatura_confere(corpo, _assinar(corpo))


def test_um_byte_a_mais_no_corpo_reprova(com_segredo):
    """Por isso a verificação é sobre os BYTES recebidos, não sobre o JSON
    reserializado: reserializar valida uma coisa e grava outra."""
    corpo = json.dumps(PAYLOAD).encode()
    assinatura = _assinar(corpo)
    assert not wpp_webhook.assinatura_confere(corpo + b" ", assinatura)
    # mesmo dicionário, serialização diferente -> assinatura não vale
    assert not wpp_webhook.assinatura_confere(
        json.dumps(PAYLOAD, indent=2).encode(), assinatura)


def test_segredo_errado_reprova(com_segredo):
    corpo = json.dumps(PAYLOAD).encode()
    assert not wpp_webhook.assinatura_confere(corpo, _assinar(corpo, "outro-segredo"))


# --------------------------------------------------------------- extração
def test_conteudo_da_mensagem_nunca_e_extraido():
    """O texto está no payload e tem que morrer nele."""
    linhas = wpp_webhook.extrair(PAYLOAD)
    serializado = json.dumps(linhas, default=str)
    assert "sigiloso" not in serializado
    assert "text" not in serializado and "body" not in serializado
    # nem o nome do perfil, que também vem no envelope
    assert "Pedro" not in serializado


def test_extrai_o_metadado_que_responde_as_duas_perguntas():
    linha = wpp_webhook.extrair(PAYLOAD)[0]
    assert linha["tipo"] == "mensagem"
    assert linha["numero"] == "5561981366766"
    assert linha["wamid"] == "wamid.ENTRADA1"
    assert linha["carimbo"] is not None


def test_extrai_recibos_de_entrega_com_o_erro():
    linhas = wpp_webhook.extrair(PAYLOAD_STATUS)
    assert [l["status"] for l in linhas] == ["delivered", "failed"]
    assert all(l["tipo"] == "status" for l in linhas)
    assert linhas[1]["erro"] == "Re-engagement message"


@pytest.mark.parametrize("payload", [
    {}, {"entry": []}, {"entry": [{"changes": []}]},
    {"entry": [{"changes": [{"value": {}}]}]},
    {"entry": [{"changes": [{"value": {"messages": [{"id": "x"}]}}]}]},   # sem `from`
])
def test_payload_estranho_nao_levanta(payload):
    """A Meta manda eventos que não são mensagem (mudança de perfil, alerta de
    qualidade). Explodir aqui faria ela reentregar em loop."""
    assert wpp_webhook.extrair(payload) == []


def test_carimbo_invalido_nao_derruba_a_linha():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "5561981366766", "id": "w1", "timestamp": "não-é-número"}]}}]}]}
    linha = wpp_webhook.extrair(payload)[0]
    assert linha["carimbo"] is None and linha["numero"] == "5561981366766"


# -------------------------------------------------------------- handshake
def test_token_de_verificacao_vem_do_ambiente(com_segredo):
    assert wpp_webhook.token_verificacao() == "token-do-handshake"


def test_sem_token_configurado_nao_ha_handshake(monkeypatch):
    monkeypatch.delenv("TUIU_WPP_VERIFY_TOKEN", raising=False)
    assert wpp_webhook.token_verificacao() == ""


# ------------------------------------------------------- janela (com banco)
def test_janela_de_24h_respeita_a_borda():
    """Regressão de um bug SILENCIOSO: `interval '%s hours'` não parametriza —
    o placeholder fica dentro do literal, o Postgres lê o lixo como 1 hora e a
    janela encolhe de 24h para 1h. Medido no host: o corte não mudava com 1, 24
    ou 168. Nada quebra, só passa a dizer "fechada" para quem escreveu há duas
    horas — e o alerta some sem ninguém entender por quê.
    """
    from app.db import conectar, migrar

    migrar()
    numero, casos = "5599999999999", [(2, True), (23, True), (25, False)]
    try:
        for horas, esperado in casos:
            with conectar() as con:
                con.execute("DELETE FROM wpp_entrada WHERE numero=%s", (numero,))
                con.execute(
                    "INSERT INTO wpp_entrada (tipo, numero, wamid, recebido_em)"
                    " VALUES ('mensagem', %s, %s, now() - make_interval(hours => %s))",
                    (numero, f"wamid.teste{horas}", horas))
                con.commit()
            assert wpp_webhook.janela_aberta(numero) is esperado, \
                f"mensagem de {horas}h atrás: esperava janela_aberta={esperado}"
    finally:
        with conectar() as con:
            con.execute("DELETE FROM wpp_entrada WHERE numero=%s", (numero,))
            con.commit()
