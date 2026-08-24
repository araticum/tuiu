"""Distribuição da fila sem dono, por cota ajustável.

Pedido do dono (24/08/2026): distribuir todos os processos sem responsável, com
possibilidade de ajustar a porcentagem de cada um dos responsáveis cadastrados.

## O que se distribui, e o que não se toca

Só item **sem dono**. Quem já tem responsável fica onde está — tirar da mão de
alguém que já começou é reequilíbrio, problema diferente, e fazer isso por
acidente numa rotina automática destrói a confiança na mesa.

A cota é do LOTE sem dono, não da carteira inteira. `carga_atual()` mostra o que
cada um já tem para a cota ser decidida com o quadro à vista, mas o cálculo não
tenta compensar sozinho: compensação silenciosa surpreende, e surpresa em
distribuição de trabalho vira conflito entre pessoas.

## Três decisões de algoritmo

**Maior resto (quota de Hare), não arredondamento.** Com 5 pessoas e 278 itens,
arredondar cada fatia perde ou inventa item. O maior resto distribui a sobra
para quem ficou com a maior fração cortada, e a soma fecha exatamente.

**Agrupar por cliente, por padrão.** Um convênio raramente vem sozinho: o mesmo
cliente tem dossiê, histórico e interlocutor. Espalhar os itens de um cliente
entre cinco pessoas obriga cinco pessoas a aprender o mesmo cliente. Agrupado, o
percentual é respeitado tão de perto quanto os tamanhos de cliente permitem — e
o desvio é RELATADO, não escondido.

**Distribuir intercalando por urgência.** Ordenar por urgência e cortar em
blocos daria todos os casos piores para quem tem a primeira fatia. A distribuição
percorre a fila do mais urgente para o menos e entrega ao operador que está mais
longe da própria cota — assim cada um recebe uma mistura parecida de gravidade.

## Determinismo

Mesma entrada, mesma saída, sempre. Nada de sorteio: distribuição que muda entre
duas execuções não é conferível, e "por que este item é meu?" precisa ter
resposta. Empate se resolve por chave estável (o CNPJ), nunca por ordem de
dicionário.
"""

from __future__ import annotations

import json
from collections import defaultdict

from app.db import conectar

MARGEM_SOMA = 0.01     # tolerância ao somar percentuais em ponto flutuante


def responsaveis_disponiveis() -> list[dict]:
    """Operadores ativos do console — a fonte de quem pode receber item.

    É a MESMA lista que `fila.atribuir` valida. Distribuir para quem não pode
    receber produziria uma rodada que falha item a item no fim.
    """
    from app.fila import responsaveis
    return responsaveis()


def carga_atual() -> dict[str, int]:
    """Quantos itens abertos cada um já tem. Não entra na conta da cota; existe
    para a cota ser decidida com o quadro à vista."""
    try:
        with conectar() as con:
            linhas = con.execute(
                "SELECT responsavel, count(*) FROM fila_status"
                " WHERE responsavel IS NOT NULL AND status <> 'resolvido'"
                " GROUP BY responsavel").fetchall()
        return {r: n for r, n in linhas}
    except Exception:  # noqa: BLE001 — sem banco, o painel mostra zero
        return {}


def cotas() -> list[dict]:
    """Cota de cada operador ativo. Quem nunca teve cota entra com 0.

    Zero é deliberado: pessoa nova não passa a receber trabalho porque foi
    criada uma conta. Alguém decide a cota dela.
    """
    disponiveis = responsaveis_disponiveis()
    try:
        with conectar() as con:
            gravado = {r: (float(p), a) for r, p, a in con.execute(
                "SELECT responsavel, percentual, ativo FROM distribuicao_cota")}
    except Exception:  # noqa: BLE001 — tabela ainda não migrada
        gravado = {}
    carga = carga_atual()
    return [{"login": d["login"], "nome": d.get("nome") or d["login"],
             "percentual": gravado.get(d["login"], (0.0, True))[0],
             "ativo": gravado.get(d["login"], (0.0, True))[1],
             "carga_atual": carga.get(d["login"], 0)}
            for d in disponiveis]


def _elegiveis() -> list[dict]:
    return [c for c in cotas() if c["ativo"] and c["percentual"] > 0]


def gravar_cotas(pesos: dict[str, float], quem: str | None = None) -> dict:
    """Grava as cotas. A soma tem que fechar 100 — ou 0, para desligar tudo.

    Recusar soma diferente de 100 é a trava que impede a rodada de distribuir
    "quase tudo" e deixar um resto órfão sem ninguém perceber.
    """
    validos = {d["login"] for d in responsaveis_disponiveis()}
    desconhecidos = [k for k in pesos if k not in validos]
    if desconhecidos:
        return {"ok": False, "erro": f"não são operadores ativos: {', '.join(sorted(desconhecidos))}"}
    for login, p in pesos.items():
        try:
            p = float(p)
        except (TypeError, ValueError):
            return {"ok": False, "erro": f"percentual inválido para {login}: {p!r}"}
        if p < 0 or p > 100:
            return {"ok": False, "erro": f"percentual de {login} fora de 0 a 100: {p}"}
    soma = sum(float(p) for p in pesos.values())
    if soma > MARGEM_SOMA and abs(soma - 100.0) > MARGEM_SOMA:
        return {"ok": False, "erro": f"a soma das cotas é {soma:.2f}%, precisa ser 100%"}

    with conectar() as con:
        atuais = {r: float(p) for r, p in con.execute(
            "SELECT responsavel, percentual FROM distribuicao_cota")}
        for login, p in pesos.items():
            p = float(p)
            con.execute(
                "INSERT INTO distribuicao_cota (responsavel, percentual, atualizado_por)"
                " VALUES (%s,%s,%s) ON CONFLICT (responsavel) DO UPDATE SET"
                " percentual=EXCLUDED.percentual, atualizado_em=now(),"
                " atualizado_por=EXCLUDED.atualizado_por", (login, p, quem))
            if abs(atuais.get(login, 0.0) - p) > MARGEM_SOMA:
                con.execute(
                    "INSERT INTO distribuicao_cota_log (responsavel, de, para, quem)"
                    " VALUES (%s,%s,%s,%s)", (login, atuais.get(login), p, quem))
        con.commit()
    return {"ok": True, "soma": soma, "cotas": cotas()}


def sem_dono(cliente: str | None = None) -> list[dict]:
    """Itens acionáveis da mesa que ainda não têm responsável.

    Puxa da mesa, não de `marcos`, porque é a mesa que aplica faixa e prioridade
    — distribuir o que a mesa não mostra seria dar às pessoas trabalho que o
    produto decidiu não pedir.
    """
    from app.mesa import montar
    from app.resumo_diario import FAIXAS_ACIONAVEIS

    itens = montar(cliente)["itens"]
    return [i for i in itens
            if not i.get("responsavel") and i.get("rank") in FAIXAS_ACIONAVEIS]


def _urgencia(i: dict) -> tuple:
    """Mais grave primeiro; empate pelo CNPJ, que é estável entre execuções."""
    return (i.get("rank", 99), i.get("dias") if i.get("dias") is not None else 99999,
            str(i.get("cnpj") or ""), str(i.get("instrumento") or ""))


def _quotas_hare(total: int, elegiveis: list[dict]) -> dict[str, int]:
    """Quantos itens cabem a cada um, pelo maior resto. A soma fecha `total`."""
    if not elegiveis or total <= 0:
        return {}
    soma = sum(c["percentual"] for c in elegiveis)
    if soma <= 0:
        return {}
    exatos = {c["login"]: total * c["percentual"] / soma for c in elegiveis}
    piso = {k: int(v) for k, v in exatos.items()}
    sobra = total - sum(piso.values())
    # maior resto primeiro; empate pelo login, para não depender da ordem do dict
    ordem = sorted(exatos, key=lambda k: (-(exatos[k] - piso[k]), k))
    for k in ordem[:sobra]:
        piso[k] += 1
    return piso


def planejar(agrupar_por_cliente: bool = True, cliente: str | None = None) -> dict:
    """Quem receberia o quê. NÃO grava — é o que a tela mostra antes de aplicar."""
    elegiveis = _elegiveis()
    itens = sem_dono(cliente)
    if not elegiveis:
        return {"ok": False, "erro": "nenhum operador com cota acima de zero",
                "itens_sem_dono": len(itens), "plano": {}, "desvio": []}
    if not itens:
        return {"ok": True, "itens_sem_dono": 0, "plano": {}, "desvio": [],
                "aviso": "não há item sem dono para distribuir"}

    alvo = _quotas_hare(len(itens), elegiveis)
    dado: dict[str, list] = defaultdict(list)

    if agrupar_por_cliente:
        # blocos por cliente, do bloco que contém o item mais grave para o menos
        blocos: dict[str, list] = defaultdict(list)
        for i in itens:
            blocos[str(i.get("cnpj"))].append(i)
        ordem = sorted(blocos, key=lambda c: (min(_urgencia(i) for i in blocos[c]), c))
        unidades = [(c, blocos[c]) for c in ordem]
    else:
        unidades = [(str(i.get("cnpj")), [i]) for i in sorted(itens, key=_urgencia)]

    cota = {c["login"]: c["percentual"] for c in elegiveis}
    for _, bloco in unidades:
        # `dado.get`, não `dado[k]`: num defaultdict a leitura CRIA a chave, e o
        # plano saía com gente que não recebeu nada — uma lista vazia com nome de
        # pessoa, que na tela lê como "fulano ficou com zero" em vez de "fulano
        # não entrou nesta rodada".
        tem = {k: len(dado.get(k, ())) for k in alvo}
        # Quem ainda não encheu a própria cota. O alvo de Hare vira TETO, e é o
        # que mantém a soma exata quando não se agrupa.
        cabe = [k for k in alvo if tem[k] < alvo.get(k, 0)] or list(alvo)
        # Entre esses, quem tem a MENOR fração da própria cota preenchida — a
        # maior média, no jargão eleitoral. Escolher por déficit ABSOLUTO (o que
        # esta linha fazia antes) entrega os primeiros blocos inteiros a quem tem
        # a maior cota: medido no dado real, com 50/30/20 sobre 163 itens, a
        # primeira pessoa levava 18 dos 19 casos vencidos há mais de um ano e a
        # terceira levava zero. A cota fechava exata e a carga era desumana — e o
        # defeito não aparecia em número nenhum do painel.
        escolhido = min(sorted(cabe), key=lambda k: tem[k] / cota[k] if cota[k] else 9e9)
        dado[escolhido].extend(bloco)

    nomes = {c["login"]: c["nome"] for c in elegiveis}
    plano = {k: [{"chave": i["chave"], "cliente": i.get("cliente"),
                  "instrumento": i.get("instrumento"), "faixa": i.get("faixa"),
                  "dias": i.get("dias")} for i in v]
             for k, v in sorted(dado.items()) if v}
    desvio = [{"login": k, "nome": nomes.get(k, k), "alvo": alvo.get(k, 0),
               "recebe": len(dado.get(k, ())),
               "diferenca": len(dado.get(k, ())) - alvo.get(k, 0)}
              for k in sorted(alvo)]
    return {"ok": True, "itens_sem_dono": len(itens), "plano": plano, "desvio": desvio,
            "agrupou_por_cliente": agrupar_por_cliente}


def aplicar(agrupar_por_cliente: bool = True, cliente: str | None = None,
            quem: str | None = None) -> dict:
    """Executa o plano. Cada item passa por `fila.atribuir`, que é onde a regra
    de quem pode receber mora — não se duplica validação aqui."""
    from app.fila import atribuir

    p = planejar(agrupar_por_cliente, cliente)
    if not p.get("ok") or not p["plano"]:
        return p

    marca = f"distribuicao:{quem}" if quem else "distribuicao"
    feitos, erros = 0, []
    for login, itens in p["plano"].items():
        for i in itens:
            r = atribuir(i["chave"], login, marca)
            if r.get("ok"):
                feitos += 1
            else:
                erros.append({"chave": i["chave"], "erro": r.get("erro")})
    with conectar() as con:
        con.execute(
            "INSERT INTO distribuicao_rodada (quem, itens, agrupou_por_cliente, detalhe)"
            " VALUES (%s,%s,%s,%s)",
            (quem, feitos, agrupar_por_cliente,
             json.dumps({k: len(v) for k, v in p["plano"].items()})))
        con.commit()
    return {"ok": True, "distribuidos": feitos, "erros": erros,
            "desvio": p["desvio"], "itens_sem_dono": p["itens_sem_dono"]}
