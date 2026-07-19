"""Regularidade do TERCEIRO EXECUTOR (OSC/entidade privada) — CEPIM, CEIS, CNEP.

Escopo corrigido pelo dono (18/07): o cliente do Tuiú é o **terceiro que executa
o plano em prol de um ente/órgão público** (OSC, associação, fundação,
cooperativa, empresa), não a prefeitura. Logo, a regularidade que importa NÃO é
o CAUC (que mede obrigações fiscais do ENTE: RREO/RGF, Fundeb, SIAFIC, mínimos
de saúde/educação), e sim os cadastros que **impedem o terceiro de celebrar**:

  CEPIM — Entidades Privadas Sem Fins Lucrativos IMPEDIDAS (o mais direto:
          impedimento de celebrar convênio/termo com a União)
  CEIS  — Empresas Inidôneas e Suspensas (impedimento de licitar/contratar)
  CNEP  — Empresas Punidas (Lei Anticorrupção 12.846/2013)

⚠️ ARMADILHA 5 (descoberta 18/07, some com a casa se não for lembrada):
    **CEIS/CNEP IGNORAM SILENCIOSAMENTE filtros desconhecidos** e devolvem a
    primeira página inteira (15 registros de terceiros aleatórios). Só
    `codigoSancionado` filtra de fato. Portanto, além de usar o parâmetro certo,
    este módulo **reconfere o documento de cada registro retornado** — se não
    casar com o consultado, descarta. Sem isso, o produto acusaria o cliente de
    uma sanção que é de outra pessoa.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cliente_transparencia import _chave, _get  # noqa: E402


def _digitos(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _doc_do_registro(r: dict) -> str:
    """Documento do sancionado, olhando as formas que a API usa em cada rota."""
    for caminho in (("sancionado", "codigoFormatado"), ("pessoaJuridica", "cnpjFormatado"),
                    ("pessoa", "cnpjFormatado"), ("pessoa", "cpfFormatado")):
        v = r
        for k in caminho:
            v = (v or {}).get(k) if isinstance(v, dict) else None
        d = _digitos(v)
        if d and "*" not in str(v):  # CPF vem mascarado em `pessoa`
            return d
    return ""


def _consultar(rota: str, doc: str, chave: str) -> tuple[list[dict], str | None]:
    """Consulta uma rota de sanção e SÓ devolve registros cujo documento casa."""
    lote, erro = _get(rota, {"codigoSancionado": doc, "pagina": 1}, chave)
    if erro:
        return [], erro
    casados = [r for r in (lote or []) if _doc_do_registro(r) == doc]
    descartados = len(lote or []) - len(casados)
    aviso = (f"{descartados} registro(s) descartado(s) por não casar com o documento "
             f"(filtro ignorado pela API — ver armadilha 5)") if descartados else None
    return casados, aviso


def consultar(cnpj: str) -> dict:
    doc = _digitos(cnpj)
    chave = _chave()
    saida = {"cnpj": doc, "impedido": False, "fontes": {}, "avisos": []}
    for rota, rotulo in (("cepim", "CEPIM — entidade privada impedida de celebrar"),
                         ("ceis", "CEIS — inidônea/suspensa de licitar e contratar"),
                         ("cnep", "CNEP — punida (Lei 12.846/2013)")):
        regs, aviso = _consultar(rota, doc, chave)
        if aviso:
            saida["avisos"].append(f"{rota}: {aviso}")
        saida["fontes"][rota] = {
            "rotulo": rotulo, "registros": len(regs),
            "detalhes": [{
                "motivo": r.get("motivo") or (r.get("tipoSancao") or {}).get("descricaoResumida"),
                "orgao": ((r.get("orgaoSuperior") or {}).get("nome")
                          or (r.get("orgaoSancionador") or {}).get("nome")),
                "inicio": r.get("dataInicioSancao"), "fim": r.get("dataFimSancao"),
                "convenio": (r.get("convenio") or {}).get("numero") if isinstance(r.get("convenio"), dict) else None,
            } for r in regs[:5]],
        }
        if regs:
            saida["impedido"] = True
    saida["base_legal"] = ("CEPIM (Decreto 6.170/2007 art. 6º e regulamentos), "
                           "CEIS/CNEP (Lei 12.846/2013; Lei 14.133/2021 art. 156)")
    return saida


if __name__ == "__main__":
    import json

    for cnpj in (sys.argv[1:] or ["20069629000103"]):
        r = consultar(cnpj)
        print(f"{r['cnpj']}: {'IMPEDIDO' if r['impedido'] else 'sem impedimento'}"
              + (f" | avisos: {r['avisos']}" if r["avisos"] else ""))
        for rota, f in r["fontes"].items():
            print(f"   {rota}: {f['registros']} registro(s)")
            for d in f["detalhes"]:
                print(f"      - {d['motivo']} | {d['orgao']} | {d['inicio']}–{d['fim'] or '—'}")


def _digitos_visiveis(cpf_mascarado: str) -> str:
    """"***790718**" -> "790718". Só os dígitos que a Receita deixa à mostra."""
    return "".join(c for c in str(cpf_mascarado or "") if c.isdigit())


def _mesmo_nome(a: str, b: str) -> bool:
    import unicodedata

    def n(s):
        s = unicodedata.normalize("NFD", (s or "").upper())
        return " ".join("".join(c for c in s if c.isalnum() or c.isspace()).split())
    return bool(n(a)) and n(a) == n(b)


def consultar_pessoa(nome: str, cpf_mascarado: str = "") -> dict:
    """Impedimento de DIRIGENTE (PF), buscando por NOME.

    Por que não por CPF: o QSA da Receita entrega o CPF **mascarado**
    ("***790718**"), e `codigoSancionado` exige o documento inteiro — mandar 6
    dígitos devolve vazio, o que pareceria "nada consta" sem ter consultado.

    O filtro `nomeSancionado` É honrado pela API (testado: nome inexistente
    devolve vazio em vez de despejar a 1ª página, que é o sintoma da armadilha
    5). Mas nome sozinho pega HOMÔNIMO — e dizer a um cliente que seu presidente
    está sancionado por engano é um estrago sério. Então:

      - o registro só conta como CASADO se os dígitos visíveis do CPF baterem;
      - se a sanção não expõe CPF, vira `a_confirmar` (humano decide), nunca
        impedimento automático.
    """
    chave = _chave()
    visiveis = _digitos_visiveis(cpf_mascarado)
    saida = {"nome": nome, "cpf": cpf_mascarado, "impedido": False,
             "a_confirmar": [], "fontes": {}, "avisos": []}

    for rota in ("ceis", "cnep"):
        lote, erro = _get(rota, {"nomeSancionado": nome, "pagina": 1}, chave)
        if erro:
            saida["avisos"].append(f"{rota}: {erro}")
            continue
        casados, confirmar = [], []
        for r in lote or []:
            if not _mesmo_nome(_nome_do_registro(r), nome):
                continue          # a API casa por prefixo/parcial; exigimos igual
            doc = _doc_do_registro(r)
            if visiveis and doc and visiveis in doc:
                casados.append(r)
            elif not doc:
                confirmar.append(r)
        saida["fontes"][rota] = {"registros": len(casados), "a_confirmar": len(confirmar)}
        if casados:
            saida["impedido"] = True
        saida["a_confirmar"] += [
            {"rota": rota, "motivo": (r.get("motivo") or "")[:180]} for r in confirmar]
    return saida


def _nome_do_registro(r: dict) -> str:
    for caminho in (("sancionado", "nome"), ("pessoa", "nome"), ("pessoaFisica", "nome")):
        v = r
        for k in caminho:
            v = (v or {}).get(k) if isinstance(v, dict) else None
        if v:
            return str(v)
    return ""
