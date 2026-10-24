"""Negócios de um cliente que estavam vivos à data do relatório.

O contexto dado ao modelo tem de conter os negócios que existiam quando o
relatório foi escrito, e não todos os que o cliente alguma vez teve. Sem o
filtro pela data, um cliente com quatro episódios de equipamento ao longo de
dois anos aparece com os quatro ao mesmo tempo, indistinguíveis, e nem o
anotador nem o modelo conseguem decidir a qual o texto se refere.

Com o filtro, a decisão passa a ser possível: os episódios do mesmo cliente e
tipo nunca se sobrepõem no tempo, pelo que à data de um relatório existe no
máximo um candidato de cada tipo.
"""

from dataclasses import dataclass
from datetime import date

# Tolerância, em dias, depois do fim do negócio, igual ao limiar de inatividade
# do §4.5: um relatório escrito pouco depois do último sinal ainda fala desse
# negócio.
TOLERANCIA_DIAS = 90


@dataclass(frozen=True)
class Negocio:
    negocio_id: str
    tipo: str
    descricao: str
    inicio: date | None
    fim: date | None

    def linha(self) -> str:
        return (f"{self.negocio_id} | {self.tipo} | {self.descricao} | "
                f"{self.inicio or '?'} a {self.fim or '?'}")


def vivos_em(conn, cliente_no: int, quando: date) -> list[Negocio]:
    """Negócios do cliente activos à data dada.

    Consumíveis não têm janela: a relação de fornecimento é contínua e entra
    sempre que o cliente tem histórico de compras.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT negocio_id, tipo,
                   COALESCE(descricao, referencia, ''), inicio, fim
              FROM negocios
             WHERE cliente_no = %s
               AND fechado_em IS NULL
               AND (tipo = 'consumiveis'
                    OR (inicio <= %s
                        AND %s <= COALESCE(fim, inicio)
                                  + make_interval(days => %s)))
             ORDER BY tipo, inicio
            """,
            (cliente_no, quando, quando, TOLERANCIA_DIAS),
        )
        return [Negocio(i, t, d, ini, f) for i, t, d, ini, f in cur.fetchall()]


def bloco(negs: list[Negocio]) -> str:
    """Bloco `<negocios_abertos>` para o prompt. Vazio quando não há nenhum."""
    if not negs:
        return ""
    linhas = "\n".join("    " + n.linha() for n in negs)
    return f"  <negocios_abertos>\n{linhas}\n  </negocios_abertos>\n"


def id_para_novo(vistamp: str, ordem: int) -> str:
    """Identificador de um negócio que o modelo abriu.

    Derivado do relatório de origem para que reprocessar o mesmo relatório
    produza o mesmo identificador, como o RF1.5 exige.
    """
    return f"NG-X{vistamp[:10]}-{ordem}"


def criar(conn, negocio_id: str, cliente_no: int, cliente: str, tipo: str,
          descricao: str, inicio, criado_por: str = "sistema") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO negocios (negocio_id, cliente_no, cliente, tipo,
                                  descricao, inicio, criado_por)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (negocio_id) DO NOTHING
            """,
            (negocio_id, cliente_no, cliente, tipo, descricao[:200], inicio, criado_por),
        )
