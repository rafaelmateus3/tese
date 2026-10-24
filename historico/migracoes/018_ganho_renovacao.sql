-- 018_ganho_renovacao.sql (15-Out-2026, decisão sobre o mapeamento da SLR)
--
--   Taxa histórica de ganho por fase (proposta 1): o Quadro 6.11 do §6.4, guardado como
--   tabela para o dashboard mostrar o histórico de cada fase e o valor ponderado do pipeline.
--   É o que aconteceu, e não uma previsão: proporção de negócios ganhos nos 180 dias seguintes
--   à primeira classificação em cada fase, classificação c05r de 19-09-2024 a 13-10-2026 e
--   faturação até 15-10-2026. As fases 6 e 7 já contam como ganho na definição do §6.4 e
--   não têm linha.
--
--   Renovação do parque (proposta 3): cliente ativo cuja máquina mais recente entrou no parque
--   há `anos_renovacao` anos ou mais e sem negócio de equipamento aberto. O limiar parte do
--   percentil 90 do intervalo entre compras de equipamento do mesmo cliente (8,1 anos, 527
--   intervalos entre episódios de compra separados por mais de um ano, sem a data de
--   migração de 03-11-2003). «Já tratei» cala o cliente durante um ano.

BEGIN;

CREATE TABLE IF NOT EXISTS taxa_ganho_fase (
    estado          TEXT PRIMARY KEY,
    negocios        INTEGER NOT NULL,
    ganho           NUMERIC NOT NULL,   -- proporção, 0 a 1
    ganho_faturacao NUMERIC,            -- só com a faturação como desfecho
    origem          TEXT NOT NULL
);

INSERT INTO taxa_ganho_fase (estado, negocios, ganho, ganho_faturacao, origem) VALUES
 ('1. Lead / Prospeção',     390, 0.023, 0.021, 'Quadro 6.11, §6.4'),
 ('2. Qualificação',         385, 0.127, 0.101, 'Quadro 6.11, §6.4'),
 ('3. Proposta / Orçamento', 270, 0.189, 0.152, 'Quadro 6.11, §6.4'),
 ('4. Negociação',            84, 0.298, 0.262, 'Quadro 6.11, §6.4'),
 ('5. Aprovação Interna',    102, 0.284, 0.255, 'Quadro 6.11, §6.4'),
 ('10. Indeterminado',       199, 0.126, 0.075, 'Quadro 6.11, §6.4')
ON CONFLICT (estado) DO NOTHING;

INSERT INTO parametros (chave, valor, descricao, origem) VALUES
 ('anos_renovacao', 8,
  'Anos desde a entrada da máquina mais recente de um cliente para o propor para renovação',
  'Percentil 90 do intervalo entre compras de equipamento do mesmo cliente (8,1 anos), 15-Out-2026')
ON CONFLICT (chave) DO NOTHING;

CREATE TABLE IF NOT EXISTS renovacao_tratada (
    cliente_no  INTEGER PRIMARY KEY,
    tratado_em  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tratado_por TEXT NOT NULL
);

COMMIT;
