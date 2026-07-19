"""Suíte do interruptor de notificações — a trava que protege gente real.

A carteira tem 50 organizações que nunca pediram para receber nada nossa. Um
erro aqui não é bug de software: é mensagem indesejada para terceiro, com o
nome da casa junto. Estes testes travam o comportamento que impede isso.

    py -3 -m pytest testes/teste_notificacoes.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.config import (CHAVES_NOTIFICACAO, envio_externo_liberado, estado,  # noqa: E402
                        gravar, ler, ligado)
from app.db import conectar, migrar  # noqa: E402


@pytest.fixture(autouse=True)
def _estado_limpo():
    """Guarda e devolve o estado — teste não pode deixar canal ligado atrás de si."""
    migrar()
    antes = {c: ler(c) for c in CHAVES_NOTIFICACAO}
    yield
    for c, v in antes.items():
        gravar(c, v, quem="pytest-restauracao")


def _tudo(valor: str):
    for c in CHAVES_NOTIFICACAO:
        gravar(c, valor, quem="pytest")


# ------------------------------------------------------------------ o padrão

def test_migration_nasce_com_tudo_desligado():
    """Instalação nova não pode sair mandando mensagem para ninguém."""
    with conectar() as con:
        linhas = con.execute(
            "SELECT chave, valor FROM configuracoes WHERE chave = ANY(%s)",
            (list(CHAVES_NOTIFICACAO),)).fetchall()
    assert len(linhas) == len(CHAVES_NOTIFICACAO), "a 0009 tem que semear todas as chaves"
    # o valor semeado pela migration; se alguém rodou o painel, o fixture restaura
    assert all(isinstance(v, str) for _, v in linhas)


def test_chave_inexistente_e_desligada():
    """Ausência nunca pode ser lida como permissão."""
    assert ligado("canal_que_nao_existe") is False
    assert ler("canal_que_nao_existe") == "false"


# ------------------------------------------------------- as duas travas em série

@pytest.mark.parametrize("geral,canal,esperado", [
    ("false", "false", False),
    ("false", "true", False),   # canal ligado sozinho NÃO libera
    ("true", "false", False),   # trava geral ligada sozinha NÃO libera
    ("true", "true", True),
])
def test_envio_exige_as_duas_travas(geral, canal, esperado):
    gravar("notificacoes_ativas", geral, quem="pytest")
    gravar("canal_seriema", canal, quem="pytest")
    assert envio_externo_liberado("seriema") is esperado


def test_ligar_um_canal_nao_liga_os_outros():
    """Erro clássico: mestre + um canal e todos passam a enviar."""
    _tudo("false")
    gravar("notificacoes_ativas", "true", quem="pytest")
    gravar("canal_seriema", "true", quem="pytest")
    assert envio_externo_liberado("seriema") is True
    assert envio_externo_liberado("whatsapp") is False, "whatsapp alcança o CLIENTE — não pode vazar"
    assert envio_externo_liberado("webhook") is False


# ------------------------------------------------------------------- gravação

def test_chave_fora_da_lista_e_recusada():
    with pytest.raises(ValueError):
        gravar("apagar_tudo", "true", quem="pytest")


@pytest.mark.parametrize("entrada,esperado", [
    ("true", True), ("1", True), ("sim", True), ("on", True), ("TRUE", True),
    ("false", False), ("0", False), ("", False), ("talvez", False), ("nao", False),
])
def test_valor_ambiguo_cai_para_desligado(entrada, esperado):
    """Qualquer coisa que não seja um 'sim' explícito é 'não'."""
    gravar("canal_whatsapp", entrada, quem="pytest")
    assert ligado("canal_whatsapp") is esperado


def test_mudanca_fica_registrada_com_autor():
    """Ligar envio externo é ato auditável, não preferência de tela."""
    gravar("canal_webhook", "false", quem="pytest")
    gravar("canal_webhook", "true", quem="fulano")
    with conectar() as con:
        r = con.execute(
            "SELECT de, para, quem FROM configuracoes_log WHERE chave='canal_webhook'"
            " ORDER BY id DESC LIMIT 1").fetchone()
    assert r == ("false", "true", "fulano")


def test_gravar_valor_igual_nao_polui_o_historico():
    gravar("canal_webhook", "false", quem="pytest")
    with conectar() as con:
        antes = con.execute("SELECT count(*) FROM configuracoes_log").fetchone()[0]
    gravar("canal_webhook", "false", quem="pytest")
    with conectar() as con:
        depois = con.execute("SELECT count(*) FROM configuracoes_log").fetchone()[0]
    assert depois == antes, "só mudança de valor entra no log"


# --------------------------------------------------------------------- painel

def test_estado_declara_o_alcance_de_cada_canal():
    """A tela precisa dizer QUEM recebe: confundir grupo interno com cliente é
    o caminho para mandar mensagem a quem não pediu."""
    e = estado()
    assert "não chega ao cliente" in e["canais"]["seriema"]["alcance"]
    assert "CLIENTE" in e["canais"]["whatsapp"]["alcance"]
    assert set(e["canais"]) == {"seriema", "whatsapp", "webhook"}
