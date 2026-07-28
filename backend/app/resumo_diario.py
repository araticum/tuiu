"""Resumo do dia — a triagem, não o feed (pedido do Danilo, 27/07/2026).

O alerta por evento não vale o incômodo, e a razão é boa: **o Transferegov já
manda e-mail de cada mudança**. Repetir isso no WhatsApp é a mesma inundação em
outro canal. Nas palavras dele: *"teve 200 mudanças, dessas 200, 5 precisam da
tua atenção porque é com você"* — e *"dos 30 que você tem que olhar, você precisa
olhar mesmo para dois"*.

Então o produto aqui não é notificação, é **recomendação**: uma mensagem por dia,
com o pouco que exige ação, e o link para o resto. Se ele fizer só os dois de
cima e não sobrar tempo, já fez o que importava.

## O que entra

Um item precisa das TRÊS coisas ao mesmo tempo:

1. **movimento** — mudou no snapshot de hoje (senão é backlog, não notícia);
2. **faixa que pede ação** — a mesa já ordena por urgência; inadimplência de
   2019 é passivo antigo, não a fila do dia.

⚠️ **A faixa manda, não a bola.** A primeira versão exigia `bola_com =
convenente` e com isso descartava os **41 itens de "Cobrar o órgão (art. 97)"** —
justamente onde o cliente tem alavanca e onde a peça já está pronta. O órgão não
se cobra sozinho: bola com o concedente e tarefa nossa convivem, e é a faixa que
sabe disso. A bola sobrou só para classificar o que NÃO é tarefa ("está com o
órgão — nada a fazer"), que é o denominador da frase.

Filtrar por bola também não bastaria: dos 396 marcos abertos, 355 são "nossos".
O corte vem do cruzamento com o que se moveu.

Marco de CLIENTE (instrumento nulo, como o agregado de prestações paradas) fica
FORA: é backlog permanente, não notícia do dia. Incluí-lo fez "8 mudanças → 9
pedem sua ação", com o numerador passando o denominador e destruindo a frase que
dá sentido à mensagem. Ele vive na mesa, que a mensagem linka.

## Silêncio é resposta

Sem item acionável, **nada é enviado**. Dia quieto não gasta a atenção de
ninguém — e "não chegou nada" só é honesto porque a quebra da cadeia avisa por
outro caminho (`ops/rodar_diario._avisar_falha`).

Uso:
    py -3 backend/app/resumo_diario.py            # monta e envia (respeita as travas)
    py -3 backend/app/resumo_diario.py --previa   # só mostra o que sairia
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import conectar  # noqa: E402

# Faixas da mesa que exigem ação do operador. 5 (vigência encerrando) e 6
# (acompanhar) ficam de fora de propósito: são vigilância, não tarefa, e entrar
# aqui devolveria a inundação que este módulo existe para evitar.
FAIXAS_ACIONAVEIS = {0, 1, 2, 3, 4, 8}
TOPO = 3          # quantos cabem na mensagem; o resto vive na mesa
# template PROPRIO: o de andamento tem outro formato, e mandar os parametros
# de um no corpo do outro produz mensagem trocada, nao erro
TEMPLATE = "aviso_tuiu_resumo"
LIMITE_ITEM = 160


def _mesa_por_instrumento(cliente: str | None = None) -> dict[tuple[str, str], dict]:
    from app.mesa import montar
    return {(i["cnpj"], str(i["instrumento"])): i
            for i in montar(cliente)["itens"] if i["instrumento"]}


def _bola_por_instrumento(con) -> dict[tuple[str, str], str]:
    """De quem é a bola em CADA instrumento — inclusive nos que a mesa não mostra.

    A mesa só carrega `farol <> 'ok'`, e o caso mais comum da carteira
    (prestação entregue, aguardando análise) é justamente `ok`. Classificar só
    por ela zerava a contagem de "está com o órgão": o evento sumia dos dois
    lados da conta e o denominador virava mentira por omissão.
    """
    return {(c, str(i)): (d or {}).get("bola_com") or "convenente"
            for c, i, d in con.execute(
                "SELECT DISTINCT ON (cnpj, instrumento) cnpj, instrumento, detalhes FROM marcos"
                " WHERE instrumento IS NOT NULL ORDER BY cnpj, instrumento, (farol = 'ok')")}


def montar(dia: date | None = None) -> dict:
    """Cruza o que MUDOU hoje com o que a mesa diz ser ação nossa."""
    dia = dia or date.today()
    with conectar() as con:
        eventos = con.execute(
            "SELECT cnpj, ente, rotulo, instrumento, de, para FROM eventos"
            " WHERE snapshot = %s AND cnpj <> 'nao_atribuido' ORDER BY id", (dia,)).fetchall()
        bolas = _bola_por_instrumento(con)

    mesa = _mesa_por_instrumento()
    acionaveis, com_orgao, sem_marco = [], 0, 0

    def _somar(item: dict, ente: str, rotulo: str, de=None, para=None) -> None:
        acionaveis.append({
            "cnpj": item["cnpj"], "cliente": item["cliente"] or ente,
            "instrumento": item["instrumento"], "rotulo": rotulo,
            "rank": item["rank"], "faixa": item["faixa"], "dias": item["dias"],
            "passo": item["proximo_passo"], "peca": item.get("peca"), "de": de, "para": para,
        })

    for cnpj, ente, rotulo, instrumento, de, para in eventos:
        chave = (cnpj, str(instrumento)) if instrumento else None
        if chave is None or chave not in bolas:
            sem_marco += 1          # sem marco: o motor não tem o que cobrar aqui
            continue
        item = mesa.get(chave)
        # 🔴 A FAIXA MANDA, não a bola. "Cobrar o órgão (art. 97)" é faixa
        # acionável COM a bola no concedente — e é tarefa nossa, porque o órgão
        # não se cobra sozinho. Filtrar por bola descartava os 41 itens de
        # cobrança, justamente onde o cliente tem alavanca e a peça está pronta.
        if item is not None and item["rank"] in FAIXAS_ACIONAVEIS:
            _somar(item, ente, rotulo, de, para)
        elif bolas[chave] != "convenente":
            com_orgao += 1

    # Marcos de CLIENTE (instrumento nulo) NÃO entram aqui. O motor junta todas
    # as prestações paradas do convenente num marco só, e isso é BACKLOG
    # permanente, não notícia do dia: enfiá-los no cálculo fez "8 mudanças → 9
    # pedem sua ação", com o numerador passando o denominador e destruindo a
    # frase que dá sentido à mensagem. Eles vivem na mesa, que a mensagem linka.
    acionaveis.sort(key=lambda i: (i["rank"], i["dias"] if i["dias"] is not None else 99999))
    return {"dia": dia.isoformat(), "mudancas": len(eventos), "acionaveis": acionaveis,
            "com_orgao": com_orgao, "sem_marco": sem_marco, "mesa_aberta": len(mesa)}


def _prazo(item: dict) -> str:
    d = item.get("dias")
    if d is None:
        return ""
    return f" (vencido há {-d}d)" if d < 0 else (" (hoje)" if d == 0 else f" (em {d}d)")


def linha_item(item: dict) -> str:
    """Uma linha por item — parâmetro de template não aceita quebra de linha."""
    # a PEÇA no fim da linha é o ponto do pedido do dono (28/07): a triagem não
    # diz só o que fazer, entrega o rascunho já montado
    peca = f" · {item['peca']['titulo'].lower()} pronta" if item.get("peca") else ""
    texto = (f"{item['cliente'][:40]} · {item['rotulo']}{_prazo(item)} — {item['passo']}{peca}")
    return texto[:LIMITE_ITEM - 1] + "…" if len(texto) > LIMITE_ITEM else texto


def parametros(r: dict, console_url: str) -> list[str]:
    """Os {{1}}..{{5}} do template `aviso_tuiu_resumo` (corpo em ferramentas/template_wpp.py).

    Três posições fixas de item porque a contagem de parâmetros do template é
    fixa; sobra vira travessão, que é feio mas honesto — a Meta recusa
    parâmetro vazio, e inventar item para preencher seria pior.
    """
    itens = r["acionaveis"][:TOPO]
    cabeca = (f"{r['mudancas']} mudança(s) na carteira hoje. "
              f"{len(r['acionaveis'])} pede(m) sua ação.")
    resto = len(r["acionaveis"]) - len(itens)
    cauda = (f"E mais {resto} na mesa." if resto > 0 else
             (f"{r['com_orgao']} mudança(s) estão com o órgão — nada a fazer."
              if r["com_orgao"] else "Só isso hoje."))
    return [cabeca,
            *[linha_item(i) for i in itens],
            *["—"] * (TOPO - len(itens)),
            cauda]


def texto(r: dict, console_url: str) -> str:
    """Versão legível para outbox/log — aqui a quebra de linha é permitida."""
    linhas = [f"📋 Tuiú · resumo de {r['dia'][8:10]}/{r['dia'][5:7]}",
              "", f"{r['mudancas']} mudança(s) hoje · {len(r['acionaveis'])} pede(m) sua ação", ""]
    for n, i in enumerate(r["acionaveis"][:TOPO], 1):
        linhas.append(f"{n}. {linha_item(i)}")
        if i.get("peca"):
            linhas.append(f"   → {i['peca']['titulo']}: {i['peca']['url']}")
    resto = len(r["acionaveis"]) - TOPO
    if resto > 0:
        linhas.append(f"…e mais {resto} na mesa.")
    if r["com_orgao"]:
        linhas.append(f"({r['com_orgao']} mudança(s) estão com o órgão — nada a fazer)")
    linhas += ["", f"Mesa completa, já priorizada: {console_url}/mesa.html"]
    return "\n".join(linhas)


def enviar(dia: date | None = None, previa: bool = False) -> dict:
    from app import seriema
    from app.config import envio_externo_liberado
    from app.notificador import CONSOLE_URL

    r = montar(dia)
    r["enviado"] = False
    if not r["acionaveis"]:
        # silêncio é a resposta certa: dia sem ação não gasta a atenção de
        # ninguém, e a quebra da cadeia avisa por outro caminho
        r["motivo"] = "nada exige ação hoje — nada enviado"
        return r
    r["texto"] = texto(r, CONSOLE_URL)
    r["parametros"] = parametros(r, CONSOLE_URL)
    if previa:
        r["motivo"] = "prévia"
        return r
    if not (envio_externo_liberado("seriema") and seriema.configurado()):
        r["motivo"] = f"canal desligado ou não configurado ({seriema.falta_config() or 'interruptor'})"
        return r
    ok, detalhe = seriema.enviar_grupo(
        r["texto"], chave_entrega=f"resumo-{r['dia']}", parametros=r["parametros"],
        template=TEMPLATE)
    r["enviado"], r["motivo"] = ok, detalhe
    return r


def main():
    previa = "--previa" in sys.argv
    r = enviar(previa=previa)
    print(f"{r['dia']}: {r['mudancas']} mudança(s), {len(r['acionaveis'])} acionável(is), "
          f"{r['com_orgao']} com o órgão, mesa com {r['mesa_aberta']}")
    if r.get("texto"):
        print("-" * 60); print(r["texto"]); print("-" * 60)
    print("enviado" if r["enviado"] else f"não enviado: {r.get('motivo')}")


if __name__ == "__main__":
    main()
