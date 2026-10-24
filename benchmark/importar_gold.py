"""Importa a anotação do Excel para a base de dados.

    python importar_gold.py --gold ..\\dados\\260922_Gold_Anotacao_Pares_v7.xlsx

Grava duas versões de cada anotação:

  v1  tal como está no Excel, porque foi contra a entrada v1 que foi feita e é
      com as corridas v1 que se compara;
  v2  com os identificadores ajustados à entrada v2. Um par que aponta para um
      negócio que não está no bloco v2 desse relatório passa a NOVO: é o caso
      do negócio que nasceu do próprio relatório e que, à data, ainda não
      existia. Um par sem identificador passa também a NOVO. Em ambos os casos
      a anotação fica marcada com dúvida e com uma nota, para ser revista na
      interface.

Correr de novo substitui o que foi importado, mas não toca em anotações que
já tenham sido gravadas pela interface depois da importação.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))

import db  # noqa: E402

LINHA_NEG = re.compile(r"^\s+(\S+)\s*\|\s*([^|]+?)\s*\|", re.M)
BLOCO = re.compile(r"<negocios_abertos>(.*?)</negocios_abertos>", re.S)


def _t(v):
    return str(v).strip() if pd.notna(v) and str(v).strip() else None


def ler(caminho: Path) -> list[dict]:
    d = pd.read_excel(caminho, sheet_name="Anotação")
    d = d[d["CONTEUDO_COMERCIAL"].notna()]
    out = []
    for _, r in d.iterrows():
        pares = []
        for p in ("P1", "P2", "P3"):
            if _t(r[f"{p}_TIPO"]):
                pares.append({"negocio_id": _t(r[f"{p}_NEGOCIO"]),
                              "tipo": _t(r[f"{p}_TIPO"]),
                              "estado": _t(r[f"{p}_ESTADO"]),
                              "excerto": _t(r[f"{p}_EXCERTO"]) or ""})
        out.append({"vistamp": str(r["vistamp"]).strip(), "linha": int(r["#"]),
                     "comercial": str(r["CONTEUDO_COMERCIAL"]).strip().upper() == "S",
                     "pares": pares, "duvida": bool(_t(r.get("DUVIDA"))),
                     "nota": _t(r.get("NOTA")) or ""})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gold", type=Path, required=True)
    args = ap.parse_args()
    anot = ler(args.gold)

    L = db.Ligacao()
    try:
        def blocos(c):
            with c.cursor() as cur:
                cur.execute("SELECT vistamp, mensagem FROM benchmark_entradas "
                            "WHERE entrada_version = 'v2'")
                out = {}
                for v, m in cur.fetchall():
                    b = BLOCO.search(m)
                    out[v] = {i for i, _t in LINHA_NEG.findall(b.group(1))} if b else set()
                return out
        v2 = L.executar(blocos)

        remapeados = []

        def gravar(c):
            with c.cursor() as cur:
                for a in anot:
                    # v1: tal como foi anotado
                    linhas = [("v1", a["pares"], a["duvida"], a["nota"])]
                    # v2: identificadores ajustados à entrada v2
                    pares2, notas = [], []
                    for p in a["pares"]:
                        q = dict(p)
                        if not q["negocio_id"]:
                            q["negocio_id"] = "NOVO"
                            notas.append(f"par de {q['tipo']} sem negócio passou a NOVO")
                        elif q["negocio_id"] != "NOVO" and q["negocio_id"] not in v2.get(a["vistamp"], set()):
                            notas.append(f"{q['negocio_id']} não estava aberto à data "
                                         f"(nasceu deste relatório): passou a NOVO")
                            q["negocio_id"] = "NOVO"
                        pares2.append(q)
                    nota2 = a["nota"]
                    if notas:
                        remapeados.append(a["linha"])
                        nota2 = (nota2 + " | " if nota2 else "") + "[importação] " + "; ".join(notas)
                    linhas.append(("v2", pares2, a["duvida"] or bool(notas), nota2))
                    for versao, pares, duvida, nota in linhas:
                        cur.execute("""
                            INSERT INTO gold_anotacoes (vistamp, entrada_version, comercial,
                                   pares, duvida, nota, origem, anotador)
                            VALUES (%s, %s, %s, %s::jsonb, %s, %s, 'importacao_v7', 'autor')
                            ON CONFLICT (vistamp, entrada_version) DO UPDATE SET
                                comercial = EXCLUDED.comercial, pares = EXCLUDED.pares,
                                duvida = EXCLUDED.duvida, nota = EXCLUDED.nota,
                                origem = EXCLUDED.origem, atualizado_em = now()
                            WHERE gold_anotacoes.origem = 'importacao_v7'""",
                            (a["vistamp"], versao, a["comercial"],
                             json.dumps(pares, ensure_ascii=False), duvida, nota))
                        cur.execute("""
                            INSERT INTO gold_anotacoes_hist (vistamp, entrada_version,
                                   comercial, pares, duvida, nota, origem, anotador)
                            VALUES (%s, %s, %s, %s::jsonb, %s, %s, 'importacao_v7', 'autor')""",
                            (a["vistamp"], versao, a["comercial"],
                             json.dumps(pares, ensure_ascii=False), duvida, nota))
            c.commit()
        L.executar(gravar)
    finally:
        L.fechar()
    print(f"{len(anot)} anotações importadas em v1 e v2")
    print(f"{len(remapeados)} com identificadores ajustados na v2, marcadas com dúvida: "
          + ", ".join(f"#{x}" for x in sorted(remapeados)))


if __name__ == "__main__":
    main()
