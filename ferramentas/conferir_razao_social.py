"""Conferência da razão social: o que a plataforma mandou x o que a tela mostra.

Esta ferramenta é a razão de a correção ser só de exibição (decisão do dono,
30/07/2026). Como `clientes.nome` continua byte a byte igual ao que o
Transferegov entregou, as duas colunas podem ser postas lado a lado a qualquer
momento — e é isto que faz isso aqui.

Serve a três perguntas:

1. **O que mudou na tela?** Coluna ORIGEM contra coluna EXIBIDO, nome por nome.
2. **O que ainda está errado?** Palavra sem entrada no léxico sai com a caixa
   corrigida e SEM acento. `--pendentes` lista essas palavras, as suspeitas
   primeiro, para o léxico crescer por decisão e não por adivinhação.
3. **Onde a correção passou por cima de mais do que devia?** `--siglas` mostra as
   palavras que ficaram em CAIXA ALTA por estarem na lista de siglas. Se alguma
   não for sigla, está errada, e é a lista mais curta para conferir.

Uso:
    py -3 ferramentas/conferir_razao_social.py              # a tabela inteira
    py -3 ferramentas/conferir_razao_social.py --mudaram    # só o que mudou
    py -3 ferramentas/conferir_razao_social.py --pendentes  # a lista de trabalho
    py -3 ferramentas/conferir_razao_social.py --siglas     # o que ficou em caixa alta
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.db import conectar  # noqa: E402
from app.razao_social import SIGLAS, exibir, pendencias  # noqa: E402
from app.texto_br import qtd, verbo  # noqa: E402


def _nomes() -> list[tuple[str, str]]:
    with conectar() as con:
        return [(d, n) for d, n in con.execute(
            "SELECT doc, nome FROM clientes WHERE tipo_doc='CNPJ' AND nome IS NOT NULL"
            " ORDER BY nome")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mudaram", action="store_true", help="só as linhas em que a tela difere da origem")
    ap.add_argument("--pendentes", action="store_true", help="palavras sem entrada no léxico")
    ap.add_argument("--siglas", action="store_true", help="palavras mantidas em caixa alta")
    args = ap.parse_args()

    nomes = _nomes()
    if not nomes:
        print("nenhuma razão social de PJ na carteira")
        return 0

    if args.pendentes:
        conta: dict[str, dict] = {}
        for _, bruto in nomes:
            for p in pendencias(bruto):
                alvo = conta.setdefault(p["palavra"], {"n": 0, "suspeita": p["suspeita"]})
                alvo["n"] += 1
        if not conta:
            print("nenhuma palavra fora do léxico — a carteira está 100% coberta")
            return 0
        # suspeitas primeiro, e dentro delas as mais frequentes: é a ordem em que
        # uma entrada nova rende mais nome corrigido
        ordem = sorted(conta.items(), key=lambda kv: (not kv[1]["suspeita"], -kv[1]["n"], kv[0]))
        suspeitas = sum(1 for _, v in conta.items() if v["suspeita"])
        print(f"{qtd(len(conta), 'palavra', 'palavras')} fora do léxico · "
              f"{suspeitas} com cara de acento faltando\n")
        for palavra, v in ordem:
            print(f"  {'⚠' if v['suspeita'] else ' '} {palavra:<24} "
                  f"em {qtd(v['n'], 'nome', 'nomes')}")
        print("\nA marca ⚠ é heurística de sufixo/cedilha, não veredito: quem decide é você.")
        print("Para corrigir, acrescente em LEXICO de backend/app/razao_social.py.")
        return 0

    if args.siglas:
        usadas = collections.Counter(
            w.upper() for _, bruto in nomes for w in re.findall(r"[A-Za-z]+", bruto)
            if w.upper() in SIGLAS)
        print(f"{qtd(len(usadas), 'sigla', 'siglas')} da lista "
              f"{verbo(len(usadas), 'aparece', 'aparecem')} na carteira:\n")
        for s, n in usadas.most_common():
            print(f"  {s:<12} em {qtd(n, 'nome', 'nomes')}")
            print(f"  {'':12} -> exibido como {s}")
        print("\nSe alguma NÃO é sigla, ela está sendo mostrada em caixa alta por engano:")
        print("remova de SIGLAS em backend/app/razao_social.py.")
        return 0

    mudaram = 0
    for doc, bruto in nomes:
        saida = exibir(bruto)
        diferente = saida != bruto
        mudaram += diferente
        if args.mudaram and not diferente:
            continue
        falta = [p["palavra"] for p in pendencias(bruto) if p["suspeita"]]
        print(f"{doc}")
        print(f"  origem   {bruto}")
        print(f"  exibido  {saida}{'' if diferente else '   (sem mudança)'}")
        if falta:
            print(f"  ⚠ ainda sem acento: {', '.join(falta)}")
        print()
    print(f"{qtd(len(nomes), 'razão social', 'razões sociais')} · "
          f"{mudaram} {verbo(mudaram, 'difere', 'diferem')} na tela · "
          f"o gravado não foi tocado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
