-- 011_nao_e_negocio.sql
-- Quando o comercial diz "isto não é um negócio", o par deixa de contar na
-- carteira, no pipeline e nos alertas. Continua em pares_llm e na avaliação.
CREATE OR REPLACE VIEW pares_efetivos AS
SELECT p.par_id, p.vistamp, p.negocio_id,
       coalesce(a.tipo_corrigido, p.tipo)     AS tipo,
       coalesce(a.estado_corrigido, p.estado) AS estado,
       p.excerto, p.ordem, p.origem, p.criado_em,
       (a.par_id IS NOT NULL)                 AS corrigido
  FROM pares_llm p
  LEFT JOIN avaliacao_pares a ON a.par_id = p.par_id AND a.acao = 'corrigido'
 WHERE a.motivo IS DISTINCT FROM 'não havia conteúdo comercial';
