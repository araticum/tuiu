"""Baixa o acervo oficial de manuais do Transferegov (gov.br) para consulta local.

A estrutura de pastas do gov.br JÁ É o pipeline de gestão (Cadastro → Atos
Preparatórios → Execução → Prestação de Contas), e os tutoriais vêm separados por
PAPEL (Convenente = nosso cliente; Concedente = o órgão). Guardamos isso no
manifesto: é o esqueleto do guia.

Fonte: API REST do Plone do gov.br (`++api++`), que expõe título, tipo e tamanho —
mais confiável que raspar o HTML (a página é renderizada por JS).

Idempotente: pula arquivo já baixado com o mesmo tamanho. Não re-baixa 550 MB à toa.

    python ingest/manuais/baixar_manuais.py            # baixa tudo
    python ingest/manuais/baixar_manuais.py --so-listar # só monta o manifesto
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

BASE = "https://www.gov.br/transferegov/++api++/pt-br/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", "Accept": "application/json"}
DESTINO = Path("/mnt/dados-gov/tuiu-manuais")

# Acervo do GUIA de referência — inclusivo de propósito: o operador pergunta sobre
# qualquer coisa, e faltar um módulo custa um "não sei" (foi o que aconteceu com
# emendas e com o Relatório de Gestão/SIAFI). Cobre o universo do terceiro-executor:
# convênios (discricionarias), parcerias MROSC (gestao-de-parcerias), transferências
# especiais/Pix (relatório de gestão, campos SIAFI), cadastro/perfis (transversais)
# e as cartilhas de emendas parlamentares (que financiam convênio de OSC).
# NB: incluir Pix no GUIA de referência ≠ operar Pix — o núcleo (base rates/marcos)
# segue sem Pix. FORA do acervo: Obras, TED, Fundo a Fundo, PAC.
MODULOS = {
    "discricionarias": "manuais/transferegov/discricionarias",
    "parcerias": "manuais/transferegov/gestao-de-parcerias",
    "especiais": "manuais/transferegov/especiais",
    "cadastro": "manuais/transferegov/cadastro",
    "perfis": "manuais/transferegov/perfis-x-funcionalidades",
    # emendas: as cartilhas do gov.br dão 401 (restritas, via cadeia de Link) e são
    # pra PARLAMENTAR, não pra OSC. Cobrimos "requisitos p/ OSC receber emenda" no
    # GUIA autoral (seção própria), que é mais preciso pro nosso cliente.
}
# Nome legível do módulo, usado como ETAPA quando os PDFs vêm SOLTOS (sem
# subpasta): é o caso de parcerias/especiais/cadastro, onde cada arquivo é filho
# direto do módulo — sem isso ficariam sem etapa e fora da navegação/filtro.
MODULO_NOME = {
    "discricionarias": "Discricionárias e Legais",
    "parcerias": "Gestão de Parcerias (ciclo novo)",
    "especiais": "Transferências Especiais / Relatório de Gestão (Pix)",
    "cadastro": "Cadastro e credenciamento",
    "perfis": "Perfis e funcionalidades",
    "emendas": "Emendas Parlamentares",
    "mrosc": "MROSC — visão geral",
}
# Manual MROSC ponta a ponta de OSC. O link do gov.br dá 401 (restrito), então o
# PDF é PRÉ-COLOCADO no acervo pelo dono; aqui só catalogamos (não baixa).
AVULSOS = [{
    "modulo": "mrosc", "etapa": "MROSC — visão geral", "papel": "convenente",
    "titulo": "Manual MROSC — Do Planejamento à Prestação de Contas",
    "arquivo": str(DESTINO / "mrosc" / "Manual_MROSC_Do_Planejamento_a_Prestacao_de_Contas.pdf"),
}]


def _get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _papel(titulo: str) -> str:
    """De quem é a tarefa — o que decide se o tutorial serve ao nosso cliente."""
    t = titulo.lower()
    if "convenente" in t or "proponente" in t:
        return "convenente"
    if "concedente" in t or "mandataria" in t or "mandatária" in t:
        return "concedente"
    return "geral"


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s.-]", "", s, flags=re.UNICODE).strip()
    return re.sub(r"\s+", "_", s)[:120]


def catalogar(modulo: str, path: str, etapa: str = "", prof: int = 0,
              vistos: set | None = None) -> list[dict]:
    vistos = vistos if vistos is not None else set()
    if path in vistos or prof > 3:
        return []
    vistos.add(path)
    try:
        d = _get(path)
    except Exception as exc:  # noqa: BLE001 — um ramo fora do ar não derruba o resto
        print(f"  ! {path}: {exc}")
        return []
    if d.get("@type") == "File":
        f = d.get("file") or {}
        if "pdf" not in (f.get("content-type") or ""):
            return []
        titulo = d.get("title") or path.rsplit("/", 1)[-1]
        # sem subpasta (arquivo solto no módulo), a etapa cai no nome do módulo —
        # senão parcerias/cadastro ficariam sem etapa, fora da navegação e do filtro
        return [{"modulo": modulo, "etapa": etapa or MODULO_NOME.get(modulo, modulo),
                 "titulo": titulo, "papel": _papel(titulo), "url": f.get("download"),
                 "bytes_esperado": f.get("size") or 0}]
    saida = []
    for i in d.get("items") or []:
        sub = i.get("@id", "").split("/pt-br/")[-1]
        # o nome da subpasta é a ETAPA do pipeline — o esqueleto do guia
        nova_etapa = i.get("title") if (i.get("@type") in ("Document", "Folder") and prof == 0) else etapa
        saida += catalogar(modulo, sub, nova_etapa or etapa, prof + 1, vistos)
    return saida


def baixar(item: dict) -> dict:
    # arquivo PRÉ-COLOCADO no acervo (ex.: MROSC, cujo link do gov.br dá 401) —
    # não baixa, só confirma que está no disco.
    ja = item.get("arquivo")
    if ja and Path(ja).exists():
        item["bytes"] = Path(ja).stat().st_size
        item["pulado"] = True
        return item
    alvo = DESTINO / item["modulo"] / _slug(item.get("etapa") or "geral")
    alvo.mkdir(parents=True, exist_ok=True)
    arq = alvo / (_slug(item["titulo"]).removesuffix(".pdf") + ".pdf")
    if arq.exists() and item["bytes_esperado"] and abs(arq.stat().st_size - item["bytes_esperado"]) < 2048:
        item["arquivo"] = str(arq)
        item["bytes"] = arq.stat().st_size
        item["pulado"] = True
        return item
    req = urllib.request.Request(item["url"], headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=180) as r, open(arq, "wb") as fh:
        dados = r.read()
        fh.write(dados)
    item["arquivo"] = str(arq)
    item["bytes"] = len(dados)
    item["sha256"] = hashlib.sha256(dados).hexdigest()
    item["pulado"] = False
    return item


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--so-listar", action="store_true", help="monta o manifesto, não baixa")
    args = ap.parse_args()

    catalogo: list[dict] = []
    for modulo, path in MODULOS.items():
        itens = catalogar(modulo, path)
        print(f"{modulo}: {len(itens)} PDFs")
        catalogo += itens
    catalogo += AVULSOS
    print(f"catálogo: {len(catalogo)} documentos")

    if not args.so_listar:
        DESTINO.mkdir(parents=True, exist_ok=True)
        ok = falha = 0
        for i, item in enumerate(catalogo, 1):
            try:
                baixar(item)
                ok += 1
                marca = "=" if item.get("pulado") else "+"
                print(f"  [{i}/{len(catalogo)}] {marca} {item['titulo'][:64]}")
            except Exception as exc:  # noqa: BLE001
                falha += 1
                item["erro"] = str(exc)
                print(f"  [{i}/{len(catalogo)}] ! {item['titulo'][:50]}: {exc}")
        print(f"baixados/ok: {ok} | falhas: {falha}")

    (DESTINO / "manifesto.json").write_text(
        json.dumps(catalogo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifesto: {DESTINO/'manifesto.json'}")


if __name__ == "__main__":
    main()
