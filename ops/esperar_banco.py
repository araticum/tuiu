"""Espera o Postgres de TUIU_DSN responder (até 60 s). Sai 0 quando conecta, 1 se não.

O compose já espera o healthcheck do `db`; isto cobre o reboot do host, em que os
dois containers sobem juntos pelo restart policy e o console pode chegar primeiro.
"""

from __future__ import annotations

import os
import sys
import time

import psycopg

dsn = os.environ.get("TUIU_DSN", "")
erro: Exception | None = None
for _ in range(30):
    try:
        psycopg.connect(dsn, connect_timeout=3).close()
        sys.exit(0)
    except Exception as e:  # noqa: BLE001 — qualquer falha é "ainda não"
        erro = e
        time.sleep(2)
print(f"banco não respondeu em 60 s: {erro}", file=sys.stderr)
sys.exit(1)
