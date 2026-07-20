"""Lake analítico das discricionárias/legais — DuckDB sobre o estoque baixado.

Por que DuckDB e não Postgres: o estoque SICONV descompacta em ~15-20 GB de CSV.
Carregar isso num Postgres seria lento, ocuparia disco e — pior — o `tuiu-db`
mora na raiz de 44 GB junto do `veredas` de PRODUÇÃO. DuckDB consulta o CSV/JSON
NO LUGAR, sem carregar: o arquivo `.duckdb` guarda só definições de VIEW e fica
minúsculo. Consulta analítica (varredura, agregação) é o caso de uso, não OLTP.

Separação de responsabilidade:
  - `tuiu-db` (Postgres, operacional) — a carteira, marcos, fila, contas. Fica.
  - lake (DuckDB, analítico) — o estoque nacional inteiro, para pergunta ampla.

O lake NÃO é tocado pela cadeia diária: é ferramenta de análise sob demanda.

Uso (no host, onde mora o estoque):
    python ingest/lake/construir_lake.py                 # (re)constroi as views
    python ingest/lake/construir_lake.py --consulta "SELECT count(*) FROM convenio"
    python ingest/lake/construir_lake.py --catalogo      # lista tabelas + linhas
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ_LAKE = Path("/mnt/dados-gov/transferegov-lake")
DB = RAIZ_LAKE / "lake.duckdb"
SICONV_CSV = RAIZ_LAKE / "detru" / "siconv"
G2_PARCERIAS = RAIZ_LAKE / "g2" / "parcerias"
G2_ESPECIAIS = RAIZ_LAKE / "g2" / "especiais"
EXTERNOS = RAIZ_LAKE / "externos"


def _duck():
    try:
        import duckdb
    except ImportError:
        sys.exit("duckdb ausente — instale: ./.venv/bin/pip install duckdb")
    return duckdb


def _nome_tabela(caminho: Path, prefixo: str = "") -> str:
    base = caminho.name
    for suf in (".csv", ".jsonl.gz", ".jsonl", ".json.gz"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    base = base.replace("siconv_", "").replace("-", "_").lower()
    return (prefixo + base) if prefixo else base


def construir() -> dict:
    duckdb = _duck()
    con = duckdb.connect(str(DB))
    feito = {"siconv": 0, "g2_parcerias": 0, "g2_especiais": 0, "externos": 0}

    # SICONV: CSV com ; e UTF-8-BOM. read_csv_auto acerta o resto; all_varchar
    # evita adivinhação de tipo errada em coluna que mistura vazio e número.
    if SICONV_CSV.exists():
        for csv in sorted(SICONV_CSV.glob("*.csv")):
            nome = _nome_tabela(csv)
            con.execute(
                f'CREATE OR REPLACE VIEW "{nome}" AS '
                f"SELECT * FROM read_csv_auto('{csv}', delim=';', header=true, "
                f"all_varchar=true, ignore_errors=true)")
            feito["siconv"] += 1

    # g2: o dump mais recente de cada módulo (subdir por data)
    for base, chave, prefixo in ((G2_PARCERIAS, "g2_parcerias", "g2_"),
                                 (G2_ESPECIAIS, "g2_especiais", "esp_")):
        if not base.exists():
            continue
        datas = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
        if not datas:
            continue
        for arq in sorted(datas[0].glob("*.jsonl.gz")):
            nome = _nome_tabela(arq, prefixo)
            con.execute(
                f'CREATE OR REPLACE VIEW "{nome}" AS '
                f"SELECT * FROM read_json_auto('{arq}', ignore_errors=true)")
            feito[chave] += 1

    # Externos (fundação de BI além do Transfergov). Cada fonte vira uma view.
    feito["externos"] = 0
    # Mapa das OSC: microdados de todas as OSCs do país (CSV ;-delimitado).
    for csv in (EXTERNOS / "mapaosc").glob("*MOSC*.csv") if (EXTERNOS / "mapaosc").exists() else []:
        con.execute(
            'CREATE OR REPLACE VIEW "mapa_osc" AS '
            f"SELECT * FROM read_csv_auto('{csv}', delim=';', header=true, "
            f"all_varchar=true, ignore_errors=true)")
        feito["externos"] += 1
    # Emendas parlamentares: um jsonl por ano → uma view unificada.
    emendas = sorted((EXTERNOS / "emendas").glob("emendas-*.jsonl.gz")) if (EXTERNOS / "emendas").exists() else []
    if emendas:
        glob = str(EXTERNOS / "emendas" / "emendas-*.jsonl.gz")
        con.execute(
            'CREATE OR REPLACE VIEW "emendas" AS '
            f"SELECT * FROM read_json_auto('{glob}', ignore_errors=true, union_by_name=true)")
        feito["externos"] += 1

    con.close()
    return feito


def catalogo() -> None:
    duckdb = _duck()
    con = duckdb.connect(str(DB), read_only=True)
    views = [r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall()]
    print(f"{len(views)} tabela(s) no lake ({DB}):\n")
    for v in views:
        try:
            n = con.execute(f'SELECT count(*) FROM "{v}"').fetchone()[0]
            print(f"  {v:<46} {n:>12,}")
        except Exception as e:  # noqa: BLE001 — arquivo malformado não derruba o catálogo
            print(f"  {v:<46} ERRO: {str(e)[:40]}")
    con.close()


def consultar(sql: str) -> None:
    duckdb = _duck()
    con = duckdb.connect(str(DB), read_only=True)
    try:
        con.execute(sql)
        cols = [d[0] for d in con.description]
        linhas = con.fetchall()
        print(" | ".join(cols))
        for r in linhas[:200]:
            print(" | ".join(str(x)[:60] for x in r))
        if len(linhas) > 200:
            print(f"... (+{len(linhas)-200} linhas)")
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--catalogo", action="store_true")
    ap.add_argument("--consulta", metavar="SQL")
    args = ap.parse_args()

    if args.consulta:
        consultar(args.consulta)
        return
    if args.catalogo:
        catalogo()
        return

    feito = construir()
    print(f"lake reconstruído em {DB}")
    print(f"  SICONV: {feito['siconv']} tabelas · g2 parcerias: {feito['g2_parcerias']}"
          f" · especiais: {feito['g2_especiais']}")
    print("consulte com: python ingest/lake/construir_lake.py --catalogo")


if __name__ == "__main__":
    main()
