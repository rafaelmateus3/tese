"""Reproduz os números do Capítulo 6 e do Anexo L que vêm do benchmark.

    python reproduzir.py              compara cada número com o da dissertação
    python reproduzir.py --so-difere  mostra só os que não coincidem

Lê anonimo/benchmark_anonimo.json.gz (ver exportar.py) e calcula tudo com metricas.py,
a única implementação das métricas. Cada linha tem o valor calculado, o valor que a
dissertação apresenta e se coincidem, já com o arredondamento do texto.

Condições de cada bloco, que são as da dissertação:
  terceira etapa (6.1)   tarefa c05/e05/v2, anotação v2, sem a regra dos pares repetidos,
                         que é posterior; 352 relatórios de avaliação
  quarta etapa (6.2, L)  tarefa c05/e05/v3 e e4, anotação revista (v3) e anotação da e4
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metricas as M  # noqa: E402

LINHAS = []


def pt(x, casas=2):
    return "–" if x is None else f"{x:.{casas}f}".replace(".", ",").replace("-", "−")


def pct(x, casas=1):
    return "–" if x is None else pt(100 * x, casas) + "%"


def p_txt(p):
    return "< 0,001" if p < 0.001 else pt(p, 3)


def ic(par, casas=2, pp=False, sinal=False):
    f = (lambda v: (("+" if sinal and v > 0 else "") + pt(100 * v if pp else v, casas)))
    return f"[{f(par[0])}; {f(par[1])}]"


def ver(secao, rotulo, calculado, tese):
    LINHAS.append((secao, rotulo, calculado, tese, calculado == tese))


# ------------------------------------------------------------ terceira etapa

def terceira_etapa():
    b = M.Benchmark(anotacao={"v2": "v2"}, juntar=False)
    locais = [c["id"] for c in b.corridas if c["prompt"] == "c05" and c["entrada"] == "v2"
              and c["rel"] >= 300 and c["backend"] == "ollama"]
    nome = {c: c.split("|")[0].split("/")[-1].replace(":latest", "").replace("-GGUF:Q4_K_M", "") for c in locais}
    met = {c: M.calcular(b, c, b.relatorios(c, "avaliacao")) for c in locais}
    rpm = {c: b.por_id[c]["rel"] / b.por_id[c]["seg"] * 60 for c in locais}

    Q61 = {  # conteúdo, FN/FP, precisão, revocação, F1, tipo, por tipificar, excerto literal
        "qwen3.8": ("95,2%", "9/8", "0,92", "0,92", "0,92", "94,8%", "1,4%", "99,4%"),
        "qwen3.6:27b": ("92,9%", "17/8", "0,91", "0,90", "0,90", "95,0%", "3,2%", "98,3%"),
        "muse-glimmer:30b": ("92,3%", "17/10", "0,88", "0,85", "0,86", "92,4%", "7,0%", "99,4%"),
        "gemma4:26b": ("95,5%", "2/14", "0,84", "0,96", "0,90", "95,0%", "2,0%", "98,5%"),
        "mistral-small": ("93,8%", "6/16", "0,82", "0,91", "0,86", "91,9%", "4,1%", "95,7%"),
        "gemma4:e4b": ("88,6%", "14/26", "0,83", "0,86", "0,84", "93,1%", "8,1%", "97,8%"),
        "OpenEuroLLM-Portuguese": ("88,9%", "7/32", "0,79", "0,85", "0,82", "93,7%", "3,4%", "96,3%"),
        "nemotron-3.5-lightning": ("90,3%", "4/30", "0,69", "0,85", "0,76", "89,0%", "7,8%", "91,5%"),
        "AMALIA-9B-0626-DPO": ("89,5%", "4/33", "0,79", "0,81", "0,80", "90,6%", "5,2%", "69,3%"),
    }
    Q62 = {  # cobertura (n/212), estado atribuído, macro, macro ligados, distância, concordância, rpm
        "qwen3.8": ("86,3% (183/212)", "94,5%", "0,622", "0,669", "0,70", "65%", "2,3"),
        "qwen3.6:27b": ("82,1% (174/212)", "89,9%", "0,584", "0,640", "0,66", "63%", "2,3"),
        "muse-glimmer:30b": ("83,0% (176/212)", "92,9%", "0,580", "0,634", "0,92", "57%", "2,6"),
        "gemma4:26b": ("92,5% (196/212)", "94,5%", "0,576", "0,649", "0,77", "64%", "10,0"),
        "mistral-small": ("84,4% (179/212)", "88,0%", "0,550", "0,610", "0,79", "55%", "1,8"),
        "gemma4:e4b": ("83,5% (177/212)", "97,8%", "0,481", "0,560", "0,91", "53%", "13,9"),
        "OpenEuroLLM-Portuguese": ("80,7% (171/212)", "96,1%", "0,370", "0,456", "0,88", "49%", "2,4"),
        "nemotron-3.5-lightning": ("78,3% (166/212)", "98,1%", "0,349", "0,472", "1,34", "37%", "7,4"),
        "AMALIA-9B-0626-DPO": ("75,9% (161/212)", "100,0%", "0,264", "0,334", "1,40", "42%", "4,8"),
    }
    for c in locais:
        m, n = met[c], nome[c]
        calc61 = (pct(m["conteudo"]), f"{m['comFN']}/{m['comFP']}", pt(m["prec"]), pt(m["rev"]), pt(m["f1par"]),
                  pct(m["tipo"]), pct(m["porTipificar"]), pct(m["excertoLiteral"]))
        calc62 = (f"{pct(m['cobPipe'])} ({m['cobGoldOk']}/{m['cicloGold']})", pct(m["cobertura"]), pt(m["macro"], 3),
                  pt(m["macroLig"], 3), pt(m["distancia"]), pct(m["concordancia"], 0), pt(rpm[c], 1))
        cols61 = ("conteúdo", "FN/FP", "precisão", "revocação", "F1 pares", "tipo", "por tipificar", "excerto literal")
        cols62 = ("cobertura", "estado atribuído", "macro-F1", "macro-F1 ligados", "distância", "concordância", "resp/min")
        for k, a, t in zip(cols61, calc61, Q61[n]):
            ver("Quadro 6.1", f"{n}: {k}", a, t)
        for k, a, t in zip(cols62, calc62, Q62[n]):
            ver("Quadro 6.2", f"{n}: {k}", a, t)
    ver("Quadro 6.1", "pares na anotação", str(met[locais[0]]["goldP"]), "355")

    q = next(c for c in locais if nome[c] == "qwen3.8")
    g = next(c for c in locais if nome[c] == "gemma4:26b")
    Q63 = {"1. Lead / Prospeção": (36, "0,59", "0,58"), "2. Qualificação": (48, "0,40", "0,49"),
           "3. Proposta / Orçamento": (51, "0,77", "0,79"), "4. Negociação": (16, "0,60", "0,65"),
           "5. Aprovação Interna": (30, "0,55", "0,61"), "6. Encomenda Confirmada": (8, "0,71", "0,33"),
           "7. Em Produção / Entrega": (3, "0,67", "0,50"), "8. Fechado": (2, "0,67", "0,50"),
           "9. Perdido / Cancelado": (18, "0,71", "0,65"), "10. Indeterminado": (1, "0,00", "0,00")}
    for fq, fg in zip(met[q]["f1"], met[g]["f1"]):
        sup, tq, tg = Q63[fq["estado"]]
        ver("Quadro 6.3", f"{fq['estado']}: suporte", str(fq["sup"]), str(sup))
        ver("Quadro 6.3", f"{fq['estado']}: qwen3.8", pt(fq["pp"]), tq)
        ver("Quadro 6.3", f"{fq['estado']}: gemma4:26b", pt(fg["pp"]), tg)

    # Quadro 6.4: McNemar contra o de maior macro-F1, Holm sobre os oito testes
    ref = max(locais, key=lambda c: met[c]["macro"])
    ver("Quadro 6.4", "referência", nome[ref], "qwen3.8")
    outros = [c for c in locais if c != ref]
    testes = {c: M.comparar(b, ref, c, base=M.comuns(b, ref, c, conjunto="avaliacao")) for c in outros}
    ph = dict(zip(outros, M.holm([testes[c]["p"] for c in outros])))
    Q64 = {"qwen3.6:27b": ("0,58", 29, 21, "0,322", "0,644"), "muse-glimmer:30b": ("0,58", 50, 21, "< 0,001", "0,002"),
           "gemma4:26b": ("0,58", 34, 30, "0,708", "0,708"), "mistral-small": ("0,55", 61, 25, "< 0,001", "< 0,001"),
           "gemma4:e4b": ("0,48", 66, 24, "< 0,001", "< 0,001"),
           "OpenEuroLLM-Portuguese": ("0,37", 78, 21, "< 0,001", "< 0,001"),
           "nemotron-3.5-lightning": ("0,35", 119, 18, "< 0,001", "< 0,001"),
           "AMALIA-9B-0626-DPO": ("0,26", 98, 16, "< 0,001", "< 0,001")}
    for c in outros:
        t, e = testes[c], Q64[nome[c]]
        ver("Quadro 6.4", f"{nome[c]}: macro-F1", pt(met[c]["macro"]), e[0])
        ver("Quadro 6.4", f"{nome[c]}: só a referência / só o modelo", f"{t['so_a']} / {t['so_b']}", f"{e[1]} / {e[2]}")
        ver("Quadro 6.4", f"{nome[c]}: p", p_txt(t["p"]), e[3])
        ver("Quadro 6.4", f"{nome[c]}: p com Holm", p_txt(ph[c]), e[4])
    ver("6.1.6", "modelos inferiores com Holm", str(sum(1 for c in outros if ph[c] < 0.05)), "6")

    # 6.1.3: intervalos por reamostragem
    av_q, av_g = b.relatorios(q, "avaliacao"), b.relatorios(g, "avaliacao")
    for c, base, t_macro, t_p in ((q, av_q, "[0,54; 0,69]", "67%"), (g, av_g, "[0,48; 0,66]", None)):
        reps = M.reamostrar(base, lambda am, c=c: M.calcular(b, c, am))
        ver("6.1.3", f"{nome[c]}: IC95 do macro-F1", ic(M.ic95([r["macro"] for r in reps])), t_macro)
        if t_p:
            ver("6.1.3", f"{nome[c]}: réplicas com macro-F1 ≥ 0,60",
                pct(sum(r["macro"] >= 0.60 for r in reps) / len(reps), 0), t_p)
        cob = [r["cobPipe"] for r in reps]
        if c == g:
            ver("6.1.3", "gemma4:26b: IC95 da cobertura", ic(M.ic95(cob), 1, pp=True).replace("]", "]"), "[88,0; 96,1]")
        ver("6.1.3", f"{nome[c]}: réplicas com cobertura ≥ 90%", pct(sum(x >= 0.90 for x in cob) / len(cob), 0),
            "87%" if c == g else "6%")

    base = M.comuns(b, q, g, conjunto="avaliacao")
    d_macro = M.comparar(b, g, q, base=base)
    ver("6.1.4", "IC95 da diferença de macro-F1, qwen3.8 − gemma4:26b", ic(d_macro["ic"]), "[−0,03; 0,13]")
    d_cob = M.comparar(b, q, g, base=base, medida="cobPipe")
    ver("6.1.4", "IC95 da diferença de cobertura, gemma4:26b − qwen3.8 (pp)", ic(d_cob["ic"], 1, pp=True), "[1,8; 10,8]")

    # 6.1.5: desenvolvimento e casos impedidos
    for c, t in ((g, "0,90"), (q, "0,80")):
        ver("6.1.5", f"{nome[c]}: macro-F1 no desenvolvimento", pt(M.calcular(b, c, b.relatorios(c, "desenvolvimento"))["macro"]), t)
    ver("6.1.5", "pares do ciclo no desenvolvimento", str(M.calcular(b, q, b.relatorios(q, "desenvolvimento"))["cicloGold"]), "14")
    linhas = {r["r"]: r["linha"] for r in b.relatorios_brutos if r["versao"] == "v2"}
    impedidos = {131, 162, 230, 266, 360}
    for c, tm, tc in ((g, "0,571", "93,0%"), (q, "0,621", "87,6%")):
        rs = [r for r in b.relatorios(c, "avaliacao") if linhas.get(r) not in impedidos]
        m = M.calcular(b, c, rs)
        ver("6.1.5", f"{nome[c]}: macro-F1 sem os cinco impedidos", pt(m["macro"], 3), tm)
        ver("6.1.5", f"{nome[c]}: cobertura sem os cinco impedidos", pct(m["cobPipe"]), tc)
    return b


# ---------------------------------------------- serviço externo e quarta etapa

def haiku():
    """6.1.4: o Claude Haiku 4.5 contra os dois da frente, anotação revista, 368 relatórios."""
    b = M.Benchmark(anotacao={"v2": "v3"})
    h, q, g = (b.corrida(x) for x in ("claude-haiku", "qwen3.8:latest|c05|e05|v2", "gemma4:26b|c05|e05|v2"))
    base = M.comuns(b, h, q, g)
    ver("6.1.4 Haiku", "relatórios comuns", str(len(base)), "368")
    for c, tm, tc in ((h, "0,511", "80,3%"), (q, "0,631", "84,2%"), (g, "0,585", "89,9%")):
        m = M.calcular(b, c, base)
        ver("6.1.4 Haiku", f"{c.split('|')[0]}: macro-F1", pt(m["macro"], 3), tm)
        ver("6.1.4 Haiku", f"{c.split('|')[0]}: cobertura", pct(m["cobPipe"]), tc)
    t = M.comparar(b, q, h, base=base)
    ver("6.1.4 Haiku", "IC95 da diferença de macro-F1, Haiku − qwen3.8", ic(t["ic"]), "[−0,21; −0,05]")
    ver("6.1.4 Haiku", "McNemar: só qwen3.8 / só Haiku", f"{t['so_a']} / {t['so_b']}", "62 / 23")
    ver("6.1.4 Haiku", "p", p_txt(t["p"]), "< 0,001")


def quarta_etapa():
    b = M.Benchmark()
    C = {k: b.corrida(v) for k, v in {
        "g375": "gemma4:26b|c05|e05|v3|260928", "q375": "qwen3.8:latest|c05|e05|v3|260929",
        "ge4": "gemma4:26b|c05|e05|e4|", "qe4": "qwen3.8:latest|c05|e05|e4|",
        "ge4s": "gemma4:26b|c05|e05|e4s|", "qe4s": "qwen3.8:latest|c05|e05|e4s|",
        "gr375": "gemma4:26b|c05r|e05|v3|", "gre4": "gemma4:26b|c05r|e05|e4|",
        "g8_375": "gemma4:26b-a4b-it-q8_0|c05|e05|v3|261011-0228", "g8_e4": "gemma4:26b-a4b-it-q8_0|c05|e05|e4|",
        "q35_375": "qwen3.6:35b-a3b-q4_K_M|c05|e05|v3|261011-0358", "q35_e4": "qwen3.6:35b-a3b-q4_K_M|c05|e05|e4|",
        "e2A": "gemma4:26b|c05r+e2A|", "e2B": "gemma4:26b|c05r+e2B|", "id": "gemma4:26b|c05r+id|"}.items()}
    rpm = lambda c: b.por_id[c]["rel"] / b.por_id[c]["seg"] * 60  # noqa: E731

    Q65 = {"g375": ("0,591", "0,589", "62,7%", "0,883", "69,3%", "10,0"), "ge4": ("0,521", "0,547", "53,1%", "0,856", "58,1%", "9,6"),
           "q375": ("0,640", "0,627", "66,4%", "0,915", "66,0%", "2,3"), "qe4": ("0,497", "0,530", "57,7%", "0,861", "58,8%", "2,2")}
    for k, t in Q65.items():
        m, m5 = M.calcular(b, C[k]), M.calcular(b, C[k], min_suporte=5)
        calc = (pt(m["macro"], 3), pt(m5["macro"], 3), pct(m["concordancia"]), pt(m["f1par"], 3), pct(m["estadoCerto"]), pt(rpm(C[k]), 1))
        for col, a, e in zip(("macro-F1", "macro-F1 ≥ 5 casos", "concordância", "F1 pares", "estado certo", "rel/min"), calc, t):
            ver("Quadro 6.5", f"{k}: {col}", a, e)
    for k, t in (("g375", "0,567"), ("q375", "0,618")):
        ver("6.2", f"{k}: macro-F1 sem os 23 de desenvolvimento", pt(M.calcular(b, C[k], b.relatorios(C[k], "avaliacao"))["macro"], 3), t)
    for k, n in (("ge4", "e4"), ("g375", "375")):
        f1 = {f["estado"]: f["sup"] for f in M.calcular(b, C[k])["f1"]}
        ver("6.2", f"pares em qualificação e em proposta ({n})", f"{f1['2. Qualificação']} e {f1['3. Proposta / Orçamento']}",
            "63 e 76" if n == "e4" else "57 e 52")
    ver("6.2", "pares a mais na quarta etapa, gemma4:26b contra qwen3.8",
        f"{M.calcular(b, C['ge4'])['paresAMais']} contra {M.calcular(b, C['qe4'])['paresAMais']}", "67 contra 32")
    ver("6.2", "cobertura na quarta etapa, qwen3.8 contra gemma4:26b",
        f"{pct(M.calcular(b, C['qe4'])['cobPipe'])} contra {pct(M.calcular(b, C['ge4'])['cobPipe'])}", "70,4% contra 81,7%")
    t = M.comparar(b, C["ge4"], C["qe4"])
    ver("6.2", "diferença de macro-F1, qwen3.8 − gemma4:26b (e4)", pt(t["dif"], 3), "−0,024")
    ver("6.2", "IC95 dessa diferença", ic(t["ic"], 3), "[−0,090; 0,043]")
    ver("6.2", "McNemar: só qwen3.8 / só gemma4:26b", f"{t['so_b']} / {t['so_a']}", "38 / 22")
    ver("6.2", "p", pt(t["p"], 3), "0,052")

    # Quadro 6.7: c05 -> c05r
    for a_, b_, n, tm, tic, tc, tmc, tp, tman in (
            ("g375", "gr375", "375", "0,591 → 0,620", "+0,029 [−0,014; +0,079]", "62,7% → 63,2%", "10 / 12", "0,83", "12/18 → 14/19"),
            ("ge4", "gre4", "e4", "0,521 → 0,548", "+0,027 [+0,000; +0,060]", "53,1% → 56,2%", "4 / 15", "0,02", "30/44 → 35/44")):
        t = M.comparar(b, C[a_], C[b_])
        ver("Quadro 6.7", f"{n}: macro-F1", f"{pt(t['a']['macro'], 3)} → {pt(t['b']['macro'], 3)}", tm)
        ver("Quadro 6.7", f"{n}: diferença (IC95)", f"{'+' if t['dif'] > 0 else ''}{pt(t['dif'], 3)} {ic(t['ic'], 3, sinal=True)}", tic)
        ver("Quadro 6.7", f"{n}: concordância", f"{pct(t['a']['concordancia'])} → {pct(t['b']['concordancia'])}", tc)
        ver("Quadro 6.7", f"{n}: McNemar só c05 / só c05r", f"{t['so_a']} / {t['so_b']}", tmc)
        ver("Quadro 6.7", f"{n}: p", pt(t["p"], 2), tp)
        ver("Quadro 6.7", f"{n}: anotação mantém a fase, certos", f"{mantem(b, C[a_])} → {mantem(b, C[b_])}", tman)
    ver("6.2", "anotação muda a fase e o modelo mantém-na, c05 → c05r (e4)",
        f"{muda_mantem(b, C['ge4'])} para {muda_mantem(b, C['gre4'])}", "7 para 8")

    # Anexo L
    for a_, b_, n, tm, tic, tc, tmc, tp in (
            ("ge4s", "ge4", "gemma4:26b", "0,485 → 0,521", "+0,036 [+0,000; +0,080]", "52,0% → 53,1%", "9 / 13", "0,52"),
            ("qe4s", "qe4", "qwen3.8", "0,473 → 0,497", "+0,024 [+0,006; +0,050]", "55,7% → 57,7%", "1 / 8", "0,04")):
        t = M.comparar(b, C[a_], C[b_])
        ver("Quadro L.1", f"{n}: macro-F1", f"{pt(t['a']['macro'], 3)} → {pt(t['b']['macro'], 3)}", tm)
        ver("Quadro L.1", f"{n}: diferença (IC95)", f"{'+' if t['dif'] > 0 else ''}{pt(t['dif'], 3)} {ic(t['ic'], 3, sinal=True)}", tic)
        ver("Quadro L.1", f"{n}: concordância", f"{pct(t['a']['concordancia'])} → {pct(t['b']['concordancia'])}", tc)
        ver("Quadro L.1", f"{n}: McNemar", f"{t['so_a']} / {t['so_b']}", tmc)
        ver("Quadro L.1", f"{n}: p", pt(t["p"], 2), tp)
    ens = [("e2A", "Segunda etapa, sem o estado da primeira", "0,548", "+0,001 [−0,034; +0,038]", "58,2%", "9 / 16", "0,69"),
           ("e2B", "Segunda etapa, com o estado da primeira", "0,519", "−0,028 [−0,069; +0,010]", "57,1%", "13 / 16", "1,00"),
           ("id", "Passo de identidade", "0,471", "−0,077 [−0,149; −0,014]", "54,5%", "35 / 29", "1,00")]
    ts = {k: M.comparar(b, C["gre4"], C[k]) for k, *_ in ens}
    ph = dict(zip(ts, M.holm([ts[k]["p"] for k in ts])))
    ver("Quadro L.2", "c05r: macro-F1 e concordância", f"{pt(ts['e2A']['a']['macro'], 3)}, {pct(ts['e2A']['a']['concordancia'])}", "0,548, 56,2%")
    for k, n, tm, tic, tc, tmc, tph in ens:
        t = ts[k]
        ver("Quadro L.2", f"{n}: macro-F1", pt(t["b"]["macro"], 3), tm)
        ver("Quadro L.2", f"{n}: diferença (IC95)", f"{'+' if t['dif'] > 0 else ''}{pt(t['dif'], 3)} {ic(t['ic'], 3, sinal=True)}", tic)
        ver("Quadro L.2", f"{n}: concordância", pct(t["b"]["concordancia"]), tc)
        ver("Quadro L.2", f"{n}: McNemar só c05r / só ensaio", f"{t['so_a']} / {t['so_b']}", tmc)
        ver("Quadro L.2", f"{n}: p com Holm", pt(ph[k], 2), tph)
    for k, t in (("g8_375", "0,626"), ("g375", "0,591"), ("g8_e4", "0,514"), ("ge4", "0,521"), ("q35_375", "0,528"), ("q35_e4", "0,462")):
        ver("Anexo L", f"{k}: macro-F1", pt(M.calcular(b, C[k])["macro"], 3), t)
    c8, c4 = M.calcular(b, C["g8_e4"])["concordancia"], M.calcular(b, C["ge4"])["concordancia"]
    ver("Anexo L", "q8 e 4 bits: mesma concordância na quarta etapa", "sim" if c8 == c4 else "não", "sim")


def mantem(b, cid):
    """Pares em que a anotação mantém o último estado do bloco: certos / total."""
    certo = total = 0
    for x in b.respostas[cid].values():
        if x["erro"]:
            continue
        lig, _p, _e = M.emparelhar(x["pares"], x["g"]["pares"])
        for g1, p1 in lig:
            if len(g1) > 3 and g1[3] == 1:
                total += 1
                certo += g1[2] == p1[2]
    return f"{certo}/{total}"


def muda_mantem(b, cid):
    """Pares em que a anotação muda a fase e o modelo mantém o último estado do bloco."""
    n = 0
    for x in b.respostas[cid].values():
        if x["erro"]:
            continue
        lig, _p, _e = M.emparelhar(x["pares"], x["g"]["pares"])
        n += sum(1 for g1, p1 in lig if len(g1) > 3 and g1[3] == 0 and len(p1) > 4 and p1[4] == 1)
    return n


def reprodutibilidade():
    """6.2: três corridas por modelo sobre os 20 relatórios da segunda etapa."""
    b = M.Benchmark()
    for modelo in ("gemma4:26b", "qwen3.8:latest"):
        cs = [c["id"] for c in b.corridas if c["id"].startswith(f"{modelo}|c05|e05|v3|261009-13")]
        ver("6.2 RF1.5", f"{modelo}: corridas de 20 relatórios", str(len(cs)), "3")
        assin = [{r: (x["com"], x["erro"], sorted(map(str, x["pares"]))) for r, x in b.respostas[c].items()} for c in cs]
        iguais = all(a == assin[0] for a in assin[1:])
        ver("6.2 RF1.5", f"{modelo}: respostas iguais, excertos incluídos", "sim" if iguais else "não", "sim")
        ver("6.2 RF1.5", f"{modelo}: erros", str(sum(1 for a in assin for v in a.values() if v[1])), "0")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--so-difere", action="store_true")
    a = ap.parse_args()
    terceira_etapa()
    haiku()
    quarta_etapa()
    reprodutibilidade()
    secao = None
    for s, rot, calc, tese, ok in LINHAS:
        if a.so_difere and ok:
            continue
        if s != secao:
            print(f"\n{s}"); secao = s
        print(f"  {'ok ' if ok else 'DIF'}  {rot:<62} {calc:<20} tese: {tese}")
    n = sum(1 for x in LINHAS if not x[4])
    print(f"\n{len(LINHAS)} números verificados, {n} diferentes da dissertação")
    return n


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
