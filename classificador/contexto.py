"""Bloco de negócios abertos tal como se conhecia à data do relatório (v2).

Usado pelo benchmark (congelar_v2) e pela produção (run.py). O último estado e
os negócios abertos por relatório acrescentam-se depois, em bloco.py (v3).

A v1 do bloco lia o registo de negócios construído com o histórico inteiro, e
isso punha na mensagem duas coisas que o sistema em produção nunca teria:

  - a data de fim do negócio, que é o último relatório do episódio e está muitas
    vezes depois do relatório em análise (142 linhas em 375 relatórios);
  - o negócio nascido do próprio relatório, com início na data do relatório e
    sem nenhum relatório anterior (88 casos). Em produção esse negócio ainda não
    existe: é este relatório que o cria, como NOVO.

A v2 reconstrói o registo à data, com a mesma regra que o construiu (a do
script de 30-Ago: um negócio é uma sequência de relatórios do mesmo cliente com
a mesma família no `u_classif`, partida por silêncios de mais de 90 dias), mas
só com os relatórios anteriores ao dia do relatório. O identificador é o do
registo sempre que o início coincide, para que a anotação continue a apontar
para o mesmo negócio.

O estado actual do negócio não entra. No benchmark congelado não há
classificação anterior de onde o tirar sem pôr lá informação do futuro; em
produção entra, porque o classificador corre por ordem de data. É uma das
diferenças entre os dois regimes, e fica declarada.
"""

import re
from collections import defaultdict
from datetime import date, timedelta

ABANDONO = 90   # dias sem sinal que fecham um episódio, como no registo

# A regra do registo: o tipo do negócio vem da família marcada pelo comercial.
TIPO_DE_CLASSIF = {"EQUIPAMENTOS": "equipamento", "SOFTWARE": "equipamento",
                   "SOLUÇÃO": "equipamento", "SERVIÇO": "producao",
                   "PEÇAS": "producao"}

# PEÇAS quer dizer coisas diferentes e a regra não as consegue separar. Numa área
# são peças que produzimos; noutras tanto são peças de reposição, que são
# pós-venda, como peças que produzimos para máquinas dos clientes, que são
# produção. Testou-se a 24-Set separar pela área de negócio: dos dois
# relatórios da amostra que mudariam, um ficava certo e o outro errado. A regra
# fica como estava e a ambiguidade é declarada: é um caso em que só o texto
# decide, que é o que o classificador acrescenta a uma regra sobre um campo.
def _tipo(classif, area):
    return TIPO_DE_CLASSIF.get(str(classif or "").strip().upper())

_GENERICO = re.compile(
    r"^(visita|telefonema|contacto|reuni[aã]o|liga[cç][aã]o|email)"
    r"( comercial| com telefonema| informativ[oa])?( consum[ií]veis)?\.?$", re.I)

FAMILIAS_CONSUMO = {"CONSUMIVEIS", "PEÇAS"}
DOCUMENTOS_VENDA = {"Factura", "Fatura Recibo"}


def _limpo(texto, n=None) -> str:
    """Uma linha, sem o separador de campos do bloco."""
    t = re.sub(r"\s+", " ", str(texto or "")).replace("|", "/").strip()
    if n and len(t) > n:
        t = t[: n - 1].rstrip() + "…"
    return t


class Contexto:
    """Tudo o que é preciso para construir o bloco de qualquer relatório."""

    def __init__(self, visitas, faturas, registo, marcas):
        """
        visitas  DataFrame da extracção de visitas (vistamp, data, no, rel,
                 resumo, u_classif)
        faturas  DataFrame das linhas de fatura
        registo  lista de (negocio_id, cliente_no, tipo, inicio) da tabela
                 `negocios`
        marcas   lista de nomes de marca do parque
        """
        self.sinais = defaultdict(list)          # (no, tipo) -> [(data, texto)]
        for r in visitas.itertuples():
            tipo = _tipo(r.u_classif, r.u_anegocio)
            if not tipo or r.no != r.no:          # NaN
                continue
            texto = str(r.rel or "").strip() or str(r.resumo or "").strip()
            self.sinais[(int(r.no), tipo)].append(
                (r.data.date(), texto, str(r.resumo or "").strip()))
        for k in self.sinais:
            self.sinais[k].sort(key=lambda x: x[0])

        f = faturas[faturas["Familia"].isin(FAMILIAS_CONSUMO)
                    & faturas["Tipo Documento"].isin(DOCUMENTOS_VENDA)]
        f = f.rename(columns={"Data do Documento": "data", "Nº Cliente": "no",
                              "Marca": "marca", "dt1": "sub"})
        self.compras = defaultdict(list)         # no -> [(data, produto)]
        for r in f[["data", "no", "marca", "sub"]].itertuples(index=False):
            if r.no != r.no or r.data != r.data:
                continue
            produto = " ".join(x for x in (_limpo(r.marca), _limpo(r.sub).lower())
                               if x and x.lower() != "nan")
            self.compras[int(r.no)].append((r.data.date(), produto))

        self.ids = {}                            # (no, tipo, inicio) -> id
        self.consumo = {}                        # no -> (id, inicio)
        for nid, no, tipo, inicio in registo:
            if tipo == "consumiveis":
                self.consumo[int(no)] = (nid, inicio)
            else:
                self.ids[(int(no), tipo, inicio)] = nid
        self.sem_registo = 0

        padroes = sorted({m for m in marcas if len(m) >= 3}, key=len, reverse=True)
        self._marca = re.compile(
            r"\b(" + "|".join(re.escape(m) for m in padroes) + r")\b", re.I)
        self._canon = {m.upper(): m for m in padroes}

    def _marcas(self, textos) -> list[str]:
        vistas = []
        for t in textos:
            for m in self._marca.findall(t):
                c = self._canon.get(m.upper(), m.upper())
                if c not in vistas:
                    vistas.append(c)
        return vistas

    def _episodio_vivo(self, no, tipo, quando: date):
        """O episódio deste tipo vivo à data, só com sinais anteriores a ela."""
        antes = [s for s in self.sinais.get((no, tipo), []) if s[0] < quando]
        if not antes:
            return None
        atual = [antes[0]]
        for s in antes[1:]:
            if (s[0] - atual[-1][0]).days > ABANDONO:
                atual = [s]
            else:
                atual.append(s)
        if (quando - atual[-1][0]).days > ABANDONO:
            return None
        return atual

    def linhas(self, no: int, quando: date) -> list[tuple[str, str, str]]:
        """(negocio_id, tipo, texto do bloco) de cada negócio aberto à data."""
        out = []
        for tipo in ("equipamento", "producao"):
            ep = self._episodio_vivo(no, tipo, quando)
            if not ep:
                continue
            inicio = ep[0][0]
            nid = self.ids.get((no, tipo, inicio))
            if nid is None:
                self.sem_registo += 1
                nid = f"NG-S{no}-{inicio:%y%m%d}"
            n = len(ep)
            marcas = self._marcas(s[1] + " " + s[2] for s in ep)
            # O resumo é o assunto que o próprio comercial deu à visita, e é
            # muitas vezes o nome do equipamento ("Exact Plus"). Os que só dizem
            # que houve visita não identificam nada e ficam de fora.
            assuntos = []
            for s in reversed(ep):
                a = _limpo(s[2], 60)
                if a and not _GENERICO.search(a) and a.lower() not in (
                        x.lower() for x in assuntos):
                    assuntos.append(a)
            cab = (f"{nid} | {tipo} | desde {inicio} | "
                   f"{n} relatório{'s' if n > 1 else ''}, último a {ep[-1][0]}"
                   + (f" | marcas: {', '.join(marcas[:4])}" if marcas else "")
                   + (f" | assuntos: {'; '.join(assuntos[:4])}" if assuntos else ""))
            corpo = f'      primeiro relatório: "{_limpo(ep[0][1], 170)}"'
            out.append((nid, tipo, cab + "\n" + corpo))

        if no in self.consumo:
            nid, inicio = self.consumo[no]
            antes = [c for c in self.compras.get(no, []) if c[0] < quando]
            if inicio and inicio < quando and antes:
                ultima = max(c[0] for c in antes)
                conta = defaultdict(int)
                for _d, p in antes:
                    if p:
                        conta[p] += 1
                top = [p for p, _n in sorted(conta.items(), key=lambda x: -x[1])[:4]]
                cab = (f"{nid} | consumiveis | cliente desde {inicio} | "
                       f"última compra a {ultima}"
                       + (f" | compra: {'; '.join(top)}" if top else ""))
                out.append((nid, "consumiveis", cab))
        return out

    def bloco(self, no: int, quando: date) -> tuple[str, list[str]]:
        ls = self.linhas(no, quando)
        if not ls:
            return "", []
        corpo = "\n".join("    " + t for _i, _t, t in ls)
        return (f"  <negocios_abertos>\n{corpo}\n  </negocios_abertos>\n",
                [i for i, _t, _x in ls])


# Relatórios anteriores do mesmo cliente que acompanham cada relatório. Igual ao
# benchmark (benchmark/entradas.py): os três mais recentes com texto.
HISTORICO = 3


def bloco_historico(anteriores) -> str:
    """Os relatórios anteriores do cliente, do mais recente para o mais antigo."""
    if anteriores.empty:
        return ""
    linhas = "\n".join(
        f"    {r.data:%Y-%m-%d} | {str(r.rel).strip()}"
        for r in anteriores.itertuples())
    return f"  <relatorios_anteriores>\n{linhas}\n  </relatorios_anteriores>\n"
