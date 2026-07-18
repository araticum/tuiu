"""Conferência de TERCEIRO: nossa carteira × Portal da Transparência (CGU).

Diferente da conferência de integridade (que re-consulta a própria g2), aqui a
fonte é independente: o Portal da Transparência da CGU. O elo é o
`dimConvenio.codigo` do Portal == `NR_CONVENIO` do SICONV/detru.

Para cada ente monitorado (por código IBGE do município), baixa os convênios do
Portal, filtra pelo CNPJ do ente e compara os conjuntos de nº de convênio com o
que o recorte do detru guardou. Reporta:
  - ambos      : instrumento nos dois (confere)
  - so_portal  : Portal tem, nosso recorte não (nossa lacuna)
  - so_nosso   : temos, Portal não (esperado p/ ciclo novo/não-convênio)

Uso:
    py -3 ingest/transparencia/cruzar_carteira.py
Escreve data/recortes/<snap>/_cruzamento_transparencia.json
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliente_transparencia import convenios, normalizar  # noqa: E402


def snapshot_recente() -> Path:
    rec = RAIZ / "data" / "recortes"
    for d in sorted(rec.iterdir(), reverse=True):
        if d.is_dir() and any((s / "carteira.json").exists() for s in d.iterdir() if s.is_dir()):
            return d
    sys.exit("sem recortes")


def _nossos_convenios(sub: Path) -> set[str]:
    arq = sub / "legado" / "convenio.csv"
    if not arq.exists():
        return set()
    with open(arq, encoding="utf-8-sig", newline="") as fh:
        return {(r.get("NR_CONVENIO") or "").strip() for r in csv.DictReader(fh, delimiter=";")}


def _ibge(carteira: dict, sub: Path) -> str:
    """IBGE do ente: carteira (g2) ou, como fallback, o COD_MUNIC_IBGE do detru.
    O filtro por `convenente` do Portal usa o ID INTERNO dele (não o CNPJ), então
    a localidade é o filtro restritivo viável."""
    if carteira.get("ibge"):
        return str(carteira["ibge"])
    arq = sub / "legado" / "proposta.csv"
    if arq.exists():
        with open(arq, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                cod = (r.get("COD_MUNIC_IBGE") or "").strip()
                if cod:
                    return cod
    return ""


def main():
    snap = snapshot_recente()
    saida = {"snapshot": snap.name, "fonte": "Portal da Transparência (CGU) — /api-de-dados/convenios",
             "elo": "dimConvenio.codigo == NR_CONVENIO (SICONV/detru)",
             "nota_cobertura": "Divergência esperada: o Portal (base SIAFI) carrega instrumentos "
                               "PRÉ-SICONV (2005–2008); o extrato detru cobre a era SICONV (2008→). "
                               "Ver so_portal_perfil.por_ano — não é lacuna do recorte.",
             "entes": []}
    cache_ibge: dict[str, list] = {}

    for sub in sorted(snap.iterdir()):
        cj = sub / "carteira.json"
        if not (sub.is_dir() and cj.exists()):
            continue
        carteira = json.loads(cj.read_text(encoding="utf-8"))
        cnpj, ibge = carteira["cnpj"], _ibge(carteira, sub)
        if not ibge:
            saida["entes"].append({"cnpj": cnpj, "rotulo": carteira.get("nome"),
                                   "pulado": "sem código IBGE (nem g2 nem detru) — Portal exige filtro de localidade"})
            print(f"  {cnpj}: PULADO (sem IBGE)")
            continue

        if ibge not in cache_ibge:
            regs, erro = convenios(codigoIBGE=ibge)
            if erro:
                saida["entes"].append({"cnpj": cnpj, "erro": erro})
                continue
            cache_ibge[ibge] = [normalizar(r) for r in regs]
        do_municipio = cache_ibge[ibge]

        meus = [c for c in do_municipio if c["cnpj_convenente"] == cnpj and c["codigo_siconv"]]
        portal = {c["codigo_siconv"] for c in meus}
        nossos = _nossos_convenios(sub)
        ambos, so_portal, so_nosso = portal & nossos, portal - nossos, nossos - portal

        # Por que o Portal tem mais? Perfil dos exclusivos (tipo e ano de início).
        from collections import Counter
        exclusivos = [c for c in meus if c["codigo_siconv"] in so_portal]
        por_tipo = Counter(c["tipo"] or "?" for c in exclusivos)
        por_ano = Counter((c["inicio_vigencia"] or "?")[:4] for c in exclusivos)
        anos = sorted(a for a in por_ano if a.isdigit())

        saida["entes"].append({
            "cnpj": cnpj, "ibge": ibge, "rotulo": carteira.get("nome"),
            "portal": len(portal), "nosso_detru": len(nossos),
            "ambos": len(ambos), "so_portal": sorted(so_portal)[:20], "so_nosso": sorted(so_nosso)[:20],
            "cobertura_do_portal": round(100 * len(ambos) / len(portal), 1) if portal else None,
            "so_portal_perfil": {
                "por_tipo": dict(por_tipo.most_common()),
                "anos_extremos": [anos[0], anos[-1]] if anos else None,
                "por_ano": dict(sorted(por_ano.items())),
            },
        })
        print(f"  {cnpj} ibge={ibge}: portal={len(portal)} nosso={len(nossos)} "
              f"ambos={len(ambos)} so_portal={len(so_portal)} so_nosso={len(so_nosso)}")

    (snap / "_cruzamento_transparencia.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {snap / '_cruzamento_transparencia.json'}")


if __name__ == "__main__":
    main()
