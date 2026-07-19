"""Conferência de integridade (fecha o "pronto quando" da F0).

Re-consulta a g2 oficial AO VIVO por CNPJ e compara a contagem autoritativa
(`total_items` do envelope) com o que o recorte guardou — detecta drift do
extrator, recorte velho ou bug de paginação. Não é validação de terceiro (o
Portal da Transparência exige chave/cadastro do dono); é reprodutibilidade
contra a própria fonte oficial, no instante da checagem.

Rotas com filtro direto por CNPJ (as demais ligam por id e não dão contagem
independente barata):
  proposta                        ?cnpj_ente_recebedor
  beneficiario_emenda_parlamentar ?nr_cnpj_beneficiario_emenda

Uso:
    py -3 ingest/transferegov_g2/verificar.py
Escreve data/recortes/<snap>/_verificacao.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g2_parcerias import BASE, _get_json, data_atualizacao  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]

CHECAGENS = [
    # (rótulo, rota, param_cnpj, caminho no carteira.json p/ o valor guardado)
    ("propostas", "proposta", "cnpj_ente_recebedor", ("parcerias", "propostas")),
    ("emendas_indicadas", "beneficiario_emenda_parlamentar", "nr_cnpj_beneficiario_emenda",
     ("emendas_indicadas", "qtd")),
]


def _total_items(rota: str, param: str, cnpj: str) -> int:
    url = f"{BASE}/{rota}?{param}={cnpj}&pagina=1&tamanho_da_pagina=1"
    return int(_get_json(url).get("total_items") or 0)


def _guardado(carteira: dict, caminho: tuple) -> int:
    v = carteira
    for k in caminho:
        v = (v or {}).get(k, 0)
    return int(v or 0)


def snapshot_recente() -> Path:
    rec = RAIZ / "data" / "recortes"
    for d in sorted(rec.iterdir(), reverse=True):
        if d.is_dir() and any((s / "carteira.json").exists() for s in d.iterdir() if s.is_dir()):
            return d
    sys.exit("sem recortes")


def main():
    estrito = "--strict" in sys.argv  # CI: falha em divergência. Default: só relata (não trava a cadeia).
    snap = snapshot_recente()
    dt_api = data_atualizacao()
    resultado = {"snapshot": snap.name, "data_atualizacao_api": dt_api,
                 "snapshot_fresco": dt_api[:10] == snap.name, "entes": []}
    total_ok = total_div = 0

    sys.path.insert(0, str(RAIZ / "backend"))
    from app.carteira import docs_ativos

    ativos = docs_ativos()
    for sub in sorted(snap.iterdir()):
        cj = sub / "carteira.json"
        if not (sub.is_dir() and cj.exists()):
            continue
        if ativos and sub.name not in ativos:
            continue
        carteira = json.loads(cj.read_text(encoding="utf-8"))
        cnpj = carteira["cnpj"]
        linha = {"cnpj": cnpj, "rotulo": carteira.get("nome"), "checagens": {}}
        for rotulo, rota, param, caminho in CHECAGENS:
            live = _total_items(rota, param, cnpj)
            guard = _guardado(carteira, caminho)
            ok = live == guard
            total_ok += ok
            total_div += (not ok)
            linha["checagens"][rotulo] = {"guardado": guard, "ao_vivo": live, "ok": ok,
                                          "delta": live - guard}
        resultado["entes"].append(linha)

    resultado["resumo"] = {"conferem": total_ok, "divergem": total_div}
    (snap / "_verificacao.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")

    fresco = "SIM" if resultado["snapshot_fresco"] else f"NAO (API={dt_api[:10]}, recorte={snap.name})"
    print(f"snapshot fresco: {fresco}")
    for e in resultado["entes"]:
        for rot, c in e["checagens"].items():
            flag = "OK" if c["ok"] else f"DIVERGE (delta {c['delta']:+d})"
            print(f"  {e['cnpj']} {rot}: guardado={c['guardado']} vivo={c['ao_vivo']} -> {flag}")
    print(f"resumo: {total_ok} conferem, {total_div} divergem -> {snap / '_verificacao.json'}")
    sys.exit(1 if (estrito and total_div) else 0)


if __name__ == "__main__":
    main()
