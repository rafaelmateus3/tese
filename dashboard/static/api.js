/* Chamadas à API. Um erro de rede não pode ficar silencioso: sobe para quem
   chamou, que o mostra ao utilizador. O 401 leva o estado, para a página
   mostrar a entrada. */
const Q = (v) => (v ? "?vendedor=" + encodeURIComponent(v) : "");
window.API = {
  async pedir(caminho, opcoes) {
    const r = await fetch(caminho, { credentials: "same-origin", ...opcoes });
    const texto = await r.text();
    if (!r.ok) {
      let detalhe = r.statusText;
      try { detalhe = JSON.parse(texto).detail || detalhe; } catch (_) {}
      const e = new Error(typeof detalhe === "string" ? detalhe : JSON.stringify(detalhe));
      e.status = r.status;
      throw e;
    }
    return texto ? JSON.parse(texto) : {};
  },
  enviar(caminho, corpo) {
    return this.pedir(caminho, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
  },
  resumo: () => API.pedir("/api/resumo"),
  pagina: (v) => API.pedir("/api/pagina" + Q(v)),
  negocio: (id) => API.pedir("/api/negocio?negocio_id=" + encodeURIComponent(id)),
  lote: (v, d) => API.pedir(`/api/lote?vendedor=${encodeURIComponent(v)}&dia=${d}`),
  negociosCliente: (n) => API.pedir("/api/negocios-cliente?cliente_no=" + n),
  // só o gestor
  equipa: () => API.pedir("/api/equipa"),
  pipeline: (v, area, origem) => API.pedir("/api/pipeline?" + new URLSearchParams(
    Object.entries({ vendedor: v, area, origem }).filter(([, x]) => x))),
  qualidade: () => API.pedir("/api/qualidade"),
  parametros: () => API.pedir("/api/parametros"),
};
