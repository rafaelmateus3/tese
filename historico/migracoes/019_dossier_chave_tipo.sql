-- 019: o número de um dossier no PHC só é único dentro do tipo (19-Out-2026).
-- A chave dos eventos passa a incluir o tipo, para que uma proposta e uma encomenda com
-- o mesmo número, ligadas ao mesmo negócio, não se anulem uma à outra.
BEGIN;
ALTER TABLE eventos_dossier DROP CONSTRAINT IF EXISTS eventos_dossier_pkey;
ALTER TABLE eventos_dossier ADD PRIMARY KEY (negocio_id, dossier_tipo, dossier_ref);
COMMIT;
