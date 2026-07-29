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

# Arquivos que EVIDENCIAM o dossiê (db/0024). O checklist estava 100% em branco
# — servia para saber o que reunir, não para mostrar o que já existe. Estes 7
# provam 5 dos 8 itens a partir de dado aberto. São 6 (177 MB): o
# `siconv_obtv_convenente` saiu depois de baixado — é chaveado por NR_MOV_FIN
# e não liga ao convênio sem outro arquivo; `desembolso` já cobre o item.
#
# Semanal, não diário: contrato, aditivo e OBTV mudam devagar, e 235 MB por dia
# seria pagar caro por frescor que ninguém usa. Fora da lista de propósito:
# `siconv_pagamento.zip` (364 MB, o maior de todos, evidenciaria nota fiscal) —
# entra se o item virar prioridade.
ZIPS_DOCUMENTAIS = ["siconv_solicitacao_rendimento_aplicacao.zip", "siconv_prorroga_oficio.zip",
                    "siconv_desembolso.zip", "siconv_licitacao.zip",
                    "siconv_termo_aditivo.zip", "siconv_contrato.zip"]
IDADE_MAX_DOCUMENTAL_H = 24 * 7
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


def _refresh_detru(fh, zips=None, idade_max=None):
    CACHE_DETRU.mkdir(parents=True, exist_ok=True)
    idade_max = IDADE_MAX_H if idade_max is None else idade_max
    for nome in (zips or ZIPS_DETRU):
        alvo = CACHE_DETRU / nome
        idade_h = (time.time() - alvo.stat().st_mtime) / 3600 if alvo.exists() else 1e9
        if idade_h <= idade_max:
            _log(fh, f"detru {nome}: cache fresco ({idade_h:.1f}h) — mantido")
            continue
        _log(fh, f"detru {nome}: baixando (cache com {idade_h:.1f}h)")
        with urllib.request.urlopen(f"{DOWNLOADS}/{nome}", timeout=300) as r, open(alvo, "wb") as out:
            while bloco := r.read(1 << 20):
                out.write(bloco)


def _avisar_falha(nome: str, rc: int) -> None:
    """Cadeia parada = prazo sem vigilância. Falha silenciosa é o pior defeito
    possível neste produto, então o vermelho sai do host.

    Vai pelo canal da EQUIPE (`seriema`), nunca pelo canal do CLIENTE. Isto aqui
    é recado interno — cita elo que quebrou e comando de journalctl —, e cliente
    não tem o que fazer com ele nem por que saber. O canal `seriema` ganhou
    transporte de nuvem justamente para este aviso ter por onde sair.

    Importa porque, com o alerta de andamento no WhatsApp de quem opera, "não
    chegou nada hoje" passa a ter dois sentidos — "nada mudou" e "a cadeia
    morreu" — e só este aviso desempata. Foi o que faltou em 22/07: o banco
    caiu, a cadeia parou no primeiro elo e ninguém soube.
    """
    sys.path.insert(0, str(RAIZ / "backend"))
    texto = (f"🔴 Tuiú — cadeia diária parou em *{nome}* (rc={rc}).\n"
             f"Os prazos NÃO foram recalculados hoje.\n"
             f"journalctl --user -u tuiu-diario -n 50")
    hoje = date.today().isoformat()
    # o template de andamento serve: {{3}} diz o que houve, {{4}} o que fazer
    avisou, detalhe = _avisar(
        texto,
        ["Tuiú (aviso interno, não é de cliente)",
         f"cadeia diária — elo {nome} (rc={rc})",
         "FALHA: os prazos NÃO foram recalculados hoje",
         f"Ver o log: journalctl --user -u tuiu-diario -n 50 · {_br_hoje()}",
         "https://tuiu.araticum.net"],
        chave=f"cadeia-falhou-{hoje}-{nome}")
    if not avisou:
        print(f"[aviso] a equipe NÃO foi avisada ({detalhe}) — a falha fica só no log "
              f"e no `systemctl --user is-failed tuiu-diario`", file=sys.stderr)


def _br_hoje() -> str:
    return date.today().strftime("%d/%m/%Y")


def _conferir_entregas(fh) -> None:
    """A Meta ACEITAR não é a mensagem CHEGAR.

    `enviar` devolve um wamid assim que a API aceita, e é isso que a cadeia
    registrava como "enviado". A recusa vem depois, pelo webhook — e foi assim
    que três dias de produção passaram com log verde e ninguém recebendo nada
    (a conta estava com "Business eligibility payment issue").

    Aqui a falha aparece no LOG, não só no canal: o canal é justamente o que
    está quebrado quando isto acontece.
    """
    sys.path.insert(0, str(RAIZ / "backend"))
    try:
        from app.wpp_webhook import falhas_recentes
        falhas = falhas_recentes(26)
    except Exception as e:  # noqa: BLE001
        _log(fh, f"! nao consegui conferir os recibos de entrega: {type(e).__name__}")
        return
    if not falhas:
        return
    for f in falhas:
        _log(fh, f"!! ENTREGA RECUSADA para {f['numero']}: {f['erro']} "
                 f"(a API aceitou, a Meta recusou depois)")
    _log(fh, f"!! {len(falhas)} entrega(s) NAO chegaram — 'enviado' no log acima "
             f"significa apenas que a API aceitou")


def _conferir_frescor(fh) -> None:
    """Dado velho passando por D-1 é a falha que mais custa neste produto.

    `verificar.py` já mede o frescor e escreve em `_verificacao.json`, mas o
    resultado só ia para o log: o exit code dele olha divergência, nunca
    frescor. Ou seja, se a carga do Transferegov atrasar, a cadeia recalcula
    prazo em cima de ontem-retrasado, emite evento e fecha "cadeia concluída"
    — verde, e mentindo sobre a idade do dado.

    Não interrompe: prazo é data, então um snapshot atrasado ainda produz marco
    quase certo, e parar a cadeia tiraria a vigilância do dia inteiro. O que
    faltava era a equipe SABER. Aqui ela sabe.
    """
    import json

    arq = RAIZ / "data" / "recortes" / date.today().isoformat() / "_verificacao.json"
    if not arq.exists():
        _log(fh, "! conferencia sem _verificacao.json — frescor NAO conferido hoje")
        return
    d = json.loads(arq.read_text(encoding="utf-8"))
    fresco, resumo = d.get("snapshot_fresco"), d.get("resumo") or {}
    divergem = int(resumo.get("divergem") or 0)
    if fresco and not divergem:
        _log(fh, f"OK dado fresco ({d.get('data_atualizacao_api', '')[:10]}), "
                 f"{resumo.get('conferem')} conferencias batem")
        return

    motivo = []
    if not fresco:
        motivo.append(f"snapshot NAO fresco (API={str(d.get('data_atualizacao_api'))[:10]}, "
                      f"recorte={d.get('snapshot')})")
    if divergem:
        motivo.append(f"{divergem} conferencia(s) DIVERGEM da g2 ao vivo")
    _log(fh, "! " + " · ".join(motivo))
    _avisar(f"⚠️ Tuiú — {' · '.join(motivo)}.\n"
            f"A cadeia seguiu, mas o dado de hoje NÃO é D-1 confiável.",
            ["Tuiú (aviso interno, não é de cliente)", "conferência de integridade",
             " · ".join(motivo), "A cadeia seguiu — confira antes de agir no que saiu hoje",
             _br_hoje()],
            chave=f"frescor-{date.today().isoformat()}")


def _avisar(texto: str, campos: list[str], chave: str) -> tuple[bool, str]:
    """Manda para a EQUIPE pelo canal interno, respeitando os interruptores."""
    sys.path.insert(0, str(RAIZ / "backend"))
    try:
        from app import seriema
        from app.config import envio_externo_liberado
        if not (envio_externo_liberado("seriema") and seriema.configurado()):
            return False, "canal desligado ou não configurado"
        return seriema.enviar_grupo(texto, chave_entrega=chave, parametros=campos)
    except Exception as e:  # avisar nunca pode mascarar o que estava sendo avisado
        return False, f"{type(e).__name__}: {e}"


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
            # semanal: contrato, aditivo e OBTV mudam devagar, e sao 235 MB. Sem
        # eles o checklist do dossie fica 100% em branco (era assim ate 28/07).
        _refresh_detru(fh, ZIPS_DOCUMENTAIS, IDADE_MAX_DOCUMENTAL_H)
        _passo(fh, "recorte legado detru", [py, "ingest/transferegov_g2/detru_recorte.py"])
        _passo(fh, "regularidade do terceiro (CEPIM/CEIS/CNEP)",
               [py, "ingest/transparencia/coletar_regularidade.py"])
        _passo(fh, "conferencia de integridade (g2 ao vivo)", [py, "ingest/transferegov_g2/verificar.py"])
        # o passo acima MEDE o frescor; este age sobre ele. Sem isto, dado velho
        # atravessava a cadeia inteira e saía como D-1.
        _conferir_frescor(fh)
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
        _passo(fh, "notificador (outbox; canais só se alerta_por_evento)",
               [py, "backend/app/notificador.py"])
        # a TRIAGEM — uma mensagem por dia com o que exige ação, em vez de uma
        # por evento (correção do Danilo, 27/07: o Transferegov já manda e-mail
        # de cada mudança). Dia sem ação não envia nada.
        _passo(fh, "resumo do dia (triagem para a equipe)", [py, "backend/app/resumo_diario.py"])
        _conferir_entregas(fh)
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
