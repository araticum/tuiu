"""Prestação de contas (F3, versão simples) — checklist por regime + wizard Pix.

Sem Sargaço, sem pdf-render, sem assinatura A1 (decisão do dono 18/07: manter
simples). O dossiê é pasta local; a saída é texto/markdown que o usuário cola
no Transferegov ou imprime pelo navegador.

Duas entregas:
  1. `checklist(cnpj, instrumento)` — o que juntar, POR REGIME, cada item com a
     base legal vinda de `regras_normativas` (vigente na data do instrumento).
  2. `relatorio_gestao_pix(cnpj)` — rascunho do Relatório de Gestão das
     transferências especiais para os planos sem relatório no estoque
     2020–2024 (a dor de 82% dos municípios; multa de 1%/dia — IN TCU 93/2024).
"""

from __future__ import annotations

import csv
import gzip
import json
from datetime import date, datetime
from pathlib import Path

from app.carteira import ROTULOS, snapshot_mais_recente
from app.db import conectar, regra_vigente

CORTE_REGIME_NOVO = date(2023, 9, 1)


def _data_br(s):
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _regime(assinatura: date | None, valor: float | None, teto: float) -> tuple[str, str]:
    if assinatura and assinatura < CORTE_REGIME_NOVO:
        return "legado_pi424", "PI 424/2016 (ultratividade — celebrado antes de 01/09/2023)"
    if valor is not None and teto and valor <= teto:
        return "simplificado_pc28", "PC MGI/MF/CGU 28/2024 (regime simplificado, art. 184-A da Lei 14.133)"
    return "completo_pc33", "PC MGI/MF/CGU 33/2023 (regime completo)"


# Itens do checklist por regime. Cada um: (item, parametro_regra|None)
ITENS = {
    "comum": [
        ("Relatório de cumprimento do objeto (o que foi executado × plano de trabalho)", None),
        ("Relação de pagamentos e extrato da conta específica (incl. rendimentos)", None),
        ("Comprovante de devolução de saldo remanescente, se houver", "prazo_devolucao_saldos"),
        ("Guarda dos documentos originais pelo prazo legal", "guarda_documental"),
    ],
    "completo_pc33": [
        ("Relatório de execução físico-financeira", None),
        ("Demonstrativo da execução da receita e despesa", None),
        ("Relação de bens adquiridos/produzidos/construídos", None),
        ("Comprovação do aporte da contrapartida", None),
        ("Processo licitatório e contratos com fornecedores", None),
        ("Registro fotográfico / laudo de vistoria (obras)", None),
    ],
    "simplificado_pc28": [
        ("Relatório simplificado de execução (parcela única)", None),
        ("Notas fiscais e comprovantes de pagamento", None),
        ("Evidência para a visita de constatação final (fotos georreferenciadas em obra)", None),
    ],
    "legado_pi424": [
        ("Relatório de execução físico-financeira (modelo PI 424/2016)", None),
        ("Demonstrativo de receita e despesa + conciliação bancária", None),
        ("Relação de bens e de pagamentos", None),
    ],
}


def _teto_simplificado(con, em: date) -> float:
    r = regra_vigente(con, "corte_regime_simplificado", "geral", em)
    return float((r or {}).get("valor", {}).get("valor") or 0)


def checklist(cnpj: str) -> dict:
    """Checklist dos instrumentos ATIVOS do ente, agrupado por regime."""
    snap = snapshot_mais_recente()
    if snap is None:
        return {"erro": "sem recortes"}
    sub = snap / "".join(c for c in cnpj if c.isdigit())
    conv = sub / "legado" / "convenio.csv"
    if not conv.exists():
        return {"cnpj": cnpj, "instrumentos": [], "nota": "sem instrumentos no estoque SICONV"}

    prop_valor: dict[str, float] = {}
    prop_csv = sub / "legado" / "proposta.csv"
    if prop_csv.exists():
        with open(prop_csv, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                try:
                    prop_valor[r.get("ID_PROPOSTA")] = float((r.get("VL_GLOBAL_PROP") or "0").replace(",", "."))
                except ValueError:
                    pass

    saida = []
    with conectar() as con:
        with open(conv, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                if (r.get("INSTRUMENTO_ATIVO") or "").upper() != "SIM":
                    continue
                assin = _data_br(r.get("DIA_ASSIN_CONV"))
                ref = assin or date.today()
                valor = prop_valor.get(r.get("ID_PROPOSTA"))
                regime, base_regime = _regime(assin, valor, _teto_simplificado(con, ref))
                itens = []
                for texto, parametro in ITENS["comum"] + ITENS[regime]:
                    base = None
                    if parametro:
                        # No simplificado, a PC 28/2024 aplica a PC 33/2023 de forma
                        # SUBSIDIÁRIA (art. 13) — daí o fallback para completo_pc33.
                        reg = (regra_vigente(con, parametro, regime, ref)
                               or (regra_vigente(con, parametro, "completo_pc33", ref)
                                   if regime == "simplificado_pc28" else None))
                        if reg:
                            v = reg["valor"]
                            quanto = v.get("dias") and f"{v['dias']} dias" or (v.get("anos") and f"{v['anos']} anos")
                            base = f"{reg['base_legal']}" + (f" — {quanto}" if quanto else "")
                    itens.append({"item": texto, "base_legal": base})
                apres = (regra_vigente(con, "prazo_prestacao_contas_apresentacao", regime, ref)
                         or (regra_vigente(con, "prazo_prestacao_contas_apresentacao", "completo_pc33", ref)
                             if regime == "simplificado_pc28" else None))
                saida.append({
                    "nr_convenio": r.get("NR_CONVENIO"), "situacao": r.get("SIT_CONVENIO"),
                    "assinatura": r.get("DIA_ASSIN_CONV"), "fim_vigencia": r.get("DIA_FIM_VIGENC_CONV"),
                    "limite_prestacao": r.get("DIA_LIMITE_PREST_CONTAS"),
                    "valor_global": valor, "regime": regime, "base_regime": base_regime,
                    "prazo_apresentacao": (apres or {}).get("valor", {}).get("dias"),
                    "prazo_base_legal": (apres or {}).get("base_legal"),
                    "checklist": itens,
                })
    return {"cnpj": cnpj, "ente": ROTULOS.get(cnpj, cnpj), "instrumentos": saida}


def _planos_sem_relatorio(sub: Path) -> list[dict]:
    cj = sub / "carteira.json"
    if not cj.exists():
        return []
    return json.loads(cj.read_text(encoding="utf-8")).get("especiais", {}).get("sem_relatorio_2020_2024", [])


def _linhas_gz(caminho: Path):
    if not caminho.exists():
        return
    with gzip.open(caminho, "rt", encoding="utf-8") as fh:
        for l in fh:
            yield json.loads(l)


def relatorio_gestao_pix(cnpj: str) -> dict:
    """Rascunho do Relatório de Gestão (transferências especiais) para os planos
    2020–2024 sem relatório — o conteúdo sai pronto para conferir e protocolar."""
    snap = snapshot_mais_recente()
    if snap is None:
        return {"erro": "sem recortes"}
    doc = "".join(c for c in cnpj if c.isdigit())
    sub = snap / doc
    pendentes = _planos_sem_relatorio(sub)
    planos = {str(p.get("codigo_plano_acao")): p for p in _linhas_gz(sub / "especiais" / "planos_acao.jsonl.gz")}
    ente = ROTULOS.get(doc, doc)

    with conectar() as con:
        multa = regra_vigente(con, "pix_multa_diaria_pendencia", "especiais", date.today())
        capital = regra_vigente(con, "pix_capital_minimo", "especiais", date.today())
        ciclo = regra_vigente(con, "pix_relatorio_gestao_estoque", "especiais", date.today())

    rascunhos = []
    for p in pendentes:
        cod = str(p.get("codigo"))
        pl = planos.get(cod, {})
        custeio = float(pl.get("valor_custeio_plano_acao") or 0)
        invest = float(pl.get("valor_investimento_plano_acao") or 0)
        total = custeio + invest
        pct_capital = round(100 * invest / total, 1) if total else None
        minimo = float((capital or {}).get("valor", {}).get("percentual") or 70)
        rascunhos.append({
            "plano": cod, "ano": p.get("ano"), "situacao": p.get("situacao"),
            "valor_custeio": custeio, "valor_investimento": invest, "valor_total": total,
            "percentual_capital": pct_capital,
            "alerta_capital": (pct_capital is not None and pct_capital < minimo),
            "parlamentar": pl.get("nome_parlamentar_emenda_plano_acao"),
            "emenda": pl.get("numero_emenda_parlamentar_plano_acao"),
            "objeto": pl.get("nome_objeto") or pl.get("detalhamento_objeto"),
            "banco": pl.get("nome_banco_plano_acao"), "agencia": pl.get("numero_agencia_plano_acao"),
            "conta": pl.get("numero_conta_plano_acao"),
            "a_preencher": [
                "Valor executado no período (empenhado/liquidado/pago)",
                "Saldo em conta e rendimentos de aplicação",
                "Descrição das ações realizadas e do estágio de execução",
                "Justificativa se a execução não atingiu o previsto",
                "Declaração do gestor (documentação comprobatória arquivada)",
            ],
        })

    return {
        "cnpj": doc, "ente": ente,
        "pendentes": len(rascunhos),
        "prazo_ciclo": (ciclo or {}).get("valor", {}).get("prazo"),
        "base_legal": (ciclo or {}).get("base_legal"),
        "risco": (f"multa de {(multa or {}).get('valor', {}).get('percentual_dia', 1)}%/dia "
                  f"por pendência — {(multa or {}).get('base_legal', 'IN TCU 93/2024')}"),
        "regra_capital": f"mínimo {minimo:.0f}% em despesas de capital — {(capital or {}).get('base_legal', 'CF art. 166-A §5º')}",
        "rascunhos": rascunhos,
    }


def markdown_relatorio(dados: dict) -> str:
    """Versão colável/imprimível do rascunho (sem PDF, por decisão de simplicidade)."""
    L = [f"# Relatório de Gestão — Transferências Especiais", "",
         f"**Ente:** {dados.get('ente')} · CNPJ {dados.get('cnpj')}",
         f"**Planos pendentes (2020–2024):** {dados.get('pendentes')}",
         f"**Prazo do ciclo:** {dados.get('prazo_ciclo') or '—'} · {dados.get('base_legal') or ''}",
         f"**Risco:** {dados.get('risco')}", f"**Regra de capital:** {dados.get('regra_capital')}", ""]
    for r in dados.get("rascunhos", []):
        L += [f"## Plano de ação {r['plano']} ({r['ano']}) — {r['situacao']}", ""]
        if r.get("objeto"):
            L.append(f"**Objeto:** {r['objeto']}")
        if r.get("parlamentar"):
            L.append(f"**Emenda:** {r.get('emenda') or '—'} · {r['parlamentar']}")
        L.append(f"**Valores:** custeio R$ {r['valor_custeio']:,.2f} · investimento R$ {r['valor_investimento']:,.2f} "
                 f"· total R$ {r['valor_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        if r["percentual_capital"] is not None:
            marca = "🔴 ABAIXO DO MÍNIMO" if r["alerta_capital"] else "✓"
            L.append(f"**Capital:** {r['percentual_capital']}% {marca}")
        if r.get("banco"):
            L.append(f"**Conta específica:** {r['banco']} ag. {r.get('agencia') or '—'} c/c {r.get('conta') or '—'}")
        L += ["", "**A preencher antes de protocolar:**"]
        L += [f"- [ ] {x}" for x in r["a_preencher"]]
        L.append("")
    return "\n".join(L)
