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
import os
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
# o historico de situacao (102 MB) e o que diz HA QUANTO TEMPO a prestacao
# esta parada na analise do concedente — sem ele nao da para acusar o art. 97
ZIPS_DETRU = ["siconv_convenio.zip", "siconv_proposta.zip", "siconv_historico_situacao.zip"]
IDADE_MAX_H = 20


def _log(fh, msg: str):
    linha = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(linha, flush=True)
    fh.write(linha + "\n")
    fh.flush()


def _passo(fh, nome: str, cmd: list[str], essencial: bool = True) -> None:
    """`essencial=False` para elos INTERNOS (prospecção): eles não servem cliente,
    então não podem interromper a cadeia que vigia prazo nem disparar alarme."""
    _log(fh, f"-> {nome}: {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace")
    fh.write(proc.stdout or "")
    fh.write(proc.stderr or "")
    if proc.returncode != 0:
        if not essencial:
            _log(fh, f"~ {nome} falhou (rc={proc.returncode}) — elo interno, cadeia segue")
            return
        _log(fh, f"X {nome} FALHOU (rc={proc.returncode}) — cadeia interrompida")
        _avisar_falha(nome, proc.returncode)
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


def _avisar_falha(nome: str, rc: int) -> None:
    """Cadeia parada = prazo sem vigilância. Falha silenciosa é o pior defeito
    possível neste produto, então o vermelho sai do host.

    Vai por TODOS os canais ligados, não só pelo grupo interno. Com o alerta de
    andamento no WhatsApp de quem opera, "não chegou nada hoje" passa a ter dois
    sentidos — "nada mudou" e "a cadeia morreu" — e só este aviso desempata. Foi
    exatamente o que faltou em 22/07: o banco caiu, a cadeia parou no primeiro
    elo e ninguém soube, porque o único canal cadastrado não estava configurado.
    """
    sys.path.insert(0, str(RAIZ / "backend"))
    texto = (f"🔴 Tuiú — cadeia diária parou em *{nome}* (rc={rc}).\n"
             f"Os prazos NÃO foram recalculados hoje.\n"
             f"journalctl --user -u tuiu-diario -n 50")
    hoje = date.today().isoformat()
    avisou = False
    try:
        from app import seriema, wpp_cloud
        from app.config import envio_externo_liberado
        from app.db import conectar
        from app.notificador import CONSOLE_URL

        # respeita o interruptor: canal pausado não pode ser furado por aqui,
        # senão a pausa vale para o cliente e não para nós
        if envio_externo_liberado("seriema") and seriema.configurado():
            seriema.enviar_grupo(texto, chave_entrega=f"cadeia-falhou-{hoje}-{nome}")
            avisou = True

        if envio_externo_liberado("whatsapp") and wpp_cloud.configurado():
            with conectar() as con:
                numeros = [e for (e,) in con.execute(
                    "SELECT DISTINCT endereco FROM destinatarios WHERE ativo AND canal='whatsapp'")]
            for numero in numeros:
                # o template de andamento serve: {{1}} diz o que é, {{5}} o que fazer
                ok, det = wpp_cloud.enviar_template(numero, [
                    "FALHA NA CADEIA DIÁRIA", "Tuiú (aviso interno)", f"elo: {nome} (rc={rc})",
                    "Os prazos NÃO foram recalculados hoje",
                    "Ver: journalctl --user -u tuiu-diario -n 50", CONSOLE_URL, _br_hoje()])
                avisou = avisou or ok
                if not ok:
                    print(f"[aviso] whatsapp {numero}: {det}", file=sys.stderr)
    except Exception as e:  # avisar nunca pode mascarar a falha original
        print(f"[aviso] falha ao notificar: {e}", file=sys.stderr)
    if not avisou:
        print("[aviso] NENHUM canal de alerta ativo — a falha fica só no log e no "
              "`systemctl --user is-failed tuiu-diario`", file=sys.stderr)


def _br_hoje() -> str:
    return date.today().strftime("%d/%m/%Y")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--sem-radar", action="store_true")
    ap.add_argument("--sem-detru", action="store_true")
    args = ap.parse_args()

    LOGS.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    with open(LOGS / f"diario-{date.today().isoformat()}.log", "a", encoding="utf-8") as fh:
        _log(fh, "=== cadeia diária do Tuiú ===")
        # A carteira vem da tabela `clientes` (onboarding por comando, não por
        # commit) — os scripts abaixo resolvem a lista sozinhos.
        _passo(fh, "recorte g2 (clientes da carteira)", [py, "ingest/transferegov_g2/recorte_ente.py"])
        if not args.sem_detru:
            _refresh_detru(fh)
            _passo(fh, "recorte legado detru", [py, "ingest/transferegov_g2/detru_recorte.py"])
        _passo(fh, "regularidade do terceiro (CEPIM/CEIS/CNEP)",
               [py, "ingest/transparencia/coletar_regularidade.py"])
        _passo(fh, "conferencia de integridade (g2 ao vivo)", [py, "ingest/transferegov_g2/verificar.py"])
        _passo(fh, "motor de prazos (marcos + alertas)", [py, "backend/app/motor_prazos.py"])
        _passo(fh, "execucao financeira por convenio (mesa)", [py, "backend/app/execucao.py"])
        _passo(fh, "motor de eventos (diff de andamento)", [py, "backend/app/eventos.py"])
        if os.environ.get("TUIU_IMAP_HOST"):
            _passo(fh, "inbox (e-mail -> eventos)", [py, "ingest/inbox/coletar_inbox.py"])
        # Fonte de TERCEIRO e instavel (o INLABS cai). Nao-essencial: uma
        # queda deles nao pode derrubar a vigilancia de prazo dos clientes.
        # A falha aparece no log e a norma fica pendente no console.
        _passo(fh, "vigilia normativa (DOU)", [py, "ingest/normas/vigia_dou.py"],
               essencial=False)
        _passo(fh, "notificador (outbox/webhook/whatsapp)", [py, "backend/app/notificador.py"])
        # cadência mensal: o próprio script só age no dia 1º
        _passo(fh, "relatorios do mes (se for dia 1o)", [py, "ops/relatorio_mensal.py"])
        if not args.sem_radar:
            # Prospeccao NOSSA, nao servico de cliente -> nao-essencial.
            # `prospects.py` ranqueia ENTIDADES PRIVADAS, que e o publico do Tuiu
            # desde a correcao de escopo de 18/07. O `radar_comercial --so-municipios`
            # ranqueia PREFEITURAS: sobrou do escopo antigo e ficou rodando todo dia
            # produzindo lista de quem nao e nosso cliente.
            _passo(fh, "prospeccao interna (entidades privadas)", [py, "ferramentas/prospects.py"],
                   essencial=False)
        _log(fh, "=== cadeia concluída ===")


if __name__ == "__main__":
    main()
