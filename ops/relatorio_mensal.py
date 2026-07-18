"""Cadência do relatório — gera, arquiva e avisa, para toda a carteira.

Roda todo dia 1º (ou sob demanda com --forcar). Para cada cliente ativo:
gera o relatório do mês anterior, arquiva em data/relatorios/<AAAA-MM>/, grava
o registro em `relatorios_entregues` (idempotente por cliente+competência) e
avisa pelo notificador que a entrega está pronta para revisão.

Não envia nada ao cliente: quem manda é a pessoa, depois de ler.

Uso:
    py -3 ops/relatorio_mensal.py            # só age no dia 1º
    py -3 ops/relatorio_mensal.py --forcar   # gera agora, competência do mês anterior
    py -3 ops/relatorio_mensal.py --competencia 2026-06
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.db import conectar, migrar  # noqa: E402
from app.relatorio_cliente import markdown, montar  # noqa: E402


def competencia_anterior(hoje: date) -> str:
    ano, mes = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    return f"{ano:04d}-{mes:02d}"


def _dias_da_competencia(comp: str, hoje: date) -> int:
    """Janela que cobre a competência inteira a partir de hoje."""
    ano, mes = int(comp[:4]), int(comp[5:7])
    primeiro = date(ano, mes, 1)
    return max((hoje - primeiro).days + 1, 1)


def _avisar(texto: str) -> None:
    try:
        from app.notificador import despachar
        with conectar() as con:
            con.execute(
                "INSERT INTO eventos (cnpj, ente, dominio, chave, rotulo, tipo, de, para,"
                " snapshot, origem, detalhe)"
                " VALUES ('operacao','Operação','relatorio',%s,'Relatórios do mês prontos',"
                " 'mudanca',NULL,%s,CURRENT_DATE,'diff',%s)",
                (f"relatorio:{date.today().isoformat()}", texto[:400],
                 json.dumps({"fonte": "relatorio_mensal"}, ensure_ascii=False)))
            con.commit()
        despachar()
    except Exception as exc:  # noqa: BLE001 — aviso não derruba a geração
        print(f"  (aviso não enviado: {exc})")


def rodar(competencia: str | None, forcar: bool) -> int:
    hoje = date.today()
    if not forcar and not competencia and hoje.day != 1:
        print(f"hoje é dia {hoje.day} — a cadência é no dia 1º (use --forcar para gerar agora)")
        return 0

    comp = competencia or competencia_anterior(hoje)
    dias = _dias_da_competencia(comp, hoje)
    migrar()

    destino = RAIZ / "data" / "relatorios" / comp
    destino.mkdir(parents=True, exist_ok=True)

    with conectar() as con:
        clientes = con.execute(
            "SELECT doc, COALESCE(apelido, nome) FROM clientes WHERE ativo ORDER BY 2").fetchall()

    if not clientes:
        print("carteira vazia")
        return 0

    gerados, pulados, linhas = 0, 0, []
    for doc, nome in clientes:
        with conectar() as con:
            ja = con.execute(
                "SELECT 1 FROM relatorios_entregues WHERE doc_cliente=%s AND competencia=%s",
                (doc, comp)).fetchone()
        if ja and not forcar:
            pulados += 1
            continue

        dados = montar(doc, dias)
        texto = markdown(dados)
        arq = destino / f"{doc}.md"
        arq.write_text(texto, encoding="utf-8")

        resumo = {
            "precisa_do_cliente": len(dados["precisa_do_cliente"]),
            "sob_vigilancia": len(dados["sob_vigilancia"]),
            "mudancas": len(dados["mudancas"]),
            "atendimentos": len(dados["diario"]),
            "impedido": dados["regularidade"]["impedido"],
        }
        with conectar() as con:
            con.execute(
                "INSERT INTO relatorios_entregues (doc_cliente, competencia, dias, caminho, resumo)"
                " VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (doc_cliente, competencia) DO UPDATE SET gerado_em=now(),"
                " caminho=EXCLUDED.caminho, resumo=EXCLUDED.resumo, dias=EXCLUDED.dias",
                (doc, comp, dias, str(arq), json.dumps(resumo, ensure_ascii=False)))
            con.commit()

        gerados += 1
        linhas.append(f"{nome}: {resumo['precisa_do_cliente']} p/ o cliente, "
                      f"{resumo['sob_vigilancia']} sob vigilância")
        print(f"  {nome[:34]:34} -> {arq.name} "
              f"(precisa do cliente: {resumo['precisa_do_cliente']}, "
              f"vigilância: {resumo['sob_vigilancia']})")

    print(f"\ncompetência {comp}: {gerados} gerado(s), {pulados} já existia(m) -> {destino}")
    if gerados:
        _avisar(f"Competência {comp}: {gerados} relatório(s) prontos para revisão em {destino}. "
                + " · ".join(linhas[:6]))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--competencia", help="AAAA-MM (default: mês anterior)")
    ap.add_argument("--forcar", action="store_true", help="gera fora do dia 1º e regrava")
    args = ap.parse_args()
    sys.exit(rodar(args.competencia, args.forcar))


if __name__ == "__main__":
    main()
