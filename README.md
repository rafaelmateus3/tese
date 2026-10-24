# TESE RUN

Código dos artefactos descritos no Capítulo 5 da dissertação.

```
ciclo.py         ciclo noturno: chama os passos pela ordem certa
classificador/   classifica relatórios de visita em pares relatório-negócio
carga/           parque de equipamentos, consumíveis e dossiers do PHC
benchmark/       compara modelos contra o conjunto de referência
dashboard/       aplicação de apoio à decisão
esquema.sql      esquema actual da base de dados, gerado da base
dados_iniciais.sql  parâmetros e taxas de ganho por fase, gerados da base
exemplos/        extrações fictícias e ensaio de ponta a ponta
instalacao/      instalação no computador de produção (corre uma vez)
historico/       o que já não corre: as migrações 001 a 020 que levaram ao esquema
```

## Reproduzir os números do Capítulo 6

```bash
pip install -r requirements.txt
python benchmark/reproduzir.py
```

Recalcula, a partir de `benchmark/anonimo/benchmark_anonimo.json.gz`, os números do
Capítulo 6 e do Anexo L que vêm do benchmark (Quadros 6.1 a 6.5, 6.7, L.1 e L.2 e os
valores do texto: intervalos de confiança, testes de McNemar com correção de Holm, conjunto
de desenvolvimento, serviço externo, quarta etapa e reprodutibilidade), e compara cada um
com o valor da dissertação. Não precisa de base de dados nem de modelo.

O ficheiro tem as corridas e a anotação sem texto: cada relatório é um número e cada
negócio um identificador sem o número do cliente; dos excertos ficam só a indicação de
constarem do relatório e um resumo para comparar corridas. Gera-se da base com
`python benchmark/exportar.py --amostra <fases 1 e 2>`.

Todas as métricas e testes têm uma só implementação, `benchmark/metricas.py`, que o
`reproduzir.py` e o painel de resultados (`benchmark/painel.py`) usam. Os intervalos de
confiança são por reamostragem dos relatórios (1000 réplicas, semente fixa).

Para ver os resultados no browser, `python benchmark/painel.py` escreve
`resultados/painel_benchmark.html` a partir do mesmo ficheiro: todas as corridas, com
filtros por tarefa, conjunto de relatórios e modelo, e as métricas e os testes com as
convenções da dissertação.

## Experimentar sem dados reais

A pasta `exemplos/` tem extrações fictícias do ERP (12 clientes, 3 comerciais) e os dois
registos da carga inicial, gerados por `exemplos/gerar_exemplos.py` (correr de novo para
datas a partir de hoje). Com uma base PostgreSQL vazia:

```bash
pip install -r requirements.txt httpx
python exemplos/ensaio.py --base "postgresql://utilizador:senha@localhost/ensaio"
```

O ensaio aplica o esquema e os dados iniciais, faz a carga, cria um utilizador por
comercial e um gestor (palavra-passe `exemplo1234`), corre o ciclo noturno com um modelo
simulado por regras de palavras-chave e abre as vistas do dashboard pela API. O modelo
simulado só serve para ver o resto do sistema a funcionar; a classificação real precisa
do ollama com o gemma4:26b (`python ciclo.py --sem-espera` com o `.env` a apontar para a
mesma base). Depois, `cd dashboard` e `uvicorn server:app --port 8000`.

## Produção

Uma vez, no computador que fica ligado (Windows):

1. `copy .env.exemplo .env` e preencher (base, modelo, `ERP_PASTA`).
2. Base de dados: numa base vazia, `psql "<URL>" -f esquema.sql` e depois
   `psql "<URL>" -f dados_iniciais.sql`. As migrações já aplicadas estão em
   `historico/migracoes/`.
3. Utilizadores, na pasta `dashboard`:
   `python utilizadores.py vendedores` (nomes do ERP) e depois
   `python utilizadores.py criar ana --nome "Ana" --vendedor "NOME NO ERP"` para
   cada comercial, e `python utilizadores.py criar gestor --papel gestor`.
4. `powershell -ExecutionPolicy Bypass -File instalacao\instalar_windows.ps1` (como
   administrador): ciclo noturno às 02:00 e dashboard na porta 8000.

A única coisa de fora: o ERP tem de deixar as extrações (`visitas_*.xlsx`,
`linhas_faturas_*.xlsx`, `equipamentos_*.xlsx`) em `ERP_PASTA` todos os dias.
A exportação corre às 02:00, fora deste repositório; o ciclo espera até 20 min pela do dia
(`--sem-espera` para correr à mão). As faturas usam-se a partir de `FATURAS_DESDE`
(2024-01-01 por omissão), a janela das extrações avaliadas.
O ciclo usa a mais recente de cada e avisa no registo se a de visitas tiver
mais de dois dias.

O que o ciclo faz (`ciclo.py`, registado na tabela `ciclos` e em `logs/`):
parque de equipamentos e relação de consumíveis, classificação dos relatórios
novos por ordem de data, fecho automático, alertas. O dashboard mostra no topo
quando correu e se correu bem.

## Classificar à mão

```bash
cd classificador
python run.py --limite 20              # ensaio
python run.py --desde 2026-09-01       # arranque: a partir de uma data
python run.py                          # o que falta
```

A mensagem dada ao modelo é a do benchmark v3 (`producao.py`, `bloco.py`,
`contexto.py`): verificado a 27-Set que, com o gold no lugar do modelo, a
produção gera 374 das 375 mensagens congeladas letra a letra (a outra difere
só num `nan` que a produção limpa). Os relatórios correm por ordem de data,
porque cada um vê o último estado deixado pelos anteriores.

## Dashboard

`app.jsx` compila-se para `app.js` (já compilado; só é preciso se o mudar):

```bash
npx esbuild dashboard/static/app.jsx --loader:.jsx=jsx --minify --outfile=dashboard/static/app.js
```

O React está em `static/vendor`: o dashboard não precisa de internet.


## Dados e anonimização

Não estão no repositório: credenciais (`.env`; usar `.env.exemplo`), registos,
a base de dados (Postgres), as extrações do ERP (`extracoes/`), o conjunto de
referência (`dados/`) e os resultados de avaliação (`resultados/`).

Nos exemplos dos prompts, os nomes de clientes, pessoas de contacto, comerciais e
marcas foram substituídos por nomes fictícios, e o sector da empresa foi retirado:
as áreas de negócio aparecem por letra (`AREA A` a `AREA D`), como na dissertação,
os exemplos falam de materiais e componentes genéricos e a lista de marcas
(`classificador/prompts/marcas.py`) é fictícia. O nome e logótipo da empresa foram
retirados do dashboard (`dashboard/static/marca/` tem um símbolo neutro no lugar
do logótipo). Por isso os resumos SHA-256 (12 primeiros caracteres) dos prompts diferem dos avaliados
no Capítulo 6:

| Prompt | Avaliado | Neste repositório |
|---|---|---|
| c01 | 21c6fee6885e | a65c247bc021 |
| c02 | d9e90ac2acd2 | 1c83339614de |
| c03 | 8d4dfb754644 | 0e6fa8b2b03a |
| c04 | 31f9ee1aa9a8 | 8ffab4276cf2 |
| c05 | 695dc199697a | a8442ec6c025 |
| c06 | 56e0f971b848 | f47c7e5f35b2 |
| c07 | eab4b172cc3d | bd35bf653eaf |
| c08 | c9eae6db2bd2 | 2350a86d8b4f |
| c05r | a144f8ce236d | 10607aa64bb0 |

`classificador/prompts/historico/a01.py` é o primeiro prompt da família A
(unidade de análise: o relatório), guardado como registo; não é importado.
