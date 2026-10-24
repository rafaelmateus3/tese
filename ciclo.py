"""Ciclo noturno do sistema (RF2.7). Corre sozinho, uma vez por noite.

    python ciclo.py                 o ciclo completo
    python ciclo.py --sem-modelo    tudo menos a classificação (ensaio rápido)
    python ciclo.py --sem-espera    não espera pela exportação do dia (correr à mão)

Passos, por esta ordem (cada um vive no módulo indicado):
  1. extrações do ERP: a mais recente de cada, na pasta ERP_PASTA; espera até 20 min
     pela exportação do dia, que corre à mesma hora (classificador/extracoes.py)
  2. parque de equipamentos e estado da relação de consumíveis (carga/carga.py)
  3. classificação dos relatórios novos, por ordem de data (classificador/run.py)
  4. dossiers do PHC: valor, fase, contacto e comercial dos negócios, abertura de
     negócios novos e unificação (carga/dossiers.py); fecho como ganho dos negócios
     adjudicados já faturados (dashboard/fechos.py) e fecho automático dos negócios
     sem contacto há mais de `dias_fecho`, RF2.8 (dashboard/alertas.py)
  5. alertas novos do dia, com o teto semanal, RF2.3 a RF2.5 (dashboard/alertas.py)

Cada ciclo fica registado na tabela `ciclos` e num ficheiro em logs/. Se um
passo falhar, o ciclo fica marcado como falhado e o dashboard mostra-o; os
passos seguintes não correm sobre dados a meio. A exceção é a classificação:
uma falha do modelo fica registada, mas os passos 4 e 5 correm sobre o que já
estava classificado.
"""

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
for sub in ("classificador", "dashboard", "carga"):
    sys.path.insert(0, str(AQUI / sub))

import alertas      # noqa: E402
import carga        # noqa: E402
import db           # noqa: E402
import dossiers     # noqa: E402
import extracoes    # noqa: E402
import fechos       # noqa: E402
import producao     # noqa: E402
import run          # noqa: E402
from config import ERP_PASTA  # noqa: E402

LOGS = AQUI / "logs"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-modelo", action="store_true")
    ap.add_argument("--sem-espera", action="store_true")
    a = ap.parse_args()

    LOGS.mkdir(exist_ok=True)
    registo = open(LOGS / f"ciclo_{datetime.now():%Y%m%d_%H%M}.log", "w", encoding="utf-8")

    def falar(texto):
        linha = f"{datetime.now():%H:%M:%S} {texto}"
        print(linha, flush=True)
        registo.write(linha + "\n")
        registo.flush()

    L = db.Ligacao()
    ciclo_id = L.executar(_abrir_ciclo)
    t = {"relatorios": 0, "pares": 0, "erros": 0}
    falha_modelo = None
    fechados = emitidos = 0
    visitas_f = None
    try:
        visitas_f, faturas_f, equip_f = extracoes.do_dia(falar, ERP_PASTA, esperar=not a.sem_espera)
        visitas = producao.ler_visitas(visitas_f)
        faturas = producao.ler_faturas(faturas_f)

        carga.passo_ciclo(L, equip_f, faturas, falar)
        if not a.sem_modelo:
            t, falha_modelo = run.passo_ciclo(L, visitas, faturas, falar)
        dossiers.passo_ciclo(L, ERP_PASTA, faturas, falar)
        fechos.passo_ciclo(L, faturas, falar)
        fechados, emitidos = alertas.passo_ciclo(L, falar)

        if falha_modelo:
            ok, msg = False, falha_modelo
        else:
            ok, msg = True, "ok" if not t["erros"] else f"{t['erros']} relatórios com erro do modelo"
    except BaseException as e:            # noqa: BLE001 — o ciclo regista tudo
        ok, msg = False, f"{type(e).__name__}: {e}"
        falar("FALHOU: " + msg)
        registo.write(traceback.format_exc())
    finally:
        L.executar(lambda c: _fechar_ciclo(c, ciclo_id, ok, t, fechados, emitidos,
                                           visitas_f.name if visitas_f else None, msg))
        L.fechar()
        registo.close()
    sys.exit(0 if ok else 1)


def _abrir_ciclo(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO ciclos DEFAULT VALUES RETURNING id")
        i = cur.fetchone()[0]
    conn.commit()
    return i


def _fechar_ciclo(conn, i, ok, t, fechados, alertas_n, visitas, msg):
    with conn.cursor() as cur:
        cur.execute("""UPDATE ciclos SET fim = now(), ok = %s, relatorios = %s, pares = %s,
                              erros = %s, fechados = %s, alertas = %s, visitas = %s, mensagem = %s
                        WHERE id = %s""",
                    (ok, t["relatorios"], t["pares"], t["erros"], fechados, alertas_n,
                     visitas, msg[:500], i))
    conn.commit()


if __name__ == "__main__":
    main()
