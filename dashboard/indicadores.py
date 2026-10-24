"""Indicadores das vistas, cada um com a sua proveniência (RF2.6).

Nenhum número aparece no ecrã sem se poder dizer como é calculado, de onde vem,
a que problema de negócio responde e o que não cobre. Na interface, esta
informação vive num botão «i» junto a cada indicador, e não num parágrafo fixo.
Os limiares dos consumíveis são os medidos ao nível do cliente: acima de 1,59
vezes o intervalo típico a relação está em risco, acima de 3,47 está dormente.
"""

from datetime import timedelta

from config import REVISAO_DESDE, hoje

# Fechos declarados fora da classificação (decisão de 15-Out-2026).
FECHO_GANHO = ('comercial_ganho', 'faturado')
FECHO_PERDA = ('comercial_perdido', 'comercial_nao_avancou')

PROVENIENCIA = {
    "pipeline": {
        "formula": "último estado de cada negócio aberto de equipamento, produção e lead, com a correção do comercial quando existe",
        "fonte": "pares relatório-negócio produzidos pelo motor de interpretação e corrigidos no uso",
        "problema": "P3, pipeline imprevisível", "requisito": "RF2.1",
        "limitacao": "estados atribuídos automaticamente; a precisão medida no uso é um limite superior",
    },
    "carteira": {
        "formula": "negócios abertos cujo último contacto foi deste comercial; dias no estado contados desde o primeiro relatório com o estado atual",
        "fonte": "pares relatório-negócio e registo de negócios",
        "problema": "P1, critério de priorização indisponível", "requisito": "RF2.1",
        "limitacao": "o valor é o do dossier do PHC (proposta, proforma ou encomenda) do mesmo cliente e tipo, o mais recente desde 30 dias antes do início do negócio; a ligação é por cliente, tipo e data, não por referência, e pode trocar valores entre dois negócios do mesmo cliente; negócios que o motor não identificou só aparecem se o comercial os acrescentar",
    },
    "alertas": {
        "formula": "à espera de resposta (proposta, negociação ou aprovação sem contacto), encomenda confirmada sem avanço, sem contacto em qualquer estado, e cliente com equipamento sem visita; emitido uma vez, quando o limiar é cruzado",
        "fonte": "carteira, parque de equipamentos e registo de alertas emitidos",
        "problema": "P3, falta de antecipação", "requisito": "RF2.3 a RF2.5",
        "limitacao": "um novo contacto rearma a regra; acima do teto semanal os sinais ficam na lista consultável, sem notificação",
    },
    "consumiveis": {
        "formula": "silêncio atual a dividir pelo intervalo típico entre compras do cliente",
        "fonte": "linhas de fatura do ERP",
        "limiares": "em risco acima de 1,59x, dormente acima de 3,47x",
        "problema": "P4, base instalada não distinguida", "requisito": "RF2.2",
        "limitacao": "exige três compras para haver periodicidade estimável; cobre 54,8% dos clientes e 97,0% do valor; o relato do comercial mostra-se ao lado e não altera o estado",
    },
    "base_instalada": {
        "formula": "cliente com equipamento no parque antes da data do acontecimento",
        "fonte": "parque de equipamentos do ERP",
        "problema": "P4, base instalada não distinguida", "requisito": "RF2.2",
        "limitacao": "data de instalação em falta em 66% do parque; nesses casos vale a data de criação do registo, pelo que o indicador subestima a base instalada",
    },
    "revisao": {
        "formula": "dias com relatórios classificados; um dia fechado confirma o que não foi corrigido",
        "fonte": "lotes de revisão e correções",
        "problema": "P2, conhecimento não capturado", "requisito": "RF1.7, RF2.9",
        "limitacao": "a confirmação por lote é prova mais fraca do que a confirmação item a item",
    },
    "saidas": {
        "formula": "negócios que saíram do pipeline nos últimos 90 dias, por motivo",
        "fonte": "carteira e registo de fechos automáticos",
        "problema": "P1 e P3", "requisito": "RF2.8",
        "limitacao": "ganho e perda declarada leem-se do último estado classificado; o fecho automático é marcado pelo ciclo noturno aos 180 dias sem contacto",
    },
    "ponderado": {
        "formula": "valor de cada negócio aberto vezes a proporção de ganho histórica da sua fase; adjudicados e em produção contam por inteiro",
        "fonte": "Quadro 6.9 do §6.4: negócios ganhos nos 180 dias seguintes à primeira classificação em cada fase, de setembro de 2024 a abril de 2026",
        "problema": "P3, pipeline imprevisível", "requisito": "RF2.1",
        "limitacao": "é o que aconteceu, não uma previsão; subestima o ganho, porque a maior parte dos negócios fica sem desfecho registado em 180 dias e alguns duplicam outros (§6.4); serve para comparar fases e carteiras, não para prometer faturação",
    },
    "renovacao": {
        "formula": "cliente com visita nos últimos dois anos ou compra de consumíveis no último ano, cuja máquina mais recente entrou no parque há pelo menos o limiar de anos, sem negócio de equipamento aberto",
        "fonte": "parque de equipamentos do ERP, relatórios de visita e faturação de consumíveis",
        "limiares": "8 anos por omissão: 90% dos intervalos entre compras de equipamento do mesmo cliente são mais curtos",
        "problema": "P4, base instalada não distinguida", "requisito": "RF2.2",
        "limitacao": "o parque não regista abates, e a data de entrada é a de criação do registo quando falta a de instalação, pelo que a idade é um mínimo; não distingue máquinas principais de acessórios; «Já tratei» cala o cliente durante um ano",
    },
    "equipa": {
        "formula": "por comercial: negócios abertos, valor, parados sem contacto acima do limiar, alertas notificados na semana e dias por rever nos últimos 14",
        "fonte": "carteira, alertas emitidos e lotes de revisão",
        "problema": "P1 e P3", "requisito": "RF2.1",
        "limitacao": "o comercial de um negócio é o do último contacto",
    },
}

# Histórico de estados por negócio, com os negócios fundidos contados como um.
SQL_HISTORICO = """
historico AS (
    SELECT coalesce(x.fundido_em, p.negocio_id) AS nid, c.data_visita::date AS d, p.estado
      FROM pares_efetivos p
      JOIN classificacoes_llm c ON c.vistamp = p.vistamp
      LEFT JOIN negocios x ON x.negocio_id = p.negocio_id
     WHERE c.data_visita IS NOT NULL
    UNION ALL
    SELECT coalesce(x.fundido_em, e.negocio_id), e.data, e.estado
      FROM eventos_dossier e
      LEFT JOIN negocios x ON x.negocio_id = e.negocio_id)
"""

# Desde quando o negócio `k` está no estado atual: o primeiro relatório depois do
# último que tinha outro estado. Exige o CTE `historico`.
SQL_DESDE_ESTADO = """
coalesce((SELECT min(h.d) FROM historico h
           WHERE h.nid = k.negocio_id
             AND h.d > coalesce((SELECT max(h2.d) FROM historico h2
                                  WHERE h2.nid = k.negocio_id
                                    AND h2.estado IS DISTINCT FROM k.estado),
                                DATE '1900-01-01')),
         k.ultimo_toque)
"""

ABERTO = """k.fechado_em IS NULL AND k.tipo <> 'consumiveis'
   AND (k.estado IS NULL OR k.estado NOT IN ('8. Fechado', '9. Perdido / Cancelado'))"""

# Último estado de cada negócio aberto do ciclo, separado por segmento (RF2.2).
SQL_PIPELINE = f"""
SELECT k.estado, k.segmento, count(*) AS negocios, coalesce(sum(k.valor), 0) AS valor
  FROM carteira k
 WHERE {ABERTO} AND k.estado IS NOT NULL
   AND (%s::text IS NULL OR k.vendedor = %s)
   AND (%s::text IS NULL OR k.area = %s)
   AND (%s::text IS NULL OR k.origem = %s)
 GROUP BY 1, 2 ORDER BY 1, 2
"""

# RF2.1: a carteira de negócios abertos, por comercial.
SQL_CARTEIRA = f"""
WITH {SQL_HISTORICO}
SELECT k.negocio_id, k.cliente, k.cliente_no, k.tipo, k.estado, k.segmento, k.valor,
       k.inicio, k.ultimo_toque, %s - k.ultimo_toque AS dias,
       {SQL_DESDE_ESTADO} AS desde_estado, k.relatorios, k.vendedor, k.excerto,
       k.dossier_ref, k.dossier_tipo, k.dossier_data, k.fase_origem, k.area, k.origem
  FROM carteira k
 WHERE {ABERTO}
   AND (%s::text IS NULL OR k.vendedor = %s)
 ORDER BY k.estado DESC NULLS LAST, k.valor DESC NULLS LAST, k.ultimo_toque
"""

SQL_CONSUMIVEIS = """
SELECT estado_relacao, count(*) AS clientes, coalesce(sum(valor), 0) AS valor
  FROM negocios WHERE tipo = 'consumiveis' AND estado_relacao IS NOT NULL
 GROUP BY 1 ORDER BY 1
"""

# Clientes cuja relação de fornecimento está em risco ou dormente, com o último
# relato do comercial sobre consumíveis. O estado vem da facturação e o relato
# não o altera: uma relação de fornecimento não se ganha nem se perde, deixa de
# estar activa e volta a estar com a compra seguinte. O que o relato acrescenta
# é o porquê, quando o relatório o declara ("passou a comprar à concorrência").
SQL_CONSUMIVEIS_CLIENTES = """
SELECT n.negocio_id,
       coalesce(n.cliente,
                (SELECT max(k.cliente) FROM classificacoes_llm k WHERE k.cliente_no = n.cliente_no))
           AS cliente,
       n.estado_relacao, coalesce(n.valor, 0) AS valor,
       u.data, u.excerto
  FROM negocios n
  LEFT JOIN LATERAL (
        SELECT c.data_visita::date AS data, p.excerto
          FROM pares_llm p JOIN classificacoes_llm c ON c.vistamp = p.vistamp
         WHERE p.negocio_id = n.negocio_id
         ORDER BY c.data_visita DESC
         LIMIT 1) u ON true
 WHERE n.tipo = 'consumiveis'
   AND (n.estado_relacao LIKE '2.%%' OR n.estado_relacao LIKE '3.%%')
 ORDER BY n.valor DESC NULLS LAST
 LIMIT 40
"""

SQL_RESUMO = """
SELECT (SELECT count(*) FROM classificacoes_llm) AS relatorios,
       (SELECT count(*) FROM pares_llm) AS pares,
       (SELECT count(*) FROM classificacoes_llm WHERE conteudo_comercial IS FALSE) AS sem_conteudo,
       (SELECT count(*) FROM classificacoes_llm WHERE llm_erro = 1) AS erros,
       (SELECT count(*) FROM carteira k WHERE k.fechado_em IS NULL AND k.tipo <> 'consumiveis'
           AND (k.estado IS NULL OR k.estado NOT IN ('8. Fechado', '9. Perdido / Cancelado'))) AS negocios_abertos
"""

# Os relatos de um negócio, do mais recente para o mais antigo: é a memória do
# negócio (P2) e o sítio onde cada estado mostra o excerto que o sustenta (RF1.3).
# Os relatos do negócio e, com origem «dossier», os dossiers do PHC que o fizeram mexer
# (fase, contacto, comercial), com a razão declarada no lugar do excerto.
SQL_HISTORIA = """
SELECT * FROM (
    SELECT c.data_visita::date AS data, c.vendedor, c.vistamp, p.tipo, p.estado, p.excerto,
           p.origem, p.corrigido, p.criado_em AS ordem
      FROM pares_efetivos p
      JOIN classificacoes_llm c ON c.vistamp = p.vistamp
      LEFT JOIN negocios x ON x.negocio_id = p.negocio_id
     WHERE coalesce(x.fundido_em, p.negocio_id) = %(n)s
    UNION ALL
    SELECT e.data, e.vendedor, NULL, n.tipo, e.estado, e.razao, 'dossier', FALSE, e.criado_em
      FROM eventos_dossier e
      JOIN negocios n ON n.negocio_id = e.negocio_id
     WHERE coalesce(n.fundido_em, e.negocio_id) = %(n)s
) h
 ORDER BY data DESC, ordem DESC
 LIMIT 50
"""

SQL_SAIDAS = """
SELECT 'automatico' AS motivo, count(*), coalesce(sum(k.valor), 0)
  FROM negocios_fechados_auto f JOIN carteira k ON k.negocio_id = f.negocio_id
 WHERE f.fechado_em >= %(desde)s AND (%(v)s::text IS NULL OR k.vendedor = %(v)s)
UNION ALL
SELECT CASE WHEN k.fecho_motivo IN ('comercial_ganho', 'faturado')
              OR (k.fecho_motivo IS NULL AND k.estado = '8. Fechado') THEN 'ganho'
            ELSE 'perdido' END, count(*),
       coalesce(sum(k.valor), 0)
  FROM carteira k
 WHERE ((k.fecho_motivo IN ('comercial_ganho', 'faturado', 'comercial_perdido', 'comercial_nao_avancou')
         AND k.fechado_em >= %(desde)s)
        OR (k.fecho_motivo IS NULL AND k.estado IN ('8. Fechado', '9. Perdido / Cancelado')
            AND k.ultimo_toque >= %(desde)s))
   AND (%(v)s::text IS NULL OR k.vendedor = %(v)s)
 GROUP BY 1
"""


# Proposta 1 da SLR (15-Out-2026): o histórico de cada fase, do §6.4.
SQL_TAXAS = "SELECT estado, ganho, negocios FROM taxa_ganho_fase"

# As fases que o §6.4 já conta como ganho: no valor ponderado entram por inteiro.
FASES_GANHAS = ('6. Encomenda Confirmada', '7. Em Produção / Entrega')

# Proposta 3 da SLR (15-Out-2026): clientes ativos com o parque por renovar.
SQL_RENOVACAO = f"""
WITH p AS (
    SELECT cliente_no, max(entrada) AS ultima_entrada, count(*) AS maquinas,
           (array_agg(marca ORDER BY entrada DESC))[1] AS marca
      FROM parque_equipamentos GROUP BY 1
), u AS (
    SELECT DISTINCT ON (cliente_no) cliente_no, data_visita::date AS ultima_visita, vendedor,
           cliente, left(coalesce(nullif(resumo, ''), relatorio), 200) AS excerto
      FROM classificacoes_llm
     WHERE cliente_no IS NOT NULL AND data_visita IS NOT NULL
     ORDER BY cliente_no, data_visita DESC
), c AS (
    SELECT cliente_no, max(ultima_compra) AS ultima_compra, coalesce(sum(valor_12m), 0) AS valor_12m
      FROM negocios WHERE tipo = 'consumiveis' GROUP BY 1
)
SELECT p.cliente_no, u.cliente, u.vendedor, p.ultima_entrada, p.maquinas, p.marca,
       u.ultima_visita, u.excerto, coalesce(c.valor_12m, 0) AS valor_12m, c.ultima_compra
  FROM p JOIN u USING (cliente_no) LEFT JOIN c USING (cliente_no)
 WHERE p.ultima_entrada <= %(hoje)s - make_interval(years => %(anos)s)
   AND (u.ultima_visita >= %(hoje)s - 730 OR c.ultima_compra >= %(hoje)s - 365)
   AND NOT EXISTS (SELECT 1 FROM carteira k
                    WHERE k.cliente_no = p.cliente_no AND k.tipo = 'equipamento' AND {ABERTO})
   AND NOT EXISTS (SELECT 1 FROM renovacao_tratada t
                    WHERE t.cliente_no = p.cliente_no AND t.tratado_em >= %(hoje)s - 365)
   AND (%(v)s::text IS NULL OR u.vendedor = %(v)s)
 ORDER BY valor_12m DESC, p.ultima_entrada
"""

# A data de entrada do registo da migração do ERP: as máquinas com ela já lá estavam.
DATA_MIGRACAO = "2003-11-03"


def _linhas(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def pipeline(conn, vendedor: str | None = None, area: str | None = None,
             origem: str | None = None) -> list[dict]:
    """Uma linha por estado, com negócios e valor em cada segmento; filtros por área e origem."""
    with conn.cursor() as cur:
        cur.execute(SQL_PIPELINE, (vendedor, vendedor, area or None, area or None, origem or None, origem or None))
        linhas = cur.fetchall()
    out: dict[str, dict] = {}
    for e, seg, n, v in linhas:
        d = out.setdefault(e, {"estado": e, "negocios": 0, "valor": 0.0,
                               "base_instalada": 0, "conquista": 0,
                               "valor_base_instalada": 0.0, "valor_conquista": 0.0})
        d["negocios"] += n
        d["valor"] += float(v)
        d[seg] += n
        d["valor_" + seg] += float(v)
    tx = taxas(conn)
    for d in out.values():
        if d["estado"] in FASES_GANHAS:
            d["taxa"], d["valor_ponderado"] = 1.0, d["valor"]
        elif d["estado"] in tx:
            d["taxa"] = tx[d["estado"]]["ganho"]
            d["valor_ponderado"] = round(d["valor"] * d["taxa"], 2)
        else:
            d["taxa"], d["valor_ponderado"] = None, 0.0
    return sorted(out.values(), key=lambda d: int(d["estado"].split(".")[0]))


def taxas(conn) -> dict:
    """A proporção de ganho histórica de cada fase (Quadro 6.9). Sem a tabela, vazio."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('taxa_ganho_fase') IS NOT NULL")
        if not cur.fetchone()[0]:
            return {}
        cur.execute(SQL_TAXAS)
        return {e: {"ganho": float(g), "negocios": n} for e, g, n in cur.fetchall()}


def renovacao(conn, vendedor: str | None, anos: int) -> list[dict]:
    """Clientes ativos com a máquina mais recente há `anos` ou mais e sem negócio de
    equipamento aberto, os de maior compra de consumíveis primeiro."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('renovacao_tratada') IS NOT NULL")
        if not cur.fetchone()[0]:
            return []
        cur.execute(SQL_RENOVACAO, {"hoje": hoje(), "anos": anos, "v": vendedor})
        out = _linhas(cur)
    h = hoje()
    for c in out:
        c["antes_de_2004"] = str(c["ultima_entrada"]) == DATA_MIGRACAO
        c["anos"] = int((h - c["ultima_entrada"]).days // 365.25)
        c["valor_12m"] = float(c["valor_12m"] or 0)
        for k in ("ultima_entrada", "ultima_visita", "ultima_compra"):
            c[k] = str(c[k]) if c[k] else None
    return out


def tratar_renovacao(conn, cliente_no: int, por: str, vendedor: str, anos: int) -> None:
    """«Já tratei» num cliente para renovação: sai da lista durante um ano. Só o comercial dele."""
    if not any(c["cliente_no"] == cliente_no for c in renovacao(conn, vendedor, anos)):
        raise LookupError("cliente fora da sua lista de renovação")
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO renovacao_tratada (cliente_no, tratado_por) VALUES (%s, %s)
                       ON CONFLICT (cliente_no) DO UPDATE SET tratado_em = now(),
                           tratado_por = EXCLUDED.tratado_por""", (cliente_no, por))
    conn.commit()


def carteira(conn, vendedor: str | None = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(SQL_CARTEIRA, (hoje(), vendedor, vendedor))
        out = _linhas(cur)
    h = hoje()
    for c in out:
        c["valor"] = float(c["valor"] or 0)
        c["inicio"] = str(c["inicio"]) if c["inicio"] else None
        c["dias_no_estado"] = (h - c["desde_estado"]).days if c["desde_estado"] else None
        c["desde_estado"] = str(c["desde_estado"]) if c["desde_estado"] else None
        c["ultimo_toque"] = str(c["ultimo_toque"])
        c["dossier_data"] = str(c["dossier_data"]) if c["dossier_data"] else None
    return out


def historia(conn, negocio_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(SQL_HISTORIA, {"n": negocio_id})
        out = _linhas(cur)
    for r in out:
        r["data"] = str(r["data"])
        r.pop("ordem", None)
    return out


def consumiveis(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(SQL_CONSUMIVEIS)
        return [{"estado": e, "clientes": n, "valor": float(v)}
                for e, n, v in cur.fetchall()]


def consumiveis_clientes(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(SQL_CONSUMIVEIS_CLIENTES)
        return [{"negocio_id": i, "cliente": c, "estado": e, "valor": float(v),
                 "data": str(d) if d else None, "excerto": x}
                for i, c, e, v, d, x in cur.fetchall()]


def saidas(conn, vendedor: str | None = None, dias: int = 90) -> dict:
    """RF2.8: o que saiu do pipeline, separando o fecho por abandono da perda declarada."""
    with conn.cursor() as cur:
        cur.execute(SQL_SAIDAS, {"desde": hoje() - timedelta(days=dias), "v": vendedor})
        linhas = cur.fetchall()
    out = {m: {"negocios": 0, "valor": 0.0} for m in ("ganho", "perdido", "automatico")}
    for m, n, v in linhas:
        out[m] = {"negocios": n, "valor": float(v)}
    out["dias"] = dias
    return out


def resumo(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(SQL_RESUMO)
        return _linhas(cur)[0]


def ultimo_ciclo(conn) -> dict | None:
    """Quando os dados foram atualizados pela última vez (RF2.7)."""
    with conn.cursor() as cur:
        cur.execute("SELECT inicio, fim, ok, relatorios, pares, erros, fechados, alertas, "
                    "visitas, mensagem FROM ciclos ORDER BY id DESC LIMIT 1")
        linhas = _linhas(cur)
    if not linhas:
        return None
    c = linhas[0]
    c["inicio"], c["fim"] = str(c["inicio"])[:16], str(c["fim"] or "")[:16]
    return c


def vendedores(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT vendedor FROM classificacoes_llm "
                    "WHERE vendedor IS NOT NULL ORDER BY 1")
        return [v for (v,) in cur.fetchall()]


def dias_de_revisao(conn, vendedor: str, limite: int = 30) -> list[dict]:
    """Os dias com relatórios do comercial, com o que o sistema leu e se o dia
    está fechado. Os por fechar vêm primeiro no ecrã: é o trabalho pendente.

    Só a partir do arranque do uso (REVISAO_DESDE): pedir ao comercial que reveja
    meses de histórico no primeiro dia tornava a revisão impraticável. O histórico
    corrige-se na carteira, negócio a negócio."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.data_visita::date AS dia, count(DISTINCT c.vistamp) AS relatorios,
                   count(p.par_id) AS pares,
                   bool_or(l.fechado_em IS NOT NULL) AS fechado
              FROM classificacoes_llm c
              LEFT JOIN pares_llm p ON p.vistamp = c.vistamp
              LEFT JOIN lotes_revisao l ON l.vendedor = c.vendedor AND l.dia = c.data_visita::date
             WHERE c.vendedor = %s AND c.data_visita IS NOT NULL
               AND c.data_visita::date <= %s AND c.data_visita::date >= %s::date
             GROUP BY 1 ORDER BY 1 DESC LIMIT %s""", (vendedor, hoje(), REVISAO_DESDE, limite))
        out = _linhas(cur)
    for d in out:
        d["dia"] = str(d["dia"])
        d["fechado"] = bool(d["fechado"])
    return out


# Consumíveis em risco ou dormentes dos clientes do comercial (o último a
# falar com o cliente sobre consumíveis).
# «Já tratei» num cliente de consumíveis cala-o até haver uma compra nova ou passarem
# 30 dias, o que vier primeiro.
SQL_CONSUMO_RISCO = """
SELECT k.negocio_id, k.cliente, k.estado_relacao AS estado,
       coalesce(n.valor_12m, 0) AS valor, n.ultima_compra, n.intervalo_compra,
       k.ultimo_toque, k.excerto, k.vendedor
  FROM carteira k JOIN negocios n ON n.negocio_id = k.negocio_id
 WHERE k.tipo = 'consumiveis' AND k.estado_relacao IN ('2. Em risco', '3. Dormente')
   AND (%s::text IS NULL OR k.vendedor = %s)
   AND NOT EXISTS (SELECT 1 FROM consumo_tratado t
                    WHERE t.negocio_id = k.negocio_id
                      AND t.tratado_em > now() - interval '30 days'
                      AND t.ultima_compra IS NOT DISTINCT FROM n.ultima_compra)
 ORDER BY coalesce(n.valor_12m, 0) DESC, k.negocio_id
 LIMIT 15
"""

SQL_EQUIPA = f"""
WITH abertos AS (
    SELECT k.vendedor, count(*) AS abertos, coalesce(sum(k.valor), 0) AS valor,
           coalesce(sum(k.valor) FILTER (WHERE k.segmento = 'base_instalada'), 0) AS valor_base,
           count(*) FILTER (WHERE k.segmento = 'base_instalada') AS abertos_base,
           count(*) FILTER (WHERE %s - k.ultimo_toque > %s) AS parados
      FROM carteira k
     WHERE {ABERTO}
     GROUP BY 1
), alertas AS (
    SELECT vendedor, count(DISTINCT coalesce(negocio_id, 'C' || cliente_no::text)) AS alertas
      FROM alertas_emitidos WHERE coalesce(notificado_em, emitido_em) >= %s AND notificado GROUP BY 1
), dias AS (
    SELECT c.vendedor, count(DISTINCT c.data_visita::date) AS por_confirmar
      FROM classificacoes_llm c
     WHERE c.data_visita::date >= greatest(%s::date - 14, %s::date) AND c.data_visita::date <= %s::date
       AND NOT EXISTS (SELECT 1 FROM lotes_revisao l
                        WHERE l.vendedor = c.vendedor AND l.dia = c.data_visita::date
                          AND l.fechado_em IS NOT NULL)
     GROUP BY 1
)
SELECT v.vendedor, coalesce(a.abertos, 0) AS abertos, coalesce(a.valor, 0) AS valor,
       coalesce(a.valor_base, 0) AS valor_base, coalesce(a.abertos_base, 0) AS abertos_base,
       coalesce(a.parados, 0) AS parados, coalesce(al.alertas, 0) AS alertas,
       coalesce(d.por_confirmar, 0) AS por_confirmar
  FROM (SELECT DISTINCT vendedor FROM classificacoes_llm WHERE vendedor IS NOT NULL) v
  LEFT JOIN abertos a ON a.vendedor = v.vendedor
  LEFT JOIN alertas al ON al.vendedor = v.vendedor
  LEFT JOIN dias d ON d.vendedor = v.vendedor
 ORDER BY 3 DESC, 2 DESC
"""


def consumo_risco(conn, vendedor: str | None = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(SQL_CONSUMO_RISCO, (vendedor, vendedor))
        out = _linhas(cur)
    h = hoje()
    for c in out:
        c["valor"] = float(c["valor"] or 0)
        c["ultimo_toque"] = str(c["ultimo_toque"])
        c["dias_sem_compra"] = (h - c["ultima_compra"]).days if c["ultima_compra"] else None
        c["ultima_compra"] = str(c["ultima_compra"]) if c["ultima_compra"] else None
    return out


def tratar_consumo(conn, negocio_id: str, por: str, vendedor: str) -> None:
    """«Já tratei» num cliente de consumíveis em risco ou dormente, só pelo comercial dele."""
    with conn.cursor() as cur:
        cur.execute("SELECT k.vendedor, n.ultima_compra FROM carteira k "
                    "JOIN negocios n ON n.negocio_id = k.negocio_id "
                    "WHERE k.negocio_id = %s AND k.tipo = 'consumiveis'", (negocio_id,))
        linha = cur.fetchone()
        if linha is None:
            raise LookupError("cliente de consumíveis inexistente")
        if linha[0] != vendedor:
            raise PermissionError("este cliente não é seu")
        cur.execute("""INSERT INTO consumo_tratado (negocio_id, tratado_por, ultima_compra)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (negocio_id) DO UPDATE SET tratado_em = now(),
                           tratado_por = EXCLUDED.tratado_por, ultima_compra = EXCLUDED.ultima_compra""",
                    (negocio_id, por, linha[1]))
    conn.commit()


def equipa(conn, dias_parado: int, semana) -> list[dict]:
    h = hoje()
    with conn.cursor() as cur:
        cur.execute(SQL_EQUIPA, (h, dias_parado, semana, h, REVISAO_DESDE, h))
        out = _linhas(cur)
    for c in out:
        c["valor"] = float(c["valor"] or 0)
        c["valor_base"] = float(c["valor_base"] or 0)
    return out


def areas(conn) -> list[str]:
    """As áreas de negócio com negócios abertos, para os filtros."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT k.area FROM carteira k WHERE {ABERTO} AND k.area IS NOT NULL ORDER BY 1")
        return [a for (a,) in cur.fetchall()]
