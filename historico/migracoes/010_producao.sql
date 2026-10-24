-- 010_producao.sql
-- O que falta para o Artefacto 2 correr em produção. Idempotente.
--
--   parametros   limiares dos alertas e dos consumíveis fora do código (RNF3)
--   utilizadores quem entra no dashboard, com papel e comercial do ERP
--   sessoes      sessões abertas (cookie)
--   ciclos       registo de cada ciclo noturno (RF2.7), para o dashboard
--                mostrar quando os dados foram atualizados pela última vez

BEGIN;

CREATE TABLE IF NOT EXISTS parametros (
    chave        TEXT PRIMARY KEY,
    valor        NUMERIC NOT NULL,
    descricao    TEXT NOT NULL,
    origem       TEXT NOT NULL,
    alterado_em  TIMESTAMP NOT NULL DEFAULT now(),
    alterado_por TEXT NOT NULL DEFAULT 'sistema'
);

INSERT INTO parametros (chave, valor, descricao, origem) VALUES
 ('dias_negociacao',   14,  'Alerta: dias sem contacto num negócio em proposta, negociação ou aprovação', '§4.5'),
 ('dias_mesmo_estado', 30,  'Alerta: dias sem contacto num negócio aberto', '§4.5'),
 ('dias_sem_contacto', 90,  'Alerta: dias sem contacto que põem o negócio em risco', '§4.5'),
 ('dias_fecho',        180, 'Fecho automático do negócio sem contacto (RF2.8)', '§4.5'),
 ('teto_semanal',      10,  'Máximo de alertas por comercial e por semana', '§5.1'),
 ('k_risco',           1.59,'Consumíveis: silêncio acima deste múltiplo do intervalo típico é "em risco"', '§4.5'),
 ('k_dormente',        3.47,'Consumíveis: silêncio acima deste múltiplo do intervalo típico é "dormente"', '§4.5')
ON CONFLICT (chave) DO NOTHING;

CREATE TABLE IF NOT EXISTS utilizadores (
    login       TEXT PRIMARY KEY,
    nome        TEXT NOT NULL,
    vendedor    TEXT,                       -- nome do comercial no ERP (vendnm)
    papel       TEXT NOT NULL CHECK (papel IN ('comercial', 'gestor')),
    senha_hash  TEXT NOT NULL,
    ativo       BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em   TIMESTAMP NOT NULL DEFAULT now(),
    CHECK (papel = 'gestor' OR vendedor IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS sessoes (
    token      TEXT PRIMARY KEY,
    login      TEXT NOT NULL REFERENCES utilizadores (login) ON DELETE CASCADE,
    criada_em  TIMESTAMP NOT NULL DEFAULT now(),
    expira_em  TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS ciclos (
    id          BIGSERIAL PRIMARY KEY,
    inicio      TIMESTAMP NOT NULL DEFAULT now(),
    fim         TIMESTAMP,
    ok          BOOLEAN,
    relatorios  INTEGER,
    pares       INTEGER,
    erros       INTEGER,
    fechados    INTEGER,
    alertas     INTEGER,
    visitas     TEXT,                       -- extração usada
    mensagem    TEXT
);

-- O estado que vale é o corrigido pelo comercial, quando existe. Todas as
-- vistas e alertas leem daqui, para que uma correção tenha efeito em todo o lado.
CREATE OR REPLACE VIEW pares_efetivos AS
SELECT p.par_id, p.vistamp, p.negocio_id,
       coalesce(a.tipo_corrigido, p.tipo)     AS tipo,
       coalesce(a.estado_corrigido, p.estado) AS estado,
       p.excerto, p.ordem, p.origem, p.criado_em,
       (a.par_id IS NOT NULL)                 AS corrigido
  FROM pares_llm p
  LEFT JOIN avaliacao_pares a ON a.par_id = p.par_id AND a.acao = 'corrigido';

-- Um negócio aberto pelo modelo (NG-X) que o registo passou a ter fica
-- "fundido" nesse negócio (producao.fundir). Os pares não se mexem, para o
-- bloco dado ao modelo continuar igual ao do benchmark; as vistas contam-no
-- como um só negócio.
ALTER TABLE negocios ADD COLUMN IF NOT EXISTS fundido_em TEXT;

-- Uma linha por negócio com pelo menos um relatório: o último sinal, quem o
-- deu e o segmento (RF2.2: base instalada se o cliente tinha equipamento antes
-- de o negócio começar). É a carteira (RF2.1) e a base dos alertas.
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
       n.tipo, n.valor, coalesce(n.inicio, s.primeiro) AS inicio,
       n.fechado_em, n.fecho_motivo, n.estado_relacao,
       s.data AS ultimo_toque, s.vendedor, s.estado, s.excerto, s.relatorios,
       CASE WHEN EXISTS (SELECT 1 FROM parque_equipamentos q
                          WHERE q.cliente_no = n.cliente_no
                            AND q.entrada < coalesce(n.inicio, s.primeiro))
            THEN 'base_instalada' ELSE 'conquista' END AS segmento
  FROM negocios n
  JOIN s ON s.nid = n.negocio_id AND s.k = 1;

COMMIT;
