"""Uma corrida do benchmark: um modelo sobre as entradas congeladas.

As corridas escrevem em tabelas próprias. As de produção guardam uma
classificação só, a corrente, e por isso a segunda corrida apagaria a primeira.

O paralelismo é assimétrico de propósito. Os modelos em nuvem são limitados pela
latência da rede e ganham muito com pedidos concorrentes. Os modelos locais
partilham uma GPU: pedidos concorrentes competem pelo mesmo recurso, não
aceleram nada e falseiam a medição de débito, que é um dos critérios de decisão.
"""

import hashlib
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))

from config import ENTRADA_VERSION, OLLAMA_CONTEXTO  # noqa: E402
from esquema import VERSAO as ESQUEMA_VERSAO  # noqa: E402
from esquema import impressao as esquema_impressao  # noqa: E402
from llm import classificar_mensagem, identificar  # noqa: E402
from prompt import get as prompt_de  # noqa: E402

CONCORRENCIA = {"anthropic": 8, "openai": 8, "ollama": 1}


@dataclass
class Resultado:
    vistamp: str
    conteudo_comercial: bool | None
    pares: list
    erro: str | None
    tokens_in: int | None
    tokens_out: int | None
    segundos: float
    raw: str | None


def _uma(entrada, prompt, modelo, backend) -> Resultado:
    vistamp, mensagem = entrada
    t = time.perf_counter()
    r = classificar_mensagem(mensagem, prompt, modelo, backend)
    return Resultado(vistamp, r["conteudo_comercial"], r["pares"], r["erro"],
                     r["tokens_in"], r["tokens_out"],
                     round(time.perf_counter() - t, 2), r["raw"])


def executar(entradas, prompt, modelo, backend, ao_terminar=None) -> list[Resultado]:
    """Corre o modelo sobre as entradas e devolve um resultado por entrada."""
    n = CONCORRENCIA.get(backend, 1)
    saida: list[Resultado] = []
    if n == 1:
        for e in entradas:
            saida.append(_uma(e, prompt, modelo, backend))
            if ao_terminar:
                ao_terminar(len(saida), len(entradas), saida[-1])
    else:
        with ThreadPoolExecutor(max_workers=n) as pool:
            for r in pool.map(lambda e: _uma(e, prompt, modelo, backend), entradas):
                saida.append(r)
                if ao_terminar:
                    ao_terminar(len(saida), len(entradas), r)
    return saida


SQL_ABRIR = """
INSERT INTO benchmark_corridas (corrida_id, modelo, modelo_id, maquina, backend,
                                prompt_version, prompt_hash, esquema_version,
                                esquema_hash, entrada_version, contexto, nota)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (corrida_id) DO NOTHING
"""

SQL_FECHAR = """
UPDATE benchmark_corridas SET
    n_relatorios = (SELECT count(*) FROM benchmark_respostas r
                     WHERE r.corrida_id = benchmark_corridas.corrida_id),
    n_erros = (SELECT count(*) FROM benchmark_respostas r
                WHERE r.corrida_id = benchmark_corridas.corrida_id
                  AND r.erro IS NOT NULL),
    tokens_in = (SELECT coalesce(sum(tokens_in), 0) FROM benchmark_respostas r
                  WHERE r.corrida_id = benchmark_corridas.corrida_id),
    tokens_out = (SELECT coalesce(sum(tokens_out), 0) FROM benchmark_respostas r
                   WHERE r.corrida_id = benchmark_corridas.corrida_id),
    segundos = (SELECT coalesce(sum(segundos), 0) FROM benchmark_respostas r
                 WHERE r.corrida_id = benchmark_corridas.corrida_id),
    terminada_em = now()
WHERE corrida_id = %s
"""

SQL_RESPOSTA = """
INSERT INTO benchmark_respostas (corrida_id, vistamp, conteudo_comercial,
                                 n_pares, erro, tokens_in, tokens_out,
                                 segundos, raw)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (corrida_id, vistamp) DO UPDATE SET
    conteudo_comercial = EXCLUDED.conteudo_comercial,
    n_pares = EXCLUDED.n_pares, erro = EXCLUDED.erro,
    tokens_in = EXCLUDED.tokens_in, tokens_out = EXCLUDED.tokens_out,
    segundos = EXCLUDED.segundos, raw = EXCLUDED.raw
"""

SQL_PAR = """
INSERT INTO benchmark_pares (corrida_id, vistamp, ordem, negocio_id, tipo,
                             estado, excerto)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (corrida_id, vistamp, ordem) DO UPDATE SET
    negocio_id = EXCLUDED.negocio_id, tipo = EXCLUDED.tipo,
    estado = EXCLUDED.estado, excerto = EXCLUDED.excerto
"""


def impressao(versao: str) -> str:
    """Resumo do texto do prompt, e não só do seu nome.

    A versão é uma etiqueta e as etiquetas podem passar a apontar para outro
    texto. O resumo fixa o que foi mesmo usado, e torna visível uma alteração
    feita ao ficheiro depois da corrida.
    """
    return hashlib.sha256(prompt_de(versao).encode("utf-8")).hexdigest()[:12]


def abrir(conn, corrida_id, modelo, backend, prompt, nota=None):
    """Regista a corrida antes de a primeira resposta chegar.

    Regista o prompt e o esquema em separado, porque são as duas metades da
    tarefa e mudam independentemente uma da outra.

    `nota` marca as corridas que não servem para pontuar. Um ensaio de três
    relatórios é informação útil sobre configuração e débito, mas entrar na
    comparação de modelos com esse denominador seria erro grosseiro, pelo que
    fica assinalado na própria linha.
    """
    try:
        modelo_id = identificar(modelo, backend)
    except (OSError, RuntimeError):
        modelo_id = None
    with conn.cursor() as cur:
        cur.execute(SQL_ABRIR, (corrida_id, modelo, modelo_id, platform.node(),
                                backend, prompt, impressao(prompt),
                                ESQUEMA_VERSAO, esquema_impressao(),
                                ENTRADA_VERSION, OLLAMA_CONTEXTO, nota))
    conn.commit()


def gravar_resposta(conn, corrida_id, r: Resultado):
    """Grava uma resposta assim que ela existe.

    Uma corrida completa demora horas nos modelos locais. Guardar só no fim
    significa perder tudo se a máquina reiniciar, que foi o que aconteceu.
    """
    with conn.cursor() as cur:
        cur.execute(SQL_RESPOSTA, (
            corrida_id, r.vistamp, r.conteudo_comercial, len(r.pares),
            r.erro, r.tokens_in, r.tokens_out, r.segundos, r.raw))
        cur.execute("DELETE FROM benchmark_pares "
                    "WHERE corrida_id = %s AND vistamp = %s",
                    (corrida_id, r.vistamp))
        for ordem, p in enumerate(r.pares, start=1):
            cur.execute(SQL_PAR, (
                corrida_id, r.vistamp, ordem, p.get("negocio_id"),
                p.get("tipo"), p.get("estado"), p.get("excerto")))
    conn.commit()


def fechar(conn, corrida_id, nota=None):
    """Recalcula os totais a partir das respostas gravadas e marca o fim.

    `nota` acrescenta o que só se sabe depois de correr, como os controlos de
    variabilidade que a plataforma acabou por aceitar para aquele modelo.
    """
    with conn.cursor() as cur:
        cur.execute(SQL_FECHAR, (corrida_id,))
        if nota:
            cur.execute("UPDATE benchmark_corridas SET nota = %s "
                        "WHERE corrida_id = %s", (nota, corrida_id))
    conn.commit()


def ja_respondidos(conn, corrida_id) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT vistamp FROM benchmark_respostas WHERE corrida_id = %s",
                    (corrida_id,))
        return {v for (v,) in cur.fetchall()}


def por_terminar(conn, modelo, prompt) -> str | None:
    """A corrida mais recente deste modelo que ficou a meio, se existir."""
    with conn.cursor() as cur:
        cur.execute("""SELECT corrida_id FROM benchmark_corridas
                        WHERE modelo = %s AND prompt_version = %s
                          AND esquema_version = %s AND entrada_version = %s
                          AND terminada_em IS NULL
                        ORDER BY iniciada_em DESC LIMIT 1""",
                    (modelo, prompt, ESQUEMA_VERSAO, ENTRADA_VERSION))
        linha = cur.fetchone()
        return linha[0] if linha else None
