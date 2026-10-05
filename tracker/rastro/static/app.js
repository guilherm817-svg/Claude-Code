/* Rastro — painel (JavaScript puro, sem build). Dados vindos da API entram no DOM só por textContent. */
"use strict";

const estado = {
  sessao: null,
  opcoes: null,
  filtros: carregarFiltros(),
  campanhas: { nivel: "campanha", trilha: [], ordem: { chave: "gasto", direcao: -1 } },
  vendas: { status: "", busca: "", pagina: 1 },
  timerAtualizacao: null,
};

// ------------------------------------------------------------------ utilitários

function el(tag, props, ...filhos) {
  const no = document.createElement(tag);
  let valor;
  for (const [chave, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (chave === "class") no.className = v;
    else if (chave === "text") no.textContent = v;
    else if (chave === "value") valor = v;
    else if (chave.startsWith("on") && typeof v === "function") no.addEventListener(chave.slice(2), v);
    else if (typeof v === "boolean" || typeof v === "number" && chave in no) no[chave] = v;
    else no.setAttribute(chave, v === true ? "" : v);
  }
  for (const filho of filhos.flat(Infinity)) {
    if (filho === null || filho === undefined || filho === false) continue;
    no.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
  if (valor !== undefined) no.value = valor;
  return no;
}

function svg(tag, atributos, ...filhos) {
  const no = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [chave, v] of Object.entries(atributos || {})) if (v !== null && v !== undefined) no.setAttribute(chave, v);
  for (const filho of filhos) if (filho) no.append(filho);
  return no;
}

// Ícones fixos do próprio app (não vêm de dados), então podem ir como HTML.
const ICONES = {
  painel: '<path d="M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zm10-18v6h8V3z"/>',
  campanhas: '<path d="M3 11v2a2 2 0 0 0 2 2h1l4 4V5L6 9H5a2 2 0 0 0-2 2zm13.5 1A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4zM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6z"/>',
  vendas: '<path d="M7 18a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM1 2v2h2l3.6 7.6L5.2 14A2 2 0 0 0 7 17h12v-2H7.4l1.1-2h7.5a2 2 0 0 0 1.7-1l3.6-6.5A1 1 0 0 0 20.4 4H5.2l-.9-2zm16 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4z"/>',
  integracoes: '<path d="M17 7h-4v2h4a3 3 0 0 1 0 6h-4v2h4a5 5 0 0 0 0-10zm-6 8H7a3 3 0 0 1 0-6h4V7H7a5 5 0 0 0 0 10h4zm-3-4h8v2H8z"/>',
  configuracoes: '<path d="M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.3 7.3 0 0 0-1.7-1L15 3.3h-4l-.4 2.6a7.3 7.3 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.3 7.3 0 0 0 1.7 1l.4 2.6h4l.4-2.6a7.3 7.3 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/>',
  sol: '<path d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM11 1h2v3h-2zm0 19h2v3h-2zM3.5 4.9l1.4-1.4L7 5.6 5.6 7zM17 18.4l1.4-1.4 2.1 2.1-1.4 1.4zM1 11h3v2H1zm19 0h3v2h-3zM3.5 19.1 5.6 17 7 18.4l-2.1 2.1zM17 5.6l2.1-2.1 1.4 1.4L18.4 7z"/>',
  sair: '<path d="M10 17l1.4 1.4L17.8 12l-6.4-6.4L10 7l3.6 3.6H2v2h11.6zM20 3h-8v2h8v14h-8v2h8a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2z"/>',
  editar: '<path d="M3 17.2V21h3.8l11-11-3.8-3.8zM20.7 7a1 1 0 0 0 0-1.4l-2.3-2.3a1 1 0 0 0-1.4 0l-1.8 1.8 3.8 3.8z"/>',
};

function icone(nome, tamanho = 18) {
  const span = el("span", { "aria-hidden": "true", style: "display:inline-flex" });
  span.innerHTML = `<svg viewBox="0 0 24 24" width="${tamanho}" height="${tamanho}" fill="currentColor">${ICONES[nome]}</svg>`;
  return span;
}

const LOGO = () => {
  const span = el("span", { "aria-hidden": "true", style: "display:inline-flex" });
  span.innerHTML = '<svg viewBox="0 0 32 32" width="28" height="28"><rect width="32" height="32" rx="8" fill="#2a78d6"/><path d="M8 22l6-7 4 4 6-9" stroke="white" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  return span;
};

const fmt = {
  moeda: new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }),
  moedaCompacta: new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1 }),
  numero: new Intl.NumberFormat("pt-BR"),
  pct: new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 1 }),
  dec: new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
};
const R$ = (v) => (v === null || v === undefined ? "—" : fmt.moeda.format(v));
const pct = (v) => (v === null || v === undefined ? "—" : fmt.pct.format(v));
const num = (v) => (v === null || v === undefined ? "—" : fmt.numero.format(v));
const roas = (v) => (v === null || v === undefined ? "—" : `${fmt.dec.format(v)}x`);

function dataCurta(iso) {
  const [, m, d] = iso.split("-");
  return `${d}/${m}`;
}

function dataHora(iso) {
  if (!iso) return "—";
  return new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

function haQuanto(iso) {
  if (!iso) return "nunca";
  const segundos = (Date.now() - new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z")) / 1000;
  if (segundos < 60) return "agora há pouco";
  if (segundos < 3600) return `há ${Math.round(segundos / 60)} min`;
  if (segundos < 86400) return `há ${Math.round(segundos / 3600)} h`;
  return `há ${Math.round(segundos / 86400)} dias`;
}

function aviso(mensagem, tipo = "ok") {
  const caixa = el("div", { class: `notificacao ${tipo === "erro" ? "erro" : ""}`, text: mensagem });
  document.getElementById("avisos").append(caixa);
  setTimeout(() => caixa.remove(), tipo === "erro" ? 6000 : 3000);
}

async function copiar(texto) {
  try {
    await navigator.clipboard.writeText(texto);
    aviso("Copiado!");
  } catch {
    window.prompt("Copie o texto abaixo:", texto);
  }
}

const NOMES_CAMPOS = { senha: "Senha", nova: "Nova senha", email: "E-mail", nome: "Nome", nome_conta: "Nome da operação", token: "Token" };

async function api(caminho, { metodo = "GET", corpo, params } = {}) {
  let url = caminho;
  if (params) {
    const consulta = new URLSearchParams();
    for (const [chave, valor] of Object.entries(params)) if (valor !== "" && valor !== null && valor !== undefined) consulta.set(chave, valor);
    if ([...consulta].length) url += "?" + consulta;
  }
  const cabecalhos = { "X-Rastro": "1" };
  if (corpo !== undefined) cabecalhos["Content-Type"] = "application/json";
  const resposta = await fetch(url, { method: metodo, headers: cabecalhos, credentials: "same-origin",
    body: corpo !== undefined ? JSON.stringify(corpo) : undefined });
  let dados = null;
  try { dados = await resposta.json(); } catch { /* sem corpo */ }
  if (resposta.status === 401 && !caminho.startsWith("/api/entrar") && !caminho.startsWith("/api/usuarios/senha")) {
    estado.sessao = null;
    iniciar();
    throw new Error("Sua sessão expirou. Entre de novo.");
  }
  if (!resposta.ok) {
    let mensagem = dados && dados.detail;
    if (Array.isArray(mensagem)) {
      mensagem = mensagem.map((erro) => {
        const campo = NOMES_CAMPOS[erro.loc && erro.loc[erro.loc.length - 1]] || "Campo";
        if (erro.type === "string_too_short") return `${campo}: mínimo de ${erro.ctx.min_length} caracteres.`;
        if (erro.type === "missing") return `${campo}: obrigatório.`;
        return (erro.msg || "").replace(/^Value error, /, "");
      }).join(" ");
    }
    throw new Error(mensagem || `Erro ${resposta.status}. Tente de novo.`);
  }
  return dados;
}

async function comBotao(botao, acao) {
  const texto = botao.textContent;
  botao.disabled = true;
  try {
    return await acao();
  } catch (erro) {
    aviso(erro.message, "erro");
  } finally {
    botao.disabled = false;
    botao.textContent = texto;
  }
}

function dica(texto) {
  return el("span", { class: "dica", title: texto, tabindex: "0", "aria-label": texto, text: "?" });
}

function faixa(titulo, texto, acao, tipo = "") {
  return el("div", { class: `faixa ${tipo}`, role: tipo === "erro" ? "alert" : "status" },
    el("div", { class: "texto" }, el("b", { text: titulo }), el("span", { class: "secundario", text: texto })),
    acao || null);
}

// ------------------------------------------------------------------ período e filtros

function carregarFiltros() {
  try {
    const salvo = JSON.parse(localStorage.getItem("rastro-filtros") || "null");
    if (salvo && salvo.preset) return salvo;
  } catch { /* ignora */ }
  return { preset: "hoje", inicio: "", fim: "", conta_anuncio_id: "", plataforma: "", produto_id: "", campanha: "" };
}

function salvarFiltros() {
  try { localStorage.setItem("rastro-filtros", JSON.stringify(estado.filtros)); } catch { /* modo privado */ }
}

function hoje() {
  const fuso = (estado.sessao && estado.sessao.conta.fuso) || "America/Sao_Paulo";
  return new Intl.DateTimeFormat("en-CA", { timeZone: fuso, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

function somarDias(iso, dias) {
  const data = new Date(iso + "T12:00:00Z");
  data.setUTCDate(data.getUTCDate() + dias);
  return data.toISOString().slice(0, 10);
}

const PRESETS = [
  ["hoje", "Hoje"], ["ontem", "Ontem"], ["7d", "7 dias"], ["30d", "30 dias"], ["mes", "Este mês"], ["mes_passado", "Mês passado"],
];

function periodo() {
  const f = estado.filtros;
  const h = hoje();
  switch (f.preset) {
    case "ontem": return [somarDias(h, -1), somarDias(h, -1)];
    case "7d": return [somarDias(h, -6), h];
    case "30d": return [somarDias(h, -29), h];
    case "mes": return [h.slice(0, 8) + "01", h];
    case "mes_passado": {
      const fim = somarDias(h.slice(0, 8) + "01", -1);
      return [fim.slice(0, 8) + "01", fim];
    }
    case "personalizado": return [f.inicio || h, f.fim || h];
    default: return [h, h];
  }
}

function parametrosFiltro() {
  const [inicio, fim] = periodo();
  const f = estado.filtros;
  return { inicio, fim, conta_anuncio_id: f.conta_anuncio_id, plataforma: f.plataforma, produto_id: f.produto_id, campanha: f.campanha };
}

function descricaoPeriodo() {
  const [inicio, fim] = periodo();
  const preset = PRESETS.find(([id]) => id === estado.filtros.preset);
  const datas = inicio === fim ? dataCurta(inicio) : `${dataCurta(inicio)} a ${dataCurta(fim)}`;
  return preset ? `${preset[1]} · ${datas}` : datas;
}

function barraFiltros(aoMudar) {
  const f = estado.filtros;
  const [inicio, fim] = periodo();
  const mudar = () => { salvarFiltros(); aoMudar(); };

  const botoes = PRESETS.map(([id, rotulo]) => el("button", {
    type: "button", text: rotulo, "aria-pressed": String(f.preset === id),
    onclick: () => { f.preset = id; mudar(); },
  }));
  const campoData = (valor, chave) => el("input", {
    type: "date", value: valor, "aria-label": chave === "inicio" ? "Data inicial" : "Data final",
    onchange: (evento) => {
      const [i, fi] = periodo();
      f.preset = "personalizado";
      f.inicio = chave === "inicio" ? evento.target.value : i;
      f.fim = chave === "fim" ? evento.target.value : fi;
      mudar();
    },
  });

  const op = estado.opcoes || { contas_anuncio: [], plataformas: [], produtos: [] };
  const seletor = (chave, rotulo, itens) => el("select", {
    "aria-label": rotulo, value: String(f[chave] || ""), onchange: (evento) => { f[chave] = evento.target.value; mudar(); },
  }, el("option", { value: "", text: rotulo }), itens.map(([valor, texto]) => el("option", { value: String(valor), text: texto })));

  let espera;
  const busca = el("input", {
    type: "search", placeholder: "Filtrar campanha…", value: f.campanha || "", "aria-label": "Filtrar por nome de campanha",
    oninput: (evento) => { clearTimeout(espera); espera = setTimeout(() => { f.campanha = evento.target.value.trim(); mudar(); }, 400); },
  });

  return el("div", { class: "filtros" },
    el("div", { class: "periodos", role: "group", "aria-label": "Período" }, botoes),
    el("div", { class: "datas" }, campoData(inicio, "inicio"), el("span", { class: "mudo", text: "a" }), campoData(fim, "fim")),
    op.contas_anuncio.length > 1 ? seletor("conta_anuncio_id", "Todas as contas de anúncio", op.contas_anuncio.map((c) => [c.id, c.nome])) : null,
    op.plataformas.length > 1 ? seletor("plataforma", "Todas as plataformas", op.plataformas.map((p) => [p, NOME_PLATAFORMA[p] || p])) : null,
    op.produtos.length > 1 ? seletor("produto_id", "Todos os produtos", op.produtos.map((p) => [p.id, p.nome])) : null,
    busca);
}

const NOME_PLATAFORMA = { hotmart: "Hotmart", kiwify: "Kiwify", generico: "Genérico" };
const NOME_METODO = { pix: "Pix", cartao: "Cartão", boleto: "Boleto", outro: "Outros" };
const STATUS_VENDA = {
  aprovada: ["Aprovada", "bom"], pendente: ["Pendente", "aviso"], recusada: ["Recusada", ""], cancelada: ["Cancelada", ""],
  reembolsada: ["Reembolsada", "critico"], chargeback: ["Chargeback", "critico"],
};

// ------------------------------------------------------------------ estrutura da página

const ROTAS = {
  painel: ["Painel", "painel", telaPainel],
  campanhas: ["Campanhas", "campanhas", telaCampanhas],
  vendas: ["Vendas", "vendas", telaVendas],
  integracoes: ["Integrações", "integracoes", telaIntegracoes],
  configuracoes: ["Configurações", "configuracoes", telaConfiguracoes],
};

function rotaAtual() {
  const nome = location.hash.replace(/^#\/?/, "").split("?")[0];
  return ROTAS[nome] ? nome : "painel";
}

function alternarTema() {
  const raiz = document.documentElement;
  const escuroAgora = raiz.getAttribute("data-theme") === "dark" ||
    (!raiz.getAttribute("data-theme") && matchMedia("(prefers-color-scheme: dark)").matches);
  const novo = escuroAgora ? "light" : "dark";
  raiz.setAttribute("data-theme", novo);
  try { localStorage.setItem("rastro-tema", novo); } catch { /* ignora */ }
  renderizar();
}

function casca(rota) {
  const usuario = estado.sessao.usuario;
  const menu = el("nav", { class: "menu", "aria-label": "Seções" }, Object.entries(ROTAS).map(([id, [rotulo, nomeIcone]]) =>
    el("a", { href: `#/${id}`, "aria-current": id === rota ? "page" : null, title: rotulo },
      icone(nomeIcone), el("span", { text: rotulo }))));
  const lateral = el("aside", { class: "lateral" },
    el("div", { class: "marca" }, LOGO(), el("span", { text: "Rastro" })),
    menu,
    el("div", { class: "lateral-rodape" },
      el("div", { class: "usuario" }, el("div", { text: usuario.nome }), el("div", { class: "mudo", text: estado.sessao.conta.nome })),
      el("div", { class: "linha-botoes" },
        el("button", { class: "botao icone fantasma", title: "Alternar tema claro/escuro", "aria-label": "Alternar tema", onclick: alternarTema }, icone("sol")),
        el("button", {
          class: "botao icone fantasma", title: "Sair", "aria-label": "Sair",
          onclick: async () => { await api("/api/sair", { metodo: "POST" }); estado.sessao = null; iniciar(); },
        }, icone("sair")))));
  const conteudo = el("main", { class: "conteudo", id: "conteudo" });
  return [el("div", { class: "casca" }, lateral, conteudo), conteudo];
}

function renderizar() {
  clearInterval(estado.timerAtualizacao);
  const app = document.getElementById("app");
  if (!estado.sessao) return;
  const rota = rotaAtual();
  const [pagina, conteudo] = casca(rota);
  app.replaceChildren(pagina);
  document.title = `${ROTAS[rota][0]} · Rastro`;
  ROTAS[rota][2](conteudo);
}

// ------------------------------------------------------------------ login e primeira configuração

function telaLogin(sessao) {
  const configurar = sessao.precisa_configurar;
  const erro = el("div", { class: "erro-form", role: "alert" });
  const campos = configurar ? [
    ["nome_conta", "Nome da operação", "text", "Ex.: Minha Empresa"],
    ["nome", "Seu nome", "text", ""],
    ["email", "E-mail", "email", ""],
    ["senha", "Senha (mínimo 8 caracteres)", "password", ""],
  ] : [["email", "E-mail", "email", ""], ["senha", "Senha", "password", ""]];
  const entradas = {};
  const botao = el("button", { class: "botao primario", type: "submit", text: configurar ? "Criar conta e entrar" : "Entrar" });
  const form = el("form", {
    onsubmit: async (evento) => {
      evento.preventDefault();
      erro.textContent = "";
      const corpo = Object.fromEntries(Object.entries(entradas).map(([chave, entrada]) => [chave, entrada.value]));
      botao.disabled = true;
      try {
        await api(configurar ? "/api/configurar" : "/api/entrar", { metodo: "POST", corpo });
        await iniciar();
      } catch (e) {
        erro.textContent = e.message;
      } finally {
        botao.disabled = false;
      }
    },
  }, campos.map(([chave, rotulo, tipo, dicaCampo]) => {
    entradas[chave] = el("input", { type: tipo, name: chave, required: true, placeholder: dicaCampo,
      autocomplete: tipo === "password" ? (configurar ? "new-password" : "current-password") : (tipo === "email" ? "email" : "off") });
    return el("label", { class: "campo" }, el("span", { text: rotulo }), entradas[chave]);
  }), erro, botao);
  document.getElementById("app").replaceChildren(el("div", { class: "tela-login" },
    el("div", { class: "cartao" }, LOGO(),
      el("h1", { text: configurar ? "Bem-vindo ao Rastro" : "Entrar no Rastro" }),
      el("p", { class: "secundario", text: configurar
        ? "Crie o acesso de administrador. Depois você conecta o checkout, o pixel e o Meta Ads."
        : "Rastreamento de vendas, gastos e lucro por anúncio." }),
      form)));
  (entradas.nome_conta || entradas.email).focus();
}

// ------------------------------------------------------------------ painel

const DEFINICOES = {
  lucro: "Faturamento líquido − gasto com anúncios − impostos − custo dos produtos.",
  faturamento: "O que fica para você das vendas aprovadas, já sem as taxas da plataforma.",
  gasto: "Gasto no Meta Ads no período, convertido pela cotação da conta e somado ao imposto sobre anúncios.",
  roas: "Faturamento líquido ÷ gasto com anúncios. Acima de 1,00x o anúncio se paga.",
  roi: "Lucro ÷ custos (anúncios + impostos + produto).",
  cpa: "Custo por aquisição: gasto com anúncios ÷ vendas aprovadas.",
  margem: "Lucro ÷ faturamento líquido.",
  pendentes: "Boletos e Pix gerados que ainda não foram pagos.",
  reembolsos: "Vendas do período reembolsadas ou com chargeback.",
};

function variacao(atual, anterior, sentido) {
  if (atual === null || atual === undefined || anterior === null || anterior === undefined || anterior === 0) return null;
  const mudanca = (atual - anterior) / Math.abs(anterior);
  if (!isFinite(mudanca) || Math.abs(mudanca) < 0.0005) return el("span", { class: "delta mudo", text: "= período anterior" });
  const subiu = mudanca > 0;
  const classe = sentido === 0 ? "mudo" : (subiu === (sentido > 0) ? "pos" : "neg");
  return el("span", { class: `delta ${classe}`, title: "Comparado ao período anterior de mesmo tamanho" },
    `${subiu ? "▲" : "▼"} ${fmt.pct.format(Math.abs(mudanca))}`, el("span", { class: "mudo", style: "font-weight:400", text: " vs. anterior" }));
}

function kpi({ rotulo, valor, detalhe, definicao, delta, heroi = false, classeValor = "" }) {
  return el("div", { class: `cartao kpi ${heroi ? "heroi" : ""}` },
    el("div", { class: "rotulo" }, rotulo, definicao ? dica(definicao) : null),
    el("div", { class: `valor ${classeValor}`, text: valor, title: valor }),
    delta || null,
    detalhe ? el("div", { class: "detalhe", text: detalhe }) : null);
}

async function telaPainel(conteudo) {
  const corpo = el("div");
  conteudo.replaceChildren(
    el("div", { class: "cabecalho" },
      el("div", {}, el("h1", { text: "Painel" }), el("div", { class: "mudo", id: "descricao-periodo", text: descricaoPeriodo() })),
      el("div", { class: "acoes" }, el("span", { class: "mudo", id: "atualizado" }),
        el("button", { class: "botao", text: "Atualizar", onclick: () => carregar() }))),
    barraFiltros(() => telaPainel(conteudo)),
    corpo);

  async function carregar() {
    corpo.classList.add("recarregando");
    try {
      const dados = await api("/api/painel", { params: parametrosFiltro() });
      desenharPainel(corpo, dados);
      const atualizado = document.getElementById("atualizado");
      if (atualizado) atualizado.textContent = `Atualizado às ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
    } catch (erro) {
      if (!corpo.childElementCount) corpo.replaceChildren(faixa("Não foi possível carregar o painel", erro.message, null, "erro"));
      else aviso(erro.message, "erro");
    } finally {
      corpo.classList.remove("recarregando");
    }
  }

  await carregar();
  // Vendas chegam o tempo todo: atualiza a cada minuto enquanto a aba está visível.
  estado.timerAtualizacao = setInterval(() => { if (!document.hidden) carregar(); }, 60000);
}

function desenharPainel(corpo, dados) {
  const r = dados.resumo;
  const a = dados.anterior;
  const avisos = [];
  if (!estado.opcoes.tem_vendas) {
    avisos.push(faixa("Nenhuma venda recebida ainda",
      "Configure o webhook do seu checkout e instale o pixel nas páginas para começar a rastrear.",
      el("a", { class: "botao primario pequeno", href: "#/integracoes", text: "Configurar integrações" })));
  }
  if (!dados.meta.conectado) {
    avisos.push(faixa("Meta Ads não conectado",
      "Sem o gasto dos anúncios o painel não calcula lucro, ROAS e CPA.",
      el("a", { class: "botao pequeno", href: "#/integracoes", text: "Conectar Meta Ads" })));
  } else if (!dados.meta.contas_ativas) {
    avisos.push(faixa("Nenhuma conta de anúncio sincronizando",
      "Escolha quais contas de anúncio o Rastro deve acompanhar.",
      el("a", { class: "botao pequeno", href: "#/integracoes", text: "Escolher contas" })));
  }
  for (const erro of dados.meta.erros) avisos.push(faixa(`Erro ao sincronizar ${erro.conta}`, erro.erro, null, "erro"));

  const kpis = el("div", { class: "grade-kpi" },
    kpi({ rotulo: "Lucro", valor: R$(r.lucro), heroi: true, definicao: DEFINICOES.lucro, classeValor: r.lucro < 0 ? "neg" : "",
      delta: variacao(r.lucro, a.lucro, 1), detalhe: `Margem ${pct(r.margem)} · ROI ${pct(r.roi)}` }),
    kpi({ rotulo: "Faturamento líquido", valor: R$(r.faturamento_liquido), definicao: DEFINICOES.faturamento,
      delta: variacao(r.faturamento_liquido, a.faturamento_liquido, 1), detalhe: `Bruto ${R$(r.faturamento_bruto)}` }),
    kpi({ rotulo: "Gasto com anúncios", valor: R$(r.gasto), definicao: DEFINICOES.gasto, delta: variacao(r.gasto, a.gasto, 0) }),
    kpi({ rotulo: "ROAS", valor: roas(r.roas), definicao: DEFINICOES.roas, delta: variacao(r.roas, a.roas, 1) }),
    kpi({ rotulo: "Vendas aprovadas", valor: num(r.vendas), delta: variacao(r.vendas, a.vendas, 1),
      detalhe: r.ticket_medio ? `Ticket médio ${R$(r.ticket_medio)}` : null }),
    kpi({ rotulo: "CPA", valor: R$(r.cpa), definicao: DEFINICOES.cpa, delta: variacao(r.cpa, a.cpa, -1) }),
    kpi({ rotulo: "Vendas pendentes", valor: num(r.pendentes), definicao: DEFINICOES.pendentes, detalhe: R$(r.pendentes_valor) }),
    kpi({ rotulo: "Reembolsos", valor: pct(r.taxa_reembolso), definicao: DEFINICOES.reembolsos,
      detalhe: `${num(r.reembolsadas + r.chargebacks)} vendas · ${R$(r.reembolsadas_valor + r.chargebacks_valor)}` }));

  const caixaGrafico = el("div", { class: "grafico" });
  const tabelaSerie = el("div", { class: "oculto" });
  const botaoTabela = el("button", {
    class: "botao pequeno fantasma", text: "Ver tabela", "aria-expanded": "false",
    onclick: () => {
      const mostrar = tabelaSerie.classList.toggle("oculto") === false;
      caixaGrafico.classList.toggle("oculto", mostrar);
      botaoTabela.textContent = mostrar ? "Ver gráfico" : "Ver tabela";
      botaoTabela.setAttribute("aria-expanded", String(mostrar));
      if (!mostrar) desenharGrafico(caixaGrafico, dados.serie);
    },
  });
  tabelaSerie.append(el("div", { class: "tabela-rolagem" }, el("table", {},
    el("thead", {}, el("tr", {}, ["Dia", "Faturamento líquido", "Gasto", "Lucro", "Vendas", "ROAS"].map((t, i) => el("th", { class: i ? "n" : "", text: t })))),
    el("tbody", {}, dados.serie.map((p) => el("tr", {},
      el("td", { text: dataCurta(p.dia) }), el("td", { class: "n", text: R$(p.faturamento_liquido) }), el("td", { class: "n", text: R$(p.gasto) }),
      el("td", { class: `n ${p.lucro < 0 ? "neg" : ""}`, text: R$(p.lucro) }), el("td", { class: "n", text: num(p.vendas) }),
      el("td", { class: "n", text: roas(p.roas) })))))));

  const cartaoGrafico = el("section", { class: "cartao", "aria-labelledby": "titulo-grafico" },
    el("div", { class: "topo" }, el("h2", { id: "titulo-grafico", text: "Faturamento, gasto e lucro por dia" }),
      el("div", { class: "legenda" }, SERIES_GRAFICO.map((s) => el("span", {}, el("i", { style: `background:${s.cor}` }), s.nome)), botaoTabela)),
    el("div", { class: "corpo" }, caixaGrafico, tabelaSerie));

  const cartaoPagamentos = el("section", { class: "cartao" },
    el("div", { class: "topo" }, el("h2", { text: "Conversão por pagamento" }), dica("Pagas ÷ geradas. Inclui vendas que depois foram reembolsadas.")),
    el("div", { class: "corpo" }, dados.pagamentos.map((p) => el("div", { class: "medidor" },
      el("div", { class: "linha" }, el("b", { text: NOME_METODO[p.metodo] || p.metodo }), el("span", { class: "num", text: pct(p.conversao) })),
      el("div", {
        class: "trilho", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round((p.conversao || 0) * 100)),
        "aria-label": `Conversão ${NOME_METODO[p.metodo]}`,
      }, el("div", { style: `width:${Math.round((p.conversao || 0) * 100)}%` })),
      el("div", { class: "linha mudo" }, el("span", { text: `${num(p.pagas)} pagas de ${num(p.geradas)}` }), el("span", { class: "num", text: R$(p.faturamento_liquido) }))))));

  const listaNumeros = (itens) => el("div", { class: "lista-numeros" }, itens.map(([rotulo, valor, classe]) =>
    el("div", { class: "item" }, el("span", { text: rotulo }), el("b", { class: `num ${classe || ""}`, text: valor }))));
  const ranking = (titulo, linhas, nomeVazio) => el("section", { class: "cartao" },
    el("div", { class: "topo" }, el("h2", { text: titulo })),
    el("div", { class: "corpo" }, linhas.length
      ? listaNumeros(linhas.map((l) => [l.nome ? (NOME_PLATAFORMA[l.nome] || l.nome) : nomeVazio, `${num(l.vendas)} · ${R$(l.faturamento_liquido)}`]))
      : el("div", { class: "mudo", text: "Sem vendas no período." })));

  corpo.replaceChildren(
    ...avisos,
    kpis,
    el("div", { class: "grade-2" }, cartaoGrafico, cartaoPagamentos),
    el("div", { class: "grade-3" },
      ranking("Vendas por origem (utm_source)", dados.por_origem, "Sem UTM"),
      ranking("Vendas por produto", dados.por_produto, "Sem produto"),
      el("section", { class: "cartao" },
        el("div", { class: "topo" }, el("h2", { text: "Outros números" })),
        el("div", { class: "corpo" }, listaNumeros([
          ["Impostos", R$(r.impostos)],
          ["Custo dos produtos", R$(r.custo_produtos)],
          ["Chargebacks", `${num(r.chargebacks)} · ${R$(r.chargebacks_valor)}`],
          ["Cartões recusados", num(r.recusadas)],
          ["Visitas rastreadas pelo pixel", num(r.visitas)],
          ["Cliques para o checkout", num(r.cliques_checkout)],
          ["Vendas aprovadas sem origem", num(r.vendas_sem_origem), r.vendas_sem_origem ? "neg" : ""],
        ])))));
  requestAnimationFrame(() => desenharGrafico(caixaGrafico, dados.serie));
}

// ------------------------------------------------------------------ gráfico de linhas (SVG)

const SERIES_GRAFICO = [
  { chave: "faturamento_liquido", nome: "Faturamento líquido", cor: "var(--serie-1)" },
  { chave: "gasto", nome: "Gasto com anúncios", cor: "var(--serie-2)" },
  { chave: "lucro", nome: "Lucro", cor: "var(--serie-3)" },
];

function escalaBonita(minimo, maximo, alvo = 5) {
  const bonito = (valor, arredondar) => {
    const expoente = Math.floor(Math.log10(valor));
    const fracao = valor / 10 ** expoente;
    let base;
    if (arredondar) base = fracao < 1.5 ? 1 : fracao < 3 ? 2 : fracao < 7 ? 5 : 10;
    else base = fracao <= 1 ? 1 : fracao <= 2 ? 2 : fracao <= 5 ? 5 : 10;
    return base * 10 ** expoente;
  };
  const passo = bonito(bonito(maximo - minimo, false) / (alvo - 1), true);
  const inicio = Math.floor(minimo / passo) * passo;
  const fim = Math.ceil(maximo / passo) * passo;
  const valores = [];
  for (let v = inicio; v <= fim + passo / 2; v += passo) valores.push(Math.round(v * 100) / 100);
  return { min: inicio, max: fim, valores };
}

function desenharGrafico(caixa, serie) {
  caixa.replaceChildren();
  if (!serie.length) return;
  const largura = caixa.clientWidth || 640;
  const altura = caixa.clientHeight || 290;
  const margem = { topo: 10, direita: 14, base: 28, esquerda: 70 };
  const valores = serie.flatMap((p) => SERIES_GRAFICO.map((s) => p[s.chave] || 0));
  let minimo = Math.min(0, ...valores);
  let maximo = Math.max(0, ...valores);
  if (maximo === minimo) maximo = minimo + 100;
  const escala = escalaBonita(minimo, maximo);
  const larguraUtil = largura - margem.esquerda - margem.direita;
  const alturaUtil = altura - margem.topo - margem.base;
  const x = (i) => margem.esquerda + (serie.length === 1 ? larguraUtil / 2 : (i * larguraUtil) / (serie.length - 1));
  const y = (v) => margem.topo + ((escala.max - v) / (escala.max - escala.min)) * alturaUtil;

  const desenho = svg("svg", { viewBox: `0 0 ${largura} ${altura}`, role: "img", tabindex: "0",
    "aria-label": "Gráfico de faturamento líquido, gasto e lucro por dia. Use as setas para navegar pelos dias." });

  for (const valor of escala.valores) {
    desenho.append(svg("line", { class: valor === 0 ? "linha-zero" : "grade-linha", x1: margem.esquerda, x2: largura - margem.direita, y1: y(valor), y2: y(valor) }));
    const rotulo = svg("text", { class: "eixo-texto", x: margem.esquerda - 8, y: y(valor) + 4, "text-anchor": "end" });
    rotulo.textContent = fmt.moedaCompacta.format(valor);
    desenho.append(rotulo);
  }
  const intervalo = Math.max(1, Math.ceil(serie.length / Math.max(1, Math.floor(larguraUtil / 58))));
  serie.forEach((p, i) => {
    if (i % intervalo !== 0 && i !== serie.length - 1) return;
    if (i === serie.length - 1 && i % intervalo !== 0 && serie.length > 1 && x(i) - x(i - (i % intervalo)) < 48) return;
    const rotulo = svg("text", { class: "eixo-texto", x: x(i), y: altura - 8, "text-anchor": "middle" });
    rotulo.textContent = dataCurta(p.dia);
    desenho.append(rotulo);
  });

  for (const s of SERIES_GRAFICO) {
    const caminho = serie.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[s.chave] || 0).toFixed(1)}`).join("");
    desenho.append(svg("path", { d: caminho, fill: "none", style: `stroke:${s.cor}`, "stroke-width": "2", "stroke-linejoin": "round", "stroke-linecap": "round" }));
    if (serie.length <= 3) {
      serie.forEach((p, i) => desenho.append(svg("circle", { cx: x(i), cy: y(p[s.chave] || 0), r: 4,
        style: `fill:${s.cor};stroke:var(--superficie)`, "stroke-width": "2" })));
    }
  }

  const mira = svg("line", { class: "mira oculto", y1: margem.topo, y2: margem.topo + alturaUtil });
  const marcadores = SERIES_GRAFICO.map((s) => svg("circle", { r: 4, class: "oculto", style: `fill:${s.cor};stroke:var(--superficie)`, "stroke-width": "2" }));
  desenho.append(mira, ...marcadores);
  const alvo = svg("rect", { x: margem.esquerda - 10, y: 0, width: larguraUtil + 20, height: altura, fill: "transparent" });
  desenho.append(alvo);

  const dicaCaixa = el("div", { class: "dica-grafico oculto", role: "tooltip" });
  caixa.append(desenho, dicaCaixa);

  let atual = -1;
  function mostrar(indice) {
    atual = Math.max(0, Math.min(serie.length - 1, indice));
    const p = serie[atual];
    const px = x(atual);
    mira.setAttribute("x1", px); mira.setAttribute("x2", px); mira.classList.remove("oculto");
    SERIES_GRAFICO.forEach((s, i) => {
      marcadores[i].setAttribute("cx", px); marcadores[i].setAttribute("cy", y(p[s.chave] || 0)); marcadores[i].classList.remove("oculto");
    });
    const [ano, mes, dia] = p.dia.split("-");
    dicaCaixa.replaceChildren(
      el("div", { class: "titulo", text: new Date(Date.UTC(ano, mes - 1, dia, 12)).toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" }) }),
      ...SERIES_GRAFICO.map((s) => el("div", { class: "linha" }, el("i", { style: `background:${s.cor}` }), el("span", { text: s.nome }),
        el("b", { class: s.chave === "lucro" && p.lucro < 0 ? "neg" : "", text: R$(p[s.chave]) }))),
      el("div", { class: "linha" }, el("i"), el("span", { text: "Vendas · ROAS" }), el("b", { text: `${num(p.vendas)} · ${roas(p.roas)}` })));
    dicaCaixa.classList.remove("oculto");
    const larguraDica = dicaCaixa.offsetWidth;
    const esquerda = px + 14 + larguraDica > largura ? px - 14 - larguraDica : px + 14;
    dicaCaixa.style.left = `${Math.max(0, esquerda)}px`;
    dicaCaixa.style.top = `${margem.topo}px`;
  }
  function esconder() {
    mira.classList.add("oculto");
    marcadores.forEach((m) => m.classList.add("oculto"));
    dicaCaixa.classList.add("oculto");
  }
  alvo.addEventListener("pointermove", (evento) => {
    const caixaSvg = desenho.getBoundingClientRect();
    const px = ((evento.clientX - caixaSvg.left) / caixaSvg.width) * largura;
    const indice = serie.length === 1 ? 0 : Math.round(((px - margem.esquerda) / larguraUtil) * (serie.length - 1));
    mostrar(indice);
  });
  alvo.addEventListener("pointerleave", esconder);
  desenho.addEventListener("focus", () => mostrar(atual < 0 ? serie.length - 1 : atual));
  desenho.addEventListener("blur", esconder);
  desenho.addEventListener("keydown", (evento) => {
    if (evento.key === "ArrowLeft") { mostrar(atual - 1); evento.preventDefault(); }
    if (evento.key === "ArrowRight") { mostrar(atual + 1); evento.preventDefault(); }
  });

  if (!caixa._observador) {
    let ultimaLargura = largura;
    caixa._observador = new ResizeObserver(() => {
      if (Math.abs(caixa.clientWidth - ultimaLargura) > 4 && caixa.isConnected) {
        ultimaLargura = caixa.clientWidth;
        desenharGrafico(caixa, serie);
      }
    });
    caixa._observador.observe(caixa);
  }
}

// ------------------------------------------------------------------ campanhas

const STATUS_EFETIVO = {
  ACTIVE: ["Ativo", "bom"], PAUSED: ["Pausado", ""], CAMPAIGN_PAUSED: ["Campanha pausada", ""], ADSET_PAUSED: ["Conjunto pausado", ""],
  DISAPPROVED: ["Reprovado", "critico"], PENDING_REVIEW: ["Em análise", "aviso"], WITH_ISSUES: ["Com problemas", "aviso"],
  IN_PROCESS: ["Processando", "aviso"], ARCHIVED: ["Arquivado", ""], DELETED: ["Excluído", ""], PENDING_BILLING_INFO: ["Pagamento pendente", "critico"],
};
const NIVEIS = [["campanha", "Campanhas"], ["conjunto", "Conjuntos"], ["anuncio", "Anúncios"]];
const PROXIMO_NIVEL = { campanha: "conjunto", conjunto: "anuncio" };

const COLUNAS_ANUNCIOS = [
  ["orcamento_diario", "Orçamento", (l) => orcamentoTexto(l)],
  ["gasto", "Gasto", (l) => R$(l.gasto)],
  ["vendas", "Vendas", (l) => num(l.vendas)],
  ["faturamento_liquido", "Faturamento", (l) => R$(l.faturamento_liquido)],
  ["lucro", "Lucro", (l) => R$(l.lucro), (l) => (l.lucro < 0 ? "neg" : l.lucro > 0 ? "pos" : "")],
  ["roas", "ROAS", (l) => roas(l.roas)],
  ["cpa", "CPA", (l) => R$(l.cpa)],
  ["margem", "Margem", (l) => pct(l.margem)],
  ["pendentes", "Pendentes", (l) => num(l.pendentes)],
  ["checkouts_iniciados", "IC (Meta)", (l) => num(l.checkouts_iniciados)],
  ["cpm", "CPM", (l) => R$(l.cpm)],
  ["ctr", "CTR", (l) => pct(l.ctr)],
  ["cpc", "CPC", (l) => R$(l.cpc)],
  ["visualizacoes_pagina", "Vis. página", (l) => num(l.visualizacoes_pagina)],
  ["visitas", "Visitas (pixel)", (l) => num(l.visitas)],
];

function orcamentoTexto(linha) {
  if (linha.orcamento_diario) return `${R$(linha.orcamento_diario)}/dia`;
  if (linha.orcamento_total) return `${R$(linha.orcamento_total)} total`;
  return "—";
}

async function telaCampanhas(conteudo) {
  const est = estado.campanhas;
  const corpo = el("div");
  const statusSinc = el("span", { class: "mudo" });
  const botaoSinc = el("button", { class: "botao", text: "Sincronizar agora" });
  botaoSinc.addEventListener("click", () => comBotao(botaoSinc, async () => {
    await api("/api/meta/sincronizar", { metodo: "POST", corpo: {} });
    aviso("Sincronização iniciada. Os números atualizam em instantes.");
    setTimeout(() => carregar(), 6000);
  }));
  conteudo.replaceChildren(
    el("div", { class: "cabecalho" },
      el("div", {}, el("h1", { text: "Campanhas" }), el("div", { class: "mudo", text: descricaoPeriodo() })),
      el("div", { class: "acoes" }, statusSinc, botaoSinc)),
    barraFiltros(() => telaCampanhas(conteudo)),
    corpo);

  async function carregar() {
    corpo.classList.add("recarregando");
    const pai = est.trilha.length ? est.trilha[est.trilha.length - 1].id : null;
    try {
      const [dados, meta] = await Promise.all([
        api("/api/anuncios", { params: { ...parametrosFiltro(), nivel: est.nivel, pai } }),
        api("/api/meta"),
      ]);
      const ultima = meta.contas_anuncio.filter((c) => c.ativo).map((c) => c.ultima_sincronizacao).filter(Boolean).sort().pop();
      statusSinc.textContent = meta.sincronizando ? "Sincronizando…" : (meta.conectado ? `Meta sincronizado ${haQuanto(ultima)}` : "");
      botaoSinc.classList.toggle("oculto", !meta.conectado);
      desenharCampanhas(corpo, dados, meta, carregar);
    } catch (erro) {
      corpo.replaceChildren(faixa("Não foi possível carregar as campanhas", erro.message, null, "erro"));
    } finally {
      corpo.classList.remove("recarregando");
    }
  }
  await carregar();
}

function desenharCampanhas(corpo, dados, meta, recarregar) {
  const est = estado.campanhas;
  const abas = el("div", { class: "abas", role: "tablist" }, NIVEIS.map(([id, rotulo]) => el("button", {
    role: "tab", "aria-selected": String(est.nivel === id), text: rotulo,
    onclick: () => { est.nivel = id; est.trilha = []; recarregar(); },
  })));
  const migalhas = est.trilha.length ? el("div", { class: "migalhas" },
    el("button", { text: "Todas as campanhas", onclick: () => { est.nivel = "campanha"; est.trilha = []; recarregar(); } }),
    est.trilha.map((item, i) => [el("span", { text: "›" }), i === est.trilha.length - 1
      ? el("b", { text: item.nome })
      : el("button", { text: item.nome, onclick: () => { est.trilha = est.trilha.slice(0, i + 1); est.nivel = PROXIMO_NIVEL[item.nivel]; recarregar(); } })])) : null;

  const linhas = [...dados.linhas];
  const { chave, direcao } = est.ordem;
  if (chave !== "nome") linhas.sort((a, b) => ((a[chave] ?? -Infinity) - (b[chave] ?? -Infinity)) * direcao);
  else linhas.sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR") * direcao);

  if (!linhas.length) {
    corpo.replaceChildren(el("div", { class: "cabecalho" }, abas, migalhas), el("div", { class: "cartao" }, el("div", { class: "vazio" },
      el("h3", { text: meta.conectado ? "Nada neste período" : "Conecte o Meta Ads" }),
      el("p", { text: meta.conectado
        ? "Sem gasto nem vendas atribuídas a anúncios no período. Confira as UTMs dos anúncios em Integrações."
        : "Conecte sua conta para ver gasto, ROAS e lucro de cada campanha, conjunto e anúncio." }),
      meta.conectado ? null : el("a", { class: "botao primario", href: "#/integracoes", text: "Conectar Meta Ads" }))));
    return;
  }

  const cabecalhoColuna = (id, rotulo, classe = "n") => el("th", {
    class: `ordenavel ${classe}`, scope: "col", text: rotulo, tabindex: "0",
    "aria-sort": chave === id ? (direcao < 0 ? "descending" : "ascending") : null,
    onclick: () => { est.ordem = { chave: id, direcao: chave === id ? -direcao : -1 }; desenharCampanhas(corpo, dados, meta, recarregar); },
    onkeydown: (evento) => { if (evento.key === "Enter") evento.target.click(); },
  });

  const linhaTabela = (linha) => {
    const status = STATUS_EFETIVO[linha.status_efetivo] || null;
    const podeEntrar = linha.id && PROXIMO_NIVEL[est.nivel];
    const interruptor = linha.id && linha.status && meta.conectado ? el("label", { class: "interruptor", title: linha.status === "ACTIVE" ? "Pausar" : "Ativar" },
      el("input", {
        type: "checkbox", checked: linha.status === "ACTIVE", "aria-label": `${linha.status === "ACTIVE" ? "Pausar" : "Ativar"} ${linha.nome}`,
        onchange: async (evento) => {
          const caixa = evento.target;
          const novo = caixa.checked ? "ACTIVE" : "PAUSED";
          if (!confirm(`${novo === "ACTIVE" ? "Ativar" : "Pausar"} "${linha.nome}" no Meta Ads?`)) { caixa.checked = !caixa.checked; return; }
          caixa.disabled = true;
          try {
            await api(`/api/anuncios/${encodeURIComponent(linha.id)}/status`, { metodo: "POST", corpo: { status: novo } });
            linha.status = novo; linha.status_efetivo = novo;
            aviso(novo === "ACTIVE" ? "Ativado no Meta Ads." : "Pausado no Meta Ads.");
            desenharCampanhas(corpo, dados, meta, recarregar);
          } catch (erro) {
            caixa.checked = !caixa.checked;
            aviso(erro.message, "erro");
          } finally { caixa.disabled = false; }
        },
      }), el("span")) : null;
    const nome = podeEntrar
      ? el("button", { class: "link", text: linha.nome, title: linha.nome, onclick: () => {
        est.trilha = [...est.trilha, { nivel: est.nivel, id: linha.id, nome: linha.nome }];
        est.nivel = PROXIMO_NIVEL[est.nivel];
        recarregar();
      } })
      : el("span", { class: "sem-link", text: linha.nome, title: linha.id ? linha.nome : `${linha.nome} — as UTMs desta venda não têm o ID do Meta` });
    const celulaOrcamento = (l) => {
      if (!l.orcamento_diario || !meta.conectado) return el("td", { class: "n", text: orcamentoTexto(l) });
      return el("td", { class: "n" }, orcamentoTexto(l), " ", el("button", {
        class: "botao fantasma pequeno", title: "Alterar orçamento diário", "aria-label": `Alterar orçamento de ${l.nome}`, style: "padding:0 4px;height:22px",
        onclick: async () => {
          const resposta = prompt(`Novo orçamento diário para "${l.nome}" (R$):`, String(l.orcamento_diario).replace(".", ","));
          if (resposta === null) return;
          const valor = Number(resposta.replace(/\./g, "").replace(",", "."));
          if (!(valor > 0)) { aviso("Valor inválido.", "erro"); return; }
          try {
            await api(`/api/anuncios/${encodeURIComponent(l.id)}/orcamento`, { metodo: "POST", corpo: { orcamento_diario: valor } });
            l.orcamento_diario = valor;
            aviso("Orçamento alterado no Meta Ads.");
            desenharCampanhas(corpo, dados, meta, recarregar);
          } catch (erro) { aviso(erro.message, "erro"); }
        },
      }, icone("editar", 14)));
    };
    return el("tr", {},
      el("td", {}, el("div", { class: "nome-entidade" }, interruptor, el("div", { style: "display:grid;min-width:0" }, nome,
        status ? el("span", { class: `selo ${status[1]}`, style: "justify-self:start;margin-top:3px", text: status[0] }) : null))),
      COLUNAS_ANUNCIOS.map(([id, , formatar, classe]) => id === "orcamento_diario" ? celulaOrcamento(linha)
        : el("td", { class: `n ${classe ? classe(linha) : ""}`, text: formatar(linha) })));
  };

  const soma = (campo) => linhas.reduce((total, l) => total + (l[campo] || 0), 0);
  const totais = {
    gasto: soma("gasto"), vendas: soma("vendas"), faturamento_liquido: soma("faturamento_liquido"), lucro: soma("lucro"),
    pendentes: soma("pendentes"), checkouts_iniciados: soma("checkouts_iniciados"), visualizacoes_pagina: soma("visualizacoes_pagina"),
    visitas: soma("visitas"), impressoes: soma("impressoes"), cliques_link: soma("cliques_link"),
  };
  totais.roas = totais.gasto ? totais.faturamento_liquido / totais.gasto : null;
  totais.cpa = totais.vendas ? totais.gasto / totais.vendas : null;
  totais.margem = totais.faturamento_liquido ? totais.lucro / totais.faturamento_liquido : null;
  totais.cpm = totais.impressoes ? (totais.gasto / totais.impressoes) * 1000 : null;
  totais.ctr = totais.impressoes ? totais.cliques_link / totais.impressoes : null;
  totais.cpc = totais.cliques_link ? totais.gasto / totais.cliques_link : null;

  corpo.replaceChildren(
    el("div", { class: "cabecalho" }, abas, migalhas),
    el("div", { class: "cartao" }, el("div", { class: "tabela-rolagem", style: "border-top:0" }, el("table", { class: "tabela-anuncios" },
      el("thead", {}, el("tr", {}, cabecalhoColuna("nome", NIVEIS.find(([id]) => id === est.nivel)[1].replace(/s$/, ""), ""),
        COLUNAS_ANUNCIOS.map(([id, rotulo]) => cabecalhoColuna(id, rotulo)))),
      el("tbody", {}, linhas.map(linhaTabela)),
      el("tfoot", {}, el("tr", {}, el("td", { text: `Total (${linhas.length})` }),
        COLUNAS_ANUNCIOS.map(([id, , formatar, classe]) => el("td", {
          class: `n ${classe ? classe(totais) : ""}`, text: id === "orcamento_diario" ? "" : formatar(totais),
        }))))))),
    el("p", { class: "mudo", style: "margin-top:10px;font-size:12.5px",
      text: "Vendas atribuídas pelas UTMs (último clique). IC = checkouts iniciados contados pelo pixel do Meta. Visitas = chegadas registradas pelo pixel do Rastro." }));
}

// ------------------------------------------------------------------ vendas

async function telaVendas(conteudo) {
  const est = estado.vendas;
  const corpo = el("div");
  let espera;
  conteudo.replaceChildren(
    el("div", { class: "cabecalho" }, el("div", {}, el("h1", { text: "Vendas" }), el("div", { class: "mudo", text: descricaoPeriodo() }))),
    barraFiltros(() => { est.pagina = 1; telaVendas(conteudo); }),
    el("div", { class: "filtros", style: "margin-top:-8px" },
      el("select", { "aria-label": "Status", value: est.status, onchange: (e) => { est.status = e.target.value; est.pagina = 1; carregar(); } },
        el("option", { value: "", text: "Todos os status" }),
        Object.entries(STATUS_VENDA).map(([id, [rotulo]]) => el("option", { value: id, text: rotulo }))),
      el("input", { type: "search", placeholder: "Buscar cliente, e-mail, pedido…", value: est.busca, "aria-label": "Buscar vendas", style: "width:260px",
        oninput: (e) => { clearTimeout(espera); espera = setTimeout(() => { est.busca = e.target.value.trim(); est.pagina = 1; carregar(); }, 350); } })),
    corpo);

  async function carregar() {
    corpo.classList.add("recarregando");
    try {
      const dados = await api("/api/vendas", { params: { ...parametrosFiltro(), status: est.status, busca: est.busca, pagina: est.pagina } });
      desenharVendas(corpo, dados, carregar);
    } catch (erro) {
      corpo.replaceChildren(faixa("Não foi possível carregar as vendas", erro.message, null, "erro"));
    } finally {
      corpo.classList.remove("recarregando");
    }
  }
  await carregar();
}

function seloStatus(status) {
  const [rotulo, classe] = STATUS_VENDA[status] || [status, ""];
  return el("span", { class: `selo ${classe}`, text: rotulo });
}

function desenharVendas(corpo, dados, recarregar) {
  const est = estado.vendas;
  if (!dados.itens.length) {
    corpo.replaceChildren(el("div", { class: "cartao" }, el("div", { class: "vazio" },
      el("h3", { text: "Nenhuma venda encontrada" }),
      el("p", { text: estado.opcoes.tem_vendas ? "Tente outro período ou filtro." : "Assim que o checkout enviar o primeiro webhook, as vendas aparecem aqui." }))));
    return;
  }
  const origem = (v) => v.anuncio || v.campanha || v.utm_source || (v.rastreada_pelo_pixel ? "Visita sem UTM" : "Sem origem");
  const paginas = Math.ceil(dados.total / dados.por_pagina);
  corpo.replaceChildren(el("div", { class: "cartao" },
    el("div", { class: "tabela-rolagem", style: "border-top:0" }, el("table", {},
      el("thead", {}, el("tr", {}, ["Data", "Status", "Produto", "Cliente", "Valor", "Líquido", "Pagamento", "Origem", "Plataforma"]
        .map((t) => el("th", { class: ["Valor", "Líquido"].includes(t) ? "n" : "", text: t })))),
      el("tbody", {}, dados.itens.map((v) => el("tr", { style: "cursor:pointer", tabindex: "0", onclick: () => detalheVenda(v),
        onkeydown: (e) => { if (e.key === "Enter") detalheVenda(v); } },
        el("td", { class: "num", text: dataHora(v.criada_em) }),
        el("td", {}, seloStatus(v.status)),
        el("td", { text: v.produto || "—", style: "max-width:220px;overflow:hidden;text-overflow:ellipsis" }),
        el("td", { style: "max-width:220px;overflow:hidden;text-overflow:ellipsis" }, el("div", { text: v.cliente_nome || "—" }), el("div", { class: "mudo", text: v.cliente_email || "" })),
        el("td", { class: "n", text: R$(v.valor_bruto) }),
        el("td", { class: "n", text: R$(v.valor_liquido) }),
        el("td", { text: NOME_METODO[v.metodo_pagamento] || v.metodo_pagamento }),
        el("td", { text: origem(v), style: "max-width:240px;overflow:hidden;text-overflow:ellipsis", title: origem(v) }),
        el("td", { text: NOME_PLATAFORMA[v.plataforma] || v.plataforma })))))),
    el("div", { class: "paginacao" },
      el("span", { class: "mudo", text: `${num(dados.total)} vendas · página ${dados.pagina} de ${paginas}` }),
      el("div", { class: "acoes", style: "display:flex;gap:6px" },
        el("button", { class: "botao pequeno", text: "Anterior", disabled: est.pagina <= 1, onclick: () => { est.pagina -= 1; recarregar(); } }),
        el("button", { class: "botao pequeno", text: "Próxima", disabled: est.pagina >= paginas, onclick: () => { est.pagina += 1; recarregar(); } })))));
}

function detalheVenda(v) {
  const fechar = () => { fundo.remove(); gaveta.remove(); document.removeEventListener("keydown", aoTeclar); };
  const aoTeclar = (e) => { if (e.key === "Escape") fechar(); };
  const linhas = [
    ["Pedido", v.id_externo], ["Plataforma", NOME_PLATAFORMA[v.plataforma] || v.plataforma], ["Criada em", dataHora(v.criada_em)],
    ["Aprovada em", dataHora(v.aprovada_em)], ["Valor pago", R$(v.valor_bruto)], ["Valor líquido", R$(v.valor_liquido)],
    ["Pagamento", NOME_METODO[v.metodo_pagamento]], ["Produto", v.produto], ["Cliente", v.cliente_nome], ["E-mail", v.cliente_email],
    ["Campanha", v.campanha], ["Conjunto", v.conjunto], ["Anúncio", v.anuncio],
    ["utm_source", v.utm_source], ["utm_medium", v.utm_medium], ["utm_campaign", v.utm_campaign], ["utm_content", v.utm_content],
    ["utm_term", v.utm_term], ["src", v.src], ["sck", v.sck],
    ["Visita do pixel", v.rastreada_pelo_pixel ? "Sim" : "Não"],
    ["API de Conversões", v.capi_situacao ? `${v.capi_situacao}${v.capi_erro ? ` — ${v.capi_erro}` : ""}` : "Não enviada"],
  ];
  const fundo = el("div", { class: "gaveta-fundo", onclick: fechar });
  const gaveta = el("aside", { class: "gaveta", role: "dialog", "aria-modal": "true", "aria-label": "Detalhes da venda" },
    el("div", { class: "cabecalho" }, el("h2", { text: "Detalhes da venda" }), el("button", { class: "botao pequeno", text: "Fechar", onclick: fechar })),
    seloStatus(v.status),
    el("div", { class: "lista-numeros", style: "margin-top:12px" }, linhas.map(([rotulo, valor]) =>
      el("div", { class: "item" }, el("span", { text: rotulo }), el("span", { text: valor || "—", style: "text-align:right;word-break:break-all" })))));
  document.body.append(fundo, gaveta);
  document.addEventListener("keydown", aoTeclar);
  gaveta.querySelector("button").focus();
}

// ------------------------------------------------------------------ integrações

const INSTRUCOES_PLATAFORMA = {
  hotmart: [
    "Na Hotmart, abra Ferramentas › Webhook (API e notificações) e clique em Cadastrar webhook.",
    "Cole a URL abaixo, escolha a versão 2.0.0 e marque os eventos de compra (aprovada, completa, boleto/Pix gerado, cancelada, reembolsada, chargeback, expirada).",
    "Opcional: copie o Hottok da Hotmart e cole no campo Segredo daqui, para recusar chamadas falsas.",
  ],
  kiwify: [
    "Na Kiwify, abra Apps › Webhooks › Criar webhook.",
    "Cole a URL abaixo, escolha os produtos e marque todos os eventos de compra (aprovada, boleto e Pix gerados, recusada, reembolso e chargeback).",
    "Opcional: copie o token do webhook da Kiwify e cole no campo Segredo daqui, para validar a assinatura.",
  ],
  generico: [
    "Use para qualquer checkout sem integração pronta, via Zapier, Make, n8n ou código próprio.",
    "Envie um POST em JSON com: id, status (aprovada, pendente, recusada, cancelada, reembolsada ou chargeback), valor, valor_liquido, metodo_pagamento, data, produto {id, nome}, cliente {nome, email, telefone} e rastreio {utm_source, utm_campaign, …, sck}.",
    "Com Segredo preenchido, mande o mesmo valor no cabeçalho X-Rastro-Token.",
  ],
};

function blocoCodigo(texto) {
  return el("div", { class: "codigo" }, el("code", { text: texto }), el("button", { class: "botao pequeno", text: "Copiar", onclick: () => copiar(texto) }));
}

async function telaIntegracoes(conteudo) {
  conteudo.replaceChildren(el("div", { class: "cabecalho" }, el("h1", { text: "Integrações" })), el("div", { class: "mudo", text: "Carregando…" }));
  let config, integracoes, meta;
  try {
    [config, integracoes, meta] = await Promise.all([api("/api/configuracoes"), api("/api/integracoes"), api("/api/meta")]);
  } catch (erro) {
    conteudo.append(faixa("Não foi possível carregar", erro.message, null, "erro"));
    return;
  }
  const admin = estado.sessao.usuario.admin;
  const recarregar = () => telaIntegracoes(conteudo);
  const local = /^https?:\/\/(localhost|127\.|0\.0\.0\.0|192\.168\.|10\.)/.test(config.url_publica);

  const passo = (numero, titulo, ...filhos) => el("section", { class: "cartao" }, el("div", { class: "corpo passo" },
    el("div", { class: "numero", text: String(numero) }), el("div", { class: "pilha" }, el("h2", { text: titulo }), ...filhos)));

  // 1. Pixel
  const pixel = passo(1, "Instale o pixel em todas as páginas do funil",
    el("p", { class: "secundario", text: "Cole antes de </head> na pré-venda, página de vendas e obrigado (WordPress, Atomicat, Elementor, GreatPages, HTML…). Ele guarda as UTMs e leva a origem da visita até o checkout pelo parâmetro sck." }),
    blocoCodigo(config.script_pixel),
    el("details", {}, el("summary", { text: "Redirecionamento por JavaScript ou botões que não são links" }),
      el("p", { class: "secundario", style: "margin-top:8px", text: "Se a página manda para o checkout por código (quiz, botão com script), use:" }),
      blocoCodigo('location.href = Rastro.url("https://pay.kiwify.com.br/SEU-PRODUTO");'),
      el("p", { class: "secundario", text: 'Para não alterar um link: data-rastro="ignorar". Para contar um botão como clique no checkout: data-rastro="checkout".' })));

  // 2. UTMs
  const utms = passo(2, "Use este padrão de UTMs nos anúncios do Meta",
    el("p", { class: "secundario", text: "No Gerenciador de Anúncios, em cada anúncio: Rastreamento › Parâmetros de URL. Assim cada venda é ligada ao ID exato da campanha, do conjunto e do anúncio — mesmo se você renomear." }),
    blocoCodigo(config.padrao_utms),
    el("p", { class: "mudo", style: "font-size:12.5px", text: "Dica: selecione vários anúncios e edite em massa para colar de uma vez." }));

  // 3. Webhooks
  const listaIntegracoes = integracoes.integracoes.length ? el("div", { class: "pilha" }, integracoes.integracoes.map((i) => {
    const segredo = el("input", { type: "password", placeholder: i.tem_segredo ? "•••••• (salvo)" : "Hottok / token (opcional)", autocomplete: "off", "aria-label": "Segredo do webhook" });
    const papel = el("select", { "aria-label": "Seu papel na venda", value: i.papel },
      [["produtor", "Sou o produtor"], ["coprodutor", "Sou coprodutor"], ["afiliado", "Sou afiliado"]].map(([v, t]) => el("option", { value: v, text: t })));
    const salvar = el("button", { class: "botao pequeno", text: "Salvar" });
    salvar.addEventListener("click", () => comBotao(salvar, async () => {
      const corpo = { papel: papel.value };
      if (segredo.value) corpo.segredo = segredo.value;
      await api(`/api/integracoes/${i.id}`, { metodo: "PATCH", corpo });
      aviso("Integração salva.");
      recarregar();
    }));
    return el("div", { class: "cartao", style: "padding:14px 16px;box-shadow:none" },
      el("div", { class: "cabecalho", style: "margin-bottom:6px" },
        el("div", {}, el("h3", { text: i.nome }), el("div", { class: "mudo", style: "font-size:12.5px",
          text: `${i.plataforma_nome} · ${num(i.recebidos)} recebidos${i.erros ? ` · ${num(i.erros)} com erro` : ""} · último ${haQuanto(i.ultimo_recebimento)}` })),
        admin ? el("div", { class: "acoes" },
          el("label", { class: "interruptor", title: i.ativo ? "Desativar" : "Ativar" }, el("input", { type: "checkbox", checked: i.ativo, "aria-label": "Integração ativa",
            onchange: async (e) => { try { await api(`/api/integracoes/${i.id}`, { metodo: "PATCH", corpo: { ativo: e.target.checked } }); } catch (erro) { aviso(erro.message, "erro"); e.target.checked = !e.target.checked; } } }), el("span")),
          el("button", { class: "botao pequeno perigo fantasma", text: "Remover", onclick: async () => {
            if (!confirm(`Remover a integração "${i.nome}"? As vendas já recebidas continuam no painel, mas a URL para de funcionar.`)) return;
            try { await api(`/api/integracoes/${i.id}`, { metodo: "DELETE" }); recarregar(); } catch (erro) { aviso(erro.message, "erro"); }
          } })) : null),
      blocoCodigo(i.url),
      el("details", {}, el("summary", { text: `Como configurar na ${i.plataforma_nome}` }),
        el("ol", { class: "instrucoes" }, (INSTRUCOES_PLATAFORMA[i.plataforma] || []).map((t) => el("li", { text: t })))),
      admin ? el("div", { class: "linha-form", style: "margin-top:10px" },
        el("label", { class: "campo" }, el("span", { text: "Segredo" }), segredo),
        i.plataforma === "hotmart" ? el("label", { class: "campo" }, el("span", { text: "Comissão que conta como faturamento" }), papel) : null,
        salvar) : null);
  })) : el("p", { class: "mudo", text: "Nenhum checkout conectado ainda." });

  const novaPlataforma = el("select", { "aria-label": "Plataforma" }, integracoes.plataformas.map((p) => el("option", { value: p.id, text: p.nome })));
  const novoNome = el("input", { type: "text", placeholder: "Ex.: Hotmart — Curso X", "aria-label": "Nome da integração" });
  const botaoNova = el("button", { class: "botao primario", text: "Gerar URL do webhook" });
  botaoNova.addEventListener("click", () => comBotao(botaoNova, async () => {
    await api("/api/integracoes", { metodo: "POST", corpo: { plataforma: novaPlataforma.value, nome: novoNome.value || null } });
    aviso("Integração criada. Copie a URL e cole na plataforma.");
    recarregar();
  }));
  const webhooks = passo(3, "Conecte o checkout (webhook de vendas)",
    local ? faixa("Este endereço não é público",
      `As plataformas não alcançam ${config.url_publica}. Publique o Rastro num servidor com HTTPS e defina RASTRO_URL_PUBLICA (veja o README). Para testar no computador, use um túnel como o Cloudflare Tunnel ou ngrok.`) : null,
    listaIntegracoes,
    admin ? el("div", { class: "linha-form" }, el("label", { class: "campo" }, el("span", { text: "Plataforma" }), novaPlataforma),
      el("label", { class: "campo" }, el("span", { text: "Nome (opcional)" }), novoNome), botaoNova) : null);

  // 4. Meta Ads
  const metaBloco = passo(4, "Conecte o Meta Ads (gastos e controle dos anúncios)", ...blocoMeta(meta, admin, recarregar));

  conteudo.replaceChildren(
    el("div", { class: "cabecalho" }, el("div", {}, el("h1", { text: "Integrações" }),
      el("div", { class: "mudo", text: "Quatro passos para rastrear cada venda até o anúncio." }))),
    el("div", { class: "pilha" }, pixel, utms, webhooks, metaBloco, blocoLogWebhooks(admin)));
}

function blocoMeta(meta, admin, recarregar) {
  if (!meta.conectado) {
    const token = el("input", { type: "password", placeholder: "EAAG…", autocomplete: "off", "aria-label": "Token de acesso do Meta" });
    const botao = el("button", { class: "botao primario", text: "Conectar" });
    botao.addEventListener("click", () => comBotao(botao, async () => {
      await api("/api/meta/token", { metodo: "POST", corpo: { token: token.value.trim() } });
      aviso("Meta Ads conectado. Agora escolha as contas de anúncio.");
      recarregar();
    }));
    return [
      el("p", { class: "secundario", text: "Use um token de Usuário do Sistema (não expira). Passo a passo:" }),
      el("ol", { class: "instrucoes" },
        el("li", { text: "Em business.facebook.com › Configurações do negócio › Usuários › Usuários do sistema, crie um usuário Administrador." }),
        el("li", { text: "Em Contas › Contas de anúncios, adicione esse usuário às contas com controle total." }),
        el("li", { text: "Volte ao usuário do sistema › Gerar novo token, escolha um app seu (crie um app do tipo Empresa em developers.facebook.com se não tiver) e marque ads_read e ads_management." }),
        el("li", { text: "Cole o token aqui." })),
      admin ? el("div", { class: "linha-form" }, el("label", { class: "campo" }, el("span", { text: "Token de acesso" }), token), botao)
        : el("p", { class: "mudo", text: "Peça a um administrador para conectar." }),
    ];
  }
  const contas = meta.contas_anuncio.map((c) => {
    const cotacao = el("input", { type: "number", step: "0.0001", min: "0.0001", value: String(c.cotacao), style: "width:100px", "aria-label": `Cotação de ${c.nome}`,
      disabled: !admin,
      onchange: async (e) => {
        try { await api(`/api/meta/contas/${c.id}`, { metodo: "PATCH", corpo: { cotacao: Number(e.target.value) } }); aviso("Cotação salva."); }
        catch (erro) { aviso(erro.message, "erro"); }
      } });
    return el("tr", {},
      el("td", {}, el("label", { class: "interruptor", title: "Sincronizar esta conta" }, el("input", {
        type: "checkbox", checked: c.ativo, disabled: !admin, "aria-label": `Sincronizar ${c.nome}`,
        onchange: async (e) => {
          try {
            await api(`/api/meta/contas/${c.id}`, { metodo: "PATCH", corpo: { ativo: e.target.checked } });
            aviso(e.target.checked ? "Conta ativada. Trazendo os últimos 30 dias…" : "Conta desativada.");
            setTimeout(recarregar, 1500);
          } catch (erro) { aviso(erro.message, "erro"); e.target.checked = !e.target.checked; }
        } }), el("span"))),
      el("td", {}, el("div", { text: c.nome }), el("div", { class: "mudo mono", text: c.meta_id })),
      el("td", { text: c.moeda }),
      el("td", {}, c.moeda !== "BRL" ? cotacao : el("span", { class: "mudo", text: "—" })),
      el("td", {}, c.erro ? el("span", { class: "selo critico", title: c.erro, text: "Erro" }) : (c.ativo ? el("span", { class: "mudo", text: haQuanto(c.ultima_sincronizacao) }) : el("span", { class: "mudo", text: "—" }))));
  });
  const inicio = el("input", { type: "date", "aria-label": "Sincronizar desde" });
  const fim = el("input", { type: "date", "aria-label": "Sincronizar até" });
  const botaoSinc = el("button", { class: "botao", text: "Sincronizar período" });
  botaoSinc.addEventListener("click", () => comBotao(botaoSinc, async () => {
    await api("/api/meta/sincronizar", { metodo: "POST", corpo: { inicio: inicio.value || null, fim: fim.value || null } });
    aviso("Sincronização iniciada em segundo plano.");
  }));
  const botaoLista = el("button", { class: "botao pequeno", text: "Atualizar lista de contas" });
  botaoLista.addEventListener("click", () => comBotao(botaoLista, async () => { await api("/api/meta/contas/atualizar", { metodo: "POST" }); recarregar(); }));
  const erros = meta.contas_anuncio.filter((c) => c.erro).map((c) => faixa(`Erro em ${c.nome}`, c.erro, null, "erro"));
  return [
    el("div", { class: "cabecalho", style: "margin:0" },
      el("span", { class: "secundario" }, el("span", { class: "selo bom", text: "Conectado" }), ` como ${meta.usuario || "—"} · token ${meta.token}`),
      admin ? el("div", { class: "acoes" }, botaoLista, el("button", { class: "botao pequeno perigo fantasma", text: "Desconectar", onclick: async () => {
        if (!confirm("Desconectar o Meta Ads? Os gastos já sincronizados continuam no painel.")) return;
        try { await api("/api/meta/token", { metodo: "DELETE" }); recarregar(); } catch (erro) { aviso(erro.message, "erro"); }
      } })) : null),
    ...erros,
    el("p", { class: "secundario", text: "Ative as contas de anúncio que o Rastro deve acompanhar. Os gastos de hoje e de ontem atualizam sozinhos a cada 15 minutos. Conta em outra moeda? Informe a cotação para converter em reais." }),
    meta.contas_anuncio.length ? el("div", { class: "tabela-rolagem" }, el("table", {},
      el("thead", {}, el("tr", {}, ["Sincronizar", "Conta", "Moeda", "Cotação", "Última sincronização"].map((t) => el("th", { text: t })))),
      el("tbody", {}, contas))) : el("p", { class: "mudo", text: "O token não tem acesso a nenhuma conta de anúncio." }),
    el("div", { class: "linha-form" },
      el("label", { class: "campo", style: "flex:0 1 170px" }, el("span", { text: "Trazer histórico desde" }), inicio),
      el("label", { class: "campo", style: "flex:0 1 170px" }, el("span", { text: "até" }), fim), botaoSinc),
  ];
}

function blocoLogWebhooks(admin) {
  const corpo = el("div", { class: "corpo" }, el("span", { class: "mudo", text: "Carregando…" }));
  const filtro = el("select", { "aria-label": "Situação", onchange: () => carregar(1) },
    el("option", { value: "", text: "Todos" }), el("option", { value: "processado", text: "Processados" }),
    el("option", { value: "ignorado", text: "Ignorados" }), el("option", { value: "erro", text: "Com erro" }));
  const reprocessarTodos = el("button", { class: "botao pequeno", text: "Reprocessar os com erro" });
  reprocessarTodos.addEventListener("click", () => comBotao(reprocessarTodos, async () => {
    const r = await api("/api/webhooks/reprocessar-erros", { metodo: "POST" });
    aviso(`${r.reprocessados} reprocessados, ${r.ainda_com_erro} ainda com erro.`);
    carregar(1);
  }));
  const SITUACAO = { processado: "bom", ignorado: "", erro: "critico" };

  async function carregar(pagina) {
    try {
      const dados = await api("/api/webhooks", { params: { situacao: filtro.value, pagina } });
      if (!dados.itens.length) { corpo.replaceChildren(el("span", { class: "mudo", text: "Nenhum webhook recebido." })); return; }
      corpo.replaceChildren(el("div", { class: "tabela-rolagem" }, el("table", {},
        el("thead", {}, el("tr", {}, ["Recebido", "Integração", "Situação", "Resultado", ""].map((t) => el("th", { text: t })))),
        el("tbody", {}, dados.itens.map((w) => el("tr", {},
          el("td", { class: "num", text: dataHora(w.recebido_em) }),
          el("td", { text: w.integracao || "—" }),
          el("td", {}, el("span", { class: `selo ${SITUACAO[w.situacao] || ""}`, text: w.situacao })),
          el("td", { style: "white-space:normal;min-width:260px" }, el("div", { text: w.mensagem || "" }),
            el("details", {}, el("summary", { text: "Ver conteúdo recebido" }), el("pre", { text: formatarJson(w.corpo) }))),
          el("td", {}, admin ? el("button", { class: "botao pequeno", text: "Reprocessar", onclick: async (e) => {
            await comBotao(e.target, async () => {
              const r = await api(`/api/webhooks/${w.id}/reprocessar`, { metodo: "POST" });
              aviso(`${r.situacao}: ${r.mensagem || ""}`);
              carregar(pagina);
            });
          } }) : null)))))),
      dados.total > 50 ? el("div", { class: "paginacao", style: "padding:12px 0 0" }, el("span", { class: "mudo", text: `${num(dados.total)} registros` }),
        el("div", { style: "display:flex;gap:6px" },
          el("button", { class: "botao pequeno", text: "Anterior", disabled: pagina <= 1, onclick: () => carregar(pagina - 1) }),
          el("button", { class: "botao pequeno", text: "Próxima", disabled: pagina * 50 >= dados.total, onclick: () => carregar(pagina + 1) }))) : null);
    } catch (erro) {
      corpo.replaceChildren(faixa("Não foi possível carregar o log", erro.message, null, "erro"));
    }
  }
  carregar(1);
  return el("section", { class: "cartao" },
    el("div", { class: "topo" }, el("div", {}, el("h2", { text: "Webhooks recebidos" }),
      el("div", { class: "mudo", style: "font-size:12.5px", text: "Tudo o que os checkouts enviaram, para conferir e reprocessar." })),
      el("div", { class: "acoes", style: "display:flex;gap:8px" }, filtro, admin ? reprocessarTodos : null)),
    corpo);
}

function formatarJson(texto) {
  try { return JSON.stringify(JSON.parse(texto), null, 2); } catch { return texto; }
}

// ------------------------------------------------------------------ configurações

const FUSOS = ["America/Sao_Paulo", "America/Bahia", "America/Fortaleza", "America/Recife", "America/Belem", "America/Manaus",
  "America/Cuiaba", "America/Campo_Grande", "America/Porto_Velho", "America/Boa_Vista", "America/Rio_Branco", "America/Noronha",
  "Europe/Lisbon", "America/New_York", "UTC"];

async function telaConfiguracoes(conteudo) {
  conteudo.replaceChildren(el("div", { class: "cabecalho" }, el("h1", { text: "Configurações" })), el("div", { class: "mudo", text: "Carregando…" }));
  let config, produtos, usuarios;
  try {
    [config, produtos, usuarios] = await Promise.all([api("/api/configuracoes"), api("/api/produtos"), api("/api/usuarios")]);
  } catch (erro) {
    conteudo.append(faixa("Não foi possível carregar", erro.message, null, "erro"));
    return;
  }
  const admin = estado.sessao.usuario.admin;
  const recarregar = () => telaConfiguracoes(conteudo);
  const cartao = (titulo, descricao, ...filhos) => el("section", { class: "cartao" },
    el("div", { class: "topo" }, el("div", {}, el("h2", { text: titulo }), descricao ? el("div", { class: "mudo", style: "font-size:12.5px", text: descricao }) : null)),
    el("div", { class: "corpo pilha" }, ...filhos));
  const salvarAjustes = async (botao, corpo, mensagem = "Configurações salvas.") => comBotao(botao, async () => {
    await api("/api/configuracoes", { metodo: "PUT", corpo });
    aviso(mensagem);
    await iniciar(false);
  });

  // Conta e custos
  const nome = el("input", { type: "text", value: config.nome, disabled: !admin, "aria-label": "Nome da operação" });
  const fuso = el("select", { value: config.fuso, disabled: !admin, "aria-label": "Fuso horário" },
    [...new Set([config.fuso, ...FUSOS])].map((f) => el("option", { value: f, text: f.replace(/_/g, " ") })));
  const imposto = el("input", { type: "number", min: "0", max: "100", step: "0.01", value: String(config.imposto_pct), disabled: !admin });
  const impostoAnuncios = el("input", { type: "number", min: "0", max: "100", step: "0.01", value: String(config.imposto_anuncios_pct), disabled: !admin });
  const botaoConta = el("button", { class: "botao primario", text: "Salvar" });
  botaoConta.addEventListener("click", () => salvarAjustes(botaoConta, {
    nome: nome.value, fuso: fuso.value, imposto_pct: Number(imposto.value || 0), imposto_anuncios_pct: Number(impostoAnuncios.value || 0),
  }));
  const contaCartao = cartao("Operação, impostos e taxas", "Entram no cálculo do lucro.",
    el("div", { class: "linha-form" },
      el("label", { class: "campo" }, el("span", { text: "Nome da operação" }), nome),
      el("label", { class: "campo" }, el("span", { text: "Fuso horário" }), fuso, el("small", { text: "Define o que é “hoje” nos filtros." }))),
    el("div", { class: "linha-form" },
      el("label", { class: "campo" }, el("span", { text: "Imposto sobre o faturamento (%)" }), imposto,
        el("small", { text: "Ex.: Simples Nacional 6%. Aplicado sobre o faturamento líquido." })),
      el("label", { class: "campo" }, el("span", { text: "Imposto sobre anúncios (%)" }), impostoAnuncios,
        el("small", { text: "Somado ao gasto do Meta. Ex.: 12,15% de ISS/PIS/COFINS cobrados na fatura." }))),
    admin ? el("div", {}, botaoConta) : null);

  // Produtos
  const produtosCartao = cartao("Custo dos produtos", "Custo por venda aprovada (produção, frete, entrega, coprodução fora da plataforma…).",
    produtos.length ? el("div", { class: "tabela-rolagem" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { text: "Produto" }), el("th", { text: "Plataforma" }), el("th", { class: "n", text: "Vendas" }), el("th", { text: "Custo por venda (R$)" }))),
      el("tbody", {}, produtos.map((p) => el("tr", {},
        el("td", { text: p.nome }), el("td", { text: NOME_PLATAFORMA[p.plataforma] || p.plataforma }), el("td", { class: "n", text: num(p.vendas) }),
        el("td", {}, el("input", { type: "number", min: "0", step: "0.01", value: String(p.custo), style: "width:120px", disabled: !admin, "aria-label": `Custo de ${p.nome}`,
          onchange: async (e) => {
            try { await api(`/api/produtos/${p.id}`, { metodo: "PATCH", corpo: { custo: Number(e.target.value || 0) } }); aviso("Custo salvo."); }
            catch (erro) { aviso(erro.message, "erro"); }
          } }))))))) : el("p", { class: "mudo", text: "Os produtos aparecem aqui automaticamente quando chega a primeira venda." }));

  // API de Conversões
  const capiAtivo = el("input", { type: "checkbox", checked: config.capi_ativo, disabled: !admin, "aria-label": "Enviar vendas para a API de Conversões" });
  const pixelId = el("input", { type: "text", value: config.capi_pixel_id || "", placeholder: "Ex.: 123456789012345", disabled: !admin });
  const capiToken = el("input", { type: "password", placeholder: config.capi_token || "Token da API de Conversões", autocomplete: "off", disabled: !admin });
  const codigoTeste = el("input", { type: "text", value: config.capi_codigo_teste || "", placeholder: "TEST12345 (opcional)", disabled: !admin });
  const botaoCapi = el("button", { class: "botao primario", text: "Salvar" });
  botaoCapi.addEventListener("click", () => {
    const corpo = { capi_ativo: capiAtivo.checked, capi_pixel_id: pixelId.value, capi_codigo_teste: codigoTeste.value };
    if (capiToken.value) corpo.capi_token = capiToken.value;
    salvarAjustes(botaoCapi, corpo);
  });
  const botaoReenviar = el("button", { class: "botao", text: "Reenviar vendas com erro" });
  botaoReenviar.addEventListener("click", () => comBotao(botaoReenviar, async () => {
    const r = await api("/api/capi/reenviar", { metodo: "POST" });
    aviso(`${r.reenfileiradas} vendas enviadas de novo.`);
  }));
  const capiCartao = cartao("API de Conversões do Meta", "Envia cada venda aprovada como evento Purchase, com e-mail, telefone, IP, fbp e fbc da visita — melhora a otimização das campanhas.",
    faixa("Evite duplicar compras",
      "Se o checkout já envia o Purchase para este mesmo pixel (pixel do Meta instalado na Hotmart/Kiwify), deixe desligado ou use um pixel separado."),
    el("label", { style: "display:flex;gap:10px;align-items:center" }, el("span", { class: "interruptor" }, capiAtivo, el("span")), "Enviar vendas aprovadas"),
    el("div", { class: "linha-form" },
      el("label", { class: "campo" }, el("span", { text: "ID do pixel (conjunto de dados)" }), pixelId),
      el("label", { class: "campo" }, el("span", { text: "Token de acesso" }), capiToken,
        el("small", { text: "Gerenciador de Eventos › seu pixel › Configurações › Gerar token de acesso." })),
      el("label", { class: "campo" }, el("span", { text: "Código de teste" }), codigoTeste,
        el("small", { text: "Para ver os eventos em Testar eventos. Apague depois de testar." }))),
    admin ? el("div", { style: "display:flex;gap:8px" }, botaoCapi, botaoReenviar) : null);

  // Usuários
  const novoNome = el("input", { type: "text", placeholder: "Nome", "aria-label": "Nome" });
  const novoEmail = el("input", { type: "email", placeholder: "email@exemplo.com", "aria-label": "E-mail" });
  const novaSenha = el("input", { type: "password", placeholder: "Senha inicial (8+)", autocomplete: "new-password", "aria-label": "Senha inicial" });
  const novoAdmin = el("input", { type: "checkbox", "aria-label": "Administrador" });
  const botaoUsuario = el("button", { class: "botao", text: "Adicionar" });
  botaoUsuario.addEventListener("click", () => comBotao(botaoUsuario, async () => {
    await api("/api/usuarios", { metodo: "POST", corpo: { nome: novoNome.value, email: novoEmail.value, senha: novaSenha.value, admin: novoAdmin.checked } });
    aviso("Usuário adicionado. Passe o e-mail e a senha para a pessoa.");
    recarregar();
  }));
  const usuariosCartao = cartao("Equipe", "Quem acessa o painel desta operação. Só administradores alteram integrações e configurações.",
    el("div", { class: "lista-numeros" }, usuarios.map((u) => el("div", { class: "item" },
      el("span", {}, el("b", { text: u.nome }), " ", el("span", { class: "mudo", text: u.email }), u.admin ? el("span", { class: "selo info", style: "margin-left:8px", text: "Admin" }) : null),
      admin && u.id !== estado.sessao.usuario.id ? el("button", { class: "botao pequeno perigo fantasma", text: "Remover", onclick: async () => {
        if (!confirm(`Remover ${u.nome}?`)) return;
        try { await api(`/api/usuarios/${u.id}`, { metodo: "DELETE" }); recarregar(); } catch (erro) { aviso(erro.message, "erro"); }
      } }) : el("span")))),
    admin ? el("div", { class: "linha-form" }, el("label", { class: "campo" }, el("span", { text: "Nome" }), novoNome),
      el("label", { class: "campo" }, el("span", { text: "E-mail" }), novoEmail),
      el("label", { class: "campo" }, el("span", { text: "Senha" }), novaSenha),
      el("label", { style: "display:flex;gap:6px;align-items:center;height:36px" }, novoAdmin, "Admin"), botaoUsuario) : null);

  // Senha
  const senhaAtual = el("input", { type: "password", autocomplete: "current-password", "aria-label": "Senha atual" });
  const senhaNova = el("input", { type: "password", autocomplete: "new-password", "aria-label": "Nova senha" });
  const botaoSenha = el("button", { class: "botao", text: "Trocar senha" });
  botaoSenha.addEventListener("click", () => comBotao(botaoSenha, async () => {
    await api("/api/usuarios/senha", { metodo: "POST", corpo: { atual: senhaAtual.value, nova: senhaNova.value } });
    senhaAtual.value = senhaNova.value = "";
    aviso("Senha alterada. As outras sessões foram encerradas.");
  }));
  const senhaCartao = cartao("Minha senha", null, el("div", { class: "linha-form" },
    el("label", { class: "campo" }, el("span", { text: "Senha atual" }), senhaAtual),
    el("label", { class: "campo" }, el("span", { text: "Nova senha" }), senhaNova), botaoSenha));

  conteudo.replaceChildren(el("div", { class: "cabecalho" }, el("h1", { text: "Configurações" })),
    el("div", { class: "pilha" }, contaCartao, produtosCartao, capiCartao, usuariosCartao, senhaCartao));
}

// ------------------------------------------------------------------ início

async function iniciar(desenhar = true) {
  let sessao;
  try {
    sessao = await api("/api/sessao");
  } catch (erro) {
    document.getElementById("app").replaceChildren(el("div", { class: "tela-login" }, faixa("Não foi possível falar com o servidor", erro.message, null, "erro")));
    return;
  }
  if (!sessao.logado) {
    estado.sessao = null;
    telaLogin(sessao);
    return;
  }
  estado.sessao = sessao;
  try { estado.opcoes = await api("/api/opcoes"); } catch { estado.opcoes = { produtos: [], plataformas: [], contas_anuncio: [], tem_vendas: false }; }
  if (desenhar) renderizar();
}

window.addEventListener("hashchange", () => { if (estado.sessao) renderizar(); });
iniciar();
