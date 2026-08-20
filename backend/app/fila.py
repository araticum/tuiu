"""Fila de trabalho do OPERADOR — o que fazer hoje, por cliente.

O Tuiú é o console com que a casa opera o Transferegov de terceiros que
receberam verba pública. Esta é a tela-mãe do operador: uma fila única,
consolidada de todas as fontes, ordenada por urgência, com o **próximo passo**
explícito e a base legal do porquê.

Fontes da fila:
  - `marcos`         prazos (prestação de contas, vigência, impedimento, defeso)
  - `eventos`        mudanças de andamento e recados do inbox ainda não tratados
  - `regularidade`   impedimento em CEPIM/CEIS/CNEP (trava celebrar/receber)

Cada item tem `chave` determinística → o operador triaga (aberto → em_andamento
→ resolvido) e a marcação sobrevive à recarga diária.
"""

from __future__ import annotations

import json
from datetime import date

from app.carteira import ROTULOS, snapshot_mais_recente
from app.db import conectar

PESO_URGENCIA = {"acao_imediata": 0, "vencido": 1, "atencao": 2, "ok": 3}

PROXIMO_PASSO = {
    "prestacao_contas": "Montar e enviar a prestação de contas no Transferegov",
    "fim_vigencia": "Decidir: concluir o objeto, pedir aditivo de prazo ou encerrar",
    "impedimento_pix": "Regularizar o plano de ação impedido junto ao órgão",
    "relatorio_gestao_pix": "Preencher e enviar o Relatório de Gestão",
    "fim_execucao_pix": "Concluir a execução pactuada e reunir comprovação",
    "defeso_eleitoral": "Não celebrar nova transferência voluntária na janela",
    "impedimento_cadastro": "Sanar a pendência que gerou o impedimento e pedir baixa",
    "andamento": "Ler a mudança e decidir a ação (o órgão mexeu no instrumento)",
    # ciclo novo (g2) — o que mais aparece na carteira de terceiros
    "proposta_parada": "Cobrar o concedente (art. 97) sobre a análise parada",
    "complementacao_pendente": "Responder a complementação exigida pelo órgão",
    "etapa_cronograma": "Executar/comprovar a etapa do cronograma físico",
    "parcela_prevista": "Conferir se a parcela foi liberada; cobrar se não saiu",
    # o prazo estourado aqui e do ORGAO — a acao e cobrar, nao produzir
    "analise_parada_concedente": "Cobrar decisão do concedente (art. 97) sobre as prestações paradas",
    "proposta_rejeitada": "Ler o parecer do órgão e decidir: corrigir e reapresentar, ou encerrar",
    # marco `ok` — a prestação está entregue e a bola é do órgão. Não aparecia na
    # fila (que só lê farol<>'ok'), mas ENTRA na mensagem de andamento, e sem
    # esta linha o alerta dizia "Próximo passo: Analisar" para quem não tem nada
    # a fazer. Nada a produzir aqui: o passo é vigiar o relógio do art. 97.
    "prestacao_em_analise": "Nada a enviar — acompanhar a análise e cobrar o órgão se passar de 60 dias (art. 97)",
}


def _clientes(con) -> dict[str, dict]:
    return {r[0]: {"doc": r[0], "nome": r[1], "apelido": r[2], "operador": r[3], "ativo": r[4]}
            for r in con.execute("SELECT doc, nome, apelido, operador, ativo FROM clientes")}


def _acoes(con) -> dict[str, str]:
    """Próximo passo por tipo de marco, EDITÁVEL POR ADMIN (regras_acao) sobre o
    padrão embutido. Sem tabela/banco, cai no dicionário PROXIMO_PASSO."""
    acoes = dict(PROXIMO_PASSO)
    try:
        for tipo, passo in con.execute("SELECT tipo, proximo_passo FROM regras_acao"):
            if passo:
                acoes[tipo] = passo
    except Exception:  # noqa: BLE001 — tabela ainda não migrada: usa o embutido
        pass
    return acoes


def montar(apenas_abertos: bool = True, cliente: str | None = None,
           apenas_clientes: bool = True) -> dict:
    """Console do operador: por padrão mostra só a carteira de CLIENTES
    (terceiros que a casa opera). `apenas_clientes=False` inclui contrapartes."""
    hoje = date.today()
    itens: list[dict] = []

    with conectar() as con:
        clientes = _clientes(con)
        acoes = _acoes(con)
        status = {r[0]: {"status": r[1], "nota": r[2], "operador": r[3]}
                  for r in con.execute("SELECT chave, status, nota, operador FROM fila_status")}

        # 1) prazos
        sql = ("SELECT cnpj, ente, tipo, instrumento, data_limite, descricao, base_legal, farol"
               " FROM marcos WHERE farol <> 'ok'")
        args: tuple = ()
        if cliente:
            sql += " AND cnpj = %s"
            args = (cliente,)
        for cnpj, ente, tipo, instr, limite, desc, base, farol in con.execute(sql, args):
            chave = f"prazo:{cnpj}:{tipo}:{instr or '-'}:{limite or '-'}"
            itens.append({
                "chave": chave, "origem": "prazo", "cliente": cnpj,
                "cliente_nome": (clientes.get(cnpj) or {}).get("apelido")
                                or (clientes.get(cnpj) or {}).get("nome") or ROTULOS.get(cnpj, cnpj),
                "e_cliente": cnpj in clientes,
                "urgencia": farol, "tipo": tipo, "referencia": instr,
                "prazo": limite.isoformat() if limite else None,
                "dias": (limite - hoje).days if limite else None,
                "descricao": desc, "base_legal": base,
                "proximo_passo": acoes.get(tipo, "Analisar"),
            })

        # 2) andamento não tratado
        sql = ("SELECT id, cnpj, ente, rotulo, tipo, de, para, origem, snapshot::text FROM eventos")
        args = ()
        if cliente:
            sql += " WHERE cnpj = %s"
            args = (cliente,)
        sql += " ORDER BY id DESC LIMIT 200"
        for eid, cnpj, ente, rotulo, tipo, de, para, origem, snap in con.execute(sql, args):
            transicao = f"{de} → {para}" if de else (para or "")
            itens.append({
                "chave": f"andamento:{cnpj}:{eid}", "origem": "andamento", "cliente": cnpj,
                "cliente_nome": (clientes.get(cnpj) or {}).get("apelido")
                                or (clientes.get(cnpj) or {}).get("nome") or ROTULOS.get(cnpj, cnpj),
                "e_cliente": cnpj in clientes,
                "urgencia": "atencao" if origem == "inbox" else "ok",
                "tipo": "andamento", "referencia": rotulo,
                "prazo": None, "dias": None,
                "descricao": f"{rotulo}: {transicao}".strip(": "),
                "base_legal": "andamento no Transferegov" + (" (e-mail do órgão)" if origem == "inbox" else " (dados abertos D-1)"),
                "proximo_passo": acoes.get("andamento", "Analisar"),
            })

    # 3) impedimento nos cadastros (lê o artefato do recorte)
    snap = snapshot_mais_recente()
    if snap:
        for sub in sorted(snap.iterdir()):
            reg = sub / "regularidade.json"
            if not (sub.is_dir() and reg.exists()):
                continue
            r = json.loads(reg.read_text(encoding="utf-8"))
            if not r.get("impedido"):
                continue
            cnpj = r.get("cnpj", sub.name)
            if cliente and cnpj != cliente:
                continue
            fontes = ", ".join(f"{k.upper()} ({v['registros']})"
                               for k, v in (r.get("fontes") or {}).items() if v.get("registros"))
            itens.append({
                "chave": f"impedimento:{cnpj}", "origem": "regularidade", "cliente": cnpj,
                "cliente_nome": ROTULOS.get(cnpj, cnpj), "e_cliente": True,
                "urgencia": "acao_imediata", "tipo": "impedimento_cadastro",
                "referencia": fontes, "prazo": None, "dias": None,
                "descricao": f"Cliente IMPEDIDO em {fontes}", "base_legal": r.get("base_legal", ""),
                "proximo_passo": acoes.get("impedimento_cadastro", "Analisar"),
            })

    for it in itens:
        st = status.get(it["chave"]) or {}
        it["status"] = st.get("status", "aberto")
        it["nota"] = st.get("nota")
        it["operador"] = st.get("operador")

    if apenas_clientes:
        itens = [i for i in itens if i["e_cliente"]]

    # Marca quando cada item apareceu — é o relógio que permite medir tempo de
    # resolução (fila_status só guarda a última mexida). Registra DEPOIS do
    # filtro de clientes (contraparte não é trabalho da casa e contaminaria a
    # métrica) e ANTES do filtro de abertos (item resolvido continua contando
    # para o histórico). Idempotente: só a primeira aparição conta.
    if itens:
        try:
            with conectar() as con:
                for it in itens:
                    con.execute(
                        "INSERT INTO fila_visto (chave, cliente, tipo, urgencia)"
                        " VALUES (%s,%s,%s,%s)"
                        " ON CONFLICT (chave) DO UPDATE SET ultima_vez=now(),"
                        " urgencia=EXCLUDED.urgencia",
                        (it["chave"], it["cliente"], it["tipo"], it["urgencia"]))
                con.commit()
        except Exception:  # noqa: BLE001 — medir não pode derrubar a fila
            pass

    if apenas_abertos:
        itens = [i for i in itens if i["status"] in ("aberto", "em_andamento")]

    itens.sort(key=lambda i: (PESO_URGENCIA.get(i["urgencia"], 9),
                              i["dias"] if i["dias"] is not None else 9999))

    por_cliente: dict[str, int] = {}
    for i in itens:
        por_cliente[i["cliente_nome"]] = por_cliente.get(i["cliente_nome"], 0) + 1

    return {
        "total": len(itens),
        "por_urgencia": {u: sum(1 for i in itens if i["urgencia"] == u)
                         for u in ("acao_imediata", "vencido", "atencao", "ok")},
        "por_cliente": dict(sorted(por_cliente.items(), key=lambda x: -x[1])),
        "itens": itens[:300],
    }


def triar(chave: str, status: str, nota: str | None = None, operador: str | None = None) -> dict:
    if status not in ("aberto", "em_andamento", "resolvido", "ignorado"):
        return {"ok": False, "erro": "status inválido"}
    with conectar() as con:
        con.execute(
            "INSERT INTO fila_status (chave, status, nota, operador) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (chave) DO UPDATE SET status=EXCLUDED.status, nota=EXCLUDED.nota,"
            " operador=EXCLUDED.operador, atualizado_em=now()",
            (chave, status, nota, operador))
        con.commit()
    return {"ok": True, "chave": chave, "status": status}


def responsaveis() -> list[dict]:
    """Quem pode receber item: usuário ativo do console, e mais ninguém.

    Atribuir para texto livre criaria dono fantasma — item que parece coberto e
    não está é pior que item sem dono, porque ninguém procura por ele.
    """
    with conectar() as con:
        return [{"login": lg, "nome": nm} for lg, nm in con.execute(
            "SELECT login, nome FROM usuarios WHERE ativo ORDER BY nome")]


def atribuir(chave: str, responsavel: str | None, quem: str | None = None) -> dict:
    """Diz DE QUEM é o item. `responsavel=None` devolve para a mesa.

    Não encosta em `status`: atribuir não é começar a trabalhar. Marcar
    `em_andamento` aqui mentiria sobre o andamento de tudo que foi só
    distribuído — e a mesa perderia a distinção entre "tem dono" e "está
    andando", que é justamente o que se quer enxergar.
    """
    if not chave:
        return {"ok": False, "erro": "chave ausente"}
    if responsavel:
        validos = {r["login"] for r in responsaveis()}
        if responsavel not in validos:
            return {"ok": False, "erro": f"'{responsavel}' não é usuário ativo do console"}
    with conectar() as con:
        con.execute(
            "INSERT INTO fila_status (chave, responsavel, atribuido_em, atribuido_por)"
            " VALUES (%s,%s,now(),%s)"
            " ON CONFLICT (chave) DO UPDATE SET responsavel=EXCLUDED.responsavel,"
            " atribuido_em=now(), atribuido_por=EXCLUDED.atribuido_por",
            (chave, responsavel, quem))
        con.commit()
    return {"ok": True, "chave": chave, "responsavel": responsavel}
