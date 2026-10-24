"""Carga inicial da base de dados a partir das extrações do ERP.

    python carga.py --erp "..\\extracoes" --registos "..\\dados"
    python carga.py --erp ..\\exemplos --registos ..\\exemplos    (dados fictícios)

Carrega duas coisas que o classificador precisa de encontrar já lá:

  parque_equipamentos  quem tem equipamento nosso e desde quando, que é o que
                       separa conquista de base instalada (RF2.2)
  negocios             os negócios abertos, que são o contexto injetado no
                       prompt e o destino a que os pares apontam

Correr de novo actualiza o que existe e acrescenta o que falta. O ciclo noturno
(ciclo.py) usa atualizar(): só o parque e a relação de consumíveis.
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import consumiveis  # noqa: E402
import db  # noqa: E402
import parametros  # noqa: E402
from extracoes import EQUIPAMENTOS, FATURAS, VISITAS, mais_recente  # noqa: E402

EMPRESA = 3504

# Extrações directas do ERP: usa-se a mais recente de cada tipo na pasta --erp
# (a carga inicial em produção usou as de 6-Set-2026).

# Registos de negócios derivados das extrações.
REGISTOS = {
    "negocios_equip": "260830_Negocios_Equip_Producao_v1.xlsx",
    "negocios_cons": "260916_Consumiveis_por_Cliente_v4.xlsx",
}


def parque(erp: Path, ficheiro: Path | None = None) -> list[tuple]:
    """Uma linha por equipamento instalado.

    A data de entrada no parque é a mais tardia entre a instalação e a criação
    do registo. Quando a instalação está em falta o ERP grava 1900-01-01 e a
    data de criação é a que prevalece, que é o comportamento pretendido: o
    indicador fica conservador e nunca sobrestima a base instalada.
    """
    d = pd.read_excel(ficheiro or mais_recente(erp, EQUIPAMENTOS))
    d = d[d["no"].notna() & d["no"].ne(EMPRESA)]
    for c in ("instal", "ousrdata"):
        d[c] = pd.to_datetime(d[c], errors="coerce")
    d = d.dropna(subset=["instal", "ousrdata"])
    d["entrada"] = d[["instal", "ousrdata"]].max(axis=1)
    return [
        (str(r.mastamp), int(r.no), r.instal.date(), r.ousrdata.date(),
         r.entrada.date(), _txt(r.marca), _txt(r.u_areaneg))
        for r in d.itertuples()
    ]


def _txt(v) -> str | None:
    return str(v).strip() if pd.notna(v) else None


def _chave(nome) -> str:
    """Nome reduzido a letras e algarismos, sem acentos, para comparação."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


class Clientes:
    """Tradução de nome para número de cliente.

    O registo de negócios guarda o nome do cliente, por vezes truncado, e não o
    número. A correspondência exacta resolve pouco mais de um décimo dos casos,
    pelo que se aceita também um prefixo que identifique um só cliente. Um
    prefixo ambíguo fica por resolver, em vez de ser atribuído ao acaso.
    """

    def __init__(self, erp: Path):
        self._mapa: dict[str, int] = {}
        for f, cn, cno in (
            (VISITAS, "nome", "no"),
            (FATURAS, "Nome Cliente", "Nº Cliente"),
        ):
            d = pd.read_excel(mais_recente(erp, f), usecols=[cn, cno]).dropna()
            for nome, no in zip(d[cn], d[cno]):
                self._mapa.setdefault(_chave(nome), int(no))
        self._chaves = sorted(self._mapa)

    def numero(self, nome) -> int | None:
        k = _chave(nome)
        if k in self._mapa:
            return self._mapa[k]
        candidatos = [c for c in self._chaves if c.startswith(k)]
        return self._mapa[candidatos[0]] if len(candidatos) == 1 else None


def negocios(erp: Path, registos: Path) -> list[tuple]:
    """Negócios de equipamento, produção e consumíveis, com identificador estável."""
    clientes = Clientes(erp)
    out, sem_numero = [], []

    eq = pd.read_excel(registos / REGISTOS["negocios_equip"], sheet_name="Negocios")
    for i, r in eq.iterrows():
        no = clientes.numero(r["cliente"])
        if no is None:
            sem_numero.append(str(r["cliente"]))
            continue
        if no == EMPRESA:
            continue
        tipo = "equipamento" if str(r["tipo"]).lower().startswith("equip") else "producao"
        out.append((
            f"NG-E{i:04d}", no, str(r["cliente"]).strip(), tipo,
            _txt(r["unidades"]), None,
            r["inicio"].date() if pd.notna(r["inicio"]) else None,
            r["fim"].date() if pd.notna(r["fim"]) else None,
            None, None,
            float(r["valor_faturado_eur"]) if pd.notna(r["valor_faturado_eur"]) else None,
        ))

    # Um negócio de consumíveis por CLIENTE, não por referência. Um comentário
    # genérico sobre material dá um par e não um por referência aberta, e é a
    # mesma agregação com que o §4.5 fixou o alerta de consumíveis.
    cs = pd.read_excel(registos / REGISTOS["negocios_cons"], sheet_name="Consumiveis")
    for r in cs.itertuples():
        if int(r.cliente) == EMPRESA:
            continue
        out.append((
            f"NG-C{int(r.cliente):05d}", int(r.cliente), None, "consumiveis",
            None, "fornecimento recorrente",
            pd.to_datetime(r.primeira).date(), None,
            None, _txt(r.estado_relacao),
            float(r.valor_total_eur) if pd.notna(r.valor_total_eur) else None,
        ))

    if sem_numero:
        print(f"{len(sem_numero)} negócios sem número de cliente resolvível, ignorados:")
        for n in sorted(set(sem_numero)):
            print("   ", n)
    return out


SQL_PARQUE = """
INSERT INTO parque_equipamentos (mastamp, cliente_no, instal, criado_em, entrada, marca, area)
VALUES %s
ON CONFLICT (mastamp) DO UPDATE SET
    cliente_no = EXCLUDED.cliente_no, entrada = EXCLUDED.entrada,
    marca = EXCLUDED.marca, area = EXCLUDED.area
"""

SQL_NEGOCIOS = """
INSERT INTO negocios (negocio_id, cliente_no, cliente, tipo, descricao, referencia,
                      inicio, fim, estado_actual, estado_relacao, valor)
VALUES %s
ON CONFLICT (negocio_id) DO UPDATE SET
    estado_relacao = EXCLUDED.estado_relacao, valor = EXCLUDED.valor,
    fim = EXCLUDED.fim
"""


def _gravar(ligacao, conn, eqs, negs) -> None:
    with conn.cursor() as cur:
        ligacao.em_bloco(cur, SQL_PARQUE, eqs, 200)
        ligacao.em_bloco(cur, SQL_NEGOCIOS, negs, 200)
    conn.commit()


SQL_CONSUMO = """
INSERT INTO negocios (negocio_id, cliente_no, cliente, tipo, referencia, inicio, estado_relacao, valor,
                      ultima_compra, intervalo_compra, valor_12m)
VALUES %s
ON CONFLICT (negocio_id) DO UPDATE SET
    estado_relacao = EXCLUDED.estado_relacao, valor = EXCLUDED.valor,
    ultima_compra = EXCLUDED.ultima_compra, intervalo_compra = EXCLUDED.intervalo_compra,
    valor_12m = EXCLUDED.valor_12m,
    cliente = coalesce(negocios.cliente, EXCLUDED.cliente)
"""


def atualizar(ligacao, equipamentos: Path, faturas: pd.DataFrame, hoje=None) -> tuple[int, int]:
    """Carga do ciclo noturno: parque de equipamentos e relação de consumíveis.

    Os negócios de equipamento e produção já não se carregam daqui: nascem da
    classificação (registo por episódios em contexto.py, e NOVO do modelo).
    """
    from datetime import date
    eqs = parque(Path(equipamentos).parent, equipamentos)
    p = ligacao.executar(parametros.ler)
    cons = consumiveis.estados(faturas, hoje or date.today(), p["k_risco"], p["k_dormente"])
    linhas = [(f"NG-C{c['cliente_no']:05d}", c["cliente_no"], c["cliente"], "consumiveis",
               "fornecimento recorrente", c["primeira"], c["estado"], c["valor"],
               c["ultima"], c["intervalo"], c["valor_12m"]) for c in cons]

    def gravar(conn):
        with conn.cursor() as cur:
            ligacao.em_bloco(cur, SQL_PARQUE, eqs, 200)
            ligacao.em_bloco(cur, SQL_CONSUMO, linhas, 200)
        conn.commit()
    ligacao.executar(gravar)
    return len(eqs), len(linhas)


def passo_ciclo(ligacao, equipamentos: Path, faturas: pd.DataFrame, falar) -> None:
    """Passo 2 do ciclo: parque de equipamentos e estado da relação de consumíveis."""
    n_eq, n_cons = atualizar(ligacao, equipamentos, faturas)
    falar(f"carga: {n_eq} equipamentos no parque · {n_cons} clientes de consumíveis")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--erp", type=Path, required=True,
                    help="pasta das extrações do ERP")
    ap.add_argument("--registos", type=Path, required=True,
                    help="pasta dos registos de negócios")
    args = ap.parse_args()

    eqs, negs = parque(args.erp), negocios(args.erp, args.registos)
    print(f"{len(eqs)} equipamentos · {len(negs)} negócios")

    ligacao = db.Ligacao()
    try:
        ligacao.executar(lambda c: _gravar(ligacao, c, eqs, negs))
    finally:
        ligacao.fechar()

    print("carregado")


if __name__ == "__main__":
    main()
