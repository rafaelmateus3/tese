"""Interface de anotação do conjunto de referência.

    python anotar.py                 abre o browser em http://127.0.0.1:8765
    python anotar.py --versao v1     anotar contra a entrada antiga

Corre só na máquina de quem anota e só aceita ligações locais. Lê e grava na
base de dados, na tabela `gold_anotacoes`, com uma linha de histórico por cada
gravação, pelo que nada se perde por corrigir.

Três regras de desenho, cada uma com a sua razão:

  - O anotador vê a mensagem exacta que o modelo viu, congelada na base de
    dados, e não uma reconstrução dela. Foi a diferença entre as duas que fez
    parecer erros de anotação o que eram defeitos do instrumento.
  - A gravação aplica o mesmo contrato que o esquema impõe ao modelo: conteúdo
    comercial com pelo menos um par, identificador do bloco ou NOVO, tipo
    compatível com o negócio, consumíveis sem estado. A anotação e a resposta
    ficam assim comparáveis por construção.
  - As respostas dos modelos só se mostram depois de a anotação estar gravada,
    e só a pedido. Anotar a olhar para elas ancoraria o gold nos modelos que
    ele serve para avaliar.
"""

import argparse
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "classificador"))

import db                                   # noqa: E402
import hashlib                              # noqa: E402
sys.path.insert(0, str(AQUI.parent / "classificador" / "prompts"))
from marcas import MARCAS                   # noqa: E402
from esquema import ESTADOS, NOVO, TIPOS    # noqa: E402

AMOSTRA = AQUI.parent / "resultados/260916_amostra_fases.json"

BLOCO_NEG = re.compile(r"<negocios_abertos>\n(.*?)\n\s*</negocios_abertos>", re.S)
BLOCO_HIST = re.compile(r"<relatorios_anteriores>\n(.*?)\n\s*</relatorios_anteriores>", re.S)
LINHA_NEG = re.compile(r"^\s+(\S+)\s*\|\s*([^|]+?)\s*\|(.*)$")
CAMPO = re.compile(r"^  (\w+)\s+(.*)$")
DATA_HIST = re.compile(r"^\s+\d{4}-\d{2}-\d{2} \|")

_lock = threading.Lock()
_lig = db.Ligacao()


def _sql(sql, params=(), um=False, escrever=False):
    """Uma consulta, serializada: a interface tem um utilizador só."""
    with _lock:
        def f(c):
            with c.cursor() as cur:
                cur.execute(sql, params)
                out = cur.fetchall() if cur.description else None
            if escrever:
                c.commit()
            return out
        r = _lig.executar(f)
    return (r[0] if r else None) if um else r


def _fases() -> dict[str, str]:
    try:
        a = json.loads(AMOSTRA.read_text(encoding="utf-8"))
    except OSError:
        return {}
    out = {v: "fase 1" for v in a.get("fase1", [])}
    out.update({v: "fase 2" for v in a.get("fase2", [])})
    return out


FASES = _fases()

# Ordem da fila de anotação: aleatória, com semente fixa. Qualquer prefixo da
# fila é assim uma amostra aleatória do conjunto de avaliação, e parar a meio
# não enviesa a métrica para os relatórios mais fáceis ou mais recentes.
SEMENTE = "20260926"


def ordem(vistamp: str) -> int:
    return int(hashlib.md5((SEMENTE + vistamp).encode()).hexdigest()[:8], 16)


def decompor(msg: str) -> dict:
    """Separa a mensagem congelada nas partes que a página mostra."""
    # Um campo pode ter várias linhas (o rel tem parágrafos). A linha que não
    # abre campo continua o anterior; antes só se lia a primeira linha e a
    # página mostrava o relatório truncado (corrigido a 27-Set).
    campos, atual = {}, None
    for linha in msg.split("\n"):
        if linha.startswith("  <") or linha.startswith("</report"):
            break
        m = CAMPO.match(linha)
        if m:
            atual = m.group(1)
            campos[atual] = m.group(2).strip()
        elif atual and linha.strip():
            campos[atual] += "\n" + linha.strip()
    hist = []
    b = BLOCO_HIST.search(msg)
    if b:
        for linha in b.group(1).split("\n"):
            if DATA_HIST.match(linha):
                d, t = linha.strip().split("|", 1)
                hist.append({"data": d.strip(), "texto": t.strip()})
            elif hist and linha.strip():
                hist[-1]["texto"] += "\n" + linha.strip()
    negs = []
    b = BLOCO_NEG.search(msg)
    if b:
        for linha in b.group(1).split("\n"):
            m = LINHA_NEG.match(linha)
            if m:
                negs.append({"id": m.group(1), "tipo": m.group(2).strip(),
                             "resto": m.group(3).strip(" |"), "primeiro": ""})
            elif negs and linha.strip():
                negs[-1]["primeiro"] = (negs[-1]["primeiro"] + " " + linha.strip()).strip()
    return {"campos": campos, "historico": hist, "negocios": negs}


def validar(corpo: dict, negs: list[dict], rel: str):
    """O contrato do esquema, aplicado à anotação. Devolve (erros, avisos)."""
    erros, avisos = [], []
    tipo_de = {n["id"]: n["tipo"] for n in negs}
    pares = corpo.get("pares") or []
    if corpo.get("comercial") is None:
        erros.append("falta decidir se há conteúdo comercial")
    elif corpo["comercial"] and not pares:
        erros.append("conteúdo comercial sem par: não existe; se não há tipo, é um lead NOVO")
    elif not corpo["comercial"] and pares:
        erros.append("sem conteúdo comercial não leva pares")
    vistos, consumo = set(), 0
    norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
    for i, p in enumerate(pares, 1):
        nid, tipo, estado = p.get("negocio_id"), p.get("tipo"), p.get("estado") or None
        if nid != NOVO and nid not in tipo_de:
            erros.append(f"par {i}: o negócio {nid!r} não está no bloco deste relatório")
        if tipo not in TIPOS:
            erros.append(f"par {i}: tipo por escolher")
        elif nid in tipo_de and tipo_de[nid] in TIPOS and tipo_de[nid] != "lead" and tipo != tipo_de[nid]:
            erros.append(f"par {i}: {nid} é de {tipo_de[nid]}, não de {tipo}")
        if tipo == "consumiveis":
            consumo += 1
            if estado:
                erros.append(f"par {i}: consumíveis não levam estado")
        elif tipo in TIPOS and estado not in ESTADOS:
            erros.append(f"par {i}: falta o estado")
        if nid != NOVO:
            if nid in vistos:
                erros.append(f"par {i}: {nid} repetido")
            vistos.add(nid)
        elif tipo == "consumiveis" and tipo in tipo_de.values():
            erros.append(f"par {i}: o bloco já tem a relação de consumíveis deste cliente; usa-a em vez de NOVO")
        elif tipo in tipo_de.values() and tipo != "lead":
            # Regras c06 (27-Set): um segundo negócio do ciclo do mesmo tipo é
            # válido quando o texto fala de outro negócio. Fica o aviso.
            avisos.append(f"par {i}: NOVO de {tipo} com um {tipo} no bloco: confirma que é outro negócio")
        exc = norm(p.get("excerto"))
        if tipo in TIPOS and not exc:
            # O excerto é a evidência que permite adjudicar (27-Set).
            erros.append(f"par {i}: falta o excerto")
        if exc and exc not in norm(rel):
            avisos.append(f"par {i}: o excerto não está literalmente no relatório")
    if consumo > 1:
        erros.append("consumíveis são uma relação: um só par por relatório")
    return erros, avisos


# ---------------------------------------------------------------- pedidos

# Na v3 o bloco depende das anotações anteriores do mesmo cliente. O anotador
# mostra-o calculado a partir do gold actual, e não congelado, para que uma
# correcção num relatório apareça logo nos seguintes. No fim congela-se com a
# mesma função (congelar_v3.py --gravar --do-v3).
_V3 = {"msgs": None}


def mensagem(versao, vistamp):
    if versao == "v3":
        if _V3["msgs"] is None:
            import congelar_v3
            novas, _ = congelar_v3.construir("v3")
            _V3["msgs"] = {v: (m, r["ln"]) for v, (r, m) in novas.items()}
        return _V3["msgs"].get(vistamp)
    r = _sql("SELECT mensagem, linha FROM benchmark_entradas WHERE vistamp = %s AND entrada_version = %s",
             (vistamp, versao), um=True)
    return (r[0], r[1]) if r else None


def api_lista(versao):
    linhas = _sql("""
        SELECT e.vistamp, e.linha, e.cliente, substring(e.mensagem from 'data +([0-9-]+)'),
               g.comercial IS NOT NULL, coalesce(g.duvida, false), g.origem
          FROM benchmark_entradas e
          LEFT JOIN gold_anotacoes g
            ON g.vistamp = e.vistamp AND g.entrada_version = e.entrada_version
         WHERE e.entrada_version = %s
         ORDER BY e.linha NULLS LAST, e.vistamp""", (versao,))
    return [{"vistamp": v, "linha": ln, "cliente": c, "data": d, "anotado": a,
             "duvida": du, "origem": o, "fase": FASES.get(v, ""), "ordem": ordem(v)}
            for v, ln, c, d, a, du, o in linhas]


def api_relatorio(versao, vistamp):
    r = mensagem(versao, vistamp)
    if not r:
        return None
    partes = decompor(r[0])
    g = _sql("SELECT comercial, pares, duvida, nota, origem, atualizado_em "
             "FROM gold_anotacoes WHERE vistamp = %s AND entrada_version = %s",
             (vistamp, versao), um=True)
    gold = None
    if g:
        pares = g[1] if isinstance(g[1], list) else json.loads(g[1])
        gold = {"comercial": g[0], "pares": pares, "duvida": g[2], "nota": g[3] or "",
                "origem": g[4], "quando": str(g[5])[:16]}
    return {"vistamp": vistamp, "linha": r[1], "fase": FASES.get(vistamp, ""),
            "mensagem": r[0], **partes, "gold": gold}


MOTIVO = re.compile(r"\b(C\d+)\s+([^·|\]]+)")


def api_lote(versao):
    """Os relatórios em dúvida ou já revistos na ronda do c06, com o que a vista
    de revisão em lote precisa para decidir sem abrir o anotador."""
    linhas = _sql("""
        SELECT e.vistamp, e.linha, e.cliente, e.mensagem, g.comercial, g.pares,
               g.duvida, coalesce(g.nota, '')
          FROM gold_anotacoes g JOIN benchmark_entradas e
            ON e.vistamp = g.vistamp AND e.entrada_version = g.entrada_version
         WHERE g.entrada_version = %s AND (g.duvida OR g.nota LIKE '%%regras c06%%')
         ORDER BY substring(e.mensagem from 'data +([0-9-]+)'), e.linha""", (versao,))
    out = []
    for v, ln, cli, msg, com, pares, du, nota in linhas:
        viva = mensagem(versao, v)
        partes = decompor(viva[0] if viva else msg)
        cab = nota.split("|")[0] if "regras c06" in nota else ""
        motivos = [{"c": c, "t": t.strip()} for c, t in MOTIVO.findall(cab)]
        out.append({"vistamp": v, "linha": ln, "cliente": cli, **partes,
                    "gold": {"comercial": com, "duvida": du, "nota": nota,
                             "pares": pares if isinstance(pares, list) else json.loads(pares or "[]")},
                    "motivos": motivos})
    return out


def api_gravar(versao, corpo):
    r = mensagem(versao, corpo["vistamp"])
    if not r:
        return {"ok": False, "erros": ["relatório desconhecido"]}
    partes = decompor(r[0])
    erros, avisos = validar(corpo, partes["negocios"], partes["campos"].get("rel", ""))
    if erros:
        return {"ok": False, "erros": erros, "avisos": avisos}
    pares = [{"negocio_id": p["negocio_id"], "tipo": p["tipo"],
              "estado": (p.get("estado") or None) if p["tipo"] != "consumiveis" else None,
              "excerto": (p.get("excerto") or "").strip()} for p in corpo["pares"]]
    args = (corpo["vistamp"], versao, bool(corpo["comercial"]),
            json.dumps(pares, ensure_ascii=False), bool(corpo.get("duvida")),
            (corpo.get("nota") or "").strip(),
            "lote" if corpo.get("origem") == "lote" else "interface")
    # A gravação é automática e dispara a cada alteração: uma gravação igual à
    # que já está na base não escreve nada, para o histórico registar decisões
    # e não cliques.
    atual = _sql("SELECT comercial, pares, duvida, coalesce(nota, '') FROM gold_anotacoes "
                 "WHERE vistamp = %s AND entrada_version = %s", args[:2], um=True)
    if atual:
        ap = atual[1] if isinstance(atual[1], list) else json.loads(atual[1])
        if (atual[0], ap, atual[2], atual[3]) == (args[2], pares, args[4], args[5]):
            return {"ok": True, "avisos": avisos, "igual": True}
    _sql("""INSERT INTO gold_anotacoes (vistamp, entrada_version, comercial, pares,
                   duvida, nota, origem, anotador)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, 'autor')
            ON CONFLICT (vistamp, entrada_version) DO UPDATE SET
                comercial = EXCLUDED.comercial, pares = EXCLUDED.pares,
                duvida = EXCLUDED.duvida, nota = EXCLUDED.nota,
                origem = EXCLUDED.origem, atualizado_em = now()""", args, escrever=True)
    _sql("""INSERT INTO gold_anotacoes_hist (vistamp, entrada_version, comercial,
                   pares, duvida, nota, origem, anotador, segundos)
            VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, 'autor', %s)""",
         args + (corpo.get("segundos"),), escrever=True)
    _V3["msgs"] = None
    return {"ok": True, "avisos": avisos}


def api_modelos(versao, vistamp):
    """A última resposta de cada modelo por tarefa, só depois de haver anotação."""
    if not _sql("SELECT 1 FROM gold_anotacoes WHERE vistamp = %s AND entrada_version = %s",
                (vistamp, versao), um=True):
        return {"bloqueado": True}
    linhas = _sql("""
        SELECT DISTINCT ON (c.modelo, c.prompt_version, c.esquema_version)
               c.corrida_id, c.modelo, c.prompt_version, c.esquema_version,
               r.conteudo_comercial, r.erro
          FROM benchmark_respostas r JOIN benchmark_corridas c USING (corrida_id)
         WHERE r.vistamp = %s AND c.entrada_version = %s
         ORDER BY c.modelo, c.prompt_version, c.esquema_version, c.iniciada_em DESC""",
                  (vistamp, versao))
    ids = [l[0] for l in linhas]
    pares = {}
    if ids:
        for cid, neg, tipo, est, exc in _sql("""
                SELECT corrida_id, negocio_id, tipo, estado, excerto FROM benchmark_pares
                 WHERE vistamp = %s AND corrida_id = ANY(%s) ORDER BY corrida_id, ordem""",
                (vistamp, ids)):
            pares.setdefault(cid, []).append(
                {"negocio_id": neg, "tipo": tipo, "estado": est, "excerto": exc})
    return {"bloqueado": False, "respostas": [
        {"modelo": m.split("/")[-1], "tarefa": f"{p}/{e}", "comercial": com,
         "erro": (err or "")[:100], "pares": pares.get(cid, [])}
        for cid, m, p, e, com, err in linhas]}


class Pedido(BaseHTTPRequestHandler):
    versao = "v3"
    meta = 230

    def log_message(self, *_):
        pass

    def _json(self, obj, codigo=200):
        dados = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                pagina = PAGINA.replace("__CONFIG__", json.dumps({
                    "versao": self.versao, "estados": ESTADOS, "tipos": TIPOS,
                    "novo": NOVO, "meta": self.meta, "marcas": MARCAS},
                    ensure_ascii=False)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(pagina)))
                self.end_headers()
                self.wfile.write(pagina)
            elif u.path == "/api/lista":
                self._json(api_lista(self.versao))
            elif u.path == "/api/relatorio":
                r = api_relatorio(self.versao, q.get("vistamp", ""))
                self._json(r if r else {"erro": "não encontrado"}, 200 if r else 404)
            elif u.path == "/lote":
                pagina = LOTE.replace("__CONFIG__", json.dumps({
                    "versao": self.versao, "estados": ESTADOS, "tipos": TIPOS,
                    "novo": NOVO}, ensure_ascii=False)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(pagina)))
                self.end_headers()
                self.wfile.write(pagina)
            elif u.path == "/api/lote":
                self._json(api_lote(self.versao))
            elif u.path == "/api/modelos":
                self._json(api_modelos(self.versao, q.get("vistamp", "")))
            else:
                self._json({"erro": "caminho desconhecido"}, 404)
        except Exception as e:                                  # noqa: BLE001
            self._json({"erro": str(e)}, 500)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            corpo = json.loads(self.rfile.read(n).decode("utf-8"))
            if urlparse(self.path).path == "/api/gravar":
                self._json(api_gravar(self.versao, corpo))
            else:
                self._json({"erro": "caminho desconhecido"}, 404)
        except Exception as e:                                  # noqa: BLE001
            self._json({"ok": False, "erros": [str(e)]}, 500)


PAGINA = (AQUI / "anotar.html").read_text(encoding="utf-8")
LOTE = (AQUI / "lote.html").read_text(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--versao", default="v3", help="versão da entrada a anotar")
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--sem-browser", action="store_true")
    ap.add_argument("--meta", type=int, default=230,
                    help="relatórios de avaliação a anotar para a decisão da fase 3")
    args = ap.parse_args()
    Pedido.versao = args.versao
    Pedido.meta = args.meta
    srv = ThreadingHTTPServer(("127.0.0.1", args.porta), Pedido)
    url = f"http://127.0.0.1:{args.porta}/"
    print(f"anotação da entrada {args.versao} em {url}  (Ctrl+C para sair)")
    if not args.sem_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _lig.fechar()


if __name__ == "__main__":
    main()
