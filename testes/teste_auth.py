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


# Escritas que o papel `cliente` pode ter: só as da PRÓPRIA conta. Nenhuma
# toca dado de operação (diário, fila, dirigente, interruptor).
ESCRITA_PROPRIA = ("/api/logout", "/api/senha", "/api/perfil/login")


def test_permissao_de_cliente_nao_tem_escrita_em_dado_de_operacao():
    """Invariante: o papel cliente escreve só na própria conta. Se alguém
    adicionar escrita em qualquer outra coisa, este teste quebra."""
    escritas = [(m, p) for m, p in PERMISSOES_CLIENTE
                if m != "GET" and p not in ESCRITA_PROPRIA]
    assert not escritas, f"papel cliente ganhou escrita em {escritas}"


# ------------------------------------------------- contas: criar e trocar login

def test_operador_cria_operador_com_senha_sorteada():
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    ok, msg, senha = auth.criar_operador("pytest_chefe", SENHA, "pytest_novo", "Novo")
    assert ok, msg
    assert senha and len(senha) >= 15, "a senha é sorteada, não escolhida por quem cria"
    novo = auth.sessao_valida(auth.autenticar("pytest_novo", senha, ip="1.1.1.1")[0])
    assert novo["papel"] == "operador"
    assert novo["trocar_senha"] is True, "conta nova nasce obrigada a trocar"


def test_criar_operador_exige_a_senha_de_quem_cria():
    """Criar conta amplia acesso: uma sessão sequestrada não pode fazer sozinha."""
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    ok, _, _ = auth.criar_operador("pytest_chefe", "senha errada", "pytest_novo", "Novo")
    assert not ok


@pytest.mark.parametrize("login", ["ab", "com espaço", "", "x" * 40, "-comeca-com-traco",
                                   "acento_çã", "ponto..duplo" * 4])
def test_login_invalido_recusado(login):
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    ok, _, _ = auth.criar_operador("pytest_chefe", SENHA, login, "Novo")
    assert not ok


def test_login_email_aceito():
    """Login em formato e-mail é aceito (o dono entra por e-mail no túnel) —
    valida a regex E a CHECK do banco (o INSERT passa pelo constraint 0017).
    Login com prefixo pytest_ para o fixture _limpo() faxinar depois."""
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    ok, msg, senha = auth.criar_operador("pytest_chefe", SENHA, "pytest_dono@araticum.net", "Dono")
    assert ok, msg
    assert auth.autenticar("pytest_dono@araticum.net", senha, ip="1.1.1.1")[0], "entra pelo e-mail"


def test_login_maiusculo_e_normalizado_nao_recusado():
    """Login não é sensível a caixa: "Fulano" vira "fulano". Assim "FULANO"
    depois colide como repetido, em vez de criar uma segunda conta."""
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    ok, msg, senha = auth.criar_operador("pytest_chefe", SENHA, "PyTest_Novo", "Novo")
    assert ok, msg
    assert auth.autenticar("pytest_novo", senha, ip="1.1.1.1")[0], "entra pelo login minúsculo"
    ok2, _, _ = auth.criar_operador("pytest_chefe", SENHA, "PYTEST_NOVO", "Outro")
    assert not ok2, "a segunda tentativa colide, não cria conta paralela"


def test_trocar_o_proprio_login_mantem_a_sessao():
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    token, _ = auth.autenticar("pytest_chefe", SENHA, ip="1.1.1.1")
    ok, msg = auth.trocar_login("pytest_chefe", "pytest_outro", SENHA)
    assert ok and msg == "pytest_outro"
    u = auth.sessao_valida(token)
    assert u and u["login"] == "pytest_outro", "o FK cascateia: a sessão acompanha o novo login"


def test_trocar_login_exige_senha_e_recusa_repetido():
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    auth.criar_usuario("pytest_outro", "Outro", SENHA)
    assert not auth.trocar_login("pytest_chefe", "pytest_livre", "errada")[0]
    assert not auth.trocar_login("pytest_chefe", "pytest_outro", SENHA)[0], "login já existe"
    assert not auth.trocar_login("pytest_chefe", "pytest_chefe", SENHA)[0], "igual ao atual"


def test_historico_de_acesso_guarda_o_nome_da_epoca():
    """`acessos_log` NÃO é reescrito na troca: ele registra quem entrou com qual
    identidade, e renomear apagaria a trilha."""
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    auth.autenticar("pytest_chefe", SENHA, ip="1.1.1.1")
    auth.trocar_login("pytest_chefe", "pytest_outro", SENHA)
    with conectar() as con:
        antigos = con.execute(
            "SELECT count(*) FROM acessos_log WHERE login='pytest_chefe'").fetchone()[0]
        troca = con.execute(
            "SELECT count(*) FROM acessos_log WHERE login='pytest_outro'"
            " AND motivo LIKE 'login alterado%%'").fetchone()[0]
    assert antigos >= 1, "o histórico antigo continua com o nome de então"
    assert troca == 1, "a troca entra no log ligando os dois nomes"


def test_ultimo_operador_ativo_nao_pode_ser_desativado():
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    auth.criar_usuario("pytest_novo", "Novo", SENHA)
    with conectar() as con:   # deixa só os dois de teste ativos nesta checagem
        outros = con.execute(
            "SELECT count(*) FROM usuarios WHERE ativo AND papel='operador'"
            " AND login NOT LIKE 'pytest_%%'").fetchone()[0]
    ok, msg = auth.desativar("pytest_chefe", "pytest_novo", SENHA)
    assert ok, msg
    if outros == 0:
        ok2, msg2 = auth.desativar("pytest_novo", "pytest_chefe", SENHA)
        assert not ok2 and "último operador" in msg2


def test_nao_desativa_a_propria_conta():
    auth.criar_usuario("pytest_chefe", "Chefe", SENHA)
    ok, msg = auth.desativar("pytest_chefe", "pytest_chefe", SENHA)
    assert not ok and "própria" in msg
