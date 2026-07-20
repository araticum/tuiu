"""Latência de análise do concedente — a 3ª face da inteligência de órgão.

Mede, por PARES DE EVENTO (não confia no DIAS_HISTORICO_SIT pré-calculado), o
tempo real entre a proposta ser enviada para análise e a decisão do concedente.
O art.97 da PC 33/2023 dá 60 dias (informatizado); o ciclo NOVO já estoura na
mediana (16 órgãos, ~80d de mediana das medianas). É a munição do cliente para
cobrar o concedente citando o artigo.

⚠️ DIA_HISTORICO_SIT é 'dd/mm/yyyy HH:MM:SS' (TEM hora) — parsear sem a hora
retorna NULL e zera o resultado. Erro pego na validação.

Roda no host (lake + tuiu-db), sob demanda, junto de base_rates.py/funil.py.

    python ingest/lake/latencia.py            # computa e carrega
    python ingest/lake/latencia.py --so-ver   # imprime, não grava
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

LAKE = "/mnt/dados-gov/transferegov-lake/lake.duckdb"
CORTE = "DATE '2023-09-01'"
LIMITE_ART97 = 60            # dias, art.97 informatizado (Transferegov é informatizado)
MIN_PREDITIVO = 100
MIN_LINHA = 50               # mediana precisa de massa

SQL = f"""
WITH ev AS (
  SELECT h.id_proposta, upper(h.historico_sit) sit,
         try_strptime(h.dia_historico_sit,'%d/%m/%Y %H:%M:%S') dt
  FROM historico_situacao h
  WHERE h.id_proposta IS NOT NULL
),
t0 AS (SELECT id_proposta, min(dt) ini FROM ev
       WHERE sit LIKE '%ENVIADA_ANALISE%' AND dt IS NOT NULL GROUP BY 1),
t1 AS (
  SELECT e.id_proposta, min(e.dt) fim
  FROM ev e JOIN t0 ON t0.id_proposta = e.id_proposta
  WHERE (e.sit LIKE '%APROVADO%' OR e.sit LIKE 'PROPOSTA_REPROVADA%') AND e.dt >= t0.ini
  GROUP BY 1
),
dur AS (
  SELECT p.desc_orgao_sup orgao,
     CASE WHEN try_strptime(p.dia_proposta,'%d/%m/%Y') < {CORTE}
          THEN 'legado_pi424' ELSE 'novo_pc33' END regime,
     date_diff('day', t0.ini, t1.fim) dias
  FROM t0 JOIN t1 USING (id_proposta)
  JOIN proposta p ON p.id_proposta = t0.id_proposta
  WHERE p.natureza_juridica = 'Organização da Sociedade Civil' AND p.desc_orgao_sup IS NOT NULL
    AND date_diff('day', t0.ini, t1.fim) BETWEEN 0 AND 3650
)
SELECT regime, orgao, count(*) n,
   CAST(median(dias) AS INT) mediana,
   CAST(quantile_cont(dias, 0.9) AS INT) p90,
   round(100.0*count(*) FILTER (WHERE dias > {LIMITE_ART97})/count(*), 0) pct_acima
FROM dur GROUP BY 1,2 HAVING count(*) >= {MIN_LINHA}
ORDER BY regime DESC, mediana DESC
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
        con.execute("TRUNCATE latencia_orgao")
        for (regime, orgao, n, med, p90, acima) in linhas:
            limite = LIMITE_ART97 if regime == "novo_pc33" else None
            con.execute(
                "INSERT INTO latencia_orgao (orgao, regime, n, mediana_dias, p90_dias,"
                " pct_acima_limite, limite_legal, preditivo)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (orgao, regime, n, med, p90, acima, limite, n >= MIN_PREDITIVO))
        con.commit()
        total = con.execute("SELECT count(*) FROM latencia_orgao").fetchone()[0]
    print(f"carregadas {total} linhas em latencia_orgao")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--so-ver", action="store_true", help="imprime, não grava")
    args = ap.parse_args()

    linhas = computar()
    print(f"{'regime':<13} {'med':>4} {'p90':>4} {'>60d':>5} {'n':>6}  órgão")
    for (regime, orgao, n, med, p90, acima) in linhas[:30]:
        print(f"  {regime:<13} {med:>4} {p90:>4} {acima:>4.0f}% {n:>6,}  {(orgao or '')[:40]}")
    if not args.so_ver:
        carregar(linhas)


if __name__ == "__main__":
    main()
