"""Extrator da API g2 do Transferegov — módulo Gestão de Parcerias (Discricionárias e Legais).

Baixa todas as rotas de https://api-publica.transferegov.gestao.gov.br/parcerias
em JSONL (opcionalmente .gz), com paginação (cap 200/página), retry com backoff
e manifesto de validação (linhas extraídas × total_items anunciado).

Sem dependências externas — stdlib pura (Python 3.10+).

Uso:
    python g2_parcerias.py                          # dump completo, todas as rotas
    python g2_parcerias.py --rotas proposta parceria
    python g2_parcerias.py --filtro cnpj_ente_recebedor=00000000000000
    python g2_parcerias.py --paginas-max 2          # amostra (teste)
    python g2_parcerias.py --out data/parcerias --workers 4

O filtro é repassado como query string — qualquer parâmetro do OpenAPI vale
(ver docs/api-parcerias-g2.md). O recorte por ente da F0 é:
proposta?cnpj_ente_recebedor=… → ids → rotas-filhas por id_proposta/id_parceria.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api-publica.transferegov.gestao.gov.br/parcerias"
PAGE_SIZE = 200          # máximo aceito pela API (422 acima disso)
TIMEOUT = 90
MAX_TENTATIVAS = 5
USER_AGENT = "tuiu-ingest/0.1 (araticum; adm@araticumcomercio.com.br)"

# Rotas paginadas (envelope data/total_pages/total_items/page_number/page_size)
ROTAS = [
    "programa",
    "proposta",
    "meta-proposta",
    "item-proposta",
    "cronograma-desembolso",
    "parceria",
    "parceria-conta",
    "analise-proposta",
    "proposta-resultado-indicador",
    "distribuicao-recurso-proposta",
    "empenho-parceria",
    "documento-habil",
    "ordem-pagamento",
    "extrato-bancario",
    "beneficiario_emenda_parlamentar",
]
# Rota singleton, sem paginação: {"data_ultima_atualizacao": "..."}
ROTA_DATA_ATUALIZACAO = "data-atualizacao"


def _get_json(url: str) -> dict:
    """GET com retry/backoff exponencial para 429/5xx/erros de rede."""
    ultima_exc: Exception | None = None
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            req = urllib.request.Request(
                url, headers={"accept": "application/json", "User-Agent": USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            # 4xx (exceto 429) é erro de chamada — não adianta repetir
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            ultima_exc = exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            ultima_exc = exc
        time.sleep(min(2 ** tentativa, 30))
    raise RuntimeError(f"esgotadas {MAX_TENTATIVAS} tentativas: {url}") from ultima_exc


def _url_rota(rota: str, pagina: int, filtros: dict[str, str]) -> str:
    params = dict(filtros)
    params["pagina"] = str(pagina)
    params["tamanho_da_pagina"] = str(PAGE_SIZE)
    return f"{BASE}/{rota}?{urllib.parse.urlencode(params)}"


def data_atualizacao() -> str:
    return _get_json(f"{BASE}/{ROTA_DATA_ATUALIZACAO}")["data_ultima_atualizacao"]


def extrair_rota(
    rota: str,
    out_dir: Path,
    filtros: dict[str, str],
    workers: int,
    paginas_max: int | None = None,
    usar_gzip: bool = True,
) -> dict:
    """Extrai uma rota completa para <out_dir>/<rota>.jsonl[.gz]; retorna resumo p/ manifesto."""
    t0 = time.time()
    primeira = _get_json(_url_rota(rota, 1, filtros))
    total_items = primeira["total_items"]
    total_pages = primeira["total_pages"]
    paginas = min(total_pages, paginas_max) if paginas_max else total_pages

    nome = rota.replace("_", "-") + (".jsonl.gz" if usar_gzip else ".jsonl")
    destino = out_dir / nome
    abrir = (lambda p: gzip.open(p, "wt", encoding="utf-8")) if usar_gzip else (
        lambda p: open(p, "w", encoding="utf-8")
    )

    linhas = 0
    with abrir(destino) as fh:
        for registro in primeira["data"]:
            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
            linhas += 1

        if paginas > 1:
            # Baixa em paralelo, grava em ordem de página (buffer por número).
            buffer: dict[int, list] = {}
            proxima_gravar = 2
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futuros = {
                    pool.submit(_get_json, _url_rota(rota, p, filtros)): p
                    for p in range(2, paginas + 1)
                }
                for fut in as_completed(futuros):
                    pagina = futuros[fut]
                    buffer[pagina] = fut.result()["data"]
                    while proxima_gravar in buffer:
                        for registro in buffer.pop(proxima_gravar):
                            fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
                            linhas += 1
                        proxima_gravar += 1

    duracao = round(time.time() - t0, 1)
    completo = paginas == total_pages
    ok = (linhas == total_items) if completo else True
    resumo = {
        "rota": rota,
        "arquivo": destino.name,
        "total_items_api": total_items,
        "total_pages_api": total_pages,
        "paginas_extraidas": paginas,
        "linhas_gravadas": linhas,
        "completo": completo,
        "bate_com_api": ok,
        "duracao_s": duracao,
        "filtros": filtros,
    }
    status = "OK" if ok else "DIVERGENTE"
    print(
        f"[{status}] {rota}: {linhas:,} linhas / {total_items:,} anunciadas "
        f"({paginas}/{total_pages} pág., {duracao}s)",
        flush=True,
    )
    return resumo


def _rotas_do_modulo(base: str) -> list[str]:
    """Descobre as rotas do módulo pelo openapi.json — em vez de manter a lista
    à mão para cada módulo (parcerias tem 16, especiais 21)."""
    spec = _get_json(f"{base}/openapi.json")
    return [p.lstrip("/") for p in sorted((spec.get("paths") or {}).keys())
            if p.lstrip("/") not in ("data-atualizacao", "openapi.json")]


def main(argv: list[str] | None = None) -> int:
    global BASE
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--modulo", choices=("parcerias", "especiais"), default="parcerias",
                    help="módulo da g2 (especiais = ciclo Pix/emenda; rotas via openapi)")
    ap.add_argument("--rotas", nargs="+", default=None, metavar="ROTA",
                    help="rotas específicas (default: todas do módulo)")
    ap.add_argument("--out", default=None, help="diretório-base de saída")
    ap.add_argument("--filtro", action="append", default=[], metavar="CHAVE=VALOR",
                    help="filtro de query da API (repetível); ex.: cnpj_ente_recebedor=…")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--paginas-max", type=int, default=None,
                    help="limita páginas por rota (amostra/teste)")
    ap.add_argument("--sem-gzip", action="store_true")
    args = ap.parse_args(argv)

    BASE = BASE.rsplit("/", 1)[0] + "/" + args.modulo
    if args.rotas is None:
        args.rotas = ROTAS if args.modulo == "parcerias" else _rotas_do_modulo(BASE)
    if args.out is None:
        args.out = f"data/{args.modulo}"

    filtros: dict[str, str] = {}
    for item in args.filtro:
        chave, _, valor = item.partition("=")
        if not valor:
            ap.error(f"--filtro exige CHAVE=VALOR, recebi: {item!r}")
        filtros[chave] = valor

    dt_api = data_atualizacao()
    out_dir = Path(args.out) / dt_api[:10]
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"data_ultima_atualizacao da API: {dt_api} → {out_dir}", flush=True)

    resumos, falhas = [], []
    for rota in args.rotas:  # rotas em série (padrão da casa); paralelismo só dentro da rota
        try:
            resumos.append(
                extrair_rota(rota, out_dir, filtros, args.workers,
                             args.paginas_max, not args.sem_gzip)
            )
        except Exception as exc:  # noqa: BLE001 — registrar e seguir para a próxima rota
            falhas.append({"rota": rota, "erro": str(exc)})
            print(f"[FALHA] {rota}: {exc}", flush=True)

    dt_api_fim = data_atualizacao()
    manifesto = {
        "extraido_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base": BASE,
        "data_atualizacao_inicio": dt_api,
        "data_atualizacao_fim": dt_api_fim,
        "snapshot_estavel": dt_api == dt_api_fim,
        "page_size": PAGE_SIZE,
        "filtros": filtros,
        "rotas": resumos,
        "falhas": falhas,
    }
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"manifesto: {out_dir / '_manifest.json'}", flush=True)

    if falhas or any(not r["bate_com_api"] for r in resumos):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
