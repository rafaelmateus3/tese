-- 002_benchmark.sql
-- Tabelas do benchmark. Separadas das de produção de propósito: comparar modelos
-- exige guardar o que cada um disse sobre o mesmo relatório, e as tabelas de
-- produção guardam uma classificação só, a corrente.

BEGIN;

-- A entrada exacta dada a todos os modelos, congelada antes da primeira corrida.
-- Sem isto, o bloco de negócios abertos mudaria entre corridas à medida que o
-- sistema fosse escrevendo, e os modelos deixariam de ser comparáveis.
CREATE TABLE IF NOT EXISTS benchmark_entradas (
    vistamp     TEXT PRIMARY KEY,
    cliente_no  INTEGER NOT NULL,
    cliente     TEXT,
    estrato     TEXT NOT NULL
                CHECK (estrato IN ('com_negocio_aberto', 'sem_negocio_aberto')),
    mensagem    TEXT NOT NULL,
    congelada_em TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS benchmark_corridas (
    corrida_id     TEXT PRIMARY KEY,
    modelo         TEXT NOT NULL,
    backend        TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    contexto       INTEGER,
    n_relatorios   INTEGER NOT NULL DEFAULT 0,
    n_erros        INTEGER NOT NULL DEFAULT 0,
    tokens_in      BIGINT NOT NULL DEFAULT 0,
    tokens_out     BIGINT NOT NULL DEFAULT 0,
    segundos       NUMERIC,
    iniciada_em    TIMESTAMP NOT NULL DEFAULT now(),
    terminada_em   TIMESTAMP,
    nota           TEXT
);

-- Uma linha por relatório e corrida, mesmo quando o modelo não devolveu pares:
-- zero pares é um resultado e tem de entrar no denominador.
CREATE TABLE IF NOT EXISTS benchmark_respostas (
    corrida_id         TEXT NOT NULL REFERENCES benchmark_corridas (corrida_id)
                       ON DELETE CASCADE,
    vistamp            TEXT NOT NULL,
    conteudo_comercial BOOLEAN,
    n_pares            SMALLINT NOT NULL DEFAULT 0,
    erro               TEXT,
    tokens_in          INTEGER,
    tokens_out         INTEGER,
    segundos           NUMERIC,
    raw                TEXT,
    PRIMARY KEY (corrida_id, vistamp)
);

CREATE TABLE IF NOT EXISTS benchmark_pares (
    corrida_id  TEXT NOT NULL,
    vistamp     TEXT NOT NULL,
    ordem       SMALLINT NOT NULL,
    negocio_id  TEXT,
    tipo        TEXT,
    estado      TEXT,
    excerto     TEXT,
    PRIMARY KEY (corrida_id, vistamp, ordem),
    FOREIGN KEY (corrida_id, vistamp)
        REFERENCES benchmark_respostas (corrida_id, vistamp) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_bpares_vistamp ON benchmark_pares (vistamp);

COMMIT;
