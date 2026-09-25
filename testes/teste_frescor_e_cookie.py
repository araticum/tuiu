"""Suíte das duas travas que estavam DESLIGADAS sem ninguém saber.

Achadas na varredura de 27/07/2026, ambas da mesma família: nada quebrado, nada
no log, só a proteção não acontecendo.

1. **Cookie de sessão sem `Secure`.** O código marcava `Secure` só se
   `TUIU_COOKIE_SECURE=1` — variável que nunca existiu no host. O console está
   publicado em https com dado de 50 organizações reais, e o cookie saía sem a
   marca: bastava uma requisição http para ele viajar em claro. Agora `Secure` é
   o padrão e desligar exige opt-in, como o `TUIU_TLS_INSECURE` já fazia.

2. **Dado velho passando por D-1.** `verificar.py` mede `snapshot_fresco` e
   escreve no `_verificacao.json`, mas o exit code dele só olha divergência —
   frescor nunca entrou na conta, nem com `--strict`. Se a carga do Transferegov
   atrasa, a cadeia recalcula prazo sobre ontem-retrasado e fecha "cadeia
   concluída". Este produto VENDE vigilância D-1; mentir sobre a idade do dado é
   o defeito mais caro que ele pode ter.

    py -3 -m pytest testes/teste_frescor_e_cookie.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(RAIZ))


# ------------------------------------------------------------------ cookie
def _secure_do_login(monkeypatch, valor: str | None) -> bool:
    """Lê a decisão do mesmo jeito que a rota de login a toma."""
    import os
    monkeypatch.delenv("TUIU_COOKIE_INSEGURO", raising=False)
    if valor is not None:
        monkeypatch.setenv("TUIU_COOKIE_INSEGURO", valor)
    return os.environ.get("TUIU_COOKIE_INSEGURO") != "1"


def test_cookie_nasce_secure_sem_precisar_de_variavel(monkeypatch):
    """O caso real: host sem variável nenhuma. Antes saía SEM Secure."""
    assert _secure_do_login(monkeypatch, None) is True


@pytest.mark.parametrize("valor", ["0", "", "sim", "true", "nao"])
def test_so_o_opt_in_exato_desliga(monkeypatch, valor):
    """Valor estranho não pode desligar proteção por engano."""
    assert _secure_do_login(monkeypatch, valor) is True


def test_opt_in_explicito_desliga_para_dev_local(monkeypatch):
    assert _secure_do_login(monkeypatch, "1") is False


def test_a_rota_de_login_usa_essa_regra():
    """Trava o texto: se alguém voltar ao `== "1"`, o cookie perde o Secure."""
    fonte = (RAIZ / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'secure=os.environ.get("TUIU_COOKIE_INSEGURO") != "1"' in fonte
    # a leitura fail-open não pode voltar — mas o NOME dela segue no comentário
    # que conta a história, e comentário não liga nem desliga nada
    assert 'environ.get("TUIU_COOKIE_SECURE")' not in fonte


# ----------------------------------------------------------------- frescor
@pytest.fixture
def diario(monkeypatch, tmp_path):
    import ops.rodar_diario as rd
    monkeypatch.setattr(rd, "RAIZ", tmp_path)
    enviados = []
    monkeypatch.setattr(rd, "_avisar",
                        lambda texto, campos, chave: (enviados.append((texto, campos, chave)), (True, "ok"))[1])
    return rd, enviados, tmp_path


def _verificacao(base: Path, *, fresco: bool, divergem: int = 0) -> None:
    from datetime import date
    d = base / "data" / "recortes" / date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "_verificacao.json").write_text(json.dumps({
        "snapshot": "2026-07-26", "data_atualizacao_api": "2026-07-27T00:00:00",
        "snapshot_fresco": fresco, "resumo": {"conferem": 100 - divergem, "divergem": divergem},
    }), encoding="utf-8")


class _Log:
    def __init__(self): self.linhas = []
    def write(self, s): self.linhas.append(s)
    def flush(self): pass


def test_dado_fresco_nao_avisa_ninguem(diario):
    rd, enviados, base = diario
    _verificacao(base, fresco=True)
    rd._conferir_frescor(_Log())
    assert enviados == [], "avisar quando está tudo bem treina a equipe a ignorar"


def test_snapshot_velho_avisa_a_equipe(diario):
    """O caso que passava calado."""
    rd, enviados, base = diario
    _verificacao(base, fresco=False)
    rd._conferir_frescor(_Log())
    assert len(enviados) == 1
    texto, campos, chave = enviados[0]
    assert "NAO fresco" in texto and "D-1" in texto
    assert len(campos) == 5, "tem que caber no template de 5 variáveis"
    assert chave.startswith("frescor-"), "idempotente por dia"


def test_divergencia_com_a_g2_avisa(diario):
    rd, enviados, base = diario
    _verificacao(base, fresco=True, divergem=3)
    rd._conferir_frescor(_Log())
    # norma culta no aviso: o número é conhecido, então concorda de verdade
    assert len(enviados) == 1 and "3 conferências DIVERGEM" in enviados[0][0]


def test_divergencia_unica_concorda_no_singular(diario):
    rd, enviados, base = diario
    _verificacao(base, fresco=True, divergem=1)
    rd._conferir_frescor(_Log())
    assert "1 conferência DIVERGE" in enviados[0][0]


def test_ausencia_do_arquivo_aparece_no_log(diario):
    """Não medir é diferente de medir e estar bom — não pode passar por 'ok'."""
    rd, enviados, base = diario
    log = _Log()
    rd._conferir_frescor(log)
    assert any("NÃO conferido" in l for l in log.linhas)
