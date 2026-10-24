"""Estado da relação de fornecimento por cliente, a partir das linhas de fatura.

É o método do §4.5 aplicado ao cliente:

  - contam as linhas de consumíveis e peças em faturas de venda;
  - linhas da mesma fatura, ou a dois dias ou menos, são uma compra;
  - com menos de três compras não há periodicidade: "0. Pontual";
  - intervalo típico = mediana dos intervalos entre compras;
  - rácio = dias desde a última compra / intervalo típico;
    acima de K_RISCO "2. Em risco", acima de K_DORMENTE "3. Dormente".

Os dois limiares vêm da tabela de parâmetros (RNF3).
"""

from datetime import date
from statistics import median

import pandas as pd

FAMILIAS = {"CONSUMIVEIS", "PEÇAS"}
DOCUMENTOS = {"Factura", "Fatura Recibo"}
MESMA_COMPRA = 2
MIN_COMPRAS = 3
EMPRESA = 3504


def estados(faturas: pd.DataFrame, hoje: date, k_risco: float, k_dormente: float) -> list[dict]:
    f = faturas[faturas["Familia"].isin(FAMILIAS) & faturas["Tipo Documento"].isin(DOCUMENTOS)]
    f = f.dropna(subset=["Data do Documento", "Nº Cliente"])
    f = f[f["Nº Cliente"] != EMPRESA]
    ev = (f.groupby(["Nº Cliente", "Nº Fatura"])
           .agg(data=("Data do Documento", "min"), valor=("Preço Venda Total F (€)", "sum"),
                nome=("Nome Cliente", "last"))
           .reset_index().sort_values("data"))
    out = []
    for cli, g in ev.groupby("Nº Cliente"):
        datas, valor = [], 0.0
        for d, v in zip(g["data"], g["valor"]):
            d = pd.Timestamp(d).date()
            valor += float(v or 0)
            if not datas or (d - datas[-1]).days > MESMA_COMPRA:
                datas.append(d)
        desde = (hoje - datas[-1]).days
        tipico = None
        if len(datas) < MIN_COMPRAS:
            estado = "0. Pontual"
        else:
            tipico = median((b - a).days for a, b in zip(datas, datas[1:]))
            racio = desde / tipico if tipico > 0 else 0
            estado = ("3. Dormente" if racio > k_dormente else
                      "2. Em risco" if racio > k_risco else "1. Activa")
        # O que o comercial lê no aviso: o ritmo habitual e quanto comprou no último ano.
        ano = sum(float(v or 0) for d, v in zip(g["data"], g["valor"])
                  if (hoje - pd.Timestamp(d).date()).days <= 365)
        out.append({"cliente_no": int(cli), "cliente": str(g["nome"].iloc[-1]).strip(),
                    "primeira": datas[0], "ultima": datas[-1],
                    "intervalo": int(round(tipico)) if tipico else None,
                    "valor_12m": round(ano, 2),
                    "valor": round(valor, 2), "estado": estado})
    return out
