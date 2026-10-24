-- 008_entrada_v2_e_gold.sql
-- Duas mudanças que andam juntas.
--
-- 1. A entrada do benchmark passa a ter versão. A v1 dava ao modelo um bloco de
--    negócios construído com o histórico inteiro: a data de fim de cada negócio
--    era o último relatório do episódio, muitas vezes posterior ao relatório em
--    análise, e os negócios nascidos do próprio relatório já lá apareciam. A v2
--    só usa o que se sabia à data. As duas ficam guardadas, e cada corrida
--    regista a que leu, porque sem isso as corridas antigas deixariam de ter
--    entrada identificável.
--
-- 2. A anotação de referência sai do Excel para a base de dados, com a versão
--    da entrada que o anotador viu e um histórico de cada gravação. Uma
--    anotação só se compara com corridas que leram a mesma entrada.

ALTER TABLE benchmark_entradas ADD COLUMN IF NOT EXISTS entrada_version TEXT NOT NULL DEFAULT 'v1';
ALTER TABLE benchmark_entradas ADD COLUMN IF NOT EXISTS linha INTEGER;
ALTER TABLE benchmark_entradas DROP CONSTRAINT IF EXISTS benchmark_entradas_pkey;
ALTER TABLE benchmark_entradas ADD PRIMARY KEY (vistamp, entrada_version);
ALTER TABLE benchmark_corridas ADD COLUMN IF NOT EXISTS entrada_version TEXT NOT NULL DEFAULT 'v1';

CREATE TABLE IF NOT EXISTS gold_anotacoes (
    vistamp          TEXT NOT NULL,
    entrada_version  TEXT NOT NULL,
    comercial        BOOLEAN NOT NULL,
    pares            JSONB NOT NULL DEFAULT '[]'::jsonb,
    duvida           BOOLEAN NOT NULL DEFAULT false,
    nota             TEXT,
    origem           TEXT,
    anotador         TEXT,
    atualizado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vistamp, entrada_version)
);

CREATE TABLE IF NOT EXISTS gold_anotacoes_hist (
    id               BIGSERIAL PRIMARY KEY,
    vistamp          TEXT NOT NULL,
    entrada_version  TEXT NOT NULL,
    comercial        BOOLEAN NOT NULL,
    pares            JSONB NOT NULL,
    duvida           BOOLEAN NOT NULL,
    nota             TEXT,
    origem           TEXT,
    anotador         TEXT,
    gravado_em       TIMESTAMPTZ NOT NULL DEFAULT now()
);
