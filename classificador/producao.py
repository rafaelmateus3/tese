"""Classificação em produção, com a mesma entrada que o benchmark v3.

A mensagem de cada relatório tem as três partes do benchmark:

  1. os campos do relatório, tal como vêm do ERP;
  2. os três relatórios anteriores do cliente (contexto.bloco_historico);
  3. os negócios abertos à data: os do registo (contexto.Contexto), com o
     último estado, e os abertos por relatórios anteriores (bloco.py).

A única diferença é de onde vem o último estado: no benchmark é o gold; aqui
são os pares já gravados, com a correção do comercial quando existe. Por isso
os relatórios correm por ordem de data: cada um vê o que os anteriores
escreveram.
"""

import re
from datetime import date

import pandas as pd

import bloco
import negocios
from contexto import HISTORICO, Contexto, bloco_historico
from config import FATURAS_DESDE
from llm import _mensagem
from prompts.marcas import MARCAS

# O negócio, o tipo e o estado corrigidos pelo comercial valem sobre os do modelo (migração 014:
# negocio_corrigido). Um par corrigido para negócio novo recebe o id que o modelo lhe daria
# (NG-X do relatório e da ordem), pelo que conta como aberto nesse relatório.
SQL_ANTERIORES = """
SELECT c.data_visita::date, coalesce(a.negocio_corrigido, p.negocio_id), p.vistamp,
       coalesce(a.tipo_corrigido, p.tipo), coalesce(a.estado_corrigido, p.estado),
       p.excerto
  FROM pares_llm p
  JOIN classificacoes_llm c ON c.vistamp = p.vistamp
  LEFT JOIN avaliacao_pares a ON a.par_id = p.par_id AND a.acao = 'corrigido'
 WHERE c.cliente_no = %s AND c.data_visita::date < %s
 ORDER BY c.data_visita, p.vistamp, p.ordem
"""

# O registo à data: negócios do ERP e episódios já vistos. Os abertos pelo
# modelo (NG-X) não entram aqui: entram pelo histórico, como no benchmark. Os abertos
# pelos dossiers do PHC (NG-D, 15-Out-2026) também não: o regime de classificação
# avaliado não muda; se os relatórios abrirem o mesmo negócio, o NG-D junta-se a ele.
SQL_REGISTO = """
SELECT negocio_id, cliente_no, tipo, inicio FROM negocios
 WHERE negocio_id NOT LIKE 'NG-X%%' AND negocio_id NOT LIKE 'NG-D%%' ORDER BY negocio_id
"""

DESDE = re.compile(r"\bdesde (\d{4}-\d\d-\d\d)")


def ler_visitas(caminho) -> pd.DataFrame:
    v = pd.read_excel(caminho)
    v = v[v["no"].notna()].copy()
    v["data"] = pd.to_datetime(v["data"])
    for c in ("rel", "resumo", "u_classif", "u_anegocio"):
        v[c] = v[c].fillna("").astype(str)
    return v


def ler_faturas(caminho) -> pd.DataFrame:
    """Linhas de fatura desde FATURAS_DESDE.

    A exportação do Metabase de 14-Out-2026 traz todo o histórico e tirou o «(€)» ao nome
    da coluna do valor; aceitam-se as duas formas."""
    f = pd.read_excel(caminho)
    if "Preço Venda Total F (€)" not in f.columns and "Preço Venda Total F" in f.columns:
        f = f.rename(columns={"Preço Venda Total F": "Preço Venda Total F (€)"})
    f["Data do Documento"] = pd.to_datetime(f["Data do Documento"])
    return f[f["Data do Documento"] >= pd.Timestamp(FATURAS_DESDE)].reset_index(drop=True)


class Entrada:
    """Monta a mensagem de qualquer relatório da extração."""

    def __init__(self, visitas: pd.DataFrame, faturas: pd.DataFrame, registo: list):
        self.visitas = visitas
        self.ctx = Contexto(visitas, faturas, registo, MARCAS)

    def linha(self, r) -> dict:
        """A linha do relatório com os campos como o benchmark os congelou."""
        linha = r._asdict() if hasattr(r, "_asdict") else dict(r)
        linha.pop("Index", None)
        linha["data"] = pd.Timestamp(linha["data"]).date()
        return linha

    def historico(self, linha) -> str:
        v = self.visitas
        ant = v[(v["no"] == linha["no"]) & (v["data"] < pd.Timestamp(linha["data"]))
                & (v["rel"].str.strip() != "")]
        return bloco_historico(ant.sort_values("data", ascending=False).head(HISTORICO))

    def registo(self, linha) -> list[dict]:
        """Negócios do registo vivos à data, no formato do bloco."""
        v2, _ = self.ctx.bloco(int(linha["no"]), linha["data"])
        return bloco.registo(v2)

    def mensagem(self, linha, negs, anteriores) -> str:
        """anteriores: (data, negocio_id, aberto_aqui, tipo, estado, excerto)."""
        hist, abertos = bloco.historico(anteriores, negs)
        b = bloco.montar(negs, hist, abertos, linha["data"])
        return _mensagem(linha, b, self.historico(linha))


def pendentes(visitas: pd.DataFrame, feitos: set, desde: date | None = None) -> pd.DataFrame:
    """Relatórios com texto por classificar, por ordem de data."""
    v = visitas[visitas["rel"].str.strip().ne("")]
    v = v[~v["vistamp"].astype(str).str.strip().isin(feitos)]
    if desde:
        v = v[v["data"] >= pd.Timestamp(desde)]
    return v.sort_values(["data", "hora", "vistamp"])


# --------------------------------------------------------------- base de dados

def ler_registo(conn) -> list:
    with conn.cursor() as cur:
        cur.execute(SQL_REGISTO)
        return cur.fetchall()


def anteriores(conn, cliente_no: int, quando: date) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(SQL_ANTERIORES, (cliente_no, quando))
        return [(d, nid, nid.startswith(f"NG-X{str(v)[:10]}-"), t, e, x)
                for d, nid, v, t, e, x in cur.fetchall()]


def garantir_registo(conn, negs: list[dict], cliente_no: int, cliente: str) -> None:
    """Os negócios do registo que o bloco mostra têm de existir na tabela,
    para que um par possa apontar para eles."""
    for n in negs:
        m = DESDE.search(n["resto"])
        if n["tipo"] in bloco.CICLO:
            negocios.criar(conn, n["id"], cliente_no, cliente, n["tipo"],
                           n["primeiro"] or n["resto"], m.group(1) if m else None)
    conn.commit()


def fundir(conn, negs: list[dict], ants: list[tuple]) -> int:
    """Um negócio aberto pelo modelo que o registo passou a ter é esse negócio.

    No bloco a ligação faz-se ao montar (bloco.destino), relatório a relatório,
    como no benchmark. Aqui só se regista na base de dados (negocios.fundido_em),
    para que a carteira, o pipeline e os alertas não contem o mesmo negócio
    duas vezes. Os pares não mudam. Devolve quantos fundiu agora.
    """
    n = 0
    cit = bloco.citados(ants)
    for d, nid, aberto_aqui, tipo, _e, _x in ants:
        if not aberto_aqui or tipo not in bloco.CICLO:
            continue
        alvo = bloco.destino(nid, tipo, negs, d, cit)
        if alvo and alvo != nid:
            with conn.cursor() as cur:
                cur.execute("UPDATE negocios SET fundido_em = %s "
                            "WHERE negocio_id = %s AND fundido_em IS NULL", (alvo, nid))
                n += cur.rowcount or 0
    conn.commit()
    return n


def resolver_pares(conn, rel: dict, pares: list[dict], abertos: list[tuple]) -> list[dict]:
    """NOVO passa a negócio com id estável; um lead re-tipificado muda de tipo.

    `abertos` são os (id, tipo) do bloco que o modelo viu."""
    tipo_de = dict(abertos)
    out = []
    for ordem, p in enumerate(pares, start=1):
        nid = str(p.get("negocio_id") or "NOVO").strip()
        if nid.upper() == "NOVO":
            # Consumíveis são uma só relação por cliente (regra do c06).
            nid = (f"NG-C{rel['cliente_no']:05d}" if p["tipo"] == "consumiveis"
                   else negocios.id_para_novo(rel["vistamp"], ordem))
            negocios.criar(conn, nid, rel["cliente_no"], rel["cliente"],
                           p["tipo"], p["excerto"], rel["data"])
        elif tipo_de.get(nid) == "lead" and p["tipo"] != "lead":
            with conn.cursor() as cur:
                cur.execute("UPDATE negocios SET tipo = %s WHERE negocio_id = %s "
                            "AND tipo = 'lead'", (p["tipo"], nid))
        out.append({**p, "negocio_id": nid})
    return out
