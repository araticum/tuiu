"""Suíte da redação por IA (etapa B) — as travas antes de o texto sair da casa.

Autorização do dono (28/07): DeepInfra, tratando o dado na entrada para retirar
e na saída para recompor. Estes testes não exercitam o modelo (rede) — exercitam
o que decide SE e COMO se chama, que é onde mora o risco.

    py -3 -m pytest testes/teste_redator.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import redator  # noqa: E402

EXIGENCIA = ("A proposta foi colocada em diligência para complementação. Solicitamos que o "
             "proponente realize os ajustes necessários no prazo de 10 dias corridos, até o "
             "dia 20/04/2026, sob pena de arquivamento da proposta conforme o Art. 21 da "
             "Portaria GM/MMA nº 1250/2024, com reapresentação por novo cadastramento.")
CONHECIDOS = {"CLIENTE": "FUNDACAO EXEMPLO", "CNPJ": "12.345.678/0001-90",
              "PESSOA_1": "Fulano de Tal"}


@pytest.fixture
def caso(monkeypatch):
    monkeypatch.setenv("DEEPINFRA_API_KEY", "chave-de-teste")
    monkeypatch.setattr(redator, "material", lambda doc, idp: {
        "pronto": True, "parecer": EXIGENCIA, "conhecidos": CONHECIDOS, "doc": "12345678000190"})
    enviados = {}

    def _falso(prompt, chave, timeout=120.0):
        enviados["prompt"] = prompt
        return {"texto": "1. A [[CLIENTE]], CNPJ [[CNPJ]], por [[PESSOA_1]], apresenta:",
                "tokens_entrada": 100, "tokens_saida": 50}

    monkeypatch.setattr(redator, "_chamar", _falso)
    return enviados


# ------------------------------------------------------- não chamar à toa
def test_parecer_curto_nao_vira_chamada(monkeypatch):
    """Na carteira o MS escreve só "Parecer Técnico nº 184/2024-COPP…". Gastar
    token para o modelo inventar em cima disso é o pior uso possível."""
    monkeypatch.setattr(redator, "material", lambda d, i: {
        "pronto": False, "erro": "parecer com 55 chars — é referência de documento"})
    monkeypatch.setenv("DEEPINFRA_API_KEY", "x")
    r = redator.redigir("123", "1", forcar=True)
    assert r["disponivel"] is False and "referência de documento" in r["erro"]


def test_desligado_por_padrao(monkeypatch):
    monkeypatch.setattr(redator, "material", lambda d, i: {"pronto": True})
    monkeypatch.setenv("DEEPINFRA_API_KEY", "x")
    monkeypatch.setattr("app.config.ligado", lambda c: False)
    assert "desligada" in redator.redigir("123", "1")["erro"]


def test_sem_chave_nao_chama(monkeypatch, caso):
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    assert "DEEPINFRA_API_KEY" in redator.redigir("123", "1", forcar=True)["erro"]


# ----------------------------------------------- o que sai, sai mascarado
def test_o_prompt_nao_leva_identificador(caso):
    redator.redigir("12345678000190", "1", forcar=True)
    prompt = caso["prompt"]
    for proibido in ("FUNDACAO EXEMPLO", "12.345.678", "Fulano de Tal", "12345678000190"):
        assert proibido not in prompt, f"vazou no prompt: {proibido}"


def test_mascara_falha_aborta_o_envio(monkeypatch):
    """A trava que autoriza: se `vazou` não vier vazio, não manda. Dado que sai
    não volta."""
    monkeypatch.setenv("DEEPINFRA_API_KEY", "x")
    monkeypatch.setattr(redator, "material", lambda d, i: {
        "pronto": True, "parecer": EXIGENCIA, "conhecidos": CONHECIDOS, "doc": "1"})
    monkeypatch.setattr(redator, "vazou", lambda t, m: ["FUNDACAO EXEMPLO"])
    chamou = []
    monkeypatch.setattr(redator, "_chamar", lambda *a, **k: chamou.append(1))
    r = redator.redigir("123", "1", forcar=True)
    assert r["disponivel"] is False and "abortado" in r["erro"]
    assert chamou == [], "não pode nem tentar chamar o modelo"


def test_prompt_declara_os_marcadores_disponiveis(caso):
    """Sem a lista o modelo INVENTA marcador, e o rascunho sai com campo que
    ninguém consegue preencher — foi o que a primeira chamada real devolveu."""
    redator.redigir("12345678000190", "1", forcar=True)
    assert "use SOMENTE estes" in caso["prompt"]
    for m in ("[[CLIENTE]]", "[[CNPJ]]", "[[PESSOA_1]]"):
        assert m in caso["prompt"]


# --------------------------------------------------------- o que volta
def test_recompoe_inclusive_o_que_nao_estava_no_parecer(caso):
    """O nome do cliente não aparece no texto do parecer, mas eu o cito no
    enunciado — sem registrá-lo, o marcador chegava CRU ao rascunho."""
    r = redator.redigir("12345678000190", "1", forcar=True)
    assert "FUNDACAO EXEMPLO" in r["markdown"]
    assert "12.345.678/0001-90" in r["markdown"] and "Fulano de Tal" in r["markdown"]
    assert "[[" not in r["markdown"]


def test_marcador_inventado_aparece_no_aviso(monkeypatch, caso):
    monkeypatch.setattr(redator, "_chamar", lambda *a, **k: {
        "texto": "1. A [[CLIENTE]] informa o empenho [[EMPENHO]].",
        "tokens_entrada": 1, "tokens_saida": 1})
    r = redator.redigir("12345678000190", "1", forcar=True)
    assert r["marcadores_inventados"] == ["[[EMPENHO]]"]
    assert "inventou" in r["aviso"]


def test_rascunho_sempre_avisa_que_e_rascunho(caso):
    r = redator.redigir("12345678000190", "1", forcar=True)
    assert "RASCUNHO" in r["aviso"] and "revise antes de enviar" in r["aviso"]
    assert r["tokens_entrada"] == 100 and r["tokens_saida"] == 50


def test_falha_de_rede_nao_levanta(monkeypatch, caso):
    def _explode(*a, **k):
        raise TimeoutError("modelo fora do ar")
    monkeypatch.setattr(redator, "_chamar", _explode)
    r = redator.redigir("12345678000190", "1", forcar=True)
    assert r["disponivel"] is False and "TimeoutError" in r["erro"]
