"""Congela a entrada v3 a partir da v2: o bloco passa a funcionar como em produção.

    python congelar_v3.py              mostra o que mudaria
    python congelar_v3.py --gravar     congela (e, na primeira vez, copia o gold da v2)

Em produção os relatórios correm por data. Cada relatório vê os negócios abertos
do cliente com o último estado, e um NOVO passa a negócio aberto para os
relatórios seguintes. No benchmark faz-se o mesmo, com o gold no lugar das
previsões:

  - cada negócio do registo leva o último estado anotado antes da data do
    relatório, e a data dessa anotação;
  - um NOVO anotado num relatório anterior do mesmo cliente liga-se ao negócio
    do registo do mesmo tipo que está no bloco, se houver só um; se não houver
    nenhum, entra no bloco com um id NG-A…; se houver mais de um, não se sabe
    qual é e fica de fora (não se inventa a ligação);
  - sai do bloco o negócio em 8 ou 9, ou sem referência há mais de 180 dias
    (RF2.8).

Só o bloco muda; o resto da mensagem é o da v2. A lógica do bloco está em
classificador/bloco.py, partilhada com a produção.
"""
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI)); sys.path.insert(0, str(AQUI.parent / "classificador"))
import anotar  # noqa: E402
import bloco   # noqa: E402
import db      # noqa: E402

DATA = re.compile(r"^\s+data\s+(\d{4}-\d\d-\d\d)", re.M)
CICLO = bloco.CICLO


def dia(s):
    return date.fromisoformat(s)


def construir(origem=None):
    origem = origem or ORIGEM_GOLD
    ent = anotar._sql("SELECT vistamp, cliente_no, cliente, estrato, mensagem, linha FROM benchmark_entradas "
                      "WHERE entrada_version = 'v2'")
    gold = {v: p for v, p in anotar._sql("SELECT vistamp, pares FROM gold_anotacoes WHERE entrada_version = %s",
                                         (origem,))}
    rel = []
    for v, cno, cli, est, msg, ln in ent:
        rel.append({"v": v, "cno": cno, "cli": cli, "est": est, "msg": msg, "ln": ln,
                    "d": dia(DATA.search(msg).group(1)), "negs": anotar.decompor(msg)["negocios"],
                    "pares": gold.get(v) or []})
    rel.sort(key=lambda r: (r["d"], r["v"]))

    # ids estáveis para os negócios abertos por anotação, pela ordem de data
    # O id diz de onde o negócio nasceu: NG-A + número do relatório + a, b, c pela
    # ordem dos NOVO desse relatório. Não depende de outras anotações, pelo que
    # corrigir um relatório não renumera os negócios dos outros.
    ids = {}
    for r in rel:
        k = 0
        for i, p in enumerate(r["pares"]):
            if p["negocio_id"] == "NOVO" and p["tipo"] in CICLO:
                ids[(r["v"], i)] = f"NG-A{r['ln']:03d}{'abcdefgh'[k]}"
                k += 1

    por_cli = defaultdict(list)
    for r in rel:
        por_cli[r["cno"]].append(r)

    novas = {}
    for r in rel:
        ant = [(x["d"], ids.get((x["v"], i), p["negocio_id"]), p["negocio_id"] == "NOVO",
                p["tipo"], p.get("estado"), p.get("excerto"))
               for x in por_cli[r["cno"]] if x["d"] < r["d"]
               for i, p in enumerate(x["pares"])]
        hist, abertos = bloco.historico(ant, r["negs"])
        novas[r["v"]] = (r, bloco.substituir(r["msg"], bloco.montar(r["negs"], hist, abertos, r["d"])))
    return novas, ids


def main():
    gravar = "--gravar" in sys.argv
    atuais = {v: m for v, m in anotar._sql("SELECT vistamp, mensagem FROM benchmark_entradas WHERE entrada_version = 'v3'")}
    novas, ids = construir()
    mudam = [r["ln"] for v, (r, m) in novas.items() if atuais.get(v) != m]
    com_estado = sum(m.count("último estado:") for _, m in novas.values())
    com_a = sum(1 for _, m in novas.values() if "NG-A" in m)
    usados = {i for _, m in novas.values() for i in re.findall(r"NG-A\d{3}[a-h]", m)}
    print(f"{len(novas)} relatórios · {len(usados)} negócios abertos por anotação · "
          f"{com_estado} negócios com último estado · {com_a} relatórios com NG-A no bloco")
    print(f"{len(mudam)} mensagens diferentes da v3 congelada" + (f": #{', #'.join(map(str, sorted(mudam)[:60]))}" if atuais else ""))
    if not gravar:
        return
    L = db.Ligacao()
    def f(c):
        with c.cursor() as cur:
            for v, (r, m) in novas.items():
                cur.execute("""INSERT INTO benchmark_entradas (vistamp, cliente_no, cliente, estrato, mensagem, congelada_em, entrada_version, linha)
                               VALUES (%s,%s,%s,%s,%s,now(),'v3',%s)
                               ON CONFLICT (vistamp, entrada_version) DO UPDATE SET mensagem = EXCLUDED.mensagem, congelada_em = now()""",
                            (v, r["cno"], r["cli"], r["est"], m, r["ln"]))
            cur.execute("SELECT count(*) FROM gold_anotacoes WHERE entrada_version = 'v3'")
            if cur.fetchone()[0] == 0:
                cur.execute("""INSERT INTO gold_anotacoes (vistamp, entrada_version, comercial, pares, duvida, nota, origem, anotador, atualizado_em)
                               SELECT vistamp, 'v3', comercial, pares, duvida, nota, 'copia_v2', anotador, now()
                                 FROM gold_anotacoes WHERE entrada_version = 'v2'""")
                cur.execute("""INSERT INTO gold_anotacoes_hist (vistamp, entrada_version, comercial, pares, duvida, nota, origem, anotador)
                               SELECT vistamp, 'v3', comercial, pares, duvida, nota, 'copia_v2', anotador
                                 FROM gold_anotacoes WHERE entrada_version = 'v2'""")
                print("gold da v2 copiado para a v3")
        c.commit()
    L.executar(f); L.fechar()
    print("v3 congelada")


ORIGEM_GOLD = "v3" if "--do-v3" in sys.argv else "v2"
if __name__ == "__main__":
    main()
