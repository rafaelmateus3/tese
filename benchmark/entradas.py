"""Congelamento da entrada do benchmark.

A mensagem dada ao modelo inclui o bloco de negócios vivos à data do relatório.
Esse bloco mudaria entre corridas à medida que o sistema fosse escrevendo, e
dois modelos deixariam de estar a responder à mesma pergunta. Congela-se uma
vez, guarda-se, e todas as corridas leem daí.
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))

import db          # noqa: E402
import negocios    # noqa: E402
from llm import _mensagem  # noqa: E402
from config import ENTRADA_VERSION  # noqa: E402

SQL = """
INSERT INTO benchmark_entradas (vistamp, cliente_no, cliente, estrato, mensagem)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (vistamp) DO UPDATE SET
    mensagem = EXCLUDED.mensagem, estrato = EXCLUDED.estrato,
    congelada_em = now()
"""


def congelar(ligacao, relatorios: list[dict]) -> int:
    """Grava a mensagem exacta de cada relatório. Devolve quantas gravou."""
    for linha in relatorios:
        no = int(linha["no"])
        vivos = ligacao.executar(
            lambda c: negocios.vivos_em(c, no, linha["data"]))
        bloco = negocios.bloco(vivos)
        # O estrato conta apenas negócios do ciclo comercial. Os de consumíveis
        # existem para qualquer cliente com histórico de compras e quase nunca
        # faltam, pelo que incluí-los tornaria o estrato constante e inútil
        # como factor de estratificação.
        ciclo = [n for n in vivos if n.tipo != "consumiveis"]
        estrato = "com_negocio_aberto" if ciclo else "sem_negocio_aberto"
        ligacao.executar(lambda c: _gravar(
            c, str(linha["vistamp"]).strip(), no, str(linha["nome"]).strip(),
            estrato, _mensagem(linha, bloco, linha.get("_historico", ""))))
    return len(relatorios)


def _gravar(conn, vistamp, cliente_no, cliente, estrato, mensagem):
    with conn.cursor() as cur:
        cur.execute(SQL, (vistamp, cliente_no, cliente, estrato, mensagem))
    conn.commit()


def carregar(conn, limite: int | None = None,
             apenas: list[str] | None = None,
             versao: str = ENTRADA_VERSION) -> list[tuple[str, str]]:
    """As entradas congeladas, por ordem estável. Devolve (vistamp, mensagem).

    `apenas` restringe a um conjunto fixado antes de correr, que é como as
    fases do protocolo de selecção funcionam: a amostra é escolhida uma vez,
    fica registada, e todos os modelos respondem exactamente aos mesmos
    relatórios. Sem isso, limitar a corrida daria os primeiros por ordem de
    identificador, que não é uma amostra.
    """
    sql = "SELECT vistamp, mensagem FROM benchmark_entradas WHERE entrada_version = %s"
    params: list = [versao]
    if apenas:
        sql += " AND vistamp IN (" + ", ".join(["%s"] * len(apenas)) + ")"
        params += list(apenas)
    sql += " ORDER BY vistamp"
    if limite:
        sql += " LIMIT %s"
        params.append(limite)
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        linhas = cur.fetchall()
    if apenas and len(linhas) != len(apenas):
        faltam = set(apenas) - {v for v, _ in linhas}
        raise SystemExit(
            f"{len(faltam)} relatório(s) da amostra não estão congelados: "
            + ", ".join(sorted(faltam)))
    return linhas


# Quantos relatórios anteriores do mesmo cliente acompanham cada relatório.
# Três é a mediana de anteriores existentes no conjunto e custa cerca de noventa
# tokens. Alargar traria episódios já encerrados de volta ao contexto, que é a
# ambiguidade que o filtro por data eliminou.
HISTORICO = 3


def bloco_historico(anteriores: pd.DataFrame) -> str:
    """Os relatórios anteriores do cliente, do mais recente para o mais antigo."""
    if anteriores.empty:
        return ""
    linhas = "\n".join(
        f"    {r.data:%Y-%m-%d} | {str(r.rel).strip()}"
        for r in anteriores.itertuples())
    return f"  <relatorios_anteriores>\n{linhas}\n  </relatorios_anteriores>\n"


def ler_relatorios(caminho_visitas: str, caminho_gold: str) -> list[dict]:
    """Os relatórios do conjunto de referência, com os campos do ERP.

    Cada um leva já o bloco de relatórios anteriores do mesmo cliente, para que
    a mensagem congelada não dependa de voltar a abrir a extração do ERP.
    """
    gold = pd.read_excel(caminho_gold, sheet_name="Anotação", usecols=["vistamp"])
    stamps = {str(v).strip() for v in gold["vistamp"] if pd.notna(v)}

    todas = pd.read_excel(caminho_visitas)
    todas = todas[todas["no"].notna()].copy()
    todas["_vs"] = todas["vistamp"].astype(str).str.strip()
    todas["data"] = pd.to_datetime(todas["data"])
    todas["rel"] = todas["rel"].fillna("").astype(str)

    alvo = todas[todas["_vs"].isin(stamps)]
    registos = []
    for r in alvo.itertuples():
        anteriores = todas[(todas["no"] == r.no) & (todas["data"] < r.data)
                           & (todas["rel"].str.strip() != "")]
        anteriores = anteriores.sort_values("data", ascending=False).head(HISTORICO)
        linha = {c: getattr(r, c) for c in alvo.columns if c != "_vs"}
        linha["data"] = r.data.date()
        linha["_historico"] = bloco_historico(anteriores)
        registos.append(linha)
    return registos
