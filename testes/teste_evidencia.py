"""Suíte da evidência do dossiê — o que o dado aberto já prova.

O checklist estava **100% em branco**: zero itens marcados, sem pasta, sem
arquivo. Ele dizia o que reunir e não mostrava o que já existe — e era para lá
que a triagem mandava 79% dos itens acionáveis. Prometer "peça pronta" e
entregar formulário vazio faz o operador parar de clicar.

O que estes testes protegem:

1. **`evidenciado` nunca vira `feito`.** São coisas diferentes: o dado aberto
   registra que o contrato existe; feito é alguém ter conferido e anexado. O
   órgão pede o documento, não a notícia de que ele existe — marcar automático
   seria mentir para quem presta contas.
2. **Zip ausente ou quebrado não derruba a mesa.** Os arquivos são semanais e
   pesados; um download pela metade não pode tirar a triagem do ar.
3. **Contagem por convênio, lida uma vez.** Os zips têm milhões de linhas;
   reabrir por cliente levaria a cadeia a horas.

    py -3 -m pytest testes/teste_evidencia.py -q
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import evidencia  # noqa: E402


@pytest.fixture(autouse=True)
def _cache_limpo():
    evidencia._cache_por_zip.clear()
    yield
    evidencia._cache_por_zip.clear()


def _zip(tmp: Path, nome: str, linhas: list[dict], colunas: list[str]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=colunas, delimiter=";")
    w.writeheader()
    for l in linhas:
        w.writerow(l)
    with zipfile.ZipFile(tmp / nome, "w") as z:
        z.writestr(nome.replace(".zip", ".csv"), buf.getvalue().encode("utf-8-sig"))


def test_conta_por_convenio(tmp_path, monkeypatch):
    # arquivo SEM ponte de propósito: contrato atravessa a licitação (ver PONTE)
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    _zip(tmp_path, "siconv_desembolso.zip",
         [{"NR_CONVENIO": "850704"}, {"NR_CONVENIO": "850704"}, {"NR_CONVENIO": "999"}],
         ["NR_CONVENIO"])
    assert evidencia._contagem("siconv_desembolso.zip", "NR_CONVENIO") == {"850704": 2, "999": 1}


def test_le_o_zip_uma_vez_so(tmp_path, monkeypatch):
    """Milhões de linhas por arquivo: reabrir por cliente levaria a cadeia a horas."""
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    _zip(tmp_path, "siconv_desembolso.zip", [{"NR_CONVENIO": "1"}], ["NR_CONVENIO"])
    evidencia._contagem("siconv_desembolso.zip", "NR_CONVENIO")
    (tmp_path / "siconv_desembolso.zip").unlink()        # some com o arquivo
    assert evidencia._contagem("siconv_desembolso.zip", "NR_CONVENIO") == {"1": 1}


def test_zip_ausente_nao_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    assert evidencia._contagem("nao_existe.zip", "NR_CONVENIO") == {}


def test_zip_quebrado_nao_derruba_a_mesa(tmp_path, monkeypatch):
    """Download pela metade não pode tirar a triagem do ar."""
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    (tmp_path / "siconv_desembolso.zip").write_bytes(b"nao sou zip")
    assert evidencia._contagem("siconv_desembolso.zip", "NR_CONVENIO") == {}


def test_junta_as_fontes_de_um_item(tmp_path, monkeypatch):
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    _zip(tmp_path, "siconv_licitacao.zip",
         [{"ID_LICITACAO": "L1", "NR_CONVENIO": "850704"}], ["ID_LICITACAO", "NR_CONVENIO"])
    _zip(tmp_path, "siconv_contrato.zip", [{"ID_LICITACAO": "L1"}] * 3, ["ID_LICITACAO"])
    monkeypatch.setattr(evidencia, "_extratos", lambda d, i: 0)
    achados = evidencia.do_instrumento("12345678000190", "850704")
    assert achados["contratos"]["quantos"] == ["3 contrato(s)", "1 licitação(ões)"]
    assert "SICONV" in achados["contratos"]["origem"]


def test_instrumento_sem_registro_nao_inventa(tmp_path, monkeypatch):
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    monkeypatch.setattr(evidencia, "_extratos", lambda d, i: 0)
    assert evidencia.do_instrumento("12345678000190", "000") == {}


def test_sem_instrumento_devolve_vazio(tmp_path, monkeypatch):
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    assert evidencia.do_instrumento("123", "") == {} and evidencia.do_instrumento("123", None) == {}


def test_extrato_da_g2_entra_como_evidencia(tmp_path, monkeypatch):
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    monkeypatch.setattr(evidencia, "_extratos", lambda d, i: 42)
    achados = evidencia.do_instrumento("12345678000190", "850704")
    assert achados["extratos"]["quantos"] == ["42 lançamento(s)"]
    assert "g2" in achados["extratos"]["origem"]


def test_evidencia_NAO_marca_o_item_como_feito(tmp_path, monkeypatch):
    """A distinção que protege quem presta contas: o órgão pede o documento,
    não a notícia de que ele existe."""
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    _zip(tmp_path, "siconv_desembolso.zip", [{"NR_CONVENIO": "850704"}], ["NR_CONVENIO"])
    monkeypatch.setattr(evidencia, "_extratos", lambda d, i: 0)
    achados = evidencia.do_instrumento("12345678000190", "850704")
    serializado = str(achados)
    assert "feito" not in serializado and "True" not in serializado


def test_resumo_e_uma_linha():
    linha = evidencia.resumir({"contratos": {"quantos": ["3 contrato(s)"], "origem": "x"},
                               "extratos": {"quantos": ["42 lançamento(s)"], "origem": "y"}})
    assert "\n" not in linha and "contratos: 3 contrato(s)" in linha


# --------------------------------- armadilhas de chave (medidas no arquivo real)
def test_coluna_inexistente_vira_aviso_e_nao_zero_calado(tmp_path, monkeypatch):
    """`siconv_contrato` não tem NR_CONVENIO e devolvia 0 sem uma palavra —
    72 MB baixados contribuindo nada. Zero silencioso é o modo de falhar que
    este repo passou o dia caçando."""
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    evidencia.COLUNAS_AUSENTES.clear()
    _zip(tmp_path, "siconv_desembolso.zip", [{"OUTRA_COLUNA": "x"}], ["OUTRA_COLUNA"])
    assert evidencia._contagem_crua("siconv_desembolso.zip", "NR_CONVENIO") == {}
    assert any("sem coluna NR_CONVENIO" in a for a in evidencia.COLUNAS_AUSENTES)


def test_contrato_chega_ao_convenio_pela_licitacao(tmp_path, monkeypatch):
    """Dois saltos: contrato -> ID_LICITACAO -> licitação -> NR_CONVENIO."""
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    _zip(tmp_path, "siconv_licitacao.zip",
         [{"ID_LICITACAO": "L1", "NR_CONVENIO": "850704"},
          {"ID_LICITACAO": "L2", "NR_CONVENIO": "999"}], ["ID_LICITACAO", "NR_CONVENIO"])
    _zip(tmp_path, "siconv_contrato.zip",
         [{"ID_LICITACAO": "L1"}, {"ID_LICITACAO": "L1"}, {"ID_LICITACAO": "L2"}],
         ["ID_LICITACAO"])
    assert evidencia._contagem("siconv_contrato.zip", "ID_LICITACAO") == {"850704": 2, "999": 1}


def test_contrato_sem_a_licitacao_no_cache_nao_inventa(tmp_path, monkeypatch):
    monkeypatch.setattr(evidencia, "CACHE", tmp_path)
    _zip(tmp_path, "siconv_contrato.zip", [{"ID_LICITACAO": "L1"}], ["ID_LICITACAO"])
    assert evidencia._contagem("siconv_contrato.zip", "ID_LICITACAO") == {}


def test_obtv_ficou_fora_das_fontes():
    """Chaveado por NR_MOV_FIN; não liga ao convênio sem outro arquivo."""
    todos = [z for fontes in evidencia.FONTES.values() for z, _, _ in fontes]
    assert "siconv_obtv_convenente.zip" not in todos
