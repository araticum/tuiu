"""Coleta o inbox e vira eventos (F1.6) — IMAP ou pasta de .eml.

Cada e-mail confiável e atribuível a um ente monitorado vira um evento
origem='inbox' na MESMA tabela eventos → o notificador o entrega (outbox/
webhook/whatsapp) como qualquer mudança. E-mail de remetente fora da allowlist
= registrado como suspeito, NUNCA notifica.

Atribuição ao ente: (1) CNPJ no corpo casando com ente monitorado; senão
(2) mapa inbox_origem pelo endereço reencaminhador; senão 'nao_atribuido'.

Fontes:
  --eml <dir>   parseia todos os .eml de uma pasta (teste / reencaminho manual)
  IMAP          env TUIU_IMAP_HOST/USER/PASS[/FOLDER]; lê não-lidos e marca lido

Uso:
    py -3 ingest/inbox/coletar_inbox.py --eml testes/fixtures/inbox
    py -3 ingest/inbox/coletar_inbox.py            # IMAP (se env setado)
"""

from __future__ import annotations

import argparse
import imaplib
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.carteira import ROTULOS  # noqa: E402
from app.db import conectar, migrar  # noqa: E402
from parser_email import parse_email  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]


def _entes_monitorados(con) -> dict[str, str]:
    """cnpj -> rótulo, a partir do inbox_origem, do ROTULOS e do último recorte."""
    entes = dict(ROTULOS)
    rec = RAIZ / "data" / "recortes"
    if rec.exists():
        for snap in sorted(rec.iterdir(), reverse=True)[:1]:
            for sub in snap.iterdir():
                if sub.is_dir() and (sub / "carteira.json").exists():
                    entes.setdefault(sub.name, sub.name)
    return entes


def _atribuir(con, p: dict, entes: dict[str, str]) -> tuple[str, str]:
    for c in p["cnpjs"]:
        if c in entes:
            return c, entes[c]
    if p["para"]:
        row = con.execute(
            "SELECT cnpj FROM inbox_origem WHERE ativo AND lower(reencaminhador)=%s LIMIT 1",
            (p["para"],)).fetchone()
        if row and row[0] in entes:
            return row[0], entes[row[0]]
    return "nao_atribuido", "(ente não identificado)"


def _rotulo(p: dict) -> str:
    ins = p["instrumentos"]
    ref = (ins["planos_pix"] or ins["convenios"] or ins["propostas"] or [""])[0]
    nome = {"diligencia": "Diligência", "complementacao": "Complementação solicitada",
            "prestacao_contas": "Prestação de contas", "impedimento": "Impedimento",
            "rejeicao": "Rejeição", "aprovacao": "Aprovação", "assinatura": "Pendente de assinatura",
            "prazo": "Prazo", "liberacao": "Liberação de recurso"}.get(p["tipo"], "Notificação")
    return f"{nome}{f' — {ref}' if ref else ''}"


def registrar(con, p: dict, entes: dict[str, str]) -> str:
    if not p["confiavel"]:
        return "suspeito"
    ja = con.execute("SELECT 1 FROM eventos WHERE origem='inbox' AND chave=%s", (p["message_id"],)).fetchone()
    if ja:
        return "duplicado"
    cnpj, ente = _atribuir(con, p, entes)
    detalhe = {"remetente": p["remetente"], "assunto": p["assunto"], "prazos": p["prazos"],
               "instrumentos": p["instrumentos"], "links_removidos": p["links_removidos"]}
    con.execute(
        "INSERT INTO eventos (cnpj, ente, dominio, chave, rotulo, tipo, de, para, snapshot, origem, detalhe)"
        " VALUES (%s,%s,'inbox',%s,%s,%s,NULL,%s,%s,'inbox',%s)",
        (cnpj, ente, p["message_id"], _rotulo(p), p["tipo"], p["resumo"],
         p["data"] or date.today().isoformat(), json.dumps(detalhe, ensure_ascii=False)))
    return "atribuido" if cnpj != "nao_atribuido" else "nao_atribuido"


def _do_eml(dir_: Path) -> list[bytes]:
    return [f.read_bytes() for f in sorted(dir_.glob("*.eml"))]


def _do_imap() -> list[bytes]:
    host, user, senha = (os.environ.get(k, "") for k in ("TUIU_IMAP_HOST", "TUIU_IMAP_USER", "TUIU_IMAP_PASS"))
    if not (host and user and senha):
        return []
    pasta = os.environ.get("TUIU_IMAP_FOLDER", "INBOX")
    brutos: list[bytes] = []
    with imaplib.IMAP4_SSL(host) as m:
        m.login(user, senha)
        m.select(pasta)
        _, dados = m.search(None, "UNSEEN")
        for num in (dados[0].split() if dados and dados[0] else []):
            _, msg = m.fetch(num, "(RFC822)")
            if msg and msg[0]:
                brutos.append(msg[0][1])
                m.store(num, "+FLAGS", "\\Seen")
    return brutos


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--eml", type=Path, help="pasta com .eml (em vez de IMAP)")
    args = ap.parse_args()

    migrar()
    brutos = _do_eml(args.eml) if args.eml else _do_imap()
    if not brutos:
        print("nenhum e-mail (pasta vazia ou IMAP não configurado — TUIU_IMAP_HOST/USER/PASS)")
        return

    tally: dict[str, int] = {}
    with conectar() as con:
        entes = _entes_monitorados(con)
        for raw in brutos:
            p = parse_email(raw)
            r = registrar(con, p, entes)
            tally[r] = tally.get(r, 0) + 1
            print(f"  [{r}] {p['remetente']} | {p['tipo']} | {p['assunto'][:56]}")
        con.commit()
    print("resumo:", ", ".join(f"{k}={v}" for k, v in tally.items()))


if __name__ == "__main__":
    main()
