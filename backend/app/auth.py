"""Autenticação do console — sessão por cookie, senha em scrypt, stdlib pura.

O console mostra CNPJ, contas, valores e prazos de 50 organizações reais. As
regras que valem aqui:

**Fail-closed.** Erro de banco, sessão duvidosa, qualquer imprevisto → NEGA. Um
falso "negado" é um login a repetir; um falso "autorizado" é dado de terceiro
exposto. Por isso `sessao_valida()` não tem `except` que devolve usuário.

**Senha nunca em claro, em lugar nenhum.** Nem em log, nem em URL, nem no banco.
`scrypt` com sal por usuário, comparação por `hmac.compare_digest`.

**Freio de força bruta.** Tentativas erradas por login/IP são contadas em
`acessos_log`; passou do teto na janela, recusa mesmo com a senha certa.

**Sem enumerar usuário.** Login inexistente e senha errada devolvem a MESMA
resposta — quem tenta não descobre quais contas existem.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from app.db import conectar

DURACAO_SESSAO_H = int(os.environ.get("TUIU_SESSAO_HORAS", "12"))
TENTATIVAS_MAX = int(os.environ.get("TUIU_TENTATIVAS_MAX", "8"))
JANELA_FREIO_MIN = int(os.environ.get("TUIU_JANELA_FREIO_MIN", "15"))
COOKIE = "tuiu_sessao"

_N, _R, _P = 2 ** 14, 8, 1   # custo do scrypt; ~100ms, suficiente e sem travar o host


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"{_N}${_R}${_P}${base64.b64encode(sal).decode()}${base64.b64encode(dk).decode()}"


def confere_senha(senha: str, guardado: str) -> bool:
    try:
        n, r, p, sal_b64, hash_b64 = guardado.split("$")
        dk = hashlib.scrypt(senha.encode(), salt=base64.b64decode(sal_b64),
                            n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except Exception:  # noqa: BLE001 — hash corrompido/formato estranho = não confere
        return False


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _registrar(con, login: str | None, sucesso: bool, motivo: str | None, ip: str | None) -> None:
    con.execute("INSERT INTO acessos_log (login, sucesso, motivo, ip) VALUES (%s,%s,%s,%s)",
                (login, sucesso, motivo, ip))


def _freado(con, login: str, ip: str | None) -> bool:
    """Muitas tentativas erradas recentes para este login OU este IP."""
    desde = _agora() - timedelta(minutes=JANELA_FREIO_MIN)
    n = con.execute(
        "SELECT count(*) FROM acessos_log WHERE NOT sucesso AND quando > %s"
        "  AND (login = %s OR (ip IS NOT NULL AND ip = %s))",
        (desde, login, ip)).fetchone()[0]
    return n >= TENTATIVAS_MAX


def criar_usuario(login: str, nome: str, senha: str, trocar_senha: bool = False) -> None:
    with conectar() as con:
        con.execute(
            "INSERT INTO usuarios (login, nome, senha_hash, trocar_senha) VALUES (%s,%s,%s,%s)"
            " ON CONFLICT (login) DO UPDATE SET nome=EXCLUDED.nome,"
            " senha_hash=EXCLUDED.senha_hash, trocar_senha=EXCLUDED.trocar_senha, ativo=true",
            (login.strip().lower(), nome, hash_senha(senha), trocar_senha))
        con.commit()


def trocar_senha(login: str, senha_atual: str, nova: str) -> tuple[bool, str]:
    if len(nova) < 12:
        return False, "a senha nova precisa de ao menos 12 caracteres"
    with conectar() as con:
        r = con.execute("SELECT senha_hash FROM usuarios WHERE login=%s AND ativo",
                        (login,)).fetchone()
        if not r or not confere_senha(senha_atual, r[0]):
            return False, "senha atual não confere"
        con.execute("UPDATE usuarios SET senha_hash=%s, trocar_senha=false WHERE login=%s",
                    (hash_senha(nova), login))
        # trocar a senha derruba as outras sessões — é o ponto de trocar
        con.execute("DELETE FROM sessoes WHERE login=%s", (login,))
        con.commit()
    return True, "senha trocada; entre de novo"


def autenticar(login: str, senha: str, ip: str | None = None,
               agente: str | None = None) -> tuple[str | None, str]:
    """Devolve (token, mensagem). Token None = não entrou."""
    login = (login or "").strip().lower()
    if not login or not senha:
        return None, "informe usuário e senha"
    with conectar() as con:
        if _freado(con, login, ip):
            _registrar(con, login, False, "freio de tentativas", ip)
            con.commit()
            return None, "muitas tentativas; espere alguns minutos"

        r = con.execute("SELECT senha_hash, ativo FROM usuarios WHERE login=%s", (login,)).fetchone()
        # mesma resposta para usuário inexistente e senha errada: quem tenta não
        # pode descobrir quais contas existem
        if not r or not r[1] or not confere_senha(senha, r[0]):
            _registrar(con, login, False, "usuário ou senha", ip)
            con.commit()
            return None, "usuário ou senha inválidos"

        token = secrets.token_urlsafe(32)
        con.execute(
            "INSERT INTO sessoes (token, login, expira_em, ip, agente) VALUES (%s,%s,%s,%s,%s)",
            (token, login, _agora() + timedelta(hours=DURACAO_SESSAO_H), ip, (agente or "")[:200]))
        con.execute("UPDATE usuarios SET ultimo_acesso=now() WHERE login=%s", (login,))
        _registrar(con, login, True, None, ip)
        con.commit()
    return token, "ok"


def sessao_valida(token: str | None) -> dict | None:
    """Usuário da sessão, ou None. Sem `except` que devolve usuário: qualquer
    falha aqui tem que virar 'não autenticado'."""
    if not token:
        return None
    try:
        with conectar() as con:
            r = con.execute(
                "SELECT s.login, u.nome, u.trocar_senha FROM sessoes s"
                " JOIN usuarios u ON u.login = s.login"
                " WHERE s.token=%s AND s.expira_em > now() AND u.ativo", (token,)).fetchone()
    except Exception:  # noqa: BLE001 — banco fora do ar NÃO libera o console
        return None
    if not r:
        return None
    return {"login": r[0], "nome": r[1], "trocar_senha": r[2]}


def encerrar(token: str | None) -> None:
    if not token:
        return
    try:
        with conectar() as con:
            con.execute("DELETE FROM sessoes WHERE token=%s", (token,))
            con.commit()
    except Exception:  # noqa: BLE001
        pass


def limpar_expiradas() -> int:
    with conectar() as con:
        n = con.execute("DELETE FROM sessoes WHERE expira_em < now()").rowcount
        con.commit()
    return n


def ha_usuario() -> bool:
    """Se não há usuário ativo, ninguém entra — e o console avisa em vez de
    deixar a porta encostada."""
    try:
        with conectar() as con:
            return con.execute("SELECT count(*) FROM usuarios WHERE ativo").fetchone()[0] > 0
    except Exception:  # noqa: BLE001
        return False
