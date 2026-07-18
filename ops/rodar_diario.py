"""Cadeia diária do Tuiú — serial, no espírito xyops (um elo por vez, para no vermelho).

Elos: [1] recorte g2 dos entes monitorados -> [2] refresh do cache detru (se >20h)
+ recorte do legado -> [3] motor de prazos (migra, marcos, alertas outbox) ->
[4] radar comercial interno. Log em ops/logs/diario-<data>.log.

Uso:
    py -3 ops/rodar_diario.py            # cadeia completa
    py -3 ops/rodar_diario.py --sem-radar
Agendamento (Task Scheduler, diário ~09h30 — após a carga da API):
    schtasks /Create /SC DAILY /ST 09:30 /TN "tuiu-diario" /TR "py -3 D:\\tuiu\\ops\\rodar_diario.py"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
LOGS = RAIZ / "ops" / "logs"
CACHE_DETRU = RAIZ / "data" / "detru" / "cache"
DOWNLOADS = "https://api-publica.transferegov.gestao.gov.br/downloads/dadosgov"
ZIPS_DETRU = ["siconv_convenio.zip", "siconv_proposta.zip"]
IDADE_MAX_H = 20


def _log(fh, msg: str):
    linha = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(linha, flush=True)
    fh.write(linha + "\n")
    fh.flush()


def _passo(fh, nome: str, cmd: list[str]) -> None:
    _log(fh, f"-> {nome}: {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace")
    fh.write(proc.stdout or "")
    fh.write(proc.stderr or "")
    if proc.returncode != 0:
        _log(fh, f"X {nome} FALHOU (rc={proc.returncode}) — cadeia interrompida")
        raise SystemExit(proc.returncode)
    _log(fh, f"OK {nome} ok ({round(time.time() - t0, 1)}s)")


def _refresh_detru(fh):
    CACHE_DETRU.mkdir(parents=True, exist_ok=True)
    for nome in ZIPS_DETRU:
        alvo = CACHE_DETRU / nome
        idade_h = (time.time() - alvo.stat().st_mtime) / 3600 if alvo.exists() else 1e9
        if idade_h <= IDADE_MAX_H:
            _log(fh, f"detru {nome}: cache fresco ({idade_h:.1f}h) — mantido")
            continue
        _log(fh, f"detru {nome}: baixando (cache com {idade_h:.1f}h)")
        with urllib.request.urlopen(f"{DOWNLOADS}/{nome}", timeout=300) as r, open(alvo, "wb") as out:
            while bloco := r.read(1 << 20):
                out.write(bloco)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--sem-radar", action="store_true")
    ap.add_argument("--sem-detru", action="store_true")
    args = ap.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    with open(LOGS / f"diario-{date.today().isoformat()}.log", "a", encoding="utf-8") as fh:
        _log(fh, "=== cadeia diária do Tuiú ===")
        _passo(fh, "recorte g2 (entes monitorados)", [py, "ingest/transferegov_g2/recorte_ente.py"])
        if not args.sem_detru:
            _refresh_detru(fh)
            _passo(fh, "recorte legado detru", [py, "ingest/transferegov_g2/detru_recorte.py"])
        _passo(fh, "regularidade CAUC", [py, "ingest/cauc/coletar_cauc.py"])
        _passo(fh, "motor de prazos (marcos + alertas)", [py, "backend/app/motor_prazos.py"])
        _passo(fh, "motor de eventos (diff de andamento)", [py, "backend/app/eventos.py"])
        _passo(fh, "notificador (outbox/webhook/whatsapp)", [py, "backend/app/notificador.py"])
        if not args.sem_radar:
            _passo(fh, "radar comercial interno", [py, "ferramentas/radar_comercial.py", "--so-municipios"])
        _log(fh, "=== cadeia concluída ===")


if __name__ == "__main__":
    main()
