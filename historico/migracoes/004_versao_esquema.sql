-- O esquema de saída é a segunda metade da tarefa dada ao modelo e muda por
-- razões próprias, independentes do texto do prompt. Sem esta coluna, corridas
-- com o mesmo prompt_version e esquemas diferentes ficavam indistinguíveis.

ALTER TABLE benchmark_corridas ADD COLUMN IF NOT EXISTS esquema_version text;

-- As corridas anteriores a esta migração: o esquema por relatório entrou em
-- vigor às 23:10 de 16-Set-2026, entre a última corrida de nuvem e a primeira
-- corrida local.
UPDATE benchmark_corridas
   SET esquema_version = CASE
       WHEN iniciada_em < timestamp '2026-09-16 23:10' THEN 'e01'
       ELSE 'e02' END
 WHERE esquema_version IS NULL;
