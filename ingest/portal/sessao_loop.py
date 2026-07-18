"""Loop de monitoramento da sessão — estado do MESMO DIA, sem depender do D-1.

Objetivo (dono, 18/07): puxar no mesmo dia a mudança de estado dos representados.
Nenhuma ação é tomada — só leitura, diff e aviso.

## Cadência escalonada (sessão longa > re-login)

- **keepalive** (~15 min): toca uma página barata só para a sessão não cair.
- **leitura** (~45 min): lê as páginas de interesse, compara com a última e
  emite evento se mudou.
- **reautenticação**: SÓ quando a sessão cai de fato (detectado por redirect ao
  login). Não há re-login por relógio — é o que mais pesa em termos de uso e de
  anti-bot.

## Três estados, não dois

O erro clássico é confundir "li e não mudou" com "não consegui ler" — o segundo
vira falso conforto ("nenhuma novidade") enquanto o monitor está cego. Aqui:

    OK_SEM_MUDANCA · OK_MUDOU · CEGO (alarma)

`CEGO` alarma depois de `TUIU_SESSAO_MAX_CEGO` ciclos (default 3).

Uso:
    py -3 ingest/portal/sessao_loop.py --uma-vez     # um ciclo (teste)
    py -3 ingest/portal/sessao_loop.py               # loop contínuo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sessao_estado as ESTADO_SESSAO  # noqa: E402
from auth_certificado import dias_para_expirar  # noqa: E402
from sessao_operador import DOMINIOS_OK, LEITURAS, _parece_login, _pendencias  # noqa: E402

KEEPALIVE_S = int(os.environ.get("TUIU_SESSAO_KEEPALIVE_S", 15 * 60))
LEITURA_S = int(os.environ.get("TUIU_SESSAO_LEITURA_S", 45 * 60))
MAX_CEGO = int(os.environ.get("TUIU_SESSAO_MAX_CEGO", 3))
ESTADO = RAIZ / "data" / "sessao" / "estado_paginas.json"


def _auditar(evento: dict) -> None:
    pasta = RAIZ / "data" / "sessao" / date.today().isoformat()
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / "loop.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({**evento, "quando": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                            ensure_ascii=False) + "\n")


def _estado() -> dict:
    return json.loads(ESTADO.read_text(encoding="utf-8")) if ESTADO.exists() else {}


def _salvar_estado(e: dict) -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=2), encoding="utf-8")


def _digest(texto: str) -> str:
    # normaliza ruído volátil (horas, contadores de sessão) antes do hash
    import re
    limpo = re.sub(r"\d{2}:\d{2}(:\d{2})?", "", texto)
    limpo = re.sub(r"\s+", " ", limpo).strip()
    return hashlib.sha256(limpo.encode("utf-8")).hexdigest()


def _notificar(titulo: str, corpo: str) -> None:
    """Reusa o notificador do produto (outbox/webhook/whatsapp via Seriema)."""
    try:
        from app.db import conectar
        from app.notificador import despachar
        with conectar() as con:
            con.execute(
                "INSERT INTO eventos (cnpj, ente, dominio, chave, rotulo, tipo, de, para,"
                " snapshot, origem, detalhe)"
                " VALUES ('sessao','Sessão do operador','portal',%s,%s,'mudanca',NULL,%s,"
                " CURRENT_DATE,'portal',%s)",
                (f"portal:{titulo}:{date.today().isoformat()}", titulo, corpo[:400],
                 json.dumps({"fonte": "sessao_loop"}, ensure_ascii=False)))
            con.commit()
        despachar()
    except Exception as exc:  # noqa: BLE001 — nunca derruba o loop por falha de aviso
        _auditar({"acao": "notificar", "erro": str(exc)[:200]})


def _ler_pagina(pagina, leitura: dict) -> tuple[str, str | None]:
    """(texto, erro). Somente GET + extração — sem clique/preenchimento."""
    url = leitura["url"]
    if not any(d in url for d in DOMINIOS_OK):
        return "", f"fora da allowlist: {url}"
    try:
        pagina.goto(url, wait_until="domcontentloaded", timeout=45000)
        pagina.wait_for_timeout(2500)
        if _parece_login(pagina.url, pagina.title()):
            return "", "sessao_caiu"
        return pagina.inner_text("body")[:200000], None
    except Exception as exc:  # noqa: BLE001
        return "", f"{type(exc).__name__}: {exc}"[:200]


def ciclo(pagina, estado: dict) -> str:
    """Um ciclo de leitura. Devolve OK_SEM_MUDANCA | OK_MUDOU | CEGO | SESSAO_CAIU."""
    mudou, cego, caiu = [], [], False
    for leitura in LEITURAS:
        texto, erro = _ler_pagina(pagina, leitura)
        nome = leitura["nome"]
        if erro == "sessao_caiu":
            caiu = True
            break
        if erro:
            cego.append(f"{nome}: {erro}")
            _auditar({"acao": "ler", "pagina": nome, "erro": erro})
            continue
        d = _digest(texto)
        anterior = (estado.get(nome) or {}).get("digest")
        estado[nome] = {"digest": d, "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "chars": len(texto), "sinais": _pendencias(texto)}
        _auditar({"acao": "ler", "pagina": nome, "digest": d[:12], "mudou": bool(anterior and anterior != d)})
        if anterior and anterior != d:
            mudou.append(nome)

    if caiu:
        return "SESSAO_CAIU"
    if cego and not mudou:
        return "CEGO"
    if mudou:
        sinais = {n: estado[n]["sinais"] for n in mudou if estado[n]["sinais"]}
        _notificar("mudança na área logada",
                   f"Páginas alteradas: {', '.join(mudou)}"
                   + (f" · sinais: {json.dumps(sinais, ensure_ascii=False)}" if sinais else "")
                   + " — conferir no portal.")
        return "OK_MUDOU"
    return "OK_SEM_MUDANCA"


def rodar(uma_vez: bool = False, headless: bool = True) -> int:
    if os.environ.get("TUIU_SESSAO_ATIVA") != "1":
        print("desligado — defina TUIU_SESSAO_ATIVA=1")
        return 1

    dias = dias_para_expirar()
    if dias is not None and dias <= 30:
        _notificar("certificado A1 vencendo", f"O certificado usado para a leitura expira em {dias} dias.")

    from playwright.sync_api import sync_playwright

    estado = _estado()
    ciclos_cegos = 0
    with sync_playwright() as pw:
        # A sessão é do CONTAINER: restaurada do storage_state persistido, que
        # sobrevive ao restart. O login (com captcha) foi feito uma vez, no
        # bootstrap — daqui em diante a manutenção é automática.
        contexto, motivo = ESTADO_SESSAO.abrir_contexto(pw, headless=headless)
        if contexto is None:
            print("ERRO:", motivo)
            return 1
        print(f"sessão restaurada · idade {ESTADO_SESSAO.idade_horas()} h · "
              f"{ESTADO_SESSAO.ler_meta().get('cookies', '?')} cookie(s)")
        pagina = contexto.new_page()

        ultimo_leitura = 0.0
        while True:
            agora = time.time()
            if agora - ultimo_leitura >= LEITURA_S or uma_vez:
                r = ciclo(pagina, estado)
                _salvar_estado(estado)
                ultimo_leitura = agora
                print(f"[{datetime.now():%H:%M:%S}] {r}")

                if r == "CEGO":
                    ciclos_cegos += 1
                    if ciclos_cegos >= MAX_CEGO:
                        _notificar("monitor CEGO",
                                   f"{ciclos_cegos} ciclos sem conseguir ler a área logada — "
                                   "o silêncio NÃO significa 'sem novidade'.")
                        ciclos_cegos = 0
                else:
                    ciclos_cegos = 0

                if r == "SESSAO_CAIU":
                    # Fim da vida útil da sessão: é ISTO que a premissa mede.
                    horas = ESTADO_SESSAO.idade_horas()
                    _auditar({"acao": "sessao_expirou", "idade_horas": horas,
                              "salvamentos": ESTADO_SESSAO.ler_meta().get("salvamentos")})
                    _notificar("sessão expirou",
                               f"A sessão durou {horas} h sob keepalive automático. "
                               "Precisa de novo bootstrap (login humano — o gov.br "
                               "protege o login com captcha).")
                    print(f"SESSAO EXPIROU apos {horas} h — bootstrap necessario")
                    return 2
                # cookies são renovados pelo servidor: re-salvar mantém a sessão viva
                ESTADO_SESSAO.salvar(contexto)
            else:
                # keepalive: toque leve só para a sessão não expirar
                try:
                    pagina.goto(LEITURAS[0]["url"], wait_until="domcontentloaded", timeout=30000)
                    ESTADO_SESSAO.salvar(contexto)
                    _auditar({"acao": "keepalive", "ok": True,
                              "idade_horas": ESTADO_SESSAO.idade_horas()})
                except Exception as exc:  # noqa: BLE001
                    _auditar({"acao": "keepalive", "erro": str(exc)[:150]})

            if uma_vez:
                return 0
            time.sleep(KEEPALIVE_S)


def conectividade() -> int:
    """Diagnóstico do container SEM certificado: prova o que dá para provar hoje
    — chromium sobe, o Transferegov é alcançável, o Postgres responde e os
    guardas do A1 estão no estado esperado."""
    from playwright.sync_api import sync_playwright

    ok = True
    print(f"host: {os.uname().nodename if hasattr(os, 'uname') else 'windows'}")

    # 1) chromium dentro do container
    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            pag = nav.new_page()
            # 2) alcance ao Transferegov (página pública — sem login)
            pag.goto(LEITURAS[0]["url"], wait_until="domcontentloaded", timeout=60000)
            pag.wait_for_timeout(2000)
            titulo, chars = pag.title(), len(pag.inner_text("body"))
            print(f"[OK] chromium + Transferegov: '{titulo[:50]}' ({chars} chars)")
            # 3) o detector de login funciona a partir daqui
            pag.goto(LEITURAS[1]["url"], wait_until="domcontentloaded", timeout=60000)
            pag.wait_for_timeout(2000)
            caiu = _parece_login(pag.url, pag.title())
            print(f"[{'OK' if caiu else 'ATENCAO'}] deteccao de sessao nao autenticada: "
                  f"{'redirecionou p/ login (esperado sem A1)' if caiu else 'NAO detectou login'}")
            nav.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[FALHA] chromium/rede: {type(exc).__name__}: {exc}"[:300])
        ok = False

    # 4) banco (para gravar eventos)
    try:
        sys.path.insert(0, "/app/backend")
        from app.db import conectar
        with conectar() as con:
            n = con.execute("SELECT count(*) FROM eventos").fetchone()[0]
        print(f"[OK] postgres alcancavel — {n} evento(s) na base")
    except Exception as exc:  # noqa: BLE001
        print(f"[FALHA] postgres: {type(exc).__name__}: {str(exc)[:160]}")
        ok = False

    # 5) guardas do certificado
    from auth_certificado import caminho_certificado, dias_para_expirar
    pfx = caminho_certificado()
    dias = dias_para_expirar()
    print(f"[{'OK' if pfx else 'INFO'}] certificado: {pfx or 'nao configurado (esperado neste teste)'}"
          + (f" | expira em {dias} dias" if dias is not None else ""))
    print(f"[INFO] opt-in TUIU_SESSAO_ATIVA={os.environ.get('TUIU_SESSAO_ATIVA', '0')}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--conectividade", action="store_true",
                    help="diagnostico sem certificado (chromium, rede, banco, guardas)")
    ap.add_argument("--com-janela", action="store_true", help="não-headless (depuração)")
    args = ap.parse_args()
    if args.conectividade:
        sys.exit(conectividade())
    sys.exit(rodar(uma_vez=args.uma_vez, headless=not args.com_janela))


if __name__ == "__main__":
    main()
