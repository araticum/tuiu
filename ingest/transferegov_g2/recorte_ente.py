"""Recorte por ente (F0) — carteira completa de um CNPJ na g2 do Transferegov.

Encadeia o grafo do módulo Gestão de Parcerias a partir do ente recebedor
(proposta → filhas → parceria → conta/NE/DH → OP/extrato), puxa as indicações de
emenda ao CNPJ e os planos de ação de Transferências Especiais (Pix, módulo
/especiais — a rota de planos não tem CNPJ, o vínculo é beneficiário → id).

Saída por ente em data/recortes/<data-api>/<cnpj>/:
    parcerias/<rota>.jsonl.gz   dados brutos do recorte
    especiais/planos_acao.jsonl.gz
    carteira.json               agregado estruturado (insumo do app)
    carteira.md                 resumo humano — a 1ª Carteira do Tuiú

Uso:
    python ingest/transferegov_g2/recorte_ente.py               # 4 CNPJs do dogfood
    python ingest/transferegov_g2/recorte_ente.py --cnpj 01616520000196
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g2_parcerias import BASE, _get_json, _url_rota, data_atualizacao  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
ESPECIAIS = BASE.rsplit("/", 1)[0] + "/especiais"

DOGFOOD = {
    "01616520000196": "Águas Lindas de Goiás/GO — prefeitura",
    "07460294000183": "Águas Lindas de Goiás/GO — FMS",
    "34925198000136": "Cutias/AP — prefeitura",
    "12008067000151": "Cutias/AP — FMS (Cutias do Araguari)",
    "15030230000170": "Cutias/AP — FMAS",
    "20069629000103": "Ecos da Natureza/SP — OSC",
}

FILHAS_PROPOSTA = [
    "meta-proposta",
    "cronograma-desembolso",
    "analise-proposta",
    "proposta-resultado-indicador",
    "distribuicao-recurso-proposta",
    "parceria",
]
FILHAS_PARCERIA = ["parceria-conta", "empenho-parceria", "documento-habil"]


def _todas_paginas(url_base: str, rota: str, filtros: dict) -> list[dict]:
    primeira = _get_json(_url_rota(rota, 1, filtros).replace(BASE, url_base))
    linhas = list(primeira["data"])
    for p in range(2, int(primeira.get("total_pages") or 1) + 1):
        linhas.extend(_get_json(_url_rota(rota, p, filtros).replace(BASE, url_base))["data"])
    return linhas


def _por_ids(rota: str, campo: str, ids: list, workers: int) -> list[dict]:
    """Uma consulta filtrada por id-pai; a API não tem operador IN."""
    def um(i):
        return _todas_paginas(BASE, rota, {campo: str(i)})

    linhas: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for bloco in pool.map(um, ids):
            linhas.extend(bloco)
    return linhas


def _brl(v) -> str:
    return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _grava(dir_: Path, nome: str, linhas: list[dict]):
    dir_.mkdir(parents=True, exist_ok=True)
    with gzip.open(dir_ / f"{nome}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for l in linhas:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")


def recortar(cnpj: str, destino: Path, workers: int) -> dict:
    print(f"== {cnpj} ({DOGFOOD.get(cnpj, 'ente')})", flush=True)
    r: dict[str, list] = {}

    r["proposta"] = _todas_paginas(BASE, "proposta", {"cnpj_ente_recebedor": cnpj})
    ids_proposta = [p["id_proposta"] for p in r["proposta"]]
    for rota in FILHAS_PROPOSTA:
        r[rota] = _por_ids(rota, "id_proposta", ids_proposta, workers)

    ids_parceria = [p["id_parceria"] for p in r.get("parceria", [])]
    for rota in FILHAS_PARCERIA:
        r[rota] = _por_ids(rota, "id_parceria", ids_parceria, workers)

    r["ordem-pagamento"] = _por_ids(
        "ordem-pagamento", "id_documento_habil",
        [d["id_documento_habil"] for d in r.get("documento-habil", [])], workers)
    r["extrato-bancario"] = _por_ids(
        "extrato-bancario", "id_parceria_conta",
        [c["id_parceria_conta"] for c in r.get("parceria-conta", [])], workers)
    r["beneficiario_emenda_parlamentar"] = _todas_paginas(
        BASE, "beneficiario_emenda_parlamentar", {"nr_cnpj_beneficiario_emenda": cnpj})

    # Especiais: acha o(s) beneficiário(s) pelo CNPJ e traz os planos por id.
    beneficiarios = _todas_paginas(ESPECIAIS, "beneficiarios_especiais", {"cnpj_beneficiario": cnpj})
    if not beneficiarios:  # nome do parâmetro pode divergir; tenta a chave real da 1ª página
        amostra = _get_json(f"{ESPECIAIS}/beneficiarios_especiais?pagina=1&tamanho_da_pagina=1")["data"]
        chave = next((k for k in (amostra[0] if amostra else {}) if "cnpj" in k.lower()), None)
        if chave:
            beneficiarios = _todas_paginas(ESPECIAIS, "beneficiarios_especiais", {chave: cnpj})
    planos = []
    for b in beneficiarios:
        bid = next((v for k, v in b.items() if k.lower().startswith("id") and "benef" in k.lower()), None)
        if bid is not None:
            planos.extend(_todas_paginas(ESPECIAIS, "planos_acao_especiais", {"id_beneficiario": str(bid)}))

    pdir = destino / "parcerias"
    for rota, linhas in r.items():
        _grava(pdir, rota.replace("_", "-"), linhas)
    _grava(destino / "especiais", "beneficiarios", beneficiarios)
    _grava(destino / "especiais", "planos_acao", planos)
    return {"parcerias": r, "planos": planos, "beneficiarios": beneficiarios}


def carteira(cnpj: str, dados: dict, dt_api: str) -> tuple[dict, str]:
    r, planos = dados["parcerias"], dados["planos"]
    props = r["proposta"]
    emendas_rows = r.get("beneficiario_emenda_parlamentar", [])
    nome = (next((p.get("nm_ente_recebedor") for p in props), None)
            or next((b.get("nm_beneficiario_emenda") for b in emendas_rows), None)
            or next((str(v) for b in dados["beneficiarios"] for k, v in b.items()
                     if "nome" in k.lower() and v), None)
            or DOGFOOD.get(cnpj, cnpj))
    uf = (next((p.get("sg_uf_recebedor") for p in props), None)
          or next((b.get("sg_uf_beneficiario_emenda") for b in emendas_rows), None)
          or next((str(v) for b in dados["beneficiarios"] for k, v in b.items()
                   if "uf" in k.lower() and v), None))
    mun = (next((p.get("nm_municipio_recebedor") for p in props), None)
           or next((b.get("nm_municipio_beneficiario_emenda") for b in emendas_rows), None))

    sit_prop = Counter(p.get("situacao_proposta") for p in props)
    sit_parc = Counter(p.get("in_situacao_parceria") for p in r.get("parceria", []))
    contas = r.get("parceria-conta", [])
    saldo_cc = sum(float(c.get("vl_saldo_conta_corrente") or 0) for c in contas)
    saldo_inv = sum(float(c.get("vl_saldo_conta_investimento") or 0) for c in contas)
    emendas = r.get("beneficiario_emenda_parlamentar", [])
    vl_emendas = sum(float(b.get("vl_total_emenda") or 0) for b in emendas)
    parlamentares = sorted({b.get("nm_parlamentar") for b in emendas if b.get("nm_parlamentar")})

    sit_pix = Counter(str(p.get("situacao_plano_acao")) for p in planos)
    impedidos = [p for p in planos if "IMPEDIDO" in str(p.get("situacao_plano_acao", "")).upper()]
    vl_pix = sum(
        float(p.get("valor_custeio_plano_acao") or 0) + float(p.get("valor_investimento_plano_acao") or 0)
        for p in planos
    )

    cj = {
        "cnpj": cnpj, "nome": nome, "uf": uf, "municipio": mun, "data_atualizacao_api": dt_api,
        "parcerias": {
            "propostas": len(props), "por_situacao": dict(sit_prop),
            "instrumentos": len(r.get("parceria", [])), "instrumentos_por_situacao": dict(sit_parc),
            "contas": len(contas), "saldo_conta_corrente": saldo_cc, "saldo_investimento": saldo_inv,
            "empenhos": len(r.get("empenho-parceria", [])),
            "documentos_habeis": len(r.get("documento-habil", [])),
            "ordens_pagamento": len(r.get("ordem-pagamento", [])),
            "lancamentos_extrato": len(r.get("extrato-bancario", [])),
        },
        "emendas_indicadas": {"qtd": len(emendas), "valor_total": vl_emendas, "parlamentares": parlamentares},
        "especiais": {
            "planos": len(planos), "por_situacao": dict(sit_pix), "valor_total": vl_pix,
            "impedidos": [
                {
                    "codigo": p.get("codigo_plano_acao"), "ano": p.get("ano_plano_acao"),
                    "situacao": p.get("situacao_plano_acao"),
                    "motivo": " ".join(str(p.get("motivo_impedimento_plano_acao") or "").split()) or None,
                }
                for p in impedidos
            ],
        },
    }

    linhas = [
        f"# Carteira — {nome}",
        "",
        f"CNPJ `{cnpj}` · {mun or '—'}/{uf or '—'} · dados da API de {dt_api[:10]} (D-1)",
        "",
        "## Parcerias (Discricionárias e Legais — ciclo novo g2)",
        f"- Propostas: **{len(props)}** — " + ", ".join(f"{k}: {v}" for k, v in sit_prop.most_common()),
        f"- Instrumentos: **{len(r.get('parceria', []))}** — " + ", ".join(f"{k}: {v}" for k, v in sit_parc.most_common()),
        f"- Financeiro: {len(r.get('empenho-parceria', []))} NE → {len(r.get('documento-habil', []))} DH → "
        f"{len(r.get('ordem-pagamento', []))} OP/OB · {len(contas)} contas · "
        f"{len(r.get('extrato-bancario', []))} lançamentos de extrato",
        f"- Saldos: {_brl(saldo_cc)} em conta corrente + {_brl(saldo_inv)} aplicados",
        "",
        "## Emendas indicadas ao ente (dinheiro a caminho)",
        f"- **{len(emendas)}** indicações · {_brl(vl_emendas)}"
        + (f" · parlamentares: {', '.join(parlamentares[:6])}{'…' if len(parlamentares) > 6 else ''}" if parlamentares else ""),
        "",
        "## Transferências especiais (emendas Pix)",
        f"- Planos de ação: **{len(planos)}** ({_brl(vl_pix)}) — "
        + (", ".join(f"{k}: {v}" for k, v in sit_pix.most_common()) if planos else "nenhum"),
    ]
    if impedidos:
        linhas.append(f"- 🔴 **{len(impedidos)} impedido(s)**:")
        for p in cj["especiais"]["impedidos"][:8]:
            mot = f" — {p['motivo'][:160]}…" if p["motivo"] and len(p["motivo"]) > 160 else (
                f" — {p['motivo']}" if p["motivo"] else "")
            linhas.append(f"  - `{p['codigo']}` ({p['ano']}): {p['situacao']}{mot}")
    if not planos and "OSC" in DOGFOOD.get(cnpj, ""):
        linhas.append("- (OSC não recebe transferência especial — art. 166-A é ente a ente; esperado)")
    linhas += ["", "> Estoque SICONV (2008→ago/2023) entra via CSV detru — próxima etapa do recorte.", ""]
    return cj, "\n".join(linhas)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--cnpj", action="append", default=[], help="repetível; default = dogfood")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    cnpjs = ["".join(c for c in x if c.isdigit()) for x in (args.cnpj or list(DOGFOOD))]
    dt_api = data_atualizacao()
    base_out = Path(args.out) if args.out else RAIZ / "data" / "recortes" / dt_api[:10]

    for cnpj in cnpjs:
        destino = base_out / cnpj
        dados = recortar(cnpj, destino, args.workers)
        cj, md = carteira(cnpj, dados, dt_api)
        destino.joinpath("carteira.json").write_text(
            json.dumps(cj, ensure_ascii=False, indent=2), encoding="utf-8")
        destino.joinpath("carteira.md").write_text(md, encoding="utf-8")
        p = cj["parcerias"]
        print(f"   propostas={p['propostas']} instrumentos={p['instrumentos']} "
              f"NE={p['empenhos']} OP={p['ordens_pagamento']} extrato={p['lancamentos_extrato']} "
              f"pix={cj['especiais']['planos']} impedidos={len(cj['especiais']['impedidos'])} "
              f"-> {destino / 'carteira.md'}", flush=True)

    print(f"\nrecortes em {base_out} (data da API: {dt_api})", flush=True)


if __name__ == "__main__":
    main()
