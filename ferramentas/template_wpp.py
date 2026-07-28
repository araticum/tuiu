"""Template do WhatsApp — submeter à Meta, listar e acompanhar a aprovação.

O alerta de andamento é proativo e cai FORA da janela de 24h; ali a Meta só
entrega mensagem de template APROVADO. Este é o caminho de ida e volta desse
template, sem passar pelo WhatsApp Manager na mão.

O corpo é o mesmo que está em `docs/motor-eventos-notificacao.md` — e é **fonte
única**: `backend/app/notificador.parametros_template()` monta os 7 valores na
ordem exata de {{1}}..{{7}}. Mexer aqui sem mexer lá manda parâmetro trocado.

Config: `TUIU_WPP_TOKEN` (ou cofre DPAPI) e `TUIU_WPP_WABA_ID`.
O WABA precisa estar ATRIBUÍDO ao system user do token (Business Manager ->
Usuários do sistema -> Adicionar ativos -> Contas do WhatsApp), senão a Meta
responde "(#200) Missing permission" mesmo com o token válido.

Uso:
    python ferramentas/template_wpp.py --listar
    python ferramentas/template_wpp.py --submeter          # cria (ou avisa que já existe)
    python ferramentas/template_wpp.py --submeter --forcar # atualiza o corpo do existente
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

# O corpo do template tem → e · ; no console do Windows (cp1252) o print estoura
# com UnicodeEncodeError e a ferramenta morre justo ao mostrar o que vai enviar.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import wpp_cloud  # noqa: E402

CATEGORIA = "UTILITY"       # aviso operacional sobre transação em curso, não marketing

# ⚠️ ordem casada com notificador.parametros_template()
#
# CINCO variáveis, não mais. A Meta recusa template com variáveis demais para o
# tamanho do texto fixo (erro 2388293, "muitas variáveis para sua extensão") — a
# versão de 7 foi rejeitada. Nada de informação se perdeu: o tipo do evento
# entrou no {{3}} e a data do dado no fim do {{4}}.
CORPO = (
    "*Tuiú* · aviso de andamento\n"
    "\n"
    "Um instrumento da sua carteira mudou de situação no Transferegov.\n"
    "\n"
    "Cliente: {{1}}\n"
    "Instrumento: {{2}}\n"
    "Situação: {{3}}\n"
    "\n"
    "O que fazer agora: {{4}}\n"
    "\n"
    "Abra a ficha no console para ver o histórico completo, os prazos e "
    "registrar o atendimento: {{5}}\n"
    "\n"
    "_Fonte: dados abertos do Transferegov, com um dia de defasagem (D-1)._"
)
EXEMPLO = [
    "FUNDACAO FACULDADE DE MEDICINA",
    "Convênio/CR 850704",
    "mudança de andamento: Prestação de Contas em Análise → Prestação de Contas em Complementação",
    "Prazo: 14/08/2026 (em 18d) · bola com o convenente · Próximo passo: enviar a complementação "
    "· dados de 25/07/2026",
    "https://tuiu.araticum.net/cliente.html?doc=60453032000174",
]

# ---------------------------------------------------------------------------
# Segundo template: o RESUMO do dia (a triagem que o Danilo pediu em 27/07).
# Nao substitui o de cima — sao mensagens de natureza diferente, e a Meta cobra
# um template por formato. Este e o que vai por padrao; o de evento fica para um
# recorte critico futuro (ver db/0028).
#
# Tres posicoes FIXAS de item porque a contagem de parametros do template e fixa
# na Meta. Sobra vira travessao: feio, mas parametro vazio e recusado no envio e
# inventar item para preencher seria pior.
CORPO_RESUMO = "\n".join([
    "*Tuiú* · resumo do dia",
    "",
    "{{1}}",
    "",
    "Precisa de você agora:",
    "• {{2}}",
    "• {{3}}",
    "• {{4}}",
    "",
    "{{5}}",
    "",
    "A mesa completa, já priorizada, está no console: "
    "https://tuiu.araticum.net/mesa.html",
    "_Andamento do Transferegov, com um dia de defasagem (D-1)._",
])
EXEMPLO_RESUMO = [
    "8 mudança(s) na carteira hoje. 2 pede(m) sua ação.",
    "CONFEDERACAO BRASILEIRA DO DESPORTO ESCOLAR · Convênio/CR 935588 (em 11d) — "
    "Montar e enviar a prestação de contas no Transferegov",
    "FUNDACAO FACULDADE DE MEDICINA · Convênio/CR 850704 (em 26d) — "
    "Montar e enviar a prestação de contas no Transferegov",
    "—",
    "2 mudança(s) estão com o órgão — nada a fazer.",
]

MODELOS = {
    "andamento": (CORPO, EXEMPLO),
    "resumo": (CORPO_RESUMO, EXEMPLO_RESUMO),
}


def _modelo(qual: str) -> tuple[str, list[str]]:
    if qual not in MODELOS:
        sys.exit(f"modelo desconhecido: {qual} (use {', '.join(MODELOS)})")
    return MODELOS[qual]


def nome_do_modelo(qual: str) -> str:
    return wpp_cloud.template_nome() if qual == "andamento" else "aviso_tuiu_resumo"


def _token() -> str:
    return wpp_cloud._cfg("TUIU_WPP_TOKEN")


def _waba() -> str:
    waba = (os.environ.get("TUIU_WPP_WABA_ID") or "").strip()
    if not waba:
        sys.exit("falta TUIU_WPP_WABA_ID (WhatsApp Manager -> Configurações -> ID da conta)")
    return waba


def _chamar(metodo: str, caminho: str, payload: dict | None = None) -> dict:
    url = f"{wpp_cloud.BASE_GRAPH}/{wpp_cloud._cfg('TUIU_WPP_VERSAO', 'v21.0')}/{caminho}"
    dados = json.dumps(payload, ensure_ascii=False).encode() if payload else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers={
        "Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        bruto = e.read()[:600].decode("utf-8", "replace")
        try:
            err = json.loads(bruto).get("error", {})
            return {"_erro": f"Meta {err.get('code')}/{err.get('error_subcode')}: "
                             f"{err.get('message')} — {err.get('error_user_msg') or ''}".strip(" —")}
        except Exception:  # noqa: BLE001
            return {"_erro": f"HTTP {e.code}: {bruto}"}
    except Exception as e:  # noqa: BLE001
        return {"_erro": f"{type(e).__name__}: {e}"}


def _existentes(nome: str) -> list[dict]:
    r = _chamar("GET", f"{_waba()}/message_templates?fields=id,name,status,category,language"
                       f"&name={nome}&limit=50")
    if "_erro" in r:
        sys.exit(r["_erro"])
    return [t for t in r.get("data") or [] if t.get("name") == nome]


def listar() -> None:
    r = _chamar("GET", f"{_waba()}/message_templates?fields=id,name,status,category,language"
                       f",rejected_reason&limit=100")
    if "_erro" in r:
        sys.exit(r["_erro"])
    linhas = r.get("data") or []
    if not linhas:
        print("nenhum template nesta WABA")
        return
    for t in linhas:
        motivo = f"  motivo: {t['rejected_reason']}" if t.get("rejected_reason") not in (None, "NONE") else ""
        print(f"  {t['name']:24s} {t.get('language'):6s} {t.get('category'):10s} "
              f"{t.get('status')}{motivo}")
    print("\nAPPROVED = já entrega fora da janela de 24h · PENDING = em análise (costuma levar minutos a horas)")


def submeter(forcar: bool, qual: str = "andamento") -> None:
    corpo, exemplo = _modelo(qual)
    nome = nome_do_modelo(qual)
    idioma = wpp_cloud._cfg("TUIU_WPP_IDIOMA", "pt_BR")
    if len(exemplo) != corpo.count("{{"):
        sys.exit(f"exemplo com {len(exemplo)} valores para {corpo.count('{{')} variáveis — a Meta recusa")

    componentes = [{
        "type": "BODY", "text": corpo,
        # a Meta EXIGE amostra para cada variável; sem isso a submissão é recusada
        "example": {"body_text": [exemplo]},
    }]

    ja = _existentes(nome)
    if ja and not forcar:
        for t in ja:
            print(f"já existe: {t['name']} / {t.get('language')} -> {t.get('status')} (id {t['id']})")
        print("use --forcar para reenviar o corpo (volta para PENDING)")
        return

    if ja and forcar:
        alvo = next((t for t in ja if t.get("language") == idioma), ja[0])
        r = _chamar("POST", alvo["id"], {"components": componentes})
        if not r.get("_erro"):
            print(f"atualizado: {nome}/{idioma} reenviado para análise")
            return
        # NUNCA apagar como fallback automático: a Meta segura o nome de um
        # template excluído por até 30 dias, e a recusa costuma ser de VALIDAÇÃO
        # (corpo inválido), que se conserta editando. Já queimei o nome
        # `aviso_tuiu` assim em 27/07 — apagar é decisão de quem opera.
        sys.exit(f"edição recusada: {r['_erro']}\n"
                 f"Se for erro de validação, corrija o CORPO e rode de novo.\n"
                 f"Se a Meta disser que o template está em análise e você aceitar "
                 f"perder o nome por até 30 dias, use --apagar e escolha outro nome.")

    r = _chamar("POST", f"{_waba()}/message_templates", {
        "name": nome, "language": idioma, "category": CATEGORIA, "components": componentes})
    if r.get("_erro"):
        sys.exit(r["_erro"])
    print(f"submetido: {nome}/{idioma} id={r.get('id')} status={r.get('status', 'PENDING')}")
    print("acompanhe com --listar; enquanto não estiver APPROVED, só entrega dentro da janela de 24h")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--submeter", action="store_true")
    ap.add_argument("--forcar", action="store_true", help="atualiza o corpo de um template já existente")
    ap.add_argument("--apagar", metavar="NOME",
                    help="apaga um template. A Meta segura o nome por ATE 30 DIAS — sem volta")
    ap.add_argument("--corpo", action="store_true", help="só mostra o corpo que será enviado")
    ap.add_argument("--modelo", choices=sorted(MODELOS), default="andamento")
    args = ap.parse_args()

    if args.apagar:
        if input(f"apagar `{args.apagar}` e perder o nome por até 30 dias? [s/N] ").strip().lower() != "s":
            sys.exit("cancelado")
        r = _chamar("DELETE", f"{_waba()}/message_templates?name={args.apagar}")
        sys.exit(r["_erro"] if r.get("_erro") else f"apagado: {args.apagar}")
    if args.corpo:
        corpo, exemplo = _modelo(args.modelo)
        print(f"# {nome_do_modelo(args.modelo)}\n")
        print(corpo)
        print("\nexemplo:", json.dumps(exemplo, ensure_ascii=False, indent=2))
        return
    if not wpp_cloud.configurado() and not args.listar:
        sys.exit(f"Cloud API não configurada — falta {wpp_cloud.falta()}")
    if args.submeter:
        submeter(args.forcar, args.modelo)
    else:
        listar()


if __name__ == "__main__":
    main()
