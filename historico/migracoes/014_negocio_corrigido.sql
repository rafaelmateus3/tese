-- 014_negocio_corrigido.sql (15-Out-2026)
-- Correção de identidade na revisão do dia. Quando o motivo é «negócio errado», o comercial
-- escolhe o negócio certo entre os negócios do cliente, ou diz que é um negócio novo.
-- O par passa a contar no negócio corrigido em todo o lado (carteira, pipeline, alertas) e no
-- bloco dado ao modelo nos relatórios seguintes (producao.SQL_ANTERIORES).
-- pares_llm não se mexe: o que o modelo disse fica em negocio_id; a correção fica aqui.
BEGIN;

ALTER TABLE avaliacao_pares ADD COLUMN IF NOT EXISTS negocio_corrigido TEXT;

CREATE OR REPLACE VIEW pares_efetivos AS
SELECT p.par_id, p.vistamp,
       coalesce(a.negocio_corrigido, p.negocio_id) AS negocio_id,
       coalesce(a.tipo_corrigido, p.tipo)          AS tipo,
       coalesce(a.estado_corrigido, p.estado)      AS estado,
       p.excerto, p.ordem, p.origem, p.criado_em,
       (a.par_id IS NOT NULL)                      AS corrigido
  FROM pares_llm p
  LEFT JOIN avaliacao_pares a ON a.par_id = p.par_id AND a.acao = 'corrigido'
 WHERE a.motivo IS DISTINCT FROM 'não havia conteúdo comercial';

COMMIT;
