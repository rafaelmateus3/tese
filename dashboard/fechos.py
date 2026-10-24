"""Fechos e correções fora da revisão do dia (decisões de 15-Out-2026, primeiros dias de uso).

Três problemas vistos pelos comerciais na carteira:

  1. Negócios que já terminaram continuam abertos: nenhum relatório posterior diz que a
     entrega foi aceite ou que o cliente desistiu, e o negócio só sai aos 180 dias sem
     contacto (RF2.8). Duas saídas:
       - o comercial fecha o negócio na carteira: ganho, perdido ou «não avançou»;
       - o ciclo fecha como ganho o negócio adjudicado ou em produção/entrega quando há
         fatura do tipo ao mesmo cliente depois da adjudicação (regra do §6.4).
  2. A carteira arranca com erros de classificação do histórico, que a revisão do dia
     (só a partir do arranque) já não apanha: o comercial corrige a fase ou o tipo de um
     negócio na carteira. A correção cai no último par do negócio e fica registada como
     qualquer outra (avaliacao_pares), no lote do dia desse relatório.
  3. Um fecho feito por engano desfaz-se (reabrir), só para os fechos do comercial.

Os fechos ficam em `negocios` (fechado_em, fecho_motivo, fechado_por). Não mexem em
`pares_llm`: o que o modelo disse continua a ser o que o modelo disse.
"""

from datetime import date, timedelta

import pandas as pd

import avaliacao
import config

MOTIVOS_FECHO = {"ganho": "comercial_ganho", "perdido": "comercial_perdido",
                 "nao_avancou": "comercial_nao_avancou"}
ADJUDICADO = ("6. Encomenda Confirmada", "7. Em Produção / Entrega")
FAMILIAS_EQUIPAMENTO = {"EQUIPAMENTOS", "SOLUÇÃO", "SOFTWARE"}
AREA_PRODUCAO = "AREA C"
DOCUMENTOS = {"Factura", "Fatura Recibo"}

SQL_DONO = """
SELECT vendedor, fechado_em, fecho_motivo, tipo FROM carteira WHERE negocio_id = %s
"""

# O último par efetivo do negócio (os fundidos contam como o negócio do registo).
SQL_ULTIMO_PAR = """
SELECT p.par_id, c.vendedor, c.data_visita::date, p.origem, p.tipo, p.estado
  FROM pares_efetivos p
  JOIN classificacoes_llm c ON c.vistamp = p.vistamp
  LEFT JOIN negocios x ON x.negocio_id = p.negocio_id
 WHERE coalesce(x.fundido_em, p.negocio_id) = %s AND c.data_visita IS NOT NULL
 ORDER BY c.data_visita DESC, p.criado_em DESC
 LIMIT 1
"""


def _dono(cur, negocio_id: str, vendedor: str | None):
    cur.execute(SQL_DONO, (negocio_id,))
    linha = cur.fetchone()
    if linha is None:
        raise LookupError("negócio inexistente")
    if vendedor is not None and linha[0] != vendedor:
        raise PermissionError("este negócio não está na sua carteira")
    return linha


def fechar(conn, negocio_id: str, motivo: str, por: str, vendedor: str | None) -> None:
    """O comercial fecha um negócio da sua carteira."""
    if motivo not in MOTIVOS_FECHO:
        raise ValueError("motivo de fecho desconhecido")
    with conn.cursor() as cur:
        _, fechado_em, _, tipo = _dono(cur, negocio_id, vendedor)
        if fechado_em:
            raise ValueError("este negócio já está fechado")
        if tipo == "consumiveis":
            raise ValueError("a relação de consumíveis não se fecha: vem da faturação")
        cur.execute("""UPDATE negocios SET fechado_em = %s, fecho_motivo = %s, fechado_por = %s
                        WHERE negocio_id = %s AND fechado_em IS NULL""",
                    (config.hoje(), MOTIVOS_FECHO[motivo], por, negocio_id))
    conn.commit()


def reabrir(conn, negocio_id: str, por: str, vendedor: str | None) -> None:
    """Desfaz um fecho feito pelo comercial (não os automáticos nem os da faturação)."""
    with conn.cursor() as cur:
        _, fechado_em, motivo, _ = _dono(cur, negocio_id, vendedor)
        if not fechado_em or not (motivo or "").startswith("comercial_"):
            raise ValueError("só se reabre um negócio fechado por um comercial")
        cur.execute("""UPDATE negocios SET fechado_em = NULL, fecho_motivo = NULL, fechado_por = NULL
                        WHERE negocio_id = %s""", (negocio_id,))
    conn.commit()


def corrigir(conn, negocio_id: str, por: str, vendedor: str | None,
             estado: str | None = None, tipo: str | None = None) -> None:
    """Corrige a fase ou o tipo de um negócio da carteira, no seu último relatório."""
    if not estado and not tipo:
        raise ValueError("diga a fase ou o tipo certo")
    with conn.cursor() as cur:
        _dono(cur, negocio_id, vendedor)
        cur.execute(SQL_ULTIMO_PAR, (negocio_id,))
        linha = cur.fetchone()
    if linha is None:
        raise LookupError("o negócio não tem relatórios")
    par_id, autor, dia, origem, tipo_atual, estado_atual = linha
    if origem == "comercial":
        raise ValueError("este negócio foi acrescentado à mão: corrige-o na revisão desse dia")
    if estado == estado_atual:
        estado = None
    if tipo == tipo_atual:
        tipo = None
    if not estado and not tipo:
        return
    lote_id = avaliacao.abrir_lote(conn, autor, dia)
    motivo = "tipo errado" if tipo else "fronteira entre estados"
    avaliacao.corrigir(conn, par_id, lote_id, por, motivo,
                       estado_corrigido=estado, tipo_corrigido=tipo, via="carteira")


def fechar_faturados(conn, faturas: pd.DataFrame, hoje: date | None = None) -> list[dict]:
    """Fecha como ganho o negócio adjudicado ou em produção/entrega que já foi faturado.

    Regra (a do §6.4): fatura ou fatura-recibo de valor positivo ao mesmo cliente, do tipo
    do negócio (equipamento: famílias EQUIPAMENTOS, SOLUÇÃO, SOFTWARE; produção: área
    AREA C), com data igual ou posterior à entrada do negócio em adjudicado (6) ou em
    produção/entrega (7). A data de fecho é a da primeira dessas faturas."""
    hoje = hoje or config.hoje()
    f = faturas[faturas["Tipo Documento"].isin(DOCUMENTOS)
                & (faturas["Preço Venda Total F (€)"] > 0)].copy()
    f = f.dropna(subset=["Nº Cliente", "Data do Documento"])
    fam = f["Familia"].fillna("").astype(str).str.strip()
    area = f["Área de Negócio"].fillna("").astype(str).str.strip() if "Área de Negócio" in f else ""
    f["tipo"] = None
    f.loc[fam.isin(FAMILIAS_EQUIPAMENTO), "tipo"] = "equipamento"
    if isinstance(area, pd.Series):
        f.loc[area == AREA_PRODUCAO, "tipo"] = "producao"
    f = f.dropna(subset=["tipo"])
    f["d"] = pd.to_datetime(f["Data do Documento"]).dt.date
    por_cliente = {(int(c), t): sorted(g["d"]) for (c, t), g in f.groupby(["Nº Cliente", "tipo"])}

    with conn.cursor() as cur:
        cur.execute("""
            SELECT k.negocio_id, k.cliente_no, k.tipo
              FROM carteira k
             WHERE k.fechado_em IS NULL AND k.tipo IN ('equipamento', 'producao')
               AND k.estado = ANY(%s)""", (list(ADJUDICADO),))
        candidatos = cur.fetchall()
        fechados = []
        for negocio_id, cliente_no, tipo in candidatos:
            cur.execute("""
                SELECT c.data_visita::date, p.estado
                  FROM pares_efetivos p
                  JOIN classificacoes_llm c ON c.vistamp = p.vistamp
                  LEFT JOIN negocios x ON x.negocio_id = p.negocio_id
                 WHERE coalesce(x.fundido_em, p.negocio_id) = %s AND c.data_visita IS NOT NULL
                 ORDER BY 1 DESC, p.criado_em DESC""", (negocio_id,))
            entrada = None
            for d, e in cur.fetchall():          # do mais recente para trás, enquanto 6 ou 7
                if e in ADJUDICADO:
                    entrada = d
                elif e is not None:
                    break
            if entrada is None:                  # a fase veio de um dossier (encomenda, produção)
                cur.execute("""SELECT min(e.data) FROM eventos_dossier e
                                 JOIN negocios n ON n.negocio_id = e.negocio_id
                                WHERE coalesce(n.fundido_em, e.negocio_id) = %s AND e.estado = ANY(%s)""",
                            (negocio_id, list(ADJUDICADO)))
                entrada = cur.fetchone()[0]
            datas = [d for d in por_cliente.get((int(cliente_no), tipo), [])
                     if entrada and entrada <= d <= hoje]
            if not datas:
                continue
            cur.execute("""UPDATE negocios SET fechado_em = %s, fecho_motivo = 'faturado',
                                  fechado_por = 'faturação'
                            WHERE negocio_id = %s AND fechado_em IS NULL""",
                        (datas[0], negocio_id))
            fechados.append({"negocio_id": negocio_id, "fatura": str(datas[0])})
    conn.commit()
    return fechados


def recentes(conn, vendedor: str | None, dias: int = 14) -> list[dict]:
    """Os negócios que o comercial fechou ou juntou nos últimos dias, para os desfazer."""
    desde = config.hoje() - timedelta(days=dias)
    with conn.cursor() as cur:
        cur.execute("""
            SELECT negocio_id, cliente, tipo, estado, fecho_motivo, fechado_em::text AS fechado_em,
                   NULL AS juntado_a
              FROM carteira
             WHERE fecho_motivo LIKE 'comercial\\_%%' AND fechado_em >= %s
               AND (%s::text IS NULL OR vendedor = %s)
            UNION ALL
            SELECT n.negocio_id, coalesce(n.cliente, k.cliente), n.tipo, NULL, 'juntado',
                   n.fundido_data::text, k.cliente || ' (' || n.fundido_em || ')'
              FROM negocios n JOIN carteira k ON k.negocio_id = n.fundido_em
             WHERE n.fundido_por IS NOT NULL AND n.fundido_por <> 'dossier'
               AND n.fundido_por NOT LIKE 'via:%%' AND n.fundido_data >= %s
               AND (%s::text IS NULL OR k.vendedor = %s)
             ORDER BY 6 DESC, 2""",
                    (desde, vendedor, vendedor, desde, vendedor, vendedor))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def juntar(conn, negocio_id: str, com: str, por: str, vendedor: str | None) -> None:
    """Junta um negócio duplicado a outro do mesmo cliente: os relatórios e dossiers do
    primeiro passam a contar no segundo (a mesma fusão que o classificador usa)."""
    if negocio_id == com:
        raise ValueError("escolha outro negócio")
    with conn.cursor() as cur:
        _dono(cur, negocio_id, vendedor)
        cur.execute("SELECT cliente_no, fechado_em FROM carteira WHERE negocio_id = %s", (com,))
        alvo = cur.fetchone()
        cur.execute("SELECT cliente_no FROM negocios WHERE negocio_id = %s", (negocio_id,))
        origem = cur.fetchone()
        if alvo is None:
            raise LookupError("o outro negócio não existe")
        if alvo[0] != origem[0]:
            raise ValueError("só se juntam negócios do mesmo cliente")
        if alvo[1]:
            raise ValueError("o outro negócio está fechado")
        cur.execute("""UPDATE negocios SET fundido_em = %s, fundido_por = %s, fundido_data = %s
                        WHERE negocio_id = %s AND fundido_em IS NULL""",
                    (com, por, config.hoje(), negocio_id))
        # A fusão resolve-se a um nível: o que já estava fundido neste passa para o outro,
        # marcado para o «separar» o poder devolver.
        cur.execute("""UPDATE negocios SET fundido_em = %s, fundido_por = %s
                        WHERE fundido_em = %s AND negocio_id <> %s""",
                    (com, "via:" + negocio_id, negocio_id, com))
    conn.commit()


def separar(conn, negocio_id: str, por: str, vendedor: str | None) -> None:
    """Desfaz um «juntar» feito por uma pessoa (não as fusões do classificador nem do PHC)."""
    with conn.cursor() as cur:
        cur.execute("SELECT fundido_em, fundido_por FROM negocios WHERE negocio_id = %s", (negocio_id,))
        linha = cur.fetchone()
        if linha is None or not linha[0] or not linha[1] or linha[1] == "dossier" or linha[1].startswith("via:"):
            raise ValueError("este negócio não foi juntado por um comercial")
        _dono(cur, linha[0], vendedor)
        cur.execute("""UPDATE negocios SET fundido_em = NULL, fundido_por = NULL, fundido_data = NULL
                        WHERE negocio_id = %s""", (negocio_id,))
        cur.execute("""UPDATE negocios SET fundido_em = %s, fundido_por = NULL
                        WHERE fundido_por = %s""", (negocio_id, "via:" + negocio_id))
    conn.commit()


def passo_ciclo(ligacao, faturas: pd.DataFrame, falar) -> int:
    """Passo 4 do ciclo, depois dos dossiers: fecha como ganhos os negócios faturados."""
    faturados = ligacao.executar(lambda c: fechar_faturados(c, faturas))
    falar(f"fecho pela faturação: {len(faturados)} negócios")
    return len(faturados)
