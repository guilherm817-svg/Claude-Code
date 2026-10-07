// Testes do Worker (node --test). Rodam sem a Cloudflare: o D1 é imitado com o node:sqlite.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { criarD1, lerMigracoes } from './d1.js';
import {
  criarApp, registrar, resumo, players, sessoes, csv, unirFaixas, curvaRetencao, compactarCurva, origem, dispositivo, navegador,
  validarEnvio, pitchValido, periodoParaDatas, hojeNoFuso, numero, rodarComandoDoEsquema,
  MAX_SEGUNDOS, PONTOS_CURVA, LIMITE_CORPO, MAX_EVENTOS, AMOSTRA_CURVA, PLAYS_POUCOS, MAX_NAVEGADOR,
} from '../src/app.js';

const FUSO = 'America/Sao_Paulo';
// User-Agents reais (abreviados), um por classe de navegador. Os mesmos estão em tests/test_vsl_analytics.py.
const UA = {
  instagramIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 334.0.4.32.98 (iPhone15,2; iOS 17_5; pt_BR; pt; scale=3.00; 1179x2556; 601595932)',
  instagramAndroid: 'Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.179 Mobile Safari/537.36 Instagram 334.0.0.42.95 Android (34/14; 450dpi; 1080x2340; samsung; SM-S918B; dm3q; qcom; pt_BR; 597335394)',
  facebookAndroid: 'Mozilla/5.0 (Linux; Android 14; SM-A546E Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.179 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/467.0.0.47.108;]',
  facebookIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBAV/467.0.0.37.108;FBBV/605519286;FBDV/iPhone15,2;FBMD/iPhone;FBSN/iOS;FBSV/17.5;FBSS/3;FBID/phone;FBLC/pt_BR;FBOP/5]',
  tiktokIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 musical_ly_34.5.0 JsSdk/2.0 NetType/WIFI Channel/App Store ByteLocale/pt-BR Region/BR WKWebView/1 BytedanceWebview/d8a21c6',
  tiktokAndroid: 'Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.179 Mobile Safari/537.36 trill_2022803 JsSdk/1.0 NetType/WIFI Channel/googleplay AppName/musical_ly app_version/34.5.3 BytedanceWebview/d8a21c6',
  webviewWv: 'Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ3A.230805.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.179 Mobile Safari/537.36',
  webviewVersion: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 Mobile Safari/537.36',
  samsung: 'Mozilla/5.0 (Linux; Android 14; SAMSUNG SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36',
  edge: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
  edgeAndroid: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36 EdgA/124.0.0.0',
  firefox: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0',
  firefoxIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/126.0 Mobile/15E148 Safari/605.1.15',
  chrome: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  chromeAndroid: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
  chromeIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0.6367.88 Mobile/15E148 Safari/604.1',
  safariIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
  safariMac: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15',
  wkwebview: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
  curl: 'curl/8.5.0',
};
const envio = (sessao = 's1', extra = {}) => ({
  v: '1.0.0', player: 'vsl-principal', visitor: 'vis-1', session: sessao,
  url: 'https://site.com/vsl?utm_source=Facebook&utm_campaign=lancamento', referrer: 'https://l.facebook.com/',
  duration: 120, maxTime: 40, unmuted: true, pitch: 30, watched: [[0, 39]],
  events: [{ type: 'unmute', ts: 1000, time: 0 }, { type: 'pitch', ts: 2000, time: 30, at: 30 }], sentAt: 3000, ...extra,
});
const em = (texto) => new Date(texto);

// ---------------------------------------------------------------- cálculos

test('unirFaixas junta sobrepostas e vizinhas e ignora lixo', () => {
  assert.deepEqual(unirFaixas([[10, 20], [0, 5], [6, 8], [15, 30], [50, 50]]), [[0, 8], [10, 30], [50, 50]]);
  assert.deepEqual(unirFaixas([[5, 2], ['a', 1], null, [-3, 4], [1, 2], 'xy', [true, 3], [0, Infinity], [1e300, 1e300]]), [[1, 2], [MAX_SEGUNDOS, MAX_SEGUNDOS]]);
});

test('curvaRetencao e compactarCurva', () => {
  assert.deepEqual(curvaRetencao([[[0, 3]], [[2, 5]], [[0, 9]]], 6), [2, 2, 3, 3, 2, 2, 1]);
  const { passo, pontos } = compactarCurva(Array.from({ length: 3000 }, (_, i) => i), 1000);
  assert.equal(passo, 3); assert.equal(pontos.length, 1000); assert.equal(pontos[0], 1);
});

test('origem, dispositivo, numero e pitch', () => {
  assert.equal(origem('', 'https://l.facebook.com/l.php?u=x'), 'facebook');
  assert.equal(origem('', 'https://www.google.com.br/'), 'google');
  assert.equal(origem('', 'https://blog.exemplo.com/post'), 'blog.exemplo.com');
  assert.equal(origem('', ''), 'direto');
  assert.equal(origem('TikTok', 'https://www.google.com/'), 'tiktok');
  assert.equal(dispositivo('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)'), 'celular');
  assert.equal(dispositivo('Mozilla/5.0 (Windows NT 10.0; Win64; x64)'), 'computador');
  assert.equal(numero('nan'), 0); assert.equal(numero([5]), 0); assert.equal(numero(true), 0); assert.equal(numero('12.5', 0, 10), 10);
  assert.equal(pitchValido('abc'), null); assert.equal(pitchValido(true), null); assert.equal(pitchValido(-1), null);
  assert.equal(pitchValido([1]), null); assert.equal(pitchValido('nan'), null); assert.equal(pitchValido('12.5'), 12.5);
  assert.equal(pitchValido(0), 0);
});

test('navegador pelo User-Agent: um UA por classe, apps antes das WebViews, WebViews antes do Chrome', () => {
  const esperado = {
    instagramIos: 'Instagram', instagramAndroid: 'Instagram', facebookAndroid: 'Facebook', facebookIos: 'Facebook',
    tiktokIos: 'TikTok', tiktokAndroid: 'TikTok', webviewWv: 'Chrome WebView', webviewVersion: 'Chrome WebView',
    samsung: 'Samsung', edge: 'Edge', edgeAndroid: 'Edge', firefox: 'Firefox', firefoxIos: 'Firefox',
    chrome: 'Chrome', chromeAndroid: 'Chrome', chromeIos: 'Chrome', safariIos: 'Safari', safariMac: 'Safari',
    wkwebview: 'Outro', curl: 'Outro',
  };
  for (const [chave, nome] of Object.entries(esperado)) assert.equal(navegador(UA[chave]), nome, chave);
  assert.equal(navegador(''), 'Outro'); assert.equal(navegador(undefined), 'Outro'); assert.equal(navegador(null), 'Outro');
  assert.equal(navegador(123), 'Outro');
});

test('validarEnvio rejeita e limpa', () => {
  assert.throws(() => validarEnvio([1, 2]));
  assert.throws(() => validarEnvio({ player: 'p' }));
  assert.throws(() => validarEnvio({ player: 'p', session: 's', events: 'x' }));
  assert.throws(() => validarEnvio({ player: 'p', session: 's', events: new Array(MAX_EVENTOS + 1).fill({}) }));
  const limpo = validarEnvio({ player: ' p\x00\n ', session: 's', duration: 'nan', maxTime: -5, unmuted: 'sim', watched: [[3, 1], [0, 2]], pitch: '',
    events: [{ type: 'x', ts: 'abc' }, 'lixo', { type: 'x' }, { type: 'ended' }] });
  assert.equal(limpo.player, 'p'); assert.equal(limpo.duracao, 0); assert.equal(limpo.maxTempo, 0); assert.equal(limpo.comSom, 1);
  assert.deepEqual(limpo.faixas, [[0, 2]]); assert.equal(limpo.pitch, null); assert.deepEqual(limpo.eventos, { x: 2, ended: 1 }); assert.equal(limpo.terminou, 1);
});

test('dia no fuso e períodos pelo relógio do servidor', () => {
  // 01:00 UTC do dia 7 ainda é dia 6 em São Paulo
  assert.equal(hojeNoFuso(FUSO, em('2026-10-07T01:00:00Z')), '2026-10-06');
  assert.equal(hojeNoFuso('fuso/inexistente', em('2026-10-07T01:00:00Z')), '2026-10-07');
  assert.deepEqual(periodoParaDatas('7', '2026-10-06'), ['2026-09-30', '2026-10-06']);
  assert.deepEqual(periodoParaDatas('hoje', '2026-10-06'), ['2026-10-06', '2026-10-06']);
  assert.deepEqual(periodoParaDatas('tudo', '2026-10-06'), [null, null]);
  assert.throws(() => periodoParaDatas('ontem', '2026-10-06'));
});

// ---------------------------------------------------------------- banco

test('registrar cria a sessão com origem, utm, dispositivo e dia no fuso', async () => {
  const db = criarD1();
  await registrar(db, envio(), 'Mozilla/5.0 (iPhone)', FUSO, em('2026-10-07T01:00:00Z'));
  const [s] = await sessoes(db);
  assert.equal(s.origem, 'facebook'); assert.equal(s.utm_campaign, 'lancamento'); assert.equal(s.dispositivo, 'celular');
  assert.equal(s.segundos, 40); assert.equal(s.com_som, 1); assert.equal(s.dia, '2026-10-06'); assert.equal(s.inicio, '2026-10-07T01:00:00Z');
  assert.equal((await players(db))[0].pitch, 30);
});

test('registrar de novo une faixas, soma eventos e mantém o máximo', async () => {
  const db = criarD1();
  await registrar(db, envio());
  await registrar(db, envio('s1', { maxTime: 100, watched: [[0, 39], [60, 99]], unmuted: false, events: [{ type: 'unmute' }, { type: 'ended' }] }));
  const [s] = await sessoes(db);
  assert.deepEqual(JSON.parse(s.assistido), [[0, 39], [60, 99]]);
  assert.equal(s.segundos, 80); assert.equal(s.max_tempo, 100); assert.equal(s.com_som, 1); assert.equal(s.terminou, 1);
  assert.deepEqual(JSON.parse(s.eventos), { unmute: 2, pitch: 1, ended: 1 });
  const r = await resumo(db);
  assert.deepEqual(Object.fromEntries(r.eventos.map((e) => [e.tipo, [e.total, e.sessoes]])), { unmute: [2, 1], pitch: [1, 1], ended: [1, 1] });
});

test('resumo calcula plays, pitch, tempos e retenção', async () => {
  const db = criarD1();
  await registrar(db, envio('a'));
  await registrar(db, envio('b', { visitor: 'vis-2', maxTime: 10, watched: [[0, 9]] }));
  await registrar(db, envio('c', { visitor: 'vis-3', unmuted: false, maxTime: 50, watched: [[0, 49]], events: [] }));
  const r = await resumo(db, { player: 'vsl-principal' });
  assert.deepEqual([r.sessoes, r.visitantes, r.plays], [3, 3, 2]);
  assert.ok(Math.abs(r.taxa_play - 2 / 3) < 1e-3);
  assert.equal(r.chegaram_pitch, 1); assert.equal(r.taxa_pitch, 0.5); assert.equal(r.pitch, 30); assert.equal(r.pitch_misto, false);
  assert.equal(r.tempo_medio, 25); assert.equal(r.tempo_mediano, 25); assert.equal(r.duracao, 120);
  assert.equal(r.engajamento, Math.round(((40 / 120 + 10 / 120) / 2) * 10000) / 10000);
  const p = r.retencao.pontos;
  assert.equal(r.retencao.passo, 1); assert.equal(p.length, 121);
  assert.deepEqual([p[0], p[9], p[10], p[39], p[40]], [2, 2, 1, 1, 0]);
  assert.equal(r.origens[0].nome, 'facebook'); assert.equal(r.origens[0].plays, 2);
  assert.equal(r.por_dia[0].sessoes, 3); assert.equal(r.por_dia[0].plays, 2);
});

test('resumo filtra por player, por datas e por período, e preenche os dias', async () => {
  const db = criarD1();
  await registrar(db, envio('a'), '', FUSO, em('2026-10-01T13:00:00Z'));
  await registrar(db, envio('b', { player: 'outro' }), '', FUSO, em('2026-10-03T13:00:00Z'));
  await registrar(db, envio('c'), '', FUSO, em('2026-10-05T13:00:00Z'));
  assert.equal((await resumo(db, { player: 'vsl-principal' })).sessoes, 2);
  assert.equal((await resumo(db, { player: 'outro' })).sessoes, 1);
  const meio = await resumo(db, { de: '2026-10-02', ate: '2026-10-04' });
  assert.equal(meio.sessoes, 1); assert.equal(meio.eventos[0].sessoes, 1);
  const dias = (await resumo(db, { de: '2026-10-01', ate: '2026-10-05' })).por_dia;
  assert.deepEqual(dias.map((d) => d.dia.slice(-2)), ['01', '02', '03', '04', '05']); assert.equal(dias[1].sessoes, 0);
  const agora = em('2026-10-06T15:00:00Z');
  assert.equal((await resumo(db, { periodo: 'hoje' }, FUSO, agora)).sessoes, 0);
  assert.equal((await resumo(db, { periodo: '7' }, FUSO, agora)).sessoes, 3);
  const r = await resumo(db, { periodo: '30' }, FUSO, agora);
  assert.equal(r.de, '2026-09-07'); assert.equal(r.ate, '2026-10-06'); assert.equal(r.hoje, '2026-10-06');
  await assert.rejects(resumo(db, { periodo: 'ontem' }));
  assert.equal((await csv(db, { periodo: '7' }, FUSO, agora)).split('\n').length, 5);
});

test('teto de duração: um envio absurdo não derruba o resumo', async () => {
  const db = criarD1();
  await registrar(db, envio('s1', { duration: 1e300, maxTime: 1e300, watched: [[0, 1e300], [5, 1e308]], events: [{ type: 'x', ts: 1e300, n: 1e300 }] }));
  const r = await resumo(db);
  assert.equal(r.duracao, MAX_SEGUNDOS); assert.ok(r.retencao.pontos.length <= PONTOS_CURVA);
  const [s] = await sessoes(db);
  assert.equal(s.max_tempo, MAX_SEGUNDOS); assert.deepEqual(JSON.parse(s.assistido), [[0, MAX_SEGUNDOS]]);
});

test('max_tempo nunca passa do que foi assistido', async () => {
  const db = criarD1();
  await registrar(db, envio('s1', { maxTime: 500, watched: [[0, 4]] }));
  assert.equal((await sessoes(db))[0].max_tempo, 5);
  assert.equal((await resumo(db)).chegaram_pitch, 0);
  await registrar(db, envio('s1', { maxTime: 500, watched: [[0, 4], [5, 35]] }));
  assert.equal((await sessoes(db))[0].max_tempo, 36); assert.equal((await resumo(db)).chegaram_pitch, 1);
});

test('pitch de cada player na vista geral', async () => {
  const db = criarD1();
  await registrar(db, envio('a', { player: 'curto', pitch: 10, maxTime: 20, watched: [[0, 19]] }));
  await registrar(db, envio('b', { player: 'longo', pitch: 50, maxTime: 20, watched: [[0, 19]] }));
  const geral = await resumo(db);
  assert.equal(geral.chegaram_pitch, 1); assert.equal(geral.pitch, null); assert.equal(geral.pitch_misto, true);
  assert.deepEqual(Object.fromEntries(geral.origens.map((o) => [o.nome, o.pitch])), { facebook: 1 });
  assert.equal((await resumo(db, { player: 'longo' })).pitch, 50); assert.equal((await resumo(db, { player: 'longo' })).chegaram_pitch, 0);
  assert.equal((await resumo(db, { pitch: 15 })).chegaram_pitch, 2); assert.equal((await resumo(db, { pitch: 15 })).pitch_misto, false);
});

test('duração e pitch do player vêm da sessão mais recente; o resumo usa as do período', async () => {
  const db = criarD1();
  await registrar(db, envio('a', { duration: 600, maxTime: 300, watched: [[0, 299]] }), '', FUSO, em('2026-09-01T13:00:00Z'));
  await registrar(db, envio('b', { duration: 120, maxTime: 60, watched: [[0, 59]] }), '', FUSO, em('2026-10-01T13:00:00Z'));
  await registrar(db, envio('c', { duration: 0, pitch: 'abc', maxTime: 10, watched: [[0, 9]] }), '', FUSO, em('2026-10-02T13:00:00Z'));
  assert.equal((await players(db))[0].duracao, 120);
  assert.equal((await players(db))[0].pitch, 30);
  assert.equal((await resumo(db, { de: '2026-10-01', ate: '2026-10-01' })).duracao, 120);
  assert.equal((await resumo(db, { ate: '2026-09-30' })).duracao, 600);
  assert.equal((await resumo(db, { de: '2026-10-01', ate: '2026-10-01' })).engajamento, 0.5);
  assert.equal((await resumo(db, { de: '2026-10-02' })).duracao, 120); // sem duração no período, usa a do player
});

test('pitch 0 vale como pitch; pitch inválido não apaga o gravado', async () => {
  const db = criarD1();
  await registrar(db, envio('s1', { pitch: 'abc' }));
  assert.equal((await players(db))[0].pitch, null);
  await registrar(db, envio('s1', { pitch: 0 }));
  assert.equal((await players(db))[0].pitch, 0); assert.equal((await resumo(db)).chegaram_pitch, 1);
  await registrar(db, envio('s1', { pitch: 'lixo' }));
  assert.equal((await players(db))[0].pitch, 0);
});

test('segundos não passam da duração', async () => {
  const db = criarD1();
  await registrar(db, envio('s1', { duration: 30.5, maxTime: 30.5, watched: [[0, 30]] }));
  const r = await resumo(db);
  assert.equal((await sessoes(db))[0].segundos, 30.5); assert.equal(r.tempo_medio, 30.5); assert.equal(r.engajamento, 1);
});

test('csv neutraliza fórmulas e escapa separadores', async () => {
  const db = criarD1();
  await registrar(db, envio("=cmd|' /C calc'!A0", { visitor: '+1', url: 'https://site.com/?utm_source=@SUM(1)&utm_campaign=-x;y' }));
  const linha = (await csv(db)).split('\n')[1];
  assert.ok(linha.startsWith("'=cmd"));
  assert.ok(linha.includes(";'+1;"));
  assert.ok(linha.includes(";'@sum(1);'@SUM(1);;\"'-x;y\";"));
  const cabecalho = (await csv(db)).split('\n')[0].split(';');
  assert.equal(cabecalho.length, 21); assert.equal(cabecalho[19], 'navegador'); assert.equal(cabecalho[20], 'dia'); assert.equal(cabecalho[3], 'inicio');
});

test('navegador gravado na sessão e no CSV (penúltima coluna, antes de dia)', async () => {
  const db = criarD1();
  await registrar(db, envio('a'), UA.instagramIos, FUSO, em('2026-10-07T13:00:00Z'));
  await registrar(db, envio('b'), UA.webviewWv, FUSO, em('2026-10-07T13:01:00Z'));
  await registrar(db, envio('c'), '', FUSO, em('2026-10-07T13:02:00Z'));
  const lista = await sessoes(db);
  assert.deepEqual(lista.map((s) => s.navegador), ['Instagram', 'Chrome WebView', 'Outro']);
  const linhas = (await csv(db)).trim().split('\n');
  assert.equal(linhas.length, 4);
  const colunas = linhas[1].split(';');
  assert.equal(colunas[19], 'Instagram'); assert.equal(colunas[20], '2026-10-07'); assert.equal(colunas[18], '0');
  assert.ok(linhas[2].includes(';Chrome WebView;'));
});

test('resumo: cliques, erros, funil, amostra pequena e tabelas por navegador, criativo e campanha (todas com cliques)', async () => {
  const db = criarD1();
  const url = (conteudo, campanha = 'lancamento') => 'https://site.com/vsl?utm_source=Facebook&utm_campaign=' + campanha + '&utm_content=' + conteudo;
  // a: play, chegou ao pitch, clicou duas vezes (conta uma sessão)
  await registrar(db, envio('a', { url: url('video-1'), events: [{ type: 'unmute' }, { type: 'cta_click', where: 'end' }, { type: 'cta_click' }] }), UA.instagramIos);
  // b: play, não chegou ao pitch, erro do vídeo
  await registrar(db, envio('b', { visitor: 'vis-2', url: url('video-1'), maxTime: 10, watched: [[0, 9]], events: [{ type: 'error', code: 'hls-load' }] }), UA.chrome);
  // c: mudo, clicou no botão da miniatura de pausa; sem utm
  await registrar(db, envio('c', { visitor: 'vis-3', url: 'https://site.com/vsl', referrer: '', unmuted: false, maxTime: 50, watched: [[0, 49]], events: [{ type: 'cta_click' }] }), UA.safariIos);
  // d: mudo, outra campanha e outro criativo, UA vazio
  await registrar(db, envio('d', { visitor: 'vis-4', url: url('video-2', 'remarketing'), unmuted: false, events: [] }), '');
  const r = await resumo(db);
  assert.deepEqual([r.sessoes, r.plays, r.chegaram_pitch], [4, 2, 1]);
  assert.equal(r.cliques, 2, 'cliques: toda sessão com cta_click, inclusive a muda');
  assert.equal(r.cliques_pitch, 1); assert.equal(r.taxa_clique, 1, 'cliques de quem chegou ao pitch ÷ chegaram ao pitch (1 ÷ 1); o clique da sessão muda fica fora');
  assert.equal(r.erros, 1); assert.equal(r.taxa_erro, 0.25);
  assert.deepEqual(r.funil, { visitas: 4, plays: 2, pitch: 1, cliques: 1 }, 'o funil é decrescente: só cliques de quem chegou ao pitch');
  assert.deepEqual(r.amostra, { plays: 2, pequena: true });
  assert.equal(r.curva_amostrada, false); assert.equal(r.curva_n, 2); assert.equal(r.navegador, null);
  const porNome = (lista) => Object.fromEntries(lista.map((g) => [g.nome, g]));
  const nav = porNome(r.navegadores);
  assert.deepEqual(Object.keys(nav).sort(), ['Chrome', 'Instagram', 'Outro', 'Safari']);
  assert.deepEqual(nav.Instagram, { nome: 'Instagram', sessoes: 1, plays: 1, pitch: 1, terminaram: 0, cliques: 1, cliques_pitch: 1 });
  assert.deepEqual(nav.Safari, { nome: 'Safari', sessoes: 1, plays: 0, pitch: 0, terminaram: 0, cliques: 1, cliques_pitch: 0 });
  assert.deepEqual(nav.Chrome, { nome: 'Chrome', sessoes: 1, plays: 1, pitch: 0, terminaram: 0, cliques: 0, cliques_pitch: 0 });
  const cri = porNome(r.criativos);
  assert.deepEqual(cri['video-1'], { nome: 'video-1', sessoes: 2, plays: 2, pitch: 1, terminaram: 0, cliques: 1, cliques_pitch: 1 });
  assert.equal(cri['video-2'].sessoes, 1); assert.equal(cri['(sem utm_content)'].sessoes, 1); assert.equal(cri['(sem utm_content)'].cliques, 1);
  const cam = porNome(r.campanhas);
  assert.equal(cam.lancamento.sessoes, 2); assert.equal(cam.remarketing.sessoes, 1); assert.equal(cam['(sem utm_campaign)'].cliques, 1);
  assert.equal(porNome(r.origens).facebook.cliques, 1); assert.equal(porNome(r.origens).direto.cliques, 1);
  assert.equal(porNome(r.dispositivos).celular.cliques, 2); assert.equal(porNome(r.dispositivos).computador.cliques, 0);
  // sem sessões: tudo zero, sem divisão por zero
  const vazio = await resumo(db, { player: 'inexistente' });
  assert.deepEqual([vazio.cliques, vazio.cliques_pitch, vazio.taxa_clique, vazio.erros, vazio.taxa_erro, vazio.curva_n], [0, 0, 0, 0, 0, 0]);
  assert.deepEqual(vazio.funil, { visitas: 0, plays: 0, pitch: 0, cliques: 0 }); assert.deepEqual(vazio.navegadores, []);
  // 30 plays deixam de ser amostra pequena
  const db2 = criarD1();
  for (let i = 0; i < PLAYS_POUCOS; i++) await registrar(db2, envio('s' + i));
  assert.equal((await resumo(db2)).amostra.pequena, false);
});

test('taxa_clique nunca passa de 100 % e o funil é decrescente: cliques de quem não chegou ao pitch ficam só em `cliques`', async () => {
  const db = criarD1();
  for (let i = 0; i < 32; i++) await registrar(db, envio('p' + i, { maxTime: 10, watched: [[0, 9]] }), UA.safariIos); // plays sem pitch
  await registrar(db, envio('pitch-clicou', { events: [{ type: 'unmute' }, { type: 'cta_click', where: 'end' }] }), UA.safariIos);
  // autoplay mudo foi até o fim e a pessoa clicou no botão da tela final (nunca liberou o som)
  for (let i = 0; i < 2; i++) await registrar(db, envio('muda' + i, { unmuted: false, maxTime: 0, watched: [], events: [{ type: 'cta_click', where: 'end' }] }), UA.safariIos);
  // com som, clicou num botão liberado por tempo antes de chegar ao pitch
  await registrar(db, envio('cedo', { maxTime: 20, watched: [[0, 19]], events: [{ type: 'unmute' }, { type: 'cta_click' }] }), UA.chrome);
  const r = await resumo(db);
  assert.deepEqual([r.plays, r.chegaram_pitch, r.cliques, r.cliques_pitch, r.taxa_clique], [34, 1, 4, 1, 1]);
  assert.deepEqual(r.funil, { visitas: 36, plays: 34, pitch: 1, cliques: 1 });
  assert.ok(r.funil.cliques <= r.funil.pitch && r.funil.pitch <= r.funil.plays && r.funil.plays <= r.funil.visitas, 'funil decrescente');
  const safari = r.navegadores.find((g) => g.nome === 'Safari');
  assert.deepEqual([safari.pitch, safari.cliques, safari.cliques_pitch], [1, 3, 1]);
  assert.equal(r.criativos[0].cliques_pitch, 1); assert.equal(r.campanhas[0].cliques, 4); assert.equal(r.origens[0].cliques_pitch, 1);
});

test('criativos e campanhas: até 12 e o resto em "outras"', async () => {
  const db = criarD1();
  for (let i = 0; i < 15; i++) {
    await registrar(db, envio('s' + i, { url: 'https://site.com/?utm_content=c' + i + '&utm_campaign=k' + i, events: i < 2 ? [{ type: 'cta_click' }] : [] }));
  }
  const r = await resumo(db);
  assert.equal(r.criativos.length, 13); assert.equal(r.criativos[12].nome, 'outras'); assert.equal(r.criativos[12].sessoes, 3);
  assert.equal(r.campanhas.length, 13); assert.equal(r.campanhas[12].nome, 'outras');
  assert.equal(r.criativos.reduce((n, g) => n + g.cliques, 0), 2); assert.equal(r.campanhas.reduce((n, g) => n + g.sessoes, 0), 15);
});

test('filtro navegador= no resumo e no CSV: exato, por parâmetro ligado, Desconhecido = sem navegador', async () => {
  const db = criarD1();
  await registrar(db, envio('a'), UA.instagramIos);
  await registrar(db, envio('b', { visitor: 'vis-2' }), UA.chrome);
  await registrar(db, envio('c', { visitor: 'vis-3' }), UA.webviewWv);
  assert.equal((await resumo(db, { navegador: 'Instagram' })).sessoes, 1);
  assert.equal((await resumo(db, { navegador: 'Chrome WebView' })).sessoes, 1);
  assert.equal((await resumo(db, { navegador: 'Chrome' })).sessoes, 1, 'exato: Chrome não pega Chrome WebView');
  assert.equal((await resumo(db, { navegador: 'chrome' })).sessoes, 0, 'exato: diferencia maiúsculas');
  assert.equal((await resumo(db, { navegador: "x' OR '1'='1" })).sessoes, 0, 'o valor vai como parâmetro, não como SQL');
  assert.equal((await resumo(db, { navegador: 'Desconhecido' })).sessoes, 0);
  const r = await resumo(db, { navegador: 'Instagram', player: 'vsl-principal' });
  assert.equal(r.navegador, 'Instagram'); assert.deepEqual(r.navegadores.map((n) => n.nome), ['Instagram']); assert.equal(r.visitantes, 1);
  assert.equal((await csv(db, { navegador: 'Chrome WebView' })).trim().split('\n').length, 2);
  assert.equal((await csv(db)).trim().split('\n').length, 4);
  assert.equal((await sessoes(db, { navegador: 'Chrome' }))[0].sessao, 'b');
});

test('curva amostrada acima de 2.000 plays: tiles exatos, curva sobre 2.000 lidos só de assistido', async () => {
  const db = criarD1();
  const inserir = (sessao, comSom = 1) => db.prepare('INSERT INTO sessoes (sessao, player, inicio, dia, ultimo, duracao, max_tempo, com_som, assistido, segundos, navegador) '
    + 'VALUES (?,?,?,?,?,?,?,?,?,?,?)').bind(sessao, 'vsl-principal', '2026-10-01T10:00:00Z', '2026-10-01', '2026-10-01T10:00:00Z', 60, 10, comSom, '[[0,9]]', 10, 'Chrome').run();
  for (let i = 0; i < AMOSTRA_CURVA + 1; i++) await inserir('s' + i);
  await inserir('muda', 0);
  await db.prepare('INSERT INTO players (player, pitch, duracao, primeiro, ultimo, sessoes) VALUES (?,?,?,?,?,?)')
    .bind('vsl-principal', 5, 60, '2026-10-01T10:00:00Z', '2026-10-01T10:00:00Z', AMOSTRA_CURVA + 2).run();
  const r = await resumo(db);
  assert.equal(r.sessoes, AMOSTRA_CURVA + 2); assert.equal(r.plays, AMOSTRA_CURVA + 1); assert.equal(r.chegaram_pitch, AMOSTRA_CURVA + 1);
  assert.equal(r.tempo_medio, 10); assert.equal(r.engajamento, Math.round((10 / 60) * 10000) / 10000);
  assert.equal(r.curva_amostrada, true); assert.equal(r.curva_n, AMOSTRA_CURVA);
  assert.deepEqual([r.retencao.pontos[0], r.retencao.pontos[9], r.retencao.pontos[10]], [AMOSTRA_CURVA, AMOSTRA_CURVA, 0], 'a sessão muda fica fora da curva');
  assert.deepEqual(r.amostra, { plays: AMOSTRA_CURVA + 1, pequena: false });
  // com exatamente 2.000 plays a curva é completa
  await db.prepare("DELETE FROM sessoes WHERE sessao = 's0'").run();
  const r2 = await resumo(db);
  assert.equal(r2.curva_amostrada, false); assert.equal(r2.curva_n, AMOSTRA_CURVA); assert.equal(r2.retencao.pontos[0], AMOSTRA_CURVA);
  // o filtro vale para a amostra também
  assert.equal((await resumo(db, { player: 'outro' })).curva_n, 0);
  assert.equal((await resumo(db, { navegador: 'Safari' })).curva_n, 0);
});

test('chaves vindas do visitante não corrompem nada (utm_source=__proto__, eventos constructor/__proto__)', async () => {
  const db = criarD1();
  await registrar(db, envio('a'));
  await registrar(db, envio('b', { url: 'https://site.com/?utm_source=__proto__', events: [{ type: 'constructor' }, { type: '__proto__' }, { type: 'hasOwnProperty' }, { type: 'cta_click' }] }));
  await registrar(db, envio('b', { url: 'https://site.com/?utm_source=__proto__', events: [{ type: '__proto__' }] }));
  await registrar(db, envio('c', { player: 'constructor', pitch: 7 }));
  const r = await resumo(db);
  assert.equal(r.sessoes, 3);
  assert.equal(r.origens.reduce((n, o) => n + o.sessoes, 0), 3, 'a tabela de origens soma todas as sessões');
  assert.ok(r.origens.some((o) => o.nome === '__proto__'));
  const tipos = Object.fromEntries(r.eventos.map((e) => [e.tipo, e.total]));
  assert.equal(tipos.constructor, 1); assert.equal(tipos.__proto__, 2); assert.equal(tipos.hasOwnProperty, 1); assert.equal(tipos.cta_click, 1);
  assert.equal(Object.prototype.sessoes, undefined); assert.equal(Object.prototype.plays, undefined); assert.equal(Object.duracao, undefined);
  assert.equal((await resumo(db, { player: 'constructor' })).pitch, 7);
  const r2 = await resumo(db);
  assert.equal(r2.pitch_misto, true); assert.equal(r2.pitch, null);
});

test('muitos tipos de evento: só os primeiros 50 ficam', async () => {
  const db = criarD1();
  await registrar(db, envio('s1', { events: Array.from({ length: 80 }, (_, i) => ({ type: 'tipo' + i })) }));
  await registrar(db, envio('s1', { events: Array.from({ length: 80 }, (_, i) => ({ type: 'outro' + i })) }));
  assert.ok((await resumo(db)).eventos.length <= 50);
});

test('envios simultâneos da mesma sessão não dão erro nem perdem dados', async () => {
  const db = criarD1();
  await Promise.all([
    registrar(db, envio('s1', { watched: [[0, 9]], maxTime: 10, events: [{ type: 'unmute' }] })),
    registrar(db, envio('s1', { watched: [[10, 19]], maxTime: 20, events: [{ type: 'pitch' }, { type: 'ended' }] })),
    registrar(db, envio('s1', { watched: [[20, 29]], maxTime: 30, events: [{ type: 'pause' }] })),
  ]);
  const [s] = await sessoes(db);
  assert.deepEqual(JSON.parse(s.assistido), [[0, 29]]);
  assert.equal(s.max_tempo, 30); assert.equal(s.terminou, 1);
  assert.deepEqual(JSON.parse(s.eventos), { unmute: 1, pitch: 1, ended: 1, pause: 1 });
  assert.equal((await players(db))[0].sessoes, 1);
});

test('tabela players: contagem, pitch e duração mais recentes, e preenchimento de bancos antigos', async () => {
  const db = criarD1();
  await registrar(db, envio('a', { duration: 0, pitch: 30 }), '', FUSO, em('2026-10-01T13:00:00Z'));
  await registrar(db, envio('a', { duration: 600 }), '', FUSO, em('2026-10-01T13:00:10Z'));
  await registrar(db, envio('b', { duration: 120, pitch: 45 }), '', FUSO, em('2026-10-02T13:00:00Z'));
  let [p] = await players(db);
  assert.equal(p.sessoes, 2); assert.equal(p.pitch, 45); assert.equal(p.duracao, 120); assert.equal(p.primeiro, '2026-10-01T13:00:00Z');
  // banco antigo: apaga a tabela players e vê se ela é reconstruída a partir das sessões
  await db.prepare('DELETE FROM players').run();
  [p] = await players(db);
  assert.equal(p.sessoes, 2); assert.equal(p.pitch, 45); assert.equal(p.duracao, 120);
});

// ---------------------------------------------------------------- HTTP

function app(opcoes = {}) {
  const env = { DB: criarD1(), TOKEN: 'segredo', FUSO, ...opcoes };
  const a = criarApp({ painel: '<title>Retenção do VSL</title><p>painel</p>' });
  return { env, pedir: (metodo, caminho, corpo, headers) => a.fetch(new Request('http://x' + caminho, { method: metodo, body: corpo, headers }), env) };
}

test('coleta aceita text/plain com CORS e o resumo reflete o envio', async () => {
  const { pedir } = app();
  let r = await pedir('POST', '/vsl', JSON.stringify(envio()), { 'Content-Type': 'text/plain;charset=UTF-8', 'User-Agent': 'Mozilla/5.0 (Android 14; Mobile)' });
  assert.equal(r.status, 204); assert.equal(r.headers.get('Access-Control-Allow-Origin'), '*');
  r = await pedir('OPTIONS', '/vsl');
  assert.equal(r.status, 204); assert.ok(r.headers.get('Access-Control-Allow-Methods').includes('POST'));
  r = await pedir('GET', '/api/resumo?player=vsl-principal', null, { 'X-Token': 'segredo' });
  const resumoJson = await r.json();
  assert.equal(r.status, 200); assert.equal(resumoJson.sessoes, 1); assert.equal(resumoJson.dispositivos[0].nome, 'celular');
});

test('coleta recusa envios ruins', async () => {
  const { pedir } = app();
  assert.equal((await pedir('POST', '/vsl', '{nao e json')).status, 400);
  assert.equal((await pedir('POST', '/vsl', '{"player": "p"}')).status, 400);
  assert.equal((await pedir('POST', '/vsl', '')).status, 400);
  assert.equal((await pedir('POST', '/vsl')).status, 400, 'POST sem corpo dá 400, não 500');
  assert.equal((await pedir('POST', '/vsl', 'é'.repeat(LIMITE_CORPO / 2 + 10))).status, 413, 'o limite conta bytes, não caracteres');
  assert.equal((await pedir('POST', '/vsl', 'x'.repeat(LIMITE_CORPO + 1))).status, 413);
  assert.equal((await pedir('POST', '/vsl', 'x', { 'Content-Length': String(LIMITE_CORPO + 1) })).status, 413);
  assert.equal((await pedir('POST', '/outro', '{}')).status, 404);
  const absurdo = '{"player":"p","session":"s","duration":1e300,"watched":[[0,1e300]],"events":[{"type":"a","ts":1e300}]}';
  assert.equal((await pedir('POST', '/vsl', absurdo)).status, 204);
  const fundo = '{"player":"p","session":"s","events":[' + '['.repeat(100000) + ']'.repeat(100000) + ']}';
  assert.ok([204, 400].includes((await pedir('POST', '/vsl', fundo)).status)); // não trava nem dá 500
});

test('painel é público; API e CSV pedem token; parâmetros inválidos dão 400', async () => {
  const { pedir } = app();
  assert.equal((await pedir('GET', '/api/resumo')).status, 401);
  assert.equal((await pedir('GET', '/api/resumo', null, { 'X-Token': 'errado' })).status, 401);
  assert.equal((await pedir('GET', '/api/resumo', null, { 'X-Token': 'segredo' })).status, 200);
  assert.equal((await pedir('GET', '/api/resumo', null, { Authorization: 'Bearer segredo' })).status, 200);
  assert.equal((await pedir('GET', '/api/resumo?token=segredo')).status, 401, 'token na query string não vale (iria para os logs)');
  let r = await pedir('GET', '/');
  assert.equal(r.status, 200); assert.ok(r.headers.get('Content-Type').includes('text/html')); assert.ok((await r.text()).includes('Reten'));
  assert.equal((await pedir('GET', '/api/sessoes.csv')).status, 401);
  r = await pedir('GET', '/api/sessoes.csv?player=../x"y;%20z%C3%A7', null, { 'X-Token': 'segredo' });
  assert.equal(r.status, 200); assert.equal(r.headers.get('Content-Disposition'), 'attachment; filename="sessoes-.._x_y_z.csv"');
  assert.ok((await r.text()).startsWith('sessao;')); // o BOM vai no corpo, mas text() o remove
  r = await pedir('GET', '/api/config');
  assert.deepEqual(await r.json(), { token: true, versao: '1.0.0', hoje: hojeNoFuso(FUSO), fuso: FUSO });
  assert.equal((await pedir('GET', '/saude')).status, 200);
  assert.equal((await pedir('GET', '/nada')).status, 404);
  assert.equal((await pedir('GET', '/painel.html')).status, 404);
  r = await pedir('HEAD', '/api/resumo', null, { 'X-Token': 'segredo' });
  assert.equal(r.status, 200); assert.equal(await r.text(), '');
  const cab = { 'X-Token': 'segredo' };
  assert.equal((await pedir('GET', '/api/resumo?de=2026-13-01', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?ate=ontem', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?pitch=abc', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?periodo=x', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?periodo=constructor', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?periodo=__proto__', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?periodo=7&pitch=12.5', null, cab)).status, 200);
  assert.equal((await pedir('GET', '/api/sessoes.csv?de=2026-99-99', null, cab)).status, 400);
  assert.equal((await pedir('PUT', '/vsl', '{}')).status, 405);
});

test('sem TOKEN configurado o painel e a API ficam abertos', async () => {
  const { pedir } = app({ TOKEN: '' });
  assert.equal((await pedir('GET', '/api/resumo')).status, 200);
  assert.equal((await (await pedir('GET', '/api/config')).json()).token, false);
});

test('o esquema é criado sozinho na primeira requisição quando a migração não rodou', async () => {
  const db = criarD1([]); // sem tabela nenhuma
  const a = criarApp({ painel: '<p>painel</p>', esquema: lerMigracoes() });
  const env = { DB: db, TOKEN: '', FUSO };
  const r = await a.fetch(new Request('http://x/vsl', { method: 'POST', body: JSON.stringify(envio()), headers: { 'User-Agent': UA.samsung } }), env);
  assert.equal(r.status, 204);
  const j = await (await a.fetch(new Request('http://x/api/resumo'), env)).json();
  assert.equal(j.sessoes, 1); assert.equal(j.navegadores[0].nome, 'Samsung');
  const colunas = (await db.prepare('PRAGMA table_info(sessoes)').all()).results.map((c) => c.name);
  assert.ok(colunas.includes('navegador'));
});

test('migração 0003 idempotente: banco já migrado, duas instâncias do Worker, D1 sem PRAGMA e comando repetido', async () => {
  const esquema = lerMigracoes();
  const db = criarD1(); // já rodou todas as migrações (wrangler d1 migrations apply): o ALTER TABLE não pode quebrar
  const env = { DB: db, TOKEN: '', FUSO };
  const pedir = (a, caminho, corpo) => a.fetch(new Request('http://x' + caminho, corpo ? { method: 'POST', body: corpo } : {}), env);
  const a1 = criarApp({ painel: '<p>painel</p>', esquema });
  assert.equal((await pedir(a1, '/vsl', JSON.stringify(envio('s1')))).status, 204);
  const a2 = criarApp({ painel: '<p>painel</p>', esquema }); // outra instância (isolate) no mesmo banco
  assert.equal((await pedir(a2, '/vsl', JSON.stringify(envio('s2')))).status, 204);
  assert.equal((await (await pedir(a2, '/api/resumo')).json()).sessoes, 2);
  const colunas = (await db.prepare('PRAGMA table_info(sessoes)').all()).results.filter((c) => c.name === 'navegador');
  assert.equal(colunas.length, 1, 'a coluna existe uma vez só');
  // D1 sem PRAGMA: sobra o erro "duplicate column", que é ignorado
  let pragmas = 0;
  const semPragma = { prepare(sql) { if (/^PRAGMA/i.test(sql)) { pragmas += 1; throw new Error('PRAGMA nao suportado'); } return db.prepare(sql); } };
  const a3 = criarApp({ painel: '<p>painel</p>', esquema });
  assert.equal((await a3.fetch(new Request('http://x/vsl', { method: 'POST', body: JSON.stringify(envio('s3')) }), { ...env, DB: semPragma })).status, 204);
  assert.equal(pragmas, 1);
  // rodarComandoDoEsquema direto, três vezes seguidas, num banco cru
  const cru = criarD1([]);
  const comandos = esquema.split(';').map((c) => c.replace(/--[^\n]*/g, '').trim()).filter(Boolean);
  for (let vez = 0; vez < 3; vez++) for (const c of comandos) await rodarComandoDoEsquema(cru, c);
  assert.equal((await cru.prepare('PRAGMA table_info(sessoes)').all()).results.filter((c) => c.name === 'navegador').length, 1);
  // outro erro no ALTER não é engolido
  await assert.rejects(rodarComandoDoEsquema(cru, 'ALTER TABLE inexistente ADD COLUMN x TEXT'), /no such table/);
});

test('banco antigo: a migração 0003 acrescenta a coluna e as sessões de antes viram "Desconhecido" (filtrável)', async () => {
  const db = criarD1(['0001_inicial.sql', '0002_players_e_indice.sql']);
  await db.prepare("INSERT INTO sessoes (sessao, player, inicio, dia, ultimo, duracao, max_tempo, com_som, assistido, segundos) "
    + "VALUES ('velha', 'vsl-principal', '2026-10-01T10:00:00Z', '2026-10-01', '2026-10-01T10:00:00Z', 120, 40, 1, '[[0,39]]', 40)").run();
  const a = criarApp({ painel: '<p>painel</p>', esquema: lerMigracoes() });
  const env = { DB: db, TOKEN: '', FUSO };
  const r = await a.fetch(new Request('http://x/vsl', { method: 'POST', body: JSON.stringify(envio('nova')), headers: { 'User-Agent': UA.instagramIos } }), env);
  assert.equal(r.status, 204);
  const j = await (await a.fetch(new Request('http://x/api/resumo'), env)).json();
  assert.deepEqual(j.navegadores.map((n) => [n.nome, n.sessoes]), [['Desconhecido', 1], ['Instagram', 1]]);
  const f = await (await a.fetch(new Request('http://x/api/resumo?navegador=Desconhecido'), env)).json();
  assert.equal(f.sessoes, 1); assert.equal(f.navegador, 'Desconhecido'); assert.equal(f.navegadores[0].nome, 'Desconhecido');
  const linhas = (await (await a.fetch(new Request('http://x/api/sessoes.csv?navegador=Desconhecido'), env)).text()).trim().split('\n');
  assert.equal(linhas.length, 2); assert.ok(linhas[1].startsWith('velha;')); assert.ok(linhas[1].endsWith(';;2026-10-01'));
});

test('API: navegador= validado (até 40 caracteres), aplicado no resumo e no CSV', async () => {
  const { env, pedir } = app();
  const cab = { 'X-Token': 'segredo' };
  await registrar(env.DB, envio('a'), UA.instagramIos);
  await registrar(env.DB, envio('b'), UA.webviewWv);
  let r = await pedir('GET', '/api/resumo?navegador=Instagram', null, cab);
  const j = await r.json();
  assert.equal(r.status, 200); assert.equal(j.sessoes, 1); assert.equal(j.navegador, 'Instagram'); assert.equal(j.navegadores[0].nome, 'Instagram');
  for (const campo of ['cliques', 'cliques_pitch', 'taxa_clique', 'erros', 'taxa_erro', 'funil', 'amostra', 'curva_amostrada', 'curva_n', 'navegadores', 'criativos', 'campanhas']) {
    assert.ok(campo in j, campo);
  }
  r = await pedir('GET', '/api/sessoes.csv?navegador=Chrome%20WebView', null, cab);
  const linhas = (await r.text()).trim().split('\n');
  assert.equal(r.status, 200); assert.equal(linhas.length, 2); assert.ok(linhas[1].includes(';Chrome WebView;'));
  assert.equal((await (await pedir('GET', '/api/resumo', null, cab)).json()).navegador, null);
  assert.equal((await pedir('GET', '/api/resumo?navegador=' + 'a'.repeat(MAX_NAVEGADOR), null, cab)).status, 200);
  assert.equal((await pedir('GET', '/api/resumo?navegador=' + 'a'.repeat(MAX_NAVEGADOR + 1), null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?navegador=%20%20', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/sessoes.csv?navegador=' + 'a'.repeat(MAX_NAVEGADOR + 1), null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?navegador=' + encodeURIComponent("x' OR 1=1 --"), null, cab)).status, 200);
  assert.equal((await (await pedir('GET', '/api/resumo?navegador=' + encodeURIComponent("x' OR 1=1 --"), null, cab)).json()).sessoes, 0);
});

test('o painel do Worker é o mesmo arquivo do servidor Python', async () => {
  const fs = await import('node:fs');
  const aqui = fs.readFileSync(new URL('../painel.html', import.meta.url), 'utf8');
  const original = fs.readFileSync(new URL('../../painel.html', import.meta.url), 'utf8');
  assert.equal(aqui, original, 'rode: cp ../painel.html painel.html dentro de player/analytics/cloudflare');
});
