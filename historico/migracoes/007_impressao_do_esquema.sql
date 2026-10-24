-- Pelo mesmo motivo do prompt: a versão do esquema é uma etiqueta escrita à mão
-- no código e pode ficar para trás de uma alteração à lógica que o constrói.
-- O resumo é tirado do esquema gerado para uma entrada fixa, para que compare.
--
-- As corridas anteriores a esta migração ficam com a coluna vazia: o código que
-- as produziu já não existe e o resumo não pode ser reconstruído. O vazio é a
-- informação correcta.

ALTER TABLE benchmark_corridas ADD COLUMN IF NOT EXISTS esquema_hash TEXT;
