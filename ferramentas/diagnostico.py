"""Diagnóstico de um terceiro no Transferegov — a partir de dados PÚBLICOS.

Por que existe: a casa ainda não é operadora cadastrada de ninguém, então nada
chega por e-mail nem por acesso logado. Mas TUDO que o produto faz roda sobre
dado aberto — logo dá para levantar a situação completa de um candidato a
cliente **antes** de qualquer contrato, sem pedir nada a ele. Serve como peça
de prospecção e como primeira entrega de serviço.

Não escreve na área dos clientes: sai em `data/diagnosticos/<data>/<cnpj>/`.

Uso:
    py -3 ferramentas/diagnostico.py 27250267000193
    py -3 ferramentas/diagnostico.py 27250267000193 --sem-legado
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(RAIZ / "ingest" / "transferegov_g2"))
sys.path.insert(0, str(RAIZ / "ingest" / "transparencia"))

from app.motor_prazos import _marcos_g2, _farol  # noqa: E402
from recorte_ente import carteira, recortar  # noqa: E402
from regularidade_terceiro import consultar as consultar_sancoes  # noqa: E402


def _brl(v) -> str:
    return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar(cnpj: str, workers: int = 6) -> dict:
    doc = "".join(c for c in cnpj if c.isdigit())
    destino = RAIZ / "data" / "diagnosticos" / date.today().isoformat() / doc
    destino.mkdir(parents=True, exist_ok=True)

    dados = recortar(doc, destino, workers)
    from recorte_ente import data_atualizacao
    cj, _md = carteira(doc, dados, data_atualizacao())
    (destino / "carteira.json").write_text(json.dumps(cj, ensure_ascii=False, indent=2), encoding="utf-8")

    hoje = date.today()
    marcos = _marcos_g2(doc, cj.get("nome") or doc, destino, hoje)
    sancoes = consultar_sancoes(doc)

    por_farol = {}
    for m in marcos:
        por_farol.setdefault(m["farol"], []).append(m)

    p = cj.get("parcerias", {})
    diag = {
        "cnpj": doc, "nome": cj.get("nome"), "uf": cj.get("uf"), "municipio": cj.get("municipio"),
        "gerado_em": hoje.isoformat(), "dados_de": cj.get("data_atualizacao_api"),
        "carteira": {
            "propostas": p.get("propostas", 0), "por_situacao": p.get("por_situacao", {}),
            "instrumentos": p.get("instrumentos", 0), "contas": p.get("contas", 0),
            "saldo": (p.get("saldo_conta_corrente", 0) or 0) + (p.get("saldo_investimento", 0) or 0),
            "empenhos": p.get("empenhos", 0), "ordens_pagamento": p.get("ordens_pagamento", 0),
            "lancamentos": p.get("lancamentos_extrato", 0),
        },
        "sancoes": {"impedido": sancoes["impedido"],
                    "fontes": {k: v["registros"] for k, v in sancoes["fontes"].items()}},
        "prazos": {"total": len(marcos),
                   "acao_imediata": len(por_farol.get("acao_imediata", [])),
                   "vencido": len(por_farol.get("vencido", [])),
                   "atencao": len(por_farol.get("atencao", []))},
        "achados": [],
    }

    for m in sorted(marcos, key=lambda x: ({"acao_imediata": 0, "vencido": 1, "atencao": 2}.get(x["farol"], 3),
                                           x["data_limite"] or date(2100, 1, 1))):
        if m["farol"] == "ok":
            continue
        diag["achados"].append({
            "farol": m["farol"], "tipo": m["tipo"],
            "prazo": m["data_limite"].isoformat() if m["data_limite"] else None,
            "descricao": m["descricao"], "base_legal": m["base_legal"],
        })

    (destino / "diagnostico.json").write_text(json.dumps(diag, ensure_ascii=False, indent=2), encoding="utf-8")
    (destino / "diagnostico.md").write_text(markdown(diag), encoding="utf-8")
    return {**diag, "destino": str(destino)}


def markdown(d: dict) -> str:
    c, s, pz = d["carteira"], d["sancoes"], d["prazos"]
    L = [f"# Situação de {d['nome']} no Transferegov.br", "",
         f"CNPJ {d['cnpj']} · {d.get('municipio') or '—'}/{d.get('uf') or '—'} · "
         f"levantado em {d['gerado_em'][8:]}/{d['gerado_em'][5:7]}/{d['gerado_em'][:4]} "
         f"(dados oficiais de {str(d.get('dados_de'))[:10]})", "",
         "> Levantamento feito **apenas com dados públicos oficiais** do Transferegov.br e do "
         "Portal da Transparência — sem nenhum acesso ao sistema da entidade.", "",
         "## Carteira", "",
         f"- Propostas: **{c['propostas']}** — " + (", ".join(f"{k}: {v}" for k, v in c["por_situacao"].items()) or "—"),
         f"- Instrumentos: **{c['instrumentos']}** · contas: {c['contas']} · saldo: **{_brl(c['saldo'])}**",
         f"- Execução: {c['empenhos']} empenho(s) → {c['ordens_pagamento']} ordem(ns) de pagamento · "
         f"{c['lancamentos']} lançamento(s) de extrato", "",
         "## Regularidade (impedimentos)", "",
         ("- 🔴 **CONSTA IMPEDIMENTO** — " if s["impedido"] else "- ✅ Sem impedimento nos cadastros federais — ")
         + ", ".join(f"{k.upper()}: {v}" for k, v in s["fontes"].items()),
         "  (CEPIM = entidade privada impedida de celebrar; CEIS = inidônea/suspensa; CNEP = Lei 12.846)", "",
         "## Pontos de atenção encontrados", "",
         f"**{pz['acao_imediata']}** exigem ação imediata · **{pz['vencido']}** vencidos · "
         f"**{pz['atencao']}** vencem em até 90 dias", ""]

    icone = {"acao_imediata": "🔴", "vencido": "🔴", "atencao": "🟡"}
    for a in d["achados"][:25]:
        quando = f" — prazo {a['prazo'][8:]}/{a['prazo'][5:7]}/{a['prazo'][:4]}" if a["prazo"] else ""
        L.append(f"- {icone.get(a['farol'], '•')} {a['descricao']}{quando}")
        L.append(f"  <sub>{a['base_legal']}</sub>")
    if len(d["achados"]) > 25:
        L.append(f"- … e mais {len(d['achados']) - 25} ponto(s).")
    L += ["", "---", "",
          "Este levantamento se atualiza sozinho todo dia útil e cada ponto acima vira alerta com prazo "
          "e base legal. Araticum — gestão de transferências da União."]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("cnpj", nargs="+")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    for cnpj in args.cnpj:
        d = gerar(cnpj, args.workers)
        print(f"{d['nome']} ({d['cnpj']}): propostas={d['carteira']['propostas']} "
              f"acao_imediata={d['prazos']['acao_imediata']} vencidos={d['prazos']['vencido']} "
              f"impedido={d['sancoes']['impedido']} -> {d['destino']}")


if __name__ == "__main__":
    main()
