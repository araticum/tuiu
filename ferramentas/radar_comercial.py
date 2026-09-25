"""Radar comercial interno — leads por dor + dinheiro em trânsito no Transferegov.

Uso interno da Araticum (não é superfície de produto; ver plano §5). Cruza o dump
diário da g2 /parcerias (proposta, beneficiario-emenda-parlamentar) com os planos de
ação de transferências especiais (g2 /especiais, baixados aqui com cache) e ranqueia
entes por sinais acionáveis, cada lead com o "motivo da abordagem" pronto.

Sinais e pesos (v1):
  +3  plano de ação Pix IMPEDIDO / rejeição de plano de trabalho (motivo vira abordagem)
  +2  emenda parlamentar indicada ao CNPJ (dinheiro a caminho, antes de cair)
  +2  proposta em sofrimento na g2 (situação contendo "Complementa" ou "Rejeitada")
  v2 (aguarda ingest próprio): CAUC pendente, prestação de contas vencendo no estoque detru,
     relatório de gestão Pix ausente.

Saída: data/radar/<AAAA-MM-DD>/radar.csv e radar.md (top N).

Exemplos:
  python ferramentas/radar_comercial.py                       # nacional, top 50
  python ferramentas/radar_comercial.py --uf GO --uf AP --top 20
  python ferramentas/radar_comercial.py --sem-especiais       # só dump local, sem rede
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
G2_ESPECIAIS_BASE = "https://api-publica.transferegov.gestao.gov.br/especiais"
PAGINA_MAX = 200
UA = {"Accept": "application/json", "User-Agent": "araticum-tuiu-radar/0.1"}

PESO_PIX_IMPEDIDO = 3
PESO_EMENDA_INDICADA = 2
PESO_PROPOSTA_SOFRENDO = 2

DOGFOOD = {
    "01616520000196": "dogfood (Águas Lindas/GO pref.)",
    "07460294000183": "dogfood (Águas Lindas/GO FMS)",
    "34925198000136": "dogfood (Cutias/AP pref.)",
    "12008067000151": "dogfood (Cutias/AP FMS)",
    "15030230000170": "dogfood (Cutias/AP FMAS)",
    "20069629000103": "dogfood (Ecos da Natureza/SP)",
}


def _digitos(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _campo(row: dict, *pedacos_alternativos: tuple[str, ...]):
    """Acha o valor pelo nome de campo cujas partes todas apareçam na chave.

    A g1 sufixava campos com _plano_acao e a g2 renomeia sem aviso; casar por
    pedaços torna o radar imune a esse drift. Entre as chaves que casam, vence a
    MAIS CURTA (mais específica: `situacao_plano_acao` antes de
    `codigo_situacao_dado_bancario_plano_acao`), pulando valores vazios.
    """
    for pedacos in pedacos_alternativos:
        chaves = sorted((k for k in row if all(p in k.lower() for p in pedacos)), key=len)
        for k in chaves:
            v = row[k]
            if v is not None and v != "":
                return v
    return None


def _brl(v: float) -> str:
    return f"R$ {v:,.0f}".replace(",", ".")


def _fetch_json(url: str, tentativas: int = 4):
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if i == tentativas - 1:
                raise
            import time

            time.sleep(2 * (i + 1))


def _carregar_rota_g2(rota: str, cache_dir: Path) -> list[dict]:
    hoje = dt.date.today().isoformat()
    cache = cache_dir / f"{rota}-{hoje}.jsonl.gz"
    if cache.exists():
        with gzip.open(cache, "rt", encoding="utf-8") as fh:
            return [json.loads(l) for l in fh]

    base = f"{G2_ESPECIAIS_BASE}/{rota}"
    primeira = _fetch_json(f"{base}?pagina=1&tamanho_da_pagina={PAGINA_MAX}")
    linhas = list(primeira["data"])
    total = int(primeira.get("total_pages") or 1)

    def pega(p):
        return _fetch_json(f"{base}?pagina={p}&tamanho_da_pagina={PAGINA_MAX}")["data"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        for bloco in pool.map(pega, range(2, total + 1)):
            linhas.extend(bloco)

    cache_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache, "wt", encoding="utf-8") as fh:
        for l in linhas:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    return linhas


def dump_parcerias_mais_recente(base: Path) -> Path:
    dirs = sorted((base / "data" / "parcerias").glob("*"), reverse=True)
    for d in dirs:
        if (d / "proposta.jsonl.gz").exists():
            return d
    sys.exit("nenhum dump de parcerias em data/parcerias/ (rode o extrator g2 antes)")


def _linhas_gz(caminho: Path):
    with gzip.open(caminho, "rt", encoding="utf-8") as fh:
        for l in fh:
            yield json.loads(l)


def montar(dump: Path, planos: list[dict], beneficiarios: dict, ufs: set[str]) -> dict[str, dict]:
    entes: dict[str, dict] = {}

    def ente(cnpj: str) -> dict:
        return entes.setdefault(
            cnpj,
            {
                "cnpj": cnpj, "nome": None, "uf": None, "municipio": None, "ibge": None,
                "natureza": None, "score": 0,
                "pix_total": 0, "pix_impedidos": [], "pix_valor": 0.0,
                "emendas_qtd": 0, "emendas_valor": 0.0, "emendas_parlamentares": set(),
                "prop_total": 0, "prop_sofrendo": Counter(),
            },
        )

    for p in _linhas_gz(dump / "proposta.jsonl.gz"):
        cnpj = _digitos(p.get("cnpj_ente_recebedor"))
        if not cnpj:
            continue
        e = ente(cnpj)
        e["nome"] = e["nome"] or p.get("nm_ente_recebedor")
        e["uf"] = e["uf"] or p.get("sg_uf_recebedor")
        e["municipio"] = e["municipio"] or p.get("nm_municipio_recebedor")
        e["ibge"] = e["ibge"] or p.get("cd_ibge_recebedor")
        e["natureza"] = e["natureza"] or p.get("nm_natureza_juridica")
        e["prop_total"] += 1
        sit = str(p.get("situacao_proposta") or "")
        if "Complementa" in sit or "Rejeitada" in sit:
            e["prop_sofrendo"][sit] += 1

    arq_emendas = dump / "beneficiario-emenda-parlamentar.jsonl.gz"
    if arq_emendas.exists():
        for b in _linhas_gz(arq_emendas):
            cnpj = _digitos(_campo(b, ("cnpj",)))
            if not cnpj:
                continue
            e = ente(cnpj)
            e["nome"] = e["nome"] or _campo(b, ("nm", "benef"), ("nome", "benef"))
            e["uf"] = e["uf"] or _campo(b, ("uf", "benef"))
            e["municipio"] = e["municipio"] or _campo(b, ("municipio", "benef"))
            e["natureza"] = e["natureza"] or _campo(b, ("natureza", "benef"))
            e["emendas_qtd"] += 1
            e["emendas_valor"] += float(_campo(b, ("vl", "total"), ("valor", "total")) or 0)
            parl = _campo(b, ("nm", "parlamentar"), ("nome", "parlamentar"))
            if parl:
                e["emendas_parlamentares"].add(str(parl))

    for pl in planos:
        # a rota g2 de planos não carrega CNPJ — o vínculo é id_beneficiario
        ben = beneficiarios.get(_campo(pl, ("id", "beneficiario")))
        cnpj = _digitos(_campo(pl, ("cnpj", "benef")) or (ben or {}).get("cnpj"))
        if not cnpj:
            continue
        e = ente(cnpj)
        e["nome"] = e["nome"] or _campo(pl, ("nome", "benef")) or (ben or {}).get("nome")
        e["uf"] = e["uf"] or _campo(pl, ("uf", "benef")) or (ben or {}).get("uf")
        e["pix_total"] += 1
        e["pix_valor"] += float(_campo(pl, ("valor", "custeio")) or 0) + float(
            _campo(pl, ("valor", "investimento")) or 0
        )
        sit = str(_campo(pl, ("situacao",)) or "")
        if "IMPEDIDO" in sit.upper():
            e["pix_impedidos"].append(
                {
                    "codigo": _campo(pl, ("codigo", "plano")),
                    "ano": _campo(pl, ("ano_plano",), ("ano_emenda",)),
                    "situacao": sit,
                    "motivo": _campo(pl, ("motivo",)),
                }
            )

    for e in entes.values():
        e["score"] = (
            PESO_PIX_IMPEDIDO * len(e["pix_impedidos"])
            + (PESO_EMENDA_INDICADA if e["emendas_qtd"] else 0)
            + (PESO_PROPOSTA_SOFRENDO if e["prop_sofrendo"] else 0)
        )

    if ufs:
        entes = {c: e for c, e in entes.items() if (e["uf"] or "").upper() in ufs}
    return {c: e for c, e in entes.items() if e["score"] > 0}


def _e_estadual(e: dict) -> bool:
    nome = (e["nome"] or "").upper()
    return "Estadual" in (e["natureza"] or "") or nome.startswith(
        ("ESTADO ", "GOVERNO DO", "FUNDO ESTADUAL", "DISTRITO FEDERAL", "FUNDO DE SAUDE DO DISTRITO")
    )


def motivo_abordagem(e: dict) -> str:
    if e["pix_impedidos"]:
        pior = e["pix_impedidos"][0]
        txt = " ".join(str(pior.get("motivo") or "").split())
        if len(txt) > 180:
            txt = txt[:180] + "…"
        motivo = f" — motivo: {txt}" if txt else ""
        extra = f" (+{len(e['pix_impedidos']) - 1} outros impedidos)" if len(e["pix_impedidos"]) > 1 else ""
        return f"Plano de ação Pix {pior.get('codigo')} ({pior.get('ano')}) IMPEDIDO{motivo}{extra}"
    if e["emendas_qtd"]:
        quem = sorted(e["emendas_parlamentares"])
        parl = f" ({quem[0]}{' e outros' if len(quem) > 1 else ''})" if quem else ""
        return f"{e['emendas_qtd']} indicação(ões) de emenda{parl}: {_brl(e['emendas_valor'])} a caminho"
    sit, qtd = e["prop_sofrendo"].most_common(1)[0]
    return f"{qtd} proposta(s) '{sit}' paradas no Transferegov"


def escrever(entes: dict[str, dict], destino: Path, top: int, fonte_dump: Path, com_especiais: bool):
    destino.mkdir(parents=True, exist_ok=True)
    ordenados = sorted(
        entes.values(),
        key=lambda e: (e["score"], len(e["pix_impedidos"]), e["emendas_valor"], e["pix_valor"]),
        reverse=True,
    )

    with open(destino / "radar.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(
            ["score", "nome", "cnpj", "uf", "municipio", "ibge", "natureza", "pix_planos", "pix_impedidos",
             "pix_valor", "emendas_qtd", "emendas_valor", "parlamentares", "propostas", "propostas_sofrendo",
             "motivo_abordagem", "obs"]
        )
        for e in ordenados:
            w.writerow(
                [e["score"], e["nome"], e["cnpj"], e["uf"], e["municipio"], e["ibge"], e["natureza"],
                 e["pix_total"], len(e["pix_impedidos"]), f"{e['pix_valor']:.2f}", e["emendas_qtd"],
                 f"{e['emendas_valor']:.2f}", " | ".join(sorted(e["emendas_parlamentares"])), e["prop_total"],
                 sum(e["prop_sofrendo"].values()), motivo_abordagem(e), DOGFOOD.get(e["cnpj"], "")]
            )

    md = [
        f"# Radar comercial — {dt.date.today().isoformat()}",
        "",
        f"Fontes: dump parcerias `{fonte_dump.name}`"
        + (", planos de ação especiais g2 (ao vivo, cache do dia)" if com_especiais else " (SEM especiais — rodada offline)")
        + f". Entes com sinal: **{len(ordenados)}**. Pesos: impedido×{PESO_PIX_IMPEDIDO}, emenda {PESO_EMENDA_INDICADA}, proposta {PESO_PROPOSTA_SOFRENDO}.",
        "",
        "| # | Ente | UF | Score | Sinais | Motivo da abordagem |",
        "|---|---|---|---|---|---|",
    ]
    for i, e in enumerate(ordenados[:top], 1):
        sinais = []
        if e["pix_impedidos"]:
            sinais.append(f"{len(e['pix_impedidos'])} Pix impedido(s)")
        if e["emendas_qtd"]:
            sinais.append(f"{e['emendas_qtd']} emenda(s) {_brl(e['emendas_valor'])}")
        if e["prop_sofrendo"]:
            sinais.append(f"{sum(e['prop_sofrendo'].values())} proposta(s) travada(s)")
        marca = f" `{DOGFOOD[e['cnpj']]}`" if e["cnpj"] in DOGFOOD else ""
        nome = f"{e['nome']}{marca}"
        md.append(f"| {i} | {nome} ({e['municipio'] or '—'}) | {e['uf'] or '—'} | {e['score']} | "
                  f"{'; '.join(sinais)} | {motivo_abordagem(e)} |")
    (destino / "radar.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return ordenados


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uf", action="append", default=[], help="filtra por UF (repetível)")
    ap.add_argument("--top", type=int, default=50, help="linhas no radar.md (CSV sai completo)")
    ap.add_argument("--parcerias", type=Path, default=None, help="dir do dump (default: mais recente)")
    ap.add_argument("--sem-especiais", action="store_true", help="não consulta a g2 /especiais (offline)")
    ap.add_argument("--so-municipios", action="store_true", help="descarta entes estaduais/DF (foco no ICP)")
    args = ap.parse_args()

    dump = args.parcerias or dump_parcerias_mais_recente(RAIZ)
    cache = RAIZ / "data" / "radar" / "cache"
    planos, beneficiarios = [], {}
    if not args.sem_especiais:
        # rotas com hífen desde ~28/08/2026 (a API /especiais trocou `_` por `-`)
        planos = _carregar_rota_g2("planos-acao-especiais", cache)
        for b in _carregar_rota_g2("beneficiarios-especiais", cache):
            bid = _campo(b, ("id", "beneficiario"))
            if bid is not None:
                beneficiarios[bid] = {
                    "cnpj": _digitos(_campo(b, ("cnpj",))),
                    "nome": _campo(b, ("nome",), ("nm",)),
                    "uf": _campo(b, ("uf",)),
                }
    entes = montar(dump, planos, beneficiarios, {u.upper() for u in args.uf})
    if args.so_municipios:
        entes = {c: e for c, e in entes.items() if not _e_estadual(e)}
    destino = RAIZ / "data" / "radar" / dt.date.today().isoformat()
    ordenados = escrever(entes, destino, args.top, dump, not args.sem_especiais)

    print(f"entes com sinal: {len(ordenados)}  ->  {destino / 'radar.md'}")
    for e in ordenados[:10]:
        print(f"  [{e['score']:>2}] {e['nome']} ({e['uf']}) — {motivo_abordagem(e)}")


if __name__ == "__main__":
    main()
