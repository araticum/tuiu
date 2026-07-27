"""Motor de eventos (F1.5) — detecta mudança de andamento por diff de estado.

Compara o recorte atual de cada ente com o ÚLTIMO estado conhecido (tabela
entidades_estado) e emite eventos: `novo` (item apareceu), `mudanca` (situação
mudou) e `incremento` (contador subiu — novo empenho/OP/relatório). Preciso e
atribuível porque lê os arquivos brutos por-ente (que têm id/nº), não os
agregados. É o "webhook" honesto: andamento D-1 dos processos do CNPJ, sem
credencial de ninguém.

Uso:
    py -3 backend/app/eventos.py            # detecta no snapshot mais recente
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.carteira import nome_exibicao, nomes_carteira, snapshot_mais_recente  # noqa: E402
from app.db import conectar, migrar  # noqa: E402

# Trackers de SITUAÇÃO: (domínio, caminho relativo, campo-chave, campo-situação, campo-rótulo)
TRACKERS = [
    ("proposta_g2", "parcerias/proposta.jsonl.gz", "id_proposta", "situacao_proposta", "id_proposta"),
    ("parceria_g2", "parcerias/parceria.jsonl.gz", "id_parceria", "in_situacao_parceria", "cd_parceria"),
    ("plano_pix", "especiais/planos_acao.jsonl.gz", "id_plano_acao", "situacao_plano_acao", "codigo_plano_acao"),
    ("convenio_legado", "legado/convenio.csv", "NR_CONVENIO", "SIT_CONVENIO", "NR_CONVENIO"),
]
# Trackers de CONTADOR: (domínio, caminho, substantivo)
CONTADORES = [
    ("empenho_g2", "parcerias/empenho-parceria.jsonl.gz", "empenho(s)"),
    ("op_g2", "parcerias/ordem-pagamento.jsonl.gz", "ordem(ns) de pagamento"),
    ("relatorio_pix", "especiais/relatorios_gestao.jsonl.gz", "relatório(s) de gestão"),
]

ROTULO_DOMINIO = {
    "proposta_g2": "Proposta", "parceria_g2": "Instrumento",
    "plano_pix": "Plano Pix", "convenio_legado": "Convênio/CR",
}


def _linhas(caminho: Path):
    if not caminho.exists():
        return
    if caminho.suffix == ".gz":
        with gzip.open(caminho, "rt", encoding="utf-8") as fh:
            for l in fh:
                yield json.loads(l)
    elif caminho.suffix == ".csv":
        with open(caminho, encoding="utf-8-sig", newline="") as fh:
            yield from csv.DictReader(fh, delimiter=";")


def _situacoes(sub: Path, dom, rel, k_chave, k_sit, k_rotulo) -> dict[str, tuple[str, str]]:
    """chave -> (situação, rótulo) do item, no recorte atual."""
    out = {}
    for r in _linhas(sub / rel):
        chave = r.get(k_chave)
        if chave is None:
            continue
        out[str(chave)] = (str(r.get(k_sit) or ""), str(r.get(k_rotulo) or chave))
    return out


def _detectar_ente(con, cnpj: str, ente: str, sub: Path, snap: str) -> list[dict]:
    eventos: list[dict] = []

    def visto(dom: str) -> dict[str, str]:
        return {c: v for c, v in con.execute(
            "SELECT chave, valor FROM entidades_estado WHERE cnpj=%s AND dominio=%s", (cnpj, dom))}

    def gravar_estado(dom: str, chave: str, valor: str):
        con.execute(
            "INSERT INTO entidades_estado (cnpj, dominio, chave, valor, snapshot) VALUES (%s,%s,%s,%s,%s)"
            " ON CONFLICT (cnpj, dominio, chave) DO UPDATE SET valor=EXCLUDED.valor,"
            " snapshot=EXCLUDED.snapshot, atualizado_em=now()",
            (cnpj, dom, chave, valor, snap))

    for dom, rel, k_chave, k_sit, k_rotulo in TRACKERS:
        atual = _situacoes(sub, dom, rel, k_chave, k_sit, k_rotulo)
        if not atual:
            continue
        antes = visto(dom)
        primeira_vez = not antes  # sem estado => baseline; grava sem emitir "novo" em massa
        for chave, (sit, rot) in atual.items():
            rotulo = f"{ROTULO_DOMINIO.get(dom, dom)} {rot}"
            if chave not in antes:
                if not primeira_vez:
                    eventos.append(dict(cnpj=cnpj, ente=ente, dominio=dom, chave=chave, rotulo=rotulo,
                                        tipo="novo", de=None, para=sit, snapshot=snap))
            elif antes[chave] != sit:
                eventos.append(dict(cnpj=cnpj, ente=ente, dominio=dom, chave=chave, rotulo=rotulo,
                                    tipo="mudanca", de=antes[chave], para=sit, snapshot=snap))
            gravar_estado(dom, chave, sit)

    for dom, rel, subst in CONTADORES:
        total = sum(1 for _ in _linhas(sub / rel))
        antes = visto(dom).get("#count")
        if antes is not None and total > int(antes):
            eventos.append(dict(cnpj=cnpj, ente=ente, dominio=dom, chave="#count",
                                rotulo=f"{total - int(antes)} novo(s) {subst}", tipo="incremento",
                                de=antes, para=str(total), snapshot=snap))
        gravar_estado(dom, "#count", str(total))

    return eventos


def detectar(snap: Path | None = None) -> dict:
    snap = snap or snapshot_mais_recente()
    if snap is None:
        raise SystemExit("sem recortes — rode o ingest antes")
    total = 0
    # ROTULOS cobre 8 CNPJs escritos à mão; os outros 42 da carteira só têm nome
    # em `clientes`, e o recorte do legado não traz razão social. Sem consultar
    # os dois, o evento nascia intitulado "78350188000195" — e é esse título que
    # vai inteiro para a mensagem do WhatsApp. O notificador resolve de novo na
    # hora de enviar, para os eventos que já nasceram torto.
    nomes = nomes_carteira()
    with conectar() as con:
        for sub in sorted(snap.iterdir()):
            cj = sub / "carteira.json"
            if not (sub.is_dir() and cj.exists()):
                continue
            carteira = json.loads(cj.read_text(encoding="utf-8"))
            cnpj = carteira["cnpj"]
            ente = nome_exibicao(cnpj, carteira.get("nome"), nomes)
            for ev in _detectar_ente(con, cnpj, ente, sub, snap.name):
                con.execute(
                    "INSERT INTO eventos (cnpj, ente, dominio, chave, rotulo, tipo, de, para, snapshot)"
                    " VALUES (%(cnpj)s,%(ente)s,%(dominio)s,%(chave)s,%(rotulo)s,%(tipo)s,%(de)s,%(para)s,%(snapshot)s)",
                    ev)
                total += 1
        con.commit()
        na_base = con.execute("SELECT count(*) FROM eventos").fetchone()[0]
    return {"snapshot": snap.name, "eventos_novos": total, "eventos_na_base": na_base}


def main():
    print("migracoes:", migrar() or "nenhuma nova")
    r = detectar()
    print(f"eventos novos: {r['eventos_novos']} (total {r['eventos_na_base']}) no snapshot {r['snapshot']}")


if __name__ == "__main__":
    main()
