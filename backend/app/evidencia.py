"""O que o DADO ABERTO já prova de cada item do dossiê.

O checklist (db/0024) estava **100% em branco** — zero itens marcados, sem
pasta, sem arquivo. Ele dizia o que reunir e não mostrava o que já existe, e era
para lá que a triagem mandava 79% dos itens acionáveis. Prometer "peça pronta" e
entregar formulário vazio é o tipo de coisa que faz o operador parar de clicar.

Acontece que boa parte do dossiê **já está em dado aberto**: o detru publica
contrato, licitação, aditivo, OBTV, desembolso e rendimento de aplicação por
convênio, e a g2 publica o extrato bancário. Usávamos 3 dos 51 arquivos do
detru; estes 6 provam a maioria dos itens.

## Evidência não é conferência

O estado que sai daqui é **`evidenciado`**, nunca `feito`. São coisas
diferentes:

    evidenciado   o dado aberto registra que existe (ex.: 3 contratos no SICONV)
    feito         alguém da casa conferiu e anexou o documento no dossiê

Marcar automaticamente como feito seria mentir para quem presta contas: o órgão
pede o documento, não a notícia de que ele existe. O que a evidência faz é
tirar o operador do zero — ele sabe o que procurar, onde e quantos.

## Cobertura

    plano_trabalho    termo aditivo, prorroga de ofício
    contratos         contrato (via licitação), licitação
    pagamentos_obtv   desembolso
    extratos          extrato bancário da g2
    conciliacao       solicitação de rendimento de aplicação
    devolucao_saldo   saldo a devolver em `execucao_convenio`
    notas_fiscais     — exige `siconv_pagamento.zip` (364 MB), fora por ora
    relatorio_objeto  — não existe em dado aberto; é peça que a casa produz

## Duas armadilhas de chave, medidas no arquivo real

Nem todo arquivo do detru traz `NR_CONVENIO`, e supor que traz devolve **zero
calado** — o mesmo modo de falhar que perseguimos o dia inteiro:

- `siconv_contrato` é chaveado por `ID_LICITACAO`; o convênio só aparece na
  licitação. Resolvido com uma ponte declarada em `PONTE`, não escondida.
- `siconv_obtv_convenente` é chaveado por `NR_MOV_FIN` e não liga ao convênio
  sem outro arquivo — saiu da lista DEPOIS de baixado. Foram 57 MB gastos à
  toa, e `desembolso` já evidencia o mesmo item.

Por isso `_contagem_crua` confere o cabeçalho antes de varrer: coluna
configurada que não existe vira aviso em `COLUNAS_AUSENTES`, não silêncio.
"""

from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
CACHE = RAIZ / "data" / "detru" / "cache"

# item do dossiê -> [(zip, coluna do nº do convênio, substantivo)]
FONTES = {
    "plano_trabalho": [("siconv_termo_aditivo.zip", "NR_CONVENIO", "termo(s) aditivo(s)"),
                       ("siconv_prorroga_oficio.zip", "NR_CONVENIO", "prorroga(s) de ofício")],
    "contratos": [("siconv_contrato.zip", "ID_LICITACAO", "contrato(s)"),
                  ("siconv_licitacao.zip", "NR_CONVENIO", "licitação(ões)")],
    # OBTV ficou de FORA: `siconv_obtv_convenente` é chaveado por NR_MOV_FIN e
    # só liga ao convênio passando por um arquivo que não baixamos. Os 57 MB
    # foram gastos à toa e saíram da lista. `desembolso` já evidencia o item.
    "pagamentos_obtv": [("siconv_desembolso.zip", "NR_CONVENIO", "desembolso(s)")],
    "conciliacao": [("siconv_solicitacao_rendimento_aplicacao.zip", "NR_CONVENIO",
                     "solicitação(ões) de rendimento de aplicação")],
}

# contrato NÃO tem NR_CONVENIO: é chaveado por ID_LICITACAO, e o convênio só
# aparece na licitação. Dois saltos, declarados aqui em vez de escondidos.
PONTE = {"siconv_contrato.zip": ("ID_LICITACAO", "siconv_licitacao.zip",
                                 "ID_LICITACAO", "NR_CONVENIO")}

_cache_por_zip: dict[str, dict[str, int]] = {}
# coluna configurada que não existe no arquivo devolvia 0 CALADO — o mesmo modo
# de falhar que perseguimos o dia inteiro. Aqui ela vira aviso visível.
COLUNAS_AUSENTES: list[str] = []


def _contagem(nome_zip: str, coluna: str) -> dict[str, int]:
    if nome_zip in PONTE and nome_zip not in _cache_por_zip:
        _cache_por_zip[nome_zip] = _por_ponte(nome_zip)
    return _contagem_crua(nome_zip, coluna)


def _contagem_crua(nome_zip: str, coluna: str) -> dict[str, int]:
    """{nº do convênio -> quantas linhas}. Lido uma vez por processo: os zips
    têm milhões de linhas e reabrir por cliente levaria a cadeia a horas."""
    if nome_zip in _cache_por_zip:
        return _cache_por_zip[nome_zip]
    caminho = CACHE / nome_zip
    contagem: dict[str, int] = {}
    if caminho.exists():
        try:
            with zipfile.ZipFile(caminho) as z:
                with z.open(z.namelist()[0]) as fh:
                    leitor = csv.DictReader(
                        io.TextIOWrapper(fh, encoding="utf-8-sig", newline=""), delimiter=";")
                    if coluna not in (leitor.fieldnames or []):
                        COLUNAS_AUSENTES.append(f"{nome_zip}: sem coluna {coluna}")
                        _cache_por_zip[nome_zip] = {}
                        return {}
                    for row in leitor:
                        chave = (row.get(coluna) or "").strip()
                        if chave:
                            contagem[chave] = contagem.get(chave, 0) + 1
        except (zipfile.BadZipFile, OSError, KeyError):
            contagem = {}     # zip pela metade não pode derrubar a mesa
    _cache_por_zip[nome_zip] = contagem
    return contagem


def _por_ponte(nome_zip: str) -> dict[str, int]:
    """Conta um arquivo que não traz o nº do convênio, atravessando a tabela que
    traz. Sem isto o `siconv_contrato` (72 MB) contribuía ZERO — e calado."""
    col_local, zip_ponte, col_ponte, col_destino = PONTE[nome_zip]
    de_para: dict[str, str] = {}
    caminho = CACHE / zip_ponte
    if caminho.exists():
        try:
            with zipfile.ZipFile(caminho) as z, z.open(z.namelist()[0]) as fh:
                for row in csv.DictReader(
                        io.TextIOWrapper(fh, encoding="utf-8-sig", newline=""), delimiter=";"):
                    chave, destino = (row.get(col_ponte) or "").strip(), (row.get(col_destino) or "").strip()
                    if chave and destino:
                        de_para[chave] = destino
        except (zipfile.BadZipFile, OSError, KeyError):
            return {}
    bruto = _contagem_crua(nome_zip, col_local)
    saida: dict[str, int] = {}
    for chave, n in bruto.items():
        alvo = de_para.get(chave)
        if alvo:
            saida[alvo] = saida.get(alvo, 0) + n
    return saida


def _extratos(doc: str, instrumento: str) -> int:
    """Lançamentos no extrato da conta da parceria (g2), via app.conferencia."""
    try:
        from app.conferencia import _contas_da_proposta, _linhas
        contas = {str(c.get("id_parceria_conta")) for c in _contas_da_proposta(doc, instrumento)}
        if not contas:
            return 0
        return sum(1 for e in _linhas(doc, "extrato-bancario")
                   if str(e.get("id_parceria_conta")) in contas)
    except Exception:  # noqa: BLE001
        return 0


def do_instrumento(doc: str, instrumento: str, con=None) -> dict[str, dict]:
    """{item do dossiê -> {quantos, o que}} para o que o dado aberto registra."""
    doc = "".join(c for c in (doc or "") if c.isdigit())
    alvo = str(instrumento or "").strip()
    if not alvo:
        return {}
    achados: dict[str, dict] = {}

    for item, fontes in FONTES.items():
        partes = []
        for nome_zip, coluna, substantivo in fontes:
            n = _contagem(nome_zip, coluna).get(alvo, 0)
            if n:
                partes.append(f"{n} {substantivo}")
        if partes:
            achados[item] = {"quantos": partes, "origem": "dados abertos SICONV/detru"}

    n = _extratos(doc, alvo)
    if n:
        achados["extratos"] = {"quantos": [f"{n} lançamento(s)"],
                               "origem": "extrato bancário da parceria (g2)"}

    if con is not None:
        try:
            r = con.execute("SELECT vl_saldo_reman_tesouro FROM execucao_convenio"
                            " WHERE cnpj=%s AND instrumento=%s", (doc, alvo)).fetchone()
            if r and r[0] and float(r[0]) > 0:
                achados["devolucao_saldo"] = {
                    "quantos": [f"saldo de R$ {float(r[0]):,.2f} a devolver".replace(",", "X")
                                .replace(".", ",").replace("X", ".")],
                    "origem": "execução financeira (detru)"}
        except Exception:  # noqa: BLE001
            con.rollback()
    return achados


def resumir(achados: dict[str, dict]) -> str:
    """Uma linha por item, para o contexto do redator e para a tela."""
    return " · ".join(f"{item}: {', '.join(d['quantos'])}" for item, d in sorted(achados.items()))
