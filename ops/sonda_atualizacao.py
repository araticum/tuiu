"""Sonda do horário de carga do Transferegov — mede QUANDO a fonte atualiza.

Troca a estimativa herdada ("carga ~09h") por medição. Duas fontes, dois sinais
de natureza diferente:

  g2 (API)    `/parcerias/data-atualizacao` e `/especiais/data-atualizacao`
              devolvem só a DATA, carimbada 00:00:00 — o campo diz de QUE DIA é
              o dado, nunca a hora em que entrou. A hora sai do FLIP: última
              sondagem que ainda via D-1 e primeira que já via D. A precisão é o
              intervalo entre sondagens (10 min no timer sugerido abaixo).
  detru CSV   os ZIPs de `downloads/dadosgov` trazem `Last-Modified` no HEAD —
              hora exata da publicação, de graça, sem baixar os 300 MB. É a
              fonte que hoje produz quase todo evento (`convenio_legado`), então
              é a que mais importa para posicionar a cadeia diária.

Por que medir: `rodar_diario` dispara às 09h30 por margem de segurança sobre um
"~09h" que ninguém conferiu. Se a carga real termina bem antes, a cadeia pode
adiantar (cliente sabe mais cedo); se às vezes atrasa, a cadeia hoje publica
dado velho como se fosse fresco — e é o `_verificacao.json` que denuncia.

Uso:
    py -3 ops/sonda_atualizacao.py            # uma sondagem (o timer chama assim)
    py -3 ops/sonda_atualizacao.py --resumo   # o que já foi medido

Timer no host (a cada 10 min na janela da madrugada/manhã):
    OnCalendar=*-*-* 04..11:00/10:00
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DIARIO = RAIZ / "ops" / "logs" / "sonda-atualizacao.jsonl"

BASE_API = "https://api-publica.transferegov.gestao.gov.br"
ROTAS_G2 = ["parcerias/data-atualizacao", "especiais/data-atualizacao"]
# mesmos ZIPs que a cadeia diária baixa (ver ops/rodar_diario.py)
ZIPS_DETRU = ["siconv_convenio.zip", "siconv_proposta.zip", "siconv_historico_situacao.zip"]


def _agora() -> datetime:
    return datetime.now().astimezone()


def _get_json(url: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _last_modified(url: str, timeout: float = 60.0) -> str | None:
    """HEAD: só o cabeçalho, sem corpo — 300 MB não trafegam por sondagem."""
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        bruto = r.headers.get("Last-Modified")
    return parsedate_to_datetime(bruto).astimezone().isoformat() if bruto else None


def sondar() -> dict:
    """Uma leitura de todos os sinais. Falha de um sinal não derruba os outros:
    a sonda é observação, nunca pode virar mais um elo que quebra."""
    leitura: dict = {"em": _agora().isoformat(timespec="seconds"), "g2": {}, "detru": {}}
    for rota in ROTAS_G2:
        try:
            leitura["g2"][rota.split("/")[0]] = _get_json(f"{BASE_API}/{rota}")["data_ultima_atualizacao"]
        except Exception as e:  # noqa: BLE001
            leitura["g2"][rota.split("/")[0]] = f"erro: {type(e).__name__}"
    for zip_nome in ZIPS_DETRU:
        try:
            leitura["detru"][zip_nome] = _last_modified(f"{BASE_API}/downloads/dadosgov/{zip_nome}")
        except Exception as e:  # noqa: BLE001
            leitura["detru"][zip_nome] = f"erro: {type(e).__name__}"

    DIARIO.parent.mkdir(parents=True, exist_ok=True)
    with open(DIARIO, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(leitura, ensure_ascii=False) + "\n")
    return leitura


def _leituras() -> list[dict]:
    if not DIARIO.exists():
        return []
    return [json.loads(l) for l in DIARIO.read_text(encoding="utf-8").splitlines() if l.strip()]


def resumo() -> None:
    leituras = _leituras()
    if not leituras:
        print(f"nada medido ainda — rode a sonda (diário: {DIARIO})")
        return

    print(f"{len(leituras)} sondagens · {leituras[0]['em'][:16]} -> {leituras[-1]['em'][:16]}\n")

    # g2: a hora da carga está entre a última leitura com o valor antigo e a
    # primeira com o novo. Uma janela por dia, por domínio.
    print("g2 (API) — janela do flip de data_ultima_atualizacao")
    for dominio in ("parcerias", "especiais"):
        anterior = None
        achou = False
        for leit in leituras:
            valor = (leit.get("g2") or {}).get(dominio)
            if not valor or valor.startswith("erro"):
                continue
            if anterior and valor != anterior[1]:
                print(f"  {dominio:10s} {anterior[1][:10]} -> {valor[:10]} "
                      f"entre {anterior[0][11:16]} e {leit['em'][11:16]} ({leit['em'][:10]})")
                achou = True
            anterior = (leit["em"], valor)
        if not achou:
            print(f"  {dominio:10s} nenhum flip capturado ainda "
                  f"(valor atual: {anterior[1][:10] if anterior else '?'})")

    # detru: Last-Modified já é a hora exata; agrupa por dia de publicação.
    print("\ndetru (CSV) — Last-Modified publicado, por dia")
    por_dia: dict[str, dict[str, str]] = defaultdict(dict)
    for leit in leituras:
        for zip_nome, quando in (leit.get("detru") or {}).items():
            if quando and not quando.startswith("erro"):
                por_dia[quando[:10]][zip_nome] = quando
    for dia in sorted(por_dia)[-14:]:
        horas = sorted(q[11:19] for q in por_dia[dia].values())
        print(f"  {dia}  {horas[0]} -> {horas[-1]}  ({len(por_dia[dia])} arquivo(s))")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--resumo", action="store_true", help="lê o diário e mostra as janelas medidas")
    args = ap.parse_args()

    if args.resumo:
        resumo()
        return
    leit = sondar()
    g2 = ", ".join(f"{k}={v[:10]}" for k, v in leit["g2"].items())
    detru = ", ".join(f"{k.replace('siconv_', '').replace('.zip', '')}={(v or '?')[11:19]}"
                      for k, v in leit["detru"].items())
    print(f"[{leit['em'][11:19]}] g2: {g2} | detru: {detru}")


if __name__ == "__main__":
    main()
