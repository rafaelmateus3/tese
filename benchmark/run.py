"""Benchmark: corre um ou vários modelos sobre o conjunto de referência.

    python run.py --congelar visitas.xlsx gold.xlsx    prepara as entradas
    python run.py --ensaio --amostra amostra.json --fase 1 --modelos ...
    python run.py --modelos gemma4:e4b,granite4.2:8b   corrida completa
    python run.py --modelos claude-sonnet-5 --backend anthropic

A amostra das fases intermédias é lida de um ficheiro fixado antes de correr,
para que todos os modelos respondam aos mesmos relatórios e a escolha não possa
ser feita depois de ver os resultados.

Uma corrida interrompida retoma-se: cada resposta é gravada assim que existe, e
correr o mesmo modelo de novo continua de onde ficou em vez de recomeçar.

Antes de cada modelo faz-se uma classificação de aquecimento, descartada e
cronometrada à parte. Um modelo local paga na primeira chamada o carregamento
dos pesos, que não é débito do modelo mas apareceria como tal.

O ensaio existe para separar dois tipos de falha. Um modelo pode falhar por
configuração, por não caber em memória ou por não respeitar o formato, e isso
sabe-se com três relatórios. Descobri-lo ao fim de 375 é desperdiçar horas.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))

import db          # noqa: E402
import corrida     # noqa: E402
import entradas    # noqa: E402
import llm         # noqa: E402
from config import ENTRADA_VERSION, PROMPT_VERSION  # noqa: E402
from esquema import VERSAO as ESQUEMA_VERSAO  # noqa: E402


def _progresso(i, total, r):
    marca = f"ERRO  {r.erro[:70]}" if r.erro else f"{len(r.pares)} par(es)"
    print(f"    [{i}/{total}] {r.segundos:6.1f}s  {marca}")


def ensaiar(ligacao, modelos, backend, prompt, n, apenas=None):
    """Corre poucos relatórios por modelo e diz quais estão prontos.

    As respostas ficam gravadas, marcadas como ensaio, para que se possa ver o
    que cada modelo respondeu em vez de acreditar na contagem de erros. Nunca
    entram na pontuação: o denominador é pequeno de mais.
    """
    itens = ligacao.executar(
        lambda c: entradas.carregar(c, None if apenas else n, apenas))
    if not itens:
        sys.exit("não há entradas congeladas: correr primeiro com --congelar")

    marca = datetime.now().strftime("%y%m%d-%H%M")
    print(f"ensaio: {len(itens)} relatórios por modelo, "
          f"{len(modelos)} modelos\n")
    prontos, falhados = [], []
    for m in modelos:
        print(f"  {m}")
        cid = f"ENSAIO|{m}|{prompt}|{ESQUEMA_VERSAO}|{ENTRADA_VERSION}|{marca}"
        ligacao.executar(
            lambda c: corrida.abrir(c, cid, m, backend, prompt, "ensaio"))

        def guardar(i, total, resultado, _cid=cid):
            _progresso(i, total, resultado)
            ligacao.executar(
                lambda c: corrida.gravar_resposta(c, _cid, resultado))

        try:
            aquecimento = llm.preparar(m, backend, prompt)
            if aquecimento:
                print(f"    aquecimento {aquecimento:.1f}s (fora da medição)")
            t = time.perf_counter()
            res = corrida.executar(itens, prompt, m, backend, guardar)
        except Exception as e:                       # noqa: BLE001
            print(f"    indisponível: {e}\n")
            ligacao.executar(lambda c: corrida.fechar(c, cid, "ensaio"))
            falhados.append((m, str(e)[:120]))
            continue
        condicoes = llm.controlos_aplicados(m, backend)
        ligacao.executar(lambda c: corrida.fechar(c, cid, f"ensaio · {condicoes}"))
        erros = [r.erro for r in res if r.erro]
        seg = time.perf_counter() - t
        rpm = len(res) / seg * 60 if seg else 0
        print(f"    {len(res) - len(erros)}/{len(res)} sem erro · {rpm:.1f} resp/min"
              f"\n    {condicoes}\n")
        (prontos if not erros else falhados).append(
            (m, f"{len(erros)} erro(s): {erros[0][:90]}" if erros else f"{rpm:.1f} resp/min"))

    print("\nPRONTOS")
    for m, nota in prontos:
        print(f"  {m:<52} {nota}")
    print("\nCOM PROBLEMAS")
    for m, nota in falhados:
        print(f"  {m:<52} {nota}")
    print(f"\nrespostas gravadas como ensaio, marca {marca}")
    return prontos


def correr(ligacao, modelos, backend, prompt, limite, recomecar=False,
           apenas=None):
    itens = ligacao.executar(lambda c: entradas.carregar(c, limite, apenas))
    if not itens:
        sys.exit("não há entradas congeladas: correr primeiro com --congelar")

    marca = datetime.now().strftime("%y%m%d-%H%M")
    for m in modelos:
        cid = None if recomecar else ligacao.executar(
            lambda c: corrida.por_terminar(c, m, prompt))
        if cid:
            print(f"\n{cid}  ·  a retomar")
        else:
            cid = f"{m}|{prompt}|{ESQUEMA_VERSAO}|{ENTRADA_VERSION}|{marca}"
            ligacao.executar(lambda c: corrida.abrir(c, cid, m, backend, prompt))

        feitos = ligacao.executar(lambda c: corrida.ja_respondidos(c, cid))
        pendentes = [e for e in itens if e[0] not in feitos]
        print(f"{cid}  ·  {len(pendentes)} por responder de {len(itens)}")
        if not pendentes:
            ligacao.executar(lambda c: corrida.fechar(c, cid))
            continue


        aquecimento = llm.preparar(m, backend, prompt)
        if aquecimento:
            print(f"  aquecimento {aquecimento:.1f}s (fora da medição)")
        t = time.perf_counter()

        def guardar(i, total, r, _cid=cid):
            _progresso(i, total, r)
            ligacao.executar(lambda c: corrida.gravar_resposta(c, _cid, r))

        res = corrida.executar(pendentes, prompt, m, backend, guardar)
        seg = time.perf_counter() - t
        condicoes = llm.controlos_aplicados(m, backend)
        ligacao.executar(lambda c: corrida.fechar(c, cid, condicoes))
        erros = sum(1 for r in res if r.erro)
        print(f"  {len(res)} respostas · {erros} erros · {seg / 60:.1f} min "
              f"· {len(res) / seg * 60:.1f} resp/min\n  {condicoes}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--congelar", nargs=2, metavar=("VISITAS", "GOLD"))
    ap.add_argument("--modelos", help="lista separada por vírgulas")
    ap.add_argument("--backend", default="ollama", choices=["ollama", "anthropic", "openai"])
    ap.add_argument("--prompt", default=PROMPT_VERSION)
    ap.add_argument("--ensaio", action="store_true")
    ap.add_argument("--n", type=int, default=3, help="relatórios por modelo no ensaio")
    ap.add_argument("--amostra", type=Path,
                    help="ficheiro JSON com a amostra fixada por fases")
    ap.add_argument("--fase", type=int, choices=[1, 2],
                    help="qual conjunto do ficheiro de amostra correr")
    ap.add_argument("--limite", type=int, help="limitar a corrida completa")
    ap.add_argument("--recomecar", action="store_true",
                    help="ignorar uma corrida a meio e começar de novo")
    args = ap.parse_args()

    ligacao = db.Ligacao()
    try:
        if args.congelar:
            rel = entradas.ler_relatorios(*args.congelar)
            print(f"{entradas.congelar(ligacao, rel)} entradas congeladas")
            return
        if not args.modelos:
            sys.exit("indicar --modelos")
        modelos = [m.strip() for m in args.modelos.split(",") if m.strip()]
        apenas = None
        if args.amostra:
            if not args.fase:
                sys.exit("--amostra precisa de --fase")
            amostra = json.loads(args.amostra.read_text(encoding="utf-8"))
            apenas = amostra[f"fase{args.fase}"]
            print(f"amostra: fase {args.fase}, {len(apenas)} relatórios, "
                  f"semente {amostra.get('semente', '?')}")
        if args.ensaio:
            ensaiar(ligacao, modelos, args.backend, args.prompt, args.n, apenas)
        else:
            correr(ligacao, modelos, args.backend, args.prompt, args.limite,
                   args.recomecar, apenas)
    finally:
        ligacao.fechar()


if __name__ == "__main__":
    main()
