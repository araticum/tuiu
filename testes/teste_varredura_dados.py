"""Suíte dos três defeitos que apagavam ou falseavam dado em silêncio.

Achados na varredura de 20/08/2026. Os três são da mesma família das quebras que
já custaram caro nesta casa: nada estoura, nada aparece no log, o dado só some.

1. **O smoke viajava para produção armado.** `smoke_eventos.py` roda
   `DELETE FROM entidades_estado` sem WHERE — 6.012 linhas no host — e planta um
   destinatário curinga no canal do CLIENTE. O deploy põe `testes/` no tar e lá
   `TUIU_DSN` é o banco real; `pytest.ini` não coleta `smoke_*`, então a única
   barreira era o nome do arquivo.
2. **`execucao.persistir` apagava sem piso.** O DELETE que "espelha a rodada" não
   distinguia "o convênio saiu" de "o recorte veio vazio" — e o recorte vem vazio
   em operação normal, porque `detru_recorte` só grava `convenio.csv` se houver
   linhas.
3. **`_refresh_detru` estava fora da rede de alarme** e escrevia direto sobre o
   alvo: download interrompido deixava arquivo truncado com data nova, que passava
   por "cache fresco" para sempre.

    py -3 -m pytest testes/teste_varredura_dados.py -q
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(RAIZ))


# ---------------------------------------------------- 1. o smoke desarmado
def _rodar_smoke(env_extra: dict) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("TUIU_SMOKE_DSN", None)
    env.update(env_extra)
    # encoding explícito: sem ele o Windows decodifica no code page do console e
    # "produção" chega com bytes trocados — o teste falharia por acento, não por
    # defeito, que é o pior tipo de teste vermelho
    return subprocess.run([sys.executable, str(RAIZ / "testes" / "smoke_eventos.py")],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(RAIZ), timeout=60)


def test_smoke_recusa_sem_banco_proprio():
    """O caso do host: alguém digita o comando numa sessão ssh."""
    r = _rodar_smoke({})
    assert r.returncode != 0, "sair com 0 faria o chamador achar que rodou"
    assert "RECUSADO" in (r.stdout + r.stderr)


def test_smoke_recusa_o_mesmo_banco_do_ambiente():
    dsn = "postgresql://postgres@localhost:5432/tuiu"
    r = _rodar_smoke({"TUIU_DSN": dsn, "TUIU_SMOKE_DSN": dsn})
    assert r.returncode != 0 and "MESMO de TUIU_DSN" in (r.stdout + r.stderr)


@pytest.mark.parametrize("dsn", [
    "postgresql://postgres@10.0.0.42:25432/tuiu",
    "postgresql://u@tuiu.araticum.net:5432/tuiu",
    "postgresql://u@localhost:25432/tuiu",
])
def test_smoke_recusa_dsn_com_cara_de_producao(dsn):
    r = _rodar_smoke({"TUIU_SMOKE_DSN": dsn})
    assert r.returncode != 0 and "produção" in (r.stdout + r.stderr)


def test_recusa_nao_imprime_senha():
    """A mensagem vai para o log, e o log vai para o chat."""
    dsn = "postgresql://u:segredo123@localhost:5432/tuiu"
    r = _rodar_smoke({"TUIU_DSN": dsn, "TUIU_SMOKE_DSN": dsn})
    assert "segredo123" not in (r.stdout + r.stderr)


def test_registra_qual_e_a_barreira_real():
    """Se um dia o tar parar de mandar `testes`, ótimo — mas não é o que protege
    hoje, e o teste deixa registrado qual é a barreira de verdade."""
    deploy = (RAIZ / "ops" / "deploy_araticum.sh").read_text(encoding="utf-8")
    assert "testes" in deploy, "mudou o deploy? reveja se a trava ainda é necessária"
    assert "smoke_" not in (RAIZ / "pytest.ini").read_text(encoding="utf-8"), \
        "pytest não pode coletar smoke destrutivo"


# ------------------------------------- 3. o download que não mente sobre frescor
class _Log:
    def __init__(self):
        self.linhas = []

    def write(self, s):
        self.linhas.append(s)

    def flush(self):
        pass


@pytest.fixture()
def diario(monkeypatch, tmp_path):
    import ops.rodar_diario as rd
    monkeypatch.setattr(rd, "CACHE_DETRU", tmp_path)
    avisos = []
    monkeypatch.setattr(rd, "_avisar_falha",
                        lambda nome, rc, interrompeu=True: avisos.append((nome, interrompeu)))
    return rd, avisos, tmp_path


def _zip_em_disco(p: Path, nome_interno="a.txt"):
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(nome_interno, "conteudo")


def _resposta(pedacos=None, erro=None):
    class _Resp:
        def __init__(self):
            self.restante = list(pedacos or [])

        def read(self, n):
            if erro is not None:
                raise erro
            return self.restante.pop(0) if self.restante else b""

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return lambda *a, **k: _Resp()


def test_download_interrompido_nao_vira_cache_fresco(diario, monkeypatch):
    """O defeito mais insidioso: truncado com data nova passa por fresco para
    sempre, e a cadeia falha todo dia até alguém apagar o arquivo à mão."""
    rd, avisos, cache = diario
    alvo = cache / "z.zip"
    _zip_em_disco(alvo)
    os.utime(alvo, (0, 0))                       # força "cache velho"
    antes = alvo.read_bytes()
    monkeypatch.setattr(rd.urllib.request, "urlopen",
                        _resposta(erro=ConnectionResetError("caiu no meio")))

    rd._refresh_detru(_Log(), zips=["z.zip"])

    assert alvo.read_bytes() == antes, "o cache bom não pode ser destruído"
    assert not list(cache.glob("*.parcial")), "o parcial tem que ser removido"
    assert any(i is False for _, i in avisos), "avisa a equipe sem matar a cadeia"


def test_resposta_que_nao_e_zip_e_recusada(diario, monkeypatch):
    """HTML de erro do gov.br tem bytes e ganha data nova — e não é um ZIP."""
    rd, avisos, cache = diario
    alvo = cache / "z.zip"
    _zip_em_disco(alvo)
    os.utime(alvo, (0, 0))
    monkeypatch.setattr(rd.urllib.request, "urlopen",
                        _resposta(pedacos=[b"<html>erro 502</html>"]))

    rd._refresh_detru(_Log(), zips=["z.zip"])

    assert zipfile.is_zipfile(alvo), "o cache tem que continuar sendo o ZIP bom"
    assert any(i is False for _, i in avisos)


def test_sem_cache_anterior_a_cadeia_para(diario, monkeypatch):
    """Degradar só faz sentido com dado velho em disco. Sem nada não há o que
    processar, e seguir produziria recorte vazio — que é exatamente o gatilho do
    defeito de `execucao.persistir`."""
    rd, avisos, cache = diario
    monkeypatch.setattr(rd.urllib.request, "urlopen", _resposta(erro=TimeoutError("timeout")))

    with pytest.raises(SystemExit):
        rd._refresh_detru(_Log(), zips=["z.zip"])
    assert any(i is True for _, i in avisos), "sem cache é falha que interrompe"


def test_download_bom_substitui_o_cache(diario, monkeypatch):
    rd, avisos, cache = diario
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("novo.txt", "novo")
    monkeypatch.setattr(rd.urllib.request, "urlopen", _resposta(pedacos=[buf.getvalue()]))

    rd._refresh_detru(_Log(), zips=["z.zip"])

    alvo = cache / "z.zip"
    assert zipfile.is_zipfile(alvo) and "novo.txt" in zipfile.ZipFile(alvo).namelist()
    assert not avisos and not list(cache.glob("*.parcial"))


def test_cache_fresco_nem_tenta_baixar(diario, monkeypatch):
    """A economia que justifica o cache continua valendo."""
    rd, avisos, cache = diario
    _zip_em_disco(cache / "z.zip")               # recém-criado = fresco
    def _explode(*a, **k):
        raise AssertionError("não deveria ter baixado")
    monkeypatch.setattr(rd.urllib.request, "urlopen", _explode)
    rd._refresh_detru(_Log(), zips=["z.zip"])


# ------------------------------------- 2. o piso do expurgo da execução
def test_persistir_confere_por_cliente_antes_de_apagar():
    """O guarda tem que olhar CLIENTE, não total: o defeito some numa conferência
    agregada, porque um cliente entre cinquenta não move o percentual."""
    fonte = (RAIZ / "backend" / "app" / "execucao.py").read_text(encoding="utf-8")
    trecho = fonte[fonte.index("def persistir"):]
    assert "sumiram = antes - agora" in trecho, "a conferência é por conjunto de CNPJ"
    assert "raise SystemExit" in trecho, "recusar tem que interromper, não avisar"
    assert trecho.index("sumiram") < trecho.index("DELETE FROM execucao_convenio"), \
        "a conferência tem que vir ANTES do DELETE"


# ------------------------------------- 4. o CPF que a tela gravaria inteiro
def test_cpf_e_mascarado_na_entrada():
    """`PRIVACY.md` declara ao titular e ao fiscal que "o CPF completo não
    temos". A via automática sempre respeitou; a via de TELA exigia 11 dígitos e
    gravava o número inteiro — e ainda recusava o mascarado que a outra via do
    mesmo produto grava.

    Nunca chegou a gravar: as 84 linhas de produção vieram todas da via
    automática, todas mascaradas. Era rota carregada e não disparada, igual ao
    smoke — e o conserto é o mesmo: fechar antes de alguém puxar o gatilho.
    """
    from app.cliente_ficha import mascarar_cpf
    assert mascarar_cpf("12379071812") == "***790718**"
    assert mascarar_cpf("123.790.718-12") == "***790718**", "pontuação não muda nada"
    assert "790718" in mascarar_cpf("12379071812")
    for saida in (mascarar_cpf("12379071812"), mascarar_cpf("123.790.718-12")):
        assert "1237" not in saida and saida.count("*") == 5


def test_mascara_ja_mascarada_volta_igual():
    """Idempotência: a via automática entrega já mascarado, e passar duas vezes
    não pode comer dígito."""
    from app.cliente_ficha import mascarar_cpf
    assert mascarar_cpf("***790718**") == "***790718**"
    assert mascarar_cpf(mascarar_cpf("12379071812")) == "***790718**"


@pytest.mark.parametrize("lixo", ["", "abc", "123", "0" * 20])
def test_cpf_impossivel_e_recusado(lixo):
    from app.cliente_ficha import mascarar_cpf
    assert mascarar_cpf(lixo) == ""


def test_a_rota_nao_exige_mais_o_numero_inteiro():
    fonte = (RAIZ / "backend" / "app" / "cliente_ficha.py").read_text(encoding="utf-8")
    trecho = fonte[fonte.index("def cadastrar_pessoa"):][:900]
    assert "mascarar_cpf(cpf)" in trecho
    assert "len(cpf_d) != 11" not in trecho, "voltou a exigir o CPF completo"
