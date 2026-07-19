"""Suíte da autenticação — a porta do console.

Do outro lado dela estão CNPJ, contas, valores e prazos de 50 organizações
reais. Um erro aqui expõe dado de terceiro. Estes testes travam as decisões que
protegem isso: fail-closed, sem enumeração de usuário, freio de força bruta e
sessão que morre quando deve.

    py -3 -m pytest testes/teste_auth.py -q
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import auth  # noqa: E402
from app.db import conectar, migrar  # noqa: E402

LOGIN = "pytest_usuario"
SENHA = "senha-de-teste-bem-longa-123"


@pytest.fixture(autouse=True)
def _limpo():
    migrar()
    with conectar() as con:
        con.execute("DELETE FROM usuarios WHERE login LIKE 'pytest_%%'")
        con.execute("DELETE FROM acessos_log WHERE login LIKE 'pytest_%%'")
        con.commit()
    yield
    with conectar() as con:
        con.execute("DELETE FROM usuarios WHERE login LIKE 'pytest_%%'")
        con.execute("DELETE FROM acessos_log WHERE login LIKE 'pytest_%%'")
        con.commit()


# --------------------------------------------------------------------- senha

def test_hash_nao_guarda_a_senha_e_confere_de_volta():
    h = auth.hash_senha(SENHA)
    assert SENHA not in h, "a senha não pode aparecer no que vai pro banco"
    assert auth.confere_senha(SENHA, h)
    assert not auth.confere_senha(SENHA + "x", h)


def test_hashes_da_mesma_senha_sao_diferentes():
    """Sal por usuário: duas contas com a mesma senha não podem ter hash igual."""
    assert auth.hash_senha(SENHA) != auth.hash_senha(SENHA)


def test_hash_corrompido_nao_autoriza():
    for lixo in ("", "abc", "1$2$3", "$$$$", "16384$8$1$naoehbase64$idem"):
        assert auth.confere_senha(SENHA, lixo) is False


# ------------------------------------------------------------------- entrada

def test_entra_com_a_senha_certa_e_nao_com_a_errada():
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    token, _ = auth.autenticar(LOGIN, SENHA, ip="1.1.1.1")
    assert token
    assert auth.sessao_valida(token)["login"] == LOGIN
    assert auth.autenticar(LOGIN, "errada", ip="1.1.1.1")[0] is None


def test_nao_enumera_usuario():
    """Login inexistente e senha errada têm que dar a MESMA resposta — senão
    quem tenta descobre quais contas existem."""
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    _, m_senha_errada = auth.autenticar(LOGIN, "errada", ip="2.2.2.2")
    _, m_inexistente = auth.autenticar("pytest_nao_existe", "qualquer", ip="2.2.2.2")
    assert m_senha_errada == m_inexistente


def test_usuario_desativado_nao_entra():
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    with conectar() as con:
        con.execute("UPDATE usuarios SET ativo=false WHERE login=%s", (LOGIN,))
        con.commit()
    assert auth.autenticar(LOGIN, SENHA, ip="3.3.3.3")[0] is None


def test_freio_de_forca_bruta_recusa_ate_a_senha_certa():
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    for _ in range(auth.TENTATIVAS_MAX):
        auth.autenticar(LOGIN, "errada", ip="4.4.4.4")
    token, msg = auth.autenticar(LOGIN, SENHA, ip="4.4.4.4")
    assert token is None, "passou do teto: nem a senha certa entra na janela"
    assert "tentativas" in msg


# ------------------------------------------------------------------- sessão

@pytest.mark.parametrize("token", [None, "", "inventado", "x" * 64])
def test_token_invalido_nunca_vira_usuario(token):
    assert auth.sessao_valida(token) is None


def test_sessao_expirada_nao_vale():
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    token, _ = auth.autenticar(LOGIN, SENHA, ip="5.5.5.5")
    with conectar() as con:
        con.execute("UPDATE sessoes SET expira_em = now() - interval '1 second' WHERE token=%s",
                    (token,))
        con.commit()
    assert auth.sessao_valida(token) is None


def test_logout_mata_a_sessao():
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    token, _ = auth.autenticar(LOGIN, SENHA, ip="6.6.6.6")
    auth.encerrar(token)
    assert auth.sessao_valida(token) is None


def test_desativar_usuario_derruba_sessao_aberta():
    """Tirar o acesso tem que valer AGORA, não quando a sessão expirar."""
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    token, _ = auth.autenticar(LOGIN, SENHA, ip="7.7.7.7")
    with conectar() as con:
        con.execute("UPDATE usuarios SET ativo=false WHERE login=%s", (LOGIN,))
        con.commit()
    assert auth.sessao_valida(token) is None


def test_trocar_senha_invalida_as_sessoes():
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    token, _ = auth.autenticar(LOGIN, SENHA, ip="8.8.8.8")
    ok, _ = auth.trocar_senha(LOGIN, SENHA, "outra-senha-bem-longa-456")
    assert ok
    assert auth.sessao_valida(token) is None, "trocar senha é justamente para derrubar quem tinha"


def test_senha_nova_curta_e_recusada():
    auth.criar_usuario(LOGIN, "Teste", SENHA)
    ok, msg = auth.trocar_senha(LOGIN, SENHA, "curta")
    assert not ok and "12" in msg
