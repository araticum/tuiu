"""Cliente do Portal da Transparência (CGU) — convênios.

Fonte INDEPENDENTE da g2/detru: serve para conferir a carteira contra um
terceiro. Chave no cofre DPAPI (`PORTAL_TRANSPARENCIA_API_KEY`) — nunca no git.

ARMADILHAS DA API (conhecimento de campo do dono, confirmado ao vivo 18/07/2026):

1. **`/convenios` exige filtro restritivo.** Todos os params são "optional" no
   spec, mas a consulta ampla é recusada: *"escolha um período de até 1 mês ou
   um convenente ou um órgão/entidade ou uma localidade (município ou
   estado-UF) ou um número de convênio"*. Combinando, a janela abre:
   `uf=DF&dataInicial=01/01/2024&dataFinal=31/12/2024` funciona — a trava de 1
   mês só vale quando a data é o ÚNICO filtro. Carga completa = iterar por UF
   (27) ou `codigoIBGE` (~5.570).
2. **Erro pode chegar com HTTP 200** e corpo `dict` em vez de `list`. Quem só
   olha `status` grava erro como registro. → checar `isinstance(r, list)`.
   (Na consulta ampla hoje veio 400 + corpo de erro; tratamos os dois.)
3. **Paginação cega**: page size **15 fixo** (sem parâmetro), o payload **não
   traz total**, e página além do fim devolve `[]`. Única estratégia: paginar
   até vir vazio.
4. **Dois bugs no payload deles**:
   a) `uf.sigla` e `uf.nome` vêm **trocados**;
   b) domínio `tipoInstrumento` **corrompido** (off-by-2 em campo fixed-width:
      o código comeu 2 chars da descrição — "1CO"/"NVENIO ÷"). → filtrar/ler
      por **id**, nunca por `descricao`.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, r"C:\Users\pedro\Desktop\Flumen\ferramentas")

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
PAGINA = 15  # fixo pela API (armadilha 3)

# TLS verificado. A chave da API viaja no header desta conexão: sem verificar o
# certificado, qualquer intermediário lê a chave. Só desliga com opt-in
# explícito (TUIU_TLS_INSECURE=1), para máquina com DLP que intercepta TLS.
_CTX = ssl.create_default_context()
if os.environ.get("TUIU_TLS_INSECURE") == "1":
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE

# Armadilha 4b: descrições corrompidas -> mapa por ID (fonte: levantamento do dono).
TIPO_INSTRUMENTO = {
    500839: "CONVENIO", 500847: "CONTRATO DE REPASSE", 500838: "TERMO DE PARCERIA",
    500824: "ACORDO DE COOPERACAO TECNICA", 500822: "TERMO DE COMPROMISSO",
    500845: "TRANSFERENCIA LEGAL",
}


NOME_CHAVE = "PORTAL_TRANSPARENCIA_API_KEY"


def _do_env_file() -> str | None:
    """`.env` na raiz do repo — é assim que o segredo chega no araticum (o cofre
    DPAPI é do Windows e não existe no host). Fora do git, chmod 600."""
    env = Path(__file__).resolve().parents[2] / ".env"
    if not env.exists():
        return None
    for linha in env.read_text(encoding="utf-8").splitlines():
        nome, _, valor = linha.partition("=")
        if nome.strip() == NOME_CHAVE:
            return valor.strip().strip("'\"") or None
    return None


def _chave() -> str:
    # ordem: ambiente -> .env (Linux/host) -> cofre DPAPI (Windows)
    k = os.environ.get(NOME_CHAVE) or _do_env_file()
    if not k:
        try:
            from segredos import get  # cofre DPAPI, só existe no Windows do dono

            k = get(NOME_CHAVE)
        except BaseException as e:  # segredos.py faz sys.exit() sem keyring
            # sem isto o motivo some e vira "ausente" — o caso comum é rodar
            # com um Python que não tem keyring (use o venv D:\venvs\flow).
            print(f"  [cofre indisponível: {type(e).__name__}: {str(e)[:80]}]", file=sys.stderr)
            k = None
    if not k:
        sys.exit(f"{NOME_CHAVE} ausente (ambiente, .env ou cofre DPAPI)")
    return k


# ARMADILHA 6 (aparece só quando a carteira cresce): a CGU limita ~90 req/min
# das 06h às 23h59 (mais folgado de madrugada). São 3 rotas de sanção por CNPJ,
# então 50 clientes = 150 requisições em rajada — a partir da ~90ª vem 429 e o
# elo de regularidade derruba a cadeia. Com 3 clientes isso nunca apareceu.
_INTERVALO = float(os.environ.get("TUIU_TRANSPARENCIA_INTERVALO", "0.75"))  # ~80/min
_ultimo_get = 0.0


def _respirar() -> None:
    global _ultimo_get
    espera = _INTERVALO - (time.monotonic() - _ultimo_get)
    if espera > 0:
        time.sleep(espera)
    _ultimo_get = time.monotonic()


def _get(path: str, params: dict, chave: str, tentativas: int = 4):
    url = f"{BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"chave-api-dados": chave, "Accept": "application/json"})
    for n in range(tentativas):
        _respirar()
        try:
            with urllib.request.urlopen(req, timeout=60, context=_CTX) as r:
                corpo = json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            if e.code == 429 and n < tentativas - 1:
                # respeita o Retry-After quando vem; senão recua exponencialmente
                pausa = float(e.headers.get("Retry-After") or 0) or min(60.0, 5.0 * 2 ** n)
                print(f"  [429] limite da CGU — aguardando {pausa:.0f}s", flush=True)
                time.sleep(pausa)
                continue
            return None, f"HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}"
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            # Rede instável NÃO é resposta da API, e por isso não pode escapar:
            # `TimeoutError` não é `HTTPError`, então passava direto pelo except
            # acima, subia pelo processo e matava a cadeia diária inteira. Foi o
            # que derrubou 31/07, 01/08 e 02/08 — três dias sem recálculo de
            # prazo por um pico de latência da CGU.
            #
            # HTTPError é subclasse de URLError: a ordem dos `except` importa e
            # este tem que vir DEPOIS, senão engole erro de aplicação como se
            # fosse rede.
            if n < tentativas - 1:
                pausa = min(60.0, 5.0 * 2 ** n)
                print(f"  [rede] {type(e).__name__} — repetindo em {pausa:.0f}s", flush=True)
                time.sleep(pausa)
                continue
            return None, f"rede indisponível após {tentativas} tentativas: {type(e).__name__}"
        # Armadilha 2: erro pode vir com 200 e corpo dict
        if not isinstance(corpo, list):
            return None, f"corpo nao-lista (erro disfarcado): {str(corpo)[:200]}"
        return corpo, None
    return None, "429 persistente apos as tentativas"


def convenios(chave: str | None = None, **filtros) -> tuple[list[dict], str | None]:
    """Pagina até vir vazio (armadilha 3). Exige ao menos um filtro restritivo
    (armadilha 1): codigoIBGE, uf(+datas), convenente, orgao ou numero."""
    chave = chave or _chave()
    saida, pagina = [], 1
    while True:
        lote, erro = _get("convenios", {**filtros, "pagina": pagina}, chave)
        if erro:
            return saida, erro
        if not lote:
            break
        saida.extend(lote)
        if len(lote) < PAGINA:  # última página parcial
            break
        pagina += 1
        if pagina > 400:  # trava de segurança (6.000 registros)
            return saida, "limite de paginas atingido"
    return saida, None


def normalizar(c: dict) -> dict:
    """Extrai os campos úteis já corrigindo os bugs do payload (armadilha 4)."""
    conv = c.get("convenente") or {}
    ti = c.get("tipoInstrumento") or {}
    mun = c.get("municipioConvenente") or {}
    uf = mun.get("uf") or {}
    # 4a: sigla/nome trocados -> a SIGLA verdadeira é a de 2 letras
    a, b = (uf.get("sigla") or ""), (uf.get("nome") or "")
    sigla = a if len(a) == 2 else (b if len(b) == 2 else a)
    nome_uf = b if len(a) == 2 else a
    tid = ti.get("id")
    dim = c.get("dimConvenio") or {}
    return {
        "id": c.get("id"),
        "numero": dim.get("numero") or c.get("numeroProcesso"),
        # dimConvenio.codigo == NR_CONVENIO do SICONV (chave p/ cruzar com o detru)
        "codigo_siconv": (dim.get("codigo") or "").strip(),
        "objeto": (dim.get("objeto") or "").strip(),
        "cnpj_convenente": "".join(ch for ch in str(conv.get("cnpjFormatado") or conv.get("cnpj") or "") if ch.isdigit()),
        "nome_convenente": conv.get("nome") or conv.get("razaoSocialReceita"),
        "municipio": mun.get("nomeIBGE") or mun.get("nome"), "uf": sigla, "uf_nome": nome_uf,
        "tipo_id": tid,
        "tipo": TIPO_INSTRUMENTO.get(tid, (ti.get("descricao") or "").strip()),  # 4b: id manda
        "situacao": (c.get("situacao") or {}).get("descricao") if isinstance(c.get("situacao"), dict) else c.get("situacao"),
        "valor": c.get("valor"), "valor_liberado": c.get("valorLiberado"),
        "inicio_vigencia": c.get("dataInicioVigencia"), "fim_vigencia": c.get("dataFinalVigencia"),
        "orgao": (c.get("orgao") or {}).get("nome"),
    }


if __name__ == "__main__":
    ibge = sys.argv[1] if len(sys.argv) > 1 else "5200258"
    regs, erro = convenios(codigoIBGE=ibge)
    print(f"codigoIBGE={ibge}: {len(regs)} convenios" + (f" | ERRO: {erro}" if erro else ""))
    for c in (normalizar(x) for x in regs[:5]):
        print(f"  {c['numero']} | {c['tipo']} | {c['nome_convenente'][:38] if c['nome_convenente'] else '?'} "
              f"| {c['municipio']}/{c['uf']} | {c['situacao']}")
