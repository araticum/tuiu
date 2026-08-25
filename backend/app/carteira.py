"""Serviço da Carteira (F0) — lê os recortes gerados pelo ingest.

Fonte de dados: data/recortes/<data>/<cnpj>/ (carteira.json do recorte_ente.py e
legado/*.csv do detru_recorte.py). Sem banco nesta fase — o walking skeleton
serve o que o ingest materializou; Postgres entra quando o motor de prazos (F1)
precisar de estado próprio.
"""

from __future__ import annotations

import csv
import json
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RECORTES = RAIZ / "data" / "recortes"

# Rótulos dos monitorados (espelho de ingest/transferegov_g2/recorte_ente.py).
# Escopo corrigido 18/07: o CLIENTE é o terceiro executor; os entes ficam como
# contraparte/contexto.
ROTULOS = {
    # terceiros executores (clientes)
    "20069629000103": "Ecos da Natureza/SP — OSC",
    "37113180000128": "Assoc. das Pioneiras Sociais/DF — OSC",
    "31883355000108": "Cooperativa Lixo Não/SP — cooperativa",
    # entes (contraparte / contexto)
    "01616520000196": "Águas Lindas de Goiás/GO — prefeitura (ente)",
    "07460294000183": "Águas Lindas de Goiás/GO — FMS (ente)",
    "34925198000136": "Cutias/AP — prefeitura (ente)",
    "12008067000151": "Cutias/AP — FMS (ente)",
    "15030230000170": "Cutias/AP — FMAS (ente)",
}


def snapshot_mais_recente() -> Path | None:
    if not RECORTES.exists():
        return None
    for d in sorted(RECORTES.iterdir(), reverse=True):
        if d.is_dir() and any((sub / "carteira.json").exists() for sub in d.iterdir() if sub.is_dir()):
            return d
    return None


def docs_ativos() -> set[str]:
    """CNPJs da carteira ATIVA.

    Recorte no disco NÃO é carteira: o diretório de um cliente desligado
    sobrevive à troca, e sem este filtro cada elo segue gastando trabalho com
    quem não é mais cliente — inclusive cota de API pública limitada (a CGU) e
    marcos/alertas que enchem a fila do operador.

    Conjunto vazio significa "não sei filtrar" (sem banco ou tabela vazia) e os
    chamadores devem processar tudo — degradar para o comportamento antigo é
    seguro; filtrar contra uma lista vazia apagaria a carteira inteira.
    """
    try:
        from app.db import conectar
        with conectar() as con:
            return {d for (d,) in con.execute("SELECT doc FROM clientes WHERE ativo")}
    except Exception:  # noqa: BLE001
        return set()


def nomes_carteira() -> dict[str, str]:
    """Nome de exibição por CNPJ, da tabela `clientes` (a fonte com os nomes
    reais dos 50 monitorados). O recorte do legado não traz razão social, então
    sem isto a carteira aparecia intitulada por CNPJ (Danilo, 07/2026). Degrada
    para {} sem banco — o chamador cai no rótulo/ nome do recorte."""
    try:
        from app.db import conectar
        with conectar() as con:
            return {d: (ap or nm) for d, ap, nm in con.execute(
                "SELECT doc, apelido, nome FROM clientes WHERE ativo")}
    except Exception:  # noqa: BLE001
        return {}


def nome_exibicao(cnpj: str, fallback: str | None = None, nomes: dict | None = None) -> str:
    """Como o cliente é chamado na tela e na mensagem. Ordem: rótulo escrito à
    mão -> `clientes` -> o que o chamador tinha -> o CNPJ.

    Existe em um lugar só porque o evento GRAVA o nome no momento do diff: quem
    resolver diferente na hora de exibir manda CNPJ cru para o WhatsApp de
    alguém — foi o que aconteceu com os 23 eventos de julho/2026.

    É também onde a razão social é CONSERTADA para leitura (decisão do dono,
    30/07: não se valida erro de plataforma, mesmo oficial). A correção vive aqui
    e só aqui, na saída: `clientes.nome` continua byte a byte igual ao que o
    Transferegov mandou, para a conferência contra a origem seguir trivial —
    `ferramentas/conferir_razao_social.py`.

    `ROTULOS` passa por fora: é rótulo escrito à mão, já correto, e reprocessar
    "Águas Lindas de Goiás/GO — prefeitura (ente)" só faria estrago.
    """
    from app.razao_social import exibir

    nomes = nomes_carteira() if nomes is None else nomes
    return ROTULOS.get(cnpj) or exibir(nomes.get(cnpj) or fallback) or cnpj


def escopo_instrumentos() -> set[tuple[str, str]]:
    """Pares (cnpj, instrumento) que a casa ACOMPANHA — a fila de trabalho.

    Não confundir com a carteira: `docs_ativos()` responde "de quem cuidamos",
    isto responde "de qual instrumento DAQUELE cliente cuidamos". O recorte traz
    a vida federal inteira de cada CNPJ, e faz bem — a ficha do cliente precisa
    dela. Mas a mesa e a notificação são fila, e ali entra só o que se opera.

    Conjunto VAZIO significa "não sei filtrar", e o chamador deve mostrar tudo.
    Degradar para o comportamento antigo é seguro; filtrar contra uma lista
    vazia esvaziaria a mesa e ninguém entenderia por quê.
    """
    from app.db import conectar

    try:
        with conectar() as con:
            return {(c, str(i)) for c, i in con.execute(
                "SELECT cnpj, instrumento FROM instrumentos_escopo WHERE ativo")}
    except Exception:  # noqa: BLE001 — tabela ainda não migrada: não filtra
        return set()


def _data_br(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _legado(dir_cnpj: Path) -> dict:
    conv_csv = dir_cnpj / "legado" / "convenio.csv"
    prop_csv = dir_cnpj / "legado" / "proposta.csv"
    if not conv_csv.exists():
        return {"instrumentos": 0, "ativos": 0, "contratos_repasse_ativos": 0,
                "por_situacao": {}, "prestacoes": []}

    modalidade = {}
    if prop_csv.exists():
        with open(prop_csv, encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                modalidade[row.get("ID_PROPOSTA")] = row.get("MODALIDADE")

    hoje = date.today()
    por_situacao: dict[str, int] = {}
    prestacoes, ativos, repasse_ativos, total = [], 0, 0, 0
    with open(conv_csv, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            total += 1
            mod = modalidade.get(row.get("ID_PROPOSTA")) or "?"
            chave = f"{mod} · {row.get('SIT_CONVENIO')}"
            por_situacao[chave] = por_situacao.get(chave, 0) + 1
            ativo = (row.get("INSTRUMENTO_ATIVO") or "").upper() == "SIM"
            if ativo:
                ativos += 1
                if "REPASSE" in mod.upper():
                    repasse_ativos += 1
                lim = _data_br(row.get("DIA_LIMITE_PREST_CONTAS"))
                if lim:
                    dias = (lim - hoje).days
                    prestacoes.append({
                        "nr_convenio": row.get("NR_CONVENIO"), "modalidade": mod,
                        "situacao": row.get("SIT_CONVENIO"),
                        "fim_vigencia": row.get("DIA_FIM_VIGENC_CONV"),
                        "limite_prestacao": lim.isoformat(), "dias": dias,
                        "farol": "vencido" if dias < 0 else ("atencao" if dias <= 90 else "ok"),
                    })
    prestacoes.sort(key=lambda p: p["limite_prestacao"])
    return {"instrumentos": total, "ativos": ativos, "contratos_repasse_ativos": repasse_ativos,
            "por_situacao": por_situacao, "prestacoes": prestacoes}


def listar_entes() -> dict:
    snap = snapshot_mais_recente()
    if snap is None:
        return {"snapshot": None, "entes": []}
    nomes = nomes_carteira()
    entes = []
    for sub in sorted(snap.iterdir()):
        cj = sub / "carteira.json"
        if not (sub.is_dir() and cj.exists()):
            continue
        carteira = json.loads(cj.read_text(encoding="utf-8"))
        cnpj = carteira.get("cnpj", sub.name)
        # nome real (clientes) > rótulo de teste (ROTULOS) > nome do recorte > CNPJ
        carteira["rotulo"] = nomes.get(cnpj) or ROTULOS.get(cnpj) or carteira.get("nome") or cnpj
        carteira["legado"] = _legado(sub)
        reg = sub / "regularidade.json"
        carteira["regularidade"] = (
            json.loads(reg.read_text(encoding="utf-8")) if reg.exists()
            else {"disponivel": False, "motivo": "ainda não coletado"}
        )
        entes.append(carteira)
    ordem = list(ROTULOS)
    entes.sort(key=lambda e: ordem.index(e["cnpj"]) if e["cnpj"] in ordem else 99)
    return {"snapshot": snap.name, "entes": entes}
