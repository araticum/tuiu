"""Dossiê por instrumento (F3, versão simples) — pasta local, sem Sargaço.

Decisão do dono (18/07): manter simples. O dossiê é um diretório por ente e
instrumento em `data/dossies/<cnpj>/<instrumento>/`, com um `indice.json` que
lista os arquivos (nome, tamanho, sha256, quando entrou). Serve para guardar os
comprovantes que a prestação de contas exige, com a guarda legal (5 ou 10 anos
conforme o regime) registrada junto.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
BASE = RAIZ / "data" / "dossies"


# --------------------------------------------------------- checklist do dossiê
# Catálogo canônico do dossiê de prestação de contas — as categorias da planilha
# do Danilo. É status (feito/não), não upload: rastreio manual do que a OSC já
# reuniu, já que o Transferegov não expõe isso. O % da Mesa sai daqui.
ITENS_DOSSIE = [
    ("plano_trabalho", "Plano de trabalho aprovado + termo e aditivos"),
    ("contratos", "Contratos com fornecedores / processo de contratação"),
    ("notas_fiscais", "Notas fiscais e comprovantes de despesa"),
    ("pagamentos_obtv", "Comprovantes de pagamento (OBTV / ordens bancárias)"),
    ("extratos", "Extratos bancários da conta específica"),
    ("conciliacao", "Conciliação bancária e rendimentos de aplicação"),
    ("relatorio_objeto", "Relatório de cumprimento do objeto"),
    ("devolucao_saldo", "Comprovante de devolução de saldo (se houver)"),
]
_ITENS_MAP = dict(ITENS_DOSSIE)


def checklist_estado(cnpj: str, instrumento: str) -> dict:
    """Os itens do dossiê e o que já foi marcado como feito, para um convênio."""
    from app.db import conectar
    doc = "".join(c for c in cnpj if c.isdigit())
    marcado: dict[str, dict] = {}
    with conectar() as con:
        for item, feito, nota, por, quando in con.execute(
                "SELECT item, feito, nota, marcado_por, marcado_em FROM dossie_checklist"
                " WHERE cnpj=%s AND instrumento=%s", (doc, str(instrumento))):
            marcado[item] = {"feito": feito, "nota": nota, "por": por,
                             "quando": quando.isoformat() if quando else None}
        # EVIDENCIADO não é FEITO: o dado aberto registra que o documento
        # existe; feito é alguém da casa ter conferido e anexado. O órgão pede o
        # documento, não a notícia de que ele existe — marcar automático seria
        # mentir para quem presta contas. O que a evidência faz é tirar o
        # operador do zero: ele sabe o que procurar, onde e quantos.
        from app.evidencia import do_instrumento
        evid = do_instrumento(doc, str(instrumento), con)

    itens = [{"item": k, "rotulo": r, **{"feito": False, "nota": None},
              **marcado.get(k, {}), "evidencia": evid.get(k)} for k, r in ITENS_DOSSIE]
    n = sum(1 for i in itens if i["feito"])
    n_evid = sum(1 for i in itens if i.get("evidencia") and not i["feito"])
    return {"cnpj": doc, "instrumento": str(instrumento), "itens": itens,
            "feitos": n, "evidenciados": n_evid, "total": len(ITENS_DOSSIE),
            "pct": round(100 * n / len(ITENS_DOSSIE)) if ITENS_DOSSIE else 0}


def marcar_item(cnpj: str, instrumento: str, item: str, feito: bool, por: str | None) -> dict:
    from app.db import conectar
    if item not in _ITENS_MAP:
        return {"ok": False, "erro": "item de dossiê desconhecido"}
    doc = "".join(c for c in cnpj if c.isdigit())
    if not doc or not instrumento:
        return {"ok": False, "erro": "informe cnpj e instrumento"}
    with conectar() as con:
        con.execute(
            "INSERT INTO dossie_checklist (cnpj, instrumento, item, feito, marcado_por, marcado_em)"
            " VALUES (%s,%s,%s,%s,%s, now())"
            " ON CONFLICT (cnpj, instrumento, item)"
            " DO UPDATE SET feito=EXCLUDED.feito, marcado_por=EXCLUDED.marcado_por, marcado_em=now()",
            (doc, str(instrumento), item, bool(feito), por))
        con.commit()
    return {"ok": True, **checklist_estado(doc, instrumento)}


def percentuais(con) -> dict[tuple, dict]:
    """{(cnpj, instrumento): {feitos,total,pct}} para a Mesa. Só convênios com
    ao menos uma marca aparecem; os demais são 0% (sem linha)."""
    total = len(ITENS_DOSSIE)
    out: dict[tuple, dict] = {}
    for cnpj, instr, n in con.execute(
            "SELECT cnpj, instrumento, count(*) FILTER (WHERE feito)"
            " FROM dossie_checklist GROUP BY 1,2"):
        out[(cnpj, instr)] = {"feitos": n, "total": total,
                              "pct": round(100 * n / total) if total else 0}
    return out


def _pasta(cnpj: str, instrumento: str) -> Path:
    doc = "".join(c for c in cnpj if c.isdigit())
    seguro = "".join(c for c in str(instrumento) if c.isalnum() or c in "-_.")[:60] or "sem-numero"
    return BASE / doc / seguro


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as fh:
        while bloco := fh.read(1 << 20):
            h.update(bloco)
    return h.hexdigest()


def guardar(cnpj: str, instrumento: str, nome_arquivo: str, conteudo: bytes,
            guarda_ate: str | None = None) -> dict:
    """Grava um documento no dossiê e atualiza o índice. Idempotente por sha256."""
    pasta = _pasta(cnpj, instrumento)
    pasta.mkdir(parents=True, exist_ok=True)
    seguro = Path(nome_arquivo).name.replace("\\", "_")
    destino = pasta / seguro
    destino.write_bytes(conteudo)
    registro = {
        "arquivo": seguro, "bytes": len(conteudo), "sha256": _sha256(destino),
        "guardado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "guarda_ate": guarda_ate,
    }
    idx = pasta / "indice.json"
    atual = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else {"documentos": []}
    atual["documentos"] = [d for d in atual["documentos"] if d["arquivo"] != seguro] + [registro]
    atual["cnpj"], atual["instrumento"] = cnpj, instrumento
    idx.write_text(json.dumps(atual, ensure_ascii=False, indent=2), encoding="utf-8")
    return registro


def listar(cnpj: str, instrumento: str | None = None) -> dict:
    doc = "".join(c for c in cnpj if c.isdigit())
    raiz = BASE / doc
    if not raiz.exists():
        return {"cnpj": doc, "instrumentos": []}
    saida = []
    for p in sorted(raiz.iterdir()):
        if not p.is_dir():
            continue
        if instrumento and p.name != instrumento:
            continue
        idx = p / "indice.json"
        dados = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else {"documentos": []}
        saida.append({"instrumento": p.name, "documentos": dados.get("documentos", []),
                      "total": len(dados.get("documentos", []))})
    return {"cnpj": doc, "instrumentos": saida}
