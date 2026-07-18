"""Ranking de prospects — terceiros com mais dor, a partir do dump nacional.

Só entidades PRIVADAS (o público do Tuiú). Pontua o que é dor real e visível no
dado aberto:
    +3  proposta parada em análise há >= 180 dias
    +2  proposta parada em análise há >= 60 dias
    +2  proposta Em Complementação (bola com o convenente)
    +1  proposta Em Elaboração parada
    +1  a cada R$ 1 mi de saldo em conta (dinheiro parado rende cobrança)
Exclui quem já é cliente.

Uso:
    py -3 ferramentas/prospects.py                 # top 20
    py -3 ferramentas/prospects.py --top 5 --gerar # + gera o diagnóstico dos 5
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PRIVADAS = ("Associa", "Privada", "Cooperativa", "Sociedade", "Empres", "Organiza",
            "Serviço Social", "Servico Social", "Religiosa", "Fundação Privada", "Fundacao Privada")
JA_CLIENTES = {"20069629000103", "37113180000128", "31883355000108"}


def _dump_recente() -> Path:
    base = RAIZ / "data" / "parcerias"
    for d in sorted(base.glob("*"), reverse=True):
        if (d / "proposta.jsonl.gz").exists():
            return d
    sys.exit("sem dump nacional em data/parcerias — rode o extrator g2 primeiro")


def ranquear() -> list[dict]:
    dump = _dump_recente()
    hoje = date.today()
    entes: dict[str, dict] = {}

    for linha in gzip.open(dump / "proposta.jsonl.gz", "rt", encoding="utf-8"):
        p = json.loads(linha)
        nat = p.get("nm_natureza_juridica") or ""
        if not any(t.lower() in nat.lower() for t in PRIVADAS):
            continue
        cnpj = (p.get("cnpj_ente_recebedor") or "").strip()
        if not cnpj or cnpj in JA_CLIENTES:
            continue
        e = entes.setdefault(cnpj, {
            "cnpj": cnpj, "nome": p.get("nm_ente_recebedor"), "natureza": nat,
            "uf": p.get("sg_uf_recebedor"), "municipio": p.get("nm_municipio_recebedor"),
            "propostas": 0, "paradas_180": 0, "paradas_60": 0, "complementacao": 0,
            "elaboracao": 0, "pontos": 0, "dias_max": 0,
        })
        e["propostas"] += 1
        sit = str(p.get("situacao_proposta") or "")

        if "Análise" in sit or "Analise" in sit:
            try:
                envio = datetime.fromisoformat(str(p.get("dt_envio_analise"))[:10]).date()
                dias = (hoje - envio).days
            except (ValueError, TypeError):
                dias = 0
            e["dias_max"] = max(e["dias_max"], dias)
            if dias >= 180:
                e["paradas_180"] += 1
                e["pontos"] += 3
            elif dias >= 60:
                e["paradas_60"] += 1
                e["pontos"] += 2
        elif "Complementa" in sit:
            e["complementacao"] += 1
            e["pontos"] += 2
        elif "Elabora" in sit:
            e["elaboracao"] += 1
            e["pontos"] += 1

    # dinheiro parado em conta soma pontos (sinal de execução travada)
    contas = dump / "parceria-conta.jsonl.gz"
    if contas.exists():
        props = {}
        for linha in gzip.open(dump / "proposta.jsonl.gz", "rt", encoding="utf-8"):
            p = json.loads(linha)
            props[p.get("id_proposta")] = (p.get("cnpj_ente_recebedor") or "").strip()
        parc = {}
        if (dump / "parceria.jsonl.gz").exists():
            for linha in gzip.open(dump / "parceria.jsonl.gz", "rt", encoding="utf-8"):
                x = json.loads(linha)
                parc[x.get("id_parceria")] = props.get(x.get("id_proposta"))
        for linha in gzip.open(contas, "rt", encoding="utf-8"):
            c = json.loads(linha)
            cnpj = parc.get(c.get("id_parceria"))
            if cnpj in entes:
                saldo = float(c.get("vl_saldo_conta_corrente") or 0) + float(c.get("vl_saldo_conta_investimento") or 0)
                entes[cnpj].setdefault("saldo", 0.0)
                entes[cnpj]["saldo"] += saldo
    for e in entes.values():
        e.setdefault("saldo", 0.0)
        e["pontos"] += int(e["saldo"] // 1_000_000)

    return sorted(entes.values(), key=lambda e: (-e["pontos"], -e["propostas"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--gerar", action="store_true", help="gera o diagnóstico dos listados")
    args = ap.parse_args()

    r = ranquear()
    print(f"{'pts':>4} {'propostas':>9} {'>180d':>6} {'>60d':>5} {'compl':>6} {'saldo':>14}  ente")
    for e in r[:args.top]:
        print(f"{e['pontos']:>4} {e['propostas']:>9} {e['paradas_180']:>6} {e['paradas_60']:>5} "
              f"{e['complementacao']:>6} {e['saldo']:>14,.0f}  {(e['nome'] or '?')[:44]} "
              f"({e['cnpj']}) {e['municipio'] or '?'}/{e['uf'] or '?'}")

    saida = RAIZ / "data" / "diagnosticos" / f"prospects-{date.today().isoformat()}.json"
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(r[:200], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nranking completo ({len(r)} entidades) -> {saida}")

    if args.gerar:
        sys.path.insert(0, str(RAIZ / "ferramentas"))
        from diagnostico import gerar
        print()
        for e in r[:args.top]:
            d = gerar(e["cnpj"])
            print(f"  diagnóstico: {d['nome'][:40]} -> acao_imediata={d['prazos']['acao_imediata']} "
                  f"vencidos={d['prazos']['vencido']}")


if __name__ == "__main__":
    main()
