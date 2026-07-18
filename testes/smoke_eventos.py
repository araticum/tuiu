"""Smoke do motor de eventos + notificação (F1.5), ponta a ponta.

1) baseline (detecta 1x — semeia estado, 0 eventos);
2) simula "ontem": altera algumas linhas de entidades_estado;
3) detecta de novo -> eventos reais de mudança;
4) sobe um sink de webhook local e despacha (webhook + whatsapp DRYRUN).
Não envia WhatsApp de verdade (dryrun) nem toca produção.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

RECEBIDOS = []


class Sink(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        RECEBIDOS.append(json.loads(self.rfile.read(n) or b"{}"))
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")

    def log_message(self, *a):  # silêncio
        pass


def main():
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


if __name__ == "__main__":
    main()
