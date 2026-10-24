"""Métricas do benchmark: a única implementação, usada pelo painel e pela reprodução.

As definições são as da secção 3.2 e do Quadro 4.2:

  nível 1   conteúdo comercial (com falsos negativos e positivos), precisão, revocação
            e F1 dos pares relatório-negócio, tipo certo nos pares emparelhados, pares
            por tipificar e excerto literal;
  nível 2   cobertura do pipeline (RF1.4), macro-F1 ponta a ponta (RF1.8) e nos pares
            ligados, estado atribuído, estado certo, distância do erro e F1 por estado;
  geral     concordância exata do relatório inteiro e composição das discordâncias.

Uma resposta que não cumpre o contrato de saída (falha de leitura) conta como relatório
por classificar em todos os denominadores; uma falha de infraestrutura fica de fora.
O macro-F1 é a média do F1 pelos estados com suporte, sem o fechado (a verdade está na
faturação) nem o indeterminado (ausência de sinal).

As comparações entre corridas fazem-se sobre os relatórios comuns: intervalo de
confiança a 95% por reamostragem dos relatórios (1000 réplicas, semente fixa) e teste
de McNemar exato sobre a concordância exata, com correção de Holm quando há vários.
"""

import gzip
import json
import math
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))
from llm import juntar_repetidos  # noqa: E402

DADOS = Path(__file__).resolve().parent / "anonimo" / "benchmark_anonimo.json.gz"
FORA_DA_MEDIA = ("8. Fechado", "10. Indeterminado")
INDETERMINADO = "10. Indeterminado"
TIPOS_DO_CICLO = ("equipamento", "producao", "lead")
REPLICAS, SEMENTE = 1000, 20260928
# Que anotação serve cada entrada: as corridas v2 com a anotação revista (v3) e as e4s
# (sem estado no bloco) com a da e4.
ANOTACAO_DE = {"v2": "v3", "e4s": "e4"}
# Entradas cujo bloco não mostra os negócios abertos pela anotação em relatórios anteriores
# (NG-A, NG-B): aí o modelo só pode responder NOVO, e é isso que a anotação passa a dizer.
SEM_ABERTOS_DA_ANOTACAO = {"v2", "e4s"}


# ------------------------------------------------------------------ dados

class Benchmark:
    """As corridas, a anotação e as respostas, prontas a medir."""

    def __init__(self, caminho=DADOS, anotacao=None, juntar=True, dados=None):
        """`anotacao` substitui entradas de ANOTACAO_DE (por exemplo {"v2": "v2"});
        `juntar` aplica às respostas a regra dos pares repetidos (llm.juntar_repetidos),
        que é do sistema desde 28-Set-2026; as corridas da terceira etapa são anteriores."""
        if dados is None:
            with gzip.open(caminho, "rt", encoding="utf-8") as f:
                dados = json.load(f)
        d = dados
        self.estados, self.tipos = d["estados"], d["tipos"]
        self.ciclo = {self.tipos.index(t) for t in TIPOS_DO_CICLO}
        self.fora = {self.estados.index(e) for e in FORA_DA_MEDIA}
        self.ind = self.estados.index(INDETERMINADO)
        self.lead = self.tipos.index("lead")
        cons = self.tipos.index("consumiveis")
        self.corridas = d["corridas"]
        self.por_id = {c["id"]: c for c in self.corridas}
        gold = {(r["r"], r["versao"]): r for r in d["relatorios"]}
        self.relatorios_brutos = d["relatorios"]
        self.respostas = {}                       # corrida -> {relatório: resposta}
        for ci, ri, com, erro, pares, *nota in d["respostas"]:
            c = self.corridas[ci]
            g0 = d["relatorios"][ri]
            ver = {**ANOTACAO_DE, **(anotacao or {})}.get(c["entrada"], c["entrada"])
            g = gold.get((g0["r"], ver), g0)
            if c["entrada"] in SEM_ABERTOS_DA_ANOTACAO:
                g = {**g, "pares": [["NOVO" if re.match(r"NG-[AB]\d", p[0]) else p[0], *p[1:]]
                                    for p in g["pares"]]}
            if juntar:
                pares = juntar_repetidos(pares, nid=lambda p: p[0],
                                         tipo=lambda p: "consumiveis" if p[1] == cons else "x")
            self.respostas.setdefault(c["id"], {})[g0["r"]] = {
                "g": g, "versao": ver, "com": com, "erro": erro, "pares": pares, "nota": nota[0] if nota else ""}

    def corrida(self, padrao):
        """A corrida cujo identificador começa por `padrao` (tem de ser única)."""
        xs = [c["id"] for c in self.corridas if c["id"].startswith(padrao)]
        if len(xs) != 1:
            raise KeyError(f"{padrao!r}: {len(xs)} corridas")
        return xs[0]

    def relatorios(self, cid, conjunto="todos"):
        """Os relatórios de uma corrida: todos, só os de avaliação ou só os de desenvolvimento."""
        rs = self.respostas.get(cid, {})
        if conjunto == "todos":
            return sorted(rs)
        quer = conjunto == "desenvolvimento"
        return sorted(r for r, x in rs.items() if bool(x["g"]["dev"]) == quer)


# --------------------------------------------------------------- emparelhar

def emparelhar(meus, seus):
    """Liga cada par da anotação ao do modelo: primeiro por negócio e tipo, depois só
    pelo negócio, que serve os NOVO porque um relatório pode abrir mais do que um."""
    livres, ligados, perdidos = list(meus), [], []
    for g in seus:
        k = -1
        for n in (2, 1):
            k = next((i for i, c in enumerate(livres) if c[0] == g[0] and (n == 1 or c[1] == g[1])), -1)
            if k >= 0:
                break
        if k >= 0:
            ligados.append((g, livres.pop(k)))
        else:
            perdidos.append(g)
    return ligados, perdidos, livres


def _chave(p):
    return f"{p[0] or ''}|{p[1]}|{'' if p[2] is None else p[2]}"


def onde_falha(meus, g, com):
    """Onde a resposta se afasta da anotação, do mais grosso ao mais fino."""
    if bool(com) != bool(g["com"]):
        return "conteudo"
    a, b = sorted(meus, key=_chave), sorted(g["pares"], key=_chave)
    if [_chave(x) for x in a] == [_chave(x) for x in b]:
        return "certo"
    if len(a) != len(b):
        return "n_pares"
    for i, k in ((0, "negocio"), (1, "tipo"), (2, "estado")):
        if [str(x[i]) for x in a] != [str(x[i]) for x in b]:
            return k
    return "estado"


def _f1(tp, fp, fn):
    d = 2 * tp + fp + fn
    return 2 * tp / d if d else 0


def _media(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


# ----------------------------------------------------------------- métricas

def calcular(b: Benchmark, cid, relatorios=None, min_suporte=1, sem_identidade=False):
    """Métricas de uma corrida sobre os relatórios dados (com repetição, para a reamostragem).

    `min_suporte` restringe a média aos estados com pelo menos esse número de pares na
    anotação; `sem_identidade` compara os pares sem o negócio apontado (só tipo e estado).
    """
    E = len(b.estados)
    rs = b.respostas.get(cid, {})
    lista = relatorios if relatorios is not None else sorted(rs)
    m = dict(rel=0, infra=0, leitura=0, comOk=0, comFN=0, comFP=0, goldP=0, meusP=0, ligados=0,
             tipoOk=0, lead=0, literal=0, cicloMeus=0, indet=0, cicloGold=0, cobGoldOk=0,
             estOk=0, estN=0, dist=0, distN=0, certos=0, falhas={}, por_rel={})
    conf = [[0] * E for _ in range(E)]
    fn, fp = [0] * E, [0] * E
    pipe = lambda g1: g1[1] in b.ciclo and g1[2] is not None and g1[2] != b.ind  # noqa: E731
    for r in lista:
        x = rs.get(r)
        if x is None:
            continue
        g = x["g"]
        gp = [[None, p[1], p[2]] for p in g["pares"]] if sem_identidade else g["pares"]
        meus = [[None, p[1], p[2]] for p in x["pares"]] if sem_identidade else x["pares"]
        if x["erro"] == "infra":
            m["infra"] += 1; m["por_rel"][r] = "infra"
            continue
        if x["erro"]:
            m["leitura"] += 1; m["rel"] += 1
            if g["com"]:
                m["comFN"] += 1
            m["goldP"] += len(gp)
            for g1 in gp:
                if g1[2] is not None:
                    fn[g1[2]] += 1
            m["cicloGold"] += sum(1 for g1 in gp if pipe(g1))
            m["falhas"]["erro"] = m["falhas"].get("erro", 0) + 1
            m["por_rel"][r] = "erro"
            continue
        m["rel"] += 1
        if bool(x["com"]) == bool(g["com"]):
            m["comOk"] += 1
        elif g["com"]:
            m["comFN"] += 1
        else:
            m["comFP"] += 1
        m["goldP"] += len(gp); m["meusP"] += len(meus)
        ligados, perdidos, extra = emparelhar(meus, gp)
        m["ligados"] += len(ligados)
        m["cicloGold"] += sum(1 for g1 in gp if pipe(g1))
        for g1, p1 in ligados:
            if pipe(g1) and p1[2] is not None and p1[2] != b.ind:
                m["cobGoldOk"] += 1
            if g1[1] == p1[1]:
                m["tipoOk"] += 1
            if g1[2] is not None:
                m["estN"] += 1
                if g1[2] == p1[2]:
                    m["estOk"] += 1
                pm = b.ind if p1[2] is None else p1[2]
                conf[g1[2]][pm] += 1
                if g1[2] not in b.fora and pm not in b.fora:
                    m["dist"] += abs(g1[2] - pm); m["distN"] += 1
        for g1 in perdidos:
            if g1[2] is not None:
                fn[g1[2]] += 1
        for p1 in extra:
            if p1[2] is not None:
                fp[p1[2]] += 1
        for p1 in x["pares"]:
            if p1[1] in b.ciclo:
                m["cicloMeus"] += 1
                if p1[2] in (b.ind, None):
                    m["indet"] += 1
            if p1[1] == b.lead:
                m["lead"] += 1
            if len(p1) > 3 and p1[3]:
                m["literal"] += 1
        k = onde_falha(meus, {"com": g["com"], "pares": gp}, x["com"])
        m["falhas"][k] = m["falhas"].get(k, 0) + 1
        m["por_rel"][r] = k
        if k == "certo":
            m["certos"] += 1
    f1s = []
    for e in range(E):
        tp = conf[e][e]
        fpe = sum(conf[y][e] for y in range(E) if y != e)
        fne = sum(conf[e][y] for y in range(E) if y != e)
        sup = fne + tp + fn[e]
        f1s.append({"estado": b.estados[e], "sup": sup, "lig": _f1(tp, fpe, fne),
                    "pp": _f1(tp, fpe + fp[e], fne + fn[e])})
    contam = [e for e, f in enumerate(f1s) if f["sup"] >= min_suporte and e not in b.fora]
    q = lambda a, d: a / d if d else None  # noqa: E731
    prec, rev = q(m["ligados"], m["meusP"]), q(m["ligados"], m["goldP"])
    m.update(
        f1=f1s, conf=conf, fn=fn, fp=fp, suporte=len(contam),
        macro=_media(f1s[e]["pp"] for e in contam), macroLig=_media(f1s[e]["lig"] for e in contam),
        prec=prec, rev=rev, f1par=2 * prec * rev / (prec + rev) if prec and rev else None,
        conteudo=q(m["comOk"], m["rel"]), tipo=q(m["tipoOk"], m["ligados"]),
        porTipificar=q(m["lead"], m["meusP"]), excertoLiteral=q(m["literal"], m["meusP"]),
        cobertura=1 - m["indet"] / m["cicloMeus"] if m["cicloMeus"] else None,
        cobPipe=q(m["cobGoldOk"], m["cicloGold"]), estadoCerto=q(m["estOk"], m["estN"]),
        distancia=q(m["dist"], m["distN"]), concordancia=q(m["certos"], m["rel"]),
        paresAMais=m["meusP"] - m["ligados"],
    )
    return m


# ------------------------------------------------------------ estatística

def mcnemar(b_, c_):
    """Teste exato (binomial, bilateral) sobre os discordantes: só A acerta, só B acerta."""
    n = b_ + c_
    if not n:
        return 1.0
    k = min(b_, c_)
    return min(1.0, 2 * sum(math.comb(n, j) for j in range(k + 1)) / 2 ** n)


def holm(ps):
    """Correção de Holm, com a monotonia; devolve os p corrigidos pela ordem de entrada."""
    ordem = sorted(range(len(ps)), key=lambda i: ps[i])
    out, maior = [0.0] * len(ps), 0.0
    for pos, i in enumerate(ordem):
        maior = max(maior, min(1.0, ps[i] * (len(ps) - pos)))
        out[i] = maior
    return out


def ic95(valores):
    """Intervalo percentil a 95% das réplicas."""
    v = sorted(x for x in valores if x is not None)
    n = len(v)
    return (v[int(0.025 * n)], v[int(0.975 * n) - 1]) if n else (None, None)


def reamostrar(base, funcao, replicas=REPLICAS, semente=SEMENTE):
    """`funcao` aplicada a `replicas` reamostragens com repetição de `base`."""
    rnd = random.Random(semente)
    return [funcao([base[rnd.randrange(len(base))] for _ in base]) for _ in range(replicas)]


def comuns(b: Benchmark, *cids, conjunto="todos"):
    """Os relatórios respondidos por todas as corridas, sem falhas de infraestrutura."""
    sets = [set(b.relatorios(c, conjunto)) for c in cids]
    base = set.intersection(*sets) if sets else set()
    return sorted(r for r in base if all(b.respostas[c][r]["erro"] != "infra" for c in cids))


def comparar(b: Benchmark, ca, cb, base=None, medida="macro", replicas=REPLICAS, **kw):
    """B contra A: medidas, IC95 da diferença (B − A) e McNemar sobre a concordância exata.

    Com `replicas=0` não há reamostragem (só o teste), que é o que o painel precisa."""
    base = base if base is not None else comuns(b, ca, cb)
    ma, mb = calcular(b, ca, base, **kw), calcular(b, cb, base, **kw)
    so_a = sum(1 for r in base if ma["por_rel"].get(r) == "certo" and mb["por_rel"].get(r) != "certo")
    so_b = sum(1 for r in base if ma["por_rel"].get(r) != "certo" and mb["por_rel"].get(r) == "certo")
    deltas = reamostrar(base, lambda am: _dif(calcular(b, cb, am, **kw)[medida], calcular(b, ca, am, **kw)[medida]),
                        replicas) if replicas else []
    return {"n": len(base), "a": ma, "b": mb, "dif": _dif(mb[medida], ma[medida]), "ic": ic95(deltas),
            "so_a": so_a, "so_b": so_b, "p": mcnemar(so_a, so_b)}


def _dif(x, y):
    return None if x is None or y is None else x - y
