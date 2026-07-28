"""Referências documentais do instrumento — onde o papel de verdade está.

O parecer da g2 muitas vezes é só um ponteiro ("Parecer Técnico nº
184/2024-COPP/CGFPS/DECIT/SECTICS/MS"), e o documento em si mora fora do dado
aberto. Este módulo levanta, do que a fonte JÁ entrega, os caminhos até ele.

Medido no recorte de 28/07/2026, sobre 31 parcerias:

    cd_processo_sei        16   processo no SEI do órgão
    publicacoes_parceria   11   ato publicado no DOU (data, edição, página)
    nu_externo              0   nunca preenchido

## O que dá e o que não dá

- **SEI**: a consulta pública dos órgãos é **captcha-gated** (medido em
  sei.saude.gov.br e sei.mma.gov.br). Não se quebra captcha aqui, em nenhuma
  hipótese — então o que se entrega é o **link com o processo já preenchido**:
  some a busca, sobra um clique e o captcha, que é do humano.
- **DOU**: o INLABS (credencial no host) serve ~**6 meses** para trás — medido:
  29/04 responde, 29/01 não; domingo não tem edição. Dentro da janela dá para
  puxar o texto do ato; fora dela, o link da edição resolve para o operador.
  A via pública do in.gov.br responde **403** a requisição automatizada.
- **Anexo do convênio** (plano de trabalho, prestação): não existe em fonte
  aberta — nem nas 16 rotas da g2, nem nos 56 arquivos do detru — e está fora
  do escopo por decisão do dono (28/07): o Tuiú opera a plataforma, não a
  execução do serviço.

Cada referência sai com a origem e o que ela custa para abrir: link que exige
captcha vem rotulado, para ninguém achar que é automático e ficar esperando.
"""

from __future__ import annotations

import gzip
import json
from datetime import date

from app.carteira import snapshot_mais_recente

# Prefixo do nº do processo -> SEI do órgão. O que não estiver aqui cai na busca
# genérica do gov.br: melhor um caminho a mais de um clique do que link errado.
SEI_POR_PREFIXO = {
    "25000": ("Ministério da Saúde", "https://sei.saude.gov.br"),
    "02000": ("Ministério do Meio Ambiente", "https://sei.mma.gov.br"),
    "71000": ("Ministério da Cidadania/Desenvolvimento Social", "https://sei.cidadania.gov.br"),
    "23000": ("Ministério da Educação", "https://sei.mec.gov.br"),
}
SEI_CAMINHO = ("/sei/modulos/pesquisa/md_pesq_processo_pesquisar.php"
               "?acao_externa=protocolo_pesquisar&acao_origem_externa=protocolo_pesquisar"
               "&id_orgao_acesso_externo=0&txtProtocoloPesquisa=")
DOU_EDICAO = "https://www.in.gov.br/leiturajornal?data={}&secao=do{}"
JANELA_INLABS_DIAS = 180     # medido: 29/04 responde, 29/01 não


def formatar_sei(bruto: str) -> str:
    """25000157186202484 -> 25000.157186/2024-84 (formato que a busca aceita)."""
    d = "".join(c for c in str(bruto or "") if c.isdigit())
    if len(d) != 17:
        return str(bruto or "")
    return f"{d[:5]}.{d[5:11]}/{d[11:15]}-{d[15:]}"


def _linhas(doc: str, rota: str) -> list[dict]:
    snap = snapshot_mais_recente()
    if snap is None:
        return []
    arq = snap / doc / "parcerias" / f"{rota}.jsonl.gz"
    if not arq.exists():
        return []
    with gzip.open(arq, "rt", encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _sei(numero: str) -> dict:
    formatado = formatar_sei(numero)
    prefixo = "".join(c for c in str(numero or "") if c.isdigit())[:5]
    orgao, base = SEI_POR_PREFIXO.get(prefixo, (None, None))
    return {
        "tipo": "processo_sei", "numero": formatado, "orgao": orgao,
        "url": (base + SEI_CAMINHO + formatado) if base else None,
        # rotulado de propósito: link que exige captcha não é automação, e
        # deixar isso implícito faz alguém esperar por um robô que não existe
        "exige": "captcha (consulta pública do SEI) — abrir e resolver na tela",
        "nota": None if base else f"SEI do órgão de prefixo {prefixo} não mapeado — buscar pelo nº",
    }


def _dou(pub: dict, hoje: date) -> dict:
    quando = str(pub.get("dt_publicacao") or "")[:10]
    secao = 1
    try:
        dias = (hoje - date.fromisoformat(quando)).days
    except ValueError:
        dias = None
    recuperavel = dias is not None and 0 <= dias <= JANELA_INLABS_DIAS
    return {
        "tipo": "publicacao_dou", "quando": quando,
        "documento": (pub.get("ds_documento_publicado") or "").strip()[:200],
        "edicao": pub.get("ds_numero_dou"), "pagina": pub.get("nr_pagina_dou"),
        "url": DOU_EDICAO.format("-".join(reversed(quando.split("-"))), secao) if quando else None,
        "texto_recuperavel": recuperavel,
        "exige": None if recuperavel else
                 f"fora da janela do INLABS (~{JANELA_INLABS_DIAS} dias) — abrir a edição",
    }


def do_instrumento(doc: str, id_proposta, hoje: date | None = None) -> list[dict]:
    """Caminhos até o papel, para esta proposta. Lista vazia = não há pista."""
    hoje = hoje or date.today()
    doc = "".join(c for c in (doc or "") if c.isdigit())
    alvo = str(id_proposta)
    saida: list[dict] = []
    for p in _linhas(doc, "parceria"):
        if str(p.get("id_proposta")) != alvo:
            continue
        if p.get("cd_processo_sei"):
            saida.append(_sei(p["cd_processo_sei"]))
        for pub in p.get("publicacoes_parceria") or []:
            saida.append(_dou(pub, hoje))
    return saida


def em_texto(refs: list[dict]) -> list[str]:
    """Para o contexto do redator: referência verificável, com a origem."""
    linhas = []
    for r in refs:
        if r["tipo"] == "processo_sei":
            linhas.append(f"- Processo SEI nº {r['numero']}"
                          + (f" ({r['orgao']})" if r.get("orgao") else "")
                          + " — é onde o parecer integral está arquivado.")
        else:
            linhas.append(f"- Publicado no DOU em {'/'.join(reversed(r['quando'].split('-')))}"
                          f", edição {r.get('edicao')}, página {r.get('pagina')}: "
                          f"{r.get('documento')}")
    return linhas
