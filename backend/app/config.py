"""Configuração operacional em banco — hoje, o interruptor de notificações.

A trava mora no BANCO, não em variável de ambiente, por dois motivos: quem opera
precisa desligar sem deploy, e ligar/desligar envio externo tem que deixar
rastro (quem, quando, de qual valor para qual).

Regra de ouro deste módulo: **na dúvida, desligado**. Se a leitura falhar, se a
chave não existir, se o valor vier estranho — a resposta é `False`. A carteira
tem organizações reais que nunca pediram para receber nada nossa; o custo de um
falso "ligado" é mandar mensagem para quem não pediu, e o de um falso
"desligado" é só um aviso que não sai.
"""

from __future__ import annotations

from app.db import conectar

CHAVES_NOTIFICACAO = ("notificacoes_ativas", "canal_seriema", "canal_whatsapp", "canal_webhook",
                      # modo: false (padrão) = um resumo por dia; true = uma
                      # mensagem por evento. Os dois juntos são a enxurrada que
                      # o resumo veio evitar — ver db/0028.
                      "alerta_por_evento")
_VERDADEIROS = ("true", "1", "sim", "on", "yes")


def _bool(valor: str | None) -> bool:
    return (valor or "").strip().lower() in _VERDADEIROS


def ler(chave: str, padrao: str = "false") -> str:
    try:
        with conectar() as con:
            r = con.execute("SELECT valor FROM configuracoes WHERE chave=%s", (chave,)).fetchone()
        return r[0] if r else padrao
    except Exception:  # noqa: BLE001 — sem banco, o seguro é o padrão
        return padrao


def ligado(chave: str) -> bool:
    return _bool(ler(chave))


def envio_externo_liberado(canal: str) -> bool:
    """Duas travas em série: a geral e a do canal. Basta uma desligada."""
    return ligado("notificacoes_ativas") and ligado(f"canal_{canal}")


def gravar(chave: str, valor: str, quem: str | None = None) -> dict:
    if chave not in CHAVES_NOTIFICACAO:
        raise ValueError(f"chave não permitida: {chave}")
    valor = "true" if _bool(valor) else "false"
    with conectar() as con:
        atual = con.execute("SELECT valor FROM configuracoes WHERE chave=%s", (chave,)).fetchone()
        de = atual[0] if atual else None
        con.execute(
            "INSERT INTO configuracoes (chave, valor, atualizado_por) VALUES (%s,%s,%s)"
            " ON CONFLICT (chave) DO UPDATE SET valor=EXCLUDED.valor,"
            " atualizado_em=now(), atualizado_por=EXCLUDED.atualizado_por",
            (chave, valor, quem))
        if de != valor:
            con.execute(
                "INSERT INTO configuracoes_log (chave, de, para, quem) VALUES (%s,%s,%s,%s)",
                (chave, de, valor, quem))
        con.commit()
    return {"chave": chave, "de": de, "para": valor}


def estado() -> dict:
    """Estado + diagnóstico: o que está ligado E o que de fato conseguiria sair."""
    from app import seriema, wpp_cloud

    with conectar() as con:
        linhas = con.execute(
            "SELECT chave, valor, atualizado_em, atualizado_por FROM configuracoes"
            " WHERE chave = ANY(%s)", (list(CHAVES_NOTIFICACAO),)).fetchall()
        dest = con.execute(
            "SELECT canal, count(*) FROM destinatarios WHERE ativo GROUP BY canal").fetchall()
        historico = con.execute(
            "SELECT chave, de, para, quem, quando FROM configuracoes_log"
            " ORDER BY id DESC LIMIT 10").fetchall()
        pendentes = con.execute(
            "SELECT count(*) FROM eventos e WHERE NOT EXISTS"
            " (SELECT 1 FROM entregas x WHERE x.evento_id=e.id AND x.canal <> 'outbox')").fetchone()[0]

    chaves = {c: {"valor": v, "ligado": _bool(v), "atualizado_em": a.isoformat() if a else None,
                  "por": p} for c, v, a, p in linhas}
    return {
        "chaves": chaves,
        "geral_ligado": chaves.get("notificacoes_ativas", {}).get("ligado", False),
        "canais": {
            "seriema": {
                "ligado": chaves.get("canal_seriema", {}).get("ligado", False),
                "configurado": seriema.configurado(), "dry_run": seriema.dry_run(),
                "transporte": seriema.provedor(),
                "destinos": len(seriema.destinos_nuvem()),
                "alcance": "EQUIPE — grupo interno de operação (não chega ao cliente)",
                # o próprio cliente responde: com dois transportes, texto fixo
                # aqui vira mentira na tela de quem opera
                "falta": seriema.falta_config(),
            },
            "whatsapp": {
                "ligado": chaves.get("canal_whatsapp", {}).get("ligado", False),
                "destinatarios": dict(dest).get("whatsapp", 0),
                "configurado": wpp_cloud.configurado(), "dry_run": wpp_cloud.dry_run(),
                "template": wpp_cloud.template_nome(),
                "alcance": "CLIENTE — Cloud API oficial da Meta, número em `destinatarios`",
                "falta": wpp_cloud.falta(),
            },
            "webhook": {
                "ligado": chaves.get("canal_webhook", {}).get("ligado", False),
                "destinatarios": dict(dest).get("webhook", 0),
                "alcance": "sistema externo (URL configurada)",
            },
        },
        "eventos_sem_envio_externo": pendentes,
        "historico": [{"chave": c, "de": d, "para": p, "quem": q,
                       "quando": w.isoformat() if w else None} for c, d, p, q, w in historico],
    }
