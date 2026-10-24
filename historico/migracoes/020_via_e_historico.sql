-- 020: integridade das correções (24-Out-2026).
-- Correr uma vez na base em produção; depois regenerar esquema.sql. É idempotente.
--
-- 1. avaliacao_pares.via: por onde chegou a correção, a revisão do dia ou a carteira.
--    A precisão do Cap. 6 conta só as da revisão de dias fechados, o mesmo universo
--    do denominador (os pares desses dias).
-- 2. avaliacao_pares_hist: uma correção substituída pela carteira fica aqui tal como
--    estava, incluindo a ratificação que tinha.
-- 3. As correções anteriores a esta migração ficam como 'revisao', exceto as que só
--    podem ter vindo da carteira: dia anterior ao arranque da revisão (12-Out-2026),
--    lote nunca fechado e um dos dois motivos que a carteira usa. Em 24-Out era uma
--    (dia 16-Jun, corrigida a 18-Out).

BEGIN;

ALTER TABLE avaliacao_pares
    ADD COLUMN IF NOT EXISTS via TEXT NOT NULL DEFAULT 'revisao';

ALTER TABLE avaliacao_pares DROP CONSTRAINT IF EXISTS avaliacao_pares_via_check;
ALTER TABLE avaliacao_pares
    ADD CONSTRAINT avaliacao_pares_via_check CHECK (via IN ('revisao', 'carteira'));

COMMENT ON COLUMN avaliacao_pares.via IS
    'Onde o erro foi encontrado: revisao (o lote do dia) ou carteira (o último relatório do negócio). É a da primeira correção do par.';

UPDATE avaliacao_pares a
   SET via = 'carteira'
  FROM lotes_revisao l
 WHERE l.lote_id = a.lote_id
   AND a.acao = 'corrigido'
   AND a.via = 'revisao'
   AND l.dia < DATE '2026-10-12'
   AND l.fechado_em IS NULL
   AND a.motivo IN ('tipo errado', 'fronteira entre estados');

CREATE TABLE IF NOT EXISTS avaliacao_pares_hist (
    id               BIGSERIAL PRIMARY KEY,
    par_id           TEXT NOT NULL,
    lote_id          TEXT,
    vistamp          TEXT NOT NULL,
    negocio_id       TEXT,
    acao             TEXT NOT NULL,
    estado_proposto  TEXT,
    estado_corrigido TEXT,
    tipo_proposto    TEXT,
    tipo_corrigido   TEXT,
    negocio_corrigido TEXT,
    motivo           TEXT NOT NULL,
    corrigido_por    TEXT NOT NULL,
    corrigido_em     TIMESTAMP NOT NULL,
    ratificado       BOOLEAN NOT NULL,
    ratificado_por   TEXT,
    ratificado_em    TIMESTAMP,
    via              TEXT NOT NULL,
    substituida_em   TIMESTAMP NOT NULL DEFAULT now(),
    substituida_por  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_aval_hist_par ON avaliacao_pares_hist (par_id);

COMMENT ON TABLE avaliacao_pares_hist IS
    'Correções substituídas por uma correção na carteira, tal como estavam antes.';

COMMIT;
