/**
 * Analytics do VSL Player em um Cloudflare Worker com banco D1.
 *
 * Mesmas rotas e os mesmos números do servidor Python (player/analytics/servidor.py):
 *   POST /vsl                      recebe o envio do player (JSON, mesmo como text/plain)
 *   GET  /                         o painel
 *   GET  /api/config | /saude      públicos
 *   GET  /api/players | /api/resumo | /api/sessoes.csv   pedem o TOKEN, se houver
 *   (filtros de /api/resumo e /api/sessoes.csv: player, periodo ou de/ate, navegador; /api/resumo aceita pitch)
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
export const AMOSTRA_CURVA = 2000;        // acima disso plays com som, a curva de retenção sai de uma amostra
export const PLAYS_POUCOS = 30;           // abaixo disso o painel avisa que os números ainda são ruído
export const MAX_NAVEGADOR = 40;          // tamanho máximo do filtro navegador=
export const NAVEGADOR_DESCONHECIDO = 'Desconhecido'; // como as sessões sem navegador ('' , anteriores à migração 0003) aparecem
export const FUSO_PADRAO = 'America/Sao_Paulo';

const CAMINHOS_COLETA = new Set(['/vsl', '/coletar', '/']);
const MAX_TIPOS_EVENTO = 50;   // tipos de evento distintos guardados por sessão
const TENTATIVAS_GRAVACAO = 5; // envios simultâneos da mesma sessão: relê e refaz
// Mapas indexados por texto vindo do visitante nunca têm prototype (utm_source=__proto__ não pode corromper nada).
const semProto = (obj) => Object.assign(Object.create(null), obj || {});
const PERIODOS = semProto({ hoje: 0, 7: 6, 30: 29, 90: 89 });
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
// As 20 primeiras colunas são as mesmas do servidor Python; `dia` (no fuso FUSO) vai no fim.
const COLUNAS_CSV = ['sessao', 'player', 'visitante', 'inicio', 'ultimo', 'origem', 'utm_source', 'utm_medium',
  'utm_campaign', 'utm_content', 'utm_term', 'dispositivo', 'url', 'referrer', 'duracao', 'max_tempo', 'segundos',
  'com_som', 'terminou', 'navegador', 'dia'];
// Sem `assistido`: a curva de retenção lê essa coluna numa consulta própria (só dos plays, e amostrada quando são muitos).
const COLUNAS_RESUMO = 'player, visitante, dia, origem, dispositivo, navegador, utm_content, utm_campaign, com_som, terminou, '
  + 'max_tempo, duracao, segundos, eventos';

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

// Navegador pelo User-Agent. A ordem importa: os apps (Instagram, Facebook, TikTok) e as WebViews do Android trazem
// "Chrome" e "Safari" no UA, Samsung e Edge também. O que sobra com "Chrome" é o Chrome; só "Safari" é o Safari.
// Mesma lista e mesma ordem do servidor Python (servidor.py: NAVEGADORES).
const NAVEGADORES = [
  [/Instagram/i, 'Instagram'],
  [/FBAN\/|FBAV\/|FB_IAB\/|FBIOS/, 'Facebook'],
  [/TikTok|musical_ly|BytedanceWebview|trill_/i, 'TikTok'],
  [/Android.*(; wv\)|Version\/\d[\d.]* +Chrome\/)/, 'Chrome WebView'],
  [/SamsungBrowser\//, 'Samsung'],
  [/Edg(e|A|iOS)?\//, 'Edge'],
  [/Firefox\/|FxiOS\//, 'Firefox'],
  [/Chrome\/|CriOS\//, 'Chrome'],
  [/Safari\//, 'Safari'],
];

/** 'Instagram' | 'Facebook' | 'TikTok' | 'Chrome WebView' | 'Samsung' | 'Edge' | 'Firefox' | 'Chrome' | 'Safari' | 'Outro'. */
export function navegador(userAgent) {
  const ua = typeof userAgent === 'string' ? userAgent : '';
  for (const [padrao, nome] of NAVEGADORES) if (padrao.test(ua)) return nome;
  return 'Outro';
}

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
  const contagem = Object.create(null);
  let tipos = 0;
  for (const ev of eventos) {
    if (!ev || typeof ev !== 'object') continue;
    const tipo = texto(ev.type, 60);
    if (!tipo) continue;
    if (!(tipo in contagem)) { if (tipos >= MAX_TIPOS_EVENTO) continue; tipos += 1; }
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
    eventos: Object.fromEntries(Object.entries(contagem)), // objeto comum, com "__proto__" como chave própria se vier
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
  for (let tentativa = 0; tentativa < TENTATIVAS_GRAVACAO; tentativa++) {
    const atual = await db.prepare('SELECT assistido, max_tempo, com_som, duracao, terminou, eventos, pitch FROM sessoes WHERE sessao = ?')
      .bind(envio.sessao).first();
    if (!atual) {
      const faixas = envio.faixas;
      const marcas = utms(envio.url);
      const r = await db.prepare('INSERT INTO sessoes (sessao, player, visitante, url, referrer, origem, utm_source, utm_medium, '
        + 'utm_campaign, utm_content, utm_term, dispositivo, navegador, user_agent, inicio, dia, ultimo, duracao, max_tempo, com_som, '
        + 'terminou, assistido, segundos, pitch, eventos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
        + 'ON CONFLICT(sessao) DO NOTHING')
        .bind(envio.sessao, envio.player, envio.visitante, envio.url, envio.referrer, origem(marcas.utm_source, envio.referrer),
          marcas.utm_source, marcas.utm_medium, marcas.utm_campaign, marcas.utm_content, marcas.utm_term, dispositivo(userAgent),
          navegador(userAgent), texto(userAgent, 500), momento, hojeNoFuso(fuso, agora), momento, envio.duracao,
          Math.min(envio.maxTempo, fimDasFaixas(faixas)), envio.comSom, envio.terminou, JSON.stringify(faixas),
          limitarSegundos(faixas, envio.duracao), envio.pitch, JSON.stringify(envio.eventos))
        .run();
      if (mudou(r) === 0) continue; // outro envio da mesma sessão chegou primeiro: refaz como atualização
      await atualizarPlayer(db, envio, momento, 1);
      return;
    }
    const faixas = unirFaixas(JSON.parse(atual.assistido).concat(envio.faixas));
    const duracao = Math.max(atual.duracao, envio.duracao);
    // O "até onde chegou" nunca passa do que as faixas mostram: protege contra um maxTime inflado.
    const maxTempo = Math.min(Math.max(atual.max_tempo, envio.maxTempo), fimDasFaixas(faixas));
    const eventos = semProto(JSON.parse(atual.eventos || '{}'));
    for (const [tipo, n] of Object.entries(envio.eventos)) {
      if (!(tipo in eventos) && Object.keys(eventos).length >= MAX_TIPOS_EVENTO) continue;
      eventos[tipo] = (Number(eventos[tipo]) || 0) + n;
    }
    // Só grava se a linha ainda for a que foi lida (assistido/eventos iguais); senão relê e soma de novo.
    const r = await db.prepare('UPDATE sessoes SET ultimo = ?, duracao = ?, max_tempo = ?, com_som = ?, terminou = ?, assistido = ?, '
      + 'segundos = ?, eventos = ?, pitch = COALESCE(?, pitch) WHERE sessao = ? AND assistido = ? AND eventos = ?')
      .bind(momento, duracao, maxTempo, Math.max(atual.com_som, envio.comSom), Math.max(atual.terminou, envio.terminou),
        JSON.stringify(faixas), limitarSegundos(faixas, duracao), JSON.stringify(Object.fromEntries(Object.entries(eventos))),
        envio.pitch, envio.sessao, atual.assistido, atual.eventos || '{}')
      .run();
    if (mudou(r) === 0) continue;
    const pitchNovo = envio.pitch != null && envio.pitch !== atual.pitch;
    const duracaoNova = envio.duracao > 0 && envio.duracao !== atual.duracao;
    if (pitchNovo || duracaoNova) await atualizarPlayer(db, envio, momento, 0);
    return;
  }
  throw new Error('nao foi possivel gravar a sessao: muitos envios simultaneos');
}

// Quantas linhas um run() mudou (D1 informa em meta.changes; sem a informação, assume que mudou).
const mudou = (r) => (r && r.meta && typeof r.meta.changes === 'number' ? r.meta.changes : 1);

/** Mantém o resumo por player: pitch e duração mais recentes, primeira e última sessão, total de sessões. */
async function atualizarPlayer(db, envio, momento, novas) {
  await db.prepare('INSERT INTO players (player, pitch, duracao, primeiro, ultimo, sessoes) VALUES (?,?,?,?,?,?) '
    + 'ON CONFLICT(player) DO UPDATE SET pitch = COALESCE(excluded.pitch, players.pitch), '
    + 'duracao = CASE WHEN excluded.duracao > 0 THEN excluded.duracao ELSE players.duracao END, '
    + 'ultimo = excluded.ultimo, sessoes = players.sessoes + excluded.sessoes')
    .bind(envio.player, envio.pitch, envio.duracao, momento, momento, novas).run();
}

// Tudo por parâmetro ligado (?): player e navegador vêm da URL do painel, nunca entram no texto do SQL.
function filtro(player, de, ate, navegador = null) {
  const condicoes = [];
  const params = [];
  if (player) { condicoes.push('player = ?'); params.push(player); }
  if (de) { condicoes.push('dia >= ?'); params.push(de); }
  if (ate) { condicoes.push('dia <= ?'); params.push(ate); }
  // "Desconhecido" é como o painel mostra as sessões sem navegador (gravadas antes da migração 0003)
  if (navegador) { condicoes.push('navegador = ?'); params.push(navegador === NAVEGADOR_DESCONHECIDO ? '' : navegador); }
  return { where: condicoes.length ? ' WHERE ' + condicoes.join(' AND ') : '', params };
}

/** Bancos criados antes da tabela players: monta a tabela a partir das sessões uma única vez. */
async function preencherPlayers(db) {
  const total = await db.prepare('SELECT COUNT(*) AS n FROM players').first('n');
  if (total > 0) return;
  const temSessoes = await db.prepare('SELECT COUNT(*) AS n FROM sessoes').first('n');
  if (!temSessoes) return;
  const janela = (coluna, condicao) => db.prepare(
    `SELECT player, ${coluna} AS valor FROM (SELECT player, ${coluna}, ROW_NUMBER() OVER (PARTITION BY player ORDER BY ultimo DESC, sessao DESC) AS rn `
    + `FROM sessoes WHERE ${condicao}) WHERE rn = 1`).all();
  const [{ results: base }, pitches, duracoes] = await Promise.all([
    db.prepare('SELECT player, MIN(inicio) AS primeiro, MAX(ultimo) AS ultimo, COUNT(*) AS sessoes FROM sessoes GROUP BY player').all(),
    janela('pitch', 'pitch IS NOT NULL'), janela('duracao', 'duracao > 0'),
  ]);
  const pitch = semProto(Object.fromEntries(pitches.results.map((l) => [l.player, l.valor])));
  const duracao = semProto(Object.fromEntries(duracoes.results.map((l) => [l.player, l.valor])));
  for (const p of base) {
    await db.prepare('INSERT OR IGNORE INTO players (player, pitch, duracao, primeiro, ultimo, sessoes) VALUES (?,?,?,?,?,?)')
      .bind(p.player, pitch[p.player] ?? null, duracao[p.player] || 0, p.primeiro, p.ultimo, p.sessoes).run();
  }
}

/** Pitch e duração de cada player (os mais recentes informados), pela tabela players. */
async function configDosPlayers(db, player) {
  await preencherPlayers(db);
  const { results } = await db.prepare('SELECT player, pitch, duracao FROM players' + (player ? ' WHERE player = ?' : ''))
    .bind(...(player ? [player] : [])).all();
  const config = Object.create(null);
  for (const l of results) config[l.player] = { pitch: l.pitch, duracao: l.duracao || 0 };
  return config;
}

export async function players(db) {
  await preencherPlayers(db);
  const { results } = await db.prepare('SELECT player, pitch, duracao, primeiro, ultimo, sessoes FROM players ORDER BY ultimo DESC').all();
  return results.map((p) => ({ player: p.player, pitch: p.pitch ?? null, duracao: p.duracao || 0, primeiro: p.primeiro, ultimo: p.ultimo, sessoes: p.sessoes }));
}

export async function sessoes(db, { player, de, ate, navegador } = {}) {
  const { where, params } = filtro(player, de, ate, navegador);
  return (await db.prepare('SELECT * FROM sessoes' + where + ' ORDER BY inicio').bind(...params).all()).results;
}

/** Métricas do painel para um player e um período (datas AAAA-MM-DD inclusivas, ou um `periodo` nomeado). */
export async function resumo(db, { player = null, de = null, ate = null, pitch = null, periodo = null, navegador = null } = {},
  fuso = FUSO_PADRAO, agora = new Date()) {
  const hoje = hojeNoFuso(fuso, agora);
  if (periodo) [de, ate] = periodoParaDatas(periodo, hoje);
  const { where, params } = filtro(player, de, ate, navegador);
  const [{ results: linhas }, config] = await Promise.all([
    db.prepare('SELECT ' + COLUNAS_RESUMO + ' FROM sessoes' + where).bind(...params).all(),
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
  let duracaoConfig = 0;
  for (const p of base) duracaoConfig = Math.max(duracaoConfig, (config[p] || {}).duracao || 0);
  let maior = 0;
  for (const s of linhas) if (s.duracao > maior) maior = s.duracao;
  const duracao = Math.min(maior || duracaoConfig, MAX_SEGUNDOS);
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

  // Curva de retenção: lê só `assistido`, e só dos plays. Acima de AMOSTRA_CURVA plays, usa uma amostra aleatória
  // (paliativo para o limite de CPU do plano gratuito); os números dos tiles continuam exatos.
  const curvaAmostrada = plays.length > AMOSTRA_CURVA;
  let listas = [];
  if (plays.length) {
    const sqlCurva = 'SELECT assistido FROM sessoes' + where + (where ? ' AND' : ' WHERE') + ' com_som = 1'
      + (curvaAmostrada ? ' ORDER BY RANDOM() LIMIT ' + AMOSTRA_CURVA : '');
    listas = (await db.prepare(sqlCurva).bind(...params).all()).results.map((l) => JSON.parse(l.assistido));
  }
  const { passo, pontos } = compactarCurva(curvaRetencao(listas, duracao));

  // Eventos: contagem por tipo e, por sessão, se houve clique no botão (cta_click) e erro do vídeo (error).
  const eventos = Object.create(null);
  for (const s of linhas) {
    let contagem = {};
    try { contagem = JSON.parse(s.eventos || '{}'); } catch (e) { contagem = {}; }
    if (!contagem || typeof contagem !== 'object' || Array.isArray(contagem)) contagem = {};
    const vezes = (tipo) => (Object.prototype.hasOwnProperty.call(contagem, tipo) ? Number(contagem[tipo]) || 0 : 0);
    s.clicou = vezes('cta_click') > 0 ? 1 : 0;
    s.errou = vezes('error') > 0 ? 1 : 0;
    for (const [tipo, n] of Object.entries(contagem)) {
      const e = eventos[tipo] || (eventos[tipo] = { tipo, total: 0, sessoes: 0 });
      e.total += Number(n) || 0;
      e.sessoes += 1;
    }
  }
  const cliques = linhas.reduce((n, s) => n + s.clicou, 0);
  const erros = linhas.reduce((n, s) => n + s.errou, 0);

  const porDia = Object.create(null);
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

  // Tabelas por origem, dispositivo, navegador, criativo e campanha: {nome, sessoes, plays, pitch, terminaram, cliques}.
  // `vazio` é o nome mostrado quando a coluna está em branco; acima de `limite` grupos, o resto vira "outras".
  const CHAVES_GRUPO = ['sessoes', 'plays', 'pitch', 'terminaram', 'cliques'];
  const agrupar = (chave, limite = null, vazio = '') => {
    const grupos = Object.create(null);
    for (const s of linhas) {
      const nome = s[chave] || vazio;
      const g = grupos[nome] || (grupos[nome] = { nome, sessoes: 0, plays: 0, pitch: 0, terminaram: 0, cliques: 0 });
      g.sessoes += 1;
      g.plays += s.com_som ? 1 : 0;
      g.pitch += chegou(s) ? 1 : 0;
      g.terminaram += s.com_som && s.terminou ? 1 : 0;
      g.cliques += s.clicou;
    }
    let lista = Object.values(grupos).sort((a, b) => b.sessoes - a.sessoes || (a.nome < b.nome ? -1 : a.nome > b.nome ? 1 : 0));
    if (limite && lista.length > limite) {
      const resto = { nome: 'outras', sessoes: 0, plays: 0, pitch: 0, terminaram: 0, cliques: 0 };
      for (const g of lista.slice(limite)) for (const k of CHAVES_GRUPO) resto[k] += g[k];
      lista = lista.slice(0, limite).concat([resto]);
    }
    return lista;
  };

  return {
    player,
    navegador,
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
    cliques,
    taxa_clique: chegaramPitch.length ? arredondar(cliques / chegaramPitch.length, 4) : 0,
    erros,
    taxa_erro: linhas.length ? arredondar(erros / linhas.length, 4) : 0,
    funil: { visitas: linhas.length, plays: plays.length, pitch: chegaramPitch.length, cliques },
    amostra: { plays: plays.length, pequena: plays.length < PLAYS_POUCOS },
    tempo_medio: arredondar(media(tempos), 1),
    tempo_mediano: arredondar(mediana(tempos), 1),
    engajamento: arredondar(media(engajamentos), 4),
    retencao: { passo, pontos },
    curva_amostrada: curvaAmostrada,
    curva_n: listas.length,
    por_dia: Object.values(porDia).sort((a, b) => (a.dia < b.dia ? -1 : 1)),
    origens: agrupar('origem', 12, 'direto'),
    dispositivos: agrupar('dispositivo'),
    navegadores: agrupar('navegador', null, NAVEGADOR_DESCONHECIDO),
    criativos: agrupar('utm_content', 12, '(sem utm_content)'),
    campanhas: agrupar('utm_campaign', 12, '(sem utm_campaign)'),
    eventos: Object.values(eventos).sort((a, b) => b.total - a.total),
  };
}

export async function csv(db, { player = null, de = null, ate = null, periodo = null, navegador = null } = {}, fuso = FUSO_PADRAO, agora = new Date()) {
  if (periodo) [de, ate] = periodoParaDatas(periodo, hojeNoFuso(fuso, agora));
  const escapar = (v) => {
    const t = v == null ? '' : String(v);
    return /[;"\n\r]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
  };
  const linhas = [COLUNAS_CSV.join(';')];
  for (const s of await sessoes(db, { player, de, ate, navegador })) linhas.push(COLUNAS_CSV.map((c) => escapar(celula(s[c]))).join(';'));
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

// Só por cabeçalho: na query string o token iria parar nos logs da Cloudflare.
function autorizado(request, url, token) {
  if (!token) return true;
  const auth = request.headers.get('Authorization') || '';
  const enviado = request.headers.get('X-Token') || (auth.startsWith('Bearer ') ? auth.slice(7) : '');
  return iguais(enviado, token);
}

const ADICIONAR_COLUNA = /^ALTER\s+TABLE\s+(\w+)\s+ADD\s+(?:COLUMN\s+)?(\w+)\b/i;

/** Se a tabela já tem a coluna, pelo PRAGMA table_info. Sem PRAGMA disponível, responde false e o ALTER decide. */
async function temColuna(db, tabela, coluna) {
  try {
    const { results } = await db.prepare('PRAGMA table_info(' + tabela + ')').all(); // `tabela` vem do nosso SQL (\w+), não do visitante
    return (results || []).some((l) => l.name === coluna);
  } catch (e) {
    return false;
  }
}

/**
 * Roda um comando do esquema de forma idempotente. CREATE ... IF NOT EXISTS já é; ALTER TABLE ... ADD COLUMN não
 * (a segunda vez dá "duplicate column name"), e ele roda em toda instância nova do Worker e também na
 * `wrangler d1 migrations apply`. Por isso confere antes pelo PRAGMA e, se mesmo assim a coluna já existir
 * (duas instâncias ao mesmo tempo), ignora o erro de coluna duplicada.
 */
export async function rodarComandoDoEsquema(db, comando) {
  const m = ADICIONAR_COLUNA.exec(comando);
  if (m && await temColuna(db, m[1], m[2])) return;
  try {
    await db.prepare(comando).run();
  } catch (erro) {
    if (!m || !/duplicate column/i.test((erro && erro.message) || '')) throw erro;
  }
}

/** Cria o app. `painel` é o HTML do painel; `esquema` é o SQL das migrações; `env` traz DB (D1), TOKEN e FUSO. */
export function criarApp({ painel, esquema = '' }) {
  // O esquema é garantido na primeira requisição de cada instância (CREATE TABLE IF NOT EXISTS é barato e o
  // ALTER TABLE só roda se a coluna faltar), para o Worker funcionar mesmo quando a migração não rodou no deploy.
  // Cada comando vai num prepare() próprio: o exec() do D1 quebra o SQL por linha e não aceita comandos de várias linhas.
  const comandos = esquema.split(';').map((c) => c.replace(/--[^\n]*/g, '').trim()).filter(Boolean);
  let esquemaPronto = null;
  const garantirEsquema = (db) => {
    if (!comandos.length || !db || typeof db.prepare !== 'function') return Promise.resolve();
    if (!esquemaPronto) {
      // em sequência: o índice só compila depois que a tabela existe, e o ALTER depois do CREATE
      esquemaPronto = (async () => { for (const c of comandos) await rodarComandoDoEsquema(db, c); })()
        .catch((erro) => { esquemaPronto = null; throw erro; });
    }
    return esquemaPronto;
  };

  async function post(request, env, url) {
    const caminho = url.pathname.replace(/\/+$/, '') || '/';
    if (!CAMINHOS_COLETA.has(caminho)) return resposta(404, 'nao encontrado', { cors: true });
    const declarado = Number(request.headers.get('Content-Length') || 0);
    if (declarado > LIMITE_CORPO) return resposta(413, 'envio grande demais', { cors: true });
    if (!request.body) return resposta(400, 'envio vazio', { cors: true });
    // lê em pedaços e para no limite, contando bytes de verdade
    const reader = request.body.getReader();
    const partes = [];
    let total = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > LIMITE_CORPO) { try { await reader.cancel(); } catch (e) { /* ignora */ } return resposta(413, 'envio grande demais', { cors: true }); }
      partes.push(value);
    }
    if (!total) return resposta(400, 'envio vazio', { cors: true });
    const corpo = await new Blob(partes).text();
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
    // navegador=: texto de até MAX_NAVEGADOR caracteres (ex.: Instagram, Chrome WebView, Desconhecido); só entra ligado (?)
    const navegadorPedido = valor('navegador');
    const navegador = texto(navegadorPedido, MAX_NAVEGADOR) || null;
    if (navegadorPedido && (navegadorPedido.length > MAX_NAVEGADOR || !navegador)) {
      return json(400, { erro: 'navegador precisa ser um texto de ate ' + MAX_NAVEGADOR + ' caracteres' });
    }
    if (caminho === '/api/resumo') {
      const pitch = valor('pitch') ? pitchValido(valor('pitch')) : null;
      if (valor('pitch') && pitch == null) return json(400, { erro: 'pitch precisa ser um numero de segundos' });
      return json(200, await resumo(env.DB, { player, de, ate, pitch, periodo, navegador }, fuso));
    }
    const seguro = (player || 'todos').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 60) || 'todos';
    return resposta(200, '﻿' + await csv(env.DB, { player, de, ate, periodo, navegador }, fuso),
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
