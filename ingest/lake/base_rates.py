"""Motor de base rates regime-aware — computa sobre o lake, carrega no tuiu-db.

Destila 18 anos de SICONV em probabilidade de desfecho por órgão, SEGMENTADA POR
REGIME. A segmentação é o produto: os finais existem quase só no regime legado
(PI 424) — o ciclo novo é jovem demais —, então a previsão vem do legado e a
coluna `regime` diz sob qual lei. Um concorrente que agrega cru afirma "esse
órgão reprova X%" sob uma regra que já morreu.

Roda no host (onde vivem o lake DuckDB e o tuiu-db). Não entra na cadeia diária —
é recomputado sob demanda, quando o estoque muda.

    python ingest/lake/base_rates.py            # computa e carrega
    python ingest/lake/base_rates.py --so-ver   # imprime, não grava
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

LAKE = "/mnt/dados-gov/transferegov-lake/lake.duckdb"
CORTE = "DATE '2023-09-01'"   # Decreto 11.531 + PC 33/2023
MIN_PREDITIVO = 100           # abaixo disso a taxa é ruído, não previsão

# Classificação do SIT_CONVENIO em desfecho. Ordem importa: ressalva antes de
# sucesso (é um sucesso qualificado), morte pelos terminais negativos.
SQL = f"""
WITH osc AS (
    SELECT id_proposta, desc_orgao_sup AS orgao FROM proposta
    WHERE natureza_juridica = 'Organização da Sociedade Civil' AND desc_orgao_sup IS NOT NULL
),
conv AS (
    SELECT o.orgao,
        CASE WHEN try_strptime(c.dia_assin_conv,'%d/%m/%Y') < {CORTE}
             THEN 'legado_pi424' ELSE 'novo_pc33' END AS regime,
        CASE
          WHEN c.sit_convenio ILIKE '%Ressalva%' THEN 'ressalva'
          WHEN c.sit_convenio ILIKE '%Aprovada%' OR c.sit_convenio ILIKE '%Concluíd%'
               OR c.sit_convenio ILIKE '%Comprovada%' THEN 'sucesso'
          WHEN c.sit_convenio ILIKE '%Anulad%' OR c.sit_convenio ILIKE '%Cancelad%'
               OR c.sit_convenio ILIKE '%Rejeitad%' OR c.sit_convenio ILIKE '%Inadimpl%'
               OR c.sit_convenio ILIKE '%Tomada de Contas%' THEN 'morte'
          ELSE 'em_curso' END AS desfecho
    FROM convenio c JOIN osc o USING (id_proposta)
),
-- comportamento do concedente: prestações entregues e paradas na análise dele
parada AS (
    SELECT o.orgao,
        CASE WHEN try_strptime(c.dia_assin_conv,'%d/%m/%Y') < {CORTE}
             THEN 'legado_pi424' ELSE 'novo_pc33' END AS regime,
        TRY_CAST(h.dias_historico_sit AS BIGINT) AS dias
    FROM historico_situacao h
    JOIN convenio c ON c.nr_convenio = h.nr_convenio
    JOIN osc o ON o.id_proposta = c.id_proposta
    WHERE h.historico_sit LIKE 'PRESTACAO_CONTAS%ANALISE'
),
desf AS (
    SELECT orgao, regime, count(*) n,
        round(100.0*count(*) FILTER (WHERE desfecho='sucesso')/count(*),1) pct_sucesso,
        round(100.0*count(*) FILTER (WHERE desfecho='ressalva')/count(*),1) pct_ressalva,
        round(100.0*count(*) FILTER (WHERE desfecho='morte')/count(*),1) pct_morte,
        round(100.0*count(*) FILTER (WHERE desfecho='em_curso')/count(*),1) pct_em_curso
    FROM conv GROUP BY 1,2
),
par AS (
    SELECT orgao, regime, count(*) paradas, CAST(median(dias) AS BIGINT) mediana
    FROM parada WHERE dias IS NOT NULL GROUP BY 1,2
)
SELECT d.orgao, d.regime, d.n, d.pct_sucesso, d.pct_ressalva, d.pct_morte, d.pct_em_curso,
       COALESCE(p.paradas,0), p.mediana
FROM desf d LEFT JOIN par p USING (orgao, regime)
WHERE d.n >= 30
ORDER BY d.regime, d.n DESC
"""


def computar() -> list[tuple]:
    import duckdb
    con = duckdb.connect(LAKE, read_only=True)
    linhas = con.execute(SQL).fetchall()
    con.close()
    return linhas


def carregar(linhas: list[tuple]) -> None:
    from app.db import conectar, migrar
    migrar()
    with conectar() as con:
        con.execute("TRUNCATE base_rates_orgao")
        for (orgao, regime, n, suc, res, mor, curso, paradas, mediana) in linhas:
            con.execute(
                "INSERT INTO base_rates_orgao (orgao, regime, n, pct_sucesso, pct_ressalva,"
                " pct_morte, pct_em_curso, prestacoes_paradas, mediana_dias_parada, preditivo)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (orgao, regime, n, suc, res, mor, curso, paradas, mediana,
                 regime == "legado_pi424" and n >= MIN_PREDITIVO))
        con.commit()
        total = con.execute("SELECT count(*) FROM base_rates_orgao").fetchone()[0]
    print(f"carregadas {total} linhas em base_rates_orgao")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--so-ver", action="store_true", help="imprime, não grava")
    args = ap.parse_args()

    linhas = computar()
    print(f"{'órgão':<48} {'regime':<13} {'n':>6} {'suc':>5} {'mor':>5} {'parada(med)':>12}")
    for (orgao, regime, n, suc, res, mor, curso, paradas, mediana) in linhas[:20]:
        print(f"  {(orgao or '')[:46]:<46} {regime:<13} {n:>6,} {suc or 0:>4}% {mor or 0:>4}%"
              f" {paradas:>6,}({mediana or 0})")
    if not args.so_ver:
        carregar(linhas)


if __name__ == "__main__":
    main()
