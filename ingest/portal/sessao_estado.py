"""Persistência e manutenção AUTOMATIZADA da sessão.

A distinção que importa:

* **Login** (primeira autenticação) — o gov.br protege com hCaptcha, que é um
  gate humano deliberado. Acontece **uma vez**, no bootstrap.
* **Manutenção da sessão** — não tem captcha nenhum e é **inteiramente
  automatizada** aqui: o container guarda o `storage_state` (cookies +
  localStorage), sobe sozinho com a sessão restaurada, mantém viva com
  keepalive, **sobrevive ao próprio restart** e re-salva o estado a cada ciclo
  (os cookies são renovados pelo servidor e precisam ser reguardados).

Ninguém "segura uma janela aberta": o container é dono da sessão.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ARQ_ESTADO = Path(os.environ.get("TUIU_SESSAO_ESTADO",
                                 RAIZ / "data" / "sessao" / "storage_state.json"))
ARQ_META = ARQ_ESTADO.with_name("sessao_meta.json")


def existe() -> bool:
    return ARQ_ESTADO.exists() and ARQ_ESTADO.stat().st_size > 0


def salvar(contexto) -> dict:
    """Guarda cookies+localStorage. Chamar a cada ciclo: o servidor renova
    cookies e um estado velho envelhece a sessão sem necessidade."""
    ARQ_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    estado = contexto.storage_state()
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")

    meta = ler_meta()
    meta["salvo_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["cookies"] = len(estado.get("cookies", []))
    meta.setdefault("bootstrap_em", meta["salvo_em"])
    meta["salvamentos"] = int(meta.get("salvamentos", 0)) + 1
    ARQ_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def ler_meta() -> dict:
    if ARQ_META.exists():
        try:
            return json.loads(ARQ_META.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def idade_horas() -> float | None:
    """Há quantas horas a sessão foi autenticada (bootstrap). É a medida da
    premissa: por quanto tempo uma sessão se sustenta sob keepalive."""
    meta = ler_meta()
    quando = meta.get("bootstrap_em")
    if not quando:
        return None
    try:
        t0 = datetime.fromisoformat(quando)
    except ValueError:
        return None
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - t0).total_seconds() / 3600, 2)


def abrir_contexto(pw, headless: bool = True):
    """Sobe um browser DO CONTAINER já com a sessão restaurada.
    Devolve (contexto, motivo) — contexto None se ainda não há bootstrap."""
    if not existe():
        return None, ("sem sessão salva — rode o bootstrap uma vez "
                      "(ingest/portal/bootstrap_sessao.py)")
    navegador = pw.chromium.launch(headless=headless,
                                   args=["--no-sandbox", "--disable-dev-shm-usage"])
    contexto = navegador.new_context(storage_state=str(ARQ_ESTADO), locale="pt-BR")
    return contexto, None


def marcar_bootstrap() -> None:
    meta = ler_meta()
    meta["bootstrap_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["salvamentos"] = 0
    ARQ_META.parent.mkdir(parents=True, exist_ok=True)
    ARQ_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    m = ler_meta()
    print(f"estado: {'presente' if existe() else 'AUSENTE'} ({ARQ_ESTADO})")
    print(f"cookies: {m.get('cookies', '—')} · salvamentos: {m.get('salvamentos', 0)}")
    print(f"bootstrap: {m.get('bootstrap_em', '—')} · idade: {idade_horas()} h")
