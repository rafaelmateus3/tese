-- 001_esquema_pares.sql
-- Migração da base de dados para a unidade de análise par relatório-negócio.
-- Correr uma vez, na consola SQL do Neon ou com psql. É idempotente.
--
-- O que muda: classificacoes_llm era um registo por relatório com um estado.
-- A unidade passou a ser o par relatório-negócio, o que exige uma tabela de
-- pares, uma tabela de negócios onde eles apontam, e o número do cliente, sem
-- o qual nada cruza com o registo de equipamentos.
--
-- Nada é apagado. As colunas llm_confianca, acerto, estado_correto, id_motivo
-- e motivo_falha deixam de ser escritas e ficam como histórico de junho.

BEGIN;

-- 1. Relatório ------------------------------------------------------------
-- cliente_no é o que liga o relatório ao parque de equipamentos (RF2.2).
-- conteudo_comercial é a saída do nível 1 da classificação.
ALTER TABLE classificacoes_llm
    ADD COLUMN IF NOT EXISTS cliente_no          INTEGER,
    ADD COLUMN IF NOT EXISTS conteudo_comercial  BOOLEAN,
    ADD COLUMN IF NOT EXISTS modelo              TEXT;

CREATE INDEX IF NOT EXISTS ix_class_cliente_no ON classificacoes_llm (cliente_no);
CREATE INDEX IF NOT EXISTS ix_class_data       ON classificacoes_llm (data_visita);

COMMENT ON COLUMN classificacoes_llm.llm_estado IS
    'Histórico: estado atribuído ao relatório inteiro pelos prompts v01-a03. '
    'A partir do prompt c01 o estado vive em pares_llm.';

-- 2. Negócios -------------------------------------------------------------
-- O negócio é a entidade a que os pares apontam. Equipamento e produção
-- percorrem o ciclo comercial e têm estado_actual; consumíveis não percorrem
-- e têm estado_relacao, calculado da periodicidade de compra.
CREATE TABLE IF NOT EXISTS negocios (
    negocio_id      TEXT PRIMARY KEY,
    cliente_no      INTEGER NOT NULL,
    cliente         TEXT,
    tipo            TEXT NOT NULL
                    CHECK (tipo IN ('equipamento', 'producao', 'consumiveis')),
    descricao       TEXT,
    referencia      TEXT,                 -- só consumíveis
    inicio          DATE,
    fim             DATE,
    estado_actual   TEXT,                 -- equipamento e produção
    estado_relacao  TEXT,                 -- consumíveis: 0. Pontual .. 3. Dormente
    valor           NUMERIC,
    fechado_em      DATE,
    fecho_motivo    TEXT,                 -- 'declarado' | 'automatico_180d'
    criado_por      TEXT NOT NULL DEFAULT 'sistema'
                    CHECK (criado_por IN ('sistema', 'comercial')),
    criado_em       TIMESTAMP NOT NULL DEFAULT now(),
    CHECK ( (tipo = 'consumiveis' AND estado_actual IS NULL)
         OR (tipo <> 'consumiveis' AND estado_relacao IS NULL) )
);

CREATE INDEX IF NOT EXISTS ix_negocios_cliente ON negocios (cliente_no, tipo);
CREATE INDEX IF NOT EXISTS ix_negocios_abertos ON negocios (fechado_em)
    WHERE fechado_em IS NULL;

COMMENT ON COLUMN negocios.criado_por IS
    'RF2.9: comercial marca um negócio que o sistema não identificou.';

-- 3. Pares ----------------------------------------------------------------
-- Uma linha por par relatório-negócio. É a unidade de análise (D-2026-08-29-02).
CREATE TABLE IF NOT EXISTS pares_llm (
    par_id          TEXT PRIMARY KEY,     -- vistamp|negocio_id
    vistamp         TEXT NOT NULL REFERENCES classificacoes_llm (vistamp)
                    ON DELETE CASCADE,
    negocio_id      TEXT NOT NULL REFERENCES negocios (negocio_id)
                    ON DELETE CASCADE,
    tipo            TEXT NOT NULL
                    CHECK (tipo IN ('equipamento', 'producao', 'consumiveis')),
    estado          TEXT,                 -- nível 2; nulo para consumíveis
    excerto         TEXT NOT NULL,        -- RF1.3: justificação ancorada no texto
    ordem           SMALLINT NOT NULL DEFAULT 1,
    origem          TEXT NOT NULL DEFAULT 'llm'
                    CHECK (origem IN ('llm', 'comercial')),
    prompt_version  TEXT NOT NULL,
    modelo          TEXT NOT NULL,
    criado_em       TIMESTAMP NOT NULL DEFAULT now(),
    CHECK ( (tipo = 'consumiveis' AND estado IS NULL)
         OR (tipo <> 'consumiveis' AND estado IS NOT NULL) )
);

CREATE INDEX IF NOT EXISTS ix_pares_vistamp ON pares_llm (vistamp);
CREATE INDEX IF NOT EXISTS ix_pares_negocio ON pares_llm (negocio_id, criado_em DESC);

COMMENT ON TABLE pares_llm IS
    'Unidade de análise. O estado só existe para equipamento e produção: os '
    'consumíveis não percorrem o ciclo comercial e o seu estado de relação é '
    'calculado do histórico de compras, em negocios.estado_relacao.';

-- 4. Parque de equipamentos (RF2.2) ---------------------------------------
-- entrada = max(instal, criado_em). Ver base_instalada.py.
CREATE TABLE IF NOT EXISTS parque_equipamentos (
    mastamp     TEXT PRIMARY KEY,
    cliente_no  INTEGER NOT NULL,
    instal      DATE,
    criado_em   DATE,
    entrada     DATE NOT NULL,
    marca       TEXT,
    area        TEXT
);

CREATE INDEX IF NOT EXISTS ix_parque_cliente ON parque_equipamentos (cliente_no, entrada);

-- 5. Alertas (RF2.3, RF2.4, RF2.5, RF2.8) ---------------------------------
-- O registo do que já foi emitido é o que torna a TRANSIÇÃO observável.
-- Sem ele não há forma de saber se a condição é nova.
CREATE TABLE IF NOT EXISTS alertas_emitidos (
    id          BIGSERIAL PRIMARY KEY,
    negocio_id  TEXT NOT NULL REFERENCES negocios (negocio_id) ON DELETE CASCADE,
    regra       TEXT NOT NULL,
    emitido_em  DATE NOT NULL,
    vendedor    TEXT,
    cliente     TEXT,
    estado      TEXT,
    dias        INTEGER,
    prioridade  NUMERIC,
    entregue    BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (negocio_id, regra, emitido_em)
);

CREATE INDEX IF NOT EXISTS ix_alertas_negocio ON alertas_emitidos (negocio_id, regra);
CREATE INDEX IF NOT EXISTS ix_alertas_semana  ON alertas_emitidos (vendedor, emitido_em);

CREATE TABLE IF NOT EXISTS negocios_fechados_auto (
    negocio_id  TEXT PRIMARY KEY REFERENCES negocios (negocio_id) ON DELETE CASCADE,
    fechado_em  DATE NOT NULL,
    ultimo_toque DATE,
    dias        INTEGER
);

-- 6. Avaliação incorporada (RF1.7, RF2.9) ---------------------------------
-- O lote é a unidade de confirmação: sem ele, "não corrigiu" é ambíguo entre
-- "vi e está bem" e "nunca olhei".
CREATE TABLE IF NOT EXISTS lotes_revisao (
    lote_id     TEXT PRIMARY KEY,         -- vendedor|YYYY-MM-DD
    vendedor    TEXT NOT NULL,
    dia         DATE NOT NULL,
    n_pares     INTEGER NOT NULL DEFAULT 0,
    aberto_em   TIMESTAMP NOT NULL DEFAULT now(),
    fechado_em  TIMESTAMP,
    UNIQUE (vendedor, dia)
);

-- Uma correcção não ratificada continua a ser informação; só não é sinal de
-- treino. Por isso proposto, corrigido e ratificado ficam em colunas separadas.
CREATE TABLE IF NOT EXISTS avaliacao_pares (
    par_id          TEXT PRIMARY KEY,
    lote_id         TEXT REFERENCES lotes_revisao (lote_id) ON DELETE SET NULL,
    vistamp         TEXT NOT NULL,
    negocio_id      TEXT,
    acao            TEXT NOT NULL
                    CHECK (acao IN ('corrigido', 'negocio_em_falta')),
    estado_proposto TEXT,
    estado_corrigido TEXT,
    tipo_proposto   TEXT,
    tipo_corrigido  TEXT,
    motivo          TEXT NOT NULL,
    corrigido_por   TEXT NOT NULL,
    corrigido_em    TIMESTAMP NOT NULL DEFAULT now(),
    ratificado      BOOLEAN NOT NULL DEFAULT FALSE,
    ratificado_por  TEXT,
    ratificado_em   TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_aval_lote ON avaliacao_pares (lote_id);
CREATE INDEX IF NOT EXISTS ix_aval_rat  ON avaliacao_pares (ratificado, corrigido_em);

COMMIT;
