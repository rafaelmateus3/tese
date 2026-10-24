"""Congela a entrada v2 do benchmark a partir da v1.

    python congelar_v2.py

Só o bloco de negócios muda. O resto da mensagem, campos do relatório e
relatórios anteriores incluídos, é copiado da v1 tal como está, para que a
diferença entre as duas versões da entrada seja exactamente uma.
"""

import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "classificador"))
sys.path.insert(0, str(AQUI.parent / "classificador" / "prompts"))

import db                      # noqa: E402
from contexto_v2 import Contexto   # noqa: E402
from marcas import MARCAS      # noqa: E402

RAIZ = AQUI.parent
VISITAS = RAIZ / "extracoes/visitas_2026-09-06T16_36_56.127644534Z.xlsx"
FATURAS = RAIZ / "extracoes/linhas_faturas_2026-09-06T16_36_31.753542795Z.xlsx"
GOLD = RAIZ / "dados/260922_Gold_Anotacao_Pares_v7.xlsx"

BLOCO = re.compile(r"  <negocios_abertos>\n.*?</negocios_abertos>\n", re.S)
DATA = re.compile(r"^\s+data\s+(\d{4}-\d\d-\d\d)", re.M)


def _ler(caminho: Path) -> pd.DataFrame:
    cache = Path("/tmp") / (caminho.stem + ".pkl")
    if cache.exists():
        return pd.read_pickle(cache)
    return pd.read_excel(caminho)


def main():
    v = _ler(VISITAS)
    v["data"] = pd.to_datetime(v["data"])
    for c in ("rel", "resumo", "u_classif", "u_anegocio"):
        v[c] = v[c].fillna("").astype(str)
    f = _ler(FATURAS)
    f["Data do Documento"] = pd.to_datetime(f["Data do Documento"])

    g = pd.read_excel(GOLD, sheet_name="Anotação", usecols=["#", "vistamp"])
    linha = {str(r.vistamp).strip(): int(r._1) for r in g.itertuples()}

    L = db.Ligacao()
    try:
        def ler(c):
            with c.cursor() as cur:
                cur.execute("SELECT negocio_id, cliente_no, tipo, inicio FROM negocios")
                reg = cur.fetchall()
                cur.execute("""SELECT vistamp, cliente_no, cliente, estrato, mensagem
                                 FROM benchmark_entradas WHERE entrada_version = 'v1'""")
                ent = cur.fetchall()
            return reg, ent
        registo, v1 = L.executar(ler)
        ctx = Contexto(v, f, registo, MARCAS)

        mudou = com_ciclo_v1 = com_ciclo_v2 = 0
        linhas_v2 = []
        for vistamp, no, cliente, estrato, msg in v1:
            quando = date.fromisoformat(DATA.search(msg).group(1))
            bloco, ids = ctx.bloco(int(no), quando)
            if BLOCO.search(msg):
                novo = BLOCO.sub(lambda _m: bloco, msg)
            else:
                novo = msg.replace("</report>", bloco + "</report>")
            mudou += int(novo != msg)
            com_ciclo_v1 += int(bool(re.search(r"\| (equipamento|producao) \|", msg)))
            com_ciclo_v2 += int(any(not i.startswith("NG-C") for i in ids))
            linhas_v2.append((vistamp, no, cliente, estrato, novo, linha.get(vistamp)))

        if "--verificar" in sys.argv:
            actuais = {v: m for v, _n, _c, _e, m in L.executar(lambda c: (lambda cur: (
                cur.execute("SELECT vistamp, cliente_no, cliente, estrato, mensagem "
                            "FROM benchmark_entradas WHERE entrada_version = 'v2'"),
                cur.fetchall())[1])(c.cursor()))}
            dif = [(ln, vs) for vs, _n, _c, _e, msg, ln in linhas_v2 if actuais.get(vs) != msg]
            print("mudariam na v2:", sorted(dif))
            return

        def gravar(c):
            with c.cursor() as cur:
                for vistamp, no, cliente, estrato, msg, ln in linhas_v2:
                    cur.execute("""
                        INSERT INTO benchmark_entradas (vistamp, entrada_version,
                               cliente_no, cliente, estrato, mensagem, linha)
                        VALUES (%s, 'v2', %s, %s, %s, %s, %s)
                        ON CONFLICT (vistamp, entrada_version) DO UPDATE SET
                            mensagem = EXCLUDED.mensagem, linha = EXCLUDED.linha,
                            congelada_em = now()""",
                        (vistamp, no, cliente, estrato, msg, ln))
                    cur.execute("""UPDATE benchmark_entradas SET linha = %s
                                    WHERE vistamp = %s AND entrada_version = 'v1'""",
                                (ln, vistamp))
            c.commit()
        L.executar(gravar)
    finally:
        L.fechar()

    print(f"v2 congelada: {len(linhas_v2)} relatórios, {mudou} com bloco alterado")
    print(f"com negócio do ciclo no bloco: v1 {com_ciclo_v1}, v2 {com_ciclo_v2}")
    print(f"episódios sem identificador no registo: {ctx.sem_registo}")


if __name__ == "__main__":
    main()
