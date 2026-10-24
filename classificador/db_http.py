"""Acesso à base de dados por HTTPS, para quando o porto 5432 não está aberto.

Muitas redes empresariais bloqueiam portos de base de dados para o exterior. O
serviço expõe o mesmo PostgreSQL num ponto de acesso HTTP, na porta 443, que
nenhuma rede bloqueia por ser a do tráfego web normal.

Este módulo implementa a parte da interface do psycopg2 que o resto do código
usa, para que nada mais precise de saber por que caminho a consulta segue.

Limitação a declarar: cada instrução é a sua própria transação. Onde o caminho
normal agrupa várias escritas num bloco atómico, aqui elas são independentes.
As escritas do sistema são idempotentes, com `ON CONFLICT DO UPDATE`, pelo que
uma corrida interrompida a meio é corrigida pela corrida seguinte, mas a
diferença fica registada.
"""

import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal

# Identificadores de tipo do PostgreSQL que chegam como texto e têm de ser
# convertidos. Os inteiros de oito bytes, como os de `count(*)`, vêm como texto
# por excederem o inteiro seguro do JSON.
DATA = 1082
CARIMBOS = (1114, 1184)
NUMERICOS = (1700, 700, 701)
INTEIROS = (20, 21, 23)


def _converter(valor, tipo):
    if valor is None:
        return None
    if tipo == DATA:
        return date.fromisoformat(valor)
    if tipo in CARIMBOS:
        return datetime.fromisoformat(valor)
    if tipo in NUMERICOS:
        return Decimal(valor)
    if tipo in INTEIROS:
        return int(valor)
    return valor


def _numerar(sql: str, params):
    """Traduz os marcadores do psycopg2 para os numerados do ponto HTTP."""
    if isinstance(params, dict):
        ordem = []

        def trocar(m):
            ordem.append(params[m.group(1)])
            return f"${len(ordem)}"

        return re.sub(r"%\((\w+)\)s", trocar, sql), ordem
    valores = list(params or ())
    saida, i = [], 0
    for parte in sql.split("%s"):
        saida.append(parte)
        if i < len(valores):
            i += 1
            saida.append(f"${i}")
    return "".join(saida), valores


def _serializar(v):
    if isinstance(v, timedelta):
        return f"{v.days} days"
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (list, tuple)):
        return list(v)
    return v


class Cursor:
    def __init__(self, ligacao):
        self._ligacao = ligacao
        self._linhas: list[tuple] = []
        self.description = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        texto, valores = _numerar(sql, params)
        resposta = self._ligacao.pedir(texto, [_serializar(v) for v in valores])
        campos = resposta.get("fields") or []
        self.description = [(c["name"],) + (None,) * 6 for c in campos]
        tipos = [c["dataTypeID"] for c in campos]
        self._linhas = [tuple(_converter(v, t) for v, t in zip(linha, tipos))
                        for linha in resposta.get("rows") or []]
        self.rowcount = resposta.get("rowCount", -1)

    def fetchall(self):
        return self._linhas

    def fetchone(self):
        return self._linhas[0] if self._linhas else None

    def close(self):
        pass


class Ligacao:
    """Substituto de uma ligação psycopg2, sobre o ponto de acesso HTTP."""

    closed = False

    def __init__(self, url: str):
        anfitriao = re.search(r"@([^/]+)/", url).group(1).split(":")[0]
        self._url = f"https://{anfitriao}/sql"
        self._cabecalhos = {
            "Content-Type": "application/json",
            "Neon-Connection-String": url,
            "Neon-Array-Mode": "true",
        }

    def pedir(self, sql: str, params: list) -> dict:
        pedido = urllib.request.Request(
            self._url,
            data=json.dumps({"query": sql, "params": params}).encode(),
            headers=self._cabecalhos)
        try:
            with urllib.request.urlopen(pedido, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            # Sem o corpo da resposta, um 400 não diz qual foi o erro de SQL.
            corpo = e.read().decode("utf-8", "replace")
            try:
                corpo = json.loads(corpo).get("message", corpo)
            except ValueError:
                pass
            raise RuntimeError(f"SQL rejeitado ({e.code}): {corpo[:300]}") from None

    def cursor(self, **_):
        return Cursor(self)

    def commit(self):
        """Cada instrução já foi confirmada quando foi enviada."""

    def rollback(self):
        """Não há transação aberta para desfazer."""

    def close(self):
        self.closed = True


def execute_values(cur, sql, linhas, page_size=200):
    """Equivalente ao utilitário do psycopg2, para inserções em bloco."""
    for i in range(0, len(linhas), page_size):
        bloco = linhas[i:i + page_size]
        marcadores = ", ".join(
            "(" + ", ".join(["%s"] * len(linha)) + ")" for linha in bloco)
        cur.execute(sql.replace("%s", marcadores, 1),
                    [v for linha in bloco for v in linha])
