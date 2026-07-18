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
