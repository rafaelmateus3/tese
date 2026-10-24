-- 012_alertas_rf.sql
-- Alinha os alertas com o Quadro 4.2. Idempotente.
--
--   RF2.3  quatro regras: à espera de resposta (proposta, negociação, aprovação),
--          encomenda confirmada sem avanço, negócio sem contacto em qualquer
--          estado, e cliente da base instalada sem contacto. A última não tem
--          negócio: o alvo passa a poder ser o cliente.
--   RF2.5  o excedente do teto semanal fica registado como não notificado e
--          aparece numa lista consultável, em vez de desaparecer.

BEGIN;

ALTER TABLE alertas_emitidos ADD COLUMN IF NOT EXISTS notificado BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE alertas_emitidos ADD COLUMN IF NOT EXISTS cliente_no INTEGER;
ALTER TABLE alertas_emitidos ALTER COLUMN negocio_id DROP NOT NULL;

DO $$ BEGIN
    ALTER TABLE alertas_emitidos ADD CONSTRAINT alertas_alvo
        CHECK (negocio_id IS NOT NULL OR cliente_no IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- O alerta de cliente não tem negócio: a unicidade da transição passa a ser por cliente.
CREATE UNIQUE INDEX IF NOT EXISTS ux_alertas_cliente
    ON alertas_emitidos (cliente_no, regra, emitido_em) WHERE negocio_id IS NULL;
CREATE INDEX IF NOT EXISTS ix_alertas_cliente ON alertas_emitidos (cliente_no, regra);

-- As descrições passam a dizer o que cada regra do RF2.3 é.
UPDATE parametros SET descricao = 'À espera de resposta: dias sem contacto num negócio em proposta, negociação ou aprovação interna'
 WHERE chave = 'dias_negociacao';
UPDATE parametros SET descricao = 'Encomenda sem avanço: dias em «Encomenda confirmada» sem mudar de estado'
 WHERE chave = 'dias_mesmo_estado';
UPDATE parametros SET descricao = 'Sem contacto: dias sem contacto num negócio aberto, em qualquer estado'
 WHERE chave = 'dias_sem_contacto';

INSERT INTO parametros (chave, valor, descricao, origem) VALUES
 ('dias_base_sem_contacto', 90,
  'Cliente com equipamento sem visita: dias sem contacto com um cliente da base instalada sem negócio aberto',
  '§4.5')
ON CONFLICT (chave) DO NOTHING;

COMMIT;
