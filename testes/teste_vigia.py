"""Suíte da vigília normativa — a peça que impede a regra de apodrecer.

O produto vende prazo com base legal citada. Regra desatualizada não dá erro:
dá resposta errada com ar de certa. Estes testes travam o que fez a vigília
falhar em silêncio na primeira versão.

    py -3 -m pytest testes/teste_vigia.py -q
"""

from __future__ import annotations

import re
import sys

import pytest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "ingest" / "normas"))

from vigia_dou import CABECALHO, TERMOS, _plano, _tag  # noqa: E402


def test_texto_normalizado_antes_de_casar():
    """A causa do primeiro fracasso: marcação inline parte a expressão e o
    regex no XML cru não casa — a vigília dizia 'nenhuma norma' com norma na
    frente."""
    cru = "<p>Portaria <i>Conjunta</i> MGI/<b>MF</b>/CGU nº 33</p>"
    assert not re.search(TERMOS["PC 33/2023"], cru, re.I), "no cru, falha (é o bug)"
    assert re.search(TERMOS["PC 33/2023"], _plano(cru), re.I), "normalizado, casa"


def test_plano_tira_marcacao_e_espaco():
    assert _plano("  <a href='x'>Portaria</a>\n\n  Conjunta  ") == "Portaria Conjunta"


def test_tag_aceita_atributo_na_abertura():
    """A Imprensa varia entre `<Identifica>` e `<Identifica id="...">`."""
    assert _tag("<Identifica>PORTARIA N 1</Identifica>", "Identifica") == "PORTARIA N 1"
    assert _tag('<Identifica id="a">PORTARIA N 2</Identifica>', "Identifica") == "PORTARIA N 2"
    assert _tag("<Ementa>Altera algo</Ementa>", "Identifica") is None


def test_cabecalho_serve_de_reserva_sem_identifica():
    texto = ("Portaria Conjunta MGI/MF/CGU Nº 45, DE 10 DE julho DE 2026 "
             "Altera a Portaria Conjunta MGI/MF/CGU nº 33, de 30 de agosto de 2023")
    m = CABECALHO.search(texto)
    assert m and "45" in m.group(1), "pega o cabeçalho, não a norma alterada"


@pytest.mark.parametrize("trecho,rotulo", [
    ("institui o Transferegov.br para", "transferegov"),
    ("transferências de recursos da União", "transferência da União"),
    ("convênios e contratos de repasse", "convênio/contrato de repasse"),
    ("Portaria Conjunta MGI/MF/CGU nº 33, de 30", "PC 33/2023"),
    ("Portaria Conjunta MGI/MF/CGU nº 28, de 21", "PC 28/2024"),
    ("Portaria Interministerial nº 424, de 2016", "PI 424/2016"),
    ("Decreto nº 11.531, de 16 de maio", "Decreto 11.531"),
    ("Lei nº 13.019, de 2014", "MROSC"),
])
def test_termos_pegam_o_que_importa(trecho, rotulo):
    assert re.search(TERMOS[rotulo], _plano(trecho), re.I)


def test_termo_nao_pega_norma_de_outro_assunto():
    """Peneira ampla, mas não a ponto de trazer o DOU inteiro."""
    fora = _plano("Portaria nº 12 que dispõe sobre horário de funcionamento do protocolo")
    assert not [r for r, p in TERMOS.items() if re.search(p, fora, re.I)]


# --------------------------------------------- peneira: sinal x ruido (medido)

from vigia_dou import ESPECIFICOS, GENERICOS, relevante  # noqa: E402


@pytest.mark.parametrize("casou,esperado", [
    (["prestação de contas"], False),        # 40 de 45 vinham só por isto
    (["emenda parlamentar"], False),
    (["transferência da União"], False),
    (["transferegov"], True),                # específico dispara sozinho
    (["PC 33/2023"], True),
    (["MROSC"], True),
    (["prestação de contas", "transferência da União"], True),   # 2 genéricos
    (["prestação de contas", "PC 28/2024"], True),
    ([], False),
])
def test_generico_nao_dispara_sozinho(casou, esperado):
    """Vigília com 40 itens por dia é vigília que ninguém lê. Termo genérico
    ('prestação de contas' aparece em qualquer portaria) só conta acompanhado."""
    assert relevante(casou) is esperado


def test_niveis_nao_se_sobrepoem():
    assert not (set(ESPECIFICOS) & set(GENERICOS)), "termo em dois níveis torna a regra ambígua"


# ------------------------------------------------------- feriado e "sem edição"
import io as _io
import zipfile as _zipfile
from datetime import date as _date

import vigia_dou as _v


def _zip_com_xml(texto: str = "<article>Portaria sobre pesca esportiva</article>") -> bytes:
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        z.writestr("um.xml", texto)
    return buf.getvalue()


def _inlabs_falso(monkeypatch, respostas: dict):
    """respostas[(dia, secao)] = bytes de ZIP, b"<html>" para página, None para 404."""
    def baixar(op, dia, secao):
        r = respostas.get((dia, secao))
        if r is None:
            return None
        if not r.startswith(b"PK"):
            raise _v.SemEdicao(dia, secao, r)
        return r
    monkeypatch.setattr(_v, "_baixar_zip", baixar)
    monkeypatch.setattr(_v, "gravar", lambda achados: achados)   # sem banco


def test_feriado_nacional_fixo():
    """07/09/2026 travou a vigília por 18 dias: página HTML tratada como fonte instável."""
    assert _v.feriado_nacional(_date(2026, 9, 7))
    assert _v.feriado_nacional(_date(2026, 11, 20)), "Consciência Negra é nacional desde 2024"
    assert not _v.feriado_nacional(_date(2026, 9, 8))


def test_pagina_antes_de_zip_e_sem_edicao(monkeypatch):
    """Terça de Carnaval não é feriado por lei, mas não tem DOU: página HTML. O ZIP
    de quarta prova que o INLABS estava de pé, então terça é 'sem edição' e o
    marcador anda até o fim."""
    ter, qua = _date(2026, 2, 17), _date(2026, 2, 18)
    _inlabs_falso(monkeypatch, {(ter, "DO1"): b"<html>sem edicao", (qua, "DO1"): _zip_com_xml()})
    r = _v.percorrer(None, [ter, qua])
    assert [e.dia for e in r["sem_edicao"]] == [ter]
    assert r["pendentes"] == [] and r["ate"] == qua


def test_pagina_no_fim_fica_pendente_e_marcador_nao_passa(monkeypatch):
    """INLABS caiu no meio da varredura: o dia sem ZIP e sem prova fica para amanhã."""
    qui, sex = _date(2026, 9, 24), _date(2026, 9, 25)
    _inlabs_falso(monkeypatch, {(qui, "DO1"): _zip_com_xml(), (sex, "DO1"): b"<html>erro"})
    r = _v.percorrer(None, [qui, sex])
    assert [e.dia for e in r["pendentes"]] == [sex]
    assert r["ate"] == qui, "o marcador para no último dia provado"


def test_so_pagina_e_fonte_instavel(monkeypatch):
    """Nenhum ZIP em nada: não há como saber se é feriado ou queda — erro, elo vermelho."""
    qui = _date(2026, 9, 24)
    _inlabs_falso(monkeypatch, {(qui, "DO1"): b"<html>fora do ar"})
    with pytest.raises(RuntimeError, match="fonte inst"):
        _v.percorrer(None, [qui])


def test_feriado_e_fim_de_semana_nao_consultam_o_inlabs(monkeypatch):
    chamadas = []
    monkeypatch.setattr(_v, "_baixar_zip", lambda op, dia, secao: chamadas.append(dia) or None)
    monkeypatch.setattr(_v, "gravar", lambda achados: achados)
    dias = [_date(2026, 9, 5), _date(2026, 9, 6), _date(2026, 9, 7), _date(2026, 9, 8)]
    r = _v.percorrer(None, dias)
    assert set(chamadas) == {_date(2026, 9, 8)} and r["ate"] == _date(2026, 9, 8)   # DO1 e DO1E do mesmo dia
