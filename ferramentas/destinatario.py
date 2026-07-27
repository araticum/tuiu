"""Destinatários de notificação — cadastrar, listar, desativar, testar.

Quem recebe alerta de andamento não é decisão de código nem de tela pública: é
uma linha em `destinatarios`, posta por quem tem acesso ao host. A carteira tem
50 organizações reais que nunca pediram para receber nada — o padrão é ninguém.

Cadastrar NÃO liga o canal. Continuam valendo as duas travas em série de
`app.config` (a geral e a do canal), que se ligam em /notificacoes.html com
autor e horário registrados.

Escopo: `--cnpj '*'` (padrão) recebe o andamento de TODA a carteira; um CNPJ
específico recebe só o daquele cliente.

Uso:
    python ferramentas/destinatario.py --listar
    python ferramentas/destinatario.py --add 61999990000 --canal whatsapp
    python ferramentas/destinatario.py --add https://... --canal webhook --cnpj 08949168000150
    python ferramentas/destinatario.py --desativar 5561999990000 --canal whatsapp
    python ferramentas/destinatario.py --testar 5561999990000 --modo texto --evento ultimo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import wpp_cloud  # noqa: E402
from app.config import estado  # noqa: E402
from app.db import conectar, migrar  # noqa: E402

CANAIS = ("whatsapp", "webhook")


def listar() -> None:
    with conectar() as con:
        linhas = con.execute(
            "SELECT id, cnpj, canal, endereco, ativo FROM destinatarios ORDER BY canal, id").fetchall()
    if not linhas:
        print("nenhum destinatário cadastrado — todo evento fica só na outbox")
        return
    for i, cnpj, canal, endereco, ativo in linhas:
        escopo = "toda a carteira" if cnpj == "*" else cnpj
        print(f"  [{i}] {canal:9s} {endereco:34s} {escopo:16s} {'ativo' if ativo else 'INATIVO'}")

    est = estado()["canais"]
    print("\ninterruptores (cadastrar não liga — ligue em /notificacoes.html):")
    for canal in CANAIS:
        c = est.get(canal, {})
        pend = c.get("falta")
        print(f"  {canal:9s} ligado={c.get('ligado')}"
              + (f" · configurado={c.get('configurado')}" if "configurado" in c else "")
              + (f" · FALTA: {pend}" if pend else ""))


def adicionar(endereco: str, canal: str, cnpj: str) -> None:
    if canal == "whatsapp":
        normalizado = wpp_cloud.normalizar_numero(endereco)
        if len(normalizado) < 12:
            sys.exit(f"número não parece E.164 completo: {endereco!r} -> {normalizado!r}\n"
                     f"informe com DDI+DDD (ex.: 5561999990000)")
        endereco = normalizado
    elif not endereco.startswith("http"):
        sys.exit(f"webhook precisa de URL: {endereco!r}")

    with conectar() as con:
        con.execute(
            "INSERT INTO destinatarios (cnpj, canal, endereco, ativo) VALUES (%s,%s,%s,true)"
            " ON CONFLICT (cnpj, canal, endereco) DO UPDATE SET ativo=true",
            (cnpj, canal, endereco))
        con.commit()
    escopo = "toda a carteira" if cnpj == "*" else cnpj
    print(f"OK {canal} -> {endereco} ({escopo})")
    print("   o canal ainda precisa ser LIGADO em /notificacoes.html")


def desativar(endereco: str, canal: str) -> None:
    endereco = wpp_cloud.normalizar_numero(endereco) if canal == "whatsapp" else endereco
    with conectar() as con:
        n = con.execute("UPDATE destinatarios SET ativo=false WHERE canal=%s AND endereco=%s",
                        (canal, endereco)).rowcount
        con.commit()
    print(f"{n} destinatário(s) desativado(s)" if n else "nada encontrado com esse endereço")


EXEMPLO = ["mudança de andamento", "Fundação Exemplo", "Convênio/CR 999999",
           "Prestação de Contas em Análise → Prestação de Contas em Complementação",
           "Prazo: 14/08/2026 (em 18d) · bola com o convenente · Próximo passo: enviar a complementação",
           "https://tuiu.araticum.net/cliente.html?doc=00000000000191", "27/07/2026"]


def _evento(qual: str) -> tuple[dict, dict]:
    """Um evento REAL da base + seu contexto — o teste mostra o que o pipe produz
    de verdade, não um exemplo que sempre parece bonito."""
    from app.notificador import contexto
    cols = ["id", "cnpj", "ente", "dominio", "chave", "rotulo", "tipo", "de", "para",
            "snapshot", "origem", "detalhe"]
    sql = ("SELECT id, cnpj, ente, dominio, chave, rotulo, tipo, de, para, snapshot::text,"
           " origem, detalhe FROM eventos WHERE cnpj <> 'nao_atribuido'")
    with conectar() as con:
        linha = con.execute(
            sql + (" ORDER BY id DESC LIMIT 1" if qual == "ultimo" else " AND id=%s"),
            () if qual == "ultimo" else (int(qual),)).fetchone()
        if not linha:
            sys.exit(f"evento não encontrado: {qual}")
        ev = dict(zip(cols, linha))
        ctx = contexto(con, ev["cnpj"], ev["chave"]) if ev["chave"] != "#count" else {}
    return ev, ctx


def testar(numero: str, modo: str, evento: str | None) -> None:
    """Dispara UMA mensagem de verdade, fora do motor de eventos.

    Serve para provar token/número/template antes de ligar o canal — e é o único
    caminho que manda WhatsApp sem passar pelos interruptores, por isso pede
    confirmação e não roda em lote. Não grava em `entregas`: teste não pode
    marcar um evento real como já notificado.

    `--modo texto` existe para a **janela de 24h**: se a pessoa escreveu para o
    número da API nas últimas 24h, texto livre entrega sem template aprovado.
    Fora da janela, só template — e aí o erro da Meta diz isso na cara.
    """
    from app.notificador import mensagem, parametros_template

    if not wpp_cloud.configurado():
        sys.exit(f"Cloud API não configurada — falta {wpp_cloud.falta()}")

    if evento:
        ev, ctx = _evento(evento)
        params, texto = parametros_template(ev, ctx), mensagem(ev, ctx)
        origem = f"evento #{ev['id']} ({ev['ente']})"
    else:
        params, texto = EXEMPLO, "\n".join(EXEMPLO[:5]) + f"\nAbrir: {EXEMPLO[5]}"
        origem = "exemplo embutido"

    seco = " [DRYRUN — nada sai]" if wpp_cloud.dry_run() else ""
    destino = wpp_cloud.normalizar_numero(numero)
    print(f"modo={modo} · origem={origem} · destino={destino}{seco}")
    print("-" * 60)
    print(texto if modo == "texto" else "\n".join(f"  {{{{{i}}}}} {p}" for i, p in enumerate(params, 1)))
    print("-" * 60)
    if not wpp_cloud.dry_run() and input("confirma o envio? [s/N] ").strip().lower() != "s":
        sys.exit("cancelado")

    if modo == "texto":
        ok, detalhe = wpp_cloud.enviar_texto(destino, texto)
    else:
        ok, detalhe = wpp_cloud.enviar_template(destino, params)
    print(("OK " if ok else "FALHOU ") + detalhe)
    if not ok and modo == "template" and "template" in detalhe.lower():
        print("  dica: enquanto o template não estiver APPROVED, use --modo texto "
              "(só entrega se a pessoa escreveu para o número nas últimas 24h)")
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--add", metavar="ENDERECO", help="número E.164 (whatsapp) ou URL (webhook)")
    ap.add_argument("--desativar", metavar="ENDERECO")
    ap.add_argument("--testar", metavar="NUMERO", help="manda uma mensagem agora")
    ap.add_argument("--modo", choices=("template", "texto"), default="template",
                    help="texto = janela de 24h, sem template aprovado")
    ap.add_argument("--evento", metavar="ID|ultimo",
                    help="usa um evento REAL da base em vez do exemplo")
    ap.add_argument("--canal", choices=CANAIS, default="whatsapp")
    ap.add_argument("--cnpj", default="*", help="'*' = toda a carteira (padrão)")
    args = ap.parse_args()

    migrar()
    if args.add:
        adicionar(args.add, args.canal, args.cnpj)
    elif args.desativar:
        desativar(args.desativar, args.canal)
    elif args.testar:
        testar(args.testar, args.modo, args.evento)
    else:
        listar()


if __name__ == "__main__":
    main()
