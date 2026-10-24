# -*- coding: utf-8 -*-
"""Painel HTML dos resultados do benchmark.

    python painel.py                        a partir da exportação anonimizada
    python painel.py --base --amostra F     a partir da base de dados, com os textos

Escreve resultados/painel_benchmark.html, um ficheiro autónomo, sem dependências
nem rede, que se abre no browser.

Por omissão lê benchmark/anonimo/benchmark_anonimo.json.gz (ver exportar.py), que
está no repositório: o painel gera-se sem base de dados e sem texto dos relatórios
nem nomes de clientes. Com --base lê a base de dados (exige as credenciais do .env
e o ficheiro F dos relatórios das fases 1 e 2) e leva o texto de cada relatório,
para iterar o prompt; esse ficheiro tem dados da empresa e não sai de resultados/.

A página leva todas as corridas; a tarefa (prompt, esquema e entrada), o conjunto de
relatórios e a execução escolhem-se nela. As métricas são as do §3.2.2 e os testes os
do §3.3, calculados por metricas.py, a mesma implementação que reproduz os números da
dissertação (reproduzir.py), e com as mesmas convenções: as corridas da entrada v2 (a
terceira etapa) contra a anotação v2, sem a regra dos pares repetidos; as restantes
contra a anotação da sua entrada (v3 ou e4), com essa regra. A página só filtra,
ordena e mostra.
"""

import argparse
import copy
import gzip
import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI.parent / "classificador"))

import exportar           # noqa: E402
import metricas as M      # noqa: E402

LIMIAR_MACRO = 0.60      # RF1.8
LIMIAR_COBERTURA = 0.90  # RF1.4

# Os relatórios usados para iterar o prompt e o esquema (fases 1 e 2 do protocolo de
# seleção). Ficam fora da métrica que decide o modelo na terceira etapa: afinar uma
# instrução sobre um conjunto e medir o resultado sobre um conjunto que o contém faz a
# medição favorecer a instrução, e com ela os modelos que melhor a seguiram nesses casos.
AMOSTRA = AQUI.parent / "resultados" / "260916_amostra_fases.json"
SAIDA = AQUI.parent / "resultados" / "painel_benchmark.html"
CONJUNTOS = {"todos": "todos", "aval": "avaliacao", "dev": "desenvolvimento"}


def para_js(m: dict, indice) -> dict:
    """As métricas de metricas.calcular com os nomes que a página usa."""
    chaves = ("rel", "comOk", "comFN", "comFP", "goldP", "meusP", "ligados", "tipoOk", "lead", "cicloMeus",
              "indet", "cicloGold", "cobGoldOk", "estOk", "estN", "falhas", "certos", "conf", "fn", "fp",
              "suporte", "macroLig", "prec", "rev", "f1par", "cobertura", "cobPipe", "conteudo", "tipo",
              "porTipificar", "estadoCerto", "distancia", "concordancia")
    out = {k: m[k] for k in chaves}
    out.update(erros={"infra": m["infra"], "leitura": m["leitura"]}, macroPP=m["macro"],
               f1=[{"sup": f["sup"], "lig": f["lig"], "pp": f["pp"]} for f in m["f1"]],
               porRel={indice(r): k for r, k in m["por_rel"].items()})
    return out


def comparacoes(bm, corridas, met) -> dict:
    """McNemar contra o de maior macro-F1, com Holm, por tarefa, execução e conjunto.

    Entram as corridas que cobrem a amostra da tarefa (pelo menos 90% dos relatórios da
    maior), e de cada modelo a última; os ensaios sobre subconjuntos ficam de fora, como
    na terceira etapa. As corridas de tarefas diferentes não se comparam."""
    out = {}
    tarefas = sorted({tarefa(c) for c in corridas if c["rel"] > 0})
    for t in tarefas:
        da_tarefa = [c for c in corridas if c["rel"] > 0 and tarefa(c) == t]
        maior = max(c["rel"] for c in da_tarefa)
        ultima = {}
        for c in da_tarefa:
            if c["rel"] >= 0.9 * maior:
                ultima[c["modelo"]] = c
        b = bm(da_tarefa[0])
        for exe in ("*", "local", "nuvem"):
            cs = [c for c in ultima.values() if exe == "*" or (c["backend"] == "ollama") == (exe == "local")]
            if len(cs) < 2:
                continue
            for k, cj in CONJUNTOS.items():
                ref = max(cs, key=lambda c: met[k][c["i"]]["macroPP"] or 0)
                testes = []
                for c in cs:
                    if c is ref:
                        continue
                    base = M.comuns(b, ref["id"], c["id"], conjunto=cj)
                    x = M.comparar(b, ref["id"], c["id"], base=base, replicas=0)
                    testes.append({"i": c["i"], "b": x["so_a"], "c": x["so_b"], "n": x["n"], "p": x["p"]})
                for tt, ph in zip(testes, M.holm([tt["p"] for tt in testes])):
                    tt["holm"] = ph
                out[f"{t}|{exe}|{k}"] = {"ref": ref["i"], "testes": sorted(testes, key=lambda x: x["p"])}
    return out


def tarefa(c):
    return f"{c['prompt']}/{c['esquema']}/{c['entrada']}"


def ler(base: bool, amostra: Path) -> dict:
    """Os dados no formato de exportar.recolher: da base, com texto, ou da exportação."""
    if base:
        return exportar.recolher(amostra, anonimizar=False, com_texto=True)
    with gzip.open(M.DADOS, "rt", encoding="utf-8") as f:
        return json.load(f)


def recolher(base=False, amostra=AMOSTRA) -> dict:
    """Corridas, anotação e respostas, e as métricas já calculadas para cada corrida."""
    d = ler(base, amostra)
    terceira = M.Benchmark(dados=copy.deepcopy(d), anotacao={"v2": "v2"}, juntar=False)   # Quadros 6.1 a 6.4
    restantes = M.Benchmark(dados=d)                                       # Quadros 6.5 a 6.7, Anexo L
    bm = lambda c: terceira if c["entrada"] == "v2" else restantes  # noqa: E731
    idx = {(r["r"], r["versao"]): i for i, r in enumerate(d["relatorios"])}
    met = {k: {} for k in CONJUNTOS}
    respostas = []
    for c in d["corridas"]:
        b, cid = bm(c), c["id"]
        rs = b.respostas.get(cid, {})
        indice = lambda r, rs=rs: idx[(r, rs[r]["versao"])]  # noqa: E731
        for k, cj in CONJUNTOS.items():
            met[k][c["i"]] = para_js(M.calcular(b, cid, b.relatorios(cid, cj)), indice)
        for r, x in rs.items():
            respostas.append([c["i"], indice(r), x["com"], x["erro"], x.get("nota") or "", [p[:3] for p in x["pares"]]])
        c["curto"] = c["modelo"].split("/")[-1]
        c["rpm"] = round(c["rel"] / c["seg"] * 60, 1) if c["seg"] else None
    for r in d["relatorios"]:
        r.setdefault("cliente", r["r"])
        r.setdefault("texto", "")
    estados, tipos = d["estados"], d["tipos"]
    return {
        "gerado": d["gerado"], "estados": estados, "tipos": tipos, "com_texto": base,
        "ciclo": [tipos.index(t) for t in M.TIPOS_DO_CICLO],
        "indeterminado": estados.index(M.INDETERMINADO),
        "fora_media": [estados.index(e) for e in M.FORA_DA_MEDIA],
        "limiares": {"macro": LIMIAR_MACRO, "cobertura": LIMIAR_COBERTURA},
        "n_dev": len({r["r"] for r in d["relatorios"] if r["dev"]}),
        "corridas": d["corridas"], "relatorios": d["relatorios"], "respostas": respostas,
        "metricas": met, "mcnemar": comparacoes(bm, d["corridas"], met),
    }


CSS = """
:root{color-scheme:light;
 --sup:#fcfcfb; --sup2:#f3f3f1; --sup3:#e9e9e6; --linha:#e2e2de;
 --ink:#0b0b0b; --ink2:#52514e; --ink3:#78766f;
 --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4;
 --bom:#0ca30c; --aviso:#fab219; --grave:#ec835a; --critico:#d03b3b;}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){
 color-scheme:dark; --sup:#1a1a19; --sup2:#232322; --sup3:#2c2c2a;
 --linha:#35352f; --ink:#fff; --ink2:#c3c2b7; --ink3:#93928a;
 --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;}}
:root[data-theme=dark]{color-scheme:dark; --sup:#1a1a19; --sup2:#232322;
 --sup3:#2c2c2a; --linha:#35352f; --ink:#fff; --ink2:#c3c2b7; --ink3:#93928a;
 --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181;}
*{box-sizing:border-box}
body{margin:0;background:var(--sup);color:var(--ink);
 font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.env{max-width:1320px;margin:0 auto;padding:26px 16px 80px}
h1{font-size:21px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:15px;margin:32px 0 6px;font-weight:600}
h3{font-size:13px;margin:20px 0 6px;font-weight:600;color:var(--ink2)}
.sub{color:var(--ink2);margin:0 0 10px;font-size:13px;max-width:80ch}
.caixa{background:var(--sup2);border:1px solid var(--linha);border-radius:8px;
 padding:12px 14px;margin:14px 0;color:var(--ink2);font-size:13px}
.barrafiltro{position:sticky;top:0;z-index:9;background:var(--sup);
 border-bottom:1px solid var(--linha);padding:10px 0 12px;margin-bottom:6px;
 display:flex;flex-wrap:wrap;gap:8px 16px;align-items:flex-end}
.campo{display:flex;flex-direction:column;gap:3px}
.campo>label{font-size:11px;color:var(--ink3);text-transform:uppercase;
 letter-spacing:.04em}
select,button.b{background:var(--sup2);color:var(--ink);border:1px solid var(--linha);
 border-radius:6px;padding:5px 8px;font:inherit;font-size:13px}
button.b{cursor:pointer}
button.b:hover{background:var(--sup3)}
.chips{display:flex;flex-wrap:wrap;gap:5px;max-width:100%}
.chip{border:1px solid var(--linha);background:var(--sup2);color:var(--ink2);
 border-radius:20px;padding:3px 10px;font-size:12px;cursor:pointer;
 font-family:ui-monospace,Menlo,monospace}
.chip.on{background:var(--s1);border-color:var(--s1);color:#fff}
.opc{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--ink2)}
.rolo{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:5px 9px;border-bottom:1px solid var(--linha);
 vertical-align:middle}
th{font-weight:600;color:var(--ink2);font-size:11.5px;white-space:nowrap;
 cursor:pointer;user-select:none;position:relative}
th:hover{color:var(--ink)}
th.sel{color:var(--ink)}
th.sel::after{content:attr(data-seta);position:absolute;margin-left:3px;
 font-size:9px}
td.n,th.n{text-align:right;white-space:nowrap}
tbody tr:hover{background:var(--sup2)}
.mod{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
 white-space:nowrap}
.tar{font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--ink3)}
.q{color:var(--ink3);font-size:10.5px;font-weight:400}
.cal{display:inline-block;min-width:34px}
.bar{display:inline-block;height:9px;border-radius:2px;background:var(--s1);
 vertical-align:1px;margin-left:6px}
.pass{color:var(--bom);font-weight:600}
.falha{color:var(--critico);font-weight:600}
.leve{color:var(--ink3)}
.pilha{display:flex;height:12px;gap:1px;min-width:90px}
.pilha span{height:12px}
.pilha span:first-child{border-radius:3px 0 0 3px}
.pilha span:last-child{border-radius:0 3px 3px 0}
.leg{display:flex;flex-wrap:wrap;gap:12px;margin:6px 0 10px;font-size:12px;
 color:var(--ink2)}
.leg i{display:inline-block;width:10px;height:10px;border-radius:2px;
 margin-right:5px;vertical-align:-1px}
.par{font-family:ui-monospace,Menlo,monospace;font-size:11.5px;color:var(--ink2)}
details{margin:4px 0;border:1px solid var(--linha);border-radius:7px;
 padding:6px 10px;background:var(--sup2)}
summary{cursor:pointer;font-size:13px}
pre.rel{white-space:pre-wrap;font:11.5px/1.5 ui-monospace,Menlo,monospace;
 color:var(--ink2);background:var(--sup);border:1px solid var(--linha);
 border-radius:6px;padding:8px 10px;margin:8px 0;max-height:280px;
 overflow:auto}
.oculto{display:none}
.mat td,.mat th{padding:3px 6px;font-size:11.5px;text-align:center}
.mat td.d{font-weight:700}
.tema{position:fixed;bottom:14px;right:16px;z-index:20}
.rf{font-size:10.5px;color:var(--ink3);font-weight:400}
.tabs{display:flex;gap:4px;margin:18px 0 0;border-bottom:1px solid var(--linha);
 flex-wrap:wrap}
.tabs button{background:none;border:none;border-bottom:2px solid transparent;
 color:var(--ink2);font:inherit;font-size:13px;padding:7px 12px;cursor:pointer}
.tabs button.on{color:var(--ink);border-bottom-color:var(--s1);font-weight:600}
"""

JS = r"""
const D = DADOS;
const EST = D.estados, TIP = D.tipos;
const CICLO = new Set(D.ciclo), FORA = new Set(D.fora_media);
const IND = D.indeterminado;
const CORES = ['var(--s1)','var(--s2)','var(--s3)','var(--s4)','var(--s5)'];
const FALHAS = [['conteudo','conteúdo comercial'],['n_pares','número de pares'],
                ['negocio','negócio apontado'],['tipo','tipo'],['estado','estado']];

/* ---------- respostas indexadas por corrida ---------- */
const POR_CORRIDA = new Map();
for (const r of D.respostas) {
  if (!POR_CORRIDA.has(r[0])) POR_CORRIDA.set(r[0], []);
  POR_CORRIDA.get(r[0]).push({rel: r[1], com: r[2], erro: r[3], nota: r[4], pares: r[5]});
}

const S = {tarefa: '', backend: '*', ultimas: true, modelos: new Set(),
           base: '', nova: '', soDif: false, texto: false, aba: 'niveis',
           ordem: {}, matriz: '', conjunto: 'todos'};

const tarefaDe = c => c.prompt + '/' + c.esquema + '/' + c.entrada;
const TAREFAS = [...new Set(D.corridas.filter(c => c.rel > 0).map(tarefaDe))];

/* ---------- metricas ---------- */
/* Calculadas em Python por metricas.py, a unica implementacao, para cada corrida e
   cada conjunto de relatorios. A pagina so as mostra. */
const metricas = i => D.metricas[S.conjunto][i];
const media = xs => xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;

/* ---------- selecao ---------- */
function visiveis() {
  let cs = D.corridas.filter(c => c.rel > 0);
  if (S.tarefa !== '*') cs = cs.filter(c => tarefaDe(c) === S.tarefa);
  if (S.backend !== '*')
    cs = cs.filter(c => (c.backend === 'ollama') === (S.backend === 'local'));
  if (S.ultimas) {
    const u = new Map();
    for (const c of cs) u.set(c.modelo + '\u0000' + tarefaDe(c), c);  /* ordem cronologica */
    cs = [...u.values()];
  }
  if (S.modelos.size) cs = cs.filter(c => S.modelos.has(c.modelo));
  return cs;
}

/* ---------- formatacao ---------- */
const esc = s => String(s === null || s === undefined ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const virg = s => s.replace('.', ',').replace('-', '−');
const pc = x => x === null || x === undefined ? '–' : virg((x * 100).toFixed(0)) + '%';
const n2 = x => x === null || x === undefined ? '–' : virg(x.toFixed(2));
const pv = x => x < 0.001 ? '&lt; 0,001' : virg(x.toFixed(3));
const frac = (a, b) => '<span class="q"> ' + a + '/' + b + '</span>';
function cel(x, a, b) { return '<span class="cal">' + pc(x) + '</span>' + frac(a, b); }
function limiar(x, lim, txt) {
  if (x === null) return '<span class="leve">–</span>';
  return '<span class="' + (x >= lim ? 'pass' : 'falha') + '">' + txt + '</span>';
}
function bar(x, largura) {
  if (x === null) return '';
  return '<span class="bar" style="width:' + Math.max(0, x * largura).toFixed(1) + 'px"></span>';
}

/* ---------- tabela generica, ordenavel ---------- */
function tabela(chaveTab, cols, linhas) {
  const o = S.ordem[chaveTab] || {k: cols.find(c => c.pre) ? cols.find(c => c.pre).k : cols[0].k, dir: -1};
  const col = cols.find(c => c.k === o.k) || cols[0];
  const ls = linhas.slice().sort((a, b) => {
    let x = a.ord[col.k], y = b.ord[col.k];
    const nx = x === null || x === undefined, ny = y === null || y === undefined;
    if (nx && ny) return 0;
    if (nx) return 1;
    if (ny) return -1;
    if (typeof x === 'string') return o.dir * (x < y ? -1 : x > y ? 1 : 0);
    return o.dir * (x - y);
  });
  const th = cols.map(c =>
    '<th class="' + (c.n ? 'n ' : '') + (c.k === o.k ? 'sel' : '') + '" data-seta="'
    + (o.dir < 0 ? '▼' : '▲') + '" data-tab="' + chaveTab + '" data-col="' + c.k
    + '" title="' + esc(c.tit || '') + '">' + c.r
    + (c.rf ? ' <span class="rf">' + c.rf + '</span>' : '') + '</th>').join('');
  const tb = ls.map(l => '<tr>' + cols.map(c =>
    '<td class="' + (c.n ? 'n' : '') + (c.cls || '') + '">' + (l.cel[c.k] || '') + '</td>').join('')
    + '</tr>').join('');
  return '<div class="rolo"><table><thead><tr>' + th + '</tr></thead><tbody>'
    + tb + '</tbody></table></div>';
}

document.addEventListener('click', ev => {
  const th = ev.target.closest('th[data-col]');
  if (th) {
    const t = th.dataset.tab, k = th.dataset.col;
    const o = S.ordem[t];
    S.ordem[t] = (o && o.k === k) ? {k, dir: -o.dir} : {k, dir: -1};
    render();
  }
});

/* ---------- niveis 1 e 2 ---------- */
function linhaBase(c) {
  return {cel: {modelo: '<span class="mod">' + esc(c.curto) + '</span>',
                tarefa: '<span class="tar">' + tarefaDe(c) + '</span>'},
          ord: {modelo: c.curto, tarefa: tarefaDe(c)}};
}

function secNivel1(cs) {
  const cols = [
    {k: 'modelo', r: 'modelo'}, {k: 'tarefa', r: 'tarefa'},
    {k: 'rel', r: 'rel', n: true, tit: 'relatórios anotados com resposta válida'},
    {k: 'com', r: 'conteúdo comercial', rf: 'RF1.1', n: true, pre: true,
     tit: 'proporção de decisões corretas sobre haver ou não conteúdo comercial'},
    {k: 'fn', r: 'falsos neg.', n: true,
     tit: 'relatório com conteúdo comercial dado como sem: o §3.2.2 pede atenção particular, porque nunca chega ao nível 2'},
    {k: 'rev', r: 'revocação', n: true,
     tit: 'pares da anotação que o modelo encontrou'},
    {k: 'prec', r: 'precisão', n: true,
     tit: 'pares propostos pelo modelo que existem na anotação'},
    {k: 'f1', r: 'F1 dos pares', n: true, tit: 'média harmónica das duas'},
    {k: 'tipo', r: 'tipo', rf: 'RF1.2', n: true,
     tit: 'exatidão do tipo nos pares que os dois lados apontam ao mesmo negócio'},
    {k: 'lead', r: 'por tipificar', n: true,
     tit: 'proporção de pares que o modelo deixou por tipificar (lead): cobertura da tipificação, RF1.2, reportada à parte'},
  ];
  const ls = cs.map(c => {
    const m = metricas(c.i), l = linhaBase(c);
    l.cel.rel = m.rel; l.ord.rel = m.rel;
    l.cel.com = cel(m.conteudo, m.comOk, m.rel); l.ord.com = m.conteudo;
    l.cel.fn = m.comFN ? '<span class="falha">' + m.comFN + '</span>' : '0';
    l.ord.fn = -m.comFN;
    l.cel.rev = cel(m.rev, m.ligados, m.goldP); l.ord.rev = m.rev;
    l.cel.prec = cel(m.prec, m.ligados, m.meusP); l.ord.prec = m.prec;
    l.cel.f1 = pc(m.f1par) + bar(m.f1par, 40); l.ord.f1 = m.f1par;
    l.cel.tipo = cel(m.tipo, m.tipoOk, m.ligados); l.ord.tipo = m.tipo;
    l.cel.lead = cel(m.porTipificar, m.lead, m.meusP);
    l.ord.lead = m.porTipificar === null ? null : -m.porTipificar;
    return l;
  });
  return '<h2>Nível 1: o relatório tem conteúdo comercial, de que negócio fala, '
    + 'e de que tipo é</h2><p class="sub">As três decisões do primeiro nível, '
    + 'cada uma sobre o denominador que lhe compete (§3.2.2). Um par não '
    + 'identificado não pode ter estado certo, pelo que a revocação desta tabela '
    + 'é o teto do nível 2. Uma resposta inválida conta como relatório por '
    + 'classificar e entra em todos os denominadores.</p>' + tabela('n1', cols, ls);
}

function secNivel2(cs) {
  const cols = [
    {k: 'modelo', r: 'modelo'}, {k: 'tarefa', r: 'tarefa'},
    {k: 'cobp', r: 'cobertura do pipeline', rf: 'RF1.4 ≥ 90%', n: true,
     tit: 'pares do ciclo da anotação (sem os indeterminados) que o modelo encontrou, no negócio certo, e a que deu um estado que não o indeterminado; denominador igual para todos os modelos'},
    {k: 'cob', r: 'estado atribuído', n: true,
     tit: 'pares do ciclo produzidos pelo próprio modelo que não ficaram em indeterminado: mede quanto o modelo se compromete (o complemento da abstenção), não se acerta; o denominador é o de cada modelo'},
    {k: 'macro', r: 'macro-F1 ponta a ponta', rf: 'RF1.8 ≥ 0,60', n: true, pre: true,
     tit: 'média do F1 pelos estados com suporte, carregando como falso negativo o par que o nível 1 não encontrou'},
    {k: 'macrolig', r: 'macro-F1 nos ligados', n: true,
     tit: 'a mesma média, só sobre os pares que os dois lados apontam ao mesmo negócio: isola o nível 2 do nível 1'},
    {k: 'ac', r: 'acurácia do estado', n: true,
     tit: 'pares ligados com estado certo; insuficiente como métrica de decisão por as classes serem muito desiguais'},
    {k: 'dist', r: 'distância do erro', n: true,
     tit: 'média das posições de distância no ciclo quando o estado está errado: errar um estado adjacente não é errar quatro'},
    {k: 'sup', r: 'estados com suporte', n: true,
     tit: 'quantos estados entram na média; fecho e indeterminado ficam de fora por decisão do §3.2.2'},
  ];
  const ls = cs.map(c => {
    const m = metricas(c.i), l = linhaBase(c);
    l.cel.cobp = limiar(m.cobPipe, D.limiares.cobertura, pc(m.cobPipe))
      + frac(m.cobGoldOk, m.cicloGold);
    l.ord.cobp = m.cobPipe;
    l.cel.cob = pc(m.cobertura) + frac(m.cicloMeus - m.indet, m.cicloMeus);
    l.ord.cob = m.cobertura;
    l.cel.macro = limiar(m.macroPP, D.limiares.macro, n2(m.macroPP)) + bar(m.macroPP, 40);
    l.ord.macro = m.macroPP;
    l.cel.macrolig = n2(m.macroLig); l.ord.macrolig = m.macroLig;
    l.cel.ac = cel(m.estadoCerto, m.estOk, m.estN); l.ord.ac = m.estadoCerto;
    l.cel.dist = n2(m.distancia); l.ord.dist = m.distancia === null ? null : -m.distancia;
    l.cel.sup = m.suporte + '<span class="q">/' + (EST.length - FORA.size) + '</span>';
    l.ord.sup = m.suporte;
    return l;
  });
  const alerta = ls.length && cs.every(c => metricas(c.i).estN < 30)
    ? '<div class="caixa">Atenção: o denominador do estado está abaixo de 30 pares '
      + 'em todos os modelos. O macro-F1 desta tabela não decide modelo nenhum: o '
      + 'erro de amostragem é maior do que as diferenças que se querem detetar, '
      + 'como o protocolo de fases fixou. Serve para ver <b>onde</b> falha, não '
      + '<b>quem</b> é melhor.</div>' : '';
  return '<h2>Nível 2: o estado da oportunidade</h2><p class="sub">Aplica-se só aos '
    + 'tipos que percorrem o ciclo. A métrica de decisão é o macro-F1 pelos estados '
    + 'cujo critério de verdade está no próprio texto do relatório, que exclui o '
    + 'fecho, confirmado pela faturação, e o indeterminado, que é ausência de '
    + 'sinal e não uma fase.</p>' + alerta + tabela('n2', cols, ls);
}

/* ---------- operacao e falhas ---------- */
function secOperacao(cs) {
  const cols = [
    {k: 'modelo', r: 'modelo'}, {k: 'tarefa', r: 'tarefa'},
    {k: 'onde', r: 'onde falha', tit: 'composição das discordâncias, do mais grosso ao mais fino'},
    {k: 'certo', r: 'concordância exata', n: true, pre: true,
     tit: 'relatórios em que tudo coincide com a anotação: diagnóstico, não métrica de decisão'},
    {k: 'rpm', r: 'resp/min', n: true, tit: 'critério de corte da fase 2'},
    {k: 'infra', r: 'falhas de infra', n: true,
     tit: 'a corrida não serve; não é desempenho na tarefa'},
    {k: 'leitura', r: 'falhas de leitura', n: true,
     tit: 'resposta que não respeita o contrato de saída'},
    {k: 'tok', r: 'tokens', n: true}, {k: 'maq', r: 'máquina'},
    {k: 'quando', r: 'corrida'},
  ];
  const ls = cs.map(c => {
    const m = metricas(c.i), l = linhaBase(c);
    const tot = Object.values(m.falhas).reduce((a, b) => a + b, 0);
    l.cel.onde = pilha(m.falhas, tot); l.ord.onde = m.concordancia;
    l.cel.certo = cel(m.concordancia, m.certos, m.rel); l.ord.certo = m.concordancia;
    l.cel.rpm = c.rpm === null ? '–' : c.rpm; l.ord.rpm = c.rpm;
    l.cel.infra = m.erros.infra ? '<span class="falha">' + m.erros.infra + '</span>' : '0';
    l.ord.infra = -m.erros.infra;
    l.cel.leitura = m.erros.leitura ? '<span class="falha">' + m.erros.leitura + '</span>' : '0';
    l.ord.leitura = -m.erros.leitura;
    l.cel.tok = (c.t_in + c.t_out).toLocaleString('pt-PT'); l.ord.tok = c.t_in + c.t_out;
    l.cel.maq = '<span class="tar">' + esc(c.backend) + '</span>'; l.ord.maq = c.backend;
    l.cel.quando = '<span class="tar">' + esc(c.quando) + '</span>'; l.ord.quando = c.quando;
    return l;
  });
  const leg = FALHAS.map((f, i) => '<span><i style="background:' + CORES[i] + '"></i>'
    + f[1] + '</span>').join('')
    + '<span><i style="background:var(--bom)"></i>igual à anotação</span>'
    + '<span><i style="background:var(--critico)"></i>erro</span>';
  return '<h2>Operação e composição do erro</h2><p class="sub">A concordância exata '
    + 'é o tudo-ou-nada do relatório inteiro, útil para ver a composição da falha e '
    + 'para o teste de McNemar, e nada mais. As falhas vão separadas entre '
    + 'infraestrutura e leitura da resposta, por serem problemas de natureza '
    + 'distinta.</p><div class="leg">' + leg + '</div>' + tabela('op', cols, ls);
}

function pilha(falhas, tot) {
  if (!tot) return '';
  let out = '';
  const certo = falhas.certo || 0;
  if (certo) out += '<span style="width:' + (certo / tot * 100).toFixed(1)
    + '%;background:var(--bom)" title="igual: ' + certo + '"></span>';
  FALHAS.forEach((f, i) => {
    const n = falhas[f[0]] || 0;
    if (n) out += '<span style="width:' + (n / tot * 100).toFixed(1) + '%;background:'
      + CORES[i] + '" title="' + f[1] + ': ' + n + '"></span>';
  });
  const erro = falhas.erro || 0;
  if (erro) out += '<span style="width:' + (erro / tot * 100).toFixed(1)
    + '%;background:var(--critico)" title="resposta inválida: ' + erro + '"></span>';
  return '<div class="pilha">' + out + '</div>';
}

/* ---------- efeito da versao do prompt ---------- */
function secEfeito() {
  const sel = t => '<select id="' + t + '">' + TAREFAS.map(x =>
    '<option value="' + x + '"' + (S[t] === x ? ' selected' : '') + '>' + x + '</option>').join('')
    + '</select>';
  const barra = '<div class="barrafiltro" style="position:static;border:0">'
    + '<div class="campo"><label>tarefa de partida</label>' + sel('base') + '</div>'
    + '<div class="campo"><label>tarefa de chegada</label>' + sel('nova') + '</div></div>';
  const ultima = {};
  for (const c of D.corridas) if (c.rel > 0) ultima[c.modelo + '\u0000' + tarefaDe(c)] = c;
  const modelos = [...new Set(D.corridas.filter(c => c.rel > 0).map(c => c.modelo))];
  const pares = modelos.map(mo => ({
    mo, a: ultima[mo + '\u0000' + S.base], b: ultima[mo + '\u0000' + S.nova]
  })).filter(p => p.a && p.b);
  if (!pares.length)
    return '<h2>Efeito da versão</h2>' + barra + '<div class="caixa">Nenhum modelo '
      + 'correu as duas tarefas, pelo que não há efeito a medir. É a razão pela qual '
      + 'uma alteração ao prompt obriga a repetir a corrida em todos os modelos '
      + 'antes de a comparação voltar a ser válida.</div>';
  const D2 = (x, y, abs) => {
    if (x === null || y === null || x === undefined || y === undefined)
      return {c: '–', o: null};
    const d = y - x;
    const s = (d > 0 ? '+' : d < 0 ? '−' : '')
      + (abs ? virg(Math.abs(d).toFixed(2)) : virg((Math.abs(d) * 100).toFixed(0)) + ' pp');
    return {c: '<span class="' + (d > 0 ? 'pass' : d < 0 ? 'falha' : 'leve') + '">' + s
            + '</span>', o: d};
  };
  const cols = [{k: 'modelo', r: 'modelo'},
    {k: 'rev', r: 'Δ revocação', n: true, pre: true},
    {k: 'prec', r: 'Δ precisão', n: true},
    {k: 'tipo', r: 'Δ tipo', n: true},
    {k: 'cobp', r: 'Δ cobertura do pipeline', n: true},
    {k: 'cob', r: 'Δ estado atribuído', n: true},
    {k: 'macro', r: 'Δ macro-F1', n: true},
    {k: 'certo', r: 'Δ concordância', n: true},
    {k: 'de', r: 'de'}, {k: 'para', r: 'para'}];
  const ls = pares.map(p => {
    const x = metricas(p.a.i), y = metricas(p.b.i);
    const l = {cel: {modelo: '<span class="mod">' + esc(p.a.curto) + '</span>'},
               ord: {modelo: p.a.curto}};
    const cs = {rev: [x.rev, y.rev], prec: [x.prec, y.prec], tipo: [x.tipo, y.tipo],
      cobp: [x.cobPipe, y.cobPipe], cob: [x.cobertura, y.cobertura], macro: [x.macroPP, y.macroPP],
      certo: [x.concordancia, y.concordancia]};
    for (const k in cs) {
      const d = D2(cs[k][0], cs[k][1], k === 'macro');
      l.cel[k] = d.c; l.ord[k] = d.o;
    }
    l.cel.de = '<span class="q">' + pc(cs.rev[0]) + ' / ' + n2(x.macroPP) + '</span>';
    l.cel.para = '<span class="q">' + pc(cs.rev[1]) + ' / ' + n2(y.macroPP) + '</span>';
    l.ord.de = 0; l.ord.para = 0;
    return l;
  });
  const somas = ['rev', 'prec', 'macro', 'certo'].map(k => {
    const v = media(ls.map(l => l.ord[k]).filter(x => x !== null));
    return k + ' ' + (v === null ? '–' : (v > 0 ? '+' : '')
      + (k === 'macro' ? n2(v) : virg((v * 100).toFixed(1)) + ' pp'));
  }).join(' · ');
  return '<h2>Efeito da versão do prompt e do esquema</h2><p class="sub">Uma '
    + 'alteração ao prompt é uma iteração de desenho e avalia-se como tal: a mesma '
    + 'amostra, os mesmos modelos, uma métrica declarada antes. A média dos deltas '
    + 'sobre ' + ls.length + ' modelos: <b>' + somas + '</b>.</p>' + barra
    + tabela('ef', cols, ls);
}

/* ---------- McNemar contra o melhor, com Holm (calculado em metricas.py) ---------- */
function secMcNemar(cs) {
  if (cs.length < 2 || S.tarefa === '*') return '';
  const x = D.mcnemar[S.tarefa + '|' + S.backend + '|' + S.conjunto];
  if (!x) return '';
  const nota = '<div class="caixa">O teste usa, de cada modelo, a última corrida desta tarefa '
      + 'sobre a amostra inteira, independentemente dos filtros de modelos; os ensaios sobre '
      + 'subconjuntos ficam de fora.</div>';
  const ref = D.corridas[x.ref], mref = metricas(x.ref);
  const linhas = x.testes.map(t => {
    const c = D.corridas[t.i], m = metricas(t.i);
    return '<tr><td class="mod">' + esc(c.curto) + '</td>'
      + '<td class="tar">' + tarefaDe(c) + '</td>'
      + '<td class="n">' + n2(m.macroPP) + '</td>'
      + '<td class="n">' + t.b + '</td><td class="n">' + t.c + '</td>'
      + '<td class="n">' + pv(t.p) + '</td>'
      + '<td class="n">' + pv(t.holm) + '</td>'
      + '<td>' + (t.holm < 0.05 ? '<span class="falha">inferior</span>'
        : '<span class="leve">não distinguível</span>') + '</td></tr>';
  }).join('');
  return '<h2>Comparação contra o melhor, com correção de Holm</h2>'
    + '<p class="sub">O procedimento fixado antes de correr: ' + x.testes.length + ' testes de '
    + 'McNemar sobre a concordância exata contra o modelo de maior macro-F1 observado, e não '
    + 'todos os pares. Quem não se distingue fica declarado equivalente, não pior. '
    + '<b>Referência: ' + esc(ref.curto) + '</b> (' + n2(mref.macroPP) + ').</p>' + nota
    + '<div class="rolo"><table><thead><tr><th>modelo</th><th>tarefa</th>'
    + '<th class="n">macro-F1</th><th class="n">só a ref. acerta</th>'
    + '<th class="n">só este acerta</th><th class="n">p</th>'
    + '<th class="n">p de Holm</th><th>leitura</th></tr></thead><tbody>'
    + linhas + '</tbody></table></div>';
}

/* ---------- F1 por estado e matriz de confusao ---------- */
function secEstados(cs) {
  if (!cs.length) return '';
  const cols = [{k: 'modelo', r: 'modelo'}, {k: 'tarefa', r: 'tarefa'}]
    .concat(EST.map((e, i) => ({k: 'e' + i, r: e.split('.')[0], n: true,
      tit: e + (FORA.has(i) ? ' (fora da média)' : ''), cls: FORA.has(i) ? ' leve' : ''})));
  const ls = cs.map(c => {
    const m = metricas(c.i), l = linhaBase(c);
    EST.forEach((_, i) => {
      const f = m.f1[i];
      l.cel['e' + i] = f.sup ? n2(f.pp) + '<span class="q"> ' + f.sup + '</span>'
        : '<span class="leve">–</span>';
      l.ord['e' + i] = f.sup ? f.pp : null;
    });
    return l;
  });
  const opcoes = cs.map(c => '<option value="' + c.i + '"' + (String(S.matriz) === String(c.i)
    ? ' selected' : '') + '>' + esc(c.curto) + ' · ' + tarefaDe(c) + '</option>').join('');
  const escolhida = cs.find(c => String(c.i) === String(S.matriz)) || cs[0];
  return '<h2>F1 por estado, ponta a ponta</h2><p class="sub">A coluna pequena é o '
    + 'suporte: quantos pares da anotação têm esse estado. Um estado sem suporte não '
    + 'entra na média e aparece vazio, que é diferente de zero. Fecho e indeterminado '
    + 'aparecem esmaecidos por ficarem fora da média.</p>'
    + tabela('est', cols, ls)
    + '<h3>Matriz de confusão <select id="matriz">' + opcoes + '</select></h3>'
    + matriz(escolhida);
}

function matriz(c) {
  const m = metricas(c.i);
  const usados = EST.map((_, i) => i).filter(i =>
    m.conf[i].some(x => x) || m.conf.some(l => l[i]) || m.fn[i] || m.fp[i]);
  if (!usados.length) return '<div class="caixa">Sem pares com estado nesta corrida.</div>';
  const max = Math.max(...usados.map(g => Math.max(...usados.map(p => m.conf[g][p]))), 1);
  const cab = '<tr><th></th>' + usados.map(i => '<th title="' + esc(EST[i]) + '">'
    + EST[i].split('.')[0] + '</th>').join('') + '<th title="pares que o modelo não '
    + 'encontrou: erro do nível 1 que se propaga">não viu</th></tr>';
  const corpo = usados.map(g => '<tr><th title="' + esc(EST[g]) + '">' + EST[g] + '</th>'
    + usados.map(p => {
      const v = m.conf[g][p];
      const a = v ? (0.12 + 0.55 * v / max).toFixed(2) : 0;
      return '<td class="' + (g === p ? 'd' : '') + '" style="background:rgba(42,120,214,'
        + a + ')">' + (v || '') + '</td>';
    }).join('') + '<td class="leve">' + (m.fn[g] || '') + '</td></tr>').join('');
  const extra = usados.some(i => m.fp[i]) ? '<tr><th class="leve">inventados</th>'
    + usados.map(i => '<td class="leve">' + (m.fp[i] || '') + '</td>').join('')
    + '<td></td></tr>' : '';
  return '<div class="rolo"><table class="mat"><thead>' + cab + '</thead><tbody>'
    + corpo + extra + '</tbody></table></div><p class="sub">Linha: o estado da '
    + 'anotação. Coluna: o que o modelo atribuiu. A última coluna é o par que o '
    + 'modelo não encontrou, e a última linha o par que inventou.</p>';
}

/* ---------- relatorio a relatorio ---------- */
function secDetalhe(cs) {
  const blocos = D.relatorios.map((g, ri) => {
    const linhas = [];
    let certos = 0, tem = 0;
    for (const c of cs) {
      const m = metricas(c.i);
      if (!(ri in m.porRel)) continue;
      tem++;
      const k = m.porRel[ri];
      if (k === 'certo') certos++;
      const r = (POR_CORRIDA.get(c.i) || []).find(x => x.rel === ri);
      const ps = r.pares.map(fmtPar).join(' · ')
        || (r.erro ? 'erro: ' + esc(r.nota) : 'nenhum par');
      const marca = k === 'certo' ? '<span class="pass">igual</span>'
        : '<span class="falha">' + (k === 'erro' ? 'erro' : k === 'infra' ? 'falha de infra'
          : (FALHAS.find(f => f[0] === k) || [0, k])[1]) + '</span>';
      linhas.push('<tr><td class="mod">' + esc(c.curto) + '</td><td class="tar">'
        + tarefaDe(c) + '</td><td>' + (r.erro ? '' : 'com=' + (r.com ? 'S' : 'N'))
        + '</td><td>' + marca + '</td><td class="par">' + ps + '</td></tr>');
    }
    if (!tem) return '';
    if (S.soDif && certos === tem) return '';
    const gold = g.pares.map(fmtPar).join(' · ') || 'nenhum par';
    return '<details><summary>#' + g.linha + ' · ' + esc(String(g.cliente).slice(0, 46))
      + ' · <b>' + certos + '/' + tem + '</b> de acordo</summary>'
      + (S.texto ? '<pre class="rel">' + esc(g.texto) + '</pre>' : '')
      + '<div class="rolo"><table><tbody><tr><td class="mod"><b>anotação</b></td>'
      + '<td></td><td>com=' + (g.com ? 'S' : 'N') + '</td><td></td>'
      + '<td class="par">' + gold + '</td></tr>' + linhas.join('')
      + '</tbody></table></div></details>';
  }).join('');
  return '<h2>Relatório a relatório</h2><p class="sub">O ponto de partida de '
    + 'qualquer alteração ao prompt: ver o texto que o modelo viu, ao lado do que '
    + 'devolveu e do que a anotação diz.' + (D.com_texto ? '' : ' Esta página foi gerada da '
    + 'exportação anonimizada, que não tem o texto dos relatórios.') + '</p>'
    + '<div class="barrafiltro" style="position:static;border:0">'
    + '<label class="opc"><input type="checkbox" id="soDif"' + (S.soDif ? ' checked' : '')
    + '> só onde há discordância</label>'
    + (D.com_texto ? '<label class="opc"><input type="checkbox" id="texto"' + (S.texto ? ' checked' : '')
      + '> mostrar o texto do relatório</label>' : '') + '</div>' + blocos;
}

const fmtPar = p => (p[0] || 'NOVO') + ' | ' + TIP[p[1]]
  + ' | ' + (p[2] === null ? 'null' : EST[p[2]].split('.')[0]);

/* ---------- metodologia ---------- */
function secMetodo() {
  const f = [
    ['Nível 1', 'conteúdo comercial, negócio apontado, tipo',
     'proporção de decisões corretas e F1 por categoria, com atenção aos falsos negativos',
     'RF1.1, RF1.2, §3.2.2'],
    ['Nível 2', 'estado da oportunidade, só nos tipos do ciclo',
     'macro-F1 pelos estados cujo critério de verdade está no texto, limiar 0,60',
     'RF1.8'],
    ['Cobertura do tipo', 'pares deixados por tipificar', 'proporção, reportada à parte; não entra no acerto', 'RF1.2'],
    ['Cobertura do pipeline', 'pares do ciclo da anotação, excluídos os indeterminados, que o modelo '
     + 'encontrou no negócio certo e a que atribuiu um estado que não o indeterminado',
     'proporção, limiar 90%; denominador comum a todos os modelos', 'RF1.4'],
    ['Estado atribuído', 'pares do ciclo produzidos pelo modelo que não ficaram em indeterminado',
     'proporção, descritiva; mede a abstenção e lê-se ao lado do macro-F1', 'RF1.4'],
    ['Proveniência', 'versão e resumo do prompt e do esquema em cada corrida',
     'a tarefa identifica-se pelo par prompt/esquema e as corridas de tarefas '
     + 'diferentes não se comparam', 'RF1.6'],
    ['Seleção', 'triagem sobre subconjunto estratificado; a decisão faz-se sobre o conjunto completo sem os ' + D.n_dev + ' relatórios das fases 1 e 2, usados para iterar o prompt',
     'comparação contra o melhor por McNemar com correção de Holm', '§3.2.3'],
    ['Falhas', 'infraestrutura contra leitura da resposta',
     'contadas em separado por serem problemas de natureza distinta', '§3.2.2'],
  ];
  return '<h2>O que esta página mede, e a que requisito responde</h2>'
    + '<p class="sub">Não há nesta página métrica que não esteja fixada na '
    + 'metodologia. A ordem inversa, escolher a métrica depois de ver os resultados, '
    + 'é o que a torna indefensável.</p><div class="rolo"><table><thead><tr>'
    + '<th>o que</th><th>sobre que</th><th>como se mede</th><th>onde está fixado</th>'
    + '</tr></thead><tbody>' + f.map(r => '<tr><td><b>' + r[0] + '</b></td><td>' + r[1]
    + '</td><td>' + r[2] + '</td><td class="tar">' + r[3] + '</td></tr>').join('')
    + '</tbody></table></div>';
}

/* ---------- barra de filtros ---------- */
function barraFiltros(cs) {
  const modelos = [...new Set(D.corridas.filter(c => c.rel > 0
    && (S.tarefa === '*' || tarefaDe(c) === S.tarefa)).map(c => c.modelo))];
  const chips = modelos.map(mo => '<span class="chip' + (S.modelos.has(mo) ? ' on' : '')
    + '" data-mod="' + esc(mo) + '">' + esc(mo.split('/').pop()) + '</span>').join('');
  const op = (id, vals, atual, extra) => '<select id="' + id + '">'
    + (extra ? '<option value="*"' + (atual === '*' ? ' selected' : '') + '>' + extra
      + '</option>' : '')
    + vals.map(v => '<option value="' + v + '"' + (atual === v ? ' selected' : '') + '>'
      + v + '</option>').join('') + '</select>';
  return '<div class="barrafiltro">'
    + '<div class="campo"><label>tarefa (prompt/esquema/entrada)</label>'
    + op('tarefa', TAREFAS, S.tarefa, 'todas') + '</div>'
    + '<div class="campo"><label>relatórios</label>'
    + '<select id="conjunto">' + [['todos','todos'],['dev','desenvolvimento (fases 1 e 2)'],
        ['aval','avaliação (sem as fases 1 e 2)']].map(o => '<option value="' + o[0] + '"'
        + (S.conjunto === o[0] ? ' selected' : '') + '>' + o[1] + '</option>').join('')
    + '</select></div>'
    + '<div class="campo"><label>execução</label>'
    + op('backend', ['local', 'nuvem'], S.backend, 'ambas') + '</div>'
    + '<div class="campo"><label>&nbsp;</label><label class="opc">'
    + '<input type="checkbox" id="ultimas"' + (S.ultimas ? ' checked' : '')
    + '> só a última corrida de cada modelo</label></div>'
    + '<div class="campo" style="flex:1;min-width:260px"><label>modelos ('
    + (S.modelos.size || modelos.length) + ' de ' + modelos.length
    + ', clicar para filtrar) <button class="b" id="limpar" style="padding:1px 6px">'
    + 'todos</button></label><div class="chips">' + chips + '</div></div>'
    + '</div>';
}

const ABAS = [['niveis', 'Níveis 1 e 2'], ['efeito', 'Efeito da versão'],
              ['estados', 'Estados e confusão'], ['operacao', 'Operação'],
              ['detalhe', 'Relatório a relatório'], ['metodo', 'Metodologia']];

function render() {
  const cs = visiveis();
  const n = new Set(cs.flatMap(c => Object.keys(metricas(c.i).porRel))).size;
  let corpo = '';
  if (S.aba === 'niveis') corpo = secNivel1(cs) + secNivel2(cs) + secMcNemar(cs);
  else if (S.aba === 'efeito') corpo = secEfeito();
  else if (S.aba === 'estados') corpo = secEstados(cs);
  else if (S.aba === 'operacao') corpo = secOperacao(cs);
  else if (S.aba === 'detalhe') corpo = secDetalhe(cs);
  else corpo = secMetodo();
  document.getElementById('topo').innerHTML =
    '<p class="sub">' + cs.length + ' corridas · ' + n + ' relatórios anotados '
    + 'comparáveis de ' + D.relatorios.length + ' · gerado em ' + D.gerado + '</p>'
    + barraFiltros(cs)
    + '<div class="tabs">' + ABAS.map(a => '<button class="' + (S.aba === a[0] ? 'on' : '')
      + '" data-aba="' + a[0] + '">' + a[1] + '</button>').join('') + '</div>';
  document.getElementById('corpo').innerHTML = corpo;
  ligar();
}

function ligar() {
  const liga = (id, prop, tipo) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.onchange = () => { S[prop] = tipo === 'b' ? el.checked : el.value; render(); };
  };
  liga('tarefa', 'tarefa'); liga('backend', 'backend'); liga('conjunto', 'conjunto'); liga('ultimas', 'ultimas', 'b');
  liga('base', 'base'); liga('nova', 'nova'); liga('matriz', 'matriz');
  liga('soDif', 'soDif', 'b'); liga('texto', 'texto', 'b');
  document.querySelectorAll('.chip[data-mod]').forEach(el => el.onclick = () => {
    const m = el.dataset.mod;
    S.modelos.has(m) ? S.modelos.delete(m) : S.modelos.add(m);
    render();
  });
  const l = document.getElementById('limpar');
  if (l) l.onclick = () => { S.modelos.clear(); render(); };
  document.querySelectorAll('.tabs button').forEach(el => el.onclick = () => {
    S.aba = el.dataset.aba; render();
  });
}

/* tarefa inicial: a mais recente com corridas, e o par de versoes para o delta */
(function () {
  S.tarefa = TAREFAS.length ? TAREFAS[TAREFAS.length - 1] : '*';
  S.nova = S.tarefa;
  S.base = TAREFAS.length > 1 ? TAREFAS[TAREFAS.length - 2] : S.tarefa;
  render();
})();
"""

PAGINA = """<!doctype html><html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITULO__</title><style>__CSS__</style></head><body>
<button class="b tema" onclick="const r=document.documentElement;
 r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'">tema</button>
<div class="env">
<h1>__TITULO__</h1>
<div id="topo"></div>
<div id="corpo"></div>
</div>
<script>const DADOS=__DADOS__;</script>
<script>__JS__</script>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", action="store_true", help="ler da base de dados, com o texto dos relatórios")
    ap.add_argument("--amostra", type=Path, default=AMOSTRA,
                    help="com --base: ficheiro das fases 1 e 2 (relatórios de desenvolvimento)")
    ap.add_argument("--saida", type=Path, default=SAIDA)
    args = ap.parse_args()

    dados = recolher(args.base, args.amostra)
    pagina = (PAGINA.replace("__CSS__", CSS).replace("__JS__", JS)
              .replace("__TITULO__", "Benchmark do classificador")
              .replace("__DADOS__", json.dumps(dados, ensure_ascii=False, separators=(",", ":"), default=str)))
    args.saida.parent.mkdir(exist_ok=True)
    args.saida.write_text(pagina, encoding="utf-8")
    print(f"escrito {args.saida} · {len(dados['corridas'])} corridas · "
          f"{len(dados['relatorios'])} anotações · {len(pagina) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
