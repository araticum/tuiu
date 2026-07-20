"""Funil de proposta regime-aware — a metade UPSTREAM da inteligência de órgão.

Enquanto base_rates.py mede o desfecho DEPOIS da celebração, este mede a odds
ANTES: de cada proposta de OSC a um órgão, quantas aprovam vs reprovam. É a
pergunta que o cliente faz primeiro — "a qual órgão levo isto?" — e a dispersão
é enorme (medido: ~92% de reprovação na Agric. Familiar, ~36% no Esporte).

Diferença para o desfecho: o regime NOVO (PC 33) É preditivo aqui. Proposta é
decidida em meses, não em anos; há dezenas de milhares de resolvidas no ciclo
atual. Então `preditivo` vale por LINHA (n_resolvidas>=100), e a linha NOVO é a
odds sob a regra de hoje — o número que o cliente de fato usa.

Roda no host (lake DuckDB + tuiu-db). Sob demanda, junto do base_rates.py.

    python ingest/lake/funil.py            # computa e carrega
    python ingest/lake/funil.py --so-ver   # imprime, não grava
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

LAKE = "/mnt/dados-gov/transferegov-lake/lake.duckdb"
CORTE = "DATE '2023-09-01'"   # Decreto 11.531 + PC 33/2023
MIN_PREDITIVO = 100           # abaixo disso a taxa é ruído
MIN_LINHA = 30               # não emite órgão com menos que isso resolvido

# DIA_PROPOSTA é dd/mm/yyyy e parseia 100% (probado). Regime pela DATA da
# proposta (não da celebração — a proposta pode nunca virar convênio).
# "resolvida" = já aprovada OU reprovada; em_curso não entra na taxa.
# `min_linha` injetável para os testes (fixture pequena).
def _sql(min_linha: int = MIN_LINHA) -> str:
    return f"""
WITH prop AS (
    SELECT p.desc_orgao_sup AS orgao,
        CASE WHEN try_strptime(p.dia_proposta,'%d/%m/%Y') < {CORTE}
             THEN 'legado_pi424' ELSE 'novo_pc33' END AS regime,
        upper(p.sit_proposta) AS sit,
        (c.nr_convenio IS NOT NULL) AS virou_conv
    FROM proposta p
    LEFT JOIN convenio c ON c.id_proposta = p.id_proposta
    WHERE p.natureza_juridica = 'Organização da Sociedade Civil'
      AND p.desc_orgao_sup IS NOT NULL
      AND try_strptime(p.dia_proposta,'%d/%m/%Y') IS NOT NULL
),
cls AS (
    SELECT orgao, regime,
        CASE
          WHEN virou_conv OR sit LIKE '%APROVAD%' OR sit LIKE '%EXECU%'
               OR sit LIKE '%CELEBR%' OR sit LIKE '%ASSINAD%' THEN 'aprovada'
          WHEN sit LIKE '%REPROV%' OR sit LIKE '%REJEIT%' OR sit LIKE '%IMPEDIMENTO%'
               OR sit LIKE '%INDEFER%' OR sit LIKE '%ELIMINAD%' THEN 'reprovada'
          ELSE 'em_curso' END AS desf
    FROM prop
)
SELECT orgao, regime,
    count(*) AS n_total,
    count(*) FILTER (WHERE desf<>'em_curso') AS n_resolvidas,
    round(100.0*count(*) FILTER (WHERE desf='aprovada')
          / nullif(count(*) FILTER (WHERE desf<>'em_curso'),0),1) AS pct_aprovada,
    round(100.0*count(*) FILTER (WHERE desf='reprovada')
          / nullif(count(*) FILTER (WHERE desf<>'em_curso'),0),1) AS pct_reprovada,
    round(100.0*count(*) FILTER (WHERE desf='em_curso')/count(*),1) AS pct_em_curso
FROM cls GROUP BY 1,2
HAVING count(*) FILTER (WHERE desf<>'em_curso') >= {min_linha}
ORDER BY regime, n_resolvidas DESC
"""


def computar_em(con, min_linha: int = MIN_LINHA) -> list[tuple]:
    """Classificação do funil sobre uma conexão DuckDB qualquer (lake ou fixture)."""
    return con.execute(_sql(min_linha=min_linha)).fetchall()


def computar() -> list[tuple]:
    import duckdb
    con = duckdb.connect(LAKE, read_only=True)
    try:
        return computar_em(con)
    finally:
        con.close()


def carregar(linhas: list[tuple]) -> None:
    from app.db import conectar, migrar
    migrar()
    with conectar() as con:
        con.execute("TRUNCATE funil_orgao")
        for (orgao, regime, n_total, n_res, apr, rep, curso) in linhas:
            con.execute(
                "INSERT INTO funil_orgao (orgao, regime, n_total, n_resolvidas,"
                " pct_aprovada, pct_reprovada, pct_em_curso, preditivo)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (orgao, regime, n_total, n_res, apr, rep, curso,
                 n_res >= MIN_PREDITIVO))
        con.commit()
        total = con.execute("SELECT count(*) FROM funil_orgao").fetchone()[0]
    print(f"carregadas {total} linhas em funil_orgao")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--so-ver", action="store_true", help="imprime, não grava")
    args = ap.parse_args()

    linhas = computar()
    print(f"{'órgão':<46} {'regime':<13} {'n_res':>7} {'aprov':>6} {'reprov':>7}")
    for (orgao, regime, n_total, n_res, apr, rep, curso) in linhas[:24]:
        print(f"  {(orgao or '')[:44]:<44} {regime:<13} {n_res:>7,} {apr or 0:>5}% {rep or 0:>6}%")
    if not args.so_ver:
        carregar(linhas)


if __name__ == "__main__":
    main()
