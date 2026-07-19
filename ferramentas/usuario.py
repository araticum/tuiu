"""Contas do console — criar, listar, desativar, resetar senha.

A senha NUNCA é escolhida por quem roda a ferramenta a partir de argumento de
linha de comando (fica no histórico do shell e no `ps`), nem é impressa na tela
(vai para o log da sessão). O caminho é:

  1. a ferramenta sorteia uma senha forte;
  2. grava em `.senha-inicial-<login>` na raiz do repo, com permissão 600;
  3. imprime só o CAMINHO do arquivo.

Quem criou a conta lê o arquivo, entra, troca a senha no console e apaga o
arquivo. A conta nasce com `trocar_senha=true`.

Uso:
    python ferramentas/usuario.py --criar pedro --nome "Pedro Lopes"
    python ferramentas/usuario.py --listar
    python ferramentas/usuario.py --desativar fulano
    python ferramentas/usuario.py --resetar pedro
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app.auth import criar_usuario  # noqa: E402
from app.db import conectar, migrar  # noqa: E402

ALFABETO = string.ascii_letters + string.digits + "!@#%*-_=+?"


def _sortear(n: int = 20) -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(n))


def _guardar(login: str, senha: str) -> Path:
    alvo = RAIZ / f".senha-inicial-{login}"
    # cria com 600 desde o nascimento — sem janela em que o arquivo fica legível
    fd = os.open(alvo, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"login: {login}\nsenha: {senha}\n\n"
                 "Entre, troque a senha no console e APAGUE este arquivo.\n")
    try:
        os.chmod(alvo, 0o600)  # Windows ignora, mas no host vale
    except OSError:
        pass
    return alvo


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--criar", metavar="LOGIN")
    ap.add_argument("--nome", default=None)
    ap.add_argument("--resetar", metavar="LOGIN")
    ap.add_argument("--desativar", metavar="LOGIN")
    ap.add_argument("--listar", action="store_true")
    args = ap.parse_args()

    migrar()

    if args.criar or args.resetar:
        login = (args.criar or args.resetar).strip().lower()
        senha = _sortear()
        criar_usuario(login, args.nome or login, senha, trocar_senha=True)
        alvo = _guardar(login, senha)
        print(f"conta '{login}' pronta (precisa trocar a senha no 1o acesso)")
        print(f"senha inicial gravada em: {alvo}")
        print("leia, entre, troque a senha e apague o arquivo.")
        return

    if args.desativar:
        with conectar() as con:
            n = con.execute("UPDATE usuarios SET ativo=false WHERE login=%s",
                            (args.desativar.strip().lower(),)).rowcount
            # desativar tem que derrubar a sessão aberta, senão a conta segue viva
            s = con.execute("DELETE FROM sessoes WHERE login=%s",
                            (args.desativar.strip().lower(),)).rowcount
            con.commit()
        print(f"desativados: {n} | sessões encerradas: {s}")
        return

    with conectar() as con:
        linhas = con.execute(
            "SELECT login, nome, ativo, trocar_senha, ultimo_acesso FROM usuarios ORDER BY login"
        ).fetchall()
    if not linhas:
        print("nenhuma conta — crie com --criar <login>")
    for lg, nome, ativo, trocar, ult in linhas:
        marca = "ativo " if ativo else "INATIVO"
        pend = " (senha inicial pendente)" if trocar else ""
        print(f"  {marca}  {lg:16s} {nome[:28]:28s} último acesso: {ult or '—'}{pend}")


if __name__ == "__main__":
    main()
