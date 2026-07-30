"""Mesa de trabalho — o backlog de prestação de contas, priorizado.

Operacionaliza a planilha "Prioridade" do Danilo: cada pendência da carteira
rankeada por FAIXA (0 inadimplência … 8 cobrar o órgão), com responder-até,
próximo passo, a exigência do órgão (quando há) e a última mudança de fase.

Fonte: `marcos` (farol<>ok) + `eventos` (fase) + `clientes` (nome) + `regras_acao`
(próximo passo, editável por admin). A classificação de fase que decide a bola já
vem calibrada pelo admin em `regras_situacao` (via motor).

⚠️ O que a planilha tem e a mesa AINDA não: execução financeira (R$ desembolsado,
saldo a devolver) e % de dossiê documental. Dependem de persistir os valores do
recorte (F2) e de rastrear os documentos (F3) — o front sinaliza isso.
"""

from __future__ import annotations

from datetime import date

from app.carteira import nome_exibicao
from app.db import conectar
from app.notificador import CONSOLE_URL
from app.dossie import percentuais as dossie_percentuais
from app.execucao import por_instrumento
from app.fila import _acoes
from app.parecer import resumo as resumo_parecer
from app.minutas import peca_de
from app.referencias import do_instrumento

# Faixas da mesa — o rank ordena o backlog (0 = mais urgente); o rótulo é o que o
# operador lê. Espelha a taxonomia em camadas da planilha do Danilo, derivada do
# que o motor já sabe: de quem é a bola, o tipo do marco e há quanto venceu.
INADIMPLENCIA_DIAS = 180
ANO_PISO = 2021   # abaixo disso a PC vencida é passivo antigo, não a fila do dia (Danilo, 07/2026)


def _faixa(tipo: str, farol: str, bola: str, dias: int | None, ano_limite: int | None) -> tuple[int, str]:
    if bola == "concedente":
        return (8, "Cobrar o órgão (art. 97)")
    if tipo == "prestacao_contas":
        # PC cujo prazo venceu antes de 2021 é passivo antigo: real, mas é análise
        # de prescrição/baixa, não trabalho do dia — não pode soterrar o acionável.
        if ano_limite is not None and ano_limite < ANO_PISO:
            return (7, "Passivo antigo (pré-2021) — verificar prescrição/baixa")
        if dias is not None and dias <= -INADIMPLENCIA_DIAS:
            return (0, "Inadimplência — PC vencida há +180 dias")
        if farol == "vencido":
            return (1, "PC vencida")
        return (3, "PC a vencer")
    if tipo == "complementacao_pendente":
        return (2, "Complementação exigida — responder")
    if tipo in ("impedimento_pix", "relatorio_gestao_pix", "fim_execucao_pix"):
        return (4, "Transferência especial — regularizar")
    if tipo == "fim_vigencia":
        return (5, "Vigência encerrando")
    if farol == "acao_imediata":
        return (2, "Ação imediata")
    if farol == "vencido":
        return (1, "Vencido")
    return (6, "Acompanhar")


def _ultima_fase(con) -> dict[str, dict]:
    """Última mudança de andamento por cliente — o "log de fases" da planilha,
    condensado na linha mais recente."""
    out: dict[str, dict] = {}
    for cnpj, rotulo, de, para, snap in con.execute(
            "SELECT DISTINCT ON (cnpj) cnpj, rotulo, de, para, snapshot::text"
            " FROM eventos ORDER BY cnpj, id DESC"):
        out[cnpj] = {"rotulo": rotulo, "transicao": (f"{de} → {para}" if de else (para or "")),
                     "quando": snap}
    return out


def _refs(cnpj: str, instrumento) -> list[dict]:
    try:
        return do_instrumento(cnpj, instrumento) if instrumento else []
    except Exception:  # noqa: BLE001 — referência é enriquecimento
        return []


def montar(cliente: str | None = None) -> dict:
    hoje = date.today()
    with conectar() as con:
        clientes = {r[0]: (r[1] or r[2]) for r in con.execute(
            "SELECT doc, apelido, nome FROM clientes WHERE ativo")}
        acoes = _acoes(con)
        fases = _ultima_fase(con)
        try:
            execucao = por_instrumento(con, hoje)     # financeiros por convênio (F2)
        except Exception:  # noqa: BLE001 — tabela ainda não migrada: mesa segue sem dinheiro
            con.rollback()
            execucao = {}
        try:
            dossies = dossie_percentuais(con)         # % de dossiê por convênio (F3)
        except Exception:  # noqa: BLE001
            con.rollback()
            dossies = {}
        status = {r[0]: r[1] for r in con.execute("SELECT chave, status FROM fila_status")}

        sql = ("SELECT cnpj, tipo, instrumento, data_limite, descricao, base_legal, farol, detalhes"
               " FROM marcos WHERE farol <> 'ok'")
        args: tuple = ()
        if cliente:
            sql += " AND cnpj = %s"
            args = (cliente,)

        itens = []
        for cnpj, tipo, instr, limite, desc, base, farol, det in con.execute(sql, args):
            if cnpj not in clientes:          # a mesa é da carteira de CLIENTES
                continue
            d = det or {}
            bola = d.get("bola_com", "convenente")
            dias = (limite - hoje).days if limite else None
            rank, faixa = _faixa(tipo, farol, bola, dias, limite.year if limite else None)
            chave = f"prazo:{cnpj}:{tipo}:{instr or '-'}:{limite or '-'}"   # mesma chave da fila: triagem sincroniza
            ultimo = d.get("ultimo_parecer")
            exig = (ultimo.get("parecer") if isinstance(ultimo, dict) else None) or ""
            itens.append({
                "chave": chave, "status": status.get(chave, "aberto"),
                # nome_exibicao, não `clientes.get` cru: é o furo que o docstring
                # dele adverte — quem resolve o nome por fora perde o rótulo à mão
                # e a correção ortográfica, e a mesa mostrava CAIXA ALTA sem acento
                "cnpj": cnpj, "cliente": nome_exibicao(cnpj, clientes.get(cnpj), clientes),
                "instrumento": instr, "situacao": d.get("situacao") or "",
                "rank": rank, "faixa": faixa, "farol": farol, "bola": bola,
                "responder_ate": limite.isoformat() if limite else None, "dias": dias,
                "tipo": tipo, "descricao": desc, "base_legal": base,
                "proximo_passo": acoes.get(tipo, "Analisar"),
                # resumo, não prefixo: pedido + prazo + consequência, que é a
                # ordem em que o operador decide (ver app.parecer)
                "exigencia": (resumo_parecer(exig, 400) if exig.strip() else None),
                "ultima_fase": fases.get(cnpj),
                "execucao": execucao.get((cnpj, instr)),   # R$ do convênio (None se g2/sem dado)
                # % de dossiê só faz sentido em item com convênio e que peça PC
                "dossie": dossies.get((cnpj, instr)) if instr and tipo in (
                    "prestacao_contas", "complementacao_pendente") else None,
                "tem_dossie": bool(instr and tipo in ("prestacao_contas", "complementacao_pendente")),
                # a peça pronta do item: o operador chega no rascunho, não na
                # tarefa em branco (ver minutas.PECA_POR_MARCO)
                "peca": peca_de(tipo, cnpj, instr, CONSOLE_URL),
                # caminhos até o documento (SEI, DOU) — o link do SEI exige
                # captcha e vem rotulado como tal; ver app.referencias
                "referencias": _refs(cnpj, instr),
            })

    abertos = [i for i in itens if i["status"] in ("aberto", "em_andamento")]
    abertos.sort(key=lambda i: (i["rank"], i["dias"] if i["dias"] is not None else 99999))
    resumo: list[dict] = []
    vistos: dict[str, dict] = {}
    for i in abertos:
        r = vistos.get(i["faixa"])
        if r is None:
            r = {"faixa": i["faixa"], "rank": i["rank"], "n": 0}
            vistos[i["faixa"]] = r
            resumo.append(r)
        r["n"] += 1
    resumo.sort(key=lambda x: x["rank"])
    # dinheiro em jogo no backlog aberto (só convênios distintos, para não somar
    # o mesmo instrumento duas vezes quando gera mais de um marco)
    vistos_conv: set = set()
    a_devolver = desembolsado = 0.0
    for i in abertos:
        ex, ch = i.get("execucao"), (i["cnpj"], i["instrumento"])
        if ex and ch not in vistos_conv:
            vistos_conv.add(ch)
            a_devolver += ex.get("vl_saldo_devolver") or 0.0
            desembolsado += ex.get("vl_desembolsado") or 0.0
    return {"total": len(abertos), "resumo": resumo, "itens": abertos,
            "clientes": len({i["cnpj"] for i in abertos}),
            "dinheiro": {"a_devolver": round(a_devolver, 2), "desembolsado": round(desembolsado, 2),
                         "convenios_com_valor": len(vistos_conv)},
            "gerado_em": hoje.isoformat()}
