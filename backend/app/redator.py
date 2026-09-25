"""Redação da resposta ao parecer — a etapa B, com o dado tratado nos dois lados.

Autorização do dono (28/07): usar a DeepInfra, **tratando o dado na entrada para
retirar e na saída para recompor**. O processador externo recebe `[[CLIENTE]]`,
`[[CNPJ]]`, `[[PESSOA_1]]` — nunca de quem é o caso — e a recomposição acontece
aqui dentro (`app.anonimo`).

## Onde isto entra

A camada determinística já cobre 199/199 dos itens acionáveis com peça pronta:
ofício do art. 97, esqueleto de diligência, checklist do dossiê, conferência de
parcela. O que sobra e é genuinamente generativo é UMA coisa: transformar *"os
critérios dos itens 1.3 e 5.1 não foram atendidos"* na resposta ponto a ponto.

Fora desse resíduo, não chama modelo. Um esqueleto determinístico é melhor que
um texto plausível: o operador confia mais no que sabe que é template.

## Fail-closed, em três pontos

1. **`vazou()` não vazio ⇒ NÃO ENVIA.** A máscara falhou; mandar assim seria
   dado de terceiro saindo da casa, e isso não se desfaz.
2. **Interruptor `redacao_ia` no banco**, desligado por padrão, como todo envio
   externo aqui. A regra da casa é DeepInfra só com autorização explícita.
3. **Sem parecer com TEXTO, não chama.** Na carteira, o Ministério da Saúde
   escreve só a referência do documento ("Parecer Técnico nº 184/2024-COPP…") —
   não há o que redigir a partir disso, e gastar token para o modelo inventar
   seria o pior uso possível.

O que volta é RASCUNHO: o operador revisa, completa e assina. Nunca sai sozinho.

Uso:
    py -3 backend/app/redator.py <cnpj> <id_proposta>   # rascunho no terminal
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.anonimo import mascarar, perdidos, recompor, vazou  # noqa: E402
from app.db import conectar  # noqa: E402

DEEPINFRA = os.environ.get("DEEPINFRA_BASE_URL") or "https://api.deepinfra.com/v1/openai"
MODELO = os.environ.get("TUIU_REDATOR_MODELO", "deepseek-ai/DeepSeek-V4-Flash")
MIN_PARECER = 200      # abaixo disso é referência de documento, não exigência
MARCADOR_NO_TEXTO = re.compile(r"\[\[[A-Z_0-9]+\]\]")

SISTEMA = """Você redige a RESPOSTA de uma entidade executora a uma exigência do órgão \
concedente, na plataforma Transferegov.

REGRAS DURAS:
1. Responda SOMENTE com base na exigência transcrita. Não invente fato, documento, valor, \
data nem artigo de lei que não esteja lá.
2. O texto tem marcadores como [[CLIENTE]], [[CNPJ]], [[PESSOA_1]]. COPIE-OS EXATAMENTE como \
estão, na mesma forma. Nunca traduza, complete nem substitua um marcador por um nome.
3. Estruture ponto a ponto: cada exigência do órgão vira um item numerado da resposta.
3a. RESPONDA À EXIGÊNCIA, NÃO AO CONTEXTO. Só o bloco "EXIGÊNCIA DO ÓRGÃO" é o que se responde. Os demais blocos são material de apoio: use o que ajudar a responder e IGNORE o resto. Nunca escreva um item comentando as regras vigentes, o acervo ou o dossiê — o órgão não perguntou isso, e responder o que não foi perguntado enfraquece a peça.
4. Onde faltar informação que só a entidade tem (número de documento, valor, data, anexo), \
escreva um campo entre colchetes para preencher, assim: [informar o nº do empenho]. É melhor \
um campo em branco do que um dado inventado.
5. Português do Brasil, formal e direto, sem adjetivo desnecessário. Nada de "venho por meio desta".
6. Não escreva saudação nem assinatura — isso o sistema acrescenta."""


def _cabecalho(con, doc: str) -> dict:
    r = con.execute("SELECT nome, apelido FROM clientes WHERE doc=%s", (doc,)).fetchone()
    pessoas = con.execute(
        "SELECT nome FROM clientes_pessoas WHERE doc_cliente=%s AND ativo LIMIT 5",
        (doc,)).fetchall()
    from app.minutas import _cnpj_fmt
    # formatado: o rascunho vira ofício, e "57722118000140" cru num documento
    # para o órgão é desleixo que o leitor atribui ao remetente
    conhecidos = {"CLIENTE": (r[0] if r else "") or "", "CNPJ": _cnpj_fmt(doc)}
    if r and r[1]:
        conhecidos["APELIDO"] = r[1]
    for n, (nome,) in enumerate(pessoas, 1):
        conhecidos[f"PESSOA_{n}"] = nome
    return conhecidos


def material(doc: str, id_proposta) -> dict:
    """A exigência e quem é o cliente. Sem texto de exigência, não há o que redigir."""
    doc = "".join(c for c in (doc or "") if c.isdigit())
    with conectar() as con:
        r = con.execute(
            "SELECT detalhes FROM marcos WHERE cnpj=%s AND instrumento=%s"
            " AND detalhes ? 'ultimo_parecer' LIMIT 1", (doc, str(id_proposta))).fetchone()
        if not r:
            return {"pronto": False, "erro": "sem parecer registrado para este instrumento"}
        det = r[0] if isinstance(r[0], dict) else json.loads(r[0] or "{}")
        parecer = ((det.get("ultimo_parecer") or {}).get("parecer") or "").strip()
        if len(parecer) < MIN_PARECER:
            return {"pronto": False,
                    "erro": f"parecer com {len(parecer)} chars — é referência de documento, "
                            f"não exigência (o MS escreve assim). Nada a redigir."}
        conhecidos = _cabecalho(con, doc)
    return {"pronto": True, "parecer": parecer, "conhecidos": conhecidos, "doc": doc}


def _chamar(prompt: str, chave: str, timeout: float = 120.0) -> dict:
    corpo = json.dumps({
        "model": MODELO, "temperature": 0.2,
        "messages": [{"role": "system", "content": SISTEMA},
                     {"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(f"{DEEPINFRA}/chat/completions", data=corpo, headers={
        "Authorization": f"Bearer {chave}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    uso = d.get("usage") or {}
    return {"texto": (d.get("choices") or [{}])[0].get("message", {}).get("content", "").strip(),
            "tokens_entrada": uso.get("prompt_tokens"), "tokens_saida": uso.get("completion_tokens")}


def redigir(doc: str, id_proposta, forcar: bool = False) -> dict:
    """Rascunho da resposta. Nunca levanta; devolve `erro` explicando."""
    from app.config import ligado

    if not (forcar or ligado("redacao_ia")):
        return {"disponivel": False,
                "erro": "redação por IA desligada — ligue `redacao_ia` em /notificacoes.html"}
    chave = os.environ.get("DEEPINFRA_API_KEY")
    if not chave:
        return {"disponivel": False, "erro": "sem DEEPINFRA_API_KEY no host"}

    m = material(doc, id_proposta)
    if not m["pronto"]:
        return {"disponivel": False, "erro": m["erro"]}

    # O CONTEXTO é o que separa peça de redação vazia: o primeiro rascunho real
    # saiu genérico porque o modelo só via o parecer. Ver app.dossie_contexto.
    from app.dossie_contexto import citacoes_soltas, montar as montar_contexto
    with conectar() as con:
        ctx = montar_contexto(con, m["doc"], id_proposta, m["parecer"])
    limpo, mapa = mascarar(ctx["texto"], m["conhecidos"])
    escapou = vazou(limpo, mapa)
    if escapou:
        # a máscara falhou: não manda. Não há como desfazer dado que saiu.
        return {"disponivel": False,
                "erro": f"máscara incompleta, envio abortado — ainda aparecem: {escapou}"}

    # O mapa de RECOMPOSIÇÃO inclui todo conhecido, não só o que apareceu no
    # parecer: eu cito [[CLIENTE]] no enunciado, e sem registrá-lo o marcador
    # chegava CRU ao rascunho — foi o que a primeira chamada real devolveu.
    mapa_volta = {f"[[{r}]]": v for r, v in m["conhecidos"].items() if str(v or "").strip()}
    mapa_volta.update(mapa)

    # Declarar os marcadores disponíveis: sem a lista, o modelo INVENTA (a
    # primeira chamada cunhou um [[CNPJ]] que eu não tinha oferecido) e o
    # rascunho sai com um campo que ninguém consegue preencher.
    disponiveis = ", ".join(sorted(mapa_volta))
    prompt = (f"Marcadores disponíveis, use SOMENTE estes: {disponiveis}\n\n"
              "O órgão concedente registrou a seguinte exigência sobre a proposta "
              f"de [[CLIENTE]]:\n\n---\n{limpo}\n---\n\n"
              "Redija a resposta da entidade, ponto a ponto.")
    try:
        r = _chamar(prompt, chave)
    except Exception as exc:  # noqa: BLE001
        return {"disponivel": False, "erro": f"falha na geração: {type(exc).__name__}: {exc}"}

    faltando = perdidos(r["texto"], mapa)
    soltas = citacoes_soltas(r["texto"], ctx["texto"])
    # marcador que o modelo inventou fora da lista fica visível no aviso: é
    # campo que ninguém consegue preencher, e some se a gente calar
    inventados = sorted(set(MARCADOR_NO_TEXTO.findall(r["texto"])) - set(mapa_volta))
    return {"disponivel": True, "markdown": recompor(r["texto"], mapa_volta),
            "marcadores_inventados": inventados,
            "titulo": f"Rascunho de resposta — proposta {id_proposta}",
            "citacoes_soltas": soltas, "blocos_de_contexto": sorted(ctx["blocos"]),
            "modelo": MODELO, "marcadores_perdidos": faltando,
            "tokens_entrada": r["tokens_entrada"], "tokens_saida": r["tokens_saida"],
            "aviso": ("RASCUNHO gerado por IA sobre a exigência do órgão — revise antes de enviar."
                      + (f" ⚠️ o modelo não devolveu {', '.join(faltando)}: confira os nomes."
                         if faltando else "")
                      + (f" ⚠️ inventou {', '.join(inventados)} — campo sem valor, apague ou preencha."
                         if inventados else "")
                      + (f" 🔴 CITAÇÃO NÃO ANCORADA: {', '.join(soltas)} — não está no acervo "
                         f"fornecido; confira antes de assinar."
                         if soltas else ""))}


def main():
    if len(sys.argv) < 3:
        sys.exit("uso: redator.py <cnpj> <id_proposta>")
    r = redigir(sys.argv[1], sys.argv[2], forcar="--forcar" in sys.argv)
    if not r.get("disponivel"):
        sys.exit(r["erro"])
    print(r["titulo"]); print("-" * 60); print(r["markdown"])
    print("-" * 60)
    print(f"{r['aviso']}\n{r['modelo']} · entrada {r['tokens_entrada']} tok · "
          f"saída {r['tokens_saida']} tok")


if __name__ == "__main__":
    main()
