-- 016_dossiers_fase.sql (15-Out-2026)
-- Os dossiers do PHC passam a mexer nos negócios, sempre com a razão declarada:
--
--   Fase: um negócio avança pela fase que o dossier implica, nunca recua.
--         Proposta e Fatura Proforma = 3 (Orçamento enviado); Encomenda de Cliente = 6
--         (Adjudicado); Pedidos Produção e Guia de Transporte CL = 7 (Em produção / entrega).
--         Prevalece a fase mais avançada entre o último relatório e os dossiers do negócio,
--         exceto quando o relatório diz 8 ou 9.
--   Contacto: um dossier conta como contacto se vier pelo menos 7 dias depois do relatório
--         anterior do negócio (decidido em carga/dossiers.py, coluna `contacto`).
--   Comercial: o negócio é do comercial do registo mais recente, relatório ou dossier.
--   Abertura e unificação: ver carga/dossiers.py (negócios NG-D) e fechos.juntar.
--
-- Os eventos são recalculados todas as noites a partir da extração; não são editados à mão.
-- `pares_llm` não muda: o que o modelo disse continua a ser o que o modelo disse.

BEGIN;

CREATE TABLE IF NOT EXISTS eventos_dossier (
    negocio_id   TEXT NOT NULL,
    dossier_ref  TEXT NOT NULL,
    dossier_tipo TEXT NOT NULL,
    data         DATE NOT NULL,
    estado       TEXT,
    vendedor     TEXT,
    contacto     BOOLEAN NOT NULL DEFAULT FALSE,
    razao        TEXT NOT NULL,
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (negocio_id, dossier_ref)
);

-- Os negócios abertos pelos dossiers ficam marcados como tal.
ALTER TABLE negocios DROP CONSTRAINT IF EXISTS negocios_criado_por_check;
ALTER TABLE negocios ADD CONSTRAINT negocios_criado_por_check
    CHECK (criado_por = ANY (ARRAY['sistema', 'comercial', 'dossier']));

ALTER TABLE negocios ADD COLUMN IF NOT EXISTS fundido_por TEXT;
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS fundido_data DATE;

-- Ordem das fases para «só avança»: o 10 (indeterminado) conta como nenhuma fase.
CREATE OR REPLACE FUNCTION fase_ordem(e TEXT) RETURNS INTEGER
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE WHEN e IS NULL THEN 0
                WHEN split_part(e, '.', 1) = '10' THEN 0
                ELSE split_part(e, '.', 1)::int END
$$;

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
), ev AS (
    SELECT coalesce(x.fundido_em, e.negocio_id) AS nid, e.data, e.estado, e.vendedor,
           e.contacto, e.razao
      FROM eventos_dossier e
      LEFT JOIN negocios x ON x.negocio_id = e.negocio_id
), dm AS (
    SELECT DISTINCT ON (nid) nid, estado, data, razao
      FROM ev WHERE estado IS NOT NULL
     ORDER BY nid, fase_ordem(estado) DESC, data DESC
), dc AS (
    SELECT nid, max(data) AS data FROM ev WHERE contacto GROUP BY nid
), vd AS (
    SELECT DISTINCT ON (nid) nid, vendedor
      FROM (SELECT nid, data_visita::date AS d, vendedor FROM r WHERE vendedor IS NOT NULL
            UNION ALL
            SELECT nid, data, vendedor FROM ev WHERE vendedor IS NOT NULL) t
     ORDER BY nid, d DESC
), j AS (
    SELECT n.*, s.data AS s_data, s.vendedor AS s_vendedor, s.cliente AS s_cliente,
           s.estado AS s_estado, s.excerto AS s_excerto, s.relatorios AS s_relatorios,
           s.primeiro AS s_primeiro, dm.estado AS d_estado, dm.razao AS d_razao,
           dc.data AS c_data, vd.vendedor AS v_vendedor,
           (dm.estado IS NOT NULL
            AND coalesce(s.estado, '') NOT IN ('8. Fechado', '9. Perdido / Cancelado')
            AND fase_ordem(dm.estado) > fase_ordem(s.estado)) AS pelo_dossier
      FROM negocios n
      LEFT JOIN s ON s.nid = n.negocio_id AND s.k = 1
      LEFT JOIN dm ON dm.nid = n.negocio_id
      LEFT JOIN dc ON dc.nid = n.negocio_id
      LEFT JOIN vd ON vd.nid = n.negocio_id
     WHERE s.nid IS NOT NULL OR dm.nid IS NOT NULL OR dc.nid IS NOT NULL
)
SELECT j.negocio_id, j.cliente_no, coalesce(j.cliente, j.s_cliente) AS cliente,
       j.tipo, coalesce(j.valor_dossier, j.valor) AS valor,
       coalesce(j.inicio, j.s_primeiro) AS inicio,
       j.fechado_em, j.fecho_motivo, j.estado_relacao,
       greatest(j.s_data, j.c_data) AS ultimo_toque,
       coalesce(j.v_vendedor, j.s_vendedor) AS vendedor,
       CASE WHEN j.pelo_dossier THEN j.d_estado ELSE j.s_estado END AS estado,
       CASE WHEN j.pelo_dossier THEN j.d_razao ELSE j.s_excerto END AS excerto,
       coalesce(j.s_relatorios, 0) AS relatorios,
       CASE WHEN EXISTS (SELECT 1 FROM parque_equipamentos q
                          WHERE q.cliente_no = j.cliente_no
                            AND q.entrada < coalesce(j.inicio, j.s_primeiro))
            THEN 'base_instalada' ELSE 'conquista' END AS segmento,
       j.dossier_ref, j.dossier_tipo, j.dossier_data,
       CASE WHEN j.pelo_dossier THEN 'dossier' ELSE 'relatorio' END AS fase_origem
  FROM j;

COMMIT;
