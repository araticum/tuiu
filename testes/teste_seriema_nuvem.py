"""Suíte do transporte do canal INTERNO (Seriema) — sessão própria vs Cloud API.

Casos herdados da sessão "WhatsApp API grupo notificações custo" (27/07/2026),
que resolveu este mesmo problema em paralelo por outro desenho. O que sobreviveu
da abordagem dela: o interruptor de transporte, o `falta_config()` que nomeia a
variável ausente, e o fan-out que falha se QUALQUER destino falhar.

O que estes testes protegem:

1. **Instalação existente não troca de transporte sozinha.** Um typo em
   `TUIU_SERIEMA_PROVIDER` não pode redirecionar aviso interno para outro lugar.
2. **A tela diz a verdade sobre o que falta.** Com dois transportes, texto fixo
   no painel vira mentira — e "não configurado" sem dizer o quê já custou tempo
   de operação antes.
3. **Aviso pela metade é aviso quebrado.** Se um dos números da equipe falhar, a
   entrega inteira é erro; ninguém pode achar que a equipe foi avisada.
4. **Nada de adivinhar campo.** No transporte de nuvem, enviar sem os campos do
   template é recusado — remontar os campos a partir do texto formatado
   adivinharia o nome do cliente num aviso operacional.

Não toca a rede: tudo em DRYRUN. Não precisa de banco.

    py -3 -m pytest testes/teste_seriema_nuvem.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import seriema  # noqa: E402

CAMPOS = ["Fundação Exemplo", "Convênio/CR 999999",
          "mudança de andamento: Em Análise → Em Complementação",
          "Prazo: 14/08/2026 (em 18d) · dados de 25/07/2026",
          "https://tuiu.araticum.net/cliente.html?doc=00000000000191"]


@pytest.fixture
def nuvem(monkeypatch):
    monkeypatch.setenv("TUIU_SERIEMA_PROVIDER", "cloud_api")
    monkeypatch.setenv("TUIU_SERIEMA_CLOUD_DESTINOS", "5561981366766, 5562999990000")
    monkeypatch.setenv("TUIU_WPP_TOKEN", "TESTE")
    monkeypatch.setenv("TUIU_WPP_PHONE_ID", "000000")
    monkeypatch.setenv("TUIU_WPP_DRYRUN", "1")


# ------------------------------------------------------------- transporte
def test_transporte_padrao_continua_a_sessao(monkeypatch):
    """Instalação existente não pode mudar de transporte sozinha."""
    monkeypatch.delenv("TUIU_SERIEMA_PROVIDER", raising=False)
    assert seriema.provedor() == seriema.PROVEDOR_SESSAO


@pytest.mark.parametrize("valor", ["cloudapi", "nuvem", "", "CLOUD-API", "x"])
def test_transporte_desconhecido_cai_para_sessao(monkeypatch, valor):
    monkeypatch.setenv("TUIU_SERIEMA_PROVIDER", valor)
    assert seriema.provedor() == seriema.PROVEDOR_SESSAO


def test_transporte_aceita_maiuscula(monkeypatch):
    monkeypatch.setenv("TUIU_SERIEMA_PROVIDER", "CLOUD_API")
    assert seriema.provedor() == seriema.PROVEDOR_NUVEM


# ------------------------------------------------------------ falta_config
def test_falta_config_nomeia_as_variaveis_da_nuvem(monkeypatch):
    monkeypatch.setenv("TUIU_SERIEMA_PROVIDER", "cloud_api")
    for n in ("TUIU_WPP_TOKEN", "TUIU_WPP_PHONE_ID", "TUIU_SERIEMA_CLOUD_DESTINOS"):
        monkeypatch.delenv(n, raising=False)
    falta = seriema.falta_config()
    assert falta and all(n in falta for n in
                         ("TUIU_WPP_TOKEN", "TUIU_WPP_PHONE_ID", "TUIU_SERIEMA_CLOUD_DESTINOS"))
    assert not seriema.configurado()


def test_falta_config_nomeia_as_variaveis_da_sessao(monkeypatch):
    monkeypatch.setenv("TUIU_SERIEMA_PROVIDER", "internal_session")
    for n in ("TUIU_SERIEMA_BASE_URL", "TUIU_SERIEMA_SECRET"):
        monkeypatch.delenv(n, raising=False)
    falta = seriema.falta_config()
    assert falta and "TUIU_SERIEMA_BASE_URL" in falta and "TUIU_SERIEMA_SECRET" in falta
    # não pode citar variável do OUTRO transporte — foi o que confundiu antes
    assert "TUIU_WPP" not in falta


def test_nuvem_completa_fica_configurada(nuvem):
    assert seriema.falta_config() is None and seriema.configurado()


def test_destinos_aceita_espaco_e_ignora_vazio(monkeypatch):
    monkeypatch.setenv("TUIU_SERIEMA_CLOUD_DESTINOS", " 5561981366766 , ,5562999990000,")
    assert seriema.destinos_nuvem() == ["5561981366766", "5562999990000"]


# ----------------------------------------------------------------- envio
def test_envio_monta_um_template_por_destino(nuvem):
    ok, detalhe = seriema.enviar_grupo("texto", chave_entrega="evento-1", parametros=CAMPOS)
    assert ok
    assert "5561981366766" in detalhe and "5562999990000" in detalhe
    assert detalhe.count("DRYRUN") == 2


def test_falha_em_um_destino_reprova_a_entrega_inteira(nuvem, monkeypatch):
    """Aviso que chega pela metade é aviso quebrado: ninguém pode achar que a
    equipe foi avisada porque metade recebeu."""
    monkeypatch.setenv("TUIU_SERIEMA_CLOUD_DESTINOS", "5561981366766,invalido")
    ok, detalhe = seriema.enviar_grupo("texto", chave_entrega="evento-1", parametros=CAMPOS)
    assert not ok and "1/2 falharam" in detalhe


def test_nuvem_sem_campos_recusa_em_vez_de_adivinhar(nuvem):
    """Remontar os campos a partir do texto formatado adivinharia o nome do
    cliente — num aviso operacional, errar isso é pior do que não mandar."""
    ok, detalhe = seriema.enviar_grupo("🔔 Fulano\nlinha 2\nlinha 3", chave_entrega="evento-1")
    assert not ok and "parametros" in detalhe


def test_envio_recusa_sem_config(monkeypatch):
    monkeypatch.setenv("TUIU_SERIEMA_PROVIDER", "cloud_api")
    monkeypatch.delenv("TUIU_WPP_TOKEN", raising=False)
    monkeypatch.delenv("TUIU_SERIEMA_CLOUD_DESTINOS", raising=False)
    ok, detalhe = seriema.enviar_grupo("texto", chave_entrega="e-1", parametros=CAMPOS)
    assert not ok and "não configurado" in detalhe and "TUIU_WPP_TOKEN" in detalhe


@pytest.mark.parametrize("texto, chave", [("", "e-1"), ("  ", "e-1"), ("texto", "")])
def test_guardas_basicas(nuvem, texto, chave):
    assert not seriema.enviar_grupo(texto, chave_entrega=chave, parametros=CAMPOS)[0]


def test_credencial_da_nuvem_e_a_mesma_do_canal_do_cliente(nuvem):
    """Um número, um token: prefixo próprio criaria duas verdades que divergem
    calado no dia em que uma for rotacionada."""
    from app import wpp_cloud
    assert wpp_cloud.configurado() and seriema.configurado()
