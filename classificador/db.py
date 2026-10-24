"""Escrita do resultado da classificação, e a ligação à base de dados.

Um relatório é uma linha em `classificacoes_llm`; os seus pares são linhas em
`pares_llm`. Reprocessar um relatório substitui os seus pares, para que a
tabela reflita sempre a última corrida e não a soma de todas.

A ligação tem dois caminhos. O normal é PostgreSQL no porto 5432. Quando esse
porto está bloqueado, o que acontece em muitas redes empresariais, passa-se ao
ponto de acesso HTTP do serviço, na porta 443. A escolha é automática: tenta-se
o porto normal e, se ele não responder, muda-se e avisa-se. `DB_MODO` força um
dos dois, com os valores `tcp` ou `http`.
"""

import os
import time

import psycopg2
import psycopg2.extras

import db_http
from config import DB_URL

MODO = os.getenv("DB_MODO", "auto")

SQL_RELATORIO = """
INSERT INTO classificacoes_llm (
    vistamp, data_visita, hora_visita, vendedor, cliente, cliente_no,
    unidade_negocio, classificacao, tipo_contacto, duracao_min,
    resumo, relatorio, conteudo_comercial,
    llm_tokens_in, llm_tokens_out, llm_raw, llm_erro,
    prompt_version, modelo
) VALUES (
    %(vistamp)s, %(data)s, %(hora)s, %(vendedor)s, %(cliente)s, %(cliente_no)s,
    %(unidade)s, %(classificacao)s, %(tipo_contacto)s, %(duracao)s,
    %(resumo)s, %(relatorio)s, %(conteudo_comercial)s,
    %(tokens_in)s, %(tokens_out)s, %(raw)s, %(erro)s,
    %(prompt_version)s, %(modelo)s
)
ON CONFLICT (vistamp) DO UPDATE SET
    conteudo_comercial = EXCLUDED.conteudo_comercial,
    llm_tokens_in      = EXCLUDED.llm_tokens_in,
    llm_tokens_out     = EXCLUDED.llm_tokens_out,
    llm_raw            = EXCLUDED.llm_raw,
    llm_erro           = EXCLUDED.llm_erro,
    prompt_version     = EXCLUDED.prompt_version,
    modelo             = EXCLUDED.modelo,
    cliente_no         = EXCLUDED.cliente_no
"""

SQL_PAR = """
INSERT INTO pares_llm (par_id, vistamp, negocio_id, tipo, estado, excerto,
                       ordem, origem, prompt_version, modelo)
VALUES (%s, %s, %s, %s, %s, %s, %s, 'llm', %s, %s)
ON CONFLICT (par_id) DO UPDATE SET
    tipo = EXCLUDED.tipo, estado = EXCLUDED.estado, excerto = EXCLUDED.excerto,
    ordem = EXCLUDED.ordem, prompt_version = EXCLUDED.prompt_version,
    modelo = EXCLUDED.modelo, criado_em = now()
"""


# A base suspende-se quando fica inactiva e demora alguns segundos a acordar.
# Durante esse arranque a ligação é recusada, pelo que a primeira tentativa de
# uma sessão falha com frequência e não é um erro real.
TENTATIVAS = 4
ESPERA_INICIAL = 2.0


class Ligacao:
    """Ligação que se restabelece sozinha e tolera o arranque a frio.

    Uma corrida com modelos locais passa minutos entre escritas, e o servidor
    fecha ligações inactivas. Reabrir na altura de escrever é mais simples e
    mais fiável do que manter a ligação viva artificialmente.
    """

    def __init__(self):
        self._conn = None
        self._por_http = False

    @property
    def por_http(self) -> bool:
        return self._por_http

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fechar()

    def _abrir(self):
        if self._conn is not None and not self._conn.closed:
            return self._conn
        if MODO == "http" or self._por_http:
            self._conn = db_http.Ligacao(DB_URL)
            return self._conn
        espera = ESPERA_INICIAL
        for tentativa in range(1, TENTATIVAS + 1):
            try:
                self._conn = psycopg2.connect(DB_URL, connect_timeout=15)
                return self._conn
            except psycopg2.OperationalError as e:
                if tentativa < TENTATIVAS:
                    print(f"  base a acordar, nova tentativa em {espera:.0f}s "
                          f"({tentativa}/{TENTATIVAS - 1})")
                    time.sleep(espera)
                    espera *= 2
                    continue
                if MODO != "auto":
                    raise
                # O porto 5432 não responde. O ponto HTTP serve a mesma base.
                print(f"  porto 5432 inacessível ({str(e).splitlines()[0]}).")
                print("  a passar para o acesso por HTTPS.")
                self._por_http = True
                self._conn = db_http.Ligacao(DB_URL)
                return self._conn
        raise AssertionError("inalcançável")

    def executar(self, funcao):
        """Corre `funcao(conn)`, reabrindo a ligação se ela tiver caído."""
        try:
            return funcao(self._abrir())
        except psycopg2.OperationalError:
            self.fechar()
            return funcao(self._abrir())
        except Exception:
            # Uma transação falhada deixa a ligação inutilizável até ao
            # rollback; sem isto, o pedido seguinte falharia também.
            desfazer = getattr(self._conn, "rollback", None)
            if desfazer:
                try:
                    desfazer()
                except Exception:
                    self.fechar()
            raise

    def em_bloco(self, cur, sql, linhas, page_size=200):
        """Inserção em bloco, pelo caminho que a ligação estiver a usar."""
        if isinstance(self._conn, db_http.Ligacao):
            db_http.execute_values(cur, sql, linhas, page_size)
        else:
            psycopg2.extras.execute_values(cur, sql, linhas, page_size=page_size)

    def fechar(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None


def ja_classificados(conn, versao: str) -> set[str]:
    """Relatórios já processados por esta versão do prompt e sem erro."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT vistamp FROM classificacoes_llm "
            "WHERE prompt_version = %s AND llm_erro = 0",
            (versao,),
        )
        return {r[0] for r in cur.fetchall()}


def gravar(conn, relatorio: dict, resultado: dict, pares: list[dict]) -> None:
    """Grava o relatório e substitui os seus pares, numa só transação."""
    with conn.cursor() as cur:
        cur.execute(SQL_RELATORIO, {
            **relatorio,
            "conteudo_comercial": resultado["conteudo_comercial"],
            "tokens_in": resultado["tokens_in"],
            "tokens_out": resultado["tokens_out"],
            "raw": resultado["raw"],
            "erro": 1 if resultado["erro"] else 0,
            "prompt_version": resultado["prompt_version"],
            "modelo": resultado["modelo"],
        })
        cur.execute("DELETE FROM pares_llm WHERE vistamp = %s AND origem = 'llm'",
                    (relatorio["vistamp"],))
        for ordem, p in enumerate(pares, start=1):
            cur.execute(SQL_PAR, (
                f"{relatorio['vistamp']}|{p['negocio_id']}",
                relatorio["vistamp"], p["negocio_id"], p["tipo"], p.get("estado"),
                p["excerto"], ordem, resultado["prompt_version"], resultado["modelo"],
            ))
    conn.commit()
