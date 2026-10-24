"""Gestão dos utilizadores do dashboard, na linha de comandos.

    python utilizadores.py criar ana --nome "Ana Silva" --vendedor "ANA SILVA" --papel comercial
    python utilizadores.py criar gestor --nome "Gestor" --papel gestor
    python utilizadores.py senha ana          muda a palavra-passe
    python utilizadores.py desativar ana
    python utilizadores.py listar
    python utilizadores.py vendedores         os nomes de comercial que o ERP usa

A palavra-passe não fica no histórico da consola.
--vendedor tem de ser o nome exatamente como aparece no ERP (ver `vendedores`).
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))

import db    # noqa: E402

import auth  # noqa: E402


def _senha() -> str:
    while True:
        s = getpass.getpass("palavra-passe (mín. 10 caracteres): ")
        if len(s) < 10:
            print("curta demais")
        elif s != getpass.getpass("repetir: "):
            print("não coincidem")
        else:
            return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("acao", choices=["criar", "senha", "desativar", "listar", "vendedores"])
    ap.add_argument("login", nargs="?")
    ap.add_argument("--nome")
    ap.add_argument("--vendedor")
    ap.add_argument("--papel", choices=["comercial", "gestor"], default="comercial")
    a = ap.parse_args()
    L = db.Ligacao()

    def sql(q, p=(), ler=False):
        def f(c):
            with c.cursor() as cur:
                cur.execute(q, p)
                out = cur.fetchall() if ler else cur.rowcount
            c.commit()
            return out
        return L.executar(f)

    if a.acao == "listar":
        for l in sql("SELECT login, nome, papel, vendedor, ativo FROM utilizadores ORDER BY 1", ler=True):
            print(" | ".join(str(x) for x in l))
    elif a.acao == "vendedores":
        import pandas as pd
        from config import ERP_PASTA
        f = sorted(Path(ERP_PASTA).glob("visitas_*.xlsx"), key=lambda p: p.stat().st_mtime)[-1]
        for v in sorted(pd.read_excel(f, usecols=["vendnm"])["vendnm"].dropna().astype(str).str.strip().unique()):
            print(v)
    elif not a.login:
        sys.exit("falta o login")
    elif a.acao == "criar":
        if a.papel == "comercial" and not a.vendedor:
            sys.exit("um comercial precisa de --vendedor (o nome no ERP)")
        sql("INSERT INTO utilizadores (login, nome, vendedor, papel, senha_hash) VALUES (%s,%s,%s,%s,%s)",
            (a.login, a.nome or a.login, a.vendedor, a.papel, auth.cifrar(_senha())))
        print("criado")
    elif a.acao == "senha":
        n = sql("UPDATE utilizadores SET senha_hash = %s WHERE login = %s", (auth.cifrar(_senha()), a.login))
        sql("DELETE FROM sessoes WHERE login = %s", (a.login,))
        print("alterada" if n else "não existe")
    elif a.acao == "desativar":
        n = sql("UPDATE utilizadores SET ativo = FALSE WHERE login = %s", (a.login,))
        sql("DELETE FROM sessoes WHERE login = %s", (a.login,))
        print("desativado" if n else "não existe")
    L.fechar()


if __name__ == "__main__":
    main()
