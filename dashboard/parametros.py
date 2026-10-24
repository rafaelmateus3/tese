"""RNF3: os limiares vivem na tabela `parametros`, não no código.

O valor por omissão fica aqui só para o caso de a tabela ainda não existir; o
que vale é o da base de dados, alterável no dashboard pelo gestor.
"""

OMISSAO = {"dias_negociacao": 14, "dias_mesmo_estado": 30, "dias_sem_contacto": 90,
           "dias_base_sem_contacto": 90, "dias_fecho": 180, "teto_semanal": 10, "teto_atraso": 15, "dia_notificacao": 5,
           "k_risco": 1.59, "k_dormente": 3.47, "anos_renovacao": 5}

# Limites de bom senso: um erro de digitação não pode desligar os alertas.
LIMITES = {"dias_negociacao": (1, 365), "dias_mesmo_estado": (1, 365),
           "dias_sem_contacto": (1, 730), "dias_base_sem_contacto": (1, 730), "dias_fecho": (30, 1095),
           "teto_semanal": (1, 100), "teto_atraso": (1, 100), "dia_notificacao": (0, 7), "k_risco": (1, 10), "k_dormente": (1, 20),
          "anos_renovacao": (3, 30)}


def ler(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT chave, valor FROM parametros")
        lidos = {k: float(v) for k, v in cur.fetchall()}
    out = {**OMISSAO, **lidos}
    return {k: (int(v) if k not in ("k_risco", "k_dormente") else v) for k, v in out.items()}


def listar(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute("SELECT chave, valor, descricao, origem, alterado_em, alterado_por "
                    "FROM parametros ORDER BY chave")
        return [{"chave": k, "valor": float(v), "descricao": d, "origem": o,
                 "alterado_em": str(e)[:16], "alterado_por": p,
                 "minimo": LIMITES[k][0], "maximo": LIMITES[k][1]}
                for k, v, d, o, e, p in cur.fetchall() if k in LIMITES]


def alterar(conn, chave: str, valor: float, por: str) -> None:
    if chave not in LIMITES:
        raise ValueError(f"parâmetro desconhecido: {chave}")
    lo, hi = LIMITES[chave]
    if not lo <= valor <= hi:
        raise ValueError(f"{chave} tem de estar entre {lo} e {hi}")
    atual = ler(conn)
    novo = {**atual, chave: valor}
    if novo["k_dormente"] <= novo["k_risco"]:
        raise ValueError("k_dormente tem de ser maior do que k_risco")
    if not novo["dias_negociacao"] <= novo["dias_mesmo_estado"] <= novo["dias_sem_contacto"] < novo["dias_fecho"]:
        raise ValueError("os dias têm de crescer: negociação ≤ mesmo estado ≤ sem contacto < fecho")
    with conn.cursor() as cur:
        cur.execute("UPDATE parametros SET valor = %s, alterado_em = now(), alterado_por = %s "
                    "WHERE chave = %s", (valor, por, chave))
    conn.commit()
