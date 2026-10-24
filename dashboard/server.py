"""API e serviço estático do dashboard.

    uvicorn server:app --host 0.0.0.0 --port 8000

Cada pedido exige sessão (auth.py). O comercial só vê o que é seu, numa página
sua (/api/pagina), e é ele quem corrige e fecha os seus dias. O gestor vê a
equipa, o pipeline agregado e a página de qualquer comercial, ratifica as
correções e altera os parâmetros; as funções dele devolvem 403 a um comercial.
/api/saude responde sem sessão, para se poder vigiar o serviço.
"""

import sys
import threading
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))

import config  # noqa: E402
import db  # noqa: E402
from esquema import ESTADOS, TIPOS  # noqa: E402

import alertas          # noqa: E402
import auth             # noqa: E402
import avaliacao        # noqa: E402
import base_instalada   # noqa: E402
import fechos           # noqa: E402
import indicadores      # noqa: E402
import parametros       # noqa: E402

ESTATICOS = Path(__file__).parent / "static"

app = FastAPI(title="SAD comercial", docs_url=None, redoc_url=None, openapi_url=None)
ligacao = db.Ligacao()
_trinco = threading.Lock()


def consultar(funcao):
    """Uma ligação partilhada, um pedido de cada vez: chega para uma equipa pequena."""
    with _trinco:
        return ligacao.executar(funcao)


# ------------------------------------------------------------------- sessão

def utilizador(request: Request) -> dict:
    u = consultar(lambda c: auth.quem(c, request.cookies.get(auth.COOKIE)))
    if not u:
        raise HTTPException(401, "sessão expirada")
    return u


def gestor(u: dict = Depends(utilizador)) -> dict:
    if u["papel"] != "gestor":
        raise HTTPException(403, "só o gestor")
    return u


def alvo(u: dict, vendedor: str | None) -> str | None:
    """O comercial só vê o seu; o gestor vê o pedido, ou todos."""
    if u["papel"] == "comercial":
        return u["vendedor"]
    return vendedor or None


_falhas: dict[str, list[float]] = defaultdict(list)


class Entrada(BaseModel):
    login: str
    senha: str


@app.post("/api/entrar")
def entrar(e: Entrada, response: Response):
    agora = time.time()
    _falhas[e.login] = [t for t in _falhas[e.login] if agora - t < 900]
    if len(_falhas[e.login]) >= 5:
        raise HTTPException(429, "demasiadas tentativas; espere 15 minutos")
    token = consultar(lambda c: auth.entrar(c, e.login.strip(), e.senha))
    if not token:
        _falhas[e.login].append(agora)
        raise HTTPException(401, "utilizador ou palavra-passe errados")
    _falhas.pop(e.login, None)
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="strict",
                        secure=auth.COOKIE_SEGURO, max_age=auth.SESSAO_HORAS * 3600)
    return {"ok": True}


@app.post("/api/sair")
def sair(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE)
    if token:
        consultar(lambda c: auth.sair(c, token))
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@app.get("/api/saude")
def saude():
    ciclo = consultar(indicadores.ultimo_ciclo)
    return {"ok": True, "hoje": str(config.hoje()), "ultimo_ciclo": ciclo and {k: ciclo[k] for k in ("inicio", "fim", "ok")}}


# ------------------------------------------------------------------- leitura

@app.get("/api/resumo")
def resumo(u: dict = Depends(utilizador)):
    """O que a moldura da página precisa: quem é, que dia é, quando correu o ciclo."""
    ciclo = consultar(indicadores.ultimo_ciclo)
    if ciclo and u["papel"] != "gestor":
        ciclo = {k: ciclo[k] for k in ("inicio", "fim", "ok")}
    return {
        "eu": u,
        "hoje": str(config.hoje()),
        "vendedores": consultar(indicadores.vendedores) if u["papel"] == "gestor" else [u["vendedor"]],
        "ultimo_ciclo": ciclo,
        "estados": ESTADOS, "tipos": TIPOS,
    }


def _semana_atual() -> date:
    return config.hoje() - timedelta(days=config.hoje().weekday())


@app.get("/api/pagina")
def pagina(vendedor: str | None = None, u: dict = Depends(utilizador)):
    """RF2.1: a página de cada comercial. Tudo o que é dele, numa só chamada:
    o que contactar, o que rever, e a carteira com o seu pipeline."""
    v = alvo(u, vendedor)
    if not v:
        raise HTTPException(400, "escolha um comercial")
    p = consultar(parametros.ler)
    return {
        "vendedor": v,
        "proprio": u["papel"] == "comercial",
        "parametros": {k: p[k] for k in ("dias_negociacao", "dias_mesmo_estado",
                                         "dias_sem_contacto", "dias_base_sem_contacto",
                                         "dias_fecho", "teto_semanal", "teto_atraso",
                                         "dia_notificacao", "anos_renovacao")},
        "revisao_desde": config.REVISAO_DESDE,
        "fechados_recentes": consultar(lambda c: fechos.recentes(c, v)),
        "alertas": consultar(lambda c: alertas.emitidos(c, v)),
        "consumo": consultar(lambda c: indicadores.consumo_risco(c, v)),
        "renovacao": consultar(lambda c: indicadores.renovacao(c, v, p["anos_renovacao"])),
        "taxas": consultar(indicadores.taxas),
        "dias": consultar(lambda c: indicadores.dias_de_revisao(c, v)),
        "estados": consultar(lambda c: indicadores.pipeline(c, v)),
        "negocios": consultar(lambda c: indicadores.carteira(c, v)),
        "saidas": consultar(lambda c: indicadores.saidas(c, v)),
        "proveniencia": {k: indicadores.PROVENIENCIA[k]
                         for k in ("alertas", "carteira", "pipeline", "consumiveis",
                                   "base_instalada", "revisao", "saidas", "ponderado", "renovacao")},
    }


@app.get("/api/negocio")
def negocio(negocio_id: str, u: dict = Depends(utilizador)):
    """Os relatos de um negócio, com o excerto que sustenta cada estado."""
    hist = consultar(lambda c: indicadores.historia(c, negocio_id))
    if u["papel"] == "comercial" and not any(h["vendedor"] == u["vendedor"] for h in hist):
        raise HTTPException(403, "este negócio não passou pelos seus relatórios")
    return {"negocio_id": negocio_id, "relatos": hist}


@app.get("/api/pipeline")
def pipeline(vendedor: str | None = None, area: str | None = None, origem: str | None = None,
             u: dict = Depends(gestor)):
    """Vista agregada da gestão (RF2.1), com a repartição do RF2.2; filtros por área e origem."""
    v = vendedor or None
    return {
        "areas": consultar(indicadores.areas),
        "estados": consultar(lambda c: indicadores.pipeline(c, v, area, origem)),
        "consumiveis": consultar(indicadores.consumiveis),
        "consumiveis_clientes": consultar(indicadores.consumiveis_clientes),
        "esforco": consultar(lambda c: base_instalada.esforco(c, v)),
        "valor": consultar(lambda c: base_instalada.valor(c, v)),
        "saidas": consultar(lambda c: indicadores.saidas(c, v)),
        "proveniencia": {**indicadores.PROVENIENCIA, "segmento": base_instalada.PROVENIENCIA},
    }


@app.get("/api/equipa")
def equipa(u: dict = Depends(gestor)):
    p = consultar(parametros.ler)
    return {"comerciais": consultar(lambda c: indicadores.equipa(c, p["dias_sem_contacto"], _semana_atual())),
            "dias_parado": p["dias_sem_contacto"],
            "teto_semanal": p["teto_semanal"],
            "totais": consultar(indicadores.resumo),
            "saidas": consultar(indicadores.saidas),
            "alertas": consultar(lambda c: alertas.emitidos(c, None)),
            "proveniencia": {k: indicadores.PROVENIENCIA[k] for k in ("equipa", "saidas", "alertas")}}


# ------------------------------------------------------------ revisão do dia

def _lote_do(u: dict, lote_id: str) -> None:
    """Corrigir e fechar o dia cabe a quem escreveu os relatórios. O gestor vê,
    mas a decisão dele é a ratificação, que é outra."""
    if u["papel"] != "comercial" or lote_id.split("|")[0] != u["vendedor"]:
        raise HTTPException(403, "o dia é revisto por quem escreveu os relatórios")


@app.get("/api/lote")
def lote(dia: str, vendedor: str | None = None, u: dict = Depends(utilizador)):
    v = alvo(u, vendedor)
    if not v:
        raise HTTPException(400, "escolha um comercial")
    d = date.fromisoformat(dia)
    if u["papel"] == "comercial":
        lote_id = consultar(lambda c: avaliacao.abrir_lote(c, v, d))
    else:
        lote_id = f"{v}|{d.isoformat()}"     # o gestor só lê: não abre lotes
    return {"lote_id": lote_id,
            "relatorios": consultar(lambda c: avaliacao.relatorios_do_lote(c, lote_id)),
            "fechado": consultar(lambda c: _fechado(c, lote_id)),
            "editavel": u["papel"] == "comercial",
            "motivos": avaliacao.MOTIVOS}


def _fechado(conn, lote_id):
    with conn.cursor() as cur:
        cur.execute("SELECT fechado_em FROM lotes_revisao WHERE lote_id = %s", (lote_id,))
        r = cur.fetchone()
    return bool(r and r[0])


@app.get("/api/negocios-cliente")
def negocios_cliente(cliente_no: int, u: dict = Depends(utilizador)):
    if u["papel"] == "comercial":
        seus = consultar(lambda c: _visitou(c, u["vendedor"], cliente_no))
        if not seus:
            raise HTTPException(403, "cliente sem relatórios seus")
    return {"negocios": consultar(lambda c: avaliacao.negocios_do_cliente(c, cliente_no))}


def _visitou(conn, vendedor, cliente_no) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM classificacoes_llm WHERE vendedor = %s AND cliente_no = %s LIMIT 1",
                    (vendedor, cliente_no))
        return cur.fetchone() is not None

class Correcao(BaseModel):
    par_id: str
    lote_id: str
    motivo: str
    estado_corrigido: str | None = None
    tipo_corrigido: str | None = None
    negocio_corrigido: str | None = None


@app.post("/api/correcao")
def corrigir(c: Correcao, u: dict = Depends(utilizador)):
    _lote_do(u, c.lote_id)
    if c.estado_corrigido and c.estado_corrigido not in ESTADOS:
        raise HTTPException(400, "estado desconhecido")
    if c.tipo_corrigido and c.tipo_corrigido not in TIPOS:
        raise HTTPException(400, "tipo desconhecido")
    if not c.par_id.startswith(tuple(_vistamps_do_lote(c.lote_id))):
        raise HTTPException(403, "este par não é deste dia")
    try:
        consultar(lambda conn: avaliacao.corrigir(
            conn, c.par_id, c.lote_id, u["login"], c.motivo,
            c.estado_corrigido, c.tipo_corrigido, c.negocio_corrigido))
    except (ValueError, LookupError) as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


def _vistamps_do_lote(lote_id: str) -> list[str]:
    rels = consultar(lambda c: avaliacao.relatorios_do_lote(c, lote_id))
    return [r["vistamp"] + "|" for r in rels] or ["\0"]


class NegocioEmFalta(BaseModel):
    vistamp: str
    lote_id: str
    negocio_id: str | None = None
    tipo: str
    estado: str | None = None
    excerto: str


@app.post("/api/negocio-em-falta")
def negocio_em_falta(c: NegocioEmFalta, u: dict = Depends(utilizador)):
    """RF2.9. O ponto de entrada é o relatório, escrito pelo próprio comercial."""
    _lote_do(u, c.lote_id)
    if c.tipo not in TIPOS or (c.estado and c.estado not in ESTADOS):
        raise HTTPException(400, "tipo ou estado desconhecido")
    if (c.vistamp + "|") not in _vistamps_do_lote(c.lote_id):
        raise HTTPException(403, "este relatório não é deste dia")
    try:
        nid = consultar(lambda conn: avaliacao.registar_negocio_em_falta(
            conn, c.vistamp, c.lote_id, u["login"], c.negocio_id, c.tipo, c.estado, c.excerto))
    except (ValueError, LookupError) as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True, "negocio_id": nid}


class AlertaTratado(BaseModel):
    id: int


@app.post("/api/alerta/tratado")
def alerta_tratado(c: AlertaTratado, u: dict = Depends(utilizador)):
    """«Já tratei»: só o próprio comercial, e sem tocar no estado do negócio."""
    if u["papel"] != "comercial":
        raise HTTPException(403, "só o comercial dono do alerta")
    try:
        n = consultar(lambda conn: alertas.tratar(conn, c.id, u["login"], u["vendedor"]))
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None
    return {"ok": True, "tratados": n}


class ConsumoTratado(BaseModel):
    negocio_id: str


@app.post("/api/consumo/tratado")
def consumo_tratado(c: ConsumoTratado, u: dict = Depends(utilizador)):
    """«Já tratei» num cliente de consumíveis: cala-o até à compra seguinte ou 30 dias."""
    if u["papel"] != "comercial":
        raise HTTPException(403, "só o comercial do cliente")
    try:
        consultar(lambda conn: indicadores.tratar_consumo(conn, c.negocio_id, u["login"], u["vendedor"]))
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None
    return {"ok": True}


class RenovacaoTratada(BaseModel):
    cliente_no: int


@app.post("/api/renovacao/tratado")
def renovacao_tratada(c: RenovacaoTratada, u: dict = Depends(utilizador)):
    """«Já tratei» num cliente para renovação do parque: sai da lista durante um ano."""
    if u["papel"] != "comercial":
        raise HTTPException(403, "só o comercial do cliente")
    anos = consultar(parametros.ler)["anos_renovacao"]
    try:
        consultar(lambda conn: indicadores.tratar_renovacao(conn, c.cliente_no, u["login"], u["vendedor"], anos))
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    return {"ok": True}


class FechoNegocio(BaseModel):
    negocio_id: str
    motivo: str | None = None


def _na_carteira(funcao):
    """Ações na carteira: o comercial só nos seus negócios; o gestor em qualquer um."""
    try:
        return consultar(funcao)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except PermissionError as e:
        raise HTTPException(403, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


def _dono(u: dict) -> str | None:
    return u["vendedor"] if u["papel"] == "comercial" else None


@app.post("/api/negocio/fechar")
def negocio_fechar(c: FechoNegocio, u: dict = Depends(utilizador)):
    _na_carteira(lambda conn: fechos.fechar(conn, c.negocio_id, c.motivo or "", u["login"], _dono(u)))
    return {"ok": True}


@app.post("/api/negocio/reabrir")
def negocio_reabrir(c: FechoNegocio, u: dict = Depends(utilizador)):
    _na_carteira(lambda conn: fechos.reabrir(conn, c.negocio_id, u["login"], _dono(u)))
    return {"ok": True}


class Juntar(BaseModel):
    negocio_id: str
    com: str | None = None


@app.post("/api/negocio/juntar")
def negocio_juntar(c: Juntar, u: dict = Depends(utilizador)):
    """Junta um negócio duplicado a outro do mesmo cliente."""
    _na_carteira(lambda conn: fechos.juntar(conn, c.negocio_id, c.com or "", u["login"], _dono(u)))
    return {"ok": True}


@app.post("/api/negocio/separar")
def negocio_separar(c: Juntar, u: dict = Depends(utilizador)):
    _na_carteira(lambda conn: fechos.separar(conn, c.negocio_id, u["login"], _dono(u)))
    return {"ok": True}


class CorrecaoNegocio(BaseModel):
    negocio_id: str
    estado: str | None = None
    tipo: str | None = None


@app.post("/api/negocio/corrigir")
def negocio_corrigir(c: CorrecaoNegocio, u: dict = Depends(utilizador)):
    """Corrige a fase ou o tipo de um negócio da carteira (cai no seu último relatório)."""
    if c.estado and c.estado not in ESTADOS:
        raise HTTPException(400, "estado desconhecido")
    if c.tipo and c.tipo not in TIPOS:
        raise HTTPException(400, "tipo desconhecido")
    _na_carteira(lambda conn: fechos.corrigir(conn, c.negocio_id, u["login"], _dono(u), c.estado, c.tipo))
    return {"ok": True}


class Desfazer(BaseModel):
    par_id: str
    lote_id: str


@app.post("/api/correcao/desfazer")
def correcao_desfazer(c: Desfazer, u: dict = Depends(utilizador)):
    _lote_do(u, c.lote_id)
    if not c.par_id.startswith(tuple(_vistamps_do_lote(c.lote_id))):
        raise HTTPException(403, "este par não é deste dia")
    try:
        consultar(lambda conn: avaliacao.desfazer(conn, c.par_id, c.lote_id))
    except (ValueError, LookupError) as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


class FechoLote(BaseModel):
    lote_id: str


@app.post("/api/lote/fechar")
def fechar(c: FechoLote, u: dict = Depends(utilizador)):
    _lote_do(u, c.lote_id)
    consultar(lambda conn: avaliacao.fechar_lote(conn, c.lote_id))
    return {"ok": True}


# -------------------------------------------------------------------- gestor

@app.get("/api/qualidade")
def qualidade(u: dict = Depends(gestor)):
    """RF2.1, terceira vista: a qualidade da classificação, medida no uso."""
    return {"metricas": consultar(avaliacao.metricas),
            "pendentes": consultar(avaliacao.por_ratificar),
            "totais": consultar(indicadores.resumo),
            "ultimo_ciclo": consultar(indicadores.ultimo_ciclo)}


class Ratificacao(BaseModel):
    par_id: str


@app.post("/api/ratificacao")
def ratificar(c: Ratificacao, u: dict = Depends(gestor)):
    consultar(lambda conn: avaliacao.ratificar(conn, c.par_id, u["login"]))
    return {"ok": True}


@app.get("/api/parametros")
def ver_parametros(u: dict = Depends(gestor)):
    return {"parametros": consultar(parametros.listar)}


class Parametro(BaseModel):
    chave: str
    valor: float


@app.post("/api/parametros")
def alterar_parametro(p: Parametro, u: dict = Depends(gestor)):
    try:
        consultar(lambda c: parametros.alterar(c, p.chave, p.valor, u["login"]))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


# ------------------------------------------------------------------ estático

@app.get("/")
def raiz():
    return FileResponse(ESTATICOS / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
