"""Suíte do diff de andamento quando a FONTE não informa a situação.

O `SIT_CONVENIO` do detru vem **em branco** em 114 convênios vivos do recorte de
27/07/2026 — conferido no CSV cru: o 989509 está `INSTRUMENTO_ATIVO=SIM`, com
vigência até 2029, e mesmo assim sem situação. Não é convênio morto nem erro de
parse: é campo que a fonte simplesmente não preenche.

Branco tratado como valor tem três danos, todos silenciosos:

1. sobrescreve o último valor conhecido e **apaga a base de comparação**;
2. emite "Aprovado → (sem situação)", alarme sem conteúdo nenhum;
3. no dia em que a fonte preencher os 114 de uma vez, viram **114 alertas
   falsos** no telefone de quem opera — de madrugada, sem ninguém entender.

A regra que estes testes travam: **evento exige os dois lados conhecidos.**

    py -3 -m pytest testes/teste_eventos_situacao.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import eventos  # noqa: E402
from app.db import conectar, migrar  # noqa: E402

CNPJ = "00000000000191"      # sintético, fora da carteira real
CABECALHO = "NR_CONVENIO;SIT_CONVENIO"


def _recorte(base: Path, linhas: list[tuple[str, str]]) -> Path:
    """Monta um recorte com o mesmo formato do detru (UTF-8-BOM, ';')."""
    sub = base / CNPJ
    (sub / "legado").mkdir(parents=True, exist_ok=True)
    corpo = "\n".join(f"{nr};{sit}" for nr, sit in linhas)
    (sub / "legado" / "convenio.csv").write_text(
        f"{CABECALHO}\n{corpo}\n", encoding="utf-8-sig")
    return sub


@pytest.fixture
def con():
    migrar()
    with conectar() as c:
        c.execute("DELETE FROM entidades_estado WHERE cnpj=%s", (CNPJ,))
        c.commit()
        yield c
        c.execute("DELETE FROM entidades_estado WHERE cnpj=%s", (CNPJ,))
        c.commit()


def _detectar(con, sub: Path, snap: str = "2026-07-27") -> list[dict]:
    ev = eventos._detectar_ente(con, CNPJ, "Ente de teste", sub, snap)
    con.commit()
    return ev


def _estado(con, chave: str) -> str | None:
    r = con.execute("SELECT valor FROM entidades_estado WHERE cnpj=%s AND dominio='convenio_legado'"
                    " AND chave=%s", (CNPJ, chave)).fetchone()
    return r[0] if r else None


def test_situacao_em_branco_nao_apaga_o_ultimo_valor_conhecido(con, tmp_path):
    """O dano mais grave: perder a base de comparação em silêncio."""
    _detectar(con, _recorte(tmp_path / "d1", [("111", "Em execução")]))       # baseline
    assert _estado(con, "111") == "Em execução"

    ev = _detectar(con, _recorte(tmp_path / "d2", [("111", "")]))             # fonte esqueceu
    assert ev == [], "branco não pode virar evento"
    assert _estado(con, "111") == "Em execução", "o último valor bom tem que sobreviver"


def test_valor_que_volta_igual_depois_do_branco_nao_gera_evento(con, tmp_path):
    """Buraco na fonte não é mudança de andamento."""
    _detectar(con, _recorte(tmp_path / "d1", [("111", "Em execução")]))
    _detectar(con, _recorte(tmp_path / "d2", [("111", "")]))
    assert _detectar(con, _recorte(tmp_path / "d3", [("111", "Em execução")])) == []


def test_mudanca_real_atravessa_um_dia_de_branco(con, tmp_path):
    """E o que importa não pode se perder: se mudou de verdade, avisa — com o
    `de` correto, que só existe porque o branco não sobrescreveu."""
    _detectar(con, _recorte(tmp_path / "d1", [("111", "Em execução")]))
    _detectar(con, _recorte(tmp_path / "d2", [("111", "")]))
    ev = _detectar(con, _recorte(tmp_path / "d3", [("111", "Prestação de Contas em Análise")]))
    assert len(ev) == 1
    assert ev[0]["tipo"] == "mudanca"
    assert ev[0]["de"] == "Em execução"
    assert ev[0]["para"] == "Prestação de Contas em Análise"


def test_estado_legado_em_branco_vira_base_e_nao_rajada(con, tmp_path):
    """Os 114 instrumentos já gravados com '' são herança de quando o branco era
    valor. A primeira leitura real deles é BASE, não mudança — senão o dia em
    que a fonte preencher tudo vira uma rajada de alerta falso."""
    con.execute("INSERT INTO entidades_estado (cnpj, dominio, chave, valor, snapshot)"
                " VALUES (%s,'convenio_legado','989509','','2026-07-26')", (CNPJ,))
    con.commit()
    ev = _detectar(con, _recorte(tmp_path / "d1", [("989509", "Em execução")]))
    assert ev == [], "primeira leitura real sobre estado vazio é base, não evento"
    assert _estado(con, "989509") == "Em execução"
    # e a PRÓXIMA mudança, essa sim, avisa
    ev2 = _detectar(con, _recorte(tmp_path / "d2", [("989509", "Concluído")]))
    assert len(ev2) == 1 and ev2[0]["de"] == "Em execução"


def test_instrumento_novo_so_conta_quando_a_fonte_informa(con, tmp_path):
    _detectar(con, _recorte(tmp_path / "d1", [("111", "Em execução")]))       # baseline
    assert _detectar(con, _recorte(tmp_path / "d2", [("111", "Em execução"), ("222", "")])) == []
    ev = _detectar(con, _recorte(tmp_path / "d3",
                                 [("111", "Em execução"), ("222", "Aprovado")]))
    assert len(ev) == 1 and ev[0]["tipo"] == "novo" and ev[0]["para"] == "Aprovado"
