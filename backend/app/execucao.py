"""Execução financeira por convênio (F2) — persiste os VL_* do detru legado.

O detru já traz, por convênio ativo, repasse/desembolsado/saldo a devolver/
rendimento — as colunas de dinheiro da planilha do Danilo (84% com desembolso
preenchido na carteira de 50). O `recorte_ente` só as narrava em texto; aqui
viram linha consultável (`execucao_convenio`) para a Mesa mostrar o quanto
entrou, saiu e falta devolver.

Reposto a cada rodada do pipe (junto do motor de prazos). Só legado nesta leva.

    python backend/app/execucao.py     # (com --app-dir backend, da raiz)
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.carteira import docs_ativos, snapshot_mais_recente  # noqa: E402
from app.db import conectar, migrar  # noqa: E402


def _num(s: str | None) -> float:
    """Número no padrão BR do detru (1.999.999,95). Vazio/estranho = 0."""
    try:
        return float((s or "0").strip().replace(".", "").replace(",", ".")) or 0.0
    except (ValueError, AttributeError):
        return 0.0


def _data(s: str | None) -> date | None:
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


COLS = ("cnpj", "instrumento", "fonte", "situacao", "vl_global", "vl_repasse",
        "vl_contrapartida", "vl_empenhado", "vl_desembolsado", "vl_saldo_reman_tesouro",
        "vl_saldo_reman_convenente", "vl_rendimento", "vl_saldo_conta",
        "inicio_vigencia", "fim_vigencia", "limite_prestacao", "snapshot")


def _linha(cnpj: str, r: dict, snapshot: str) -> dict:
    return {
        "cnpj": cnpj, "instrumento": r.get("NR_CONVENIO"), "fonte": "legado",
        "situacao": (r.get("SIT_CONVENIO") or "").strip() or None,
        "vl_global": _num(r.get("VL_GLOBAL_CONV")),
        "vl_repasse": _num(r.get("VL_REPASSE_CONV")),
        "vl_contrapartida": _num(r.get("VL_CONTRAPARTIDA_CONV")),
        "vl_empenhado": _num(r.get("VL_EMPENHADO_CONV")),
        "vl_desembolsado": _num(r.get("VL_DESEMBOLSADO_CONV")),
        "vl_saldo_reman_tesouro": _num(r.get("VL_SALDO_REMAN_TESOURO")),
        "vl_saldo_reman_convenente": _num(r.get("VL_SALDO_REMAN_CONVENENTE")),
        "vl_rendimento": _num(r.get("VL_RENDIMENTO_APLICACAO")),
        "vl_saldo_conta": _num(r.get("VL_SALDO_CONTA")),
        "inicio_vigencia": _data(r.get("DIA_INIC_VIGENC_CONV")),
        "fim_vigencia": _data(r.get("DIA_FIM_VIGENC_CONV")),
        "limite_prestacao": _data(r.get("DIA_LIMITE_PREST_CONTAS")),
        "snapshot": snapshot,
    }


def persistir() -> dict:
    snap = snapshot_mais_recente()
    if snap is None:
        raise SystemExit("sem recortes — rode o ingest antes")
    ativos = docs_ativos()
    linhas: list[dict] = []
    for sub in sorted(snap.iterdir()):
        conv = sub / "legado" / "convenio.csv"
        if not (sub.is_dir() and conv.exists()):
            continue
        cnpj = sub.name
        if ativos and cnpj not in ativos:
            continue
        with open(conv, encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                if (r.get("INSTRUMENTO_ATIVO") or "").upper() == "SIM" and r.get("NR_CONVENIO"):
                    linhas.append(_linha(cnpj, r, snap.name))

    marcadores = ", ".join(f"%({c})s" for c in COLS)
    set_ = ", ".join(f"{c}=EXCLUDED.{c}" for c in COLS if c not in ("cnpj", "instrumento"))
    with conectar() as con:
        # QUEM tinha linha antes, entre os clientes que continuam ativos. É o
        # denominador da conferência abaixo — sem ele, o DELETE que "espelha a
        # rodada" não distingue "o convênio saiu" de "o recorte veio vazio".
        antes = {c for (c,) in con.execute(
            "SELECT DISTINCT cnpj FROM execucao_convenio"
            + (" WHERE cnpj = ANY(%s)" if ativos else ""),
            (list(ativos),) if ativos else ())}
        agora = {l["cnpj"] for l in linhas}
        sumiram = antes - agora
        if sumiram:
            # Perda silenciosa em operação NORMAL: `detru_recorte` só grava
            # `legado/convenio.csv` quando há linhas, e o recorte nasce em pasta
            # nova a cada dia. Cliente que numa rodada não casa convênio nenhum
            # perderia TODAS as suas linhas de repasse, desembolso e saldo — a
            # coluna de dinheiro que a mesa usa para priorizar — sem uma palavra
            # no log, porque `main()` sai com 0 e o passo essencial só olha
            # código diferente de zero.
            #
            # Some por decisão (cliente desligado) continua funcionando: esse
            # caminho passa pela segunda cláusula do DELETE, com `ativos`.
            raise SystemExit(
                f"RECUSADO: {len(sumiram)} cliente(s) ativo(s) tinham execução na base e "
                f"vieram SEM nenhuma linha neste recorte ({snap.name}). Isso apagaria o "
                f"histórico financeiro deles.\n"
                f"  CNPJ: {', '.join(sorted(sumiram)[:5])}"
                f"{' …' if len(sumiram) > 5 else ''}\n"
                f"  Confira o recorte antes de insistir — provavelmente o `legado/convenio.csv` "
                f"não foi gerado para esses clientes.")
        inicio = con.execute("SELECT clock_timestamp()").fetchone()[0]
        for l in linhas:
            con.execute(
                f"INSERT INTO execucao_convenio ({', '.join(COLS)}, atualizado_em)"
                f" VALUES ({marcadores}, clock_timestamp())"
                f" ON CONFLICT (cnpj, instrumento) DO UPDATE SET {set_}, atualizado_em=clock_timestamp()",
                l)
        # espelha a rodada: convênio que saiu do recorte (ou cliente desligado) some
        removidos = con.execute(
            "DELETE FROM execucao_convenio WHERE atualizado_em < %s"
            + (" OR NOT (cnpj = ANY(%s))" if ativos else ""),
            (inicio, list(ativos)) if ativos else (inicio,)).rowcount
        con.commit()
        n = con.execute("SELECT count(*) FROM execucao_convenio").fetchone()[0]
    return {"persistidos": len(linhas), "total_na_base": n, "removidos": removidos,
            "snapshot": snap.name}


def _f(x) -> float:
    return float(x) if x is not None else 0.0


def _derivados(rep, des, saldo_t, saldo_c, rend, ini, fim, hoje) -> dict:
    pct_desemb = round(100 * des / rep, 1) if rep else None
    pct_tempo = None
    if ini and fim and fim > ini:
        pct_tempo = round(100 * (hoje - ini).days / (fim - ini).days, 1)
        pct_tempo = max(0.0, min(pct_tempo, 999.0))
    return {
        "vl_repasse": rep, "vl_desembolsado": des, "vl_saldo_devolver": saldo_t,
        "vl_saldo_conta": saldo_c, "vl_rendimento": rend,
        "pct_desembolsado": pct_desemb, "pct_tempo_decorrido": pct_tempo,
        # gap físico-financeiro: tempo correndo à frente do dinheiro (só se sobra a gastar)
        "gap_execucao": (pct_tempo is not None and pct_desemb is not None
                         and pct_tempo - pct_desemb >= 25 and pct_desemb < 100),
    }


def por_instrumento(con, hoje: date | None = None) -> dict[tuple, dict]:
    """{(cnpj, instrumento): {financeiros + derivados}} para a Mesa enriquecer a linha."""
    hoje = hoje or date.today()
    out: dict[tuple, dict] = {}
    for (cnpj, instr, rep, des, saldo_t, saldo_c, rend, ini, fim) in con.execute(
            "SELECT cnpj, instrumento, vl_repasse, vl_desembolsado, vl_saldo_reman_tesouro,"
            " vl_saldo_conta, vl_rendimento, inicio_vigencia, fim_vigencia FROM execucao_convenio"):
        out[(cnpj, instr)] = _derivados(_f(rep), _f(des), _f(saldo_t), _f(saldo_c),
                                        _f(rend), ini, fim, hoje)
    return out


def resumo_cliente(con) -> dict[str, dict]:
    """Totais por cliente (repasse, desembolsado, a devolver) — o rodapé de dinheiro."""
    out: dict[str, dict] = {}
    for (cnpj, n, rep, des, saldo, rend) in con.execute(
            "SELECT cnpj, count(*), COALESCE(sum(vl_repasse),0), COALESCE(sum(vl_desembolsado),0),"
            " COALESCE(sum(vl_saldo_reman_tesouro),0), COALESCE(sum(vl_rendimento),0)"
            " FROM execucao_convenio GROUP BY cnpj"):
        out[cnpj] = {"instrumentos": n, "vl_repasse": _f(rep), "vl_desembolsado": _f(des),
                     "vl_saldo_devolver": _f(saldo), "vl_rendimento": _f(rend)}
    return out


def main():
    print("migracoes:", migrar() or "nenhuma nova")
    print(persistir())


if __name__ == "__main__":
    main()
