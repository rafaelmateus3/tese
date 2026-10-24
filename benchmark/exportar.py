"""Exporta as corridas do benchmark e a anotação de referência, anonimizadas.

    python exportar.py --amostra AMOSTRA_FASES.json

Escreve anonimo/benchmark_anonimo.json.gz, que é o que metricas.py e
reproduzir.py leem. O ficheiro não tem texto: nem relatórios, nem excertos, nem
nomes de clientes. Cada relatório passa a um número (R0001...) e cada negócio a um
identificador sem o número do cliente, com o mesmo prefixo (NG-E, NG-C, NG-A, NG-X),
porque o emparelhamento só compara identificadores dentro do mesmo relatório.

Do texto guarda-se só o que as métricas precisam dele. Cada par leva, depois do
negócio, do tipo e do estado:
  - se o excerto consta do campo rel do relatório (o «excerto literal» do Quadro 6.1);
  - se o estado é igual ao último estado que o bloco mostra para esse negócio
    (1 igual, 0 diferente, None sem último estado), para o Quadro 6.7;
  - um resumo de 8 caracteres do excerto, que só serve para ver se duas corridas
    deram o mesmo excerto (reprodutibilidade, secção 6.2).
A anotação leva só o segundo.

Ficam de fora as versões da anotação que o Capítulo 6 não usa e o nome da
máquina de cada corrida.
"""

import argparse
import gzip
import json
import re
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "classificador"))

import db  # noqa: E402
from esquema import ESTADOS, TIPOS  # noqa: E402

VERSOES = ("v2", "v3", "e4", "e4s")
SAIDA = AQUI / "anonimo" / "benchmark_anonimo.json.gz"
# As corridas sem estado no bloco (e4s) comparam-se com a anotação da e4: o relatório
# e a resposta certa são os mesmos, só muda a entrada dada ao modelo.
GOLD_DE = {"e4s": "e4"}
_INFRA = re.compile(r"conex|connect|timeout|timed out|refused|unreachable|credit balance|"
                    r"\b5\d\d\b|\b429\b|rate.?limit|overload|unavailable|socket|"
                    r"not found|pull the model|out of memory|cuda", re.I)
_REL = re.compile(r"^  rel\s+(.*?)(?=^  \S|^</report>|\Z)", re.S | re.M)
_PREFIXO = re.compile(r"^(NG-[A-Z]+)")
_ULTIMO = re.compile(r"^\s+(\S+)\s*\|.*\|\s*último estado:\s*(.+?)\s+\(a \d{4}-\d\d-\d\d\)", re.M)


def ultimos(mensagem):
    """{negócio: último estado} do bloco de negócios abertos da mensagem."""
    return {n: e.strip() for n, e in _ULTIMO.findall(mensagem or "")}


def igual_ao_ultimo(ult, nid, estado):
    return None if nid not in ult or not estado else int(ult[nid] == estado)


def resumo(texto):
    import hashlib
    return hashlib.sha256(normal(texto).encode("utf-8")).hexdigest()[:8] if texto else None


def classe_erro(texto):
    """Infraestrutura (a corrida não serve) ou leitura (o modelo não cumpriu o contrato)."""
    return "infra" if _INFRA.search(texto or "") else "leitura"


def normal(texto):
    return re.sub(r"\s+", " ", str(texto or "")).strip().lower()


def rel_de(mensagem):
    m = _REL.search(mensagem or "")
    return normal(m.group(1)) if m else ""


class Identidade:
    """Sem anonimização: para o painel, que fica no computador de quem o gera."""

    def relatorio(self, vistamp):
        return vistamp

    def negocio(self, nid):
        return nid


class Anonimo:
    def __init__(self):
        self.rel, self.neg, self.conta = {}, {}, {}

    def relatorio(self, vistamp):
        return self.rel.setdefault(vistamp, f"R{len(self.rel) + 1:04d}")

    def negocio(self, nid):
        if not nid or nid == "NOVO":
            return nid
        if nid not in self.neg:
            m = _PREFIXO.match(nid)
            p = m.group(1) if m else "NG-?"
            self.conta[p] = self.conta.get(p, 0) + 1
            self.neg[nid] = f"{p}{self.conta[p]:04d}"
        return self.neg[nid]


def recolher(amostra: Path, anonimizar=True, com_texto=False) -> dict:
    """Corridas, anotação e respostas no formato que metricas.Benchmark lê.

    `com_texto` acrescenta o texto da mensagem, o cliente e a mensagem de erro, para o
    painel; nunca se usa com `anonimizar`. `amostra` é o ficheiro dos relatórios das
    fases 1 e 2 (o conjunto de desenvolvimento); sem ele a divisão entre
    desenvolvimento e avaliação sairia errada, pelo que a falta dele é um erro."""
    assert not (anonimizar and com_texto)
    amostra = Path(amostra)
    if not amostra.exists():
        raise FileNotFoundError(f"ficheiro das fases 1 e 2 não encontrado: {amostra}")
    fases = json.loads(amostra.read_text(encoding="utf-8"))
    dev = set(fases.get("fase1", [])) | set(fases.get("fase2", []))

    def puxar(conn):
        with conn.cursor() as cur:
            cur.execute("""SELECT corrida_id, modelo, backend, nota, n_relatorios, n_erros, segundos,
                                  tokens_in, tokens_out, iniciada_em, prompt_version, esquema_version,
                                  entrada_version
                             FROM benchmark_corridas
                            WHERE entrada_version = ANY(%s) AND n_relatorios > 0
                            ORDER BY iniciada_em""", (list(VERSOES),))
            corridas = cur.fetchall()
            ids = [c[0] for c in corridas]
            cur.execute("""SELECT g.vistamp, g.entrada_version, g.comercial, g.pares, e.linha, e.mensagem, e.cliente
                             FROM gold_anotacoes g
                             JOIN benchmark_entradas e
                               ON e.vistamp = g.vistamp AND e.entrada_version = g.entrada_version
                            WHERE g.entrada_version = ANY(%s)
                            ORDER BY e.entrada_version, e.linha""", (list(VERSOES),))
            gold = cur.fetchall()
            cur.execute("""SELECT corrida_id, vistamp, conteudo_comercial, erro
                             FROM benchmark_respostas WHERE corrida_id = ANY(%s)""", (ids,))
            respostas = cur.fetchall()
            cur.execute("""SELECT corrida_id, vistamp, ordem, negocio_id, tipo, estado, excerto
                             FROM benchmark_pares WHERE corrida_id = ANY(%s)
                            ORDER BY corrida_id, vistamp, ordem""", (ids,))
            pares = cur.fetchall()
            cur.execute("""SELECT vistamp, entrada_version, mensagem FROM benchmark_entradas
                            WHERE entrada_version = ANY(%s)""", (list(VERSOES),))
            entradas = cur.fetchall()
        return corridas, gold, respostas, pares, entradas

    L = db.Ligacao()
    try:
        corridas, gold, respostas, pares, entradas = L.executar(puxar)
    finally:
        L.fechar()

    an = Anonimo() if anonimizar else Identidade()
    texto = {(v, ver): rel_de(m) for v, ver, m in entradas}
    ult = {(v, ver): ultimos(m) for v, ver, m in entradas}
    idx = lambda lista, x: lista.index(x) if x in lista else -1  # noqa: E731

    rel_idx, relatorios = {}, []
    for v, ver, com, gp, linha, msg, cliente in gold:
        gp = gp if isinstance(gp, list) else json.loads(gp)
        trio = [(p.get("negocio_id"), p.get("tipo"), p.get("estado")) for p in gp]
        if any(not n for n, _t, _e in trio):
            continue                                   # anotação incompleta: não comparável
        rel_idx[(v, ver)] = len(relatorios)
        u = ult.get((v, ver), {})
        relatorios.append({"r": an.relatorio(v), "versao": ver, "linha": linha, "dev": int(v in dev),
                           "com": bool(com),
                           "pares": [[an.negocio(n), idx(TIPOS, t), idx(ESTADOS, e) if e else None,
                                      igual_ao_ultimo(u, n, e)] for n, t, e in trio]})
        if com_texto:
            relatorios[-1].update(texto=msg or "", cliente=cliente or "")

    ver_de = {c[0]: GOLD_DE.get(c[12], c[12]) for c in corridas}
    entrada_de = {c[0]: c[12] for c in corridas}
    ci_de = {c[0]: i for i, c in enumerate(corridas)}
    do_par = {}
    for cid, v, _o, nid, tipo, estado, excerto in pares:
        if (v, ver_de[cid]) not in rel_idx:
            continue
        t = texto.get((v, entrada_de[cid]), "")
        literal = int(bool(normal(excerto)) and normal(excerto) in t)
        u = ult.get((v, entrada_de[cid]), {})
        do_par.setdefault((cid, v), []).append(
            [an.negocio(nid), idx(TIPOS, tipo), idx(ESTADOS, estado) if estado else None, literal,
             igual_ao_ultimo(u, nid, estado), resumo(excerto)])

    saida_resp = []
    for cid, v, com, erro in respostas:
        chave = (v, ver_de[cid])
        if chave not in rel_idx:
            continue
        saida_resp.append([ci_de[cid], rel_idx[chave], None if com is None else int(bool(com)),
                           classe_erro(erro) if erro else None, do_par.get((cid, v), [])]
                          + ([(erro or "")[:120]] if com_texto else []))

    saida_corr = []
    for i, c in enumerate(corridas):
        cid, modelo, backend, nota, n_rel, n_err, seg, t_in, t_out, quando, prompt, esquema, entrada = c
        saida_corr.append({"i": i, "id": cid, "modelo": modelo, "backend": backend or "",
                           "nota": nota or "", "rel": int(n_rel or 0), "err": int(n_err or 0),
                           "seg": round(float(seg or 0), 1), "t_in": int(t_in or 0), "t_out": int(t_out or 0),
                           "quando": str(quando)[:16], "prompt": prompt, "esquema": esquema, "entrada": entrada})

    return {"gerado": datetime.now().strftime("%Y-%m-%d %H:%M"), "estados": ESTADOS, "tipos": TIPOS,
            "corridas": saida_corr, "relatorios": relatorios, "respostas": saida_resp}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--amostra", required=True, type=Path,
                    help="ficheiro das fases 1 e 2 (relatórios de desenvolvimento)")
    a = ap.parse_args()
    dados = recolher(a.amostra)
    SAIDA.parent.mkdir(exist_ok=True)
    with gzip.open(SAIDA, "wt", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(dados['corridas'])} corridas · {len(dados['relatorios'])} anotações · "
          f"{len(dados['respostas'])} respostas -> {SAIDA}")


if __name__ == "__main__":
    main()
