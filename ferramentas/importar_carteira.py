"""Carrega a carteira REAL a partir da lista de instrumentos de trabalho.

Decisão do dono (24/08/2026): não há mais dogfood — a lista enviada são os
instrumentos reais de trabalho, e o sistema passa a se basear nela. Este comando
troca a carteira de 50 OSCs de teste pelo conjunto que a casa opera de verdade.

## O problema que ele resolve

A lista identifica o instrumento por **número de convênio** e por **proposta**, e
não traz CNPJ. Todo o encanamento do Tuiú é chaveado por CNPJ: `clientes.doc`, o
diretório do recorte, `marcos.cnpj`. Sem a ponte, a lista não entra.

A ponte usa os dumps que a cadeia diária já baixa:

    NR_CONVENIO --(siconv_convenio)--> ID_PROPOSTA --(siconv_proposta)--> IDENTIF_PROPONENTE

Linha ainda em fase de plano não tem convênio; essa resolve direto pelo campo
`NR_PROPOSTA`, que no dump **já vem com o ano embutido** (`42651/2019`). Casar
por número e ano separados não acha nada — e não acha em SILÊNCIO, que foi como
o primeiro ensaio marcou 0 de 352 sem levantar erro nenhum.

## Duas armadilhas do dump, ambas silenciosas

1. **BOM de UTF-8 em arquivo latin-1.** Lido como latin-1, `NR_CONVENIO` chega
   como `ï»¿NR_CONVENIO` e todo `.get("NR_CONVENIO")` devolve `None`. Por isso a
   normalização remove qualquer prefixo não-alfabético do cabeçalho, em vez de
   remover um BOM específico.
2. **O nome no dump é a razão social oficial; o da lista é o apelido de quem
   opera** (`AVB`, `INSTITUTO ACERTE (2)`). O oficial vai para `nome`, o da lista
   para `apelido` — quem trabalha reconhece o segundo, e o primeiro é o que
   confere com a fonte.

## O que este comando NÃO faz

**Grava também o ESCOPO**, em `instrumentos_escopo`: quais convênios de cada
cliente a casa acompanha. Sem isso a mesa mostrava a vida federal inteira do
CNPJ — 38% da notificação de 25/08 era instrumento que ninguém opera, incluindo
o item do topo da mensagem.

**Não apaga cliente nenhum.** Quem sai da carteira vira `ativo=false`, e
`carteira.docs_ativos()` já filtra por isso. Marcos, eventos e histórico da fila
continuam no banco: desligar é reversível, apagar não é, e a carteira antiga é
prova do que já foi operado.

Uso:
    py -3 ferramentas/importar_carteira.py lista.csv              # simula (padrão)
    py -3 ferramentas/importar_carteira.py lista.csv --aplicar
    py -3 ferramentas/importar_carteira.py lista.csv --aplicar --manter-antigos
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))

from app.db import conectar, migrar  # noqa: E402
from app.texto_br import qtd, verbo  # noqa: E402

CACHE = RAIZ / "data" / "detru" / "cache"
COL_ENTIDADE, COL_CONVENIO, COL_PROPOSTA = "Entidade", "Convênio", "Proposta"
COL_SITUACAO, COL_RESPONSAVEL = "Situação", "Responsável"


def cabecalho(linha: list[str]) -> list[str]:
    """Remove o prefixo não-alfabético — o BOM de UTF-8 lido como latin-1."""
    return [re.sub(r"^[^A-Za-z_]+", "", c).strip() for c in linha]


def _dump(nome: str):
    caminho = CACHE / f"{nome}.zip"
    if not caminho.exists():
        raise SystemExit(f"falta {caminho} — rode a cadeia diária para baixar o cache do detru")
    z = zipfile.ZipFile(caminho)
    with z.open(z.namelist()[0]) as fh:
        leitor = csv.reader(io.TextIOWrapper(fh, encoding="latin-1", newline=""), delimiter=";")
        cab = cabecalho(next(leitor))
        for linha in leitor:
            if len(linha) == len(cab):
                yield dict(zip(cab, linha))


def ler_lista(caminho: Path) -> list[dict]:
    """A lista tem preâmbulo antes do cabeçalho; acha a linha que abre a tabela."""
    linhas = caminho.read_text(encoding="utf-8-sig").splitlines()
    try:
        i = next(k for k, l in enumerate(linhas) if l.startswith(f"{COL_ENTIDADE};"))
    except StopIteration:
        raise SystemExit(f"não achei o cabeçalho '{COL_ENTIDADE};...' em {caminho}")
    return list(csv.DictReader(linhas[i:], delimiter=";"))


def resolver(alvo: list[dict]) -> tuple[list[dict], list[dict]]:
    """Cada linha da lista para o CNPJ do proponente. Devolve (resolvidos, sem)."""
    convs = {(r.get(COL_CONVENIO) or "").strip() for r in alvo if (r.get(COL_CONVENIO) or "").strip()}
    props = {(r.get(COL_PROPOSTA) or "").strip() for r in alvo if (r.get(COL_PROPOSTA) or "").strip()}

    conv_id = {}
    for row in _dump("siconv_convenio"):
        nr = (row.get("NR_CONVENIO") or "").strip()
        if nr in convs:
            conv_id[nr] = (row.get("ID_PROPOSTA") or "").strip()

    ids = set(conv_id.values())
    por_id, por_prop = {}, {}
    for row in _dump("siconv_proposta"):
        idp = (row.get("ID_PROPOSTA") or "").strip()
        nr = (row.get("NR_PROPOSTA") or "").strip()
        dupla = ((row.get("IDENTIF_PROPONENTE") or "").strip(),
                 (row.get("NM_PROPONENTE") or "").strip())
        if idp and idp in ids:
            por_id[idp] = dupla
        if nr in props:
            por_prop[nr] = dupla

    resolvidos, sem = [], []
    for r in alvo:
        conv = (r.get(COL_CONVENIO) or "").strip()
        prop = (r.get(COL_PROPOSTA) or "").strip()
        achado, via = None, ""
        if conv and conv in conv_id and conv_id[conv] in por_id:
            achado, via = por_id[conv_id[conv]], "convênio"
        elif prop in por_prop:
            achado, via = por_prop[prop], "proposta"
        reg = {"entidade": (r.get(COL_ENTIDADE) or "").strip(), "convenio": conv,
               "proposta": prop, "situacao": (r.get(COL_SITUACAO) or "").strip(),
               "responsavel": (r.get(COL_RESPONSAVEL) or "").strip()}
        if achado and len(re.sub(r"\D", "", achado[0])) == 14:
            reg.update({"cnpj": re.sub(r"\D", "", achado[0]), "nome": achado[1], "via": via})
            resolvidos.append(reg)
        else:
            sem.append(reg)
    return resolvidos, sem


def consolidar(resolvidos: list[dict]) -> dict[str, dict]:
    """Uma entrada por CNPJ. O apelido só entra quando difere do nome oficial —
    repetir a razão social no apelido é ruído na tela."""
    fora: dict[str, dict] = {}
    for r in resolvidos:
        c = fora.setdefault(r["cnpj"], {"nome": r["nome"], "apelidos": set(), "instrumentos": 0})
        c["instrumentos"] += 1
        if r["entidade"] and r["entidade"].upper() != r["nome"].upper():
            c["apelidos"].add(r["entidade"])
    for c in fora.values():
        # vários apelidos para o mesmo CNPJ acontece (`INSTITUTO ACERTE (2)`);
        # fica o mais curto, que é como a pessoa chama no dia a dia
        c["apelido"] = min(c["apelidos"], key=len) if c["apelidos"] else None
        del c["apelidos"]
    return fora


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("lista", type=Path, help="CSV com a lista de instrumentos de trabalho")
    ap.add_argument("--aplicar", action="store_true", help="grava (o padrão é só simular)")
    ap.add_argument("--manter-antigos", action="store_true",
                    help="não desliga quem está fora da lista")
    ap.add_argument("--saida", type=Path, help="grava o resolvido em JSON, para os próximos passos")
    args = ap.parse_args()

    alvo = ler_lista(args.lista)
    print(f"lista: {qtd(len(alvo), 'linha', 'linhas')}")
    resolvidos, sem = resolver(alvo)
    print(f"resolvidos: {len(resolvidos)} · "
          f"por convênio {sum(1 for r in resolvidos if r['via'] == 'convênio')} · "
          f"por proposta {sum(1 for r in resolvidos if r['via'] == 'proposta')}")
    if sem:
        print(f"\n! {qtd(len(sem), 'linha NÃO resolvida', 'linhas NÃO resolvidas')} — "
              f"{verbo(len(sem), 'fica', 'ficam')} fora da carteira:")
        for r in sem:
            print(f"    {r['entidade'][:46]:46s} conv={r['convenio'] or '—'} prop={r['proposta']}")

    novos = consolidar(resolvidos)
    print(f"\ncarteira da lista: {qtd(len(novos), 'entidade', 'entidades')}")

    migrar()
    with conectar() as con:
        atuais = {d: (n, a) for d, n, a in con.execute("SELECT doc, nome, ativo FROM clientes")}
    pares = {(r["cnpj"], str(r["convenio"] or r["proposta"]))
             for r in resolvidos if (r["convenio"] or r["proposta"])}
    with conectar() as con:
        try:
            no_escopo = {(c, str(i)) for c, i in con.execute(
                "SELECT cnpj, instrumento FROM instrumentos_escopo WHERE ativo")}
        except Exception:  # noqa: BLE001 — antes da migração
            con.rollback()
            no_escopo = set()
    entram = [d for d in novos if d not in atuais]
    reativam = [d for d in novos if d in atuais and not atuais[d][1]]
    desligam = [d for d, (_, ativo) in atuais.items() if ativo and d not in novos]

    print(f"  entram novos:        {len(entram)}")
    print(f"  já existem e ficam:  {len(novos) - len(entram)}"
          + (f" (dos quais {len(reativam)} reativados)" if reativam else ""))
    print(f"  instrumentos no escopo: {len(pares)}"
          f"  ({len(pares - no_escopo)} novos, {len(no_escopo - pares)} saem da fila)")
    print(f"  saem da carteira:    {len(desligam)}"
          + ("  [--manter-antigos: nenhum sai]" if args.manter_antigos
             else "  (ativo=false, não apagados)"))

    if args.saida:
        args.saida.write_text(json.dumps({"resolvidos": resolvidos, "sem": sem},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nresolvido gravado em {args.saida}")

    if not args.aplicar:
        print("\n(simulação — nada foi gravado; use --aplicar)")
        return 0

    with conectar() as con:
        for doc, c in novos.items():
            con.execute(
                "INSERT INTO clientes (doc, tipo_doc, nome, apelido, ativo)"
                " VALUES (%s,'CNPJ',%s,%s,true)"
                " ON CONFLICT (doc) DO UPDATE SET nome=EXCLUDED.nome,"
                " apelido=COALESCE(EXCLUDED.apelido, clientes.apelido), ativo=true",
                (doc, c["nome"], c["apelido"]))
        if desligam and not args.manter_antigos:
            con.execute("UPDATE clientes SET ativo=false WHERE doc = ANY(%s)", (desligam,))
        # o escopo é reescrito inteiro: desliga o que saiu da lista e liga o que
        # entrou. `ativo=false` em vez de DELETE — tirar da fila não pode apagar
        # o registro de que um dia esteve lá.
        con.execute("UPDATE instrumentos_escopo SET ativo=false WHERE ativo")
        for cnpj, instr in sorted(pares):
            con.execute(
                "INSERT INTO instrumentos_escopo (cnpj, instrumento, origem, ativo)"
                " VALUES (%s,%s,'lista',true) ON CONFLICT (cnpj, instrumento)"
                " DO UPDATE SET ativo=true, origem='lista'", (cnpj, instr))
        con.commit()
    print(f"\ngravado: {len(novos)} na carteira ativa, "
          f"{0 if args.manter_antigos else len(desligam)} desligados")
    print("Próximo passo: rodar a cadeia diária para gerar o recorte dos novos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
