"""Classificação dos relatórios de visita em produção.

    python run.py                          o que falta, das extrações mais recentes
    python run.py --desde 2026-09-01       só relatórios a partir desta data
    python run.py --limite 20              pára ao fim de 20, para ensaiar
    python run.py --visitas V.xlsx --faturas F.xlsx

As extrações vêm da pasta ERP_PASTA do .env (visitas_*.xlsx e
linhas_faturas_*.xlsx; usa-se a mais recente de cada). O modelo, o backend e a
versão do prompt vêm do .env (MODELO, BACKEND, PROMPT_VERSION).

Os relatórios correm por ordem de data, porque cada um vê o último estado que os
anteriores deixaram (ver producao.py). Relatórios sem texto são ignorados.
"""

import argparse
import sys
import time
from datetime import date

import pandas as pd

import db
import producao
from config import BACKEND, ERP_PASTA, MODELO, PAUSA_SEG, PROMPT_VERSION
from extracoes import FATURAS, VISITAS, mais_recente
from llm import BACKENDS, classificar_mensagem, garantir_modelo, negocios_abertos


def _para_gravar(linha: dict) -> dict:
    """Campos do relatório com os nomes que a base de dados usa."""
    def txt(k):
        v = linha.get(k)
        return str(v).strip() if pd.notna(v) and str(v).strip() else None
    return {"vistamp": str(linha["vistamp"]).strip(), "data": str(linha["data"]),
            "hora": txt("hora"), "vendedor": txt("vendnm"), "cliente": txt("nome"),
            "cliente_no": int(linha["no"]), "unidade": txt("u_anegocio"),
            "classificacao": txt("u_classif"), "tipo_contacto": txt("ctipo"),
            "duracao": int(linha["duracao"]) if pd.notna(linha.get("duracao")) else None,
            "resumo": txt("resumo"), "relatorio": txt("rel")}


def processar(ligacao, visitas: pd.DataFrame, faturas: pd.DataFrame, *,
              prompt: str = PROMPT_VERSION, modelo: str = MODELO,
              backend: str = BACKEND, desde: date | None = None,
              limite: int | None = None, tudo: bool = False, apenas: set | None = None,
              falar=print) -> dict:
    """Classifica o que falta e devolve os totais da corrida.

    `apenas` restringe a estes vistamp (o resto da extração continua a servir de
    contexto: relatórios anteriores e registo)."""
    feitos = set() if tudo else ligacao.executar(lambda c: db.ja_classificados(c, prompt))
    fila = producao.pendentes(visitas, {f.strip() for f in feitos}, desde)
    if apenas is not None:
        fila = fila[fila["vistamp"].astype(str).str.strip().isin(apenas)]
    if limite:
        fila = fila.head(limite)
    entrada = producao.Entrada(visitas, faturas, ligacao.executar(producao.ler_registo))
    falar(f"{len(fila)} relatórios por classificar · prompt {prompt} · {modelo} · {backend}")

    t = {"relatorios": 0, "pares": 0, "erros": 0, "fundidos": 0,
         "tokens_in": 0, "tokens_out": 0}
    for r in fila.itertuples():
        linha = entrada.linha(r)
        rel = _para_gravar(linha)
        negs = entrada.registo(linha)
        ligacao.executar(lambda c: producao.garantir_registo(c, negs, rel["cliente_no"], rel["cliente"]))
        ants = ligacao.executar(lambda c: producao.anteriores(c, rel["cliente_no"], linha["data"]))
        t["fundidos"] += ligacao.executar(lambda c: producao.fundir(c, negs, ants))
        mensagem = entrada.mensagem(linha, negs, ants)
        res = classificar_mensagem(mensagem, prompt, modelo, backend)
        pares = [] if res["erro"] else ligacao.executar(lambda c: producao.resolver_pares(
            c, rel, res["pares"], negocios_abertos(mensagem)))
        ligacao.executar(lambda c: db.gravar(c, rel, res, pares))

        t["relatorios"] += 1
        t["pares"] += len(pares)
        t["erros"] += 1 if res["erro"] else 0
        t["tokens_in"] += res["tokens_in"] or 0
        t["tokens_out"] += res["tokens_out"] or 0
        marca = f"ERRO {res['erro']}" if res["erro"] else f"{len(pares)} par(es)"
        falar(f"  [{t['relatorios']}/{len(fila)}] {rel['data']} {str(rel['cliente'])[:34]:<34} {marca}")
        if backend != "ollama":
            time.sleep(PAUSA_SEG)
    return t


def passo_ciclo(ligacao, visitas: pd.DataFrame, faturas: pd.DataFrame, falar) -> tuple[dict, str | None]:
    """Passo 3 do ciclo: classifica os relatórios novos e devolve (totais, falha).

    Uma falha do modelo não pára o ciclo: os alertas e o fecho correm sobre o que
    já está classificado, e a falha volta para o ciclo a registar.
    """
    t = {"relatorios": 0, "pares": 0, "erros": 0}
    try:
        garantir_modelo(MODELO, BACKEND, PROMPT_VERSION, falar)
        t = processar(ligacao, visitas, faturas, falar=falar)
        falar(f"classificação: {t['relatorios']} relatórios · {t['pares']} pares · {t['erros']} erros")
        return t, None
    except Exception as e:     # noqa: BLE001
        falha = f"classificação falhou: {type(e).__name__}: {e}"
        falar(falha)
        return t, falha


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--visitas")
    ap.add_argument("--faturas")
    ap.add_argument("--desde", type=date.fromisoformat)
    ap.add_argument("--limite", type=int)
    ap.add_argument("--tudo", action="store_true", help="reprocessar também o que já existe")
    ap.add_argument("--prompt", default=PROMPT_VERSION)
    ap.add_argument("--modelo", default=MODELO)
    ap.add_argument("--backend", default=BACKEND, choices=sorted(BACKENDS))
    a = ap.parse_args()

    try:
        visitas = producao.ler_visitas(a.visitas or mais_recente(ERP_PASTA, VISITAS))
        faturas = producao.ler_faturas(a.faturas or mais_recente(ERP_PASTA, FATURAS))
    except FileNotFoundError as e:
        sys.exit(str(e))
    ligacao = db.Ligacao()
    try:
        t = processar(ligacao, visitas, faturas, prompt=a.prompt, modelo=a.modelo,
                      backend=a.backend, desde=a.desde, limite=a.limite, tudo=a.tudo)
    finally:
        ligacao.fechar()
    print(f"\n{t['relatorios']} processados · {t['pares']} pares · {t['erros']} erros · "
          f"{t['fundidos']} negócios fundidos")


if __name__ == "__main__":
    main()
