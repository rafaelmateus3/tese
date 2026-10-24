"""Bloco de negócios abertos com o último estado (entrada v3).

É o mesmo código no benchmark e em produção, para que o modelo veja nos dois a
mesma coisa. O que muda é de onde vem o histórico: no benchmark é o gold dos
relatórios anteriores; em produção são os pares já gravados.

A partir do bloco do registo (negócios do cliente vivos à data, ver
contexto.py), acrescenta-se:

  - a cada negócio do ciclo, o último estado anterior à data e a data dele;
  - os negócios abertos por um relatório anterior (NOVO) que o registo não tem,
    com o primeiro excerto. Um NOVO do mesmo tipo de um único negócio do
    registo é esse negócio, salvo se esse negócio foi citado no mesmo relatório
    (então são dois); havendo dois do mesmo tipo não se sabe qual é e fica de
    fora (não se inventa a ligação);
  - sai o negócio aberto por relatório que está em 8 ou 9, ou sem referência há
    mais de 180 dias (RF2.8).
"""

import re
from collections import defaultdict
from datetime import timedelta

CICLO = ("equipamento", "producao", "lead")
FECHO = timedelta(days=180)
FINAIS = ("8.", "9.")
DESDE = re.compile(r"\bdesde (\d{4}-\d\d-\d\d)")

BLOCO = re.compile(r"  <negocios_abertos>\n(.*?)\n\s*</negocios_abertos>\n", re.S)
_LINHA = re.compile(r"^\s+(\S+)\s*\|\s*([^|]+?)\s*\|(.*)$")


def registo(bloco_v2: str) -> list[dict]:
    """Os negócios de um bloco no formato do registo (v2)."""
    negs = []
    m = BLOCO.search(bloco_v2 or "")
    if not m:
        return negs
    for linha in m.group(1).split("\n"):
        x = _LINHA.match(linha)
        if x:
            negs.append({"id": x.group(1), "tipo": x.group(2).strip(),
                         "resto": x.group(3).strip(" |"), "primeiro": ""})
        elif negs and linha.strip():
            negs[-1]["primeiro"] = (negs[-1]["primeiro"] + " " + linha.strip()).strip()
    return negs


def citados(anteriores) -> set:
    """(data, negócio) de cada negócio do registo citado por um par anterior."""
    return {(d, nid) for d, nid, aberto_aqui, *_ in anteriores if not aberto_aqui}


def destino(novo_id: str, tipo: str, negs: list[dict], d=None, cit=frozenset()) -> str | None:
    """Para onde aponta, neste bloco, um negócio aberto por um relatório anterior.

    Um NOVO aberto no mesmo relatório (mesma data) em que o negócio do registo
    também foi citado é outro negócio, e não esse (corrigido a 09-Out-2026)."""
    reg = [y for y in negs if y["tipo"] == tipo]
    if len(reg) == 1:
        return novo_id if (d, reg[0]["id"]) in cit else reg[0]["id"]
    return None if reg else novo_id


def historico(anteriores, negs: list[dict]) -> dict:
    """({negócio: [(data, estado, excerto, tipo)]}, negócios abertos por relatório).

    `anteriores` são (data, negocio_id, aberto_aqui, tipo, estado, excerto):
    aberto_aqui diz se foi esse par que abriu o negócio (NOVO).
    """
    hist, abertos = defaultdict(list), set()
    cit = citados(anteriores)
    for d, nid, aberto_aqui, tipo, estado, excerto in anteriores:
        if tipo not in CICLO:
            continue
        if aberto_aqui:
            nid = destino(nid, tipo, negs, d, cit)
            if nid and nid not in {x["id"] for x in negs}:
                abertos.add(nid)
        if nid:
            hist[nid].append((d, estado, excerto or "", tipo))
    return hist, abertos


def montar(negs: list[dict], hist: dict, abertos: set, quando) -> str:
    """O bloco v3, pronto a entrar na mensagem. Vazio se não houver negócios."""
    linhas = []
    for x in negs:
        linha = f"    {x['id']} | {x['tipo']} | {x['resto']}"
        h = [e for e in sorted(hist.get(x["id"], [])) if e[1]]
        # O último estado só conta dentro do episódio que o bloco mostra: um estado
        # anterior ao «desde» é de um episódio já encerrado (silêncio de mais de 90
        # dias) e não descreve o negócio de agora (corrigido a 08-Out-2026).
        ini = DESDE.search(x["resto"])
        if ini:
            h = [e for e in h if str(e[0]) >= ini.group(1)]
        # Fechado ou perdido sai do bloco, como já acontecia aos negócios abertos por
        # relatório: o que vier depois é outro negócio ou pós-venda (08-Out-2026).
        if x["tipo"] in CICLO and h and h[-1][1][:2] in FINAIS:
            continue
        if x["tipo"] in CICLO and h:
            linha += f" | último estado: {h[-1][1]} (a {h[-1][0]})"
        linhas.append(linha)
        if x["primeiro"]:
            linhas.append(f"      {x['primeiro']}")
    for nid in sorted(k for k in hist if k in abertos):
        h = sorted(hist[nid])
        ult = [e for e in h if e[1]]
        if not ult or ult[-1][1][:2] in FINAIS or quando - h[-1][0] > FECHO:
            continue
        n = len(h)
        linhas.append(f"    {nid} | {h[-1][3]} | desde {h[0][0]} | {n} relatório{'s' if n > 1 else ''}, "
                      f"último a {h[-1][0]} | último estado: {ult[-1][1]} (a {ult[-1][0]})")
        linhas.append(f'      primeiro relatório: "{h[0][2][:160]}"')
    if not linhas:
        return ""
    return "  <negocios_abertos>\n" + "\n".join(linhas) + "\n  </negocios_abertos>\n"


def substituir(msg: str, bloco: str) -> str:
    """Põe o bloco na mensagem, no lugar do anterior ou antes de </report>."""
    if BLOCO.search(msg):
        return BLOCO.sub(lambda _: bloco, msg)
    return msg.replace("</report>", bloco + "</report>") if bloco else msg
