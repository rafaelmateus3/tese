/* SAD comercial: a página de cada comercial e as vistas da gestão.

   Princípio de desenho: os requisitos do Quadro 4.2 aparecem dentro da
   informação e não ao lado dela.
     RF2.1  cada comercial tem a sua página (#/); a gestão tem a equipa, o
            pipeline agregado e a qualidade da classificação
     RF2.2  a repartição base instalada / conquista é a cor das barras e um
            ponto junto a cada cliente, em todas as vistas
     RF2.3-5 os alertas são a lista «Para contactar», escrita em linguagem de
            comercial; o excedente do teto fica em «outros sinais»
     RF2.6  cada indicador tem um «i» com fórmula, fonte, problema e limites
     RF2.8  «fecha sozinho daqui a N dias» e as saídas do pipeline por motivo;
            o comercial fecha na carteira (ganho, perdido, não avançou)
     Dossiers do PHC: a fase, o valor, o contacto e o comercial podem vir de um dossier,
            sempre com a razão à vista («fase pelo PHC», «aberto pelo PHC», histórico)
     RF1.3, RF1.7, RF2.9  a revisão do dia mostra o excerto; corrige-se tocando
            no campo errado, desfaz-se, e acrescenta-se o negócio em falta
   As funções de administração (qualidade, ratificação, parâmetros) só existem
   no menu do gestor. */

const { useState, useEffect, useCallback, useMemo } = React;

/* ------------------------------------------------------------ formatação e termos */
const EUR = (v) => (v || 0).toLocaleString("pt-PT", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const PCT = (v) => Math.round(v || 0) + "%";
const DIAS = (n) => (n === 1 ? "1 dia" : `${n} dias`);
const dataDe = (s) => new Date(s + "T12:00:00");
const DATA_LONGA = (s) => dataDe(s).toLocaleDateString("pt-PT", { weekday: "long", day: "numeric", month: "long" });
const DATA_CURTA = (s) => dataDe(s).toLocaleDateString("pt-PT", { day: "numeric", month: "short" });
const numEstado = (e) => (e ? parseInt(e, 10) : null);

/* A base de dados guarda os dez estados do
   Quadro 4.2 tal como estão; aqui muda só o que o comercial lê. */
const FASE = {
  "1. Lead / Prospeção": "Prospeção",
  "2. Qualificação": "Levantamento de necessidades",
  "3. Proposta / Orçamento": "Orçamento enviado",
  "4. Negociação": "Em negociação",
  "5. Aprovação Interna": "Decisão do cliente",
  "6. Encomenda Confirmada": "Adjudicado",
  "7. Em Produção / Entrega": "Em produção / entrega",
  "8. Fechado": "Entregue",
  "9. Perdido / Cancelado": "Perdido",
  "10. Indeterminado": "Por perceber",
};
const nomeEstado = (e) => (e ? FASE[e] || e.replace(/^\d+\.\s*/, "") : "sem fase");
const TIPO = { equipamento: "Equipamento", producao: "Produção", consumiveis: "Consumíveis", lead: "Lead" };
const SEGMENTO = { base_instalada: "Cliente com máquina", conquista: "Cliente novo" };
const CICLO = ["equipamento", "producao", "lead"];
/* Áreas de negócio do ERP (unidade de negócio do relatório), com nomes legíveis. */
const AREA = { "AREA A": "Área A", "AREA B": "Área B",
  "AREA C": "Área C", "AREA D": "Área D", "ESPECIFICA": "Específica" };
const nomeArea = (a) => (a ? AREA[a] || a : "sem área");
/* Origem do negócio: aberto a partir de um relatório (pelo sistema ou pelo comercial) ou pelo PHC. */
const ORIGENS = [["", "Todas as origens"], ["relatorio", "Abertos por relatório"], ["dossier", "Abertos pelo PHC"]];
const daOrigem = (n, o) => !o || (o === "dossier" ? n.origem === "dossier" : n.origem !== "dossier");

/* Histórico de ganho por fase (Quadro 6.9, §6.4). Adjudicado e em produção já são ganho. */
const FASES_GANHAS = ["6. Encomenda Confirmada", "7. Em Produção / Entrega"];
const taxaDe = (taxas, e) => (FASES_GANHAS.includes(e) ? 1 : ((taxas || {})[e] || {}).ganho ?? null);
const ponderado = (lista, taxas) => lista.reduce((s, n) => s + (n.valor || 0) * (taxaDe(taxas, n.estado) || 0), 0);

/* Funil calculado no navegador a partir de uma lista de negócios, para seguir os filtros. */
function funilDe(lista) {
  const por = {};
  for (const n of lista) {
    if (!n.estado) continue;
    const e = por[n.estado] || (por[n.estado] = { estado: n.estado, negocios: 0, valor: 0, base_instalada: 0, conquista: 0 });
    e.negocios += 1; e.valor += n.valor || 0; e[n.segmento] = (e[n.segmento] || 0) + 1;
  }
  return Object.values(por).sort((a, b) => numEstado(a.estado) - numEstado(b.estado));
}

/* O estado da relação de consumíveis não é uma fase do ciclo comercial: é
   calculado da periodicidade de compra. Leva família visual própria, com
   ícone e rótulo, para que nunca seja lido como uma das dez fases. */
const RELACAO = {
  "0. Pontual": { cor: "var(--tinta-3)", icone: "○", rotulo: "Compra pontual" },
  "1. Activa": { cor: "var(--bom)", icone: "●", rotulo: "Compra regular" },
  "2. Em risco": { cor: "var(--aviso)", icone: "▲", rotulo: "Compra atrasada" },
  "3. Dormente": { cor: "var(--critico)", icone: "■", rotulo: "Deixou de comprar" },
};

/* Os avisos em linguagem de comercial: o tipo, o que se passa e porque aparece.
   `porque` recebe os parâmetros, para dizer o limiar que fez disparar o aviso. */
const REGRAS = {
  negociacao_parada: { nivel: "aviso", tipo: "Sem resposta",
    frase: (a) => <>{nomeEstado(a.estado)}, sem contacto há <strong>{DIAS(a.dias)}</strong></>,
    porque: (p) => `Avisamos quando um orçamento ou negociação fica ${p.dias_negociacao} dias sem contacto.` },
  encomenda_parada: { nivel: "aviso", tipo: "Adjudicado parado",
    frase: (a) => <>Adjudicado há <strong>{DIAS(a.dias)}</strong>, ainda sem produção nem entrega.
      Pode faltar o pagamento do cliente ou a nossa encomenda ao fornecedor</>,
    porque: (p) => `Avisamos quando um negócio fica ${p.dias_mesmo_estado} dias adjudicado sem avançar.` },
  sem_contacto: { nivel: "critico", tipo: "Negócio parado",
    frase: (a) => <>Sem contacto há <strong>{DIAS(a.dias)}</strong>{a.estado ? <>, em «{nomeEstado(a.estado)}»</> : ""}</>,
    porque: (p) => `Avisamos aos ${p.dias_sem_contacto} dias sem contacto. Aos ${p.dias_fecho} o negócio fecha sozinho.` },
  base_sem_contacto: { nivel: "aviso", tipo: "Cliente sem visita",
    frase: (a) => <>Cliente com máquina sem visita há <strong>{DIAS(a.dias)}</strong> e sem negócio aberto</>,
    porque: (p) => `Avisamos quando um cliente com máquina fica ${p.dias_base_sem_contacto} dias sem visita.` },
  mesmo_estado: { nivel: "aviso", tipo: "Sem avanço",
    frase: (a) => <>{DIAS(a.dias)} sem contacto</>, porque: () => "" },
};

const DIA_SEMANA = ["todos os dias", "segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"];


/* ------------------------------------------------------------ utilidades */
function usarDados(carregar, deps) {
  const [dados, setDados] = useState(null);
  const [erro, setErro] = useState(null);
  const recarregar = useCallback(() => {
    setErro(null);
    carregar().then(setDados).catch(setErro);
  }, deps);
  useEffect(recarregar, [recarregar]);
  return [dados, erro, recarregar];
}

function usarRota() {
  const ler = () => (location.hash.replace(/^#\/?/, "") || "").split("/").map(decodeURIComponent).filter(Boolean);
  const [rota, setRota] = useState(ler);
  useEffect(() => {
    const f = () => { setRota(ler()); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return rota;
}
const ir = (...partes) => { location.hash = "#/" + partes.map(encodeURIComponent).join("/"); };

function Erro({ erro }) {
  if (!erro) return null;
  return <div className="cartao" style={{ borderColor: "var(--critico)" }}>
    <strong>Não foi possível carregar.</strong>
    <p className="legenda" style={{ margin: "6px 0 0" }}>{String(erro.message || erro)}</p>
  </div>;
}
const Carregar = () => <p className="vazio">a carregar…</p>;

/* RF2.6: a proveniência mora num «i» junto ao indicador. */
function Info({ p, dir }) {
  if (!p) return null;
  return <details className={"info" + (dir ? " dir" : "")}>
    <summary aria-label="Como é calculado" title="Como é calculado">i</summary>
    <dl className="caixa">
      <dt>Como é calculado</dt><dd>{p.formula}.</dd>
      {p.limiares && <><dt>Limiares</dt><dd>{p.limiares}.</dd></>}
      <dt>Fonte</dt><dd>{p.fonte}.</dd>
      {p.problema && <><dt>Responde a</dt><dd>{p.problema}{p.requisito ? ` (${p.requisito})` : ""}.</dd></>}
      {p.limitacao && <><dt>O que não cobre</dt><dd>{p.limitacao}.</dd></>}
    </dl>
  </details>;
}

function Seg({ s }) {
  if (!s) return null;
  const base = s === "base_instalada";
  return <span className="seg"><i className={"ponto " + (base ? "base" : "conquista")} />{SEGMENTO[s]}</span>;
}

function Etapa({ e }) {
  const n = numEstado(e);
  if (!n) return <span className="etapa sub">sem estado</span>;
  const cls = n === 8 ? " ganho" : n === 9 ? " perdido" : "";
  return <span className="etapa" title={e}><b className={cls.trim()}>{n}</b>{nomeEstado(e)}</span>;
}

function Relacao({ e }) {
  const r = RELACAO[e] || { cor: "var(--tinta-3)", icone: "·", rotulo: e };
  return <span className="relacao"><span className="ic" style={{ color: r.cor }}>{r.icone}</span>{r.rotulo}</span>;
}

function Divisao({ base, conquista, formatar, chaves = true }) {
  const t = (base || 0) + (conquista || 0);
  const pb = t ? (base / t) * 100 : 0;
  return <>
    <div className="divisao" role="img" aria-label={`Clientes com máquina ${PCT(pb)}, clientes novos ${PCT(100 - pb)}`}>
      {t > 0 && base > 0 && <i className="b" style={{ width: pb + "%" }} />}
      {t > 0 && conquista > 0 && <i className="c" style={{ width: 100 - pb + "%" }} />}
    </div>
    {chaves && <div className="chaves">
      <span className="chave"><i className="ponto base" />{SEGMENTO.base_instalada} {formatar ? formatar(base) : PCT(pb)}</span>
      <span className="chave"><i className="ponto conquista" />{SEGMENTO.conquista} {formatar ? formatar(conquista) : PCT(100 - pb)}</span>
    </div>}
  </>;
}

function Tile({ r, n, s, info, onClick, children }) {
  return <div className={"tile" + (onClick ? " acao" : "")} onClick={onClick}
    role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined}
    onKeyDown={onClick ? (e) => e.key === "Enter" && onClick() : undefined}>
    <div className="r">{r}{info}</div>
    <div className="n">{n}</div>
    {children}
    {s && <div className="s">{s}</div>}
  </div>;
}

/* ------------------------------------------------------------ peças partilhadas */

/* Funil: número escrito em cada linha; carregar num estado filtra a carteira. */
function Funil({ estados, filtro, setFiltro }) {
  const max = Math.max(...estados.map((e) => e.negocios), 1);
  if (!estados.length) return <p className="vazio">Ainda não há negócios classificados.</p>;
  return <div className="funil">
    {estados.map((e) => (
      <button key={e.estado} className="funil-linha" aria-pressed={filtro === e.estado}
        onClick={() => setFiltro && setFiltro(filtro === e.estado ? "" : e.estado)}
        title={`${e.estado}: ${e.base_instalada} em base instalada, ${e.conquista} em conquista`}>
        <span className="rot"><Etapa e={e.estado} /></span>
        <span className="trilho">
          {e.base_instalada > 0 && <i className="b" style={{ width: (e.base_instalada / max) * 100 + "%" }} />}
          {e.conquista > 0 && <i className="c" style={{ width: (e.conquista / max) * 100 + "%" }} />}
        </span>
        <span className="val"><b>{e.negocios}</b>{e.valor > 0 && <span> · {EUR(e.valor)}</span>}</span>
      </button>))}
  </div>;
}

function Chaves() {
  return <div className="chaves">
    <span className="chave"><i className="ponto base" />Cliente com máquina: já tinha equipamento nosso</span>
    <span className="chave"><i className="ponto conquista" />Cliente novo: ainda não tinha</span>
  </div>;
}

function Historia({ negocioId }) {
  const [d, erro] = usarDados(() => API.negocio(negocioId), [negocioId]);
  if (erro) return <p className="erro">{erro.message}</p>;
  if (!d) return <Carregar />;
  return <ol className="historia">
    {d.relatos.map((h, i) => (
      <li key={i} className={h.origem === "dossier" ? "phc" : ""}>
        <div className="quando">{DATA_LONGA(h.data)}{h.vendedor && <> · {h.vendedor}</>}
          {h.origem === "dossier" && <> · <span className="pilula phc">PHC</span></>}
          {h.corrigido && <> · <span className="pilula humano">corrigido</span></>}
          {h.origem === "comercial" && <> · <span className="pilula humano">acrescentado pelo comercial</span></>}</div>
        <div>{h.estado ? <Etapa e={h.estado} /> : <span className="sub">{TIPO[h.tipo]}</span>}</div>
        {h.origem === "dossier"
          ? <div className="razao">{h.excerto}</div>
          : <div className="excerto">“{h.excerto}”</div>}
      </li>))}
  </ol>;
}

/* ------------------------------------------------------------ ícones
   Traço simples, herdam a cor do texto. Servem de âncora visual para quem
   não lê a página: telefone = contactar, lista = rever, pasta = negócios. */
const ICONE = {
  contactar: "M5 4h3l2 5-2.5 1.5a11 11 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2",
  rever: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  carteira: "M3 8h18v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM8 8V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v3M3 13h18",
  seta: "M9 6l6 6-6 6",
  visto: "M5 12l5 5 9-10",
  lapis: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  desfazer: "M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
  tema: "M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18zM12 3v18M12 7h4M12 11h5M12 15h4",
};
function Icone({ n, t = 20 }) {
  return <svg className="icone" width={t} height={t} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={ICONE[n]} /></svg>;
}

/* Um botão que espera pela resposta do servidor antes de deixar carregar outra vez. */
function Acao({ className = "sec", onClick, children, title }) {
  const [a, setA] = useState(false);
  return <button className={className} disabled={a} title={title}
    onClick={async () => { setA(true); try { await onClick(); } catch (e) { alert(e.message); } finally { setA(false); } }}>
    {children}</button>;
}

/* ------------------------------------------------------------ avisos */

/* Um aviso: o tipo, quem, porquê, quanto vale, o último relato e o que fazer.
   Usado na página do comercial e na vista Equipa. */
function Sinal({ a, fecho, comercial, tratar, param }) {
  const [historia, setHistoria] = useState(false);
  const r = REGRAS[a.regra] || { nivel: "aviso", tipo: a.regra, frase: () => DIAS(a.dias), porque: () => "" };
  const faltam = a.negocio_id && a.ultimo_toque ? fecho - a.dias : null;
  return <article className={"sinal " + r.nivel}>
    <div className="sinal-cab">
      <div className="quem">
        <span className={"tipo-aviso " + r.nivel}>{r.tipo}</span>
        <span className="cliente">{a.cliente}</span>
        <span className="meta"><Seg s={a.segmento} />{a.tipo && <span>{TIPO[a.tipo] || a.tipo}</span>}
          {comercial && <span>{a.vendedor}</span>}</span>
      </div>
      {a.valor > 0 && <div className="valor">{EUR(a.valor)}</div>}
    </div>
    <p className="porque">{r.frase(a)}.</p>
    {param && r.porque(param) && <p className="motivo">Porque vês isto: {r.porque(param)}</p>}
    {a.regra === "sem_contacto" && faltam > 0 && faltam <= 60 &&
      <p className="prazo">Fecha sozinho daqui a {DIAS(faltam)} se não houver contacto.</p>}
    {a.excerto && <blockquote className="relato">
      <span className="quando">{a.ultimo_toque ? "Último registo, " + DATA_CURTA(a.ultimo_toque) : "Último registo"}</span>
      {a.excerto}</blockquote>}
    {(a.negocio_id || tratar) && <div className="botoes">
      {a.negocio_id && <button className="sec" aria-expanded={historia} onClick={() => setHistoria(!historia)}>
        {historia ? "Esconder histórico" : "Ver histórico"}</button>}
      {tratar && <Acao className="sec forte" title="Tira o aviso da lista sem mudar a fase do negócio"
        onClick={() => tratar(a.id)}><Icone n="visto" t={16} /> Já tratei</Acao>}
    </div>}
    {historia && <div className="historia-caixa"><Historia negocioId={a.negocio_id} /></div>}
  </article>;
}

function SinalConsumo({ c, tratar }) {
  const dormente = c.estado === "3. Dormente";
  return <article className={"sinal " + (dormente ? "critico" : "aviso")}>
    <div className="sinal-cab">
      <div className="quem">
        <span className={"tipo-aviso " + (dormente ? "critico" : "aviso")}>{dormente ? "Deixou de comprar" : "Consumíveis atrasados"}</span>
        <span className="cliente">{c.cliente}</span>
        <span className="meta"><span>Consumíveis</span></span>
      </div>
      {c.valor > 0 && c.ultima_compra && <div className="valor">{EUR(c.valor)}<span className="valor-nota">últimos 12 meses</span></div>}
    </div>
    {c.dias_sem_compra != null && <p className="porque">{c.intervalo_compra
      ? <>Costuma comprar a cada <strong>{DIAS(c.intervalo_compra)}</strong>; a última compra foi há <strong>{DIAS(c.dias_sem_compra)}</strong>.</>
      : <>A última compra foi há <strong>{DIAS(c.dias_sem_compra)}</strong>.</>}</p>}
    <p className="motivo">Porque vês isto: {dormente
      ? "o silêncio já vai em mais do triplo do ritmo habitual deste cliente."
      : "a compra está atrasada face ao ritmo habitual deste cliente."}</p>
    {c.excerto && <blockquote className="relato"><span className="quando">Último relatório, {DATA_CURTA(c.ultimo_toque)}</span>{c.excerto}</blockquote>}
    {tratar && <div className="botoes">
      <Acao className="sec forte" title="Tira o cliente da lista até à próxima compra (no máximo 30 dias)"
        onClick={() => tratar(c.negocio_id)}><Icone n="visto" t={16} /> Já tratei</Acao>
    </div>}
  </article>;
}

/* Um cliente para propor renovação: máquina mais recente com muitos anos, sem negócio
   de equipamento aberto. É uma oportunidade, não um atraso: leva a cor da marca. */
function SinalRenovacao({ c, anos, tratar }) {
  return <article className="sinal oportunidade">
    <div className="sinal-cab">
      <div className="quem">
        <span className="tipo-aviso oportunidade">Renovar máquina</span>
        <span className="cliente">{c.cliente}</span>
        <span className="meta"><span>{c.maquinas} {c.maquinas === 1 ? "máquina" : "máquinas"} no parque</span>
          {c.marca && <span>a mais recente: {c.marca}</span>}</span>
      </div>
      {c.valor_12m > 0 && <div className="valor">{EUR(c.valor_12m)}<span className="valor-nota">consumíveis, 12 meses</span></div>}
    </div>
    <p className="porque">{c.antes_de_2004
      ? <>A máquina mais recente já estava no parque <strong>antes de 2004</strong>.</>
      : <>A máquina mais recente entrou no parque há <strong>{c.anos} anos</strong> ou mais.</>}</p>
    <p className="motivo">Porque vês isto: o cliente compra ou é visitado, não tem negócio de equipamento aberto,
      e a última máquina tem {anos} anos ou mais. A maioria dos clientes volta a comprar antes disso.</p>
    {c.excerto && <blockquote className="relato"><span className="quando">Última visita, {DATA_CURTA(c.ultima_visita)}</span>{c.excerto}</blockquote>}
    {tratar && <div className="botoes">
      <Acao className="sec forte" title="Tira o cliente desta lista durante um ano"
        onClick={() => tratar(c.cliente_no)}><Icone n="visto" t={16} /> Já tratei</Acao>
    </div>}
  </article>;
}

/* Lista de avisos com os primeiros N à vista e o resto recolhido (vista Equipa). */
function Sinais({ lista, n = 8, fecho, comercial, resto }) {
  return <>
    <div className="sinais">{lista.slice(0, n).map((a) => <Sinal key={a.id} a={a} fecho={fecho} comercial={comercial} />)}</div>
    {lista.length > n && <details className="mais"><summary>{resto(lista.length - n)}</summary>
      <div className="sinais">{lista.slice(n).map((a) => <Sinal key={a.id} a={a} fecho={fecho} comercial={comercial} />)}</div>
    </details>}
  </>;
}

/* ------------------------------------------------------------ página do comercial
   Três separadores, um por tarefa: contactar, revisão do dia, negócios. No
   telemóvel ficam numa barra fixa em baixo; no computador, na faixa do topo. A
   rota guarda o separador, para o «voltar» da revisão regressar ao sítio certo. */

const ABAS = ["contactar", "rever", "carteira"];

function PaginaComercial({ vendedor, eu, meta, dia, aba }) {
  const [p, erro, recarregar] = usarDados(() => API.pagina(vendedor), [vendedor]);
  if (erro) return <Erro erro={erro} />;
  if (!p) return <Carregar />;
  const base = p.proprio ? [] : ["comercial", vendedor];
  if (dia) return <RevisaoDia vendedor={vendedor} dia={dia} meta={meta} proprio={p.proprio}
    voltar={() => { ir(...base, "rever"); recarregar(); }} />;
  return <Resumo p={p} eu={eu} meta={meta} base={base} aba={aba} recarregar={recarregar} />;
}

function Resumo({ p, eu, meta, base, aba, recarregar }) {
  const proprio = p.proprio;
  const notificados = p.alertas.filter((a) => a.notificado);
  const pendentes = p.dias.filter((d) => !d.fechado);
  const nContactar = notificados.length + p.consumo.length;
  const contas = { contactar: nContactar, rever: pendentes.length, carteira: p.negocios.length };
  const atual = ABAS.includes(aba) ? aba : nContactar ? "contactar" : pendentes.length ? "rever" : "carteira";
  const mudar = (k) => ir(...base, k);
  const nome = proprio ? eu.nome.split(" ")[0] : p.vendedor;
  const mexe = proprio || eu.papel === "gestor";

  const frase = nContactar + pendentes.length === 0
    ? (proprio ? "Está tudo em dia. Podes ver os teus negócios." : "Não tem nada pendente.")
    : <>{proprio ? "Esta semana tens " : "Esta semana tem "}
        {nContactar > 0 && <strong>{nContactar} {nContactar === 1 ? "cliente" : "clientes"} para contactar</strong>}
        {nContactar > 0 && pendentes.length > 0 && " e "}
        {pendentes.length > 0 && <strong>{pendentes.length} {pendentes.length === 1 ? "dia" : "dias"} por rever</strong>}.</>;

  const ROT = { contactar: "Contactar", rever: "Revisão", carteira: "Negócios" };
  const DESC = { contactar: nContactar === 1 ? "cliente para contactar" : "clientes para contactar",
    rever: pendentes.length === 1 ? "dia por rever" : "dias por rever",
    carteira: "negócios abertos" };

  return <>
    <section className="hoje">
      {!proprio && <a className="migalha" href="#/">← Equipa</a>}
      <h1>{proprio ? `Olá, ${nome}` : `Página de ${nome}`}</h1>
      <p className="frase">{frase}</p>
      <nav className="abas-topo" aria-label="Secções">
        {ABAS.map((k) => <button key={k} className="aba-cartao" aria-current={atual === k ? "page" : undefined} onClick={() => mudar(k)}>
          <Icone n={k} t={22} />
          <span className="n">{contas[k]}</span>
          <span className="r">{DESC[k]}</span>
        </button>)}
      </nav>
    </section>
    {!proprio && <p className="aviso-gestor">Vês a página como o comercial a vê. A revisão do dia cabe a ele;
      nos negócios podes fechar e corrigir.</p>}

    {atual === "contactar" && <AbaContactar p={p} recarregar={recarregar} />}
    {atual === "rever" && <AbaRever p={p} abrirDia={(d) => ir(...base, "dia", d)} />}
    {atual === "carteira" && <Carteira p={p} meta={meta} mexe={mexe} recarregar={recarregar} />}

    <nav className="abas-baixo" aria-label="Secções">
      {ABAS.map((k) => <button key={k} aria-current={atual === k ? "page" : undefined} onClick={() => mudar(k)}>
        <span className="ic"><Icone n={k} />{contas[k] > 0 && k !== "carteira" && <b>{contas[k]}</b>}</span>
        {ROT[k]}
      </button>)}
    </nav>
  </>;
}

function Cab({ titulo, conta, info, children }) {
  return <div className="sec-cab">
    <h2>{titulo}{conta != null && <span className="conta">{conta}</span>}</h2>
    {info && <span className="dir">{info}</span>}
    {children && <p className="dica">{children}</p>}
  </div>;
}

function AbaContactar({ p, recarregar }) {
  const notificados = p.alertas.filter((a) => a.notificado);
  const aguardam = p.alertas.filter((a) => a.aguarda);
  const atrasados = p.alertas.filter((a) => a.atrasado);
  const outros = p.alertas.filter((a) => !a.notificado && !a.aguarda && !a.atrasado);
  const par = p.parametros;
  const diaAviso = DIA_SEMANA[par.dia_notificacao || 0];
  const tratar = p.proprio ? async (id) => { await API.enviar("/api/alerta/tratado", { id }); recarregar(); } : undefined;
  const tratarConsumo = p.proprio ? async (negocio_id) => { await API.enviar("/api/consumo/tratado", { negocio_id }); recarregar(); } : undefined;
  const tratarRenovacao = p.proprio ? async (cliente_no) => { await API.enviar("/api/renovacao/tratado", { cliente_no }); recarregar(); } : undefined;
  const renov = p.renovacao || [];
  const renovar = (l) => <div className="sinais">{l.map((c) => <SinalRenovacao key={c.cliente_no} c={c} anos={par.anos_renovacao} tratar={tratarRenovacao} />)}</div>;
  const fecho = par.dias_fecho;
  const lista = (l) => <div className="sinais">{l.map((a) => <Sinal key={a.id} a={a} fecho={fecho} tratar={tratar} param={par} />)}</div>;
  return <section>
    <Cab titulo="Para contactar esta semana" info={<Info p={p.proveniencia.alertas} dir />}>
      {par.dia_notificacao ? `Os avisos chegam à ${diaAviso}. ` : ""}Cada cartão diz o tipo de aviso e porque o estás a ver.
      {p.proprio && " «Já tratei» tira-o da lista sem mudar a fase do negócio."}
    </Cab>
    {notificados.length + p.consumo.length === 0
      ? <div className="vazio-caixa"><Icone n="visto" t={28} /><strong>Nada novo esta semana.</strong>
          <span>{atrasados.length ? "Os avisos antigos vão chegando à " + diaAviso + "." : "Pode haver negócios parados em «Os meus negócios»."}</span></div>
      : <div className="sinais">
          {notificados.map((a) => <Sinal key={a.id} a={a} fecho={fecho} tratar={tratar} param={par} />)}
          {p.consumo.map((c) => <SinalConsumo key={c.negocio_id} c={c} tratar={tratarConsumo} />)}
        </div>}
    {aguardam.length > 0 && <details className="mais">
      <summary>{aguardam.length} {aguardam.length === 1 ? "aviso novo chega" : "avisos novos chegam"} na {diaAviso}</summary>
      <p className="dica">Já se notam; chegam juntos na {diaAviso} para planeares a semana seguinte.</p>
      {lista(aguardam)}
    </details>}
    {atrasados.length > 0 && <details className="mais">
      <summary>{atrasados.length} {atrasados.length === 1 ? "aviso antigo" : "avisos antigos"}, de antes de começarmos</summary>
      <p className="dica">São negócios que já estavam parados quando o sistema arrancou. Vão chegando na {diaAviso},
        até {par.teto_atraso} por semana, os de maior valor primeiro. Podes tratá-los já.</p>
      {lista(atrasados)}
    </details>}
    {outros.length > 0 && <details className="mais">
      <summary>Mais {outros.length} {outros.length === 1 ? "aviso" : "avisos"} acima do limite semanal</summary>
      <p className="dica">Para não encher a lista, só chegam {par.teto_semanal} avisos por semana. Estes ficaram de fora.</p>
      {lista(outros)}
    </details>}
    {renov.length > 0 && <>
      <Cab titulo="Para propor renovação" conta={renov.length} info={<Info p={p.proveniencia.renovacao} dir />}>
        Clientes teus com máquinas antigas e sem negócio de equipamento aberto. Não é urgente: é uma razão para a próxima visita.
        {p.proprio && " «Já tratei» tira o cliente desta lista durante um ano."}
      </Cab>
      {renovar(renov.slice(0, 3))}
      {renov.length > 3 && <details className="mais">
        <summary>Mais {renov.length - 3} {renov.length - 3 === 1 ? "cliente" : "clientes"} para renovação</summary>
        {renovar(renov.slice(3))}
      </details>}
    </>}
  </section>;
}

function Dia({ d, abrir }) {
  const dt = dataDe(d.dia);
  const sem = dt.toLocaleDateString("pt-PT", { weekday: "long" }).replace("-feira", "");
  return <button className={"dia" + (d.fechado ? " fechado" : "")} onClick={() => abrir(d.dia)}>
    <span className="cal"><b>{dt.getDate()}</b>{dt.toLocaleDateString("pt-PT", { month: "short" }).replace(".", "")}</span>
    <span className="txt"><span className="d">{sem}</span>
      <span className="q">{d.relatorios} {d.relatorios === 1 ? "relatório" : "relatórios"}{d.pares != null && <> · {d.pares} {d.pares === 1 ? "negócio" : "negócios"}</>}</span></span>
    {d.fechado ? <span className="estado-dia ok"><Icone n="visto" t={16} /> revisto</span>
      : <span className="estado-dia">Rever <Icone n="seta" t={16} /></span>}
  </button>;
}

function AbaRever({ p, abrirDia }) {
  const pendentes = p.dias.filter((d) => !d.fechado);
  const fechados = p.dias.filter((d) => d.fechado);
  const desde = p.revisao_desde ? DATA_CURTA(p.revisao_desde) : null;
  return <section>
    <Cab titulo="Revisão do dia" info={<Info p={p.proveniencia.revisao} dir />}>
      {p.proprio ? "Abre um dia, confirma o que o sistema percebeu dos teus relatórios e conclui a revisão."
        : "Dias com relatórios deste comercial e se já os reviu."}
      {desde && ` Só a partir de ${desde}; o que é anterior corrige-se em «Os meus negócios».`}
    </Cab>
    {pendentes.length === 0
      ? <div className="vazio-caixa"><Icone n="visto" t={28} /><strong>Não há dias por rever.</strong></div>
      : <div className="dias">{pendentes.map((d) => <Dia key={d.dia} d={d} abrir={abrirDia} />)}</div>}
    {fechados.length > 0 && <details className="mais">
      <summary>{fechados.length} {fechados.length === 1 ? "dia revisto" : "dias revistos"}</summary>
      <div className="dias">{fechados.map((d) => <Dia key={d.dia} d={d} abrir={abrirDia} />)}</div>
    </details>}
  </section>;
}

/* ------------------------------------------------------------ os meus negócios */

const FECHOS = [["ganho", "Ganho"], ["perdido", "Perdido"], ["nao_avancou", "Não avançou"]];

function Negocio({ n, limite, meta, mexe, irmaos, recarregar, taxas }) {
  const [aberto, setAberto] = useState(false);
  const [modo, setModo] = useState(null);       // null | "fase" | "fechar"
  const enviar = async (caminho, corpo) => { await API.enviar(caminho, { negocio_id: n.negocio_id, ...corpo }); recarregar(); };
  return <li className={"negocio" + (aberto ? " aberto" : "")}>
    <button className="neg-linha" aria-expanded={aberto} onClick={() => setAberto(!aberto)}>
      <span className="neg-a">
        <span className="cliente">{n.cliente}</span>
        <span className="neg-estado"><Etapa e={n.estado} />{n.dias_no_estado != null && <span className="sub">há {DIAS(n.dias_no_estado)}</span>}
          {n.fase_origem === "dossier" && <span className="pilula phc" title={n.excerto}>fase pelo PHC</span>}
          {n.negocio_id.startsWith("NG-D") && <span className="pilula phc">aberto pelo PHC</span>}</span>
        <span className="meta"><Seg s={n.segmento} /><span>{TIPO[n.tipo] || n.tipo}</span>
          {n.area && <span>{nomeArea(n.area)}</span>}
          <span className={n.dias > limite ? "tarde" : ""}>último contacto há {DIAS(n.dias)}</span></span>
      </span>
      <span className="neg-b">{n.valor ? <span className="valor">{EUR(n.valor)}</span> : <span className="sem-valor">sem valor</span>}<Icone n="seta" t={18} /></span>
    </button>
    {aberto && <div className="neg-detalhe">
      {mexe && <div className="neg-acoes">
        {modo === null && <>
          {CICLO.includes(n.tipo) && <button className="sec" onClick={() => setModo("fase")}><Icone n="lapis" t={16} /> Mudar fase</button>}
          <button className="sec forte" onClick={() => setModo("fechar")}><Icone n="visto" t={16} /> Fechar negócio</button>
          {irmaos.length > 0 && <button className="sec" onClick={() => setModo("juntar")}>Juntar a outro negócio</button>}
        </>}
        {modo === "juntar" && <div className="formulario">
          <label>É o mesmo negócio que…
            <select defaultValue="" autoFocus onChange={(e) => e.target.value && enviar("/api/negocio/juntar", { com: e.target.value })}>
              <option value="">escolher…</option>
              {irmaos.map((m) => <option key={m.negocio_id} value={m.negocio_id}>{descreverNegocio(m)}</option>)}
            </select></label>
          <p className="fraco">Os relatórios e dossiers deste negócio passam a contar no outro. Desfaz-se em «Fechados há pouco».</p>
          <div className="botoes"><button className="sec" onClick={() => setModo(null)}>Cancelar</button></div>
        </div>}
        {modo === "fase" && <div className="formulario">
          <label>Em que fase está, de facto?
            <select defaultValue="" autoFocus onChange={(e) => e.target.value && enviar("/api/negocio/corrigir", { estado: e.target.value })}>
              <option value="">escolher…</option>
              {meta.estados.filter((s) => s !== n.estado).map((s) => <option key={s} value={s}>{nomeEstado(s)}</option>)}
            </select></label>
          <p className="fraco">Fica registado como correção ao último relatório deste negócio.</p>
          <div className="botoes"><button className="sec" onClick={() => setModo(null)}>Cancelar</button></div>
        </div>}
        {modo === "fechar" && <div className="formulario">
          <span className="rot-leitura">Como terminou?</span>
          <div className="botoes">
            {FECHOS.map(([k, t]) => <Acao key={k} className={"sec" + (k === "ganho" ? " forte" : "")}
              onClick={() => enviar("/api/negocio/fechar", { motivo: k })}>{t}</Acao>)}
          </div>
          <p className="fraco">Sai da lista de negócios. Enganaste-te? Reabre-o em «Fechados há pouco», no fim da lista.</p>
          <div className="botoes"><button className="sec" onClick={() => setModo(null)}>Cancelar</button></div>
        </div>}
      </div>}
      {n.fase_origem === "dossier" && <p className="dossier">A fase vem do PHC: {n.excerto}.</p>}
      {numEstado(n.estado) <= 5 && taxaDe(taxas, n.estado) != null && <p className="historico-fase">
        Dos negócios que passaram por «{nomeEstado(n.estado)}» entre 2024 e 2026, <strong>{Math.round(taxaDe(taxas, n.estado) * 100)} em cada 100</strong> foram
        ganhos nos 6 meses seguintes. É o histórico da fase, não uma previsão para este negócio.</p>}
      {n.dossier_ref && <p className="dossier">Valor da {{ "Proposta": "proposta", "Fatura Proforma": "fatura proforma", "Encomenda de Cliente": "encomenda" }[n.dossier_tipo] || n.dossier_tipo} nº {n.dossier_ref} do PHC, de {DATA_CURTA(n.dossier_data)}.</p>}
      <p className="fraco">{n.relatorios} {n.relatorios === 1 ? "relatório" : "relatórios"} sobre este negócio</p>
      <Historia negocioId={n.negocio_id} />
    </div>}
  </li>;
}

function Carteira({ p, meta, mexe, recarregar }) {
  const [filtro, setFiltro] = useState("");
  const [seg, setSeg] = useState("");
  const [procura, setProcura] = useState("");
  const [area, setArea] = useState("");
  const [origem, setOrigem] = useState("");
  const todos = p.negocios;
  const areasHa = [...new Set(todos.map((n) => n.area).filter(Boolean))].sort();
  const abertos = todos.filter((n) => (!area || n.area === area) && daOrigem(n, origem));
  const limite = p.parametros.dias_sem_contacto;
  const vb = abertos.filter((n) => n.segmento === "base_instalada").reduce((s, n) => s + n.valor, 0);
  const vc = abertos.filter((n) => n.segmento === "conquista").reduce((s, n) => s + n.valor, 0);
  const nb = abertos.filter((n) => n.segmento === "base_instalada").length;
  const lista = abertos.filter((n) =>
    (!filtro || n.estado === filtro) && (!seg || n.segmento === seg) &&
    (!procura || (n.cliente || "").toLowerCase().includes(procura.toLowerCase())));
  const ordenada = [...lista].sort((a, b) => (numEstado(b.estado) || 0) - (numEstado(a.estado) || 0) || b.valor - a.valor || a.dias - b.dias);
  const ativos = ordenada.filter((n) => n.dias <= limite);
  const parados = ordenada.filter((n) => n.dias > limite);
  const s = p.saidas;
  const SEGS = [["", "Todos"], ["base_instalada", SEGMENTO.base_instalada], ["conquista", SEGMENTO.conquista]];
  const linhas = (l) => <ul className="negocios">{l.map((n) => <Negocio key={n.negocio_id} n={n} limite={limite}
    meta={meta} mexe={mexe} recarregar={recarregar} taxas={p.taxas}
    irmaos={todos.filter((m) => m.cliente_no === n.cliente_no && m.negocio_id !== n.negocio_id)} />)}</ul>;
  const reabrir = async (id) => { await API.enviar("/api/negocio/reabrir", { negocio_id: id }); recarregar(); };
  const separar = async (id) => { await API.enviar("/api/negocio/separar", { negocio_id: id }); recarregar(); };
  return <section>
    <Cab titulo={p.proprio ? "Os meus negócios" : "Negócios"} info={<Info p={p.proveniencia.pipeline} dir />}>
      Negócios abertos em que foste o último a falar com o cliente. Toca num negócio para ver o histórico,
      corrigir a fase ou fechá-lo.
    </Cab>

    <div className="numeros">
      <div><span className="n">{abertos.length}</span><span className="r">negócios abertos</span>
        <Divisao base={nb} conquista={abertos.length - nb} formatar={(v) => v} /></div>
      <div><span className="n">{vb + vc ? EUR(vb + vc) : "n.d."}</span>
        <span className="r">em negócios <Info p={p.proveniencia.carteira} dir /></span>
        {vb + vc > 0 ? <Divisao base={vb} conquista={vc} /> : null}
        <span className="fraco">Valor da última proposta, proforma ou encomenda no PHC.</span>
        {vb + vc > 0 && p.taxas && Object.keys(p.taxas).length > 0 && <span className="fraco bloco">Ponderado pelo histórico de cada fase:
          {" "}<strong>{EUR(ponderado(abertos, p.taxas))}</strong> <Info p={p.proveniencia.ponderado} dir /></span>}</div>
    </div>

    <details className="painel" open={!!filtro}>
      <summary>Por fase {filtro ? <span className="pilula">{nomeEstado(filtro)}</span> : <span className="fraco">toca numa fase para filtrar</span>}</summary>
      <Funil estados={funilDe(abertos)} filtro={filtro} setFiltro={setFiltro} />
      <p className="fraco saidas">Últimos {s.dias} dias: {s.ganho.negocios} ganhos, {s.perdido.negocios} perdidos,
        {" "}{s.automatico.negocios} fechados por falta de contacto. <Info p={p.proveniencia.saidas} dir /></p>
    </details>

    <div className="filtros">
      <input type="search" placeholder="Procurar cliente" value={procura} onChange={(e) => setProcura(e.target.value)} aria-label="Procurar cliente" />
      <div className="segmentado" role="group" aria-label="Segmento">
        {SEGS.map(([k, t]) => <button key={k} aria-pressed={seg === k} onClick={() => setSeg(k)}>
          {k && <i className={"ponto " + (k === "base_instalada" ? "base" : "conquista")} />}{t}</button>)}
      </div>
      <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Área">
        <option value="">Todas as áreas</option>
        {areasHa.map((a) => <option key={a} value={a}>{nomeArea(a)}</option>)}
      </select>
      <select value={origem} onChange={(e) => setOrigem(e.target.value)} aria-label="Origem do negócio">
        {ORIGENS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
      </select>
      {filtro && <button className="pilula tirar" onClick={() => setFiltro("")}>{nomeEstado(filtro)} ×</button>}
      {(area || origem) && <button className="pilula tirar" onClick={() => { setArea(""); setOrigem(""); }}>limpar filtros ×</button>}
    </div>
    {ordenada.length === 0 ? <p className="vazio">Sem negócios com estes filtros.</p> : <>
      <h3 className="grupo">Com contacto nos últimos {limite} dias <span className="conta">{ativos.length}</span></h3>
      {ativos.length ? linhas(ativos) : <p className="vazio">Nenhum.</p>}
      {parados.length > 0 && <details className="mais">
        <summary>{parados.length} {parados.length === 1 ? "negócio" : "negócios"} sem contacto há mais de {limite} dias</summary>
        <p className="dica">Fecham sozinhos aos {p.parametros.dias_fecho} dias sem contacto. Se já terminaram, fecha-os aqui.</p>
        {linhas(parados)}
      </details>}
    </>}
    {(p.fechados_recentes || []).length > 0 && <details className="mais">
      <summary>Fechados há pouco ({p.fechados_recentes.length})</summary>
      <ul className="negocios">{p.fechados_recentes.map((f) => <li key={f.negocio_id} className="negocio">
        <div className="neg-linha estatico">
          <span className="neg-a"><span className="cliente">{f.cliente}</span>
            <span className="meta"><span>{TIPO[f.tipo] || f.tipo}</span>
              <span>{f.fecho_motivo === "juntado" ? "juntado a " + f.juntado_a
                : { comercial_ganho: "ganho", comercial_perdido: "perdido", comercial_nao_avancou: "não avançou" }[f.fecho_motivo]} a {DATA_CURTA(f.fechado_em)}</span></span></span>
          {mexe && (f.fecho_motivo === "juntado"
            ? <Acao className="sec" onClick={() => separar(f.negocio_id)}><Icone n="desfazer" t={16} /> Separar</Acao>
            : <Acao className="sec" onClick={() => reabrir(f.negocio_id)}><Icone n="desfazer" t={16} /> Reabrir</Acao>)}
        </div></li>)}</ul>
    </details>}
  </section>;
}

/* ------------------------------------------------------------ revisão do dia
   Cada negócio que o sistema leu é uma ficha com três campos: negócio, tipo e
   fase. Para corrigir, toca-se no campo errado e escolhe-se o certo; grava logo.
   «Não é um negócio» tira-o da contagem. Qualquer correção desfaz-se enquanto o
   dia não estiver revisto. O motivo da correção (RF1.7) vem do campo mexido. */

function Campo({ rotulo, valor, antes, opcoes, editavel, aoMudar }) {
  const [aEditar, setAEditar] = useState(false);
  if (aEditar) return <div className="campo a-editar">
    <span className="campo-rot">{rotulo}</span>
    <select autoFocus defaultValue="" onChange={async (e) => { if (!e.target.value) return; await aoMudar(e.target.value); setAEditar(false); }}>
      <option value="">escolher…</option>
      {opcoes.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
    </select>
    <button className="ligacao" onClick={() => setAEditar(false)}>cancelar</button>
  </div>;
  return <button className={"campo" + (antes != null ? " mudado" : "")} disabled={!editavel} onClick={() => setAEditar(true)}>
    <span className="campo-rot">{rotulo}</span>
    <span className="campo-val">{antes && <s>{antes}</s>} {valor}</span>
    {editavel && <span className="campo-ed"><Icone n="lapis" t={15} /> mudar</span>}
  </button>;
}

function descreverNegocio(n) {
  if (!n) return "outro negócio do cliente";
  return `${TIPO[n.tipo] || n.tipo}, ${n.estado ? nomeEstado(n.estado).toLowerCase() : "sem fase"}${n.ultimo_toque ? ", último contacto " + DATA_CURTA(n.ultimo_toque) : ""}`;
}

function Par({ p, lote, meta, cands, editavel, feito }) {
  const [erro, setErro] = useState(null);
  const novoAqui = (id) => id && id.startsWith("NG-X" + p.vistamp.slice(0, 10) + "-");
  const naoE = p.acao === "corrigido" && p.motivo === "não havia conteúdo comercial";
  const tipo = p.tipo_corrigido || p.tipo;
  const estado = p.estado_corrigido || p.estado;
  const negocio = p.negocio_corrigido || p.negocio_id;
  const ciclo = CICLO.includes(tipo);
  const mexido = p.acao === "corrigido" || p.origem === "comercial";
  const pode = editavel && !naoE && p.origem !== "comercial" && !p.ratificado;

  const gravar = async (mud) => {
    setErro(null);
    const novo = { estado: p.estado_corrigido, tipo: p.tipo_corrigido, negocio: p.negocio_corrigido, ...mud };
    const motivo = mud.naoE ? "não havia conteúdo comercial"
      : novo.negocio ? "negócio errado" : novo.tipo ? "tipo errado" : "fronteira entre estados";
    try {
      await API.enviar("/api/correcao", { par_id: p.par_id, lote_id: lote, motivo,
        estado_corrigido: mud.naoE ? null : novo.estado || null,
        tipo_corrigido: mud.naoE ? null : novo.tipo || null,
        negocio_corrigido: mud.naoE ? null : novo.negocio || null });
      feito();
    } catch (e) { setErro(e.message); }
  };
  const desfazer = async () => {
    setErro(null);
    try { await API.enviar("/api/correcao/desfazer", { par_id: p.par_id, lote_id: lote }); feito(); }
    catch (e) { setErro(e.message); }
  };

  const atual = (cands || []).find((n) => n.negocio_id === negocio);
  const nomeNeg = novoAqui(negocio) ? "Negócio novo, aberto neste relatório" : descreverNegocio(atual);
  const outrosNeg = (cands || []).filter((n) => n.negocio_id !== negocio)
    .map((n) => [n.negocio_id, descreverNegocio(n)]);
  if (!novoAqui(negocio)) outrosNeg.push(["NOVO", "É um negócio novo"]);

  return <div className={"par" + (mexido ? " mexido" : "") + (naoE ? " nao-e" : "")}>
    {naoE ? <p className="nao-e-txt">Marcaste que isto <strong>não é um negócio</strong>.</p> : <div className="campos">
      {ciclo && <Campo rotulo="Negócio" valor={nomeNeg} editavel={pode} opcoes={outrosNeg}
        antes={p.negocio_corrigido ? "" : null} aoMudar={(v) => gravar({ negocio: v })} />}
      <Campo rotulo="Tipo" valor={TIPO[tipo] || tipo} antes={p.tipo_corrigido ? TIPO[p.tipo] || p.tipo : null} editavel={pode}
        opcoes={meta.tipos.filter((t) => t !== tipo).map((t) => [t, TIPO[t] || t])} aoMudar={(v) => gravar({ tipo: v })} />
      {ciclo && <Campo rotulo="Fase" valor={nomeEstado(estado)} antes={p.estado_corrigido ? nomeEstado(p.estado) : null} editavel={pode}
        opcoes={meta.estados.filter((s) => s !== estado).map((s) => [s, nomeEstado(s)])} aoMudar={(v) => gravar({ estado: v })} />}
    </div>}
    <p className="excerto">O sistema percebeu isto por causa desta frase: “{p.excerto}”</p>
    <div className="par-rodape">
      {p.origem === "comercial" && <span className="pilula humano">acrescentado por ti</span>}
      {p.acao === "corrigido" && !naoE && <span className="pilula humano">corrigido por ti{p.ratificado ? " e ratificado" : ""}</span>}
      {pode && <button className="sec" onClick={() => gravar({ naoE: true })}>Não é um negócio</button>}
      {editavel && mexido && !p.ratificado && <button className="sec" onClick={desfazer}><Icone n="desfazer" t={15} /> Desfazer</button>}
    </div>
    {erro && <p className="erro">{erro}</p>}
  </div>;
}

function EmFalta({ rel, lote, meta, feito, cancelar }) {
  const [negs] = usarDados(() => API.negociosCliente(rel.cliente_no), [rel.cliente_no]);
  const [negocio, setNegocio] = useState("");
  const [tipo, setTipo] = useState("");
  const [estado, setEstado] = useState("");
  const [excerto, setExcerto] = useState("");
  const [erro, setErro] = useState(null);
  const escolhido = negs && negs.negocios.find((n) => n.negocio_id === negocio);
  const t = escolhido ? escolhido.tipo : tipo;
  const pronto = t && excerto.trim() && (!CICLO.includes(t) || estado);
  const gravar = async () => {
    try {
      await API.enviar("/api/negocio-em-falta", { vistamp: rel.vistamp, lote_id: lote,
        negocio_id: negocio || null, tipo: t, estado: CICLO.includes(t) ? estado : null, excerto });
      feito();
    } catch (e) { setErro(e.message); }
  };
  return <div className="formulario falta">
    <strong>Negócio que o sistema não viu</strong>
    <label>É um negócio que já existe?
      <select value={negocio} onChange={(e) => setNegocio(e.target.value)}>
        <option value="">Não, é um negócio novo</option>
        {(negs ? negs.negocios : []).map((n) => <option key={n.negocio_id} value={n.negocio_id}>
          {descreverNegocio(n)}</option>)}
      </select></label>
    {!escolhido && <label>Tipo
      <select value={tipo} onChange={(e) => setTipo(e.target.value)}>
        <option value="">escolher…</option>
        {meta.tipos.map((s) => <option key={s} value={s}>{TIPO[s] || s}</option>)}
      </select></label>}
    {CICLO.includes(t) && <label>Fase
      <select value={estado} onChange={(e) => setEstado(e.target.value)}>
        <option value="">escolher…</option>
        {meta.estados.map((s) => <option key={s} value={s}>{nomeEstado(s)}</option>)}
      </select></label>}
    <label>Copia a frase do relatório que o mostra
      <input value={excerto} onChange={(e) => setExcerto(e.target.value)} /></label>
    <div className="botoes">
      <button className="acao" disabled={!pronto} onClick={gravar}>Guardar</button>
      <button className="sec" onClick={cancelar}>Cancelar</button>
    </div>
    {erro && <p className="erro">{erro}</p>}
  </div>;
}

function RevisaoDia({ vendedor, dia, meta, proprio, voltar }) {
  const [lote, erro, recarregar] = usarDados(() => API.lote(vendedor, dia), [vendedor, dia]);
  const [emFalta, setEmFalta] = useState(null);
  const [aFechar, setAFechar] = useState(false);
  if (erro) return <Erro erro={erro} />;
  if (!lote) return <Carregar />;
  const editavel = lote.editavel && !lote.fechado;
  const feito = () => { setEmFalta(null); recarregar(); };
  const fechar = async () => {
    setAFechar(true);
    try { await API.enviar("/api/lote/fechar", { lote_id: lote.lote_id }); voltar(); }
    finally { setAFechar(false); }
  };
  const nPares = lote.relatorios.reduce((s, r) => s + r.pares.length, 0);
  const n = lote.relatorios.length;

  return <div className={"revisao" + (editavel ? " com-rodape" : "")}>
    <button className="ligacao migalha" onClick={voltar}>← {proprio ? "Voltar" : "Página de " + vendedor}</button>
    <div className="sec-cab">
      <h1>{DATA_LONGA(dia)}</h1>
      <span className="dir"><Info p={{ formula: "o motor lê cada relatório e diz de que negócios fala, de que tipo são e em que fase estão, com a frase que o mostra", fonte: "os relatórios de visita do ERP", problema: "P2, conhecimento não capturado", requisito: "RF1.3, RF1.7, RF2.9", limitacao: "o que não corrigires fica confirmado quando concluíres a revisão; isso é prova mais fraca do que confirmar item a item" }} dir /></span>
      <p className="dica">{n} {n === 1 ? "relatório" : "relatórios"} · o sistema encontrou {nPares} {nPares === 1 ? "negócio" : "negócios"}</p>
    </div>

    {editavel && <ol className="passos">
      <li>Lê cada relatório e a ficha do que o sistema percebeu.</li>
      <li>Se um campo estiver errado, <b>toca nele</b> e escolhe o certo. Se não for um negócio, carrega em <b>Não é um negócio</b>.</li>
      <li>Enganaste-te? Carrega em <b>Desfazer</b>.</li>
      <li>No fim, <b>conclui a revisão do dia</b>. O que não mudaste fica confirmado.</li>
    </ol>}
    {!editavel && <p className="aviso-gestor">{lote.fechado ? "A revisão deste dia já está concluída." : "Só quem escreveu os relatórios faz a revisão do dia."}</p>}

    {n === 0 && <p className="vazio">Sem relatórios neste dia.</p>}
    {lote.relatorios.map((r, i) => (
      <article key={r.vistamp} className="relato-bloco">
        <div className="relato-cab">
          <span className="ordem">{i + 1}/{n}</span>
          <strong>{r.cliente}</strong> <Seg s={r.segmento} />
          {r.hora && <span className="hora">{String(r.hora).replace(/^(\d{1,2}):(\d{2}).*/, (_, h, m) => h.padStart(2, "0") + ":" + m)}</span>}
        </div>
        <blockquote className="relatorio">{r.relatorio}</blockquote>
        {r.erro && <p className="erro">O sistema não conseguiu ler este relatório.</p>}
        <div className="leitura">
          <span className="rot-leitura">O que o sistema percebeu</span>
          {r.pares.length === 0 && !r.erro && <p className="fraco">Nenhum negócio neste relatório.</p>}
          {r.pares.map((p) => <Par key={p.par_id} p={p} lote={lote.lote_id} meta={meta} cands={r.candidatos}
            editavel={editavel} feito={feito} />)}
          {editavel && (emFalta === r.vistamp
            ? <EmFalta rel={r} lote={lote.lote_id} meta={meta} feito={feito} cancelar={() => setEmFalta(null)} />
            : <button className="sec tracejado" onClick={() => setEmFalta(r.vistamp)}>+ Falta um negócio</button>)}
        </div>
      </article>))}

    {n > 0 && (editavel
      ? <div className="rodape-dia">
          <button className="acao grande" disabled={aFechar} onClick={fechar}><Icone n="visto" t={18} /> Concluir a revisão do dia</button>
        </div>
      : lote.fechado && <p className="ok fechado-fim"><Icone n="visto" t={18} /> Revisão concluída</p>)}
  </div>;
}


/* ------------------------------------------------------------ gestão */

function Equipa({ r }) {
  const [d, erro] = usarDados(API.equipa, []);
  if (erro) return <Erro erro={erro} />;
  if (!d) return <Carregar />;
  const c = d.comerciais;
  const soma = (k) => c.reduce((s, x) => s + (x[k] || 0), 0);
  const valor = soma("valor"), vbase = soma("valor_base");
  const abertos = soma("abertos"), abase = soma("abertos_base");
  const notificados = d.alertas.filter((a) => a.notificado);
  const outros = d.alertas.filter((a) => !a.notificado && !a.aguarda);
  const s = d.saidas;
  return <>
    <div className="cabeca"><div><h1>Equipa comercial</h1>
      <p>Carteira, alertas e revisão de cada comercial. Carrega num nome para abrir a página dele.</p></div></div>
    <div className="tiles">
      <Tile r="Negócios abertos" n={abertos} s={`${abase} de clientes com máquina · ${abertos - abase} de clientes novos`}>
        <Divisao base={abase} conquista={abertos - abase} chaves={false} /></Tile>
      <Tile r="Valor em carteira" n={valor ? EUR(valor) : "n.d."} s={valor ? `${PCT((vbase / valor) * 100)} em clientes com máquina` : "valor ainda não chega do ERP"}>
        {valor > 0 && <Divisao base={vbase} conquista={valor - vbase} chaves={false} />}</Tile>
      <Tile r="Alertas notificados esta semana" n={soma("alertas")} s={`máximo de ${d.teto_semanal} por comercial`} info={<Info p={d.proveniencia.alertas} />} />
      <Tile r="Dias por rever" n={soma("por_confirmar")} s="dias sem fecho nos últimos 14" info={<Info p={d.proveniencia.equipa} dir />} />
    </div>
    <section className="cartao">
      <div className="cartao-cab"><h2>Por comercial</h2><span className="dir"><Info p={d.proveniencia.equipa} dir /></span></div>
      <p className="legenda">«Parados» são negócios abertos sem contacto há mais de {d.dias_parado} dias.</p>
      <div className="rolar"><table>
        <thead><tr><th>Comercial</th><th className="num">Abertos</th><th className="num">Valor</th>
          <th style={{ minWidth: 150 }}>Com máquina / novos</th><th className="num">Parados</th>
          <th className="num">Alertas</th><th className="num">Dias por rever</th></tr></thead>
        <tbody>{c.map((x) => (
          <tr key={x.vendedor} className="clicavel" onClick={() => ir("comercial", x.vendedor)}>
            <td><a href={"#/comercial/" + encodeURIComponent(x.vendedor)} onClick={(e) => e.stopPropagation()}><strong>{x.vendedor}</strong></a></td>
            <td className="num">{x.abertos}</td>
            <td className="num">{x.valor ? EUR(x.valor) : "n.d."}</td>
            <td>{x.abertos > 0
              ? <><Divisao base={x.abertos_base} conquista={x.abertos - x.abertos_base} chaves={false} />
                  <div className="sub">{x.abertos_base} · {x.abertos - x.abertos_base} negócios</div></>
              : <span className="sub">n.d.</span>}</td>
            <td className="num">{x.parados}</td>
            <td className="num">{x.alertas}</td>
            <td className="num">{x.por_confirmar > 0 ? <span style={{ color: "var(--aviso-texto)", fontWeight: 600 }}>{x.por_confirmar}</span> : "0"}</td>
          </tr>))}</tbody>
      </table></div>
      <Chaves />
    </section>
    <div className="grelha">
      <section className="cartao">
        <div className="cartao-cab"><h2>Sinais da semana</h2><span className="conta">{notificados.length}</span>
          <span className="dir"><Info p={d.proveniencia.alertas} dir /></span></div>
        <p className="legenda">Os alertas notificados aos comerciais: primeiro os de negócio, por valor e dias parado.</p>
        {notificados.length === 0 ? <p className="vazio">Nada novo esta semana.</p>
          : <Sinais lista={notificados} fecho={180} comercial resto={(k) => `Ver os outros ${k} alertas notificados`} />}
        {outros.length > 0 && <details className="mais"><summary>Mais {outros.length} fora do limite semanal</summary>
          <div className="sinais">{outros.map((a) => <Sinal key={a.id} a={a} fecho={180} comercial />)}</div></details>}
      </section>
      <section className="cartao">
        <div className="cartao-cab"><h2>Saídas do pipeline</h2><span className="dir"><Info p={d.proveniencia.saidas} dir /></span></div>
        <p className="legenda">Últimos {s.dias} dias. O fecho por falta de contacto fica separado da perda declarada.</p>
        <table><tbody>
          <tr><td><span className="etapa"><b className="ganho">8</b>Ganhos</span></td><td className="num">{s.ganho.negocios}</td><td className="num">{s.ganho.valor ? EUR(s.ganho.valor) : "n.d."}</td></tr>
          <tr><td><span className="etapa"><b className="perdido">9</b>Perdidos, declarados</span></td><td className="num">{s.perdido.negocios}</td><td className="num">{s.perdido.valor ? EUR(s.perdido.valor) : "n.d."}</td></tr>
          <tr><td><span className="etapa"><b className="perdido">–</b>Fechados sem contacto</span></td><td className="num">{s.automatico.negocios}</td><td className="num">{s.automatico.valor ? EUR(s.automatico.valor) : "n.d."}</td></tr>
        </tbody></table>
      </section>
    </div>
  </>;
}

function PipelineEmpresa({ r }) {
  const [vendedor, setVendedor] = useState("");
  const [area, setArea] = useState("");
  const [origem, setOrigem] = useState("");
  const [p, erro] = usarDados(() => API.pipeline(vendedor, area, origem), [vendedor, area, origem]);
  if (erro) return <Erro erro={erro} />;
  if (!p) return <Carregar />;
  const seg = (lista, s) => lista.find((d) => d.segmento === s) || {};
  const eb = seg(p.esforco, "base_instalada"), ec = seg(p.esforco, "conquista");
  const vb = seg(p.valor, "base_instalada"), vc = seg(p.valor, "conquista");
  return <>
    <div className="cabeca">
      <div><h1>Pipeline</h1><p>Onde estão os negócios abertos e para onde vai o esforço comercial.</p></div>
      <div className="dir"><select value={vendedor} onChange={(e) => setVendedor(e.target.value)} aria-label="Comercial">
        <option value="">toda a equipa</option>
        {r.vendedores.map((v) => <option key={v} value={v}>{v}</option>)}
      </select>
      <select value={area} onChange={(e) => setArea(e.target.value)} aria-label="Área">
        <option value="">todas as áreas</option>
        {(p.areas || []).map((a) => <option key={a} value={a}>{nomeArea(a)}</option>)}
      </select>
      <select value={origem} onChange={(e) => setOrigem(e.target.value)} aria-label="Origem do negócio">
        {ORIGENS.map(([k, t]) => <option key={k} value={k}>{t.toLowerCase()}</option>)}
      </select></div>
    </div>
    {(area || origem) && <p className="aviso-gestor">Filtros por área e origem aplicam-se aos negócios por fase; o esforço, o valor por segmento e os consumíveis são da equipa ou do comercial escolhido.</p>}
    <div className="grelha">
      <section className="cartao">
        <div className="cartao-cab"><h2>Negócios abertos por estado</h2><span className="dir"><Info p={p.proveniencia.pipeline} dir /></span></div>
        <p className="legenda">Último estado de cada negócio de equipamento, produção e lead.</p>
        <Funil estados={p.estados} />
        <Chaves />
      </section>
      <section className="cartao">
        <div className="cartao-cab"><h2>Clientes com máquina e clientes novos</h2><span className="dir"><Info p={p.proveniencia.segmento} dir /></span></div>
        <p className="legenda">Quem já tinha equipamento, separado de quem não tinha.</p>
        <h3 className="fraco" style={{ margin: "4px 0 0", textTransform: "uppercase", letterSpacing: ".05em" }}>Esforço: contactos</h3>
        <Divisao base={eb.contactos || 0} conquista={ec.contactos || 0} formatar={(v) => `${v} (${PCT(((v || 0) / ((eb.contactos || 0) + (ec.contactos || 0) || 1)) * 100)})`} />
        <h3 className="fraco" style={{ margin: "14px 0 0", textTransform: "uppercase", letterSpacing: ".05em" }}>Valor dos negócios</h3>
        <Divisao base={vb.valor || 0} conquista={vc.valor || 0} formatar={EUR} />
        {(vb.por_tipo || vc.por_tipo) && <table style={{ marginTop: 12 }}>
          <thead><tr><th>Tipo</th><th className="num">Com máquina</th><th className="num">Novos</th></tr></thead>
          <tbody>{["equipamento", "producao", "consumiveis", "lead"].filter((t) => (vb.por_tipo || {})[t] || (vc.por_tipo || {})[t]).map((t) => (
            <tr key={t}><td>{TIPO[t]}</td><td className="num">{EUR((vb.por_tipo || {})[t])}</td><td className="num">{EUR((vc.por_tipo || {})[t])}</td></tr>))}</tbody>
        </table>}
      </section>
    </div>
    <section className="cartao">
      <div className="cartao-cab"><h2>Valor ponderado pelo histórico</h2><span className="dir"><Info p={p.proveniencia.ponderado} dir /></span></div>
      <p className="legenda">Quantos negócios de cada fase foram ganhos em 6 meses, entre 2024 e 2026. É o histórico, não uma previsão;
        fica abaixo do real, porque nem todos os fechos ficam registados.</p>
      <div className="rolar"><table>
        <thead><tr><th>Fase</th><th className="num">Negócios</th><th className="num">Valor</th><th className="num">Ganhos em 100</th><th className="num">Ponderado</th></tr></thead>
        <tbody>{p.estados.map((e) => <tr key={e.estado}><td>{nomeEstado(e.estado)}</td><td className="num">{e.negocios}</td>
          <td className="num">{EUR(e.valor)}</td>
          <td className="num">{FASES_GANHAS.includes(e.estado) ? <span className="sub">adjudicado</span> : e.taxa != null ? Math.round(e.taxa * 100) : "n.d."}</td>
          <td className="num">{EUR(e.valor_ponderado)}</td></tr>)}</tbody>
        <tfoot><tr><th>Total</th><th className="num">{p.estados.reduce((s, e) => s + e.negocios, 0)}</th>
          <th className="num">{EUR(p.estados.reduce((s, e) => s + e.valor, 0))}</th><th></th>
          <th className="num">{EUR(p.estados.reduce((s, e) => s + (e.valor_ponderado || 0), 0))}</th></tr></tfoot>
      </table></div>
    </section>
    <section className="cartao">
      <div className="cartao-cab"><h2>Relação de fornecimento e pós-venda</h2><span className="dir"><Info p={p.proveniencia.consumiveis} dir /></span></div>
      <p className="legenda">Não é uma fase do ciclo comercial: é o ritmo de compra de cada cliente, calculado da faturação.
        {vendedor && " Esta parte é da empresa toda."}</p>
      <div className="grelha" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,2fr)" }}>
        <table><thead><tr><th>Relação</th><th className="num">Clientes</th><th className="num">Valor</th></tr></thead>
          <tbody>{p.consumiveis.map((c) => <tr key={c.estado}><td><Relacao e={c.estado} /></td><td className="num">{c.clientes}</td><td className="num">{EUR(c.valor)}</td></tr>)}</tbody></table>
        <div className="rolar"><table>
          <thead><tr><th>Em risco ou dormentes</th><th>Relação</th><th className="num">Valor</th><th>Último relato</th></tr></thead>
          <tbody>{p.consumiveis_clientes.slice(0, 12).map((c) => (
            <tr key={c.negocio_id}><td>{c.cliente || <span className="sub">cliente sem nome no registo · {c.negocio_id}</span>}</td><td><Relacao e={c.estado} /></td>
              <td className="num">{EUR(c.valor)}</td>
              <td className="excerto">{c.excerto ? <>{DATA_CURTA(c.data)}: “{c.excerto}”</> : <span className="fraco">sem relato</span>}</td></tr>))}</tbody>
        </table></div>
      </div>
    </section>
  </>;
}

function Qualidade() {
  const [d, erro, recarregar] = usarDados(API.qualidade, []);
  if (erro) return <Erro erro={erro} />;
  if (!d) return <Carregar />;
  const m = d.metricas, t = d.totais, c = d.ultimo_ciclo;
  const max = Math.max(...m.motivos.map((x) => x.n), 1);
  return <>
    <div className="cabeca"><div><h1>Qualidade da classificação</h1>
      <p>O que o uso do sistema mostra sobre o motor de interpretação, e as correções à espera de ratificação.</p></div></div>
    <div className="tiles">
      <Tile r="Relatórios classificados" n={t.relatorios} s={`${t.pares} negócios lidos`} />
      <Tile r="Sem conteúdo comercial" n={t.sem_conteudo} s={`${PCT((t.sem_conteudo / (t.relatorios || 1)) * 100)} dos relatórios`} />
      <Tile r="Por classificar" n={t.erros} s="o modelo não conseguiu ler" />
      <Tile r="Último ciclo noturno" n={c ? (c.ok ? "ok" : c.ok === false ? "falhou" : "a correr") : "n.d."}
        s={c ? `${c.inicio} · ${c.relatorios ?? 0} relatórios · ${c.alertas ?? 0} alertas` : "ainda não correu"} />
    </div>
    <div className="grelha">
      <section className="cartao">
        <div className="cartao-cab"><h2>Correções por ratificar</h2><span className="conta">{d.pendentes.length}</span></div>
        <p className="legenda">Uma correção só entra no corpus que orienta a versão seguinte do prompt depois de ratificada,
          para manter um critério único. Já conta no pipeline e nos alertas antes disso.</p>
        {d.pendentes.length === 0 ? <p className="vazio">Nada pendente.</p> :
          <div className="rolar"><table>
            <thead><tr><th>Relatório</th><th>O modelo disse</th><th>O comercial disse</th><th></th></tr></thead>
            <tbody>{d.pendentes.map((p) => (
              <tr key={p.par_id}>
                <td><strong>{p.cliente}</strong><div className="relatorio" style={{ maxHeight: 90, overflow: "auto" }}>{p.relatorio}</div></td>
                <td>{p.acao === "negocio_em_falta" ? <span className="sub">nada</span> : <>{TIPO[p.tipo_proposto]} {p.estado_proposto && <Etapa e={p.estado_proposto} />}</>}</td>
                <td>{TIPO[p.tipo_corrigido] || ""} {p.estado_corrigido && <Etapa e={p.estado_corrigido} />}
                  <div className="sub">{p.motivo} · {p.corrigido_por}</div></td>
                <td><button className="sec" onClick={async () => { await API.enviar("/api/ratificacao", { par_id: p.par_id }); recarregar(); }}>Ratificar</button></td>
              </tr>))}</tbody>
          </table></div>}
      </section>
      <section>
        <div className="cartao">
          <div className="cartao-cab"><h2>Precisão observada no uso</h2>
            <span className="dir"><Info p={{ formula: "pares vistos em dias fechados menos as correções feitas na revisão desses dias, a dividir pelos pares vistos", fonte: "lotes de revisão e correções", problema: "avaliação contínua do Artefacto 1", requisito: "RF1.7", limitacao: m.nota + "; não substitui o conjunto de referência" }} dir /></span></div>
          <div className="tile" style={{ border: 0, boxShadow: "none", padding: "4px 0" }}>
            <div className="n">{m.precisao_maxima_no_examinado === null ? "n.d." : PCT(m.precisao_maxima_no_examinado)}</div>
            <div className="s">limite superior, sobre {m.pares_examinados_em_lotes_fechados} pares vistos</div>
          </div>
          <p className="fraco">{m.correcoes} correções nos dias revistos · {m.negocios_em_falta} negócios que o sistema não viu · {m.correcoes_ratificadas} ratificadas</p>
          {(m.correcoes_carteira > 0 || m.correcoes_dias_abertos > 0) && <p className="fraco">Fora da conta: {m.correcoes_carteira} feitas na carteira · {m.correcoes_dias_abertos} em dias ainda por fechar</p>}
        </div>
        {m.motivos.length > 0 && <div className="cartao">
          <div className="cartao-cab"><h2>Onde estão os erros</h2></div>
          <div className="funil">{m.motivos.map((x) => (
            <div className="funil-linha" key={x.motivo} style={{ cursor: "default" }}>
              <span className="rot">{x.motivo}</span>
              <span className="trilho"><i className="b" style={{ width: (x.n / max) * 100 + "%", borderRadius: "0 4px 4px 0" }} /></span>
              <span className="val"><b>{x.n}</b></span>
            </div>))}</div>
        </div>}
      </section>
    </div>
  </>;
}

function Parametros() {
  const [d, erro, recarregar] = usarDados(API.parametros, []);
  const [valores, setValores] = useState({});
  const [msg, setMsg] = useState(null);
  if (erro) return <Erro erro={erro} />;
  if (!d) return <Carregar />;
  const gravar = async (chave) => {
    setMsg(null);
    try {
      await API.enviar("/api/parametros", { chave, valor: Number(valores[chave]) });
      setValores({ ...valores, [chave]: undefined });
      setMsg({ ok: true, t: "Guardado. Vale a partir do próximo ciclo noturno." });
      recarregar();
    } catch (e) { setMsg({ ok: false, t: e.message }); }
  };
  return <>
    <div className="cabeca"><div><h1>Parâmetros</h1>
      <p>Os limiares que o sistema usa. Alterá-los é configuração, não programação (RNF3).</p></div></div>
    <section className="cartao">
      {msg && <p className={msg.ok ? "ok" : "erro"}>{msg.t}</p>}
      <div className="rolar"><table>
        <thead><tr><th>Parâmetro</th><th className="num">Valor</th><th>Origem</th><th>Última alteração</th><th></th></tr></thead>
        <tbody>{d.parametros.map((p) => (
          <tr key={p.chave}>
            <td>{p.descricao}<div className="sub">{p.chave} · entre {p.minimo} e {p.maximo}</div></td>
            <td className="num"><input type="number" step="any" min={p.minimo} max={p.maximo} style={{ width: 90, textAlign: "right" }}
              value={valores[p.chave] ?? p.valor} onChange={(e) => setValores({ ...valores, [p.chave]: e.target.value })} /></td>
            <td>{p.origem}</td>
            <td className="sub">{p.alterado_em} · {p.alterado_por}</td>
            <td>{valores[p.chave] !== undefined && Number(valores[p.chave]) !== p.valor &&
              <button className="acao" onClick={() => gravar(p.chave)}>guardar</button>}</td>
          </tr>))}</tbody>
      </table></div>
    </section>
  </>;
}

/* ------------------------------------------------------------ moldura */

const temaInicial = () => { try { return localStorage.getItem("tema"); } catch (_) { return null; } };
function usarTema() {
  const [tema, setTema] = useState(temaInicial);
  useEffect(() => {
    if (tema) document.documentElement.setAttribute("data-tema", tema);
    else document.documentElement.removeAttribute("data-tema");
    try { tema ? localStorage.setItem("tema", tema) : localStorage.removeItem("tema"); } catch (_) {}
  }, [tema]);
  const escuroAgora = () => tema === "escuro" || (!tema && matchMedia("(prefers-color-scheme: dark)").matches);
  return () => setTema(escuroAgora() ? "claro" : "escuro");
}

function Faixa() { return <div className="faixa" aria-hidden="true"><i /><i /><i /><i /></div>; }

function Login({ entrou }) {
  const [login, setLogin] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState(null);
  const entrar = async (e) => {
    e.preventDefault(); setErro(null);
    try { await API.enviar("/api/entrar", { login, senha }); entrou(); }
    catch (x) { setErro(x.message); }
  };
  return <div className="login-fundo"><div className="login">
    <Faixa />
    <form onSubmit={entrar}>
      <img className="claro" src="/static/marca/logo.png" alt="Empresa" />
      <img className="escuro" src="/static/marca/logo_branco.png" alt="Empresa" />
      <h1>Apoio à decisão comercial</h1>
      <label>Utilizador<input autoFocus autoComplete="username" value={login} onChange={(e) => setLogin(e.target.value)} /></label>
      <label>Palavra-passe<input type="password" autoComplete="current-password" value={senha} onChange={(e) => setSenha(e.target.value)} /></label>
      {erro && <p className="erro" style={{ margin: 0 }}>{erro}</p>}
      <button className="acao" disabled={!login || !senha}>Entrar</button>
    </form>
  </div></div>;
}

function Ciclo({ c }) {
  if (!c) return <span className="ciclo">ainda sem atualização</span>;
  const cor = c.ok === false ? "#ff8a8f" : c.ok ? "#3fe0c0" : "#fbba00";
  const dia = c.inicio.slice(0, 10), hora = c.inicio.slice(11, 16);
  const hoje = new Date().toISOString().slice(0, 10);
  const quando = (dia === hoje ? "hoje" : c.inicio.slice(8, 10) + "/" + c.inicio.slice(5, 7)) + " às " + hora;
  const texto = c.ok === null ? "a atualizar" : c.ok ? "Dados de " + quando : "A atualização falhou";
  return <span className="ciclo" title={(c.ok === false ? "Última tentativa " + quando + ". " : "") + (c.mensagem || "")}>
    <i className="ponto" style={{ background: cor }} /><span className="ciclo-t">{texto}</span></span>;
}

function App() {
  const [sessao, setSessao] = useState(0);
  const [r, erro] = usarDados(API.resumo, [sessao]);
  const rota = usarRota();
  const alternarTema = usarTema();

  if (erro && erro.status === 401) return <Login entrou={() => setSessao(sessao + 1)} />;
  if (erro) return <main><Erro erro={erro} /></main>;
  if (!r) return <main><Carregar /></main>;

  const gestor = r.eu.papel === "gestor";
  const meta = { estados: r.estados, tipos: r.tipos };
  const [pag, a1, a2, a3] = rota;
  let conteudo, atual = pag || "", pagComercial = false;

  if (!gestor) {
    // O comercial tem uma página: a sua (#/contactar, #/rever, #/carteira, #/dia/AAAA-MM-DD).
    pagComercial = true;
    conteudo = <PaginaComercial vendedor={r.eu.vendedor} eu={r.eu} meta={meta}
      dia={pag === "dia" ? a1 : null} aba={pag} />;
  } else if (pag === "comercial" && a1) {
    pagComercial = true;
    conteudo = <PaginaComercial key={a1} vendedor={a1} eu={r.eu} meta={meta}
      dia={a2 === "dia" ? a3 : null} aba={a2} />;
  } else if (pag === "pipeline") conteudo = <PipelineEmpresa r={r} />;
  else if (pag === "qualidade") conteudo = <Qualidade />;
  else if (pag === "parametros") conteudo = <Parametros />;
  else { conteudo = <Equipa r={r} />; atual = ""; }

  const Liga = ({ k, children }) => <a href={"#/" + k} aria-current={atual === k ? "page" : undefined}>{children}</a>;

  return <>
    <header className="topo">
      <div className="topo-in">
        <a href="#/" aria-label="Início"><img src="/static/marca/logo_branco.png" alt="Empresa" /></a>
        <span className="marca-nome">Apoio comercial</span>
        <div className="topo-dir">
          <Ciclo c={r.ultimo_ciclo} />
          <span className="quem">{r.eu.nome}{gestor && <span className="papel"> · gestão</span>}</span>
          <button onClick={alternarTema} title="Tema claro ou escuro" aria-label="Alternar tema claro ou escuro"><Icone n="tema" t={16} /></button>
          <button onClick={async () => { await API.enviar("/api/sair", {}); location.hash = ""; location.reload(); }}>Sair</button>
        </div>
      </div>
      <Faixa />
    </header>
    {gestor && <nav className="menu" aria-label="Vistas"><div className="menu-in">
      <Liga k="">Equipa</Liga>
      <Liga k="pipeline">Pipeline</Liga>
      <select value={pag === "comercial" ? a1 : ""} onChange={(e) => e.target.value && ir("comercial", e.target.value)}
        aria-label="Abrir a página de um comercial">
        <option value="">Página de…</option>
        {r.vendedores.map((v) => <option key={v} value={v}>{v}</option>)}
      </select>
      <div className="admin"><span className="admin-rot">Administração</span>
        <Liga k="qualidade">Qualidade</Liga>
        <Liga k="parametros">Parâmetros</Liga>
      </div>
    </div></nav>}
    <main className={pagComercial ? "pagina-comercial" : ""}>{conteudo}</main>
  </>;
}

ReactDOM.createRoot(document.getElementById("raiz")).render(<App />);
