"""Suíte da chave que liga o EVENTO ao MARCO.

O contexto da mensagem (prazo, de quem é a bola, próximo passo, exigência) sai de
`marcos`, procurado por instrumento. A chave do diff só coincide com esse
instrumento em dois dos quatro domínios:

    proposta_g2      chave id_proposta    ->  marco id_proposta   ✓
    convenio_legado  chave NR_CONVENIO    ->  marco NR_CONVENIO   ✓
    parceria_g2      chave id_parceria    ->  marco id_proposta   ✗
    plano_pix        chave id_plano_acao  ->  marco codigo        ✗

Nos dois que não casam o contexto voltava vazio e a mensagem saía sem nada do
que faz o operador decidir — sem erro, sem log, sem sinal. Latente hoje (todo
evento vem do legado), real quando o ciclo novo entrar na carteira.

    py -3 -m pytest testes/teste_eventos_instrumento.py -q
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import eventos  # noqa: E402
from app.db import conectar, migrar  # noqa: E402

CNPJ = "00000000000191"


@pytest.fixture
def con():
    migrar()
    with conectar() as c:
        c.execute("DELETE FROM entidades_estado WHERE cnpj=%s", (CNPJ,))
        c.commit()
        yield c
        c.execute("DELETE FROM entidades_estado WHERE cnpj=%s", (CNPJ,))
        c.commit()


def _parcerias(base: Path, registros: list[dict]) -> Path:
    sub = base / CNPJ
    (sub / "parcerias").mkdir(parents=True, exist_ok=True)
    with gzip.open(sub / "parcerias" / "parceria.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in registros:
            fh.write(json.dumps(r) + "\n")
    return sub


def test_evento_de_parceria_aponta_para_a_PROPOSTA(con, tmp_path):
    """O caso que estava quebrado: o marco do ciclo novo é indexado pela
    proposta, não pela parceria."""
    reg = {"id_parceria": "999", "cd_parceria": "7AAEHR", "id_proposta": "555",
           "in_situacao_parceria": "Em execução"}
    eventos._detectar_ente(con, CNPJ, "Ente", _parcerias(tmp_path / "d1", [reg]), "2026-07-27")
    con.commit()

    reg2 = {**reg, "in_situacao_parceria": "Concluída"}
    ev = eventos._detectar_ente(con, CNPJ, "Ente", _parcerias(tmp_path / "d2", [reg2]), "2026-07-28")
    con.commit()

    assert len(ev) == 1
    assert ev[0]["chave"] == "999", "o diff continua por id_parceria"
    assert ev[0]["instrumento"] == "555", "mas o contexto tem que procurar pela PROPOSTA"
    assert "7AAEHR" in ev[0]["rotulo"], "e o humano continua lendo o código da parceria"


def test_sem_o_campo_de_ligacao_cai_na_chave(con, tmp_path):
    """Registro velho ou incompleto não pode virar instrumento vazio."""
    reg = {"id_parceria": "888", "cd_parceria": "7AAEZZ", "in_situacao_parceria": "Em execução"}
    eventos._detectar_ente(con, CNPJ, "Ente", _parcerias(tmp_path / "d1", [reg]), "2026-07-27")
    con.commit()
    ev = eventos._detectar_ente(
        con, CNPJ, "Ente",
        _parcerias(tmp_path / "d2", [{**reg, "in_situacao_parceria": "Concluída"}]), "2026-07-28")
    con.commit()
    assert ev[0]["instrumento"] == "888"


def test_contador_nao_tem_instrumento(con, tmp_path):
    """`#count` não é item: pedir contexto para ele seria consulta à toa."""
    sub = tmp_path / "d1" / CNPJ
    (sub / "parcerias").mkdir(parents=True)
    for n in (1, 2):
        with gzip.open(sub / "parcerias" / "empenho-parceria.jsonl.gz", "at", encoding="utf-8") as fh:
            fh.write(json.dumps({"i": n}) + "\n")
    eventos._detectar_ente(con, CNPJ, "Ente", sub, "2026-07-27")
    con.commit()
    with gzip.open(sub / "parcerias" / "empenho-parceria.jsonl.gz", "at", encoding="utf-8") as fh:
        fh.write(json.dumps({"i": 3}) + "\n")
    ev = eventos._detectar_ente(con, CNPJ, "Ente", sub, "2026-07-28")
    con.commit()
    assert len(ev) == 1 and ev[0]["tipo"] == "incremento" and ev[0]["instrumento"] is None
