"""Suíte da atribuição — de quem é o item, decidido ANTES do trabalho.

`fila_status` já guardava `operador`, mas isso é **pegada**: quem mexeu por
último, e só existe depois que alguém age. Foi por isso que a tabela estava com
**0 linhas** enquanto `fila_visto` tinha 757: as pessoas abriam a mesa,
trabalhavam, e não havia nada a marcar antes de terminar.

Uma mesa de trabalho precisa dizer "isto é seu" antes. Sem isso não existe
"minha fila", ninguém sabe se um item está coberto ou esquecido, e dois
operadores podem tocar o mesmo convênio sem se ver.

O que estes testes protegem, na ordem em que doem:

1. **Dono fantasma não entra.** Item que parece coberto e não está é pior que
   item sem dono, porque ninguém procura por ele.
2. **Atribuir não é começar.** Mexer no `status` aqui mentiria sobre o andamento
   de tudo que foi só distribuído.
3. **Quem atribuiu é auditoria**, então vem da sessão e nunca do corpo.

    py -3 -m pytest testes/teste_atribuicao.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.db import conectar, migrar  # noqa: E402
from app.fila import atribuir, responsaveis  # noqa: E402

LOGIN = "pytest_dono"
CHAVE = "pytest:chave:1"


@pytest.fixture(autouse=True)
def _limpo():
    migrar()
    def _apaga():
        with conectar() as con:
            con.execute("DELETE FROM fila_status WHERE chave LIKE 'pytest:%%'")
            con.execute("DELETE FROM usuarios WHERE login LIKE 'pytest_%%'")
            con.commit()
    _apaga()
    with conectar() as con:
        con.execute("INSERT INTO usuarios (login, nome, senha_hash, ativo, papel)"
                    " VALUES (%s,%s,%s,true,'operador')", (LOGIN, "Dono de Teste", "x"))
        con.commit()
    yield
    _apaga()


def _linha(chave=CHAVE):
    with conectar() as con:
        return con.execute(
            "SELECT responsavel, status, atribuido_por FROM fila_status WHERE chave=%s",
            (chave,)).fetchone()


# ------------------------------------------------------- dono fantasma não entra
def test_recusa_quem_nao_e_usuario_do_console():
    """Atribuir para texto livre criaria item que PARECE coberto e não está."""
    r = atribuir(CHAVE, "fulano_que_nao_existe", quem="pedro")
    assert r["ok"] is False and "não é usuário ativo" in r["erro"]
    assert _linha() is None, "recusa não pode gravar nada"


def test_recusa_usuario_inativo():
    with conectar() as con:
        con.execute("UPDATE usuarios SET ativo=false WHERE login=%s", (LOGIN,))
        con.commit()
    assert atribuir(CHAVE, LOGIN, quem="pedro")["ok"] is False


def test_chave_vazia_nao_grava():
    assert atribuir("", LOGIN, quem="pedro")["ok"] is False


# ------------------------------------------------------- atribuir não é começar
def test_atribuir_nao_mexe_no_status():
    """"Tem dono" e "está andando" são estados diferentes, e a mesa precisa
    enxergar os dois — marcar `em_andamento` na distribuição apagaria a
    distinção e faria a produtividade contar trabalho que não começou."""
    assert atribuir(CHAVE, LOGIN, quem="pedro")["ok"] is True
    responsavel, status, _ = _linha()
    assert responsavel == LOGIN and status == "aberto"


def test_atribuir_preserva_status_ja_existente():
    from app.fila import triar
    triar(CHAVE, "em_andamento", nota=None, operador="pedro")
    atribuir(CHAVE, LOGIN, quem="pedro")
    responsavel, status, _ = _linha()
    assert responsavel == LOGIN and status == "em_andamento", "atribuir não reabre item"


def test_devolver_para_a_mesa():
    atribuir(CHAVE, LOGIN, quem="pedro")
    assert atribuir(CHAVE, None, quem="pedro")["ok"] is True
    assert _linha()[0] is None


def test_reatribuir_troca_o_dono():
    atribuir(CHAVE, LOGIN, quem="pedro")
    with conectar() as con:
        con.execute("INSERT INTO usuarios (login, nome, senha_hash, ativo, papel)"
                    " VALUES ('pytest_dono2','Outro','x',true,'operador')")
        con.commit()
    atribuir(CHAVE, "pytest_dono2", quem="pedro")
    assert _linha()[0] == "pytest_dono2"


# ------------------------------------------------------- auditoria
def test_quem_atribuiu_fica_registrado():
    atribuir(CHAVE, LOGIN, quem="pedro")
    assert _linha()[2] == "pedro"


def test_a_rota_tira_quem_da_SESSAO_nao_do_corpo():
    """Aceitar `atribuido_por` do corpo deixaria qualquer um assinar a
    atribuição com o nome de outro."""
    fonte = (RAIZ / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    trecho = fonte[fonte.index("def fila_atribuir"):][:700]
    assert "request.state" in trecho and 'payload.get("quem"' not in trecho
    assert 'payload.get("atribuido_por"' not in trecho


def test_leitor_nao_pode_receber_item():
    """A conta `usuario` do host é papel `leitor` (read-only, login de
    demonstração usado de 8 IPs) e aparecia no seletor. Atribuir tarefa a quem
    não pode executá-la é dono fantasma com crachá."""
    with conectar() as con:
        con.execute("INSERT INTO usuarios (login, nome, senha_hash, ativo, papel)"
                    " VALUES ('pytest_leitor','Leitor','x',true,'leitor')")
        con.commit()
    assert "pytest_leitor" not in {r["login"] for r in responsaveis()}
    assert atribuir(CHAVE, "pytest_leitor", quem="pedro")["ok"] is False


def test_responsaveis_lista_so_ativos():
    logins = {r["login"] for r in responsaveis()}
    assert LOGIN in logins
    with conectar() as con:
        con.execute("UPDATE usuarios SET ativo=false WHERE login=%s", (LOGIN,))
        con.commit()
    assert LOGIN not in {r["login"] for r in responsaveis()}
