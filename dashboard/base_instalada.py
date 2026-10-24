"""RF2.2: separar a atividade dirigida a quem já tem equipamento da dirigida a
quem não tem.

O §4.2 fixou o critério sobre uma janela de observação fechada: o cliente tem
base instalada se o equipamento entrou no parque antes do início da janela. Num
sistema contínuo não há janela, e a tradução é avaliar o atributo **na data do
acontecimento**: para um contacto, se o cliente já tinha equipamento nessa data;
para faturação, se já tinha antes de o negócio começar. Sem isto, uma máquina
entregue na semana passada transformaria essa conquista em base instalada.

A conversão, cliente que não tinha e passou a ter, é exposta como acontecimento
derivado e não como terceira categoria, porque o requisito pede duas.

O indicador é conservador por construção: a data de instalação falta em 66% do
parque e nesses casos vale a data de criação do registo, que é posterior ou
igual à instalação real. Subestima a base instalada, nunca a sobrestima.
"""

from datetime import date

PROVENIENCIA = {
    "indicador": "Conquista vs base instalada",
    "formula": ("cliente com base instalada à data do acontecimento = existe "
                "equipamento cuja entrada no parque é anterior a essa data"),
    "fonte": "parque_equipamentos, carregado do registo de equipamentos do ERP",
    "problema": "P4",
    "requisito": "RF2.2",
    "limitacao": ("a data de instalação falta em 66% do parque; nesses casos a "
                  "entrada é datada pela criação do registo"),
}

SQL_SEGMENTO = """
SELECT EXISTS (SELECT 1 FROM parque_equipamentos
                WHERE cliente_no = %s AND entrada < %s)
"""

SQL_ESFORCO = """
SELECT CASE WHEN EXISTS (SELECT 1 FROM parque_equipamentos p
                          WHERE p.cliente_no = c.cliente_no
                            AND p.entrada < c.data_visita::date)
            THEN 'base_instalada' ELSE 'conquista' END AS segmento,
       count(*)                       AS contactos,
       count(DISTINCT c.cliente_no)   AS clientes,
       round(sum(coalesce(c.duracao_min, 0)) / 60.0) AS horas
  FROM classificacoes_llm c
 WHERE c.cliente_no IS NOT NULL AND c.data_visita IS NOT NULL
   AND (%s::text IS NULL OR c.vendedor = %s)
 GROUP BY 1
"""

SQL_VALOR = """
SELECT CASE WHEN EXISTS (SELECT 1 FROM parque_equipamentos p
                          WHERE p.cliente_no = n.cliente_no
                            AND p.entrada < n.inicio)
            THEN 'base_instalada' ELSE 'conquista' END AS segmento,
       n.tipo,
       coalesce(sum(n.valor), 0) AS valor
  FROM negocios n
 WHERE n.inicio IS NOT NULL
 GROUP BY 1, 2
"""

# Com um comercial escolhido: o valor dos negócios da carteira dele.
SQL_VALOR_VENDEDOR = """
SELECT segmento, tipo, coalesce(sum(valor), 0) FROM carteira
 WHERE vendedor = %s GROUP BY 1, 2
"""

SQL_CONVERSOES = """
SELECT cliente_no, min(entrada) AS convertido_em
  FROM parque_equipamentos
 GROUP BY cliente_no
HAVING min(entrada) BETWEEN %s AND %s
 ORDER BY 2
"""


def segmento(conn, cliente_no: int, quando: date) -> str:
    with conn.cursor() as cur:
        cur.execute(SQL_SEGMENTO, (cliente_no, quando))
        return "base_instalada" if cur.fetchone()[0] else "conquista"


def _percentagens(linhas: list[dict], campo: str) -> list[dict]:
    total = sum(l[campo] for l in linhas) or 1
    for l in linhas:
        l["pct"] = round(l[campo] / total * 100, 1)
    return linhas


def esforco(conn, vendedor: str | None = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(SQL_ESFORCO, (vendedor, vendedor))
        linhas = [{"segmento": s, "contactos": c, "clientes": cl, "horas": int(h or 0),
                   "por_cliente": round(c / cl, 1) if cl else 0}
                  for s, c, cl, h in cur.fetchall()]
    return _percentagens(linhas, "contactos")


def valor(conn, vendedor: str | None = None) -> list[dict]:
    """Valor por segmento, decomposto por tipo de negócio.

    A decomposição é o que sustenta a leitura do §4.2: a base instalada é
    sobretudo um activo de venda e não uma anuidade de serviço.
    """
    with conn.cursor() as cur:
        if vendedor:
            cur.execute(SQL_VALOR_VENDEDOR, (vendedor,))
        else:
            cur.execute(SQL_VALOR)
        bruto = cur.fetchall()
    por_segmento: dict[str, dict] = {}
    for seg, tipo, v in bruto:
        d = por_segmento.setdefault(seg, {"segmento": seg, "valor": 0.0, "por_tipo": {}})
        d["valor"] += float(v)
        d["por_tipo"][tipo] = round(float(v), 2)
    return _percentagens(list(por_segmento.values()), "valor")


def conversoes(conn, desde: date, ate: date) -> list[dict]:
    """Clientes que passaram de conquista a base instalada no período.

    Não é uma terceira categoria: é o acontecimento que move um cliente de um
    segmento para o outro, e mostra se a conquista produz base instalada nova.
    """
    with conn.cursor() as cur:
        cur.execute(SQL_CONVERSOES, (desde, ate))
        return [{"cliente_no": c, "convertido_em": str(d)} for c, d in cur.fetchall()]
