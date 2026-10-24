-- esquema.sql
-- Esquema actual da base de dados do SAD comercial (esquema public), sem dados.
-- Gerado da base em produção, não escrito à mão: em caso de dúvida, a base manda.
-- Para recriar a base: psql "<URL>" -v ON_ERROR_STOP=1 -f esquema.sql
-- Para regenerar depois de mudar a base:
--   pg_dump "<URL>" --schema-only --no-owner --no-privileges -n public -f esquema.sql
--   (pg_dump 18 ou mais recente; tirar as linhas \restrict / \unrestrict e pôr
--   IF NOT EXISTS nos CREATE SCHEMA)
-- A evolução até aqui está em historico/migracoes/ (001 a 020).
-- Gerado a 24-Out-2026, PostgreSQL 18.6 (Neon), depois da migração 020.

--
-- PostgreSQL database dump
--


-- Dumped from database version 18.6 (fd34222)
-- Dumped by pg_dump version 18.3 (Ubuntu 18.3-1.pgdg22.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: fase_ordem(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.fase_ordem(e text) RETURNS integer
    LANGUAGE sql IMMUTABLE
    AS $$
    SELECT CASE WHEN e IS NULL THEN 0
                WHEN split_part(e, '.', 1) = '10' THEN 0
                ELSE split_part(e, '.', 1)::int END
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: benchmark_entradas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.benchmark_entradas (
    vistamp text NOT NULL,
    cliente_no integer NOT NULL,
    cliente text,
    estrato text NOT NULL,
    mensagem text NOT NULL,
    congelada_em timestamp without time zone DEFAULT now() NOT NULL,
    entrada_version text DEFAULT 'v1'::text NOT NULL,
    linha integer,
    CONSTRAINT benchmark_entradas_estrato_check CHECK ((estrato = ANY (ARRAY['com_negocio_aberto'::text, 'sem_negocio_aberto'::text])))
);


--
-- Name: gold_anotacoes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gold_anotacoes (
    vistamp text NOT NULL,
    entrada_version text NOT NULL,
    comercial boolean NOT NULL,
    pares jsonb DEFAULT '[]'::jsonb NOT NULL,
    duvida boolean DEFAULT false NOT NULL,
    nota text,
    origem text,
    anotador text,
    atualizado_em timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: gold_anotacoes_hist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gold_anotacoes_hist (
    id bigint NOT NULL,
    vistamp text NOT NULL,
    entrada_version text NOT NULL,
    comercial boolean NOT NULL,
    pares jsonb NOT NULL,
    duvida boolean NOT NULL,
    nota text,
    origem text,
    anotador text,
    gravado_em timestamp with time zone DEFAULT now() NOT NULL,
    segundos numeric
);


--
-- Name: alertas_emitidos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alertas_emitidos (
    id bigint NOT NULL,
    negocio_id text,
    regra text NOT NULL,
    emitido_em date NOT NULL,
    vendedor text,
    cliente text,
    estado text,
    dias integer,
    prioridade numeric,
    entregue boolean DEFAULT false NOT NULL,
    notificado boolean DEFAULT true NOT NULL,
    cliente_no integer,
    notificado_em date,
    tratado_em timestamp with time zone,
    tratado_por text,
    CONSTRAINT alertas_alvo CHECK (((negocio_id IS NOT NULL) OR (cliente_no IS NOT NULL)))
);


--
-- Name: alertas_emitidos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.alertas_emitidos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: alertas_emitidos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.alertas_emitidos_id_seq OWNED BY public.alertas_emitidos.id;


--
-- Name: avaliacao_pares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.avaliacao_pares (
    par_id text NOT NULL,
    lote_id text,
    vistamp text NOT NULL,
    negocio_id text,
    acao text NOT NULL,
    estado_proposto text,
    estado_corrigido text,
    tipo_proposto text,
    tipo_corrigido text,
    motivo text NOT NULL,
    corrigido_por text NOT NULL,
    corrigido_em timestamp without time zone DEFAULT now() NOT NULL,
    ratificado boolean DEFAULT false NOT NULL,
    ratificado_por text,
    ratificado_em timestamp without time zone,
    negocio_corrigido text,
    via text DEFAULT 'revisao'::text NOT NULL,
    CONSTRAINT avaliacao_pares_acao_check CHECK ((acao = ANY (ARRAY['corrigido'::text, 'negocio_em_falta'::text]))),
    CONSTRAINT avaliacao_pares_via_check CHECK ((via = ANY (ARRAY['revisao'::text, 'carteira'::text])))
);


--
-- Name: COLUMN avaliacao_pares.via; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.avaliacao_pares.via IS 'Onde o erro foi encontrado: revisao (o lote do dia) ou carteira (o último relatório do negócio). É a da primeira correção do par.';


--
-- Name: avaliacao_pares_hist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.avaliacao_pares_hist (
    id bigint NOT NULL,
    par_id text NOT NULL,
    lote_id text,
    vistamp text NOT NULL,
    negocio_id text,
    acao text NOT NULL,
    estado_proposto text,
    estado_corrigido text,
    tipo_proposto text,
    tipo_corrigido text,
    negocio_corrigido text,
    motivo text NOT NULL,
    corrigido_por text NOT NULL,
    corrigido_em timestamp without time zone NOT NULL,
    ratificado boolean NOT NULL,
    ratificado_por text,
    ratificado_em timestamp without time zone,
    via text NOT NULL,
    substituida_em timestamp without time zone DEFAULT now() NOT NULL,
    substituida_por text NOT NULL
);


--
-- Name: TABLE avaliacao_pares_hist; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.avaliacao_pares_hist IS 'Correções substituídas por uma correção na carteira, tal como estavam antes.';


--
-- Name: avaliacao_pares_hist_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.avaliacao_pares_hist_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: avaliacao_pares_hist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.avaliacao_pares_hist_id_seq OWNED BY public.avaliacao_pares_hist.id;


--
-- Name: benchmark_corridas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.benchmark_corridas (
    corrida_id text NOT NULL,
    modelo text NOT NULL,
    backend text NOT NULL,
    prompt_version text NOT NULL,
    contexto integer,
    n_relatorios integer DEFAULT 0 NOT NULL,
    n_erros integer DEFAULT 0 NOT NULL,
    tokens_in bigint DEFAULT 0 NOT NULL,
    tokens_out bigint DEFAULT 0 NOT NULL,
    segundos numeric,
    iniciada_em timestamp without time zone DEFAULT now() NOT NULL,
    terminada_em timestamp without time zone,
    nota text,
    modelo_id text,
    maquina text,
    esquema_version text,
    prompt_hash text,
    esquema_hash text,
    entrada_version text DEFAULT 'v1'::text NOT NULL
);


--
-- Name: COLUMN benchmark_corridas.prompt_hash; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.benchmark_corridas.prompt_hash IS 'sha256 (12 hex) do SYSTEM_PROMPT usado na corrida';


--
-- Name: benchmark_pares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.benchmark_pares (
    corrida_id text NOT NULL,
    vistamp text NOT NULL,
    ordem smallint NOT NULL,
    negocio_id text,
    tipo text,
    estado text,
    excerto text
);


--
-- Name: benchmark_respostas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.benchmark_respostas (
    corrida_id text NOT NULL,
    vistamp text NOT NULL,
    conteudo_comercial boolean,
    n_pares smallint DEFAULT 0 NOT NULL,
    erro text,
    tokens_in integer,
    tokens_out integer,
    segundos numeric,
    raw text
);


--
-- Name: classificacoes_llm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.classificacoes_llm (
    id integer NOT NULL,
    vistamp text NOT NULL,
    data_visita text,
    hora_visita text,
    vendedor text,
    cliente text,
    unidade_negocio text,
    classificacao text,
    tipo_contacto text,
    duracao_min integer,
    resumo text,
    relatorio text,
    llm_estado text,
    llm_confianca integer,
    llm_justificacao text,
    llm_tokens_in integer,
    llm_tokens_out integer,
    llm_raw text,
    llm_erro integer DEFAULT 0,
    acerto text,
    estado_correto text,
    id_motivo integer DEFAULT 0,
    motivo_falha text,
    criado_em timestamp without time zone DEFAULT now(),
    valor numeric,
    prompt_version text,
    cliente_no integer,
    conteudo_comercial boolean,
    modelo text
);


--
-- Name: COLUMN classificacoes_llm.llm_estado; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.classificacoes_llm.llm_estado IS 'Histórico: estado atribuído ao relatório inteiro pelos prompts v01-a03. A partir do prompt c01 o estado vive em pares_llm.';


--
-- Name: eventos_dossier; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.eventos_dossier (
    negocio_id text NOT NULL,
    dossier_ref text NOT NULL,
    dossier_tipo text NOT NULL,
    data date NOT NULL,
    estado text,
    vendedor text,
    contacto boolean DEFAULT false NOT NULL,
    razao text NOT NULL,
    criado_em timestamp with time zone DEFAULT now() NOT NULL,
    area text
);


--
-- Name: negocios; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.negocios (
    negocio_id text NOT NULL,
    cliente_no integer NOT NULL,
    cliente text,
    tipo text NOT NULL,
    descricao text,
    referencia text,
    inicio date,
    fim date,
    estado_actual text,
    estado_relacao text,
    valor numeric,
    fechado_em date,
    fecho_motivo text,
    criado_por text DEFAULT 'sistema'::text NOT NULL,
    criado_em timestamp without time zone DEFAULT now() NOT NULL,
    fundido_em text,
    fechado_por text,
    ultima_compra date,
    intervalo_compra integer,
    valor_12m numeric,
    valor_dossier numeric,
    dossier_ref text,
    dossier_tipo text,
    dossier_data date,
    fundido_por text,
    fundido_data date,
    CONSTRAINT negocios_check CHECK ((((tipo = 'consumiveis'::text) AND (estado_actual IS NULL)) OR ((tipo <> 'consumiveis'::text) AND (estado_relacao IS NULL)))),
    CONSTRAINT negocios_criado_por_check CHECK ((criado_por = ANY (ARRAY['sistema'::text, 'comercial'::text, 'dossier'::text]))),
    CONSTRAINT negocios_tipo_valido CHECK ((tipo = ANY (ARRAY['equipamento'::text, 'producao'::text, 'consumiveis'::text, 'lead'::text])))
);


--
-- Name: COLUMN negocios.criado_por; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.negocios.criado_por IS 'RF2.9: comercial marca um negócio que o sistema não identificou.';


--
-- Name: pares_llm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pares_llm (
    par_id text NOT NULL,
    vistamp text NOT NULL,
    negocio_id text NOT NULL,
    tipo text NOT NULL,
    estado text,
    excerto text NOT NULL,
    ordem smallint DEFAULT 1 NOT NULL,
    origem text DEFAULT 'llm'::text NOT NULL,
    prompt_version text NOT NULL,
    modelo text NOT NULL,
    criado_em timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT pares_llm_check CHECK ((((tipo = 'consumiveis'::text) AND (estado IS NULL)) OR ((tipo <> 'consumiveis'::text) AND (estado IS NOT NULL)))),
    CONSTRAINT pares_llm_origem_check CHECK ((origem = ANY (ARRAY['llm'::text, 'comercial'::text]))),
    CONSTRAINT pares_llm_tipo_valido CHECK ((tipo = ANY (ARRAY['equipamento'::text, 'producao'::text, 'consumiveis'::text, 'lead'::text])))
);


--
-- Name: TABLE pares_llm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pares_llm IS 'Unidade de análise. O estado só existe para equipamento e produção: os consumíveis não percorrem o ciclo comercial e o seu estado de relação é calculado do histórico de compras, em negocios.estado_relacao.';


--
-- Name: pares_efetivos; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.pares_efetivos AS
 SELECT p.par_id,
    p.vistamp,
    COALESCE(a.negocio_corrigido, p.negocio_id) AS negocio_id,
    COALESCE(a.tipo_corrigido, p.tipo) AS tipo,
    COALESCE(a.estado_corrigido, p.estado) AS estado,
    p.excerto,
    p.ordem,
    p.origem,
    p.criado_em,
    (a.par_id IS NOT NULL) AS corrigido
   FROM (public.pares_llm p
     LEFT JOIN public.avaliacao_pares a ON (((a.par_id = p.par_id) AND (a.acao = 'corrigido'::text))))
  WHERE (a.motivo IS DISTINCT FROM 'não havia conteúdo comercial'::text);


--
-- Name: parque_equipamentos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parque_equipamentos (
    mastamp text NOT NULL,
    cliente_no integer NOT NULL,
    instal date,
    criado_em date,
    entrada date NOT NULL,
    marca text,
    area text
);


--
-- Name: carteira; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.carteira AS
 WITH r AS (
         SELECT COALESCE(x.fundido_em, p.negocio_id) AS nid,
            c.data_visita,
            c.vendedor,
            c.cliente,
            p.estado,
            p.excerto,
            p.criado_em,
            c.unidade_negocio
           FROM ((public.pares_efetivos p
             JOIN public.classificacoes_llm c ON ((c.vistamp = p.vistamp)))
             LEFT JOIN public.negocios x ON ((x.negocio_id = p.negocio_id)))
          WHERE (c.data_visita IS NOT NULL)
        ), s AS (
         SELECT r.nid,
            (r.data_visita)::date AS data,
            r.vendedor,
            r.cliente,
            r.estado,
            r.excerto,
            r.unidade_negocio,
            row_number() OVER (PARTITION BY r.nid ORDER BY r.data_visita DESC, r.criado_em DESC) AS k,
            count(*) OVER (PARTITION BY r.nid) AS relatorios,
            min((r.data_visita)::date) OVER (PARTITION BY r.nid) AS primeiro
           FROM r
        ), ev AS (
         SELECT COALESCE(x.fundido_em, e.negocio_id) AS nid,
            e.data,
            e.estado,
            e.vendedor,
            e.contacto,
            e.razao,
            e.area
           FROM (public.eventos_dossier e
             LEFT JOIN public.negocios x ON ((x.negocio_id = e.negocio_id)))
        ), dm AS (
         SELECT DISTINCT ON (ev.nid) ev.nid,
            ev.estado,
            ev.data,
            ev.razao
           FROM ev
          WHERE (ev.estado IS NOT NULL)
          ORDER BY ev.nid, (public.fase_ordem(ev.estado)) DESC, ev.data DESC
        ), dc AS (
         SELECT ev.nid,
            max(ev.data) AS data
           FROM ev
          WHERE ev.contacto
          GROUP BY ev.nid
        ), da AS (
         SELECT DISTINCT ON (ev.nid) ev.nid,
            ev.area
           FROM ev
          WHERE (ev.area IS NOT NULL)
          ORDER BY ev.nid, ev.data DESC
        ), vd AS (
         SELECT DISTINCT ON (t.nid) t.nid,
            t.vendedor
           FROM ( SELECT r.nid,
                    (r.data_visita)::date AS d,
                    r.vendedor
                   FROM r
                  WHERE (r.vendedor IS NOT NULL)
                UNION ALL
                 SELECT ev.nid,
                    ev.data,
                    ev.vendedor
                   FROM ev
                  WHERE (ev.vendedor IS NOT NULL)) t
          ORDER BY t.nid, t.d DESC
        ), j AS (
         SELECT n.negocio_id,
            n.cliente_no,
            n.cliente,
            n.tipo,
            n.descricao,
            n.referencia,
            n.inicio,
            n.fim,
            n.estado_actual,
            n.estado_relacao,
            n.valor,
            n.fechado_em,
            n.fecho_motivo,
            n.criado_por,
            n.criado_em,
            n.fundido_em,
            n.fechado_por,
            n.ultima_compra,
            n.intervalo_compra,
            n.valor_12m,
            n.valor_dossier,
            n.dossier_ref,
            n.dossier_tipo,
            n.dossier_data,
            n.fundido_por,
            n.fundido_data,
            s.data AS s_data,
            s.vendedor AS s_vendedor,
            s.cliente AS s_cliente,
            s.estado AS s_estado,
            s.excerto AS s_excerto,
            s.relatorios AS s_relatorios,
            s.primeiro AS s_primeiro,
            dm.estado AS d_estado,
            dm.razao AS d_razao,
            dc.data AS c_data,
            vd.vendedor AS v_vendedor,
            s.unidade_negocio AS s_area,
            da.area AS d_area,
            ((dm.estado IS NOT NULL) AND (COALESCE(s.estado, ''::text) <> ALL (ARRAY['8. Fechado'::text, '9. Perdido / Cancelado'::text])) AND (public.fase_ordem(dm.estado) > public.fase_ordem(s.estado))) AS pelo_dossier
           FROM (((((public.negocios n
             LEFT JOIN s ON (((s.nid = n.negocio_id) AND (s.k = 1))))
             LEFT JOIN dm ON ((dm.nid = n.negocio_id)))
             LEFT JOIN dc ON ((dc.nid = n.negocio_id)))
             LEFT JOIN vd ON ((vd.nid = n.negocio_id)))
             LEFT JOIN da ON ((da.nid = n.negocio_id)))
          WHERE ((s.nid IS NOT NULL) OR (dm.nid IS NOT NULL) OR (dc.nid IS NOT NULL))
        )
 SELECT negocio_id,
    cliente_no,
    COALESCE(cliente, s_cliente) AS cliente,
    tipo,
    COALESCE(valor_dossier, valor) AS valor,
    COALESCE(inicio, s_primeiro) AS inicio,
    fechado_em,
    fecho_motivo,
    estado_relacao,
    GREATEST(s_data, c_data) AS ultimo_toque,
    COALESCE(v_vendedor, s_vendedor) AS vendedor,
        CASE
            WHEN pelo_dossier THEN d_estado
            ELSE s_estado
        END AS estado,
        CASE
            WHEN pelo_dossier THEN d_razao
            ELSE s_excerto
        END AS excerto,
    COALESCE(s_relatorios, (0)::bigint) AS relatorios,
        CASE
            WHEN (EXISTS ( SELECT 1
               FROM public.parque_equipamentos q
              WHERE ((q.cliente_no = j.cliente_no) AND (q.entrada < COALESCE(j.inicio, j.s_primeiro))))) THEN 'base_instalada'::text
            ELSE 'conquista'::text
        END AS segmento,
    dossier_ref,
    dossier_tipo,
    dossier_data,
        CASE
            WHEN pelo_dossier THEN 'dossier'::text
            ELSE 'relatorio'::text
        END AS fase_origem,
    COALESCE(s_area, d_area) AS area,
        CASE criado_por
            WHEN 'dossier'::text THEN 'dossier'::text
            WHEN 'comercial'::text THEN 'comercial'::text
            ELSE 'relatorio'::text
        END AS origem
   FROM j;


--
-- Name: ciclos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ciclos (
    id bigint NOT NULL,
    inicio timestamp without time zone DEFAULT now() NOT NULL,
    fim timestamp without time zone,
    ok boolean,
    relatorios integer,
    pares integer,
    erros integer,
    fechados integer,
    alertas integer,
    visitas text,
    mensagem text
);


--
-- Name: ciclos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ciclos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ciclos_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ciclos_id_seq OWNED BY public.ciclos.id;


--
-- Name: classificacoes_llm_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.classificacoes_llm_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: classificacoes_llm_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.classificacoes_llm_id_seq OWNED BY public.classificacoes_llm.id;


--
-- Name: consumo_tratado; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumo_tratado (
    negocio_id text NOT NULL,
    tratado_em timestamp with time zone DEFAULT now() NOT NULL,
    tratado_por text NOT NULL,
    ultima_compra date
);


--
-- Name: gold_anotacoes_hist_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.gold_anotacoes_hist_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gold_anotacoes_hist_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.gold_anotacoes_hist_id_seq OWNED BY public.gold_anotacoes_hist.id;


--
-- Name: lotes_revisao; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lotes_revisao (
    lote_id text NOT NULL,
    vendedor text NOT NULL,
    dia date NOT NULL,
    n_pares integer DEFAULT 0 NOT NULL,
    aberto_em timestamp without time zone DEFAULT now() NOT NULL,
    fechado_em timestamp without time zone
);


--
-- Name: negocios_fechados_auto; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.negocios_fechados_auto (
    negocio_id text NOT NULL,
    fechado_em date NOT NULL,
    ultimo_toque date,
    dias integer
);


--
-- Name: notas_dsr; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notas_dsr (
    chave text NOT NULL,
    valor text DEFAULT ''::text NOT NULL,
    actualizado_em timestamp without time zone DEFAULT now()
);


--
-- Name: parametros; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parametros (
    chave text NOT NULL,
    valor numeric NOT NULL,
    descricao text NOT NULL,
    origem text NOT NULL,
    alterado_em timestamp without time zone DEFAULT now() NOT NULL,
    alterado_por text DEFAULT 'sistema'::text NOT NULL
);


--
-- Name: renovacao_tratada; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.renovacao_tratada (
    cliente_no integer NOT NULL,
    tratado_em timestamp with time zone DEFAULT now() NOT NULL,
    tratado_por text NOT NULL
);


--
-- Name: sessoes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessoes (
    token text NOT NULL,
    login text NOT NULL,
    criada_em timestamp without time zone DEFAULT now() NOT NULL,
    expira_em timestamp without time zone NOT NULL
);


--
-- Name: taxa_ganho_fase; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.taxa_ganho_fase (
    estado text NOT NULL,
    negocios integer NOT NULL,
    ganho numeric NOT NULL,
    ganho_faturacao numeric,
    origem text NOT NULL
);


--
-- Name: utilizadores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.utilizadores (
    login text NOT NULL,
    nome text NOT NULL,
    vendedor text,
    papel text NOT NULL,
    senha_hash text NOT NULL,
    ativo boolean DEFAULT true NOT NULL,
    criado_em timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT utilizadores_check CHECK (((papel = 'gestor'::text) OR (vendedor IS NOT NULL))),
    CONSTRAINT utilizadores_papel_check CHECK ((papel = ANY (ARRAY['comercial'::text, 'gestor'::text])))
);


--
-- Name: alertas_emitidos id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertas_emitidos ALTER COLUMN id SET DEFAULT nextval('public.alertas_emitidos_id_seq'::regclass);


--
-- Name: avaliacao_pares_hist id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.avaliacao_pares_hist ALTER COLUMN id SET DEFAULT nextval('public.avaliacao_pares_hist_id_seq'::regclass);


--
-- Name: ciclos id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ciclos ALTER COLUMN id SET DEFAULT nextval('public.ciclos_id_seq'::regclass);


--
-- Name: classificacoes_llm id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.classificacoes_llm ALTER COLUMN id SET DEFAULT nextval('public.classificacoes_llm_id_seq'::regclass);


--
-- Name: gold_anotacoes_hist id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gold_anotacoes_hist ALTER COLUMN id SET DEFAULT nextval('public.gold_anotacoes_hist_id_seq'::regclass);


--
-- Name: alertas_emitidos alertas_emitidos_negocio_id_regra_emitido_em_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertas_emitidos
    ADD CONSTRAINT alertas_emitidos_negocio_id_regra_emitido_em_key UNIQUE (negocio_id, regra, emitido_em);


--
-- Name: alertas_emitidos alertas_emitidos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertas_emitidos
    ADD CONSTRAINT alertas_emitidos_pkey PRIMARY KEY (id);


--
-- Name: avaliacao_pares_hist avaliacao_pares_hist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.avaliacao_pares_hist
    ADD CONSTRAINT avaliacao_pares_hist_pkey PRIMARY KEY (id);


--
-- Name: avaliacao_pares avaliacao_pares_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.avaliacao_pares
    ADD CONSTRAINT avaliacao_pares_pkey PRIMARY KEY (par_id);


--
-- Name: benchmark_corridas benchmark_corridas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_corridas
    ADD CONSTRAINT benchmark_corridas_pkey PRIMARY KEY (corrida_id);


--
-- Name: benchmark_entradas benchmark_entradas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_entradas
    ADD CONSTRAINT benchmark_entradas_pkey PRIMARY KEY (vistamp, entrada_version);


--
-- Name: benchmark_pares benchmark_pares_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_pares
    ADD CONSTRAINT benchmark_pares_pkey PRIMARY KEY (corrida_id, vistamp, ordem);


--
-- Name: benchmark_respostas benchmark_respostas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_respostas
    ADD CONSTRAINT benchmark_respostas_pkey PRIMARY KEY (corrida_id, vistamp);


--
-- Name: ciclos ciclos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ciclos
    ADD CONSTRAINT ciclos_pkey PRIMARY KEY (id);


--
-- Name: classificacoes_llm classificacoes_llm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.classificacoes_llm
    ADD CONSTRAINT classificacoes_llm_pkey PRIMARY KEY (id);


--
-- Name: classificacoes_llm classificacoes_llm_vistamp_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.classificacoes_llm
    ADD CONSTRAINT classificacoes_llm_vistamp_key UNIQUE (vistamp);


--
-- Name: consumo_tratado consumo_tratado_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumo_tratado
    ADD CONSTRAINT consumo_tratado_pkey PRIMARY KEY (negocio_id);


--
-- Name: eventos_dossier eventos_dossier_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.eventos_dossier
    ADD CONSTRAINT eventos_dossier_pkey PRIMARY KEY (negocio_id, dossier_tipo, dossier_ref);


--
-- Name: gold_anotacoes_hist gold_anotacoes_hist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gold_anotacoes_hist
    ADD CONSTRAINT gold_anotacoes_hist_pkey PRIMARY KEY (id);


--
-- Name: gold_anotacoes gold_anotacoes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gold_anotacoes
    ADD CONSTRAINT gold_anotacoes_pkey PRIMARY KEY (vistamp, entrada_version);


--
-- Name: lotes_revisao lotes_revisao_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lotes_revisao
    ADD CONSTRAINT lotes_revisao_pkey PRIMARY KEY (lote_id);


--
-- Name: lotes_revisao lotes_revisao_vendedor_dia_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lotes_revisao
    ADD CONSTRAINT lotes_revisao_vendedor_dia_key UNIQUE (vendedor, dia);


--
-- Name: negocios_fechados_auto negocios_fechados_auto_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.negocios_fechados_auto
    ADD CONSTRAINT negocios_fechados_auto_pkey PRIMARY KEY (negocio_id);


--
-- Name: negocios negocios_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.negocios
    ADD CONSTRAINT negocios_pkey PRIMARY KEY (negocio_id);


--
-- Name: notas_dsr notas_dsr_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notas_dsr
    ADD CONSTRAINT notas_dsr_pkey PRIMARY KEY (chave);


--
-- Name: parametros parametros_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parametros
    ADD CONSTRAINT parametros_pkey PRIMARY KEY (chave);


--
-- Name: pares_llm pares_llm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pares_llm
    ADD CONSTRAINT pares_llm_pkey PRIMARY KEY (par_id);


--
-- Name: parque_equipamentos parque_equipamentos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parque_equipamentos
    ADD CONSTRAINT parque_equipamentos_pkey PRIMARY KEY (mastamp);


--
-- Name: renovacao_tratada renovacao_tratada_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.renovacao_tratada
    ADD CONSTRAINT renovacao_tratada_pkey PRIMARY KEY (cliente_no);


--
-- Name: sessoes sessoes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessoes
    ADD CONSTRAINT sessoes_pkey PRIMARY KEY (token);


--
-- Name: taxa_ganho_fase taxa_ganho_fase_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.taxa_ganho_fase
    ADD CONSTRAINT taxa_ganho_fase_pkey PRIMARY KEY (estado);


--
-- Name: utilizadores utilizadores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.utilizadores
    ADD CONSTRAINT utilizadores_pkey PRIMARY KEY (login);


--
-- Name: ix_alertas_cliente; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alertas_cliente ON public.alertas_emitidos USING btree (cliente_no, regra);


--
-- Name: ix_alertas_negocio; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alertas_negocio ON public.alertas_emitidos USING btree (negocio_id, regra);


--
-- Name: ix_alertas_semana; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_alertas_semana ON public.alertas_emitidos USING btree (vendedor, emitido_em);


--
-- Name: ix_aval_hist_par; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aval_hist_par ON public.avaliacao_pares_hist USING btree (par_id);


--
-- Name: ix_aval_lote; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aval_lote ON public.avaliacao_pares USING btree (lote_id);


--
-- Name: ix_aval_rat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_aval_rat ON public.avaliacao_pares USING btree (ratificado, corrigido_em);


--
-- Name: ix_bpares_vistamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_bpares_vistamp ON public.benchmark_pares USING btree (vistamp);


--
-- Name: ix_class_cliente_no; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_class_cliente_no ON public.classificacoes_llm USING btree (cliente_no);


--
-- Name: ix_class_data; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_class_data ON public.classificacoes_llm USING btree (data_visita);


--
-- Name: ix_negocios_abertos; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_negocios_abertos ON public.negocios USING btree (fechado_em) WHERE (fechado_em IS NULL);


--
-- Name: ix_negocios_cliente; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_negocios_cliente ON public.negocios USING btree (cliente_no, tipo);


--
-- Name: ix_pares_negocio; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pares_negocio ON public.pares_llm USING btree (negocio_id, criado_em DESC);


--
-- Name: ix_pares_vistamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_pares_vistamp ON public.pares_llm USING btree (vistamp);


--
-- Name: ix_parque_cliente; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_parque_cliente ON public.parque_equipamentos USING btree (cliente_no, entrada);


--
-- Name: ux_alertas_cliente; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_alertas_cliente ON public.alertas_emitidos USING btree (cliente_no, regra, emitido_em) WHERE (negocio_id IS NULL);


--
-- Name: alertas_emitidos alertas_emitidos_negocio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertas_emitidos
    ADD CONSTRAINT alertas_emitidos_negocio_id_fkey FOREIGN KEY (negocio_id) REFERENCES public.negocios(negocio_id) ON DELETE CASCADE;


--
-- Name: avaliacao_pares avaliacao_pares_lote_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.avaliacao_pares
    ADD CONSTRAINT avaliacao_pares_lote_id_fkey FOREIGN KEY (lote_id) REFERENCES public.lotes_revisao(lote_id) ON DELETE SET NULL;


--
-- Name: benchmark_pares benchmark_pares_corrida_id_vistamp_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_pares
    ADD CONSTRAINT benchmark_pares_corrida_id_vistamp_fkey FOREIGN KEY (corrida_id, vistamp) REFERENCES public.benchmark_respostas(corrida_id, vistamp) ON DELETE CASCADE;


--
-- Name: benchmark_respostas benchmark_respostas_corrida_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.benchmark_respostas
    ADD CONSTRAINT benchmark_respostas_corrida_id_fkey FOREIGN KEY (corrida_id) REFERENCES public.benchmark_corridas(corrida_id) ON DELETE CASCADE;


--
-- Name: negocios_fechados_auto negocios_fechados_auto_negocio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.negocios_fechados_auto
    ADD CONSTRAINT negocios_fechados_auto_negocio_id_fkey FOREIGN KEY (negocio_id) REFERENCES public.negocios(negocio_id) ON DELETE CASCADE;


--
-- Name: pares_llm pares_llm_negocio_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pares_llm
    ADD CONSTRAINT pares_llm_negocio_id_fkey FOREIGN KEY (negocio_id) REFERENCES public.negocios(negocio_id) ON DELETE CASCADE;


--
-- Name: pares_llm pares_llm_vistamp_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pares_llm
    ADD CONSTRAINT pares_llm_vistamp_fkey FOREIGN KEY (vistamp) REFERENCES public.classificacoes_llm(vistamp) ON DELETE CASCADE;


--
-- Name: sessoes sessoes_login_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessoes
    ADD CONSTRAINT sessoes_login_fkey FOREIGN KEY (login) REFERENCES public.utilizadores(login) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--


