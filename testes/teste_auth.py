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


# ---------------------------------------------- isolamento entre tenants (D3)

CLI_A, CLI_B = "11111111111111", "22222222222222"


def _conta_cliente(login: str, doc: str):
    auth.criar_usuario(login, "Cliente", SENHA, papel="cliente", doc_cliente=doc)
    return auth.sessao_valida(auth.autenticar(login, SENHA, ip="9.9.9.9")[0])


def test_cliente_so_enxerga_o_proprio_cnpj():
    u = _conta_cliente("pytest_cli_a", CLI_A)
    assert auth.escopo(u) == {CLI_A}
    assert auth.pode_ver(u, CLI_A)
    assert not auth.pode_ver(u, CLI_B), "vazamento entre clientes é o incidente de LGPD"


def test_cliente_enxerga_com_cnpj_formatado():
    """O doc chega da URL às vezes com pontuação; comparar cru abriria brecha."""
    u = _conta_cliente("pytest_cli_a", CLI_A)
    assert auth.pode_ver(u, "11.111.111/1111-11")


def test_operador_enxerga_a_carteira_toda():
    auth.criar_usuario("pytest_op", "Operador", SENHA)
    u = auth.sessao_valida(auth.autenticar("pytest_op", SENHA, ip="9.9.9.9")[0])
    assert auth.escopo(u) is None
    assert auth.pode_ver(u, CLI_A) and auth.pode_ver(u, CLI_B)


@pytest.mark.parametrize("usuario", [
    None, {}, {"papel": "cliente"},              # cliente sem doc = sem alcance
    {"papel": "cliente", "doc_cliente": None},
    {"papel": "auditor"},                        # papel que ninguém previu
    {"papel": ""},
])
def test_papel_estranho_nao_ve_nada(usuario):
    """D3: papel novo nasce sem alcance. Um `elif` esquecido não pode virar
    'vê tudo'."""
    assert auth.escopo(usuario) == set()
    assert not auth.pode_ver(usuario, CLI_A)


def test_banco_recusa_cliente_sem_alcance():
    """A trava está no schema também: papel cliente sem doc não pode existir."""
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        with conectar() as con:
            con.execute("INSERT INTO usuarios (login, nome, senha_hash, papel, doc_cliente)"
                        " VALUES ('pytest_ruim','X','x','cliente',NULL)")
            con.commit()


def test_criar_cliente_sem_doc_e_recusado_no_codigo():
    with pytest.raises(ValueError):
        auth.criar_usuario("pytest_ruim2", "X", SENHA, papel="cliente")


# ------------------------------------------- RBAC: o metodo faz parte da permissao

from app.main import PERMISSOES_CLIENTE, _cliente_pode  # noqa: E402


@pytest.mark.parametrize("metodo,caminho,pode", [
    # leitura da propria ficha: pode
    ("GET", "/api/cliente/20069629000103", True),
    ("GET", "/api/relatorio/20069629000103", True),
    ("GET", "/api/prestacao/20069629000103", True),
    # ESCRITA sob o MESMO prefixo: nao pode. Sem o metodo na permissao,
    # "pode ver /api/cliente/" virava "pode gravar no nosso diario interno" —
    # foi o que aconteceu na primeira versao (200, linha no banco).
    ("POST", "/api/cliente/20069629000103/diario", False),
    ("POST", "/api/cliente/20069629000103/pessoa", False),
    # superficie de operador
    ("GET", "/api/cockpit", False),
    ("GET", "/api/fila", False),
    ("POST", "/api/fila/triar", False),
    ("GET", "/api/notificacoes", False),
    ("POST", "/api/notificacoes", False),
    ("GET", "/api/normas", False),
    ("POST", "/api/normas/1/tratar", False),
    ("GET", "/api/clientes", False),
    # o proprio usuario
    ("POST", "/api/senha", True),
    ("POST", "/api/logout", True),
    ("GET", "/api/sessao", True),
    # metodo que ninguem previu
    ("DELETE", "/api/cliente/20069629000103", False),
    ("PUT", "/api/cliente/20069629000103", False),
])
def test_permissao_do_cliente_considera_o_metodo(metodo, caminho, pode):
    assert _cliente_pode(metodo, caminho) is pode


def test_permissao_de_cliente_nao_tem_escrita_em_dado_de_operacao():
    """Invariante: fora de logout/senha, o papel cliente é SÓ LEITURA."""
    escritas = [(m, p) for m, p in PERMISSOES_CLIENTE
                if m != "GET" and p not in ("/api/logout", "/api/senha")]
    assert not escritas, f"papel cliente ganhou escrita em {escritas}"
