"""Ensaio de ponta a ponta com os dados fictícios e um modelo simulado.

    python ensaio.py --base "postgresql://utilizador:senha@localhost/ensaio"

Precisa de uma base PostgreSQL VAZIA (recusa-se a correr numa base com tabelas). Faz,
por ordem, o que uma instalação nova faria:

  1. esquema.sql e dados_iniciais.sql;
  2. carga inicial (carga/carga.py) com as extrações e os registos desta pasta;
  3. um utilizador por comercial e um gestor, todos com a palavra-passe «exemplo1234»;
  4. o ciclo noturno (ciclo.py), com um modelo SIMULADO no lugar do LLM: regras de
     palavras-chave que devolvem pares no formato do esquema. Serve para ver o resto do
     sistema a funcionar sem servidor de modelos; não diz nada sobre a qualidade da
     classificação, que se mede no Capítulo 6 com o modelo real;
  5. as vistas do dashboard pela API, como o comercial e como o gestor.

Para usar o modelo real em vez do simulado, correr o passo 4 à mão (python ciclo.py
--sem-espera) com o servidor ollama e o gemma4:26b, e o .env a apontar para esta base.
Depois: cd dashboard; uvicorn server:app --port 8000, e entrar com um dos utilizadores.
"""

import argparse
import json
import os
import re
import runpy
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent


def aplicar_sql(url, ficheiro):
    import psycopg2
    conn = psycopg2.connect(url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(ficheiro.read_text(encoding="utf-8"))
    conn.close()


def base_vazia(url) -> bool:
    import psycopg2
    conn = psycopg2.connect(url)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        n = cur.fetchone()[0]
    conn.close()
    return n == 0


ESTADOS = [  # palavra-chave do relato -> estado, pela ordem em que se testam
    ("entregue", "8. Fechado"), ("em produção", "7. Em Produção / Entrega"),
    ("encomenda", "6. Encomenda Confirmada"), ("aprovada", "5. Aprovação Interna"),
    ("desconto", "4. Negociação"), ("proposta", "3. Proposta / Orçamento"),
    ("orçamento", "3. Proposta / Orçamento"), ("sem novidades", "10. Indeterminado"),
    ("demonstração", "2. Qualificação"), ("pediram", "2. Qualificação"), ("interesse", "2. Qualificação"),
]


def modelo_simulado(sistema, mensagem, modelo, esquema):
    """Devolve (texto, tokens_in, tokens_out) como os caminhos reais de llm.py."""
    import llm
    rel = re.search(r"^\s+rel\s+(.*)$", mensagem, re.M)
    classif = re.search(r"^\s+u_classif\s+(.*)$", mensagem, re.M)
    rel = rel.group(1).strip() if rel else ""
    classif = classif.group(1).strip().upper() if classif else ""
    abertos = llm.negocios_abertos(mensagem)
    baixo = rel.lower()
    if not rel or "cortesia" in baixo or "não atenderam" in baixo:
        return json.dumps({"pares": []}), 0, 0
    tipo = {"EQUIPAMENTOS": "equipamento", "SERVIÇO": "producao", "CONSUMIVEIS": "consumiveis"}.get(classif, "lead")
    if tipo == "consumiveis" and "materiais" not in baixo and "componentes" not in baixo:
        tipo = "lead"
    nid = next((i for i, t in abertos if t == tipo), "NOVO")
    estado = None
    if tipo != "consumiveis":
        estado = next((e for k, e in ESTADOS if k in baixo), "1. Lead / Prospeção" if tipo == "lead" else "2. Qualificação")
        if tipo == "lead" and estado not in ("1. Lead / Prospeção", "2. Qualificação"):
            estado = "1. Lead / Prospeção"
    excerto = re.split(r"(?<=[.;])\s", rel)[0]
    return json.dumps({"pares": [{"negocio_id": nid, "tipo": tipo, "estado": estado, "excerto": excerto}]}), 0, 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="URL de uma base PostgreSQL vazia")
    a = ap.parse_args()
    if not base_vazia(a.base):
        sys.exit("a base tem tabelas: o ensaio só corre numa base vazia")

    os.environ.update({"NEON_DATABASE_URL": a.base, "DB_MODO": "tcp", "ERP_PASTA": str(AQUI),
                       "BACKEND": "simulado", "MODELO": "simulado", "PROMPT_VERSION": "c05r"})
    print("1. esquema e dados iniciais")
    aplicar_sql(a.base, RAIZ / "esquema.sql")
    aplicar_sql(a.base, RAIZ / "dados_iniciais.sql")

    print("2. carga inicial")
    subprocess.run([sys.executable, str(RAIZ / "carga" / "carga.py"), "--erp", str(AQUI), "--registos", str(AQUI)],
                   check=True, env=os.environ)

    for sub in ("classificador", "dashboard", "carga"):
        sys.path.insert(0, str(RAIZ / sub))
    import auth, db, llm  # noqa: E401
    llm.BACKENDS["simulado"] = modelo_simulado

    print("3. utilizadores")
    import pandas as pd
    from extracoes import VISITAS, mais_recente
    vendedores = sorted(pd.read_excel(mais_recente(AQUI, VISITAS))["vendnm"].dropna().unique())
    L = db.Ligacao()

    def criar(conn):
        with conn.cursor() as cur:
            for v in vendedores:
                cur.execute("INSERT INTO utilizadores (login, nome, vendedor, papel, senha_hash) VALUES (%s,%s,%s,'comercial',%s)",
                            (v.lower().replace("av-", ""), v, v, auth.cifrar("exemplo1234")))
            cur.execute("INSERT INTO utilizadores (login, nome, papel, senha_hash) VALUES ('gestor','Gestor','gestor',%s)",
                        (auth.cifrar("exemplo1234"),))
        conn.commit()
    L.executar(criar)
    print("   ", ", ".join(v.lower().replace("av-", "") for v in vendedores), "e gestor")

    print("4. ciclo noturno, com o modelo simulado")
    sys.argv = ["ciclo.py", "--sem-espera"]
    try:
        runpy.run_path(str(RAIZ / "ciclo.py"), run_name="__main__")
    except SystemExit as e:
        if e.code not in (0, None):
            sys.exit("o ciclo falhou: ver logs/")

    print("5. dashboard")
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    falhas = 0

    def ver(rotulo, r):
        nonlocal falhas
        ok = r.status_code == 200
        falhas += not ok
        print(f"    {'ok ' if ok else 'ERRO'} {rotulo} ({r.status_code})")
        return r.json() if ok else {}

    um = vendedores[0].lower().replace("av-", "")
    ver(f"entrar como {um}", c.post("/api/entrar", json={"login": um, "senha": "exemplo1234"}))
    p = ver("página do comercial", c.get("/api/pagina"))
    print(f"      {len(p.get('negocios', []))} negócios na carteira, {len(p.get('alertas', []))} alertas, "
          f"{len(p.get('consumo', []))} clientes de consumíveis a acompanhar, {len(p.get('dias', []))} dias para rever")
    if p.get("dias"):
        ver("revisão de um dia", c.get("/api/lote", params={"dia": p["dias"][0]["dia"]}))
    c.post("/api/sair")
    ver("entrar como gestor", c.post("/api/entrar", json={"login": "gestor", "senha": "exemplo1234"}))
    for rota in ("/api/equipa", "/api/pipeline", "/api/qualidade", "/api/parametros"):
        ver(rota, c.get(rota))
    L.fechar()
    print("ensaio concluído" if not falhas else f"ensaio com {falhas} erros")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
