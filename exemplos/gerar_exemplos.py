"""Gera extrações fictícias do ERP para experimentar o sistema sem dados reais.

    python gerar_exemplos.py            escreve os ficheiros nesta pasta

Os ficheiros têm as colunas que o código lê das extrações reais (visitas, linhas de
fatura, equipamentos e dossiers) e os dois registos da carga inicial. Clientes,
comerciais, marcas e textos são inventados; as datas contam-se a partir de hoje, para
que o ciclo encontre extrações do dia e dossiers recentes. A semente é fixa: o mesmo
dia dá sempre os mesmos ficheiros.
"""

import random
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

AQUI = Path(__file__).resolve().parent
HOJE = date.today()
rnd = random.Random(42)

COMERCIAIS = ["AV-Ana", "AV-Bruno", "AV-Carla"]
CLIENTES = [(1000 + i, nome) for i, nome in enumerate([
    "INDÚSTRIAS ALFA, LDA.", "OFICINA EXEMPLO, LDA.", "ESTÚDIO XPTO, LDA.", "FÁBRICA SUL, LDA.",
    "METALÚRGICA BETA, LDA.", "COMPONENTES NORTE, S.A.", "TÉCNICA DELTA, LDA.", "MOLDES GAMA, LDA.",
    "SERVIÇOS ÓMEGA, LDA.", "INDUSTRIAL ÉPSILON, S.A.", "OFICINAS ZETA, LDA.", "PROJETOS SIGMA, LDA."], start=1)]
DONO = {no: COMERCIAIS[i % len(COMERCIAIS)] for i, (no, _) in enumerate(CLIENTES)}
MARCAS = ["TARVO", "VELDA", "LUMEN", "KORAL", "NOVARA", "SOLMA"]
AREAS = ["AREA A", "AREA A", "AREA A", "AREA B", "AREA C", "AREA D"]

RELATOS = {
    "equipamento": [
        "Apresentei a {m} ao Sr. {p}. Mostrou interesse, quer ver uma demonstração.",
        "Enviei a proposta da máquina {m}; o Sr. {p} vai analisar com a direção.",
        "O Sr. {p} pediu desconto na proposta da {m} e um prazo de entrega mais curto.",
        "A {m} foi aprovada pela administração, aguardam o financiamento.",
        "Confirmaram a encomenda da {m}. Instalação prevista para o próximo mês.",
        "Sem novidades da proposta da {m}; o Sr. {p} diz que este ano não há verba.",
    ],
    "producao": [
        "Pediram orçamento para produzirmos 50 peças por medida.",
        "Enviei o orçamento das peças; o Sr. {p} vai decidir esta semana.",
        "As peças estão em produção e seguem na sexta.",
        "Peças entregues; o cliente ficou satisfeito com o acabamento.",
    ],
    "consumiveis": [
        "Encomendou componentes {m} e cola para o mês.",
        "Visita de rotina; o stock de materiais está bem, volta a encomendar em breve.",
        "Queixou-se do prazo de entrega dos materiais {m}.",
        "Está a comprar os materiais a outro fornecedor por causa do preço.",
    ],
    "lead": [
        "Primeiro contacto com o Sr. {p}; apresentei a empresa e as nossas áreas.",
        "Convidei o Sr. {p} para a feira do próximo mês.",
    ],
    "nada": ["Visita de cortesia, sem assuntos.", "Telefonei mas não atenderam."],
}
CLASSIF = {"equipamento": "EQUIPAMENTOS", "producao": "SERVIÇO", "consumiveis": "CONSUMIVEIS",
           "lead": "", "nada": ""}
PESSOAS = ["Rui", "Mário", "Jorge", "Carlos", "Paulo", "Nuno", "Luís", "Pedro"]


def dia(antes: int) -> date:
    return HOJE - timedelta(days=antes)


def visitas() -> pd.DataFrame:
    linhas = []
    for no, nome in CLIENTES:
        tipo_cliente = rnd.choice(["equipamento", "producao", "consumiveis", "equipamento"])
        antes = rnd.randint(300, 600)
        passo = 0
        while antes > 0:
            tipo = rnd.choice([tipo_cliente, tipo_cliente, "consumiveis", "lead", "nada"])
            lista = RELATOS[tipo]
            texto = (lista[min(passo, len(lista) - 1)] if tipo == tipo_cliente else rnd.choice(lista))
            texto = texto.format(m=rnd.choice(MARCAS).title(), p=rnd.choice(PESSOAS))
            d = dia(antes)
            linhas.append({
                "vistamp": f"{rnd.getrandbits(88):022x}",
                "no": no, "nome": nome, "data": pd.Timestamp(d), "hora": f"{rnd.randint(9, 17):02d}:00",
                "vendnm": DONO[no], "duracao": rnd.choice([30, 45, 60, 90]),
                "ctipo": rnd.choice(["Visita", "Telefonema", "Reunião"]),
                "u_anegocio": rnd.choice(AREAS) if tipo != "producao" else "AREA C",
                "u_classif": CLASSIF[tipo], "resumo": texto.split(";")[0][:60], "rel": texto})
            if tipo == tipo_cliente:
                passo += 1
            antes -= rnd.randint(15, 70)
        d = dia(1)                                   # um relatório recente por cliente
        linhas.append({**linhas[-1], "vistamp": f"{rnd.getrandbits(88):022x}",
                       "data": pd.Timestamp(d)})
    return pd.DataFrame(linhas)


def faturas() -> pd.DataFrame:
    linhas, n = [], 5000
    for no, nome in CLIENTES:
        intervalo = rnd.choice([20, 30, 45, 60])
        silencio = rnd.choice([5, 10, 40, 90, 200])   # há clientes em risco e dormentes
        d = dia(silencio)
        while d > dia(650):
            n += 1
            for _ in range(rnd.randint(1, 3)):
                linhas.append({"Nº Fatura": n, "Tipo Documento": "Factura", "Data do Documento": pd.Timestamp(d),
                               "Nº Cliente": no, "Nome Cliente": nome, "Familia": "CONSUMIVEIS",
                               "Área de Negócio": "AREA A", "Marca": rnd.choice(MARCAS),
                               "dt1": rnd.choice(["Componentes", "Cola", "Materiais"]),
                               "Preço Venda Total F (€)": round(rnd.uniform(40, 900), 2)})
            d -= timedelta(days=max(3, int(rnd.gauss(intervalo, intervalo / 4))))
        if rnd.random() < 0.3:                       # algumas vendas de equipamento
            n += 1
            linhas.append({"Nº Fatura": n, "Tipo Documento": "Factura", "Data do Documento": pd.Timestamp(dia(rnd.randint(20, 400))),
                           "Nº Cliente": no, "Nome Cliente": nome, "Familia": "EQUIPAMENTOS",
                           "Área de Negócio": "AREA A", "Marca": rnd.choice(MARCAS), "dt1": "Máquina",
                           "Preço Venda Total F (€)": round(rnd.uniform(8000, 60000), 2)})
    return pd.DataFrame(linhas)


def equipamentos() -> pd.DataFrame:
    linhas = []
    for no, _ in CLIENTES:
        for k in range(rnd.randint(0, 4)):
            inst = dia(rnd.randint(100, 4000))
            linhas.append({"mastamp": f"EQ{no}{k:03d}".ljust(22, "0"), "no": no, "instal": pd.Timestamp(inst),
                           "ousrdata": pd.Timestamp(inst + timedelta(days=rnd.randint(0, 30))),
                           "marca": rnd.choice(MARCAS), "u_areaneg": rnd.choice(AREAS)})
    return pd.DataFrame(linhas)


def dossiers() -> pd.DataFrame:
    linhas, numero = [], 202600000
    for no, nome in rnd.sample(CLIENTES, 6):
        numero += 1
        tipo_doc = rnd.choice(["Proposta", "Fatura Proforma", "Encomenda de Cliente"])
        cat, area = rnd.choice([("EQUIPAMENTOS", "AREA A"), ("SERVIÇO", "AREA C")])
        for _ in range(rnd.randint(1, 3)):
            linhas.append({"Tipo Dossier": tipo_doc, "Nº Dossier": numero, "Nº Cliente": no, "Nome Cliente": nome,
                           "Data abertura Dossier": pd.Timestamp(dia(rnd.randint(2, 50))),
                           "Categoria": cat, "Área Negócio Artigo": area, "Nome Vendedor": DONO[no],
                           "Preço Artigo": round(rnd.uniform(500, 20000), 2)})
    return pd.DataFrame(linhas)


def registos(v: pd.DataFrame, f: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Os dois registos da carga inicial, derivados das extrações fictícias."""
    neg = []
    for (no, tipo), g in v[v["u_classif"].isin(["EQUIPAMENTOS", "SERVIÇO"])].groupby(["no", "u_classif"]):
        neg.append({"cliente": g["nome"].iloc[0], "tipo": "equipamento" if tipo == "EQUIPAMENTOS" else "producao",
                    "unidades": g["u_anegocio"].iloc[0], "inicio": g["data"].min(), "fim": g["data"].max(),
                    "valor_faturado_eur": None})
    cons = (f.groupby("Nº Cliente").agg(primeira=("Data do Documento", "min"),
                                        valor_total_eur=("Preço Venda Total F (€)", "sum"))
             .reset_index().rename(columns={"Nº Cliente": "cliente"}))
    cons["estado_relacao"] = None
    return pd.DataFrame(neg), cons


def main() -> None:
    carimbo = datetime.combine(HOJE, datetime.min.time()).replace(hour=1).strftime("%Y-%m-%dT%H_%M_%SZ")
    for velho in AQUI.glob("*.xlsx"):
        velho.unlink()
    v, f = visitas(), faturas()
    v.to_excel(AQUI / f"visitas_{carimbo}.xlsx", index=False)
    f.to_excel(AQUI / f"linhas_faturas_{carimbo}.xlsx", index=False)
    equipamentos().to_excel(AQUI / f"equipamentos_{carimbo}.xlsx", index=False)
    dossiers().to_excel(AQUI / f"dossiers_{carimbo}.xlsx", index=False)
    neg, cons = registos(v, f)
    with pd.ExcelWriter(AQUI / "260830_Negocios_Equip_Producao_v1.xlsx") as w:
        neg.to_excel(w, sheet_name="Negocios", index=False)
    with pd.ExcelWriter(AQUI / "260916_Consumiveis_por_Cliente_v4.xlsx") as w:
        cons.to_excel(w, sheet_name="Consumiveis", index=False)
    print(f"{len(v)} relatórios · {len(f)} linhas de fatura · {len(CLIENTES)} clientes · em {AQUI}")


if __name__ == "__main__":
    main()
