"""Conexão e migrações do Tuiú (F1+).

DSN via env TUIU_DSN; default = Postgres nativo local (trust), banco `tuiu`.
Migrações = arquivos db/NNNN_*.sql aplicados em ordem, uma vez (tabela
`migracoes` guarda o nome). Sem Alembic nesta fase — SQL puro numerado, no
espírito runtime-DDL da Habilitação; Alembic entra se/quando o schema crescer.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

RAIZ = Path(__file__).resolve().parents[2]
DSN = os.environ.get("TUIU_DSN", "postgresql://postgres@localhost:5432/tuiu")


def conectar() -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=False)


def migrar() -> list[str]:
    aplicadas: list[str] = []
    with conectar() as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS migracoes ("
            " nome text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now())"
        )
        feitas = {r[0] for r in con.execute("SELECT nome FROM migracoes")}
        for sql in sorted((RAIZ / "db").glob("[0-9][0-9][0-9][0-9]_*.sql")):
            if sql.name in feitas:
                continue
            con.execute(sql.read_text(encoding="utf-8"))
            con.execute("INSERT INTO migracoes (nome) VALUES (%s)", (sql.name,))
            aplicadas.append(sql.name)
        con.commit()
    return aplicadas


def regra_vigente(con: psycopg.Connection, parametro: str, regime: str, em) -> dict | None:
    """Regra vigente NA DATA `em` — o coração do versionamento (nunca a 'mais nova')."""
    row = con.execute(
        "SELECT valor, base_legal FROM regras_normativas"
        " WHERE parametro=%s AND regime IN (%s,'geral')"
        "   AND vigencia_inicio<=%s AND (vigencia_fim IS NULL OR vigencia_fim>=%s)"
        " ORDER BY CASE WHEN regime=%s THEN 0 ELSE 1 END, vigencia_inicio DESC LIMIT 1",
        (parametro, regime, em, em, regime),
    ).fetchone()
    return {"valor": row[0], "base_legal": row[1]} if row else None
