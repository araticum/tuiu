#!/usr/bin/env python3
"""Evento do xyOps que dispara a cadeia diária do Tuiú às 09h30 (após a carga da API).

Roda NO HOST (araticum), chamado pelo ops/deploy_remoto.sh:

    python3 ops/xyops_eventos.py            # cria ou atualiza o evento `tuiu_diario`
    python3 ops/xyops_eventos.py --listar   # só mostra o que existe no xyOps

Idempotente de verdade: `get_events/v1` devolve `rows: []` (bug conhecido do xyOps), e
`create_event/v1` NÃO é idempotente — chamar duas vezes cria dois eventos. Por isso a
existência é conferida no banco do próprio xyOps (sqlite, só leitura) antes de decidir
entre `update_event` e `create_event`. Modelo: veredas `ops/observability/xyops_pipes.py`.

O script do evento segue o padrão dos outros 13 pipes do host: `pipe_metric.sh` no fim,
que emite a métrica do node-exporter (o watchdog das 08:00 lê a idade dela) e avisa a
equipe por WhatsApp na TRANSIÇÃO de estado (ok→falha e falha→ok, cooldown de 24 h).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import urllib.error
import urllib.request

APIKEY = "/home/pedro/xyops/.apikey"
BANCO = "/home/pedro/xyops/data/sqlite.db"
BASE = "http://localhost:5522/api/app"
METRICA = "bash /home/pedro/oasis-v2-test/observability/pipe_metric.sh"

SCRIPT = f"""#!/bin/bash
PIPE=tuiu-diario
START=$(date +%s)
echo "===== [$PIPE] $(date -Is) ====="
cd /home/pedro/tuiu && docker compose -f ops/compose.yaml run --rm -T cadeia
rc=$?
{METRICA} "$PIPE" "$rc" "$START"
echo "[$PIPE] fim rc=$rc"
exit $rc
"""

EVENTO = {
    "id": "tuiu_diario",
    "title": "Tuiú: cadeia diária em container (09:30, após a carga da API)",
    "enabled": True,
    "category": "general",
    "algo": "random",
    "plugin": "shellplug",
    "timezone": "America/Sao_Paulo",
    "targets": ["main"],
    "limits": [{"type": "job", "enabled": True, "amount": 1}],
    "triggers": [
        {"type": "manual", "enabled": True},
        {"type": "schedule", "enabled": True, "hours": [9], "minutes": [30],
         "timezone": "America/Sao_Paulo"},
    ],
    "params": {"script": SCRIPT},
}


def _chave() -> str:
    return open(APIKEY, encoding="utf-8").read().strip()


def post(endpoint: str, corpo: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{BASE}/{endpoint}/v1", data=json.dumps(corpo).encode(),
        headers={"X-API-Key": _chave(), "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def eventos_existentes() -> dict[str, dict]:
    """Lê o banco do xyOps (só leitura): {id: evento}."""
    con = sqlite3.connect(f"file:{BANCO}?mode=ro", uri=True)
    saida: dict[str, dict] = {}
    for (valor,) in con.execute("select value from items where key like 'global/events/%'"):
        texto = valor.decode() if isinstance(valor, bytes) else str(valor)
        try:
            pagina = json.loads(texto)
        except json.JSONDecodeError:
            continue
        for e in pagina.get("items", []) if isinstance(pagina, dict) else []:
            if isinstance(e, dict) and e.get("id"):
                saida[e["id"]] = e
    return saida


def main() -> int:
    existentes = eventos_existentes()
    if "--listar" in sys.argv:
        for id_, e in sorted(existentes.items()):
            print(f"{id_:28} enabled={e.get('enabled')!s:5} {e.get('title')}")
        return 0
    if EVENTO["id"] in existentes:
        status, corpo = post("update_event", EVENTO)
        print(f"{EVENTO['id']}: existe -> update_event: {status} {corpo[:200]}")
    else:
        status, corpo = post("create_event", EVENTO)
        print(f"{EVENTO['id']}: novo -> create_event: {status} {corpo[:200]}")
    return 0 if status == 200 and '"code":0' in corpo.replace(" ", "") else 1


if __name__ == "__main__":
    sys.exit(main())
