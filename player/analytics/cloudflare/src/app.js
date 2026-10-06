/**
 * Analytics do VSL Player em um Cloudflare Worker com banco D1.
 *
 * Mesmas rotas e os mesmos números do servidor Python (player/analytics/servidor.py):
 *   POST /vsl                      recebe o envio do player (JSON, mesmo como text/plain)
 *   GET  /                         o painel
 *   GET  /api/config | /saude      públicos
 *   GET  /api/players | /api/resumo | /api/sessoes.csv   pedem o TOKEN, se houver
 *
 * Diferenças por causa do D1: cada sessão é uma linha e os eventos ficam contados em JSON dentro dela
 * (uma escrita por envio); o pitch e a duração de cada player vêm da sessão mais recente dele.
 */

export const VERSAO = '1.0.0';
export const LIMITE_CORPO = 512 * 1024;
export const MAX_EVENTOS = 500;
export const MAX_FAIXAS = 5000;
export const MAX_TEXTO = 2000;
export const MAX_ID = 120;
export const MAX_SEGUNDOS = 24 * 3600;
export const MAX_TS = 2 ** 53;
export const MAX_DIAS = 400;
export const PONTOS_CURVA = 1200;
export const FUSO_PADRAO = 'America/Sao_Paulo';

const CAMINHOS_COLETA = new Set(['/vsl', '/coletar', '/']);
const PERIODOS = { hoje: 0, 7: 6, 30: 29, 90: 89 };
const ORIGENS_CONHECIDAS = [
  [/(^|\.)facebook\.com$|^fb\.me$|^fb\.com$/, 'facebook'],
  [/(^|\.)instagram\.com$/, 'instagram'],
  [/(^|\.)youtube\.com$|^youtu\.be$/, 'youtube'],
  [/(^|\.)tiktok\.com$/, 'tiktok'],
  [/(^|\.)google\.[a-z.]+$/, 'google'],
  [/^t\.co$|(^|\.)twitter\.com$|(^|\.)x\.com$/, 'x'],
  [/(^|\.)whatsapp\.com$/, 'whatsapp'],
  [/(^|\.)linkedin\.com$/, 'linkedin'],
];
const COLUNAS_CSV = ['sessao', 'player', 'visitante', 'inicio', 'dia', 'ultimo', 'origem', 'utm_source', 'utm_medium',
  'utm_campaign', 'utm_content', 'utm_term', 'dispositivo', 'url', 'referrer', 'duracao', 'max_tempo', 'segundos',
  'com_som', 'terminou'];

// ----------------------------------------------------------------------------- cálculos

/** Converte para número dentro de [minimo, maximo]; lixo, NaN, infinito, booleanos e listas viram o mínimo. */
export function numero(valor, minimo = 0, maximo = null) {
  if (typeof valor === 'number') { /* segue */ } else if (typeof valor === 'string' && valor.trim() !== '') valor = Number(valor);
  else return minimo;
  if (!Number.isFinite(valor)) return minimo;
  let n = Math.max(minimo, valor);
  if (maximo != null) n = Math.min(maximo, n);
  return n;
}

/** Tempo do pitch em segundos: número (ou texto numérico) finito e >= 0. Qualquer outra coisa é "sem pitch". */
export function pitchValido(valor) {
  if (typeof valor !== 'number' && typeof valor !== 'string') return null;
  if (typeof valor === 'string' && valor.trim() === '') return null;
  const n = Number(valor);
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.min(n, MAX_SEGUNDOS);
}

/** Une faixas [[a, b], ...] de segundos (inclusivas) em faixas ordenadas, sem sobreposição, até MAX_SEGUNDOS. */
export function unirFaixas(faixas) {
  const limpas = [];
  for (const faixa of Array.isArray(faixas) ? faixas : []) {
    if (!Array.isArray(faixa) || faixa.length < 2) continue;
    const a = numero(faixa[0], -1, MAX_SEGUNDOS);
    const b = numero(faixa[1], -1, MAX_SEGUNDOS);
    if (a < 0 || b < a) continue;
    limpas.push([Math.trunc(a), Math.trunc(b)]);
  }
  limpas.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  const saida = [];
  for (const [a, b] of limpas) {
    const ultima = saida[saida.length - 1];
    if (ultima && a <= ultima[1] + 1) ultima[1] = Math.max(ultima[1], b);
    else saida.push([a, b]);
  }
  return saida;
}

export const segundosAssistidos = (faixas) => faixas.reduce((total, [a, b]) => total + (b - a + 1), 0);

/** Até onde a sessão chegou, pelas faixas assistidas (fim da última + 1), ou 0 sem faixas. */
export const fimDasFaixas = (faixas) => (faixas.length ? faixas[faixas.length - 1][1] + 1 : 0);

/** Quantas sessões assistiram cada segundo, de 0 até a duração (inclusive). */
export function curvaRetencao(listasDeFaixas, duracao) {
  const n = Math.min(Math.trunc(numero(duracao)), MAX_SEGUNDOS) + 1;
  if (n <= 0) return [];
  const diferenca = new Int32Array(n + 1);
  for (const faixas of listasDeFaixas) {
    for (const [a, b] of faixas) {
      if (a >= n) continue;
      diferenca[a] += 1;
      diferenca[Math.min(b, n - 1) + 1] -= 1;
    }
  }
  const curva = new Array(n);
  let acumulado = 0;
  for (let i = 0; i < n; i++) { acumulado += diferenca[i]; curva[i] = acumulado; }
  return curva;
}

/** Reduz a curva a no máximo `maximo` pontos, tirando a média de cada bloco de `passo` segundos. */
export function compactarCurva(curva, maximo = PONTOS_CURVA) {
  if (curva.length <= maximo) return { passo: 1, pontos: curva.map(Number) };
  const passo = Math.ceil(curva.length / maximo);
  const pontos = [];
  for (let i = 0; i < curva.length; i += passo) {
    const bloco = curva.slice(i, i + passo);
    pontos.push(Math.round((bloco.reduce((s, v) => s + v, 0) / bloco.length) * 100) / 100);
  }
  return { passo, pontos };
}

export const dispositivo = (userAgent) => (/Mobi|Android|iPhone|iPad|iPod/i.test(userAgent || '') ? 'celular' : 'computador');

export function utms(url) {
  let params;
  try { params = new URL(url).searchParams; } catch (e) { params = new URLSearchParams(); }
  const saida = {};
  for (const chave of ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term']) {
    saida[chave] = (params.get(chave) || '').slice(0, 200).trim();
  }
  return saida;
}

export function origem(utmSource, referrer) {
  if (utmSource) return utmSource.toLowerCase();
  let host = '';
  try { host = new URL(referrer).hostname.toLowerCase(); } catch (e) { host = ''; }
  if (!host) return 'direto';
  if (host.startsWith('www.')) host = host.slice(4);
  for (const [padrao, nome] of ORIGENS_CONHECIDAS) if (padrao.test(host)) return nome;
  return host;
}

export function texto(valor, maximo = MAX_TEXTO) {
  if (typeof valor !== 'string') return '';
  return valor.slice(0, maximo).replace(/[\x00-\x08\x0a-\x1f]/g, '').trim();
}

/** "AAAA-MM-DD" válido (datas reais), ou null. */
export function diaValido(valor) {
  if (!valor) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(valor));
  if (!m) return null;
  const [ano, mes, dia] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const d = new Date(Date.UTC(ano, mes - 1, dia));
  if (d.getUTCFullYear() !== ano || d.getUTCMonth() !== mes - 1 || d.getUTCDate() !== dia) return null;
  return d.toISOString().slice(0, 10);
}

/** Data de hoje ("AAAA-MM-DD") num fuso IANA; fuso inválido cai em UTC. */
export function hojeNoFuso(fuso, agora = new Date()) {
  try {
    return new Intl.DateTimeFormat('en-CA', { timeZone: fuso || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).format(agora);
  } catch (e) {
    return agora.toISOString().slice(0, 10);
  }
}

function somarDias(dia, n) {
  const d = new Date(dia + 'T00:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** 'hoje', '7', '30', '90' viram datas pelo relógio do servidor (no fuso); 'tudo' ou vazio é sem filtro. */
export function periodoParaDatas(periodo, hoje) {
  if (!periodo || periodo === 'tudo') return [null, null];
  if (!(periodo in PERIODOS)) throw new Error('periodo precisa ser hoje, 7, 30, 90 ou tudo');
  return [somarDias(hoje, -PERIODOS[periodo]), hoje];
}

/** Confere e limpa um envio do player. Lança Error se não servir. */
export function validarEnvio(dados) {
  if (!dados || typeof dados !== 'object' || Array.isArray(dados)) throw new Error('o envio precisa ser um objeto JSON');
  const player = texto(dados.player, MAX_ID);
  const sessao = texto(dados.session, MAX_ID);
  if (!player || !sessao) throw new Error('faltam player e session');
  const eventos = dados.events || [];
  const faixas = dados.watched || [];
  if (!Array.isArray(eventos) || !Array.isArray(faixas)) throw new Error('events e watched precisam ser listas');
  if (eventos.length > MAX_EVENTOS || faixas.length > MAX_FAIXAS) throw new Error('envio grande demais');
  const contagem = {};
  for (const ev of eventos) {
    if (!ev || typeof ev !== 'object') continue;
    const tipo = texto(ev.type, 60);
    if (!tipo) continue;
    contagem[tipo] = (contagem[tipo] || 0) + 1;
  }
  return {
    player,
    sessao,
    visitante: texto(dados.visitor, MAX_ID),
    url: texto(dados.url),
    referrer: texto(dados.referrer),
    duracao: Math.round(numero(dados.duration, 0, MAX_SEGUNDOS) * 100) / 100,
    maxTempo: Math.round(numero(dados.maxTime, 0, MAX_SEGUNDOS) * 100) / 100,
    comSom: dados.unmuted ? 1 : 0,
    faixas: unirFaixas(faixas),
    eventos: contagem,
    terminou: contagem.ended ? 1 : 0,
    pitch: pitchValido(dados.pitch),
  };
}

/** Neutraliza fórmulas no CSV: Excel e Sheets executam células que começam com = + - @ (OWASP). */
export function celula(valor) {
  if (typeof valor === 'string' && /^[=+\-@\t\r]/.test(valor)) return "'" + valor;
  return valor;
}

/** Segundos assistidos, nunca além da duração do vídeo (a contagem inclusiva daria duração + 1). */
const limitarSegundos = (faixas, duracao) => {
  const total = segundosAssistidos(faixas);
  return duracao > 0 ? Math.min(total, duracao) : total;
};

// ----------------------------------------------------------------------------- banco (D1)

const momentoIso = (data) => data.toISOString().slice(0, 19) + 'Z';

/** Guarda um envio do player: cria ou atualiza a linha da sessão, somando os eventos. */
export async function registrar(db, dados, userAgent = '', fuso = FUSO_PADRAO, agora = new Date()) {
  const envio = validarEnvio(dados);
  const momento = momentoIso(agora);
  const atual = await db.prepare('SELECT assistido, max_tempo, com_som, duracao, terminou, eventos, pitch FROM sessoes WHERE sessao = ?')
    .bind(envio.sessao).first();
  if (atual) {
    const faixas = unirFaixas(JSON.parse(atual.assistido).concat(envio.faixas));
    const duracao = Math.max(atual.duracao, envio.duracao);
    // O "até onde chegou" nunca passa do que as faixas mostram: protege contra um maxTime inflado.
    const maxTempo = Math.min(Math.max(atual.max_tempo, envio.maxTempo), fimDasFaixas(faixas));
    const eventos = JSON.parse(atual.eventos || '{}');
    for (const [tipo, n] of Object.entries(envio.eventos)) eventos[tipo] = (eventos[tipo] || 0) + n;
    await db.prepare('UPDATE sessoes SET ultimo = ?, duracao = ?, max_tempo = ?, com_som = ?, terminou = ?, assistido = ?, '
      + 'segundos = ?, eventos = ?, pitch = COALESCE(?, pitch) WHERE sessao = ?')
      .bind(momento, duracao, maxTempo, Math.max(atual.com_som, envio.comSom), Math.max(atual.terminou, envio.terminou),
        JSON.stringify(faixas), limitarSegundos(faixas, duracao), JSON.stringify(eventos), envio.pitch, envio.sessao)
      .run();
    return;
  }
  const faixas = envio.faixas;
  const marcas = utms(envio.url);
  await db.prepare('INSERT INTO sessoes (sessao, player, visitante, url, referrer, origem, utm_source, utm_medium, utm_campaign, '
    + 'utm_content, utm_term, dispositivo, user_agent, inicio, dia, ultimo, duracao, max_tempo, com_som, terminou, assistido, '
    + 'segundos, pitch, eventos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
    .bind(envio.sessao, envio.player, envio.visitante, envio.url, envio.referrer, origem(marcas.utm_source, envio.referrer),
      marcas.utm_source, marcas.utm_medium, marcas.utm_campaign, marcas.utm_content, marcas.utm_term, dispositivo(userAgent),
      texto(userAgent, 500), momento, hojeNoFuso(fuso, agora), momento, envio.duracao,
      Math.min(envio.maxTempo, fimDasFaixas(faixas)), envio.comSom, envio.terminou, JSON.stringify(faixas),
      limitarSegundos(faixas, envio.duracao), envio.pitch, JSON.stringify(envio.eventos))
    .run();
}

function filtro(player, de, ate) {
  const condicoes = [];
  const params = [];
  if (player) { condicoes.push('player = ?'); params.push(player); }
  if (de) { condicoes.push('dia >= ?'); params.push(de); }
  if (ate) { condicoes.push('dia <= ?'); params.push(ate); }
  return { where: condicoes.length ? ' WHERE ' + condicoes.join(' AND ') : '', params };
}

/** Pitch e duração de cada player, pela sessão mais recente que informou cada um. */
async function configDosPlayers(db, player) {
  const extra = player ? ' AND player = ?' : '';
  const params = player ? [player] : [];
  const janela = (coluna, condicao) => db.prepare(
    `SELECT player, ${coluna} AS valor FROM (SELECT player, ${coluna}, ROW_NUMBER() OVER (PARTITION BY player ORDER BY ultimo DESC, sessao DESC) AS rn `
    + `FROM sessoes WHERE ${condicao}${extra}) WHERE rn = 1`).bind(...params).all();
  const [pitches, duracoes] = await Promise.all([janela('pitch', 'pitch IS NOT NULL'), janela('duracao', 'duracao > 0')]);
  const config = {};
  for (const linha of pitches.results) config[linha.player] = { pitch: linha.valor, duracao: 0 };
  for (const linha of duracoes.results) (config[linha.player] = config[linha.player] || { pitch: null, duracao: 0 }).duracao = linha.valor;
  return config;
}

export async function players(db) {
  const [{ results }, config] = await Promise.all([
    db.prepare('SELECT player, COUNT(*) AS sessoes, MIN(inicio) AS primeiro, MAX(ultimo) AS ultimo FROM sessoes GROUP BY player ORDER BY ultimo DESC').all(),
    configDosPlayers(db, null),
  ]);
  return results.map((p) => ({ player: p.player, pitch: (config[p.player] || {}).pitch ?? null, duracao: (config[p.player] || {}).duracao || 0,
    primeiro: p.primeiro, ultimo: p.ultimo, sessoes: p.sessoes }));
}

export async function sessoes(db, { player, de, ate } = {}) {
  const { where, params } = filtro(player, de, ate);
  return (await db.prepare('SELECT * FROM sessoes' + where + ' ORDER BY inicio').bind(...params).all()).results;
}

/** Métricas do painel para um player e um período (datas AAAA-MM-DD inclusivas, ou um `periodo` nomeado). */
export async function resumo(db, { player = null, de = null, ate = null, pitch = null, periodo = null } = {}, fuso = FUSO_PADRAO, agora = new Date()) {
  const hoje = hojeNoFuso(fuso, agora);
  if (periodo) [de, ate] = periodoParaDatas(periodo, hoje);
  const { where, params } = filtro(player, de, ate);
  const [{ results: linhas }, config] = await Promise.all([
    db.prepare('SELECT * FROM sessoes' + where).bind(...params).all(),
    configDosPlayers(db, player),
  ]);

  const envolvidos = new Set(linhas.map((s) => s.player));
  const base = envolvidos.size ? [...envolvidos] : Object.keys(config);
  const distintos = new Set(base.map((p) => (config[p] || {}).pitch).filter((p) => p != null));
  const pitchDe = (s) => (pitch != null ? pitch : (config[s.player] || {}).pitch ?? null);
  const chegou = (s) => { const p = pitchDe(s); return !!s.com_som && p != null && s.max_tempo >= p; };
  let pitchEm = null;
  let pitchMisto = false;
  if (pitch != null) pitchEm = pitch;
  else if (distintos.size === 1) pitchEm = [...distintos][0];
  else pitchMisto = distintos.size > 1;

  const plays = linhas.filter((s) => s.com_som);
  const duracaoConfig = Math.max(0, ...base.map((p) => (config[p] || {}).duracao || 0));
  const duracao = Math.min(Math.max(0, ...linhas.map((s) => s.duracao)) || duracaoConfig, MAX_SEGUNDOS);
  const chegaramPitch = plays.filter(chegou);
  const terminaram = plays.filter((s) => s.terminou);
  const tempos = plays.map((s) => s.segundos);
  const engajamentos = plays.filter((s) => s.duracao > 0).map((s) => Math.min(1, s.segundos / s.duracao));
  const media = (lista) => (lista.length ? lista.reduce((a, b) => a + b, 0) / lista.length : 0);
  const mediana = (lista) => {
    if (!lista.length) return 0;
    const ordenada = [...lista].sort((a, b) => a - b);
    const meio = Math.floor(ordenada.length / 2);
    return ordenada.length % 2 ? ordenada[meio] : (ordenada[meio - 1] + ordenada[meio]) / 2;
  };
  const arredondar = (n, casas) => Math.round(n * 10 ** casas) / 10 ** casas;

  const { passo, pontos } = compactarCurva(curvaRetencao(plays.map((s) => JSON.parse(s.assistido)), duracao));

  const porDia = {};
  for (const s of linhas) {
    const d = porDia[s.dia] || (porDia[s.dia] = { dia: s.dia, sessoes: 0, plays: 0 });
    d.sessoes += 1;
    d.plays += s.com_som ? 1 : 0;
  }
  const dias = Object.keys(porDia).sort();
  if (dias.length || (de && ate)) {
    const primeiro = de || dias[0];
    const ultimo = ate || dias[dias.length - 1];
    const total = Math.round((new Date(ultimo + 'T00:00:00Z') - new Date(primeiro + 'T00:00:00Z')) / 86400000);
    if (total >= 0 && total < MAX_DIAS) {
      for (let i = 0; i <= total; i++) {
        const d = somarDias(primeiro, i);
        porDia[d] = porDia[d] || { dia: d, sessoes: 0, plays: 0 };
      }
    }
  }

  const agrupar = (chave, limite) => {
    const grupos = {};
    for (const s of linhas) {
      const g = grupos[s[chave]] || (grupos[s[chave]] = { nome: s[chave], sessoes: 0, plays: 0, pitch: 0, terminaram: 0 });
      g.sessoes += 1;
      g.plays += s.com_som ? 1 : 0;
      g.pitch += chegou(s) ? 1 : 0;
      g.terminaram += s.com_som && s.terminou ? 1 : 0;
    }
    let lista = Object.values(grupos).sort((a, b) => b.sessoes - a.sessoes || (a.nome < b.nome ? -1 : a.nome > b.nome ? 1 : 0));
    if (limite && lista.length > limite) {
      const resto = { nome: 'outras', sessoes: 0, plays: 0, pitch: 0, terminaram: 0 };
      for (const g of lista.slice(limite)) for (const k of ['sessoes', 'plays', 'pitch', 'terminaram']) resto[k] += g[k];
      lista = lista.slice(0, limite).concat([resto]);
    }
    return lista;
  };

  const eventos = {};
  for (const s of linhas) {
    let contagem = {};
    try { contagem = JSON.parse(s.eventos || '{}'); } catch (e) { contagem = {}; }
    for (const [tipo, n] of Object.entries(contagem)) {
      const e = eventos[tipo] || (eventos[tipo] = { tipo, total: 0, sessoes: 0 });
      e.total += n;
      e.sessoes += 1;
    }
  }

  return {
    player,
    periodo: periodo || (de || ate ? 'custom' : 'tudo'),
    de,
    ate,
    hoje,
    duracao: arredondar(duracao, 1),
    pitch: pitchEm,
    pitch_misto: pitchMisto,
    sessoes: linhas.length,
    visitantes: new Set(linhas.map((s) => s.visitante).filter(Boolean)).size,
    plays: plays.length,
    taxa_play: linhas.length ? arredondar(plays.length / linhas.length, 4) : 0,
    chegaram_pitch: chegaramPitch.length,
    taxa_pitch: plays.length ? arredondar(chegaramPitch.length / plays.length, 4) : 0,
    terminaram: terminaram.length,
    taxa_conclusao: plays.length ? arredondar(terminaram.length / plays.length, 4) : 0,
    tempo_medio: arredondar(media(tempos), 1),
    tempo_mediano: arredondar(mediana(tempos), 1),
    engajamento: arredondar(media(engajamentos), 4),
    retencao: { passo, pontos },
    por_dia: Object.values(porDia).sort((a, b) => (a.dia < b.dia ? -1 : 1)),
    origens: agrupar('origem', 12),
    dispositivos: agrupar('dispositivo'),
    eventos: Object.values(eventos).sort((a, b) => b.total - a.total),
  };
}

export async function csv(db, { player = null, de = null, ate = null, periodo = null } = {}, fuso = FUSO_PADRAO, agora = new Date()) {
  if (periodo) [de, ate] = periodoParaDatas(periodo, hojeNoFuso(fuso, agora));
  const escapar = (v) => {
    const t = v == null ? '' : String(v);
    return /[;"\n\r]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
  };
  const linhas = [COLUNAS_CSV.join(';')];
  for (const s of await sessoes(db, { player, de, ate })) linhas.push(COLUNAS_CSV.map((c) => escapar(celula(s[c]))).join(';'));
  return linhas.join('\n') + '\n';
}

// ----------------------------------------------------------------------------- HTTP

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age': '86400',
};

function resposta(status, corpo = null, { tipo = 'text/plain; charset=utf-8', cors = false, extras = {} } = {}) {
  const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', ...(cors ? CORS : {}), ...extras };
  if (corpo != null) headers['Content-Type'] = tipo;
  return new Response(corpo, { status, headers });
}

const json = (status, dados) => resposta(status, JSON.stringify(dados), { tipo: 'application/json; charset=utf-8' });

function iguais(a, b) {
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diferente = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diferente |= (x[i] || 0) ^ (y[i] || 0);
  return diferente === 0;
}

function autorizado(request, url, token) {
  if (!token) return true;
  const enviado = url.searchParams.get('token') || request.headers.get('X-Token') || '';
  return iguais(enviado, token);
}

/** Cria o app. `painel` é o HTML do painel; `esquema` é o SQL da migração; `env` traz DB (D1), TOKEN e FUSO. */
export function criarApp({ painel, esquema = '' }) {
  // O esquema é garantido na primeira requisição de cada instância (CREATE TABLE IF NOT EXISTS é barato),
  // para o Worker funcionar mesmo quando a migração não rodou no deploy.
  let esquemaPronto = null;
  const garantirEsquema = (db) => {
    if (!esquema || !db || typeof db.exec !== 'function') return Promise.resolve();
    if (!esquemaPronto) esquemaPronto = db.exec(esquema).catch((erro) => { esquemaPronto = null; throw erro; });
    return esquemaPronto;
  };

  async function post(request, env, url) {
    const caminho = url.pathname.replace(/\/+$/, '') || '/';
    if (!CAMINHOS_COLETA.has(caminho)) return resposta(404, 'nao encontrado', { cors: true });
    const declarado = Number(request.headers.get('Content-Length') || 0);
    if (declarado > LIMITE_CORPO) return resposta(413, 'envio grande demais', { cors: true });
    const corpo = await request.text();
    if (!corpo) return resposta(400, 'envio vazio', { cors: true });
    if (corpo.length > LIMITE_CORPO) return resposta(413, 'envio grande demais', { cors: true });
    try {
      await registrar(env.DB, JSON.parse(corpo), request.headers.get('User-Agent') || '', env.FUSO || FUSO_PADRAO);
    } catch (erro) {
      if (erro instanceof SyntaxError || erro instanceof RangeError || (erro && erro.message && !/D1_|SQLITE/.test(erro.message))) {
        return resposta(400, 'envio invalido: ' + (erro && erro.name ? erro.name : 'erro'), { cors: true });
      }
      throw erro;
    }
    return resposta(204, null, { cors: true });
  }

  async function get(request, env, url) {
    const caminho = url.pathname.replace(/\/+$/, '') || '/';
    const fuso = env.FUSO || FUSO_PADRAO;
    if (caminho === '/saude') return json(200, { ok: true });
    if (caminho === '/api/config') return json(200, { token: !!env.TOKEN, versao: VERSAO, hoje: hojeNoFuso(fuso), fuso });
    if (caminho === '/' || caminho === '/painel') return resposta(200, painel, { tipo: 'text/html; charset=utf-8' });
    if (!['/api/resumo', '/api/players', '/api/sessoes.csv'].includes(caminho)) return resposta(404, 'nao encontrado');
    if (!autorizado(request, url, env.TOKEN)) return json(401, { erro: 'token invalido' });
    if (caminho === '/api/players') return json(200, { players: await players(env.DB) });

    const valor = (chave) => url.searchParams.get(chave) || '';
    const player = texto(valor('player'), MAX_ID) || null;
    const de = diaValido(valor('de'));
    const ate = diaValido(valor('ate'));
    if ((valor('de') && !de) || (valor('ate') && !ate)) return json(400, { erro: 'de e ate precisam estar no formato AAAA-MM-DD' });
    const periodo = valor('periodo') || null;
    if (periodo && periodo !== 'tudo' && !(periodo in PERIODOS)) return json(400, { erro: 'periodo precisa ser hoje, 7, 30, 90 ou tudo' });
    if (caminho === '/api/resumo') {
      const pitch = valor('pitch') ? pitchValido(valor('pitch')) : null;
      if (valor('pitch') && pitch == null) return json(400, { erro: 'pitch precisa ser um numero de segundos' });
      return json(200, await resumo(env.DB, { player, de, ate, pitch, periodo }, fuso));
    }
    const seguro = (player || 'todos').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60) || 'todos';
    return resposta(200, '﻿' + await csv(env.DB, { player, de, ate, periodo }, fuso),
      { tipo: 'text/csv; charset=utf-8', extras: { 'Content-Disposition': `attachment; filename="sessoes-${seguro}.csv"` } });
  }

  return {
    async fetch(request, env) {
      const url = new URL(request.url);
      try {
        if (request.method === 'OPTIONS') return resposta(204, null, { cors: true });
        await garantirEsquema(env.DB);
        if (request.method === 'POST') return await post(request, env, url);
        if (request.method === 'GET') return await get(request, env, url);
        if (request.method === 'HEAD') {
          const r = await get(request, env, url);
          return new Response(null, { status: r.status, headers: r.headers });
        }
        return resposta(405, 'metodo nao permitido');
      } catch (erro) {
        console.error('erro em ' + request.method + ' ' + url.pathname, erro);
        return resposta(500, 'erro interno', { cors: request.method === 'POST' });
      }
    },
  };
}
