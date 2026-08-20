"""Smoke do motor de eventos + notificação (F1.5), ponta a ponta.

1) baseline (detecta 1x — semeia estado, 0 eventos);
2) simula "ontem": altera algumas linhas de entidades_estado;
3) detecta de novo -> eventos reais de mudança;
4) sobe um sink de webhook local e despacha (webhook + whatsapp DRYRUN).

⚠️ DESTRUTIVO: apaga `entidades_estado`, `eventos` e `entregas` INTEIRAS, sem
WHERE, e planta um destinatário curinga `'*'` no canal do cliente. Correto para
banco descartável, catastrófico para o de trabalho.

"não toca produção" era afirmação do docstring, não do código: este arquivo
viaja no tar do deploy (`ops/deploy_araticum.sh:36`) e no host `TUIU_DSN` aponta
para o banco real, onde `entidades_estado` tem 6.012 linhas. Agora a garantia é
de código — `_guarda_smoke.exigir_banco_de_teste()` recusa rodar sem um DSN
descartável dito na mão. Uso:

    TUIU_SMOKE_DSN=postgresql://postgres@localhost:5432/tuiu_smoke         py -3 testes/smoke_eventos.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))     # para `_guarda_smoke`

RECEBIDOS = []
# só vira True depois que a trava aceitou o banco descartável. Sem isto, a
# limpeza do `finally` rodaria mesmo numa execução RECUSADA — conectando no
# banco de trabalho logo depois de nos recusarmos a tocá-lo.
ARMADO = False


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        RECEBIDOS.append(json.loads(self.rfile.read(n) or b"{}"))
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def log_message(self, *a):  # silêncio
        pass


def main():
    # ANTES de qualquer import de app.db: ele resolve o DSN no import, e depois
    # disso já é tarde para escolher outro banco
    global ARMADO
    from _guarda_smoke import exigir_banco_de_teste
    exigir_banco_de_teste()
    ARMADO = True

    srv = HTTPServer(("127.0.0.1", 8790), Sink)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["TUIU_WEBHOOK_URL"] = "http://127.0.0.1:8790/hook"
    os.environ["TUIU_WPP_TOKEN"] = "TESTE"
    os.environ["TUIU_WPP_PHONE_ID"] = "000000"
    os.environ["TUIU_WPP_DRYRUN"] = "1"

    from app.db import conectar, migrar
    from app import eventos, notificador

    migrar()
    with conectar() as con:
        con.execute("DELETE FROM entregas"); con.execute("DELETE FROM eventos")
        con.execute("DELETE FROM entidades_estado")
        # '*' casa TODO CNPJ no canal do CLIENTE: num banco descartável é o
        # jeito de capturar o despacho; deixado para trás vira destino curinga
        # válido em produção. Sai no `finally` do main.
        con.execute("INSERT INTO destinatarios (cnpj, canal, endereco) VALUES "
                    "('*','whatsapp','5561999990000') ON CONFLICT DO NOTHING")
        con.commit()

    print("1) baseline:", eventos.detectar())

    with conectar() as con:
        # simula ontem: 2 mudanças de situação + 1 contador menor (=> incremento)
        con.execute("UPDATE entidades_estado SET valor='Em Complementação'"
                    " WHERE dominio='proposta_g2' AND ctid IN"
                    " (SELECT ctid FROM entidades_estado WHERE dominio='proposta_g2' LIMIT 2)")
        con.execute("UPDATE entidades_estado SET valor=(valor::int - 3)::text"
                    " WHERE dominio='empenho_g2' AND chave='#count'"
                    " AND valor::int >= 3")
        con.commit()

    print("2) apos simular:", eventos.detectar())
    print("3) despacho:", notificador.despachar())

    with conectar() as con:
        print("\n--- amostra de entregas ---")
        for canal, msg, status, det in con.execute(
                "SELECT canal, mensagem, status, detalhe FROM entregas ORDER BY id LIMIT 6"):
            print(f"[{canal}/{status}]", (msg.replace(chr(10), ' | '))[:110])
            if canal == "whatsapp" and det:
                print("   payload:", det[:150])
    print(f"\nwebhook recebeu {len(RECEBIDOS)} POST(s); 1o:",
          json.dumps(RECEBIDOS[0]["evento"], ensure_ascii=False)[:140] if RECEBIDOS else "—")
    srv.shutdown()


def _limpar_curinga():
    """Tira o destino `'*'` mesmo se o smoke quebrar no meio.

    Ele casa TODO CNPJ no canal do CLIENTE. Num banco descartável é o que faz o
    teste funcionar; esquecido numa base que depois vira outra coisa, é mensagem
    para quem nunca pediu.

    Não roda em execução RECUSADA: conectar no banco de trabalho logo depois de
    nos recusarmos a tocá-lo seria contradizer a própria trava.
    """
    if not ARMADO:
        return
    try:
        from app.db import conectar
        with conectar() as con:
            con.execute("DELETE FROM destinatarios WHERE cnpj='*'"
                        " AND endereco='5561999990000'")
            con.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] AVISO: não consegui limpar o destino curinga: {exc}")



if __name__ == "__main__":
    try:
        main()
    finally:
        _limpar_curinga()
