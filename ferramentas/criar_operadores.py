"""Cria em LOTE as contas do console, a partir dos nomes da lista de trabalho.

`usuario.py` cria uma conta por vez e grava a senha num arquivo próprio. Para 25
pessoas isso seria 25 comandos e 25 arquivos espalhados na raiz do repositório —
cada um um segredo solto esperando ser esquecido. Aqui a senha de todo mundo sai
numa folha só, com permissão 600, e o caminho é impresso uma vez.

## O que este comando garante

**Senha nunca passa por argumento nem por tela.** Ela é sorteada aqui, gravada
na folha e mais nada: argumento de linha de comando fica no histórico do shell e
no `ps`, e o que se imprime vai para o log da sessão.

**Não reseta quem já existe.** Rodar duas vezes por engano não pode derrubar a
senha de quem já entrou e trocou. Conta existente é PULADA e relatada; trocar a
senha de alguém é `--resetar`, explícito, um a um.

**Todo mundo nasce com `trocar_senha`.** A senha desta folha serve para o
primeiro acesso e morre ali.

## Sobre o papel

`leitor` vê a carteira inteira e não escreve nada. É o papel certo para começar,
e tem uma consequência que precisa ser dita: `fila.responsaveis()` só devolve
**operador**, então conta de leitor **não recebe item na distribuição**. Enquanto
as pessoas forem leitoras, a mesa continua sem dono. Promover é
`usuario.py --criar <login> --papel operador` (mesmo login, mantém a conta).

Uso:
    py -3 ferramentas/criar_operadores.py --nomes nomes.txt --papel leitor \\
        --tamanho 14 --saida /caminho/senhas.txt
    py -3 ferramentas/criar_operadores.py --nomes nomes.txt --simular
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import string
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))

from app.auth import criar_usuario  # noqa: E402
from app.db import conectar, migrar  # noqa: E402
from app.texto_br import qtd, verbo  # noqa: E402

# Mesmo alfabeto do `usuario.py`: letras, dígitos e pontuação segura. Sem
# ambiguidade visual removida de propósito — a senha é copiada e colada da folha,
# não digitada de cabeça, e reduzir o alfabeto reduz a entropia sem ganho real.
ALFABETO = string.ascii_letters + string.digits + "!@#%*-_=+?"
DOMINIO = "araticum.net"


def sortear(n: int) -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(n))


def login_de(nome: str) -> str:
    """`Karlla THuanny Ribeiro Araújo` -> `karlla.araujo`. Sem acento, sem caixa.

    Primeiro e ÚLTIMO nome, não primeiro e segundo: o último é o que distingue
    (`Maria Eduarda Teixeira dos Santos` e `Maria Eduarda Teixeira da Silva`
    colidiriam por `maria.eduarda`).
    """
    s = unicodedata.normalize("NFD", (nome or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    partes = [p for p in re.split(r"[^a-z]+", s) if p]
    if not partes:
        return ""
    return partes[0] if len(partes) == 1 else f"{partes[0]}.{partes[-1]}"


def ler_nomes(caminho: Path) -> list[str]:
    vistos, fora = set(), []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        nome = linha.strip()
        if not nome or nome.startswith("#"):
            continue
        if nome.lower() not in vistos:
            vistos.add(nome.lower())
            fora.append(nome)
    return fora


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--nomes", type=Path, required=True,
                    help="arquivo com um nome por linha")
    ap.add_argument("--papel", choices=("leitor", "operador"), default="leitor")
    ap.add_argument("--tamanho", type=int, default=14, help="caracteres da senha")
    ap.add_argument("--dominio", default=DOMINIO)
    ap.add_argument("--saida", type=Path, help="folha de senhas (permissão 600)")
    ap.add_argument("--simular", action="store_true", help="mostra o plano e não cria nada")
    args = ap.parse_args()

    if args.tamanho < 12:
        return int(bool(sys.stderr.write(
            "senha com menos de 12 caracteres não passa: o primeiro acesso é por ela\n")))

    nomes = ler_nomes(args.nomes)
    contas = []
    for nome in nomes:
        base = login_de(nome)
        if not base:
            print(f"  ! nome sem letra nenhuma, pulado: {nome!r}")
            continue
        contas.append({"nome": nome, "login": f"{base}@{args.dominio}"})

    colisoes = {c["login"] for c in contas
                if sum(1 for x in contas if x["login"] == c["login"]) > 1}
    if colisoes:
        print(f"! login repetido entre nomes diferentes: {', '.join(sorted(colisoes))}")
        print("  resolva antes — duas pessoas num login só é conta compartilhada.")
        return 1

    migrar()
    with conectar() as con:
        existentes = {l for (l,) in con.execute("SELECT login FROM usuarios")}

    novos = [c for c in contas if c["login"] not in existentes]
    pulados = [c for c in contas if c["login"] in existentes]

    print(f"{qtd(len(contas), 'nome na lista', 'nomes na lista')} · "
          f"{len(novos)} a criar · {len(pulados)} já {verbo(len(pulados), 'existe', 'existem')}")
    for c in pulados:
        print(f"  = {c['login']:38s} já existe — senha NÃO tocada ({c['nome']})")
    for c in novos:
        print(f"  + {c['login']:38s} {c['nome']}")

    if args.simular:
        print("\n(simulação — nada foi criado)")
        return 0
    if not novos:
        print("\nnada a criar.")
        return 0
    if not args.saida:
        print("\n--saida é obrigatório: a senha precisa de onde ser lida uma vez.")
        return 1

    for c in novos:
        c["senha"] = sortear(args.tamanho)
        criar_usuario(c["login"], c["nome"], c["senha"], trocar_senha=True, papel=args.papel)

    alvo = args.saida
    alvo.parent.mkdir(parents=True, exist_ok=True)
    corpo = [
        "SENHAS INICIAIS — Tuiú",
        f"gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · papel: {args.papel}",
        "",
        "Cada senha vale para UM acesso: o console exige a troca ao entrar.",
        "Entregue a cada pessoa só a linha dela e APAGUE este arquivo depois.",
        "",
    ]
    largura = max(len(c["login"]) for c in novos)
    for c in sorted(novos, key=lambda x: x["nome"]):
        corpo.append(f"{c['nome']}\n  {c['login']:<{largura}}   {c['senha']}\n")
    # 600 desde o nascimento: sem janela em que o arquivo fica legível por outros
    fd = os.open(alvo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(corpo))
    try:
        os.chmod(alvo, 0o600)
    except OSError:
        pass

    print(f"\n{qtd(len(novos), 'conta criada', 'contas criadas')} com papel {args.papel}.")
    print(f"folha de senhas: {alvo}")
    print("Distribua e APAGUE. Nenhuma senha foi impressa aqui nem gravada em outro lugar.")
    if args.papel == "leitor":
        print("\nAtenção: leitor NÃO recebe item na distribuição da fila "
              "(`fila.responsaveis()` só devolve operador).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
