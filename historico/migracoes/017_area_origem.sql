-- 017_area_origem.sql (15-Out-2026)
-- Filtros por área e por origem do negócio.
--   área    a unidade de negócio do relatório mais recente do negócio (campo do ERP); sem
--           relatório, a área mais frequente nas linhas do dossier mais recente
--   origem  relatorio (aberto pelo classificador ou pelo registo), comercial (acrescentado na
--           revisão do dia) ou dossier (aberto pelo PHC)
-- A vista carteira ganha as duas colunas no fim; o resto é o da 016.

BEGIN;

ALTER TABLE eventos_dossier ADD COLUMN IF NOT EXISTS area TEXT;

CREATE OR REPLACE VIEW carteira AS
WITH r AS (
    SELECT coalesce(x.fundido_em, p.negocio_id) AS nid, c.data_visita, c.vendedor,
           c.cliente, p.estado, p.excerto, p.criado_em, c.unidade_negocio
      FROM pares_efetivos p
      JOIN classificacoes_llm c ON c.vistamp = p.vistamp
      LEFT JOIN negocios x ON x.negocio_id = p.negocio_id
     WHERE c.data_visita IS NOT NULL
), s AS (
    SELECT nid, data_visita::date AS data, vendedor, cliente, estado, excerto, unidade_negocio,
           row_number() OVER (PARTITION BY nid ORDER BY data_visita DESC, criado_em DESC) AS k,
           count(*) OVER (PARTITION BY nid) AS relatorios,
           min(data_visita::date) OVER (PARTITION BY nid) AS primeiro
      FROM r
), ev AS (
    SELECT coalesce(x.fundido_em, e.negocio_id) AS nid, e.data, e.estado, e.vendedor,
           e.contacto, e.razao, e.area
      FROM eventos_dossier e
      LEFT JOIN negocios x ON x.negocio_id = e.negocio_id
), dm AS (
    SELECT DISTINCT ON (nid) nid, estado, data, razao
      FROM ev WHERE estado IS NOT NULL
     ORDER BY nid, fase_ordem(estado) DESC, data DESC
), dc AS (
    SELECT nid, max(data) AS data FROM ev WHERE contacto GROUP BY nid
), da AS (
    SELECT DISTINCT ON (nid) nid, area FROM ev WHERE area IS NOT NULL ORDER BY nid, data DESC
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
           s.unidade_negocio AS s_area, da.area AS d_area,
           (dm.estado IS NOT NULL
            AND coalesce(s.estado, '') NOT IN ('8. Fechado', '9. Perdido / Cancelado')
            AND fase_ordem(dm.estado) > fase_ordem(s.estado)) AS pelo_dossier
      FROM negocios n
      LEFT JOIN s ON s.nid = n.negocio_id AND s.k = 1
      LEFT JOIN dm ON dm.nid = n.negocio_id
      LEFT JOIN dc ON dc.nid = n.negocio_id
      LEFT JOIN vd ON vd.nid = n.negocio_id
      LEFT JOIN da ON da.nid = n.negocio_id
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
       CASE WHEN j.pelo_dossier THEN 'dossier' ELSE 'relatorio' END AS fase_origem,
       coalesce(j.s_area, j.d_area) AS area,
       CASE j.criado_por WHEN 'dossier' THEN 'dossier' WHEN 'comercial' THEN 'comercial'
            ELSE 'relatorio' END AS origem
  FROM j;

COMMIT;
