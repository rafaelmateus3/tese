# -*- coding: utf-8 -*-
"""Gera prompts/marcas.py a partir do parque de equipamentos.

A lista de marcas não é escrita à mão: sai do sistema de registo, onde já
existe. Correr de novo depois de uma carga actualiza-a, e a versão do prompt
tem de subir a seguir, porque o texto do prompt mudou.

    python _gerar_marcas.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402

MINIMO = 3          # equipamentos no parque para a marca entrar

# Entradas que não são marcas, ou que o responsável do domínio marcou como sem
# importância para a leitura dos relatórios.
FORA = {"MAQUINAS DIVERSAS", "PC", "PC DELL", "MACINTOSH", "SEM MARCA",
        "OUTROS", "VARIOS", "DIVERSOS", "EMPRESA", "INFORMATICA", "UPS"}

SQL = """
SELECT btrim(marca) AS marca, count(*) AS n
  FROM parque_equipamentos
 WHERE marca IS NOT NULL AND btrim(marca) <> ''
 GROUP BY 1 HAVING count(*) >= %s
 ORDER BY 2 DESC, 1
"""

CABECALHO = '''# -*- coding: utf-8 -*-
"""Marcas presentes no parque de equipamentos dos clientes.

Gerado por _gerar_marcas.py a partir de parque_equipamentos em {data}.
Não editar à mão: {n} marcas com pelo menos {minimo} equipamentos instalados,
menos as entradas que não são marcas.

Serve um fim preciso no prompt: uma menção a um destes nomes NOMEIA UM PRODUTO
CONCRETO, o que satisfaz o primeiro dos quatro sinais que tipificam um negócio.
Não diz de que tipo é o negócio; isso continua a sair do resto do texto.
"""

MARCAS = {marcas!r}
'''


def main() -> None:
    ligacao = db.Ligacao()
    try:
        def ler(conn):
            with conn.cursor() as cur:
                cur.execute(SQL, (MINIMO,))
                return cur.fetchall()
        linhas = ligacao.executar(ler)
    finally:
        ligacao.fechar()

    marcas = [m for m, _n in linhas if m.upper() not in FORA]
    destino = Path(__file__).resolve().parent / "marcas.py"
    destino.write_text(
        CABECALHO.format(data=date.today().isoformat(), n=len(marcas),
                         minimo=MINIMO, marcas=marcas),
        encoding="utf-8")
    print(f"{len(linhas)} marcas com >= {MINIMO} equipamentos, "
          f"{len(linhas) - len(marcas)} excluídas, {len(marcas)} escritas")


if __name__ == "__main__":
    main()
