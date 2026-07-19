"""Carteira de dogfood: os N maiores executores de cada recorte temático.

POR QUE A FONTE É O SICONV (detru) E NÃO A g2 (decisão medida, 19/07/2026):

A primeira versão ranqueava pelo dump da g2. Não serve para recorte temático —
no universo PRIVADO a g2 só carrega dois órgãos superiores (Saúde e Meio
Ambiente) e, na prática, três instrumentos: Lei de Incentivo à Reciclagem,
PRONON e PRONAS/PCD. Não existem 3º, 4º e 5º temas ali. Isso é consequência
conhecida do recorte da g2 (só ciclo novo, ~2025+); o estoque 2008→ está nos
CSVs detru, e é lá que a diversidade temática existe: 19.330 OSCs distribuídas
por Saúde, Assistência Social, Educação, Agricultura, Esporte, Cultura, Direitos
Humanos, Turismo, C&T, Meio Ambiente...

MÉTRICA
    tema     = DESC_ORGAO_SUP (órgão superior repassador) — o tema de fato
    tamanho  = soma de VL_REPASSE_CONV dos instrumentos CELEBRADOS
    exigência= pelo menos 1 instrumento com INSTRUMENTO_ATIVO=SIM

A exigência de instrumento vivo é o que separa dogfood útil de arquivo morto:
uma OSC gigante em 2010 e parada desde então não tem nada a gerir hoje, e o
pipeline inteiro produziria zero para ela.

QUEM ENTRA
    natureza = "Organização da Sociedade Civil". No SICONV, isso já exclui
    "Consórcio Público" e "Empresa pública/Sociedade de economia mista" — as
    conjunções de empresas ficam de fora por construção.
    Uma organização entra UMA vez: CNPJs de mesma raiz (filiais) são
    consolidados na de maior valor, senão "50 clientes" viram 48 organizações.

Uso:
    py -3 ferramentas/maiores.py                          # temas + seleção
    py -3 ferramentas/maiores.py --por-tema 10 --temas 5
    py -3 ferramentas/maiores.py --exportar data/carteira.json
    py -3 ferramentas/maiores.py --de data/carteira.json --semear --substituir
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(RAIZ / "ferramentas"))

CACHE = RAIZ / "data" / "detru" / "cache"
OSC = "Organização da Sociedade Civil"
# Saúde domina o universo (R$ 65,7 bi contra R$ 10,5 bi do 2º) e sozinha
# tomaria a carteira inteira — por isso entra com teto próprio.
TEMA_SAUDE = "MINISTERIO DA SAUDE"


def _num(s: str | None) -> float:
    try:
        return float((s or "0").replace(".", "").replace(",", "."))
    except ValueError:
        return 0.0


def _digitos(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _csv_do_zip(nome: str):
    caminho = CACHE / nome
    if not caminho.exists():
        sys.exit(f"falta {caminho} — rode a cadeia (ops/rodar_diario.py) para baixar o detru")
    z = zipfile.ZipFile(caminho)
    with z.open(z.namelist()[0]) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig"), delimiter=";")


def levantar() -> dict[str, dict]:
    """Um registro por CNPJ de OSC: tema dominante, valor e nº de ativos."""
    print("varrendo siconv_proposta.csv…", flush=True)
    de_proposta: dict[str, tuple[str, str]] = {}   # id_proposta -> (cnpj, tema)
    meta: dict[str, dict] = {}
    for r in _csv_do_zip("siconv_proposta.zip"):
        if (r.get("NATUREZA_JURIDICA") or "").strip() != OSC:
            continue
        doc = _digitos(r.get("IDENTIF_PROPONENTE"))
        if len(doc) != 14:
            continue
        de_proposta[r["ID_PROPOSTA"]] = (doc, (r.get("DESC_ORGAO_SUP") or "").strip())
        meta.setdefault(doc, {
            "doc": doc, "nome": (r.get("NM_PROPONENTE") or "").strip(),
            "natureza": OSC, "uf": (r.get("UF_PROPONENTE") or "").strip(),
            "municipio": (r.get("MUNIC_PROPONENTE") or "").strip(),
        })

    print("varrendo siconv_convenio.csv…", flush=True)
    por_tema: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    ativos: collections.Counter = collections.Counter()
    instrumentos: collections.Counter = collections.Counter()
    for r in _csv_do_zip("siconv_convenio.zip"):
        alvo = de_proposta.get(r.get("ID_PROPOSTA"))
        if not alvo:
            continue
        doc, tema = alvo
        por_tema[doc][tema] += _num(r.get("VL_REPASSE_CONV"))
        instrumentos[doc] += 1
        if (r.get("INSTRUMENTO_ATIVO") or "").upper() == "SIM":
            ativos[doc] += 1

    saida = {}
    for doc, temas in por_tema.items():
        tema, valor = temas.most_common(1)[0]
        saida[doc] = {**meta[doc], "tema": tema, "tamanho": sum(temas.values()),
                      "valor_no_tema": valor, "instrumentos": instrumentos[doc],
                      "ativos": ativos[doc]}
    return saida


def selecionar(universo: dict[str, dict], por_tema: int, n_temas: int) -> tuple[list[dict], list[tuple]]:
    vivos = [e for e in universo.values() if e["ativos"] > 0]

    ranking = collections.Counter()
    organizacoes: dict[str, set] = collections.defaultdict(set)
    for e in vivos:
        ranking[e["tema"]] += e["tamanho"]
        organizacoes[e["tema"]].add(e["doc"][:8])   # raiz: filial não conta como vaga

    # Um tema que não comporta a cota não é recorte temático — é exceção. A
    # Defesa, por exemplo, pesa R$ 5,1 bi mas tem 8 OSCs no país inteiro: entraria
    # incompleta e a carteira fecharia em 48. Quem não enche a cota cede a vaga.
    ordem = [t for t, _ in ranking.most_common() if len(organizacoes[t]) >= por_tema]
    magros = [(t, len(organizacoes[t])) for t, _ in ranking.most_common()
              if len(organizacoes[t]) < por_tema][:3]
    if magros:
        print("  temas fora por não comportarem a cota de "
              f"{por_tema}: " + ", ".join(f"{t[:34]} ({n})" for t, n in magros))
    temas = ([TEMA_SAUDE] if TEMA_SAUDE in ordem else []) + \
            [t for t in ordem if t != TEMA_SAUDE][:n_temas]

    carteira: list[dict] = []
    resumo = []
    for tema in temas:
        candidatos = sorted((e for e in vivos if e["tema"] == tema),
                            key=lambda e: -e["tamanho"])
        # uma organização por raiz de CNPJ (filial não ocupa vaga de outra)
        vistos, escolhidos = set(), []
        for e in candidatos:
            if e["doc"][:8] in vistos:
                continue
            vistos.add(e["doc"][:8])
            escolhidos.append(e)
            if len(escolhidos) == por_tema:
                break
        carteira += escolhidos
        resumo.append((tema, ranking[tema], len(candidatos), len(escolhidos)))
    return carteira, resumo


def semear(carteira: list[dict], substituir: bool) -> None:
    from app.db import conectar, migrar
    from onboarding import _valido

    maus = [e["doc"] for e in carteira if not _valido(e["doc"])]
    if maus:
        print(f"  ! {len(maus)} CNPJ(s) reprovados no dígito verificador, fora: {maus}")
        carteira = [e for e in carteira if _valido(e["doc"])]

    migrar()
    docs = [e["doc"] for e in carteira]
    with conectar() as con:
        for e in carteira:
            con.execute(
                "INSERT INTO clientes (doc, tipo_doc, nome, natureza, uf, municipio, observacao)"
                " VALUES (%s,'CNPJ',%s,%s,%s,%s,%s)"
                " ON CONFLICT (doc) DO UPDATE SET nome=EXCLUDED.nome,"
                " natureza=EXCLUDED.natureza, uf=EXCLUDED.uf, municipio=EXCLUDED.municipio,"
                " observacao=EXCLUDED.observacao, ativo=true",
                (e["doc"], e["nome"], e["natureza"], e["uf"], e["municipio"],
                 f"dogfood {e['tema'][:40]} · R$ {e['tamanho']:,.0f} · {e['ativos']} ativo(s)"))
        if substituir:
            # desativa, não apaga: clientes_pessoas e diario_cliente penduram nisto
            cur = con.execute("UPDATE clientes SET ativo=false WHERE ativo AND NOT (doc = ANY(%s))",
                              (docs,))
            print(f"  desativados (fora da seleção): {cur.rowcount}")
        con.commit()
    print(f"  semeados/atualizados: {len(carteira)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--por-tema", type=int, default=10)
    ap.add_argument("--temas", type=int, default=4, help="temas ALÉM da saúde")
    ap.add_argument("--semear", action="store_true")
    ap.add_argument("--substituir", action="store_true",
                    help="com --semear: desativa quem ficou fora")
    ap.add_argument("--exportar", metavar="ARQ")
    ap.add_argument("--de", metavar="ARQ", help="lê a carteira de um JSON já exportado")
    args = ap.parse_args()

    if args.de:
        carteira = json.loads(Path(args.de).read_text(encoding="utf-8"))
        print(f"carteira lida de {args.de}: {len(carteira)} organizações")
        if args.semear:
            semear(carteira, args.substituir)
        return

    universo = levantar()
    carteira, resumo = selecionar(universo, args.por_tema, args.temas)

    vivos = sum(1 for e in universo.values() if e["ativos"] > 0)
    print(f"\nOSCs no SICONV: {len(universo):,} | com instrumento ATIVO: {vivos:,}\n")
    print(f"{'TEMA':<58} {'R$ (vivos)':>16} {'cand.':>6} {'sel.':>5}")
    for tema, valor, cand, sel in resumo:
        print(f"{tema[:56]:<58} {valor:>16,.0f} {cand:>6} {sel:>5}")

    print()
    tema_atual = None
    for e in carteira:
        if e["tema"] != tema_atual:
            tema_atual = e["tema"]
            print(f"\n== {tema_atual}")
        print(f"   {e['doc']}  R$ {e['tamanho']:>14,.0f}  {e['instrumentos']:3d}i "
              f"({e['ativos']} ativo)  {e['uf']}  {e['nome'][:40]}")
    print(f"\ntotal selecionado: {len(carteira)} organizações")

    if args.exportar:
        Path(args.exportar).write_text(json.dumps(carteira, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        print(f"exportado: {args.exportar}")
    if args.semear:
        semear(carteira, args.substituir)


if __name__ == "__main__":
    main()
