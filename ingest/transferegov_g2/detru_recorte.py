"""Recorte do estoque SICONV (CSVs detru) por CNPJ — o legado 2008→hoje da carteira.

Complementa o recorte_ente.py: a g2 /parcerias só tem o ciclo novo (~2025+); o
histórico de convênios e contratos de repasse vive nos CSVs diários do detru
(espelho `/downloads` da g2). Este script filtra proposta+convênio pelos CNPJs
e escreve, por ente, `legado/{proposta,convenio}.csv` + `legado.md` com o que o
motor de prazos vai consumir (vigência, DIA_LIMITE_PREST_CONTAS, suspensiva).

Pré-requisito (cache local, baixado do espelho g2):
    data/detru/cache/siconv_proposta.zip   e   siconv_convenio.zip

Uso:
    python ingest/transferegov_g2/detru_recorte.py            # CNPJs do dogfood
    python ingest/transferegov_g2/detru_recorte.py --cnpj 07460294000183
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recorte_ente import monitorados  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))
from app.texto_br import qtd, verbo  # noqa: E402
CACHE = RAIZ / "data" / "detru" / "cache"
HISTORICO_ZIP = "siconv_historico_situacao.zip"


def _digitos(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _linhas_zip(nome_zip: str):
    with zipfile.ZipFile(CACHE / nome_zip) as z:
        interno = z.namelist()[0]
        with z.open(interno) as fh:
            texto = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            yield from csv.DictReader(texto, delimiter=";")


def _data_br(s: str):
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


def _datahora_br(s: str):
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def recortar(cnpjs: set[str], base_out: Path) -> dict[str, dict]:
    # nomes vêm da carteira; sem banco, o rótulo é o próprio CNPJ (não engana)
    try:
        rotulos = monitorados()
    except SystemExit:
        rotulos = {}
    props: dict[str, dict] = {}   # ID_PROPOSTA -> {cnpj, row}
    print("varredura de siconv_proposta.csv…", flush=True)
    for row in _linhas_zip("siconv_proposta.zip"):
        cnpj = _digitos(row.get("IDENTIF_PROPONENTE"))
        if cnpj in cnpjs:
            props[row["ID_PROPOSTA"]] = {"cnpj": cnpj, "row": row}

    convs: dict[str, list[dict]] = {c: [] for c in cnpjs}
    print("varredura de siconv_convenio.csv…", flush=True)
    for row in _linhas_zip("siconv_convenio.zip"):
        p = props.get(row.get("ID_PROPOSTA"))
        if p:
            convs[p["cnpj"]].append(row)

    # Última situação registrada de cada instrumento. É daqui que sai HÁ QUANTO
    # TEMPO a prestação está parada na análise do CONCEDENTE — o convenio.csv
    # diz a situação atual, mas não desde quando. Sem isso não dá para saber que
    # o prazo do art. 97 (60d informatizado / 180d convencional) estourou.
    dono = {r.get("NR_CONVENIO"): c for c, linhas in convs.items() for r in linhas}
    ultima_sit: dict[str, dict] = {}
    if (CACHE / HISTORICO_ZIP).exists():
        print("varredura de siconv_historico_situacao.csv…", flush=True)
        for row in _linhas_zip(HISTORICO_ZIP):
            nr = row.get("NR_CONVENIO")
            if nr not in dono:
                continue
            quando = _datahora_br(row.get("DIA_HISTORICO_SIT"))
            atual = ultima_sit.get(nr)
            if quando and (atual is None or quando > atual["_quando"]):
                ultima_sit[nr] = {
                    "NR_CONVENIO": nr, "DIA_HISTORICO_SIT": row.get("DIA_HISTORICO_SIT"),
                    "HISTORICO_SIT": row.get("HISTORICO_SIT"),
                    "DIAS_HISTORICO_SIT": row.get("DIAS_HISTORICO_SIT"), "_quando": quando,
                }
    else:
        print(f"  [sem {HISTORICO_ZIP} — sem histórico de situação nesta rodada]", flush=True)

    resultados = {}
    for cnpj in cnpjs:
        minhas_props = [p["row"] for p in props.values() if p["cnpj"] == cnpj]
        meus_convs = convs[cnpj]
        historico = [{k: v for k, v in h.items() if not k.startswith("_")}
                     for nr, h in ultima_sit.items() if dono.get(nr) == cnpj]
        destino = base_out / cnpj / "legado"
        destino.mkdir(parents=True, exist_ok=True)
        for nome, linhas in (("proposta", minhas_props), ("convenio", meus_convs),
                             ("historico_situacao", historico)):
            if linhas:
                with open(destino / f"{nome}.csv", "w", newline="", encoding="utf-8-sig") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(linhas[0].keys()), delimiter=";")
                    w.writeheader()
                    w.writerows(linhas)

        modalidade_por_prop = {p["ID_PROPOSTA"]: p.get("MODALIDADE") for p in minhas_props}
        hoje = date.today()
        ativos, repasse_ativos, prest_vencendo = [], [], []
        sit = Counter()
        for c in meus_convs:
            mod = modalidade_por_prop.get(c.get("ID_PROPOSTA"), "?")
            sit[f"{mod} · {c.get('SIT_CONVENIO')}"] += 1
            if (c.get("INSTRUMENTO_ATIVO") or "").upper() == "SIM":
                ativos.append(c)
                if "REPASSE" in (mod or "").upper():
                    repasse_ativos.append(c)
            lim = _data_br(c.get("DIA_LIMITE_PREST_CONTAS") or "")
            if lim and (c.get("INSTRUMENTO_ATIVO") or "").upper() == "SIM":
                prest_vencendo.append((lim, c.get("NR_CONVENIO"), mod, c.get("SIT_CONVENIO")))
        prest_vencendo.sort()

        md = [
            f"# Legado SICONV — {rotulos.get(cnpj, cnpj)}",
            "",
            f"CNPJ `{cnpj}` · fonte: CSVs detru de {date.today().isoformat()} (carga diária ~09h)",
            "",
            f"- Propostas históricas: **{len(minhas_props)}** · instrumentos celebrados: **{len(meus_convs)}**"
            f" · **ativos: {len(ativos)}**",
            f"- 🏗️ Contratos de repasse (obra, mandatária) ATIVOS: **{len(repasse_ativos)}**"
            + (" — " + ", ".join(f"`{c.get('NR_CONVENIO')}` ({c.get('SIT_CONVENIO')}, vig. até {c.get('DIA_FIM_VIGENC_CONV')})"
                                 for c in repasse_ativos[:6]) if repasse_ativos else ""),
            "- Por modalidade × situação: " + (", ".join(f"{k}: {v}" for k, v in sit.most_common(10)) or "—"),
        ]
        if prest_vencendo:
            md.append("- ⏰ Limites de prestação de contas (instrumentos ativos):")
            for lim, nr, mod, s in prest_vencendo[:8]:
                marca = "🔴 VENCIDO" if lim < hoje else ("🟡" if (lim - hoje).days <= 90 else "🟢")
                md.append(f"  - {marca} `{nr}` ({mod}, {s}): limite **{lim.strftime('%d/%m/%Y')}**")
        md.append("")
        (base_out / cnpj / "legado.md").write_text("\n".join(md), encoding="utf-8")
        resultados[cnpj] = {
            "propostas": len(minhas_props), "instrumentos": len(meus_convs), "ativos": len(ativos),
            "contratos_repasse_ativos": len(repasse_ativos),
            "prest_contas_vencidas": sum(1 for l, *_ in prest_vencendo if l < hoje),
        }
        # razão social CRUA aqui de propósito: esta linha relata o que a
        # plataforma entregou, e é o rastro de auditoria contra o que a tela
        # mostra depois de `razao_social.exibir`. Corrigir os dois lados
        # apagaria a comparação que justifica corrigir só a exibição.
        rep, venc = len(repasse_ativos), resultados[cnpj]["prest_contas_vencidas"]
        print(f"  {rotulos.get(cnpj, cnpj)}: {len(meus_convs)} instrumentos "
              f"({len(ativos)} {verbo(len(ativos), 'ativo', 'ativos')}, "
              f"{qtd(rep, 'contrato de repasse ativo', 'contratos de repasse ativos')}, "
              f"{qtd(venc, 'prestação vencida', 'prestações vencidas')})", flush=True)
    return resultados


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cnpj", action="append", default=[], help="repetível; default = dogfood")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cnpjs = {_digitos(x) for x in (args.cnpj or monitorados())}
    base_out = Path(args.out) if args.out else RAIZ / "data" / "recortes" / date.today().isoformat()
    resultados = recortar(cnpjs, base_out)
    (base_out / "_legado_resumo.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
