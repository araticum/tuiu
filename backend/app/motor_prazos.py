"""Motor de prazos (F1) — deriva marcos das carteiras e gera alertas (outbox).

Fontes: data/recortes/<snapshot>/<cnpj>/ (carteira.json + legado/*.csv).
Marcos derivados nesta versão:
  - legado: limite de prestação de contas (DIA_LIMITE_PREST_CONTAS do detru; na
    falta, fim de vigência + prazo da regra vigente do regime) e fim de vigência
    de instrumentos ativos;
  - especiais: plano de ação IMPEDIDO = ação imediata (multa de 1%/dia no
    estoque 2020–2024 — IN TCU 93/2024);
  - geral: defeso eleitoral vigente (janela da Lei 9.504/97).
Alertas: baldes vencido / T-1 / T-7 / T-30, um por (marco, gatilho), mensagem
pronta para WhatsApp com base legal. Canal `outbox` — o fio Seriema entra na
sequência da F1.

Uso:
    py -3 -m app.motor_prazos            # (com --app-dir backend, da raiz do repo)
    python backend/app/motor_prazos.py   # equivalente
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.carteira import ROTULOS, snapshot_mais_recente  # noqa: E402
from app.db import conectar, migrar, regra_vigente  # noqa: E402

CORTE_REGIME_NOVO = date(2023, 9, 1)  # Decreto 11.531 + PC 33 em vigor


def _data_br(s):
    try:
        return datetime.strptime((s or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _farol(limite: date | None, hoje: date) -> str:
    if limite is None:
        return "acao_imediata"
    dias = (limite - hoje).days
    return "vencido" if dias < 0 else ("atencao" if dias <= 90 else "ok")


def _marcos_legado(con, cnpj: str, ente: str, dir_cnpj: Path, hoje: date) -> list[dict]:
    conv_csv = dir_cnpj / "legado" / "convenio.csv"
    if not conv_csv.exists():
        return []
    marcos = []
    with open(conv_csv, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            if (row.get("INSTRUMENTO_ATIVO") or "").upper() != "SIM":
                continue
            nr = row.get("NR_CONVENIO")
            assinatura = _data_br(row.get("DIA_ASSIN_CONV"))
            regime = "completo_pc33" if (assinatura and assinatura >= CORTE_REGIME_NOVO) else "legado_pi424"
            fim_vig = _data_br(row.get("DIA_FIM_VIGENC_CONV"))
            limite_pc = _data_br(row.get("DIA_LIMITE_PREST_CONTAS"))
            base_pc = "cláusula do instrumento (campo DIA_LIMITE_PREST_CONTAS do Transferegov)"
            if limite_pc is None and fim_vig is not None:
                regra = regra_vigente(con, "prazo_prestacao_contas_apresentacao", regime, fim_vig)
                if regra:
                    from datetime import timedelta

                    limite_pc = fim_vig + timedelta(days=int(regra["valor"]["dias"]))
                    base_pc = regra["base_legal"]
            if limite_pc:
                marcos.append({
                    "cnpj": cnpj, "ente": ente, "fonte": "legado", "instrumento": nr,
                    "tipo": "prestacao_contas", "data_limite": limite_pc,
                    "descricao": f"Prestação de contas do {nr} ({row.get('SIT_CONVENIO')})",
                    "base_legal": base_pc, "farol": _farol(limite_pc, hoje),
                    "detalhes": {"regime": regime, "fim_vigencia": row.get("DIA_FIM_VIGENC_CONV")},
                })
            if fim_vig and fim_vig >= hoje:
                marcos.append({
                    "cnpj": cnpj, "ente": ente, "fonte": "legado", "instrumento": nr,
                    "tipo": "fim_vigencia", "data_limite": fim_vig,
                    "descricao": f"Fim de vigência do {nr}",
                    "base_legal": "vigência pactuada no instrumento (Transferegov)",
                    "farol": _farol(fim_vig, hoje), "detalhes": {"regime": regime},
                })
    return marcos


def _marcos_especiais(con, cnpj: str, ente: str, carteira: dict, hoje: date) -> list[dict]:
    marcos = []
    esp = carteira.get("especiais", {})

    # Relatório de gestão ausente no estoque 2020–2024 (a dor dos 82%)
    sem_rel = esp.get("sem_relatorio_2020_2024", [])
    if sem_rel:
        regra = regra_vigente(con, "pix_relatorio_gestao_estoque", "especiais", hoje)
        prazo = date.fromisoformat(regra["valor"]["prazo"]) if regra else None
        base = regra["base_legal"] if regra else "IN TCU 93/2024"
        for p in sem_rel:
            marcos.append({
                "cnpj": cnpj, "ente": ente, "fonte": "especiais",
                "instrumento": p.get("codigo"), "tipo": "relatorio_gestao_pix",
                "data_limite": prazo,
                "descricao": f"Relatório de Gestão AUSENTE do plano {p.get('codigo')} "
                             f"({p.get('ano')}, {p.get('situacao')}) — estoque 2020–2024",
                "base_legal": f"{base}; multa de 1%/dia por pendência",
                "farol": _farol(prazo, hoje), "detalhes": p,
            })

    # Fim de execução pactuado no plano de trabalho aprovado
    for pt in esp.get("planos_trabalho", {}).get("fins_execucao", []):
        try:
            fim = date.fromisoformat(str(pt.get("fim_execucao"))[:10])
        except ValueError:
            continue
        if fim >= hoje:
            marcos.append({
                "cnpj": cnpj, "ente": ente, "fonte": "especiais",
                "instrumento": pt.get("codigo"), "tipo": "fim_execucao_pix",
                "data_limite": fim,
                "descricao": f"Fim da execução pactuada do plano {pt.get('codigo')} "
                             f"({pt.get('situacao')})",
                "base_legal": "plano de trabalho aprovado no Transferegov (execução pactuada)",
                "farol": _farol(fim, hoje), "detalhes": pt,
            })

    for imp in esp.get("impedidos", []):
        regra = regra_vigente(con, "pix_multa_diaria_pendencia", "especiais", hoje)
        base = regra["base_legal"] if regra else "IN TCU 93/2024"
        motivo = (imp.get("motivo") or imp.get("situacao") or "").strip()
        marcos.append({
            "cnpj": cnpj, "ente": ente, "fonte": "especiais",
            "instrumento": imp.get("codigo"), "tipo": "impedimento_pix", "data_limite": None,
            "descricao": f"Plano de ação {imp.get('codigo')} ({imp.get('ano')}) IMPEDIDO — regularizar"
                         + (f": {motivo[:160]}" if motivo else ""),
            "base_legal": f"{base}; risco de multa de 1%/dia no estoque 2020–2024",
            "farol": "acao_imediata", "detalhes": imp,
        })
    return marcos


def _linhas_gz(caminho: Path):
    if not caminho.exists():
        return
    import gzip
    with gzip.open(caminho, "rt", encoding="utf-8") as fh:
        for l in fh:
            yield json.loads(l)


def _marcos_g2(cnpj: str, ente: str, sub: Path, hoje: date) -> list[dict]:
    """Prazos do CICLO NOVO (g2) — a fonte que importa para o TERCEIRO EXECUTOR,
    que normalmente não tem estoque no detru nem transferência especial."""
    marcos: list[dict] = []
    pdir = sub / "parcerias"

    props = {p["id_proposta"]: p for p in _linhas_gz(pdir / "proposta.jsonl.gz")}
    if not props:
        return marcos

    # 1) Cronograma FÍSICO: fim de cada etapa pactuada (meta -> etapas)
    for m in _linhas_gz(pdir / "meta-proposta.jsonl.gz"):
        p = props.get(m.get("id_proposta")) or {}
        for e in (m.get("etapas_proposta") or []):
            try:
                fim = date.fromisoformat(str(e.get("dt_fim"))[:10])
            except (ValueError, TypeError):
                continue
            marcos.append({
                "cnpj": cnpj, "ente": ente, "fonte": "g2",
                "instrumento": f"{p.get('id_proposta')}/{e.get('cd_etapa')}",
                "tipo": "etapa_cronograma", "data_limite": fim,
                "descricao": f"Fim da etapa {e.get('cd_etapa')} — {(e.get('nm_etapa') or '')[:70]}",
                "base_legal": "cronograma físico do plano de trabalho (Transferegov)",
                "farol": _farol(fim, hoje),
                "detalhes": {"meta": m.get("nm_meta"), "situacao_proposta": p.get("situacao_proposta")},
            })

    # 2) Cronograma de DESEMBOLSO: parcela prevista (mês/ano -> fim do mês)
    import calendar
    for c in _linhas_gz(pdir / "cronograma-desembolso.jsonl.gz"):
        mes, ano = c.get("nr_ref_mes_data_especif"), c.get("nr_ref_ano_data_especif")
        if not (mes and ano):
            continue
        try:
            venc = date(int(ano), int(mes), calendar.monthrange(int(ano), int(mes))[1])
        except (ValueError, TypeError):
            continue
        p = props.get(c.get("id_proposta")) or {}
        marcos.append({
            "cnpj": cnpj, "ente": ente, "fonte": "g2",
            "instrumento": str(c.get("id_proposta_cronograma_item")),
            "tipo": "parcela_prevista", "data_limite": venc,
            "descricao": f"Parcela prevista de R$ {float(c.get('vl_cronograma_desembolso') or 0):,.2f}"
                         f" ({c.get('origem_recurso') or '—'})".replace(",", "X").replace(".", ",").replace("X", "."),
            "base_legal": "cronograma de desembolso pactuado (Transferegov)",
            "farol": _farol(venc, hoje),
            "detalhes": {"proposta": p.get("id_proposta"), "situacao": p.get("situacao_proposta")},
        })

    # 3) Proposta parada em análise/elaboração: ação de cobrança (sem prazo legal)
    for p in props.values():
        sit = str(p.get("situacao_proposta") or "")
        if "Análise" in sit or "Analise" in sit:
            try:
                envio = date.fromisoformat(str(p.get("dt_envio_analise"))[:10])
                dias = (hoje - envio).days
            except (ValueError, TypeError):
                continue
            if dias >= 60:
                marcos.append({
                    "cnpj": cnpj, "ente": ente, "fonte": "g2", "instrumento": str(p["id_proposta"]),
                    "tipo": "proposta_parada", "data_limite": None,
                    "descricao": f"Proposta {p['id_proposta']} em análise há {dias} dias — cobrar o concedente",
                    "base_legal": "acompanhamento da análise (sem prazo legal fixo)",
                    "farol": "acao_imediata" if dias >= 180 else "atencao",
                    "detalhes": {"dias_em_analise": dias, "objeto": (p.get("ds_objeto") or "")[:120]},
                })
        elif "Complementa" in sit:
            marcos.append({
                "cnpj": cnpj, "ente": ente, "fonte": "g2", "instrumento": str(p["id_proposta"]),
                "tipo": "complementacao_pendente", "data_limite": None,
                "descricao": f"Proposta {p['id_proposta']} aguardando COMPLEMENTAÇÃO — responder ao órgão",
                "base_legal": "diligência do concedente (prazo fixado no parecer)",
                "farol": "acao_imediata", "detalhes": {"situacao": sit},
            })
    return marcos


def _marco_defeso(con, cnpj: str, ente: str, hoje: date) -> list[dict]:
    regra = regra_vigente(con, "defeso_eleitoral", "geral", hoje)
    if not regra:
        return []
    fim = date.fromisoformat(regra["valor"]["fim"])
    return [{
        "cnpj": cnpj, "ente": ente, "fonte": "geral", "instrumento": None,
        "tipo": "defeso_eleitoral", "data_limite": fim,
        "descricao": f"Defeso eleitoral vigente até {fim.strftime('%d/%m/%Y')} — novas transferências "
                     "voluntárias vedadas (exceções: obra em andamento c/ cronograma, calamidade)",
        "base_legal": regra["base_legal"], "farol": "atencao",
        "detalhes": regra["valor"],
    }]


def gerar_marcos(hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    snap = snapshot_mais_recente()
    if snap is None:
        raise SystemExit("sem recortes em data/recortes — rode o ingest antes")
    todos: list[dict] = []
    with conectar() as con:
        for sub in sorted(snap.iterdir()):
            cj = sub / "carteira.json"
            if not (sub.is_dir() and cj.exists()):
                continue
            carteira = json.loads(cj.read_text(encoding="utf-8"))
            cnpj = carteira["cnpj"]
            ente = ROTULOS.get(cnpj, carteira.get("nome") or cnpj)
            todos += _marcos_legado(con, cnpj, ente, sub, hoje)
            todos += _marcos_g2(cnpj, ente, sub, hoje)          # ciclo novo: o que serve ao terceiro
            todos += _marcos_especiais(con, cnpj, ente, carteira, hoje)
            todos += _marco_defeso(con, cnpj, ente, hoje)

        for m in todos:
            con.execute(
                """INSERT INTO marcos (cnpj, ente, fonte, instrumento, tipo, data_limite,
                                       descricao, base_legal, farol, detalhes, snapshot)
                   VALUES (%(cnpj)s, %(ente)s, %(fonte)s, %(instrumento)s, %(tipo)s, %(data_limite)s,
                           %(descricao)s, %(base_legal)s, %(farol)s, %(detalhes)s, %(snapshot)s)
                   ON CONFLICT (cnpj, fonte, tipo, COALESCE(instrumento,''),
                                COALESCE(data_limite,'0001-01-01'::date))
                   DO UPDATE SET descricao=EXCLUDED.descricao, base_legal=EXCLUDED.base_legal,
                                 farol=EXCLUDED.farol, detalhes=EXCLUDED.detalhes,
                                 snapshot=EXCLUDED.snapshot, atualizado_em=now()""",
                {**m, "detalhes": json.dumps(m.get("detalhes") or {}, ensure_ascii=False),
                 "snapshot": snap.name},
            )
        con.commit()
        n = con.execute("SELECT count(*) FROM marcos").fetchone()[0]
    return {"snapshot": snap.name, "gerados_ou_atualizados": len(todos), "total_na_base": n}


def gerar_alertas(hoje: date | None = None) -> int:
    """Um alerta por (marco, gatilho); gatilho = balde mais urgente aplicável hoje."""
    hoje = hoje or date.today()
    novos = 0
    with conectar() as con:
        rows = con.execute(
            "SELECT id, ente, tipo, instrumento, descricao, base_legal, data_limite, farol"
            " FROM marcos WHERE farol <> 'ok'"
        ).fetchall()
        for mid, ente, tipo, instr, desc, base, limite, farol in rows:
            # Sem data-limite NÃO implica ação imediata: há marcos de
            # acompanhamento (proposta parada) com farol 'atencao' e sem prazo.
            if limite is None:
                gatilho = "vencido"
                cabeca = "🔴 AÇÃO IMEDIATA" if farol == "acao_imediata" else "🟡 ACOMPANHAR"
            else:
                dias = (limite - hoje).days
                if dias < 0:
                    gatilho, cabeca = "vencido", f"🔴 VENCIDO há {-dias} dia(s)"
                elif dias <= 1:
                    gatilho, cabeca = "T-1", "🟠 VENCE AMANHÃ" if dias == 1 else "🟠 VENCE HOJE"
                elif dias <= 7:
                    gatilho, cabeca = "T-7", f"🟡 vence em {dias} dias"
                elif dias <= 30:
                    gatilho, cabeca = "T-30", f"🟡 vence em {dias} dias"
                else:
                    continue
            msg = (f"{cabeca} — {ente}\n{desc}"
                   + (f"\nLimite: {limite.strftime('%d/%m/%Y')}" if limite else "")
                   + f"\nBase legal: {base}\n— Tuiú (dados oficiais D-1)")
            cur = con.execute(
                "INSERT INTO alertas (marco_id, gatilho, mensagem) VALUES (%s,%s,%s)"
                " ON CONFLICT (marco_id, gatilho) DO NOTHING RETURNING id",
                (mid, gatilho, msg),
            )
            if cur.fetchone():
                novos += 1
        con.commit()
    return novos


def main():
    print("migracoes aplicadas:", migrar() or "nenhuma nova")
    resumo = gerar_marcos()
    print(f"marcos: {resumo['gerados_ou_atualizados']} gerados/atualizados "
          f"(total {resumo['total_na_base']}) do snapshot {resumo['snapshot']}")
    print(f"alertas novos na outbox: {gerar_alertas()}")


if __name__ == "__main__":
    main()
