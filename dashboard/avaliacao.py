"""RF1.7 e RF2.9: a avaliação incorporada no uso.

Quem usa o dashboard encontra uma classificação errada e corrige-a ali. O que
entra em análise é o que um humano, a trabalhar, identificou como errado. Não há
fila de validação nem tarefa a acrescer ao trabalho de ninguém.

Há duas decisões humanas, e servem fins diferentes.

A primeira é a **revisão do lote**, feita por quem usa. Obrigar o comercial a
carimbar "está certo" em cada negócio não sobrevive à segunda semana, pelo que a
unidade de confirmação é o lote do dia: abre a lista, corrige o que estiver
errado, fecha a lista. O que não corrigiu fica confirmado por lote. É isto que
resolve o denominador: sem lotes, "não corrigiu" é ambíguo entre "vi e está bem"
e "nunca olhei".

A segunda é a **ratificação**, feita por uma pessoa só. Uma correção só entra no
corpus que alimenta a iteração do prompt depois de ratificada, porque seis
pessoas a corrigir com seis critérios implícitos produzem um corpus tão
inconsistente quanto o conjunto de referência que se está a tentar substituir.

O que a precisão medida por esta via vale: é um **limite superior**, não uma
estimativa centrada. Quem passa os olhos por doze linhas apanha o erro grosseiro
e deixa passar o subtil. É mais uma razão pela qual o conjunto de referência não
pode ser dispensado.
"""

from datetime import date

MOTIVOS = [
    "fronteira entre estados",
    "negócio errado",
    "tipo errado",
    "não havia conteúdo comercial",
    "excerto não sustenta a decisão",
    "outro",
]


def abrir_lote(conn, vendedor: str, dia: date) -> str:
    """Cria ou devolve o lote do dia daquele comercial, com a contagem de pares.

    A contagem só se atualiza enquanto o dia está aberto: depois de fechado é o
    denominador da precisão (metricas) e não muda com reclassificações posteriores."""
    lote_id = f"{vendedor}|{dia.isoformat()}"
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO lotes_revisao (lote_id, vendedor, dia, n_pares)
            SELECT %s, %s, %s, count(*)
              FROM pares_llm p JOIN classificacoes_llm c ON c.vistamp = p.vistamp
             WHERE c.vendedor = %s AND c.data_visita::date = %s
            ON CONFLICT (lote_id) DO UPDATE SET n_pares = EXCLUDED.n_pares
             WHERE lotes_revisao.fechado_em IS NULL
        """, (lote_id, vendedor, dia, vendedor, dia))
    conn.commit()
    return lote_id


def relatorios_do_lote(conn, lote_id: str) -> list[dict]:
    """Os relatórios do dia, cada um com os pares que o sistema leu.

    Mostram-se também os relatórios sem pares: é aí que o comercial vê um
    negócio que o sistema não viu (RF2.9)."""
    vendedor, dia = lote_id.split("|")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.vistamp, c.cliente, c.cliente_no, c.hora_visita AS hora,
                   c.relatorio, c.llm_erro = 1 AS erro,
                   CASE WHEN EXISTS (SELECT 1 FROM parque_equipamentos q
                                      WHERE q.cliente_no = c.cliente_no
                                        AND q.entrada < c.data_visita::date)
                        THEN 'base_instalada' ELSE 'conquista' END AS segmento
              FROM classificacoes_llm c
             WHERE c.vendedor = %s AND c.data_visita::date = %s
             ORDER BY c.hora_visita, c.vistamp
        """, (vendedor, dia))
        rels = _dicts(cur)
        cur.execute("""
            SELECT p.par_id, p.vistamp, p.negocio_id, p.tipo, p.estado, p.excerto,
                   p.origem, a.acao, a.estado_corrigido, a.tipo_corrigido,
                   a.negocio_corrigido, a.motivo, a.ratificado
              FROM pares_llm p
              JOIN classificacoes_llm c ON c.vistamp = p.vistamp
              LEFT JOIN avaliacao_pares a ON a.par_id = p.par_id
             WHERE c.vendedor = %s AND c.data_visita::date = %s
             ORDER BY p.ordem
        """, (vendedor, dia))
        pares = _dicts(cur)
    por = {}
    for p in pares:
        por.setdefault(p["vistamp"], []).append(p)
    for r in rels:
        r["pares"] = por.get(r["vistamp"], [])
        r["candidatos"] = candidatos_identidade(conn, r["vistamp"])
    return rels


CICLO = ("equipamento", "producao", "lead")

# Por onde chega uma correção: a revisão do dia (o lote, antes de fechar) ou a
# carteira (o último relatório de um negócio, em qualquer dia; decisão de 15-Out-2026).
VIAS = ("revisao", "carteira")

# Uma correção substituída pela carteira fica guardada tal como estava.
SQL_ARQUIVAR = """
INSERT INTO avaliacao_pares_hist (par_id, lote_id, vistamp, negocio_id, acao,
       estado_proposto, estado_corrigido, tipo_proposto, tipo_corrigido, negocio_corrigido,
       motivo, corrigido_por, corrigido_em, ratificado, ratificado_por, ratificado_em, via,
       substituida_por)
SELECT par_id, lote_id, vistamp, negocio_id, acao,
       estado_proposto, estado_corrigido, tipo_proposto, tipo_corrigido, negocio_corrigido,
       motivo, corrigido_por, corrigido_em, ratificado, ratificado_por, ratificado_em, via,
       %s
  FROM avaliacao_pares WHERE par_id = %s
"""


def _exigir_dia_aberto(cur, lote_id: str) -> None:
    cur.execute("SELECT fechado_em FROM lotes_revisao WHERE lote_id = %s", (lote_id,))
    lote = cur.fetchone()
    if lote and lote[0]:
        raise ValueError("o dia já está fechado")

SQL_CANDIDATOS = """
SELECT n.negocio_id, n.tipo, k.estado, k.ultimo_toque::text AS ultimo_toque,
       coalesce(k.excerto, n.descricao) AS excerto
  FROM classificacoes_llm c
  JOIN negocios n ON n.cliente_no = c.cliente_no
  LEFT JOIN carteira k ON k.negocio_id = n.negocio_id
 WHERE c.vistamp = %s
   AND n.tipo IN ('equipamento', 'producao', 'lead')
   AND n.fundido_em IS NULL
   AND (n.fechado_em IS NULL OR n.fechado_em >= c.data_visita::date)
   AND coalesce(n.inicio, c.data_visita::date) <= c.data_visita::date
   AND (k.negocio_id IS NOT NULL OR n.negocio_id NOT LIKE 'NG-X%%')
 ORDER BY k.ultimo_toque DESC NULLS LAST, n.negocio_id
"""


def candidatos_identidade(conn, vistamp: str) -> list[dict]:
    """Os negócios do ciclo do cliente abertos na data do relatório: a lista entre a qual o
    comercial escolhe o negócio certo quando o sistema ligou o par ao negócio errado.

    Um NG-X sem pares efetivos (todos os seus pares foram corrigidos para outro) não entra."""
    with conn.cursor() as cur:
        cur.execute(SQL_CANDIDATOS, (vistamp,))
        return _dicts(cur)


def negocios_do_cliente(conn, cliente_no: int) -> list[dict]:
    """Negócios abertos do cliente, para ligar um negócio em falta."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT negocio_id, tipo, estado, ultimo_toque::text AS ultimo_toque, excerto
              FROM carteira WHERE cliente_no = %s AND fechado_em IS NULL
             ORDER BY ultimo_toque DESC""", (cliente_no,))
        return _dicts(cur)


def _dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def corrigir(conn, par_id: str, lote_id: str, por: str, motivo: str,
             estado_corrigido: str | None = None,
             tipo_corrigido: str | None = None,
             negocio_corrigido: str | None = None, via: str = "revisao") -> None:
    """Regista a correção, guardando também o que o modelo tinha proposto.

    As três coisas ficam em colunas separadas, porque uma correção não
    ratificada continua a ser informação, só não é sinal de treino.

    Com o motivo «negócio errado», `negocio_corrigido` diz qual é o negócio certo: um dos
    negócios do ciclo do cliente abertos na data do relatório, ou "NOVO". Um negócio novo
    recebe o id que o modelo lhe daria se o tivesse aberto (NG-X do relatório e da ordem do
    par), para que o bloco dos relatórios seguintes o trate como aberto neste relatório.

    Pela revisão do dia, o dia tem de estar aberto e uma correção ratificada não se
    muda. Pela carteira, a correção nova substitui a anterior e volta a pedir
    ratificação; a anterior fica em avaliacao_pares_hist. A via guardada é a da
    primeira correção do par: diz onde o erro foi encontrado.
    """
    if via not in VIAS:
        raise ValueError(f"via desconhecida: {via!r}")
    if motivo not in MOTIVOS:
        raise ValueError(f"motivo desconhecido: {motivo!r}")
    if motivo != "negócio errado":
        negocio_corrigido = None
    with conn.cursor() as cur:
        cur.execute("SELECT vistamp, negocio_id, estado, tipo, ordem, excerto FROM pares_llm "
                    "WHERE par_id = %s", (par_id,))
        linha = cur.fetchone()
        if linha is None:
            raise LookupError(f"par inexistente: {par_id!r}")
        vistamp, negocio_id, estado, tipo, ordem, excerto = linha
        cur.execute("SELECT ratificado FROM avaliacao_pares WHERE par_id = %s", (par_id,))
        anterior = cur.fetchone()
        if via == "revisao":
            _exigir_dia_aberto(cur, lote_id)
            if anterior and anterior[0]:
                raise ValueError("esta correção já foi ratificada pelo gestor")
        if motivo == "negócio errado" and not negocio_corrigido and (tipo_corrigido or tipo) in CICLO:
            raise ValueError("falta dizer qual é o negócio certo")
        if negocio_corrigido:
            negocio_corrigido = _negocio_certo(cur, vistamp, negocio_id, tipo_corrigido or tipo,
                                               ordem, excerto, negocio_corrigido)
        if via == "carteira" and anterior:
            cur.execute(SQL_ARQUIVAR, (por, par_id))
        cur.execute("""
            INSERT INTO avaliacao_pares (par_id, lote_id, vistamp, negocio_id,
                acao, estado_proposto, estado_corrigido, tipo_proposto,
                tipo_corrigido, negocio_corrigido, motivo, corrigido_por, via)
            VALUES (%s, %s, %s, %s, 'corrigido', %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (par_id) DO UPDATE SET
                estado_corrigido = EXCLUDED.estado_corrigido,
                tipo_corrigido = EXCLUDED.tipo_corrigido,
                negocio_corrigido = EXCLUDED.negocio_corrigido,
                motivo = EXCLUDED.motivo, corrigido_em = now(),
                ratificado = FALSE, ratificado_por = NULL, ratificado_em = NULL
        """, (par_id, lote_id, vistamp, negocio_id, estado, estado_corrigido,
              tipo, tipo_corrigido, negocio_corrigido, motivo, por, via))
    conn.commit()


def _negocio_certo(cur, vistamp, negocio_id, tipo, ordem, excerto, escolhido) -> str:
    """Valida a correção de identidade e devolve o id que fica gravado."""
    if tipo not in CICLO:
        raise ValueError("a correção do negócio é só para equipamento, produção e lead")
    if escolhido == "NOVO":
        if negocio_id.startswith(f"NG-X{vistamp[:10]}-"):
            raise ValueError("o sistema já tinha aberto um negócio novo neste relatório")
        novo = f"NG-X{vistamp[:10]}-{ordem}"          # negocios.id_para_novo(vistamp, ordem)
        cur.execute("""INSERT INTO negocios (negocio_id, cliente_no, cliente, tipo, descricao,
                                             inicio, criado_por)
                       SELECT %s, cliente_no, cliente, %s, %s, data_visita::date, 'comercial'
                         FROM classificacoes_llm WHERE vistamp = %s
                       ON CONFLICT (negocio_id) DO NOTHING""",
                    (novo, tipo, (excerto or "")[:200], vistamp))
        escolhido = novo
    else:
        if escolhido == negocio_id:
            raise ValueError("é o mesmo negócio que o sistema escolheu")
        cur.execute(SQL_CANDIDATOS, (vistamp,))
        if escolhido not in {r[0] for r in cur.fetchall()}:
            raise ValueError("esse negócio não é deste cliente ou não estava aberto nesta data")
    cur.execute("""SELECT 1 FROM pares_efetivos
                    WHERE vistamp = %s AND negocio_id = %s AND par_id <> %s""",
                (vistamp, escolhido, f"{vistamp}|{negocio_id}"))
    if cur.fetchone():
        raise ValueError("esse negócio já tem outro par neste relatório")
    return escolhido


def registar_negocio_em_falta(conn, vistamp: str, lote_id: str, por: str,
                              negocio_id: str | None, tipo: str, estado: str | None,
                              excerto: str) -> str:
    """RF2.9: o comercial marca um negócio que o sistema não identificou.

    É a única forma de observar um falso negativo em produção: um negócio que o
    nível 1 não viu nunca aparece no dashboard, logo nunca seria corrigido, e um
    sistema avaliado só pelas suas correções parece tanto melhor quanto mais
    casos deixa escapar.

    O par entra com origem 'comercial' e passa a contar no pipeline e nos
    alertas; reprocessar o relatório não o apaga. Sem negocio_id, abre-se um
    negócio novo, marcado como criado pelo comercial.
    """
    tipo_ciclo = tipo in ("equipamento", "producao", "lead")
    if tipo_ciclo and not estado:
        raise ValueError("falta o estado")
    if not tipo_ciclo:
        estado = None
    if not (excerto or "").strip():
        raise ValueError("falta a frase do relatório que o mostra")
    with conn.cursor() as cur:
        _exigir_dia_aberto(cur, lote_id)
        cur.execute("SELECT cliente_no, cliente, data_visita::date FROM classificacoes_llm "
                    "WHERE vistamp = %s", (vistamp,))
        linha = cur.fetchone()
        if linha is None:
            raise LookupError("relatório inexistente")
        cliente_no, cliente, dia = linha
        if not negocio_id:
            cur.execute("SELECT count(*) FROM negocios WHERE negocio_id LIKE %s",
                        (f"NG-M{vistamp[:10]}-%",))
            negocio_id = f"NG-M{vistamp[:10]}-{cur.fetchone()[0] + 1}"
            cur.execute("""INSERT INTO negocios (negocio_id, cliente_no, cliente, tipo,
                                                 descricao, inicio, criado_por)
                           VALUES (%s, %s, %s, %s, %s, %s, 'comercial')""",
                        (negocio_id, cliente_no, cliente, tipo, excerto[:200], dia))
        par_id = f"{vistamp}|{negocio_id}"
        cur.execute("""INSERT INTO pares_llm (par_id, vistamp, negocio_id, tipo, estado,
                                              excerto, ordem, origem, prompt_version, modelo)
                       VALUES (%s, %s, %s, %s, %s, %s, 99, 'comercial', 'comercial', %s)
                       ON CONFLICT (par_id) DO NOTHING""",
                    (par_id, vistamp, negocio_id, tipo, estado, excerto, por))
        cur.execute("""
            INSERT INTO avaliacao_pares (par_id, lote_id, vistamp, negocio_id, acao,
                                         estado_corrigido, tipo_corrigido, motivo, corrigido_por)
            VALUES (%s, %s, %s, %s, 'negocio_em_falta', %s, %s,
                    'não havia conteúdo comercial', %s)
            ON CONFLICT (par_id) DO NOTHING
        """, (par_id, lote_id, vistamp, negocio_id, estado, tipo, por))
    conn.commit()
    return negocio_id


def desfazer(conn, par_id: str, lote_id: str) -> None:
    """Desfaz uma correção ou um negócio acrescentado, enquanto o dia não está fechado.

    Uma correção já ratificada não se desfaz aqui: é do gestor. Um negócio novo criado
    pela correção fica em `negocios` sem pares, e por isso fora da carteira."""
    with conn.cursor() as cur:
        _exigir_dia_aberto(cur, lote_id)
        cur.execute("SELECT acao, ratificado FROM avaliacao_pares WHERE par_id = %s", (par_id,))
        linha = cur.fetchone()
        if linha is None:
            raise LookupError("não há correção neste par")
        acao, ratificado = linha
        if ratificado:
            raise ValueError("esta correção já foi ratificada pelo gestor")
        cur.execute("DELETE FROM avaliacao_pares WHERE par_id = %s", (par_id,))
        if acao == "negocio_em_falta":
            cur.execute("DELETE FROM pares_llm WHERE par_id = %s AND origem = 'comercial'", (par_id,))
    conn.commit()


def fechar_lote(conn, lote_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE lotes_revisao SET fechado_em = now() "
                    "WHERE lote_id = %s AND fechado_em IS NULL", (lote_id,))
    conn.commit()


def ratificar(conn, par_id: str, por: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE avaliacao_pares SET ratificado = TRUE, "
                    "ratificado_por = %s, ratificado_em = now() WHERE par_id = %s",
                    (por, par_id))
    conn.commit()


def por_ratificar(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT a.par_id, a.vistamp, a.negocio_id, a.acao, a.estado_proposto,
                   a.estado_corrigido, a.tipo_proposto, a.tipo_corrigido,
                   a.negocio_corrigido, a.motivo, a.corrigido_por, a.corrigido_em,
                   c.cliente, c.relatorio
              FROM avaliacao_pares a
              LEFT JOIN classificacoes_llm c ON c.vistamp = a.vistamp
             WHERE NOT a.ratificado
             ORDER BY a.corrigido_em
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def metricas(conn) -> dict:
    """O que este mecanismo mede, e como se chama ao que ele mede.

    A precisão sai rotulada como limite superior porque o denominador são os
    pares vistos em lotes fechados, e a confirmação por lote é prova mais fraca
    do que a confirmação item a item.

    O numerador tem o mesmo universo do denominador: as correções feitas na revisão
    de dias que estão fechados. As da carteira e as de dias ainda abertos contam-se
    à parte.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT coalesce(sum(n_pares), 0) FROM lotes_revisao
             WHERE fechado_em IS NOT NULL
        """)
        examinados = cur.fetchone()[0]
        cur.execute("""
            SELECT count(*) FILTER (WHERE a.acao = 'corrigido' AND a.via = 'revisao'
                                      AND l.fechado_em IS NOT NULL),
                   count(*) FILTER (WHERE a.acao = 'corrigido' AND a.via = 'carteira'),
                   count(*) FILTER (WHERE a.acao = 'corrigido' AND a.via = 'revisao'
                                      AND l.fechado_em IS NULL),
                   count(*) FILTER (WHERE a.acao = 'negocio_em_falta'),
                   count(*) FILTER (WHERE a.ratificado)
              FROM avaliacao_pares a
              LEFT JOIN lotes_revisao l ON l.lote_id = a.lote_id
        """)
        corrigidos, na_carteira, em_dias_abertos, em_falta, ratificados = cur.fetchone()
        cur.execute("""
            SELECT motivo, count(*) FROM avaliacao_pares
             GROUP BY 1 ORDER BY 2 DESC
        """)
        motivos = [{"motivo": m, "n": n} for m, n in cur.fetchall()]
    return {
        "pares_examinados_em_lotes_fechados": examinados,
        "correcoes": corrigidos,
        "correcoes_carteira": na_carteira,
        "correcoes_dias_abertos": em_dias_abertos,
        "negocios_em_falta": em_falta,
        "correcoes_ratificadas": ratificados,
        "precisao_maxima_no_examinado":
            round((examinados - corrigidos) / examinados * 100, 1) if examinados else None,
        "nota": ("limite superior: o denominador são os pares vistos em lotes "
                 "fechados e a confirmação por lote é prova mais fraca do que a "
                 "confirmação item a item"),
        "motivos": motivos,
    }


def corpus_erro(conn, so_ratificados: bool = True) -> list[dict]:
    """O corpus que alimenta a versão seguinte do prompt.

    O prompt não se automodifica: as correções dizem onde olhar, e a versão nova
    só substitui a de produção se ganhar no conjunto de referência fixo.
    """
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT a.vistamp, a.negocio_id, a.negocio_corrigido, a.estado_proposto,
                   a.estado_corrigido, a.motivo, p.excerto, c.relatorio
              FROM avaliacao_pares a
              LEFT JOIN pares_llm p ON p.par_id = a.par_id
              LEFT JOIN classificacoes_llm c ON c.vistamp = a.vistamp
             WHERE a.acao = 'corrigido' {'AND a.ratificado' if so_ratificados else ''}
             ORDER BY a.corrigido_em
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
