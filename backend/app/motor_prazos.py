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
import unicodedata
from datetime import date, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.carteira import ROTULOS, docs_ativos, snapshot_mais_recente  # noqa: E402
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


def _marcos_legado(con, cnpj: str, ente: str, dir_cnpj: Path, hoje: date,
                   regras: dict | None = None) -> list[dict]:
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
            situacao = (row.get("SIT_CONVENIO") or "").strip()
            fase = _fase_prestacao(situacao, regras)
            # Sem fase de prestação (plano/assinatura ou situação em branco) NÃO
            # há marco: o limite herdado do detru ali não é trabalho de ninguém.
            if limite_pc and fase:
                com_o_cliente = fase == "convenente"
                marcos.append({
                    "cnpj": cnpj, "ente": ente, "fonte": "legado", "instrumento": nr,
                    "tipo": "prestacao_contas" if com_o_cliente else "prestacao_em_analise",
                    "data_limite": limite_pc,
                    "descricao": (f"Prestação de contas do {nr} ({situacao})" if com_o_cliente else
                                  f"Prestação do {nr} já entregue — {situacao.lower()}"),
                    "base_legal": base_pc,
                    # prazo vencido só acusa quem PODE agir; com a prestação
                    # entregue, o atraso é da análise, não do convenente
                    "farol": _farol(limite_pc, hoje) if com_o_cliente else "ok",
                    "detalhes": {"regime": regime, "fim_vigencia": row.get("DIA_FIM_VIGENC_CONV"),
                                 "situacao": situacao, "bola_com": fase},
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


ANALISE_DO_CONCEDENTE = ("PRESTACAO_CONTAS_ENVIADA_ANALISE", "PRESTACAO_CONTAS_EM_ANALISE")


def _marco_analise_parada(con, cnpj: str, ente: str, dir_cnpj: Path, hoje: date) -> list[dict]:
    """O outro lado do prazo: quando a prestação já foi entregue, o art. 97 passa
    a correr contra o CONCEDENTE (60 dias informatizado, 180 convencional).

    Medido na carteira de 50: de 1.004 prestações paradas na análise, 953 (95%)
    já estouraram o prazo do governo — a mais antiga há 4.878 dias. É o inverso
    do que o motor dizia antes de hoje, quando acusava atraso do cliente.

    Sai UM marco por cliente, não um por instrumento: 817 itens não são fila de
    trabalho, são fato de carteira. O operador recebe uma tarefa — cobrar — e o
    detalhe fica em `detalhes`.

    O corte é o prazo CONVENCIONAL (o maior), porque o dado não diz qual
    modalidade de análise se aplica. Acusar o governo de atraso pede o limite
    mais conservador.
    """
    hist = dir_cnpj / "legado" / "historico_situacao.csv"
    if not hist.exists():
        return []
    regra = regra_vigente(con, "prazo_analise_convencional", "completo_pc33", hoje)
    limite = int((regra or {}).get("valor", {}).get("dias") or 180)
    base = (regra or {}).get("base_legal", "PC 33/2023, art. 97")

    paradas = []
    with open(hist, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            if (row.get("HISTORICO_SIT") or "").strip() not in ANALISE_DO_CONCEDENTE:
                continue
            try:
                dias = int(row.get("DIAS_HISTORICO_SIT") or 0)
            except ValueError:
                continue
            if dias > limite:
                paradas.append({"instrumento": row.get("NR_CONVENIO"), "dias": dias,
                                "desde": row.get("DIA_HISTORICO_SIT"),
                                "situacao": row.get("HISTORICO_SIT")})
    if not paradas:
        return []

    paradas.sort(key=lambda p: -p["dias"])
    pior = paradas[0]
    alem_da_prorrogacao = [p for p in paradas if p["dias"] > limite * 2]
    return [{
        "cnpj": cnpj, "ente": ente, "fonte": "legado", "instrumento": None,
        "tipo": "analise_parada_concedente", "data_limite": None,
        "descricao": (f"{len(paradas)} prestação(ões) entregues e paradas na análise do concedente "
                      f"há mais de {limite} dias — a pior há {pior['dias']} dias "
                      f"(instrumento {pior['instrumento']}, desde {pior['desde']})"),
        "base_legal": f"{base} — o prazo de análise é do órgão, não do convenente",
        "farol": "atencao",
        "detalhes": {"limite_dias": limite, "total": len(paradas), "bola_com": "concedente",
                     "alem_da_prorrogacao": len(alem_da_prorrogacao),
                     "piores": paradas[:10]},
    }]


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


def _marcos_g2(cnpj: str, ente: str, sub: Path, hoje: date, con=None) -> list[dict]:
    """Prazos do CICLO NOVO (g2) — a fonte que importa para o TERCEIRO EXECUTOR,
    que normalmente não tem estoque no detru nem transferência especial.

    `con` é opcional: com ele, a proposta parada cita o art. 97 pela REGRA
    VIGENTE (versionada); sem ele (testes de unidade sem banco), cai num fallback
    com o mesmo prazo. O resto dos marcos não depende de regra."""
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
            # liberar a parcela é do concedente: parcela atrasada é cobrança, não agir-agora
            "detalhes": {"proposta": p.get("id_proposta"), "situacao": p.get("situacao_proposta"),
                         "bola_com": "concedente"},
        })

    # Último parecer de cada proposta. O arquivo `analise-proposta` é coletado
    # desde sempre e nunca era lido — e é o órgão dizendo POR ESCRITO o que
    # exigiu. Sem ele, "cobrar o concedente" é um pedido no escuro; com ele, o
    # operador sabe o que foi pedido antes de a análise parar.
    pareceres: dict[str, dict] = {}
    for a in _linhas_gz(sub / "parcerias" / "analise-proposta.jsonl.gz"):
        idp = str(a.get("id_proposta"))
        quando = str(a.get("dh_analise_proposta") or "")
        if idp not in pareceres or quando > pareceres[idp]["quando"]:
            pareceres[idp] = {
                "quando": quando,
                "resultado": a.get("in_resultado_analise"),
                "fase": a.get("in_fase_analise"),
                # INTEIRO, não os primeiros 600: todo corte era pelo começo, e
                # o que sumia era o fim — onde mora a consequência ("resultará
                # no arquivamento"). Quem exibe decide o tamanho, com o resumo
                # de `app.parecer`, que corta pelo que importa e não pela ordem.
                "parecer": (a.get("ds_parecer") or "").strip(),
            }

    # 3) Proposta parada em análise: agora com os DENTES do art. 97. O prazo do
    #    concedente é LEGAL, não "acompanhamento". Transferegov é informatizado,
    #    então o limite aplicável é o de 60 dias (art. 97, I). Passou disso, o
    #    atraso é do órgão e vira alavanca de cobrança — com o artigo na mão.
    #    Escala para ação imediata só além do prazo convencional (180d), quando
    #    a análise está claramente abandonada sob qualquer leitura.
    regra_inf = regra_vigente(con, "prazo_analise_informatizado", "completo_pc33", hoje) if con else None
    limite_inf = int((regra_inf or {}).get("valor", {}).get("dias") or 60)
    base_inf = (regra_inf or {}).get("base_legal") or "PC 33/2023, art. 97, I e §1º"
    regra_conv = regra_vigente(con, "prazo_analise_convencional", "completo_pc33", hoje) if con else None
    limite_conv = int((regra_conv or {}).get("valor", {}).get("dias") or 180)
    for p in props.values():
        sit = str(p.get("situacao_proposta") or "")
        if "Análise" in sit or "Analise" in sit:
            try:
                envio = date.fromisoformat(str(p.get("dt_envio_analise"))[:10])
                dias = (hoje - envio).days
            except (ValueError, TypeError):
                continue
            if dias >= limite_inf:
                ultimo = pareceres.get(str(p["id_proposta"]))
                vencido_ha = dias - limite_inf
                marcos.append({
                    "cnpj": cnpj, "ente": ente, "fonte": "g2", "instrumento": str(p["id_proposta"]),
                    "tipo": "proposta_parada", "data_limite": None,
                    "descricao": (f"Proposta {p['id_proposta']} em análise há {dias} dias — "
                                  f"art. 97 ({limite_inf}d informatizado) vencido há {vencido_ha} dias; "
                                  f"cobrar o concedente"
                                  + (f" (último parecer: {ultimo['resultado']} na fase "
                                     f"{ultimo['fase']})" if ultimo else "")),
                    "base_legal": f"{base_inf} — o prazo de análise é do concedente, não do proponente",
                    # a bola é do ÓRGÃO: cobrar é acompanhamento, não "agir agora"
                    # (Danilo, 07/2026). Fica em 'atencao' por mais parada que esteja.
                    "farol": "atencao",
                    "detalhes": {"dias_em_analise": dias, "limite_informatizado": limite_inf,
                                 "limite_convencional": limite_conv, "bola_com": "concedente",
                                 "vencido_ha_dias": vencido_ha, "objeto": (p.get("ds_objeto") or "")[:120],
                                 "ultimo_parecer": ultimo},
                })
        elif "Complementa" in sit:
            ultimo = pareceres.get(str(p["id_proposta"]))
            marcos.append({
                "cnpj": cnpj, "ente": ente, "fonte": "g2", "instrumento": str(p["id_proposta"]),
                "tipo": "complementacao_pendente", "data_limite": None,
                "descricao": (f"Proposta {p['id_proposta']} aguardando COMPLEMENTAÇÃO — responder ao órgão"
                              + (f". Parecer: {ultimo['parecer'][:180]}" if ultimo and ultimo["parecer"] else "")),
                "base_legal": "diligência do concedente (prazo fixado no parecer)",
                "farol": "acao_imediata",
                "detalhes": {"situacao": sit, "ultimo_parecer": ultimo},
            })
        elif "Rejeitada" in sit or "Reprovada" in sit:
            # Rejeitada não gerava marco nenhum: a proposta morria em silêncio.
            # Com o parecer em mãos dá para dizer POR QUE, e a decisão de
            # reapresentar deixa de ser adivinhação.
            ultimo = pareceres.get(str(p["id_proposta"]))
            marcos.append({
                "cnpj": cnpj, "ente": ente, "fonte": "g2", "instrumento": str(p["id_proposta"]),
                "tipo": "proposta_rejeitada", "data_limite": None,
                "descricao": (f"Proposta {p['id_proposta']} REJEITADA — avaliar se reapresenta"
                              + (f". Motivo do órgão: {ultimo['parecer'][:200]}"
                                 if ultimo and ultimo["parecer"] else " (sem parecer publicado)")),
                "base_legal": "parecer de análise do concedente (Transferegov)",
                # não é prazo correndo: é decisão a tomar, e sem data não pode
                # entrar como "ação imediata" ao lado do que vence amanhã
                "farol": "atencao",
                "detalhes": {"situacao": sit, "objeto": (p.get("ds_objeto") or "")[:120],
                             "ultimo_parecer": ultimo},
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


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower().strip()


# Classificação da fase de prestação de contas pela SIT_CONVENIO do detru.
# É ALLOWLIST, não blocklist: fora das listas conhecidas NÃO se inventa prazo de
# prestação. A blocklist antiga (default "cobrar") transformava plano recém
# aprovado (94), situação em branco (79) e complementação de PLANO em análise
# (7) em "prestação vencida" — 181 de 294 alarmes vermelhos eram falsos na
# carteira de 50 (feedback do Danilo, especialista, 07/2026).
_PC_CONVENENTE = (            # o cliente ainda tem ação de prestação pendente
    "em execucao",           # executando: prazo se aproximando é aviso legítimo
    "aguardando prestacao de contas",
    "prestacao de contas em complementacao",
    "prestacao de contas iniciada por antecipacao",
)
_PC_CONCEDENTE = (           # prestação entregue: a bola está com o órgão
    "prestacao de contas enviada",
    "prestacao de contas em analise",
    "prestacao de contas comprovada",
    "prestacao de contas aprovada",
    "prestacao de contas arquivada",
)


def carregar_regras_situacao(con=None) -> dict:
    """Regras de classificação da situação, EDITÁVEIS POR ADMIN (regras_situacao).

    Fallback para as listas embutidas se a tabela estiver vazia/ausente/sem banco
    — o motor nunca fica sem classificar (nem os testes de unidade)."""
    base = {"convenente": list(_PC_CONVENENTE), "concedente": list(_PC_CONCEDENTE), "ignorar": []}
    if con is None:
        return base
    try:
        rows = con.execute("SELECT fase, padrao FROM regras_situacao WHERE ativo").fetchall()
    except Exception:  # noqa: BLE001 — tabela ainda não migrada: usa o embutido
        return base
    if not rows:
        return base
    out = {"convenente": [], "concedente": [], "ignorar": []}
    for fase, padrao in rows:
        out.setdefault(fase, []).append(_sem_acento(padrao))
    return out


def _fase_prestacao(situacao: str | None, regras: dict | None = None) -> str | None:
    """De quem é a bola da prestação de contas — ou None quando não há prestação
    em cena (ainda em plano/assinatura, ou situação em branco).

    Precedência: ignorar (silêncio explícito do admin) > convenente > concedente.
    None é deliberado: convênio que nem saiu da fase de plano herda um
    DIA_LIMITE_PREST_CONTAS antigo que não é trabalho de ninguém hoje — emitir
    marco vencido ali era a origem do alarme falso que corrói a confiança."""
    r = regras or {"convenente": _PC_CONVENENTE, "concedente": _PC_CONCEDENTE, "ignorar": ()}
    s = _sem_acento(situacao)
    if any(t in s for t in r.get("ignorar", ())):
        return None
    if any(t in s for t in r.get("convenente", ())):
        return "convenente"
    if any(t in s for t in r.get("concedente", ())):
        return "concedente"
    return None


def gerar_marcos(hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    snap = snapshot_mais_recente()
    if snap is None:
        raise SystemExit("sem recortes em data/recortes — rode o ingest antes")
    todos: list[dict] = []
    with conectar() as con:
        # Recorte no disco NÃO é carteira: quem sai de `clientes` (desativado,
        # trocado) deixa o diretório para trás e continuaria gerando marco e
        # alerta para sempre — fila do operador cheia de quem não é cliente.
        ativos = docs_ativos()
        regras_sit = carregar_regras_situacao(con)   # classificação editável por admin, 1 leitura por rodada
        ignorados = 0
        for sub in sorted(snap.iterdir()):
            cj = sub / "carteira.json"
            if not (sub.is_dir() and cj.exists()):
                continue
            carteira = json.loads(cj.read_text(encoding="utf-8"))
            cnpj = carteira["cnpj"]
            if ativos and cnpj not in ativos:
                ignorados += 1
                continue
            ente = ROTULOS.get(cnpj, carteira.get("nome") or cnpj)
            todos += _marcos_legado(con, cnpj, ente, sub, hoje, regras_sit)
            todos += _marco_analise_parada(con, cnpj, ente, sub, hoje)
            todos += _marcos_g2(cnpj, ente, sub, hoje, con)     # ciclo novo: o que serve ao terceiro
            todos += _marcos_especiais(con, cnpj, ente, carteira, hoje)
            todos += _marco_defeso(con, cnpj, ente, hoje)

        # marcador da rodada: tudo que não for tocado depois disto é lixo.
        # clock_timestamp() avança dentro da transação; now() não.
        inicio = con.execute("SELECT clock_timestamp()").fetchone()[0]

        for m in todos:
            con.execute(
                """INSERT INTO marcos (cnpj, ente, fonte, instrumento, tipo, data_limite,
                                       descricao, base_legal, farol, detalhes, snapshot, atualizado_em)
                   VALUES (%(cnpj)s, %(ente)s, %(fonte)s, %(instrumento)s, %(tipo)s, %(data_limite)s,
                           %(descricao)s, %(base_legal)s, %(farol)s, %(detalhes)s, %(snapshot)s,
                           clock_timestamp())
                   ON CONFLICT (cnpj, fonte, tipo, COALESCE(instrumento,''),
                                COALESCE(data_limite,'0001-01-01'::date))
                   DO UPDATE SET descricao=EXCLUDED.descricao, base_legal=EXCLUDED.base_legal,
                                 farol=EXCLUDED.farol, detalhes=EXCLUDED.detalhes,
                                 snapshot=EXCLUDED.snapshot, atualizado_em=clock_timestamp()""",
                {**m, "detalhes": json.dumps(m.get("detalhes") or {}, ensure_ascii=False),
                 "snapshot": snap.name},
            )
        # A base espelha ESTA rodada. Duas fontes de lixo, ambas reais:
        #  - cliente que saiu da carteira, senão seus marcos sobrevivem ao
        #    desligamento e seguem alimentando alerta e fila;
        #  - marco não regerado agora (instrumento sumiu do recorte, ou mudou de
        #    tipo — foi o caso da prestação entregue, que deixou de ser
        #    `prestacao_contas` e virou `prestacao_em_analise`: o upsert não casa
        #    tipo diferente, então a linha "vencida" antiga conviveria com a nova).
        #
        # O corte é por `atualizado_em`, NÃO por `snapshot`: snapshot é a data do
        # recorte, e duas rodadas no mesmo dia compartilham o valor — foi assim
        # que 1.027 duplicatas sobreviveram à primeira tentativa de limpeza.
        # `clock_timestamp()` (e não `now()`) porque now() é o início da
        # transação e seria igual ao marcador, não maior.
        removidos = con.execute(
            "DELETE FROM marcos WHERE atualizado_em < %s"
            + (" OR NOT (cnpj = ANY(%s))" if ativos else ""),
            (inicio, list(ativos)) if ativos else (inicio,)).rowcount
        con.commit()
        n = con.execute("SELECT count(*) FROM marcos").fetchone()[0]
    return {"snapshot": snap.name, "gerados_ou_atualizados": len(todos),
            "total_na_base": n, "recortes_fora_da_carteira": ignorados,
            "marcos_removidos": removidos}


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
    if resumo.get("recortes_fora_da_carteira") or resumo.get("marcos_removidos"):
        print(f"fora da carteira: {resumo['recortes_fora_da_carteira']} recorte(s) ignorado(s), "
              f"{resumo['marcos_removidos']} marco(s) removido(s)")
    print(f"marcos: {resumo['gerados_ou_atualizados']} gerados/atualizados "
          f"(total {resumo['total_na_base']}) do snapshot {resumo['snapshot']}")
    print(f"alertas novos na outbox: {gerar_alertas()}")


if __name__ == "__main__":
    main()
