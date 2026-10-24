-- O registo guardava a VERSÃO do prompt mas não o seu conteúdo. Bastou editar
-- um ficheiro de prompt depois de as corridas terem sido feitas para a etiqueta
-- deixar de identificar o texto que as produziu, sem que nada o assinalasse.
--
-- Passa a guardar-se o resumo criptográfico do prompt efectivamente usado. Uma
-- alteração posterior ao ficheiro deixa de ser silenciosa: o resumo da corrida
-- e o do ficheiro divergem e a divergência é visível.

ALTER TABLE benchmark_corridas ADD COLUMN IF NOT EXISTS prompt_hash TEXT;

COMMENT ON COLUMN benchmark_corridas.prompt_hash IS
  'sha256 dos primeiros 12 caracteres hex do SYSTEM_PROMPT usado na corrida';
