"""Os dossiers do PHC e os negócios (decisões de 15-Out-2026).

Os relatórios de visita quase nunca dizem quanto vale um negócio, nem quando a proposta
saiu ou a encomenda entrou. Os dossiers do PHC (exportação do Metabase, modelo 150,
`dossiers_*.xlsx`, uma linha por artigo) têm isso. Aqui ligam-se aos negócios e
passam a contar de quatro formas, todas com a razão declarada (eventos_dossier.razao):

  Valor   o do dossier mais recente ligado ao negócio (soma das linhas do tipo).
  Fase    cada dossier implica uma fase; o negócio avança, nunca recua (a vista
          `carteira` fica com a mais avançada entre o relatório e os dossiers).
  Contacto  um dossier conta como contacto se vier pelo menos 7 dias depois do
          relatório anterior do negócio.
  Comercial o negócio passa para o comercial do registo mais recente, relatório ou
          dossier (só vendedores que escrevem relatórios; AD-Directo e afins não).

E dois de estrutura:

  Abrir   um dossier recente (60 dias) de equipamento ou produção para um cliente sem
          negócio aberto desse tipo abre um negócio NG-D, a menos que já haja fatura do
          tipo depois dele (a venda está feita) ou um negócio do tipo fechado depois dele.
  Unificar  um NG-D junta-se ao negócio aberto do mesmo cliente e tipo que os relatórios
          tenham entretanto aberto (o NG-D nasceu só porque ainda não havia relatório).

Regra de ligação negócio -> dossier: mesmo cliente; linhas do tipo do negócio
(equipamento = categorias EQUIPAMENTOS, SOLUÇÃO, SOFTWARE; produção = área AREA C,
e todo o dossier «Pedidos Produção»); dossier aberto entre 30 dias antes do início do
negócio e hoje; cada dossier vale para um só negócio, o de contacto mais recente que o
admita. Limitação a declarar: a ligação é por cliente, tipo e data, não por referência.

Os NG-D não entram no registo dado ao classificador (producao.SQL_REGISTO): o regime de
classificação avaliado no Cap. 6 não muda.
"""

from datetime import date, timedelta

import pandas as pd

FASE = {
    "Proposta": "3. Proposta / Orçamento",
    "Fatura Proforma": "3. Proposta / Orçamento",
    "Encomenda de Cliente": "6. Encomenda Confirmada",
    "Pedidos Produção": "7. Em Produção / Entrega",
    "Guia de Transporte CL": "7. Em Produção / Entrega",
}
NOME = {"Proposta": "Proposta", "Fatura Proforma": "Fatura proforma",
        "Encomenda de Cliente": "Encomenda de cliente", "Pedidos Produção": "Pedido de produção",
        "Guia de Transporte CL": "Guia de transporte"}
SIGLA = {"Proposta": "P", "Fatura Proforma": "F", "Encomenda de Cliente": "E",
         "Pedidos Produção": "PP", "Guia de Transporte CL": "G"}
ABREM = {"Proposta", "Fatura Proforma", "Encomenda de Cliente", "Pedidos Produção"}
CATEGORIAS_EQUIPAMENTO = {"EQUIPAMENTOS", "SOLUÇÃO", "SOFTWARE"}
AREA_PRODUCAO = "AREA C"
MARGEM_ANTES = 30
DIAS_ABRIR = 60
DIAS_CONTACTO = 7
EMPRESA = 3504
FAMILIAS_FATURA = {"equipamento": {"EQUIPAMENTOS", "SOLUÇÃO", "SOFTWARE"}}


def ler(caminho) -> pd.DataFrame:
    """As linhas de dossier úteis, já com o tipo do negócio."""
    d = pd.read_excel(caminho)
    d.columns = [str(c).strip().strip('"') for c in d.columns]
    for c in ("Tipo Dossier", "Categoria", "Área Negócio Artigo", "Nome Vendedor", "Nome Cliente"):
        d[c] = d[c].astype("string").str.strip()
    d = d[d["Tipo Dossier"].isin(FASE.keys())].copy()
    d["tipo"] = None
    d.loc[d["Categoria"].isin(CATEGORIAS_EQUIPAMENTO), "tipo"] = "equipamento"
    d.loc[(d["Área Negócio Artigo"] == AREA_PRODUCAO) | (d["Tipo Dossier"] == "Pedidos Produção"), "tipo"] = "producao"
    d = d.dropna(subset=["tipo", "Nº Cliente", "Data abertura Dossier"])
    d = d[~d["Nº Cliente"].isin([0, EMPRESA])]
    d["dia"] = pd.to_datetime(d["Data abertura Dossier"]).dt.date
    return d


def _por_dossier(d: pd.DataFrame) -> pd.DataFrame:
    # A numeração do PHC é por tipo de dossier: o mesmo número repete-se entre tipos, pelo que
    # o documento é identificado pelo tipo e pelo número (corrigido a 19-Out-2026).
    return (d.groupby(["Tipo Dossier", "Nº Dossier", "Nº Cliente", "tipo"])
             .agg(valor=("Preço Artigo", "sum"),
                  dia=("dia", "min"), vendedor=("Nome Vendedor", lambda s: s.dropna().mode().iat[0] if s.notna().any() else None),
                  cliente=("Nome Cliente", "first"),
                  area=("Área Negócio Artigo", lambda s: s[s.fillna("") != ""].mode().iat[0]
                        if (s.fillna("") != "").any() else None))
             .reset_index()
             .rename(columns={"Tipo Dossier": "tipo_dossier", "Nº Dossier": "numero", "Nº Cliente": "cliente_no"}))


def _razao(r) -> str:
    return f"{NOME[r.tipo_dossier]} nº {int(r.numero)} de {r.dia:%d/%m/%Y} no PHC"


def _faturado_depois(faturas, cliente_no: int, tipo: str, dia: date) -> bool:
    if faturas is None:
        return False
    f = faturas[(faturas["Nº Cliente"] == cliente_no)
                & faturas["Tipo Documento"].isin(["Factura", "Fatura Recibo"])
                & (faturas["Preço Venda Total F (€)"] > 0)]
    if tipo == "equipamento":
        f = f[f["Familia"].fillna("").astype(str).str.strip().isin(FAMILIAS_FATURA["equipamento"])]
    else:
        f = f[f["Área de Negócio"].fillna("").astype(str).str.strip() == AREA_PRODUCAO]
    return bool((pd.to_datetime(f["Data do Documento"]).dt.date >= dia).any())


SQL_ABERTOS = """
SELECT negocio_id, cliente_no, tipo, inicio, ultimo_toque
  FROM carteira
 WHERE fechado_em IS NULL AND tipo IN ('equipamento', 'producao')
   AND (estado IS NULL OR estado NOT IN ('8. Fechado', '9. Perdido / Cancelado'))
"""

# Datas dos relatórios de cada negócio (para a regra do contacto).
SQL_RELATORIOS = """
SELECT coalesce(x.fundido_em, p.negocio_id), c.data_visita::date
  FROM pares_efetivos p
  JOIN classificacoes_llm c ON c.vistamp = p.vistamp
  LEFT JOIN negocios x ON x.negocio_id = p.negocio_id
 WHERE c.data_visita IS NOT NULL
"""

SQL_FECHADOS = """
SELECT cliente_no, tipo, max(fechado_em) FROM negocios
 WHERE fechado_em IS NOT NULL AND tipo IN ('equipamento', 'producao') GROUP BY 1, 2
"""


def atualizar(conn, dossiers: pd.DataFrame, hoje: date | None = None, faturas=None) -> dict:
    """Recalcula valor, eventos (fase, contacto, comercial), abre NG-D e unifica."""
    hoje = hoje or date.today()
    pd_ = _por_dossier(dossiers)
    pd_ = pd_[(pd_["valor"] > 0) & (pd_["dia"] <= hoje)]
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT vendedor FROM classificacoes_llm WHERE vendedor IS NOT NULL")
        comerciais = {v for (v,) in cur.fetchall()}

        # 1. Unificar: um NG-D aberto junta-se ao negócio aberto do mesmo cliente e tipo
        #    que os relatórios tenham aberto.
        cur.execute(SQL_ABERTOS)
        abertos = cur.fetchall()
        unificados = 0
        for nid, cli, tipo, *_ in abertos:
            if not nid.startswith("NG-D"):
                continue
            alvo = [a for a in abertos if a[1] == cli and a[2] == tipo and not a[0].startswith("NG-D")]
            if alvo:
                destino = max(alvo, key=lambda a: a[4] or date.min)[0]
                cur.execute("""UPDATE negocios SET fundido_em = %s, fundido_por = 'dossier', fundido_data = %s
                                WHERE negocio_id = %s AND fundido_em IS NULL""", (destino, hoje, nid))
                unificados += 1
        if unificados:
            cur.execute(SQL_ABERTOS)
            abertos = cur.fetchall()

        cur.execute(SQL_RELATORIOS)
        rel: dict[str, list[date]] = {}
        for nid, d in cur.fetchall():
            rel.setdefault(nid, []).append(d)
        cur.execute(SQL_FECHADOS)
        fechados = {(c, t): d for c, t, d in cur.fetchall()}

        # 2. Ligar cada dossier a um negócio aberto.
        indice = {k: g.sort_values("dia") for k, g in pd_.groupby(["cliente_no", "tipo"])}
        usados: set = set()
        ligados: dict[str, list] = {}
        for nid, cli, tipo, inicio, ultimo in sorted(abertos, key=lambda n: n[4] or date.min, reverse=True):
            g = indice.get((int(cli), tipo)) if cli is not None else None
            if g is None:
                continue
            desde = (inicio or ultimo or hoje) - timedelta(days=MARGEM_ANTES)
            for r in g.itertuples():
                if (r.tipo_dossier, r.numero) not in usados and desde <= r.dia:
                    usados.add((r.tipo_dossier, r.numero))
                    ligados.setdefault(nid, []).append(r)

        # 3. Abrir NG-D com os dossiers recentes que sobram.
        abertos_ct = {(a[1], a[2]) for a in abertos}
        chave = list(zip(pd_["tipo_dossier"], pd_["numero"]))
        sobra = pd_[~pd.Series([k in usados for k in chave], index=pd_.index) & pd_["tipo_dossier"].isin(ABREM)
                    & (pd_["dia"] >= hoje - timedelta(days=DIAS_ABRIR))]
        novos = 0
        for (cli, tipo), g in sobra.groupby(["cliente_no", "tipo"]):
            cli = int(cli)
            if (cli, tipo) in abertos_ct:
                continue
            primeiro = g.sort_values("dia").iloc[0]
            fechado = fechados.get((cli, tipo))
            if fechado and fechado >= primeiro.dia:
                continue
            if _faturado_depois(faturas, cli, tipo, primeiro.dia):
                continue
            nid = f"NG-D{int(primeiro.numero)}"
            cur.execute("SELECT cliente_no, tipo FROM negocios WHERE negocio_id = %s", (nid,))
            ja = cur.fetchone()
            if (ja and (int(ja[0]), ja[1]) != (cli, tipo)) or nid in ligados:
                # o mesmo número noutro tipo de dossier já deu um NG-D a outro negócio
                nid = f"NG-D{int(primeiro.numero)}-{SIGLA[primeiro.tipo_dossier]}"
            cur.execute("""INSERT INTO negocios (negocio_id, cliente_no, cliente, tipo, descricao, inicio, criado_por)
                           VALUES (%s, %s, %s, %s, %s, %s, 'dossier')
                           ON CONFLICT (negocio_id) DO NOTHING""",
                        (nid, cli, primeiro.cliente, tipo, "Aberto pelo PHC: " + _razao(primeiro), primeiro.dia))
            ligados[nid] = list(g.sort_values("dia").itertuples())
            novos += 1

        # 4. Escrever: valor e eventos (fase, contacto, comercial), recalculados por inteiro.
        cur.execute("""UPDATE negocios SET valor_dossier = NULL, dossier_ref = NULL,
                              dossier_tipo = NULL, dossier_data = NULL
                        WHERE valor_dossier IS NOT NULL""")
        cur.execute("DELETE FROM eventos_dossier")
        n_ev = 0
        for nid, lista in ligados.items():
            ult = max(lista, key=lambda r: (r.dia, r.numero))
            cur.execute("""UPDATE negocios SET valor_dossier = %s, dossier_ref = %s,
                                  dossier_tipo = %s, dossier_data = %s WHERE negocio_id = %s""",
                        (round(float(ult.valor), 2), str(int(ult.numero)), ult.tipo_dossier, ult.dia, nid))
            datas = sorted(rel.get(nid, []))
            for r in lista:
                antes = [d for d in datas if d <= r.dia]
                contacto = not antes or (r.dia - antes[-1]).days >= DIAS_CONTACTO
                vend = r.vendedor if r.vendedor in comerciais else None
                cur.execute("""INSERT INTO eventos_dossier (negocio_id, dossier_ref, dossier_tipo, data,
                                   estado, vendedor, contacto, razao, area)
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                               ON CONFLICT (negocio_id, dossier_tipo, dossier_ref) DO NOTHING""",
                            (nid, str(int(r.numero)), r.tipo_dossier, r.dia, FASE[r.tipo_dossier],
                             vend, contacto, _razao(r), r.area))
                n_ev += 1
    conn.commit()
    return {"negocios": len(ligados), "eventos": n_ev, "abertos": novos, "unificados": unificados}


def passo_ciclo(ligacao, pasta, faturas, falar) -> dict | None:
    """Passo 4 do ciclo, depois da classificação (que pode abrir negócios novos).

    Usa a extração de dossiers mais recente da pasta do ERP. Sem ela, o ciclo segue
    sem valores novos.
    """
    from extracoes import DOSSIERS, idade_dias, mais_recente
    try:
        ficheiro = mais_recente(pasta, DOSSIERS)
    except FileNotFoundError:
        falar("AVISO: sem extração de dossiers; os valores dos negócios não foram atualizados")
        return None
    idade = idade_dias(ficheiro)
    n = ligacao.executar(lambda c: atualizar(c, ler(ficheiro), faturas=faturas))
    falar(f"dossiers ({ficheiro.name}): {n['negocios']} negócios com valor, "
          f"{n['eventos']} eventos, {n['abertos']} abertos, {n['unificados']} unificados"
          + (f" · AVISO: extração com {idade} dias" if idade > 2 else ""))
    return n
