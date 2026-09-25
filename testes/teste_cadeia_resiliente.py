"""Suíte da queda de 31/07–02/08: três dias sem recalcular prazo.

A cadeia diária morreu três manhãs seguidas em
`ingest/transparencia/coletar_regularidade.py`, com
`TimeoutError: The read operation timed out`. A API da CGU respondia em 0,3 s
quando fomos olhar — foi pico de latência, não indisponibilidade.

Duas causas somadas, e a suíte protege as duas:

1. **O retry não cobria rede.** `_get` repetia HTTP 429, mas `TimeoutError` não
   é `HTTPError`: escapava do `except`, subia pelo processo e derrubava tudo.
2. **O elo estava no caminho crítico.** Regularidade é enriquecimento vindo de
   API de TERCEIRO; marcá-lo essencial entregou o controle da nossa cadeia à
   disponibilidade da CGU. Abaixo dele ficam motor de prazos, eventos e o resumo
   do dia — nada disso rodou por três dias.

E uma terceira, de linguagem: o aviso não podia continuar dizendo "os prazos NÃO
foram recalculados" quando a cadeia seguiu. Alarme que exagera é alarme que se
aprende a ignorar.

    py -3 -m pytest testes/teste_cadeia_resiliente.py -q
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "ingest" / "transparencia"))


# ------------------------------------------------- 1. o retry cobre rede
@pytest.fixture()
def cli(monkeypatch):
    from ingest.transparencia import cliente_transparencia as c
    monkeypatch.setattr(c, "_respirar", lambda: None)
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    return c


@pytest.mark.parametrize("erro", [
    TimeoutError("The read operation timed out"),
    urllib.error.URLError("temporary failure in name resolution"),
    ConnectionResetError("connection reset by peer"),
])
def test_falha_de_rede_nao_escapa_da_funcao(cli, monkeypatch, erro):
    """O defeito exato: a exceção subia e matava a cadeia inteira.

    O contrato de `_get` é devolver `(dado, erro)`. Levantar por conta de rede
    quebra esse contrato e leva junto tudo que vinha depois.
    """
    monkeypatch.setattr(cli.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(erro))
    dado, msg = cli._get("cnep", {}, "chave-falsa", tentativas=2)
    assert dado is None
    assert "rede indisponível" in msg and type(erro).__name__ in msg


def test_rede_instavel_e_repetida_e_o_dado_chega(cli, monkeypatch):
    """Pico de latência é passageiro: a segunda tentativa costuma passar."""
    class _Resp:
        def read(self): return b'[{"ok": true}]'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    tentativas = {"n": 0}

    def _urlopen(*a, **k):
        tentativas["n"] += 1
        if tentativas["n"] == 1:
            raise TimeoutError("timeout")
        return _Resp()

    monkeypatch.setattr(cli.urllib.request, "urlopen", _urlopen)
    dado, msg = cli._get("cnep", {}, "chave-falsa", tentativas=3)
    assert msg is None and dado == [{"ok": True}] and tentativas["n"] == 2


def test_http_error_continua_sendo_tratado_como_erro_de_aplicacao(cli, monkeypatch):
    """`HTTPError` é subclasse de `URLError`: se o except de rede vier antes,
    engole 500 e 404 como se fossem instabilidade e some com o diagnóstico."""
    def _urlopen(*a, **k):
        raise urllib.error.HTTPError("u", 500, "erro", {}, None)

    monkeypatch.setattr(cli.urllib.request, "urlopen", _urlopen)
    dado, msg = cli._get("cnep", {}, "chave-falsa", tentativas=2)
    assert dado is None and msg.startswith("HTTP 500")


# ------------------------------- 2. elo de terceiro fora do caminho crítico
class _Log:
    def __init__(self): self.linhas = []
    def write(self, s): self.linhas.append(s)
    def flush(self): pass


@pytest.fixture()
def diario(monkeypatch):
    import ops.rodar_diario as rd

    avisos = []
    monkeypatch.setattr(rd, "_avisar_falha",
                        lambda nome, rc, interrompeu=True: avisos.append((nome, rc, interrompeu)))

    class _Proc:
        returncode, stdout, stderr = 1, "", "falhou"

    monkeypatch.setattr(rd.subprocess, "run", lambda *a, **k: _Proc())
    return rd, avisos


def test_elo_de_terceiro_falha_e_a_cadeia_segue(diario):
    """Regularidade vem da CGU. Nossa vigília de prazo não pode depender da
    disponibilidade dela — foi o que custou 31/07, 01/08 e 02/08."""
    rd, avisos = diario
    rd._passo(_Log(), "regularidade", ["x"], essencial=False, avisar=True)
    assert avisos == [("regularidade", 1, False)], "avisa, mas sem interromper"


def test_elo_essencial_continua_interrompendo(diario):
    """A trava que importa não pode ter afrouxado junto."""
    rd, avisos = diario
    with pytest.raises(SystemExit):
        rd._passo(_Log(), "motor de prazos", ["x"])
    assert avisos == [("motor de prazos", 1, True)]


def test_elo_interno_falha_calado(diario):
    """Prospecção não serve cliente: nem para a cadeia nem faz barulho."""
    rd, avisos = diario
    rd._passo(_Log(), "prospeccao", ["x"], essencial=False)
    assert avisos == []


def test_a_regularidade_esta_fora_do_caminho_critico():
    """A chamada real, não só o mecanismo: é o que quebrou de fato."""
    fonte = (RAIZ / "ops" / "rodar_diario.py").read_text(encoding="utf-8")
    trecho = fonte[fonte.index("regularidade do terceiro"):]
    assert "essencial=False" in trecho[:400] and "avisar=True" in trecho[:400]


# ------------------------------------------------- 3. o aviso não exagera
def test_aviso_nao_diz_que_o_prazo_parou_quando_a_cadeia_seguiu(monkeypatch):
    """Alarme que exagera é alarme que se aprende a ignorar — e este precisa ser
    crível no dia em que o prazo de fato não for recalculado."""
    import ops.rodar_diario as rd

    enviados = []
    monkeypatch.setattr(rd, "_avisar",
                        lambda texto, campos, chave: (enviados.append((texto, campos)), (True, "ok"))[1])

    rd._avisar_falha("regularidade", 1, interrompeu=False)
    texto, campos = enviados[0]
    assert "FORAM recalculados" in texto
    assert "NÃO foram recalculados" not in texto
    assert not any("NÃO foram recalculados" in c for c in campos)

    enviados.clear()
    rd._avisar_falha("motor de prazos", 1)
    texto, campos = enviados[0]
    assert "NÃO foram recalculados" in texto
