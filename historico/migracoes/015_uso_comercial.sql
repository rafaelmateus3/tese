-- 015_uso_comercial.sql (15-Out-2026)
-- Ajustes depois dos primeiros dias de uso pelos comerciais. Idempotente.
--
--   Avisos atrasados: os do arranque (a condição acumulada do histórico) passam a entrar
--   aos poucos no lote de sexta, depois dos novos; enquanto houver atrasados, o teto
--   semanal sobe para `teto_atraso`.
--   Fecho pelo comercial: na carteira, o comercial fecha um negócio como ganho, perdido ou
--   «não avançou». Fica em negocios (fecho_motivo comercial_*), com quem fechou.
--   Fecho pela faturação: um negócio adjudicado ou em produção/entrega com fatura do tipo
--   ao mesmo cliente depois da adjudicação fecha como ganho (fecho_motivo faturado).
--   Valor dos negócios: o do dossier do PHC (proposta, proforma ou encomenda de cliente)
--   ligado ao negócio por cliente, tipo e data (carga/dossiers.py). A vista carteira passa a
--   usar esse valor quando existe; as colunas novas da vista vão no fim, como o PostgreSQL exige.
--   Consumíveis: a última compra, o intervalo habitual e o valor dos últimos 12 meses
--   ficam guardados para o comercial perceber o aviso; «já tratei» também aqui.

BEGIN;

ALTER TABLE negocios ADD COLUMN IF NOT EXISTS fechado_por TEXT;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS ultima_compra DATE;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS intervalo_compra INTEGER;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS valor_12m NUMERIC;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS valor_dossier NUMERIC;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS dossier_ref TEXT;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS dossier_tipo TEXT;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS dossier_data DATE;

CREATE TABLE IF NOT EXISTS consumo_tratado (
    negocio_id    TEXT PRIMARY KEY,
    tratado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    tratado_por   TEXT NOT NULL,
    ultima_compra DATE            -- a última compra que havia quando foi tratado
);

INSERT INTO parametros (chave, valor, descricao, origem) VALUES
 ('teto_atraso', 15,
  'Máximo de avisos por comercial e por semana enquanto houver avisos atrasados do arranque',
  '15-Out-2026')
ON CONFLICT (chave) DO NOTHING;

CREATE OR REPLACE VIEW carteira AS
WITH r AS (
    SELECT coalesce(x.fundido_em, p.negocio_id) AS nid, c.data_visita, c.vendedor,
           c.cliente, p.estado, p.excerto, p.criado_em
      FROM pares_efetivos p
      JOIN classificacoes_llm c ON c.vistamp = p.vistamp
      LEFT JOIN negocios x ON x.negocio_id = p.negocio_id
     WHERE c.data_visita IS NOT NULL
), s AS (
    SELECT nid, data_visita::date AS data, vendedor, cliente, estado, excerto,
           row_number() OVER (PARTITION BY nid ORDER BY data_visita DESC, criado_em DESC) AS k,
           count(*) OVER (PARTITION BY nid) AS relatorios,
           min(data_visita::date) OVER (PARTITION BY nid) AS primeiro
      FROM r
)
SELECT n.negocio_id, n.cliente_no, coalesce(n.cliente, s.cliente) AS cliente,
       n.tipo, coalesce(n.valor_dossier, n.valor) AS valor, coalesce(n.inicio, s.primeiro) AS inicio,
       n.fechado_em, n.fecho_motivo, n.estado_relacao,
       s.data AS ultimo_toque, s.vendedor, s.estado, s.excerto, s.relatorios,
       CASE WHEN EXISTS (SELECT 1 FROM parque_equipamentos q
                          WHERE q.cliente_no = n.cliente_no
                            AND q.entrada < coalesce(n.inicio, s.primeiro))
            THEN 'base_instalada' ELSE 'conquista' END AS segmento,
       n.dossier_ref, n.dossier_tipo, n.dossier_data
  FROM negocios n
  JOIN s ON s.nid = n.negocio_id AND s.k = 1;

COMMIT;
