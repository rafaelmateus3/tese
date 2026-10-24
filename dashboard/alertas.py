"""RF2.3 a RF2.5 e RF2.8: alertas de inatividade e fecho automático.

As quatro regras do RF2.3, com os limiares na tabela `parametros` (RNF3) e os
valores de partida do §4.5:

  negociacao_parada   à espera de resposta: proposta, negociação ou aprovação
                      interna sem contacto há mais de 14 dias
  encomenda_parada    encomenda confirmada sem avanço: no estado 6 há mais de
                      30 dias, contados desde que o negócio lá entrou
  sem_contacto        negócio parado em qualquer estado: sem contacto há mais
                      de 90 dias
  base_sem_contacto   cliente da base instalada sem contacto há mais de 90 dias
                      e sem negócio aberto (se o tiver, o alerta é do negócio)

O alerta dispara na TRANSIÇÃO e não enquanto a condição se mantém (RF2.4).
Medido no §4.5: aplicado à condição, o limiar de 30 dias assinala 683 dos 758
clientes, o que é um inventário e não um alerta. É por isso que existe a tabela
`alertas_emitidos`: sem registo do que já foi emitido não há forma de saber se
a condição é nova. Um novo contacto rearma as regras de contacto; uma mudança de
estado rearma a da encomenda.

O teto por comercial e por semana (RF2.5) conta o que já foi notificado nessa
semana. Quando vincula, os alertas de negócio passam à frente dos de cliente
(um negócio vivo parado pesa mais do que uma visita de manutenção em falta), e
dentro de cada grupo ordena-se por valor e depois por dias, como no §5.3.4. O
excedente fica registado como não notificado: não desaparece, passa para a
lista consultável.

Cadência : a emissão continua diária,
porque é na transição que a condição se deteta, mas a notificação é semanal, no
dia `dia_notificacao` (sexta por omissão), com os alertas da semana ainda por
tratar e o teto aplicado a esse lote (notificar_semana). Os comerciais pediram
os avisos agregados à sexta, para planear a semana seguinte. Com o parâmetro a 0
volta à notificação diária.

«Já tratei» : o comercial tira o alerta da lista sem corrigir o
estado do negócio (tratar). Sem isto, a forma de calar um alerta era corrigir o
estado, e a correção deixava de medir o acerto do modelo (RF1.7).

"""

from datetime import date, timedelta

import config
import parametros
from indicadores import SQL_DESDE_ESTADO, SQL_HISTORICO

ESTADOS_NEGOCIACAO = ("3. Proposta / Orçamento", "4. Negociação", "5. Aprovação Interna")
ESTADO_ENCOMENDA = "6. Encomenda Confirmada"
ESTADOS_FINAIS = ["8. Fechado", "9. Perdido / Cancelado"]

# Quando um negócio dispara várias regras, mostra-se a mais grave.
GRAVIDADE = {"sem_contacto": 0, "negociacao_parada": 1, "encomenda_parada": 2,
             "base_sem_contacto": 3, "mesmo_estado": 4}

SQL_ABERTOS = f"""
WITH {SQL_HISTORICO}
SELECT k.negocio_id, k.ultimo_toque, k.estado, k.vendedor, k.cliente, k.valor,
       k.segmento, k.tipo, k.cliente_no, {SQL_DESDE_ESTADO} AS desde_estado
  FROM carteira k
 WHERE k.fechado_em IS NULL AND k.tipo <> 'consumiveis'
   AND (k.estado IS NULL OR k.estado <> ALL(%s))
"""

# Último contacto de cada cliente da base instalada sem negócio do ciclo aberto.
SQL_BASE_SILENCIOSA = """
WITH u AS (
    SELECT cliente_no, max(data_visita::date) AS ultima
      FROM classificacoes_llm
     WHERE cliente_no IS NOT NULL AND data_visita IS NOT NULL
       AND data_visita::date <= %(hoje)s
     GROUP BY 1
)
SELECT u.cliente_no, u.ultima,
       (SELECT c.vendedor FROM classificacoes_llm c WHERE c.cliente_no = u.cliente_no
         ORDER BY c.data_visita DESC LIMIT 1) AS vendedor,
       (SELECT c.cliente FROM classificacoes_llm c WHERE c.cliente_no = u.cliente_no
         ORDER BY c.data_visita DESC LIMIT 1) AS cliente,
       (SELECT coalesce(sum(n.valor), 0) FROM negocios n
         WHERE n.cliente_no = u.cliente_no AND n.tipo = 'consumiveis') AS valor
  FROM u
 WHERE %(hoje)s - u.ultima > %(dias)s
   AND EXISTS (SELECT 1 FROM parque_equipamentos q
                WHERE q.cliente_no = u.cliente_no AND q.entrada < %(hoje)s)
   AND NOT EXISTS (SELECT 1 FROM carteira k
                    WHERE k.cliente_no = u.cliente_no AND k.fechado_em IS NULL
                      AND k.tipo <> 'consumiveis'
                      AND (k.estado IS NULL OR k.estado <> ALL(%(finais)s)))
"""

# A última emissão de cada regra para cada alvo: é contra ela que se decide se
# a condição é nova.
SQL_ULTIMA_EMISSAO = """
SELECT negocio_id, cliente_no, regra, max(emitido_em)
  FROM alertas_emitidos GROUP BY 1, 2, 3
"""

SQL_SEMANA = """
SELECT coalesce(vendedor, 'sem comercial'),
       count(DISTINCT coalesce(negocio_id, 'C' || cliente_no::text))
  FROM alertas_emitidos
 WHERE coalesce(notificado_em, emitido_em) >= %s AND notificado
 GROUP BY 1
"""

SQL_EMITIR = """
INSERT INTO alertas_emitidos (negocio_id, cliente_no, regra, emitido_em, vendedor,
                              cliente, estado, dias, prioridade, notificado)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
"""

SQL_EMITIDOS = """
SELECT a.id, a.negocio_id, a.cliente_no, a.regra, a.emitido_em, a.vendedor, a.cliente,
       a.estado, a.dias, a.prioridade, a.notificado, a.notificado_em,
       c.valor, c.segmento, c.tipo, c.excerto, c.ultimo_toque, c.fechado_em
  FROM alertas_emitidos a LEFT JOIN carteira c ON c.negocio_id = a.negocio_id
 WHERE (a.emitido_em >= %(desde)s OR a.notificado_em >= %(desde)s
        OR (a.emitido_em = %(primeiro)s AND NOT a.notificado))
   AND (%(v)s::text IS NULL OR a.vendedor = %(v)s)
   AND a.tratado_em IS NULL
"""

SQL_ULTIMO_RELATO_CLIENTE = """
SELECT DISTINCT ON (cliente_no) cliente_no, data_visita::date,
       left(coalesce(nullif(resumo, ''), relatorio), 200)
  FROM classificacoes_llm
 WHERE cliente_no = ANY(%s) AND data_visita IS NOT NULL
 ORDER BY cliente_no, data_visita DESC
"""

SQL_FECHAR = """
INSERT INTO negocios_fechados_auto (negocio_id, fechado_em, ultimo_toque, dias)
VALUES (%s, %s, %s, %s) ON CONFLICT (negocio_id) DO NOTHING
"""


def _alvo(a: dict) -> str:
    return a["negocio_id"] or f"C{a['cliente_no']}"


def _regras_negocio(hoje: date, ultimo: date, desde: date | None, estado: str | None,
                    p: dict) -> list[tuple[str, int, date]]:
    """As regras que a condição actual dispara: (regra, dias, data que a rearma)."""
    dias = (hoje - ultimo).days
    fora = []
    if estado in ESTADOS_NEGOCIACAO and dias > p["dias_negociacao"]:
        fora.append(("negociacao_parada", dias, ultimo))
    if estado == ESTADO_ENCOMENDA:
        desde = desde or ultimo
        no_estado = (hoje - desde).days
        if no_estado > p["dias_mesmo_estado"]:
            fora.append(("encomenda_parada", no_estado, desde))
    if dias > p["dias_sem_contacto"]:
        fora.append(("sem_contacto", dias, ultimo))
    return fora


def _semana(hoje: date) -> date:
    return hoje - timedelta(days=hoje.weekday())


def calcular(conn, hoje: date | None = None) -> list[dict]:
    """Alertas novos de hoje, filtrados por transição e marcados face ao teto."""
    hoje = hoje or config.hoje()
    p = parametros.ler(conn)
    with conn.cursor() as cur:
        cur.execute(SQL_ABERTOS, (ESTADOS_FINAIS,))
        abertos = cur.fetchall()
        cur.execute(SQL_BASE_SILENCIOSA, {"hoje": hoje, "dias": p["dias_base_sem_contacto"],
                                          "finais": ESTADOS_FINAIS})
        base = cur.fetchall()
        cur.execute(SQL_ULTIMA_EMISSAO)
        ultima = {(n or f"C{c}", r): d for n, c, r, d in cur.fetchall()}
        cur.execute(SQL_SEMANA, (_semana(hoje),))
        usados = dict(cur.fetchall())
        cur.execute("SELECT EXISTS (SELECT 1 FROM alertas_emitidos)")
        arranque = not cur.fetchone()[0]
    semanal = p.get("dia_notificacao", 0) > 0

    candidatos = []
    for (negocio_id, ultimo, estado, vendedor, cliente, valor, segmento, tipo,
         cliente_no, desde) in abertos:
        if (hoje - ultimo).days > p["dias_fecho"]:
            continue                          # é fecho automático, não alerta
        for regra, dias, rearma in _regras_negocio(hoje, ultimo, desde, estado, p):
            emitido = ultima.get((negocio_id, regra))
            if emitido and emitido >= rearma:
                continue                      # a condição não é nova
            candidatos.append({
                "negocio_id": negocio_id, "cliente_no": cliente_no, "regra": regra,
                "dias": dias, "estado": estado, "vendedor": vendedor, "cliente": cliente,
                "valor": float(valor or 0), "segmento": segmento, "tipo": tipo,
                "prioridade": round(float(valor or 0) / 1000 + dias, 1),
            })
    for cliente_no, ultima_visita, vendedor, cliente, valor in base:
        emitido = ultima.get((f"C{cliente_no}", "base_sem_contacto"))
        if emitido and emitido >= ultima_visita:
            continue
        dias = (hoje - ultima_visita).days
        candidatos.append({
            "negocio_id": None, "cliente_no": cliente_no, "regra": "base_sem_contacto",
            "dias": dias, "estado": None, "vendedor": vendedor, "cliente": cliente,
            "valor": float(valor or 0), "segmento": "base_instalada", "tipo": None,
            "prioridade": round(float(valor or 0) / 1000 + dias, 1),
        })
    # Em cadência semanal, nada se notifica no dia da emissão: o lote sai no dia
    # da notificação (notificar_semana). O registo é o mesmo.
    return _aplicar_teto(candidatos, p["teto_semanal"], usados, arranque or semanal)


def ordem(a: dict) -> tuple:
    """Negócio antes de cliente; depois valor; depois dias."""
    return (a["negocio_id"] is None, -(a["valor"] or 0), -(a["dias"] or 0))


def _aplicar_teto(candidatos: list[dict], teto: int, usados: dict, arranque: bool = False) -> list[dict]:
    """No máximo `teto` notificados por comercial na semana, os de maior prioridade
    primeiro. O excedente não se perde: sai com notificado=False (RF2.5).

    Um alvo conta uma vez: se dispara várias regras, mostra-se a mais grave e as
    outras ficam registadas com ela, para não reaparecerem no dia seguinte."""
    por_alvo: dict[str, dict] = {}
    for c in sorted(candidatos, key=lambda x: GRAVIDADE[x["regra"]]):
        k = _alvo(c)
        if k in por_alvo:
            por_alvo[k]["inclui"].append(c["regra"])
        else:
            por_alvo[k] = {**c, "inclui": []}
    contagem: dict[str, int] = {}
    out = []
    for c in sorted(por_alvo.values(), key=ordem):
        v = c["vendedor"] or "sem comercial"
        n = contagem.get(v, 0)
        c["notificado"] = (not arranque) and n < teto - usados.get(v, 0)
        contagem[v] = n + (1 if c["notificado"] else 0)
        out.append(c)
    return out


def emitir(conn, alertas: list[dict], hoje: date | None = None) -> int:
    """Grava os alertas do dia. Devolve quantos foram notificados."""
    hoje = hoje or config.hoje()
    with conn.cursor() as cur:
        for a in alertas:
            for regra in [a["regra"], *a.get("inclui", [])]:
                cur.execute(SQL_EMITIR, (a["negocio_id"], a["cliente_no"], regra, hoje,
                                         a["vendedor"], a["cliente"], a["estado"],
                                         a["dias"], a["prioridade"], a["notificado"]))
    conn.commit()
    return sum(1 for a in alertas if a["notificado"])


def ultimo_dia_notificacao(hoje: date, dia: int) -> date | None:
    """O dia de notificação mais recente, até hoje inclusive (None se diária)."""
    if not dia:
        return None
    return hoje - timedelta(days=(hoje.isoweekday() - dia) % 7)


def emitidos(conn, vendedor: str | None = None, dias: int = 14) -> list[dict]:
    """Os alertas emitidos nos últimos dias e ainda por tratar, um por alvo e dia.

    Tratado quer dizer que já houve contacto depois do alerta, ou que o negócio
    fechou. Cada alerta traz `notificado`: os que o teto deixou de fora vão para a
    lista consultável, não desaparecem."""
    hoje = config.hoje()
    lote = ultimo_dia_notificacao(hoje, parametros.ler(conn).get("dia_notificacao", 0))
    with conn.cursor() as cur:
        cur.execute("SELECT min(emitido_em) FROM alertas_emitidos")
        primeiro = cur.fetchone()[0]
        cur.execute(SQL_EMITIDOS, {"desde": hoje - timedelta(days=dias), "primeiro": primeiro,
                                   "v": vendedor})
        cols = [d[0] for d in cur.description]
        linhas = [dict(zip(cols, r)) for r in cur.fetchall()]
        clientes = sorted({a["cliente_no"] for a in linhas if not a["negocio_id"]})
        relato = {}
        if clientes:
            cur.execute(SQL_ULTIMO_RELATO_CLIENTE, (clientes,))
            relato = {c: (d, x) for c, d, x in cur.fetchall()}

    melhor: dict[tuple, dict] = {}
    for a in linhas:
        k = (_alvo(a), a["emitido_em"])
        if k not in melhor or GRAVIDADE.get(a["regra"], 9) < GRAVIDADE.get(melhor[k]["regra"], 9):
            melhor[k] = a
    out = []
    for a in melhor.values():
        if not a["negocio_id"]:
            ultima, excerto = relato.get(a["cliente_no"], (None, None))
            a.update(ultimo_toque=ultima, excerto=excerto, segmento="base_instalada")
        if a["fechado_em"] or (a["ultimo_toque"] and a["ultimo_toque"] > a["emitido_em"]):
            continue
        a.pop("fechado_em")
        # Atrasado: veio do arranque (a condição acumulada do histórico) e ainda não foi
        # notificado; entra aos poucos nos lotes de sexta, depois dos novos.
        a["atrasado"] = not a["notificado"] and primeiro is not None and a["emitido_em"] == primeiro
        # À espera do dia da notificação: nasceu depois do último lote.
        a["aguarda"] = (bool(lote) and not a["notificado"] and not a["atrasado"]
                        and a["emitido_em"] > lote)
        a["notificado_em"] = str(a["notificado_em"]) if a["notificado_em"] else None
        a["ultimo_toque"] = str(a["ultimo_toque"]) if a["ultimo_toque"] else None
        a["emitido_em"] = str(a["emitido_em"])
        a["valor"] = float(a["valor"] or 0)
        a["prioridade"] = float(a["prioridade"] or 0)
        out.append(a)
    out.sort(key=lambda a: (not a["notificado"], *ordem(a)))
    return out


def fechar_inativos(conn, hoje: date | None = None) -> list[dict]:
    """RF2.8: fecho automático sem contacto, distinguível de uma perda declarada."""
    hoje = hoje or config.hoje()
    limite = hoje - timedelta(days=parametros.ler(conn)["dias_fecho"])
    with conn.cursor() as cur:
        cur.execute(SQL_ABERTOS, (ESTADOS_FINAIS,))
        velhos = [s for s in cur.fetchall() if s[1] < limite]
        for negocio_id, ultimo, *_ in velhos:
            cur.execute(SQL_FECHAR, (negocio_id, hoje, ultimo, (hoje - ultimo).days))
            cur.execute("UPDATE negocios SET fechado_em = %s, "
                        "fecho_motivo = 'automatico_180d' WHERE negocio_id = %s",
                        (hoje, negocio_id))
    conn.commit()
    return [{"negocio_id": s[0], "ultimo_toque": str(s[1]),
             "dias": (hoje - s[1]).days} for s in velhos]


def notificar_semana(conn, hoje: date | None = None) -> int:
    """RF2.5 em cadência semanal: no dia de notificação, notifica os alertas da
    semana ainda por tratar, no máximo `teto_semanal` por comercial, pela ordem do
    §5.3.4. O excedente fica não notificado, na lista consultável.

    Os alertas do arranque (a condição acumulada da primeira corrida) entram depois
    dos novos, pela mesma ordem, a encher o lote. Enquanto um comercial tiver
    atrasados, o teto dele sobe para `teto_atraso` (decisão de 15-Out-2026: o atraso
    trata-se em poucas semanas sem tapar os avisos novos)."""
    hoje = hoje or config.hoje()
    p = parametros.ler(conn)
    dia = p.get("dia_notificacao", 0)
    if not dia or hoje.isoweekday() != dia:
        return 0
    with conn.cursor() as cur:
        cur.execute("SELECT min(emitido_em) FROM alertas_emitidos")
        primeiro = cur.fetchone()[0]
        cur.execute(SQL_SEMANA, (_semana(hoje),))
        usados = dict(cur.fetchall())
    if primeiro is None:
        return 0
    inicio = hoje - timedelta(days=7)
    todos = emitidos(conn, None, dias=7)
    lote = [a for a in todos
            if not a["notificado"] and date.fromisoformat(a["emitido_em"]) > max(inicio, primeiro)]
    atrasados = [a for a in todos if a["atrasado"]]

    def um_por_alvo(lista):
        por_alvo: dict[str, dict] = {}
        for a in sorted(lista, key=lambda x: GRAVIDADE.get(x["regra"], 9)):
            por_alvo.setdefault(_alvo(a), a)
        return sorted(por_alvo.values(), key=ordem)

    novos = um_por_alvo(lote)
    velhos = [a for a in um_por_alvo(atrasados) if _alvo(a) not in {_alvo(x) for x in novos}]
    com_atraso = {a["vendedor"] or "sem comercial" for a in velhos}
    contagem: dict[str, int] = {}
    escolhidos = []
    for a in novos + velhos:              # os novos primeiro; os atrasados enchem o resto
        v = a["vendedor"] or "sem comercial"
        teto = p.get("teto_atraso", p["teto_semanal"]) if v in com_atraso else p["teto_semanal"]
        n = contagem.get(v, 0)
        if n < teto - usados.get(v, 0):
            escolhidos.append(a)
            contagem[v] = n + 1
    with conn.cursor() as cur:
        for a in escolhidos:
            if a["atrasado"]:
                de, ate = primeiro, primeiro
            else:
                de, ate = max(inicio, primeiro) + timedelta(days=1), hoje
            cur.execute("""UPDATE alertas_emitidos SET notificado = TRUE, notificado_em = %s
                            WHERE emitido_em BETWEEN %s AND %s AND tratado_em IS NULL AND NOT notificado
                              AND ((%s::text IS NOT NULL AND negocio_id = %s)
                                   OR (%s::text IS NULL AND negocio_id IS NULL AND cliente_no = %s))""",
                        (hoje, de, ate, a["negocio_id"], a["negocio_id"],
                         a["negocio_id"], a["cliente_no"]))
    conn.commit()
    return len(escolhidos)


def tratar(conn, alerta_id: int, por: str, vendedor: str | None = None) -> int:
    """«Já tratei»: tira o alerta da lista sem tocar no estado do negócio. Marca
    todas as emissões por tratar do mesmo alvo. Com `vendedor`, só se for dele."""
    with conn.cursor() as cur:
        cur.execute("SELECT negocio_id, cliente_no, vendedor FROM alertas_emitidos WHERE id = %s",
                    (alerta_id,))
        linha = cur.fetchone()
        if linha is None:
            raise LookupError("alerta inexistente")
        negocio_id, cliente_no, dono = linha
        if vendedor is not None and dono != vendedor:
            raise PermissionError("este alerta não é seu")
        cur.execute("""UPDATE alertas_emitidos SET tratado_em = now(), tratado_por = %s
                        WHERE tratado_em IS NULL
                          AND ((%s::text IS NOT NULL AND negocio_id = %s)
                               OR (%s::text IS NULL AND negocio_id IS NULL AND cliente_no = %s))""",
                    (por, negocio_id, negocio_id, negocio_id, cliente_no))
        n = cur.rowcount
    conn.commit()
    return n


def passo_ciclo(ligacao, falar) -> tuple[int, int]:
    """Passos 4 e 5 do ciclo: o fecho automático (RF2.8) e os alertas novos do dia,
    com o lote semanal (RF2.3 a RF2.5). Devolve (fechados, notificados)."""
    fechados = len(ligacao.executar(fechar_inativos))
    falar(f"fecho automático: {fechados} negócios")
    novos = ligacao.executar(calcular)
    emitidos = ligacao.executar(lambda c: emitir(c, novos))
    lote = ligacao.executar(notificar_semana)
    emitidos += lote
    falar(f"alertas: {len(novos)} emitidos · {emitidos} notificados"
          + (" (lote semanal)" if lote else ""))
    return fechados, emitidos
