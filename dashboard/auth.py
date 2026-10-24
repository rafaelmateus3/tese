"""Autenticação do dashboard.

Dois papéis:
  comercial  vê e corrige só o que é seu (a sua carteira, os seus alertas, os
             seus relatórios)
  gestor     vê todos, ratifica correções e altera os parâmetros

A palavra-passe guarda-se com scrypt (biblioteca padrão) e nunca em claro. A
sessão é um token aleatório num cookie HttpOnly, válido SESSAO_HORAS horas.
Os utilizadores criam-se na linha de comandos (utilizadores.py), não pelo
dashboard.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

SESSAO_HORAS = int(os.getenv("SESSAO_HORAS", "12"))
COOKIE = "sad_sessao"
# Em HTTPS o cookie só viaja cifrado. Numa rede interna sem HTTPS fica a 0.
COOKIE_SEGURO = os.getenv("COOKIE_SEGURO", "0") == "1"

_N, _R, _P = 2 ** 14, 8, 1


def cifrar(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P)
    return f"scrypt${sal.hex()}${h.hex()}"


def confere(senha: str, guardado: str) -> bool:
    try:
        _, sal, h = guardado.split("$")
        novo = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal), n=_N, r=_R, p=_P)
        return hmac.compare_digest(novo.hex(), h)
    except ValueError:
        return False


def entrar(conn, login: str, senha: str) -> str | None:
    """Devolve o token da sessão, ou None se as credenciais não servem."""
    with conn.cursor() as cur:
        cur.execute("SELECT senha_hash FROM utilizadores WHERE login = %s AND ativo", (login,))
        linha = cur.fetchone()
        if not linha or not confere(senha, linha[0]):
            return None
        token = secrets.token_urlsafe(32)
        cur.execute("DELETE FROM sessoes WHERE expira_em < now()")
        cur.execute("INSERT INTO sessoes (token, login, expira_em) VALUES (%s, %s, %s)",
                    (token, login, datetime.now() + timedelta(hours=SESSAO_HORAS)))
    conn.commit()
    return token


def sair(conn, token: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sessoes WHERE token = %s", (token,))
    conn.commit()


def quem(conn, token: str | None) -> dict | None:
    if not token:
        return None
    with conn.cursor() as cur:
        cur.execute("""SELECT u.login, u.nome, u.vendedor, u.papel
                         FROM sessoes s JOIN utilizadores u ON u.login = s.login
                        WHERE s.token = %s AND s.expira_em > now() AND u.ativo""", (token,))
        linha = cur.fetchone()
    if not linha:
        return None
    return dict(zip(("login", "nome", "vendedor", "papel"), linha))
