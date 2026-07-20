"""Funil por AÇÃO orçamentária — drill-down do funil_orgao onde o órgão é grosso.

O órgão esconde variação enorme: dentro de Agricultura a aprovação de OSC vai de
0% a 100% conforme a AÇÃO. A ação é o que o cliente escolhe ao montar a proposta,
e é a chave estável (código do orçamento, recorre entre anos) — diferente do
cod_programa (anual) e do nome (mojibake).

⚠️ Dois vieses de dado que este motor corrige (medidos):
  - a tabela `programa` do lake vem multiplicada ~405× → DEDUP por id_programa;
  - uma proposta liga a >1 programa → conta id_proposta DISTINTO.
Sem isso o número infla ordens de grandeza (184 mil "aprovadas" onde há ~450).

Roda no host (lake + tuiu-db), sob demanda, junto de funil.py.

    python ingest/lake/funil_acao.py            # computa e carrega
    python ingest/lake/funil_acao.py --so-ver   # imprime, não grava
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

LAKE = "/mnt/dados-gov/transferegov-lake/lake.duckdb"
CORTE = "DATE '2023-09-01'"
MIN_PREDITIVO = 80           # ação é mais fina que órgão; teto menor
MIN_LINHA = 40
# ações-placeholder ("sem ação"): não são ação real, poluiriam o ranking
ACAO_NULA = "('00000000','00000001')"


def _sql(min_linha: int = MIN_LINHA) -> str:
    return f"""
WITH prog AS (  -- dedup da tabela programa (vem ~405x) e exclui ação-placeholder
    SELECT id_programa, any_value(acao_orcamentaria) acao, any_value(nome_programa) nome
    FROM programa
    WHERE acao_orcamentaria IS NOT NULL AND acao_orcamentaria NOT IN {ACAO_NULA}
    GROUP BY id_programa
),
base AS (
    SELECT p.desc_orgao_sup orgao, pr.acao, pr.nome,
        CASE WHEN try_strptime(p.dia_proposta,'%d/%m/%Y') < {CORTE}
             THEN 'legado_pi424' ELSE 'novo_pc33' END regime,
        p.id_proposta, upper(p.sit_proposta) sit,
        (c.nr_convenio IS NOT NULL) virou_conv
    FROM proposta p
    JOIN programa_proposta x ON x.id_proposta = p.id_proposta
    JOIN prog pr ON pr.id_programa = x.id_programa
    LEFT JOIN convenio c ON c.id_proposta = p.id_proposta
    WHERE p.natureza_juridica = 'Organização da Sociedade Civil'
      AND p.desc_orgao_sup IS NOT NULL
      AND try_strptime(p.dia_proposta,'%d/%m/%Y') IS NOT NULL
),
cls AS (  -- 1 linha por proposta DISTINTA na (órgão, ação, regime)
    SELECT DISTINCT orgao, acao, regime, id_proposta,
        CASE
          WHEN virou_conv OR sit LIKE '%APROVAD%' OR sit LIKE '%EXECU%'
               OR sit LIKE '%CELEBR%' OR sit LIKE '%ASSINAD%' THEN 'aprovada'
          WHEN sit LIKE '%REPROV%' OR sit LIKE '%REJEIT%' OR sit LIKE '%IMPEDIMENTO%'
               OR sit LIKE '%INDEFER%' OR sit LIKE '%ELIMINAD%' THEN 'reprovada'
          ELSE 'em_curso' END AS desf
    FROM base
),
nomes AS (SELECT orgao, acao, any_value(nome) nome FROM base GROUP BY orgao, acao),
agg AS (
    SELECT orgao, acao, regime,
        count(*) n_total,
        count(*) FILTER (WHERE desf<>'em_curso') n_res,
        round(100.0*count(*) FILTER (WHERE desf='aprovada')
              / nullif(count(*) FILTER (WHERE desf<>'em_curso'),0),1) pct_aprovada,
        round(100.0*count(*) FILTER (WHERE desf='reprovada')
              / nullif(count(*) FILTER (WHERE desf<>'em_curso'),0),1) pct_reprovada
    FROM cls GROUP BY 1,2,3
    HAVING count(*) FILTER (WHERE desf<>'em_curso') >= {min_linha}
)
SELECT a.orgao, a.acao, n.nome, a.regime, a.n_total, a.n_res, a.pct_aprovada, a.pct_reprovada
FROM agg a LEFT JOIN nomes n USING (orgao, acao)
ORDER BY a.regime DESC, a.orgao, a.pct_aprovada
"""


def _limpar_nome(s: str | None) -> str | None:
    """Higieniza o rótulo: remove replacement chars e '??' de mojibake."""
    if not s:
        return None
    s = re.sub(r"�+", "", s)          # �
    s = re.sub(r"\?{2,}", "", s)           # ?? que sobrou de çã/ão corrompidos
    s = re.sub(r"\s+", " ", s).strip(" -–")
    return s or None


def computar_em(con, min_linha: int = MIN_LINHA) -> list[tuple]:
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
        con.execute("TRUNCATE funil_acao")
        for (orgao, acao, nome, regime, n_total, n_res, apr, rep) in linhas:
            con.execute(
                "INSERT INTO funil_acao (orgao, acao, nome, regime, n_total, n_resolvidas,"
                " pct_aprovada, pct_reprovada, preditivo)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (orgao, acao, _limpar_nome(nome), regime, n_total, n_res, apr, rep,
                 n_res >= MIN_PREDITIVO))
        con.commit()
        total = con.execute("SELECT count(*) FROM funil_acao").fetchone()[0]
    print(f"carregadas {total} linhas em funil_acao")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--so-ver", action="store_true", help="imprime, não grava")
    args = ap.parse_args()
    linhas = computar()
    print(f"{'órgão':<30} {'ação':<10} {'regime':<13} {'n':>5} {'aprova':>6}")
    for (orgao, acao, nome, regime, n_total, n_res, apr, rep) in linhas[:26]:
        print(f"  {(orgao or '')[:28]:<28} {acao:<10} {regime:<13} {n_res:>5} {apr or 0:>5}%")
    if not args.so_ver:
        carregar(linhas)


if __name__ == "__main__":
    main()
