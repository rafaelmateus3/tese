-- 009_tempo_de_anotacao.sql
-- Tempo gasto em cada anotação, medido pela interface entre abrir o relatório
-- e gravar. Serve para declarar o custo de construir o conjunto de referência,
-- que é um dos critérios de adequação a uma PME (§3.2.2).
ALTER TABLE gold_anotacoes_hist ADD COLUMN IF NOT EXISTS segundos NUMERIC;
