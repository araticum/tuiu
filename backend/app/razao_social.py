"""Razão social legível — correção de EXIBIÇÃO, nunca de gravação.

Decisão do dono (30/07/2026): *"não validamos erros de plataforma, mesmo que
oficial"*. O Transferegov entrega razão social em caixa alta e sem acento
(`FUNDACAO COORDENACAO DE PROJETOS,PESQUISAS`), e repetir isso na tela é aceitar
o erro de quem publicou. Então conserta-se — **só na apresentação**, para que a
conferência contra a origem continue trivial depois.

## O contrato, e por que ele é estreito

O dado gravado **não muda**. Este módulo é chamado por `carteira.nome_exibicao`,
que é o único lugar onde se decide como o cliente é chamado na tela e na
mensagem. `clientes.nome` continua byte a byte igual ao que a plataforma
mandou — quem quiser auditar roda `ferramentas/conferir_razao_social.py` e vê as
duas colunas lado a lado.

## Acento não se deduz, se consulta

Não existe regra que leve `FUNDACAO` a `Fundação` sem saber que a palavra é
"fundação": `CACAU` não vira `Caçaú`, `PROJETOS` não ganha acento nenhum. Por
isso o acento vem de **léxico explícito** e nada mais — palavra fora do léxico
sai com a caixa corrigida e sem acento, jamais com acento adivinhado. Inventar
acento erraria o nome registrado de uma pessoa jurídica, que é falsear dado, e a
regra que motivou este módulo é justamente não aceitar dado falseado.

`pendencias()` existe para o léxico não virar dívida invisível: ele devolve as
palavras que passaram sem entrada, marcando as que **parecem** precisar de acento
(sufixo típico). É a lista de trabalho, e o dono decide caso a caso.

## O que fica de fora de propósito

**Truncamento da origem.** `DESENVOL`, `PESQ`, `EDUCAO`, `LATINOAMERICA` vêm
cortados da plataforma. Expandir seria adivinhar palavra inteira, não repor
acento — risco muito maior. Saem como estão e aparecem na conferência.
"""

from __future__ import annotations

import re
import unicodedata

# Palavras que não sobem de caixa no meio do nome (sobem se abrirem o nome).
MINUSCULAS = {
    "a", "à", "às", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos",
    "e", "em", "na", "nas", "no", "nos", "o", "os", "para", "por", "sob",
    "sobre", "um", "uma",
}

# Siglas e nomes de instituição que são sigla: ficam em caixa alta. Lista
# explícita, não heurística — `ICA` e `Ica` são coisas diferentes, e adivinhar
# por tamanho transformaria `SAO` (São) em sigla.
SIGLAS = {
    "ANCAT", "BR", "CAED", "CCT", "CEAP", "COPPETEC", "CPASC", "FAMAR", "FIOTEC",
    "HCFMRPUSP", "IAUPE", "ICA", "IMIP", "IOM", "IPGIAS", "MOC", "RGS", "SPDM",
    "SUS", "TELAR", "UFMA",
    # UFs, que aparecem nos rótulos e nos nomes de unidade
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT",
    "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}

ROMANOS = re.compile(r"^(?=[MDCLXVI]+$)M*(C[MD]|D?C{0,3})(X[CL]|L?X{0,3})(I[XV]|V?I{0,3})$")

# Léxico de acentuação — a ÚNICA fonte de acento deste módulo.
#
# Levantado do corpus real da carteira (95 razões sociais, 280 palavras
# distintas) em 30/07/2026. Entrou só o que é inequívoco: substantivo comum e
# topônimo de grafia consagrada. Antropônimo duvidoso ficou FORA de propósito —
# `SOUSANDRADE`, `LEO` e `CAIUA` podem ou não levar acento no nome registrado, e
# `pendencias()` os entrega para decisão humana em vez de arriscar.
LEXICO = {
    # -ção / -ções: o grupo mais numeroso e o mais seguro
    "ACAO": "Ação", "ACOES": "Ações", "ARTICULACAO": "Articulação",
    "AVALIACAO": "Avaliação", "CONFEDERACAO": "Confederação",
    "COORDENACAO": "Coordenação", "EDUCACAO": "Educação",
    "EXTENSAO": "Extensão", "GESTAO": "Gestão", "INSTITUICAO": "Instituição",
    "MISSAO": "Missão", "ORGANIZACAO": "Organização",
    "ORIENTACAO": "Orientação", "POPULACOES": "Populações",
    "PROMOCAO": "Promoção", "PROTECAO": "Proteção",
    "RECUPERACAO": "Recuperação", "UNIAO": "União", "FUNDACAO": "Fundação",
    "ASSOCIACAO": "Associação",
    # -ância / -ência
    "AGENCIA": "Agência", "ASSISTENCIA": "Assistência",
    "BENEFICENCIA": "Beneficência", "CIENCIA": "Ciência",
    "EXCELENCIA": "Excelência", "INFANCIA": "Infância",
    # -ário / -ório / -ico / -ável
    "CIENTIFICO": "Científico", "COMUNITARIA": "Comunitária",
    "ESTRATEGICO": "Estratégico", "EVANGELICA": "Evangélica",
    "LITERARIA": "Literária", "MISERICORDIA": "Misericórdia",
    "POLITICAS": "Políticas", "PUBLICA": "Pública", "PUBLICAS": "Públicas",
    "RECICLAVEIS": "Recicláveis", "SODALICIO": "Sodalício",
    "SUSTENTAVEL": "Sustentável", "TECNOLOGICO": "Tecnológico",
    "TECNOLOGICOS": "Tecnológicos", "UNIVERSITARIA": "Universitária",
    "UNIVERSITARIO": "Universitário", "VOLUNTARIOS": "Voluntários",
    # diversos, substantivo comum
    "ARIDO": "Árido", "AVANCADOS": "Avançados", "CANCER": "Câncer",
    "CIDADAO": "Cidadão", "ESPERANCA": "Esperança", "GLORIA": "Glória",
    "IRMA": "Irmã", "MILHAO": "Milhão", "NUCLEO": "Núcleo",
    "PORTUGUES": "Português",
    "SAUDE": "Saúde", "SERVICO": "Serviço",
    # topônimos de grafia consagrada
    "CEARA": "Ceará", "GOIAS": "Goiás", "GUARATINGUETA": "Guaratinguetá",
    "IJUI": "Ijuí", "JARAGUA": "Jaraguá", "MARILIA": "Marília",
    "PARANA": "Paraná", "SABARA": "Sabará", "SAO": "São",
    # antropônimos de grafia estabelecida
    "ALVARO": "Álvaro", "ANTONIO": "Antônio", "APOLONIO": "Apolônio",
    "BONIFACIO": "Bonifácio", "GETULIO": "Getúlio", "GUIMARAES": "Guimarães",
    "JOSE": "José", "MARIO": "Mário",
    # abreviatura de tratamento: em português leva ponto
    "DR": "Dr.",
}

# Sufixos que, em português, quase sempre pedem acento. Não acentuam nada —
# apenas marcam a palavra como suspeita em `pendencias()`, para o léxico crescer
# por decisão e não por adivinhação.
SUFIXO_SUSPEITO = re.compile(
    # -ão/-ões e -ção/-ções: `MARANHAO` não casava com `CAO$` e passava calado
    r"(AO|OES|AES|ENCIA|ANCIA|ARIO|ARIA|ORIO|ORIA|AVEL|IVEL|ICO|ICA|ICOS|ICAS"
    r"|OGIA|ONIO|ESIA|AUDE|ANCER|EIA)$")
# `ç` some no dado da plataforma como `c`: `CRIANCA`, `ESPERANCA`, `AVANCADOS`.
# Não casa com sufixo nenhum, então precisa de sinal próprio.
CEDILHA_PROVAVEL = re.compile(r"N[CÇ][AOU]|[AEIOU]C[AOU](?=[MRS]?$)")


def _sem_acento(palavra: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", palavra)
                   if unicodedata.category(c) != "Mn")


def _ja_tem_acento(nome: str) -> bool:
    """Rótulo escrito à mão já vem correto — reprocessar só faria estrago."""
    return _sem_acento(nome) != nome


def _palavra(bruta: str, primeira: bool) -> str:
    nu = bruta.upper()
    if nu in SIGLAS or (len(nu) > 1 and ROMANOS.match(nu)):
        return nu
    if nu in LEXICO:
        return LEXICO[nu]
    baixa = bruta.lower()
    if not primeira and baixa in MINUSCULAS:
        return baixa
    # sem entrada no léxico: corrige a CAIXA e não toca no acento
    return baixa.capitalize()


def exibir(bruto: str | None) -> str:
    """`"FUNDACAO ... DE PROJETOS,PESQUISAS"` -> `"Fundação ... de Projetos, Pesquisas"`.

    Nome que já vem acentuado passa intacto: é rótulo nosso, escrito à mão, e
    reprocessar `"Águas Lindas de Goiás/GO — prefeitura (ente)"` só estragaria.
    Nome em caixa mista sem acento também passa — só se mexe no que veio no
    padrão da plataforma (CAIXA ALTA), que é o erro que se recusou a validar.
    """
    nome = (bruto or "").strip()
    if not nome or _ja_tem_acento(nome) or nome != nome.upper():
        return re.sub(r"([,;])(?=\S)", r"\1 ", nome)
    nome = re.sub(r"([,;])(?=\S)", r"\1 ", nome)
    saida, abre = [], True
    for pedaco in nome.split(" "):
        if not pedaco:
            continue
        # `PROJETOS,PESQUISAS` já foi separado; sobra hífen e barra, que dividem
        # palavra sem dividir token — `SAO/SP` tem duas palavras num pedaço só
        partes = re.split(r"([-/])", pedaco)
        montado = "".join(p if p in "-/" else _palavra(p, abre and i == 0)
                          for i, p in enumerate(partes))
        saida.append(montado)
        abre = False
    return " ".join(saida)


def pendencias(bruto: str | None) -> list[dict]:
    """Palavras que saíram SEM entrada no léxico, marcando as suspeitas.

    O léxico não pode virar dívida invisível: sem esta lista, uma razão social
    nova entraria na carteira e apareceria meio-corrigida na tela sem ninguém
    notar. `suspeita=True` é só heurística de sufixo — quem decide é o dono.
    """
    nome = (bruto or "").strip()
    if not nome or _ja_tem_acento(nome) or nome != nome.upper():
        return []
    fora = []
    for palavra in re.findall(r"[A-Za-z]+", nome):
        nu = palavra.upper()
        if nu in LEXICO or nu in SIGLAS or palavra.lower() in MINUSCULAS:
            continue
        if len(nu) > 1 and ROMANOS.match(nu):
            continue
        fora.append({"palavra": nu,
                     "suspeita": bool(SUFIXO_SUSPEITO.search(nu)
                                      or CEDILHA_PROVAVEL.search(nu))})
    vistos, unicas = set(), []
    for p in fora:
        if p["palavra"] not in vistos:
            vistos.add(p["palavra"])
            unicas.append(p)
    return unicas
