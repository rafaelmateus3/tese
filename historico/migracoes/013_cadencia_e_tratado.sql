-- 013_cadencia_e_tratado.sql
-- Decisões de 10-Out-2026, a partir da Entrevista 1 (sessão de grupo, 9-Out). Idempotente.
--
--   RF2.5  os alertas continuam a ser emitidos no dia da transição, mas a
--          notificação passa a ser semanal, num dia fixo (sexta por omissão),
--          agregando os da semana para o comercial planear a seguinte.
--   RF1.7  «já tratei»: o comercial tira um alerta da lista sem mexer no estado
--          do negócio. A correção do estado fica reservada à revisão do dia e
--          continua a medir o acerto da classificação.

BEGIN;

ALTER TABLE alertas_emitidos ADD COLUMN IF NOT EXISTS notificado_em DATE;
ALTER TABLE alertas_emitidos ADD COLUMN IF NOT EXISTS tratado_em TIMESTAMPTZ;
ALTER TABLE alertas_emitidos ADD COLUMN IF NOT EXISTS tratado_por TEXT;

UPDATE alertas_emitidos SET notificado_em = emitido_em
 WHERE notificado AND notificado_em IS NULL;

INSERT INTO parametros (chave, valor, descricao, origem) VALUES
 ('dia_notificacao', 5,
  'Dia da semana em que os alertas são notificados (1 = segunda, 5 = sexta; 0 = todos os dias)',
  'Entrevista 1, 9-Out-2026')
ON CONFLICT (chave) DO NOTHING;

COMMIT;
