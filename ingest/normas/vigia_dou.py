"""Vigília normativa — lê o DOU e avisa o que pode mexer nas nossas regras.

Por que existe: o Tuiú vende prazo com **base legal citada**. As portarias
conjuntas mudam a cada trimestre (4 alterações na PC 33 desde 2023) e até aqui
quem percebia era pesquisa manual — a PC 45/2026 e a 46/2026 foram pegas assim.
Regra desatualizada não dá erro: dá resposta errada com ar de certa.

Fonte: **INLABS** (Imprensa Nacional), distribuição oficial do DOU em XML, feita
para uso programático. Credencial `INLABS_EMAIL`/`INLABS_SENHA` no cofre.

Não decide nada sozinho: marca a norma como PENDENTE e o operador diz se muda
`regras_normativas`. Versionar regra continua manual e consciente — nova redação
é LINHA NOVA com vigência, nunca sobrescrita.

Uso:
    python ingest/normas/vigia_dou.py                 # ontem e hoje
    python ingest/normas/vigia_dou.py --dia 2026-07-15
    python ingest/normas/vigia_dou.py --desde 2026-07-01
"""

from __future__ import annotations

import argparse
import html
import http.cookiejar
import io
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app.db import conectar, migrar  # noqa: E402

BASE = "https://inlabs.in.gov.br"
SECOES = ("DO1", "DO1E")   # DO1E = edição extra; a PC 45/2026 saiu numa delas

# Dias em que o DOU não sai por lei federal (Leis 662/1949, 6.802/1980 e 14.759/2023).
# Ponto facultativo (Carnaval, Corpus Christi…) NÃO entra aqui de propósito: nesses
# dias a vigília pergunta ao INLABS e só aceita "sem edição" com prova (ver `percorrer`).
FERIADOS_FIXOS = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)}


def feriado_nacional(dia: date) -> bool:
    return (dia.month, dia.day) in FERIADOS_FIXOS


class SemEdicao(RuntimeError):
    """O INLABS devolveu uma página (HTTP 200) em vez do ZIP daquele dia/seção.

    Acontece nos dois casos que importa distinguir: não há edição (feriado, ponto
    facultativo) OU o servidor está fora do ar respondendo página de erro. Quem decide
    é `percorrer`, com a prova de um ZIP de dia posterior — nunca esta função sozinha.
    """

    def __init__(self, dia: date, secao: str, bruto: bytes):
        self.dia, self.secao, self.tamanho = dia, secao, len(bruto)
        super().__init__(
            f"INLABS devolveu {len(bruto)} bytes que não são ZIP para {secao} de {dia} "
            f"(início: {bruto[:60]!r})")

# Termos em DOIS níveis, por causa de uma medição: na primeira versão, 40 de 45
# normas vieram casando SÓ "prestação de contas" — expressão que aparece em
# qualquer portaria. Vigília com 40 itens por dia para triar é vigília que
# ninguém lê, e aí ela não serve para nada.
#
# ESPECÍFICOS disparam sozinhos (só aparecem no nosso domínio).
# GENÉRICOS só contam acompanhados: 2 deles juntos, ou 1 ao lado de um
# específico. Assim "transferências da União" + "prestação de contas" entra, e
# "prestação de contas" solta fica de fora.
ESPECIFICOS = {
    "transferegov": r"transfer[êe]gov",
    "PC 33/2023": r"Portaria\s+Conjunta\s+MGI\s*/\s*MF\s*/\s*CGU\s+n[ºo°]?\s*33",
    "PC 28/2024": r"Portaria\s+Conjunta\s+MGI\s*/\s*MF\s*/\s*CGU\s+n[ºo°]?\s*28",
    "PI 424/2016": r"Portaria\s+Interministerial\s+n[ºo°]?\s*424",
    "Decreto 11.531": r"Decreto\s+n[ºo°]?\s*11\.?531",
    "convênio/contrato de repasse": r"conv[êe]nios?\s+e\s+contratos?\s+de\s+repasse",
    "MROSC": r"Lei\s+n[ºo°]?\s*13\.?019",
}
GENERICOS = {
    "transferência da União": r"transfer[êe]ncias?\s+(?:de\s+recursos\s+)?d[ao]\s+Uni[ãa]o",
    "prestação de contas": r"presta[çc][ãa]o\s+de\s+contas",
    "emenda parlamentar": r"emendas?\s+parlamentar",
}
TERMOS = {**ESPECIFICOS, **GENERICOS}


def relevante(casou: list[str]) -> bool:
    """Pelo menos um específico, ou dois genéricos juntos."""
    especificos = [t for t in casou if t in ESPECIFICOS]
    genericos = [t for t in casou if t in GENERICOS]
    return bool(especificos) or len(genericos) >= 2


def _segredo(nome: str) -> str:
    """ambiente -> .env -> cofre DPAPI (mesma ordem do resto do repo)."""
    if os.environ.get(nome):
        return os.environ[nome]
    env = RAIZ / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            k, _, v = linha.partition("=")
            if k.strip() == nome:
                return v.strip().strip("'\"")
    try:
        r = subprocess.run([r"D:\venvs\flow\Scripts\python.exe",
                            r"C:\Users\pedro\Desktop\Flumen\ferramentas\segredos.py", "get", nome],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def entrar(tentativas: int = 4):
    """O INLABS cai com alguma frequência (502/504). Vale insistir antes de
    desistir — mas desistir em voz alta, nunca fingindo que não havia norma."""
    email, senha = _segredo("INLABS_EMAIL"), _segredo("INLABS_SENHA")
    if not (email and senha):
        sys.exit("INLABS_EMAIL/INLABS_SENHA ausentes (ambiente, .env ou cofre)")
    for n in range(tentativas):
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        try:
            op.open(urllib.request.Request(
                f"{BASE}/logar.php",
                data=urllib.parse.urlencode({"email": email, "password": senha}).encode(),
                headers={"User-Agent": "Mozilla/5.0"}), timeout=90)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and n < tentativas - 1:
                pausa = min(60.0, 5.0 * 2 ** n)
                print(f"  [INLABS HTTP {e.code}] tentando de novo em {pausa:.0f}s", flush=True)
                time.sleep(pausa)
                continue
            sys.exit(f"INLABS indisponível (HTTP {e.code}) — a vigília NÃO rodou hoje")
        except urllib.error.URLError as e:
            if n < tentativas - 1:
                time.sleep(min(60.0, 5.0 * 2 ** n))
                continue
            sys.exit(f"INLABS inalcançável ({e.reason}) — a vigília NÃO rodou hoje")
        if any(c.name.startswith("inlabs_session") for c in jar):
            return op
        sys.exit("login no INLABS não devolveu sessão — confira a credencial")
    sys.exit("INLABS indisponível após as tentativas — a vigília NÃO rodou hoje")


def _texto(bruto: str) -> str:
    """O corpo vem escapado DUAS vezes dentro do XML — sem desescapar duas
    vezes, `<Identifica>` não aparece e a varredura acha zero."""
    return html.unescape(html.unescape(bruto))


def _tag(texto: str, tag: str) -> str | None:
    """Aceita atributos na abertura (`<Identifica id="x">`) — a Imprensa varia."""
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}\s*>", texto, re.S | re.I)
    if not m:
        return None
    limpo = re.sub(r"<[^>]+>", " ", m.group(1))
    return re.sub(r"\s+", " ", limpo).strip() or None


def _plano(texto: str) -> str:
    """Texto sem marcação e com espaço normalizado.

    É contra ISTO que a busca roda. Casar regex no XML cru falha silenciosamente
    quando a marcação parte a expressão no meio — "Portaria <i>Conjunta</i>",
    "MGI/<span>MF</span>/CGU" — e o resultado é uma vigília que diz "nenhuma
    norma" num dia em que saiu norma.
    """
    limpo = re.sub(r"<[^>]+>", " ", texto)
    return re.sub(r"\s+", " ", limpo).strip()


# Cabeçalho de norma no corpo do texto — usado quando <Identifica> não vem.
CABECALHO = re.compile(
    r"((?:Portaria\s+(?:Conjunta|Interministerial)?|Instru[çc][ãa]o\s+Normativa|"
    r"Decreto|Resolu[çc][ãa]o|Medida\s+Provis[óo]ria)"
    r"[^.]{0,90}?N[ºo°]?\s*[\d.]+[^.]{0,70}?\d{4})", re.I)


def _baixar_zip(op, dia: date, secao: str) -> bytes | None:
    """ZIP da seção do dia; None se a seção não existe (404); SemEdicao se veio página."""
    url = f"{BASE}/index.php?p={dia.isoformat()}&dl={dia.isoformat()}-{secao}.zip"
    try:
        with op.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                     timeout=300) as r:
            bruto = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None     # seção não existe nesse dia (extra nem sempre sai)
        raise RuntimeError(f"INLABS respondeu HTTP {e.code} para {secao} de {dia}") from e
    if not bruto.startswith(b"PK"):
        # Servidor fora do ar devolve página de erro com HTTP 200 — e feriado também
        # (07/09/2026 travou a vigília por isso). Tratar como "nada encontrado" faria
        # a vigília dizer "0 normas" num dia em que ela não olhou — silêncio
        # indistinguível de sossego. Quem desempata é `percorrer`.
        raise SemEdicao(dia, secao, bruto)
    return bruto


def _artigos_do_zip(bruto: bytes):
    z = zipfile.ZipFile(io.BytesIO(bruto))
    for nome in z.namelist():
        if nome.endswith(".xml"):
            yield nome, _texto(z.read(nome).decode("utf-8", "replace"))


def artigos_do_dia(op, dia: date, secao: str):
    bruto = _baixar_zip(op, dia, secao)
    if bruto is not None:
        yield from _artigos_do_zip(bruto)


def varrer(op, dia: date) -> tuple[list[dict], int, list[SemEdicao]]:
    """(achados, ZIPs lidos, seções que vieram como página em vez de ZIP)."""
    achados: list[dict] = []
    zips, faltas = 0, []
    for secao in SECOES:
        try:
            bruto = _baixar_zip(op, dia, secao)
        except SemEdicao as e:
            faltas.append(e)
            continue
        if bruto is None:
            continue
        zips += 1
        for nome, texto in _artigos_do_zip(bruto):
            plano = _plano(texto)
            casou = [rotulo for rotulo, padrao in TERMOS.items()
                     if re.search(padrao, plano, re.I)]
            if not relevante(casou):
                continue
            # <Identifica> quando vem; senão o cabeçalho no corpo. Sem os dois,
            # registra pelo arquivo — deixar passar norma por falta de rótulo
            # seria trocar um falso positivo por um silêncio.
            ident = _tag(texto, "Identifica")
            if not ident:
                m = CABECALHO.search(plano)
                ident = m.group(1).strip() if m else f"[sem identificação] {nome}"
            orgao = re.search(r'artCategory="([^"]+)"', texto)
            achados.append({
                "secao": secao, "publicado_em": dia, "identifica": ident[:300],
                "orgao": orgao.group(1)[:200] if orgao else None,
                "ementa": (_tag(texto, "Ementa") or _plano(plano[:400]))[:600] or None,
                "termos": casou, "arquivo": nome,
            })
    return achados, zips, faltas


def gravar(achados: list[dict]) -> list[dict]:
    novos = []
    with conectar() as con:
        for a in achados:
            cur = con.execute(
                "INSERT INTO normas_vistas (secao, publicado_em, identifica, orgao, ementa, termos)"
                " VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (fonte, publicado_em, identifica) DO NOTHING RETURNING id",
                (a["secao"], a["publicado_em"], a["identifica"], a["orgao"], a["ementa"], a["termos"]))
            if cur.fetchone():
                novos.append(a)
        con.commit()
    return novos


def percorrer(op, dias: list[date]) -> dict:
    """Varre os dias em ordem e diz até onde o marcador pode avançar.

    Página em vez de ZIP só vale como "sem edição" quando um ZIP de dia POSTERIOR (ou da
    outra seção do mesmo dia) prova que o INLABS estava de pé. Sem essa prova o dia fica
    PENDENTE: o marcador não passa dele e amanhã a vigília tenta de novo. Se nenhum ZIP
    veio e houve página, é fonte instável — erro, para o elo aparecer vermelho.
    """
    novos: list[dict] = []
    faltas: list[SemEdicao] = []
    ultimo_zip: date | None = None
    zips_total = 0
    for dia in dias:
        if dia.weekday() >= 5:      # DOU não sai sábado/domingo (extra é raro)
            continue
        if feriado_nacional(dia):
            print(f"  {dia}: feriado nacional, DOU não sai", flush=True)
            continue
        achados, zips, faltas_dia = varrer(op, dia)
        zips_total += zips
        if zips:
            ultimo_zip = dia
        faltas += faltas_dia
        novos_dia = gravar(achados)
        novos += novos_dia
        aviso = f" — página em vez de ZIP: {', '.join(e.secao for e in faltas_dia)}" if faltas_dia else ""
        print(f"  {dia}: {len(achados)} relevante(s), {len(novos_dia)} novo(s){aviso}", flush=True)
    if faltas and zips_total == 0:
        raise RuntimeError(
            f"INLABS devolveu página em vez de ZIP em todas as {len(faltas)} tentativas "
            f"({faltas[0]}) — fonte instável, NÃO é 'nenhuma norma'; o marcador não avança")
    pendentes = [e for e in faltas if ultimo_zip is None or e.dia > ultimo_zip]
    sem_edicao = [e for e in faltas if e not in pendentes]
    ate = max(dias) if not pendentes else ultimo_zip
    return {"novos": novos, "ate": ate, "sem_edicao": sem_edicao, "pendentes": pendentes}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dia")
    ap.add_argument("--desde")
    args = ap.parse_args()

    migrar()
    hoje = date.today()
    if args.dia:
        dias = [date.fromisoformat(args.dia)]
    elif args.desde:
        d = date.fromisoformat(args.desde)
        dias = []
        while d <= hoje:
            dias.append(d)
            d += timedelta(days=1)
    else:
        # Retoma de onde parou, não de "ontem". O INLABS cai com frequência; se a
        # vigília falhar três dias seguidos, uma janela fixa pularia esses dias
        # EM SILÊNCIO — e norma publicada no buraco nunca seria vista.
        with conectar() as con:
            m = con.execute("SELECT ate FROM vigia_marcador WHERE fonte='DOU'").fetchone()
        inicio = (m[0] if m else hoje - timedelta(days=1))
        if (hoje - inicio).days > 30:
            inicio = hoje - timedelta(days=30)   # teto: não rebaixar o DOU inteiro
            print(f"  [marcador muito antigo — varrendo os últimos 30 dias]", flush=True)
        dias = []
        d = inicio
        while d <= hoje:
            dias.append(d)
            d += timedelta(days=1)
        if len(dias) > 2:
            print(f"  retomando de {inicio} ({len(dias)} dia(s) desde a última varredura)",
                  flush=True)

    op = entrar()
    r = percorrer(op, dias)
    todos_novos = r["novos"]
    if r["sem_edicao"]:
        print("  sem edição (INLABS de pé, provado por ZIP posterior): "
              + ", ".join(f"{e.dia} {e.secao}" for e in r["sem_edicao"]), flush=True)
    if r["pendentes"]:
        print("  PENDENTE, sem prova de que o INLABS estava de pé — refaz amanhã: "
              + ", ".join(f"{e.dia} {e.secao}" for e in r["pendentes"]), flush=True)

    with conectar() as con:
        con.execute(
            "INSERT INTO vigia_marcador (fonte, ate) VALUES ('DOU', %s)"
            " ON CONFLICT (fonte) DO UPDATE SET ate=GREATEST(vigia_marcador.ate, EXCLUDED.ate),"
            " atualizado_em=now()", (r["ate"],))
        pendentes = con.execute("SELECT count(*) FROM normas_vistas WHERE NOT tratada").fetchone()[0]
        con.commit()

    for n in todos_novos:
        print(f"\n  NOVA  {n['identifica']}")
        print(f"        {n['orgao'] or '—'}  ·  casou: {', '.join(n['termos'])}")
        if n["ementa"]:
            print(f"        {n['ementa'][:150]}")
    print(f"\npendentes de avaliação: {pendentes}"
          + ("  (ver /normas.html)" if pendentes else ""))


if __name__ == "__main__":
    main()
