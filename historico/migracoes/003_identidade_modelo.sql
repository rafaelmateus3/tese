-- 003_identidade_modelo.sql
-- Regista a identidade dos pesos, e não apenas o nome do modelo.
--
-- A etiqueta de um modelo local não identifica os pesos: o mesmo `gemma4:26b`
-- tinha resumos diferentes em duas máquinas, 17 GB numa e 18 GB noutra. Comparar
-- modelos por etiqueta compararia artefactos diferentes com o mesmo nome, o que
-- destrói a reprodutibilidade que o RF1.5 exige e a proveniência do RF1.6.

ALTER TABLE benchmark_corridas ADD COLUMN IF NOT EXISTS modelo_id TEXT;
ALTER TABLE benchmark_corridas ADD COLUMN IF NOT EXISTS maquina TEXT;

COMMENT ON COLUMN benchmark_corridas.modelo_id IS
    'Resumo criptográfico dos pesos (ollama) ou identificador do modelo (nuvem). '
    'É esta coluna, e não o nome, que identifica o que foi executado.';
