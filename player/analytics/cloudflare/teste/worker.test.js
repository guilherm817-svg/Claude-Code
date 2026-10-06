// Testes do Worker (node --test). Rodam sem a Cloudflare: o D1 é imitado com o node:sqlite.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { criarD1 } from './d1.js';
import {
  criarApp, registrar, resumo, players, sessoes, csv, unirFaixas, curvaRetencao, compactarCurva, origem, dispositivo,
  validarEnvio, pitchValido, periodoParaDatas, hojeNoFuso, numero, MAX_SEGUNDOS, PONTOS_CURVA, LIMITE_CORPO, MAX_EVENTOS,
} from '../src/app.js';

const FUSO = 'America/Sao_Paulo';
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
  r = await pedir('GET', '/api/resumo?token=segredo&player=vsl-principal');
  const resumoJson = await r.json();
  assert.equal(r.status, 200); assert.equal(resumoJson.sessoes, 1); assert.equal(resumoJson.dispositivos[0].nome, 'celular');
});

test('coleta recusa envios ruins', async () => {
  const { pedir } = app();
  assert.equal((await pedir('POST', '/vsl', '{nao e json')).status, 400);
  assert.equal((await pedir('POST', '/vsl', '{"player": "p"}')).status, 400);
  assert.equal((await pedir('POST', '/vsl', '')).status, 400);
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
  let r = await pedir('GET', '/');
  assert.equal(r.status, 200); assert.ok(r.headers.get('Content-Type').includes('text/html')); assert.ok((await r.text()).includes('Reten'));
  assert.equal((await pedir('GET', '/api/sessoes.csv')).status, 401);
  r = await pedir('GET', '/api/sessoes.csv?token=segredo&player=../x"y;%20z%C3%A7');
  assert.equal(r.status, 200); assert.equal(r.headers.get('Content-Disposition'), 'attachment; filename="sessoes-.._x_y_z.csv"');
  assert.ok((await r.text()).startsWith('sessao;')); // o BOM vai no corpo, mas text() o remove
  r = await pedir('GET', '/api/config');
  assert.deepEqual(await r.json(), { token: true, versao: '1.0.0', hoje: hojeNoFuso(FUSO), fuso: FUSO });
  assert.equal((await pedir('GET', '/saude')).status, 200);
  assert.equal((await pedir('GET', '/nada')).status, 404);
  assert.equal((await pedir('GET', '/painel.html')).status, 404);
  r = await pedir('HEAD', '/api/resumo?token=segredo');
  assert.equal(r.status, 200); assert.equal(await r.text(), '');
  const cab = { 'X-Token': 'segredo' };
  assert.equal((await pedir('GET', '/api/resumo?de=2026-13-01', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?ate=ontem', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?pitch=abc', null, cab)).status, 400);
  assert.equal((await pedir('GET', '/api/resumo?periodo=x', null, cab)).status, 400);
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
  const fs = await import('node:fs');
  const { DatabaseSync } = await import('node:sqlite');
  const esquema = fs.readFileSync(new URL('../migrations/0001_inicial.sql', import.meta.url), 'utf8');
  const bruto = new DatabaseSync(':memory:'); // sem tabela nenhuma
  const db = {
    prepare(sql) { const st = bruto.prepare(sql); const stmt = { args: [], bind(...a) { stmt.args = a.map((x) => (x === undefined ? null : x)); return stmt; },
      async first() { const r = st.get(...stmt.args); return r == null ? null : { ...r }; }, async all() { return { results: st.all(...stmt.args).map((r) => ({ ...r })) }; },
      async run() { st.run(...stmt.args); return { success: true }; } }; return stmt; },
    async exec(sql) { bruto.exec(sql); },
  };
  const a = criarApp({ painel: '<p>painel</p>', esquema });
  const env = { DB: db, TOKEN: '', FUSO };
  const r = await a.fetch(new Request('http://x/vsl', { method: 'POST', body: JSON.stringify(envio()) }), env);
  assert.equal(r.status, 204);
  assert.equal((await (await a.fetch(new Request('http://x/api/resumo'), env)).json()).sessoes, 1);
});

test('o painel do Worker é o mesmo arquivo do servidor Python', async () => {
  const fs = await import('node:fs');
  const aqui = fs.readFileSync(new URL('../painel.html', import.meta.url), 'utf8');
  const original = fs.readFileSync(new URL('../../painel.html', import.meta.url), 'utf8');
  assert.equal(aqui, original, 'rode: cp ../painel.html painel.html dentro de player/analytics/cloudflare');
});
