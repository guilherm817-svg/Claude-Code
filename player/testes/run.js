// Teste do VSL Player num Chromium de verdade. Rode: node run.js (precisa de playwright e ffmpeg).
const { chromium } = require('playwright');
const { spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const DIR = __dirname;                 // player/testes
const ROOT = path.dirname(DIR);        // player
const VIDEO = path.join(DIR, 'teste.webm');
const PORT = 8700 + Math.floor(Math.random() * 200); // porta aleatória: não briga com servidores esquecidos
const BASE = `http://127.0.0.1:${PORT}/testes`;
const CAPTURAS = path.join(DIR, 'capturas');

// Vídeo de 30 s em WebM (o Chromium do Playwright não decodifica H.264). As páginas de teste são montadas
// a partir de pagina.html e servidas da memória: nada além do vídeo e das capturas é gravado em disco.
let modelo = '';
function preparar() {
  if (!fs.existsSync(VIDEO)) {
    const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=duration=30:size=640x360:rate=25',
      '-f', 'lavfi', '-i', 'sine=frequency=440:duration=30', '-c:v', 'libvpx-vp9', '-b:v', '400k', '-deadline', 'realtime',
      '-cpu-used', '8', '-c:a', 'libopus', VIDEO], { stdio: 'inherit' });
    if (r.status !== 0) throw new Error('ffmpeg falhou ao gerar teste.webm');
  }
  modelo = fs.readFileSync(path.join(DIR, 'pagina.html'), 'utf8');
  fs.mkdirSync(CAPTURAS, { recursive: true });
}
const PAGINAS = {}; // nome.html -> html (servido em /testes/<nome>.html)
function pagina(nome, o = {}) {
  PAGINAS[nome + '.html'] = modelo
    .replace('__SRC__', () => o.src || 'teste.webm').replace('__PITCH__', () => o.pitch || '5')
    .replace('__ANALYTICS__', () => o.analytics || '').replace('__AUTOPLAY__', () => o.autoplay || 'true')
    .replace('__ATTRS__', () => o.attrs || '').replace('__ATTRS2__', () => o.attrs2 || '')
    .replace('__HEAD__', () => o.head || '').replace('__EXTRA__', () => o.extra || '');
  return `${BASE}/${nome}.html`;
}

// Shim de window.Hls (não há hls.js local): liga o webm ao <video>, anuncia MANIFEST_PARSED com níveis
// e deixa simular erro fatal com instancia.erroFatal(tipo). Serve tanto injetado pelo player quanto inline.
const SHIM = `(function () {
  var ctl = window.__hlsShim = window.__hlsShim || {};
  ctl.instancias = [];
  ctl.video = ctl.video || 'teste.webm';
  ctl.levels = ctl.levels || [{ width: 640, height: 360 }, { width: 854, height: 480 }, { width: 1280, height: 720 }, { width: 1920, height: 1080 }];
  function Hls(config) { this.config = config || {}; this.startLevel = this.config.startLevel; this.levels = ctl.levels; this.chamadas = []; this._h = {}; ctl.instancias.push(this); }
  Hls.isSupported = function () { return ctl.suportado !== false; };
  Hls.Events = { MANIFEST_PARSED: 'hlsManifestParsed', ERROR: 'hlsError' };
  Hls.ErrorTypes = { NETWORK_ERROR: 'networkError', MEDIA_ERROR: 'mediaError', OTHER_ERROR: 'otherError' };
  Hls.prototype.on = function (ev, fn) { (this._h[ev] = this._h[ev] || []).push(fn); };
  Hls.prototype.trigger = function (ev, data) { (this._h[ev] || []).slice().forEach(function (fn) { fn(ev, data); }); };
  Hls.prototype.loadSource = function (url) { this.chamadas.push('loadSource'); this.url = url; var self = this; setTimeout(function () { self.trigger(Hls.Events.MANIFEST_PARSED, { levels: self.levels }); }, 0); };
  Hls.prototype.attachMedia = function (video) { this.chamadas.push('attachMedia'); this.media = video; video.src = ctl.video; };
  Hls.prototype.startLoad = function () { this.chamadas.push('startLoad'); };
  Hls.prototype.recoverMediaError = function () { this.chamadas.push('recoverMediaError'); };
  Hls.prototype.destroy = function () { this.chamadas.push('destroy'); this.destruida = true; };
  Hls.prototype.erroFatal = function (tipo) { this.trigger(Hls.Events.ERROR, { type: tipo, details: tipo + 'Details', fatal: true }); };
  window.Hls = Hls;
})();`;

let failures = 0;
function check(cond, msg, extra) {
  if (cond) console.log('  PASS', msg);
  else { failures++; console.log('  FAIL', msg, extra !== undefined ? JSON.stringify(extra) : ''); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Servidor estático mínimo para a pasta player/, com suporte a Range (o <video> precisa) e alguns
// vídeos "difíceis": quebrado.webm (404 até ctl.quebrado virar false), lento.webm (demora ctl.delayVideoMs
// para responder, ou chega a ctl.lentoKBs KB/s com Range, como uma CDN numa rede lenta) e preso.webm (não responde
// enquanto ctl.preso; soltar() libera; derrubar() corta as respostas em andamento). Com ctl.semRange o servidor
// ignora o Range e manda o arquivo inteiro (como um servidor simples ou um cache frio): aí o load() de uma
// retentativa volta à rede em vez de usar o que o Chromium já tinha.
const TIPOS = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.webm': 'video/webm', '.mp4': 'video/mp4', '.png': 'image/png', '.jpg': 'image/jpeg' };
const ctl = { quebrado: true, pedidosQuebrado: 0, delayVideoMs: 0, preso: false, semRange: false, lentoKBs: 0, ativos: new Set() };
const presos = [];
function soltar() { while (presos.length) presos.shift()(); }
// A rede caiu: derruba as respostas em andamento e prende as próximas (soltar() libera).
function derrubar() { ctl.preso = true; ctl.ativos.forEach((r) => r.destroy()); ctl.ativos.clear(); }
function servidor() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const url = decodeURIComponent(req.url.split('?')[0]);
      const nome = url.startsWith('/testes/') ? url.slice(8) : '';
      if (PAGINAS[nome]) { res.writeHead(200, { 'Content-Type': TIPOS['.html'], 'Cache-Control': 'no-store' }); res.end(PAGINAS[nome]); return; }
      if (nome === 'hls-shim.js') { res.writeHead(200, { 'Content-Type': TIPOS['.js'], 'Cache-Control': 'no-store' }); res.end(SHIM); return; }
      if (nome === 'video.m3u8') { res.writeHead(200, { 'Content-Type': 'application/vnd.apple.mpegurl' }); res.end('#EXTM3U\n#EXT-X-ENDLIST\n'); return; }
      let alvo = path.normalize(path.join(ROOT, url));
      if (nome === 'quebrado.webm') { ctl.pedidosQuebrado++; if (ctl.quebrado) { res.writeHead(404); res.end(); return; } alvo = VIDEO; }
      if (nome === 'lento.webm' || nome === 'preso.webm') alvo = VIDEO;
      if (!alvo.startsWith(ROOT) || !fs.existsSync(alvo) || fs.statSync(alvo).isDirectory()) { res.writeHead(404); res.end(); return; }
      const tamanho = fs.statSync(alvo).size;
      const tipo = TIPOS[path.extname(alvo)] || 'application/octet-stream';
      const enviar = () => {
        const range = ctl.semRange ? null : /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
        if (range) {
          const inicio = range[1] ? parseInt(range[1], 10) : Math.max(0, tamanho - parseInt(range[2], 10));
          const fim = range[1] && range[2] ? Math.min(parseInt(range[2], 10), tamanho - 1) : tamanho - 1;
          if (nome === 'lento.webm' && ctl.lentoKBs) {
            // Range, mas devagar (e sem cache): o Chromium fica com o buffer perto do playhead, e o load() de uma
            // retentativa precisa voltar à rede para a posição guardada.
            res.writeHead(206, { 'Content-Type': tipo, 'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${inicio}-${fim}/${tamanho}`, 'Content-Length': fim - inicio + 1, 'Cache-Control': 'no-store' });
            ctl.ativos.add(res); res.on('close', () => ctl.ativos.delete(res));
            const fd = fs.openSync(alvo, 'r'); let pos = inicio; const passo = 16384;
            const tick = () => {
              if (res.destroyed || pos > fim) { fs.closeSync(fd); if (!res.destroyed) res.end(); return; }
              const n = Math.min(passo, fim - pos + 1); const buf = Buffer.alloc(n); fs.readSync(fd, buf, 0, n, pos); pos += n; res.write(buf);
              setTimeout(tick, ctl.lentoKBs ? passo / (ctl.lentoKBs * 1024) * 1000 : 0);
            };
            tick();
            return;
          }
          res.writeHead(206, { 'Content-Type': tipo, 'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${inicio}-${fim}/${tamanho}`, 'Content-Length': fim - inicio + 1 });
          fs.createReadStream(alvo, { start: inicio, end: fim }).pipe(res);
          return;
        }
        res.writeHead(200, Object.assign({ 'Content-Type': tipo, 'Content-Length': tamanho, 'Cache-Control': 'no-store' }, ctl.semRange ? {} : { 'Accept-Ranges': 'bytes' }));
        fs.createReadStream(alvo).pipe(res);
      };
      if (nome === 'lento.webm' && ctl.delayVideoMs) setTimeout(enviar, ctl.delayVideoMs);
      else if ((nome === 'preso.webm' || nome === 'lento.webm') && ctl.preso) presos.push(enviar);
      else enviar();
    });
    srv.listen(PORT, '127.0.0.1', () => resolve(srv));
  });
}
const state = (page, id = '#vsl-teste') => page.getAttribute(id, 'data-state');
const vid = (page, expr, id = 'vsl-teste') => page.evaluate(([id, expr]) => { const v = document.getElementById(id).querySelector('video'); return eval(expr); }, [id, expr]);
const player = (page, expr, id = 'vsl-teste') => page.evaluate(([id, expr]) => { const player = VSLPlayer.get(id); return eval(expr); }, [id, expr]);
const eventos = (page) => page.evaluate(() => window.eventos.map((e) => e.nome));
const evento = (page, nome) => page.evaluate((nome) => window.eventos.find((e) => e.nome === nome) || null, nome);
const amostra = (page) => page.evaluate(() => { const r = document.getElementById('vsl-teste'); const v = r.querySelector('video'); return { state: r.getAttribute('data-state'), paused: v.paused, buffering: r.classList.contains('vsl-buffering'), time: +v.currentTime.toFixed(2) }; });
const infoHls = (page) => page.evaluate(() => { const s = window.__hlsShim; const h = s && s.instancias[0]; return { scripts: document.querySelectorAll('script[data-vsl-hls]').length, instancias: s ? s.instancias.length : 0, startLevel: h && h.startLevel, config: h && h.config, src: document.querySelector('#vsl-teste video').currentSrc }; });
const chamadas = (page, i) => page.evaluate((i) => window.__hlsShim.instancias[i].chamadas, i);
const fmt = (s) => Math.floor(s / 60) + ':' + String(Math.floor(s % 60)).padStart(2, '0');
async function waitState(page, s, timeout = 8000, id = 'vsl-teste') {
  await page.waitForFunction(([id, s]) => document.getElementById(id).getAttribute('data-state') === s, [id, s], { timeout });
}
async function waitTime(page, t, timeout = 15000) {
  await page.waitForFunction((t) => document.getElementById('vsl-teste').querySelector('video').currentTime >= t, t, { timeout });
}
// Erros de página derrubam o teste. Erros de console também, exceto os 404 esperados (recursos: false).
function vigiar(page, { recursos = true } = {}) {
  page.on('pageerror', (e) => { failures++; console.log('  PAGEERROR', e.message); });
  page.on('console', (m) => {
    if (m.type() !== 'error') return;
    if (!recursos && /Failed to load resource/.test(m.text())) return;
    failures++; console.log('  CONSOLE ERROR', m.text());
  });
}
const CANTO = { position: { x: 12, y: 12 } }; // clique longe do CTA (que fica no centro ou nos cantos de baixo)

(async () => {
  preparar();
  const server = await servidor();
  const viewport = { width: 1000, height: 800 };
  try {
    const browser = await chromium.launch();

    // ---------------------------------------------------------------- A. visita nova, autoplay permitido
    console.log('\nA. Visita nova: autoplay mudo, clique para ouvir, pausa, delay de elementos, travas');
    const ctx = await browser.newContext({ viewport });
    let page = await ctx.newPage();
    vigiar(page);
    await page.goto(pagina('t1'));
    await waitState(page, 'autoplaying');
    check(await vid(page, 'v.muted') === true, 'autoplay começa mudo');
    check(await vid(page, '!v.paused'), 'vídeo está tocando no autoplay');
    check(await page.isVisible('#vsl-teste .vsl-unmute'), 'overlay "clique para ouvir" visível');
    check((await page.$('#vsl-teste .vsl-unmute > button.vsl-box[type="button"]')) !== null, 'aviso de autoplay é um <button class="vsl-box"> acessível');
    check((await page.getAttribute('#vsl-teste .vsl-unmute button', 'aria-label')) === 'Seu vídeo já começou. Clique para ouvir', 'aria-label do aviso junta título e subtítulo');
    check((await page.textContent('#vsl-teste .vsl-paused strong')) === 'Continuar assistindo', 'texto de pausa novo: "Continuar assistindo"');
    check((await page.textContent('#vsl-teste .vsl-ended strong')) === 'Assistir de novo', 'texto de fim novo: "Assistir de novo"');
    check(!(await page.isVisible('#cta')), 'elemento com data-vsl-show-at começa escondido');
    check(await page.isVisible('#aviso'), 'elemento com data-vsl-hide-at começa visível');
    check(!(await page.isVisible('#cta2')), 'elemento do segundo player começa escondido');
    await page.screenshot({ path: path.join(CAPTURAS, '01-autoplaying.png') });
    await waitTime(page, 2);
    await page.click('#vsl-teste .vsl-unmute button');
    await waitState(page, 'playing');
    check(await vid(page, 'v.muted') === false, 'ao clicar no aviso, vídeo fica com som');
    check((await vid(page, 'v.currentTime')) < 1.5, 'ao clicar, vídeo recomeça do início', await vid(page, 'v.currentTime'));
    await page.waitForSelector('#vsl-teste .vsl-unmute', { state: 'hidden', timeout: 3000 }).then(() => check(true, 'overlay some depois do clique'), () => check(false, 'overlay some depois do clique'));
    let ev = await eventos(page);
    check(ev.includes('autoplay') && ev.includes('unmute') && ev.includes('play'), 'eventos autoplay, unmute e play disparados', ev);
    await waitTime(page, 2.5);
    const width = await page.evaluate(() => parseFloat(document.querySelector('#vsl-teste .vsl-progress-bar').style.width));
    const t = await vid(page, 'v.currentTime');
    const esperado = (1 - Math.pow(1 - t / 30, 2.2)) * 100;
    check(width > t / 30 * 100 && Math.abs(width - esperado) < 6, 'barra de progresso inteligente anda mais rápido que o tempo real', { width, t, esperado });
    await waitTime(page, 5.2);
    await sleep(300);
    check(await page.isVisible('#cta'), 'elemento data-vsl-show-at="5" apareceu aos 5s');
    check(!(await page.isVisible('#aviso')), 'elemento data-vsl-hide-at="5" sumiu aos 5s');
    ev = await eventos(page);
    check(ev.filter((n) => n === 'reach').length === 2, 'dois eventos reach (show e hide)', ev);
    check(ev.includes('pitch'), 'evento pitch disparado aos 5s (com som e aba visível)');
    const pitchA = await evento(page, 'pitch');
    check(pitchA && pitchA.detail.at === 5 && pitchA.detail.muted === false && pitchA.detail.time >= 5, 'detalhe do pitch: { at, time, muted: false }', pitchA);
    check(ev.includes('milestone'), 'evento milestone disparado (10%)');
    // travas
    await vid(page, 'v.playbackRate = 2');
    await sleep(200);
    check((await vid(page, 'v.playbackRate')) === 1, 'velocidade travada em 1x');
    const antes = await vid(page, 'v.currentTime');
    await vid(page, 'v.currentTime = 25');
    await sleep(800);
    const depois = await vid(page, 'v.currentTime');
    check(depois < antes + 3, 'pulo pelo console é bloqueado', { antes, depois });
    check((await eventos(page)).includes('seek_blocked'), 'evento seek_blocked disparado');
    // pausa
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'paused');
    check(await vid(page, 'v.paused'), 'clique pausa o vídeo');
    await page.waitForSelector('#vsl-teste .vsl-paused', { state: 'visible', timeout: 3000 }).then(() => check(true, 'overlay de pausa visível'), () => check(false, 'overlay de pausa visível'));
    check((await page.getAttribute('#vsl-teste', 'data-pause-poster')) === null, 'sem data-pause-poster-late não há miniatura de pausa');
    await sleep(400);
    await page.screenshot({ path: path.join(CAPTURAS, '02-paused.png') });
    const pos = await page.evaluate(() => parseFloat(localStorage.getItem('vsl:vsl-teste:pos')));
    check(pos > 5, 'posição salva no localStorage ao pausar', pos);
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    check(await vid(page, '!v.paused'), 'clique retoma o vídeo');
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'paused');
    const posSalva = await page.evaluate(() => parseFloat(localStorage.getItem('vsl:vsl-teste:pos')));
    // segundo player (autoplay off) e elemento com escopo
    check((await state(page, '#vsl-segundo')) === 'idle', 'segundo player com autoplay=false fica em idle');
    await page.click('#vsl-segundo');
    await waitState(page, 'playing', 8000, 'vsl-segundo');
    check(await vid(page, 'v.muted', 'vsl-segundo') === false, 'segundo player toca com som ao clicar');
    await page.waitForFunction(() => document.getElementById('vsl-segundo').querySelector('video').currentTime >= 2.2);
    await sleep(300);
    check(await page.isVisible('#cta2'), 'elemento com data-vsl-player aparece pelo segundo player');
    await page.click('#vsl-segundo');

    // ---------------------------------------------------------------- B. volta: continuar de onde parou
    console.log('\nB. Segunda visita: elementos persistidos e "continuar de onde parou"');
    await page.goto(pagina('t1'));
    await waitState(page, 'autoplaying');
    check(await page.isVisible('#cta'), 'elemento show-at já aparece ao recarregar (persistido)');
    check(!(await page.isVisible('#aviso')), 'elemento hide-at continua escondido ao recarregar');
    check(!(await eventos(page)).includes('pitch'), 'pitch não dispara de novo para o mesmo visitante');
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'modal');
    check(await vid(page, 'v.paused'), 'vídeo pausa enquanto a pergunta está aberta');
    await page.waitForSelector('#vsl-teste .vsl-card', { state: 'visible', timeout: 3000 }).then(() => check(true, 'pergunta "continuar de onde parou" visível'), () => check(false, 'pergunta "continuar de onde parou" visível'));
    check((await page.textContent('#vsl-teste .vsl-card strong')) === 'Continuar de onde parou?', 'título do modal novo');
    const sub = await page.textContent('#vsl-teste .vsl-card p');
    check(sub === 'Você parou em ' + fmt(posSalva), 'subtítulo "Você parou em m:ss" com o tempo salvo', { sub, posSalva });
    check((await page.$$('#vsl-teste .vsl-card .vsl-card-actions > button[data-vsl-action]')).length === 2, 'botões dentro de .vsl-card-actions');
    check((await page.textContent('#vsl-teste [data-vsl-action="continue"]')) === 'Continuar' && (await page.textContent('#vsl-teste [data-vsl-action="restart"]')) === 'Ver do início', 'textos dos botões: Continuar / Ver do início');
    await sleep(400);
    await page.screenshot({ path: path.join(CAPTURAS, '03-modal.png') });
    await page.click('#vsl-teste [data-vsl-action="continue"]');
    await waitState(page, 'playing');
    await sleep(500);
    const retomado = await vid(page, 'v.currentTime');
    check(Math.abs(retomado - posSalva) < 2.5, 'continua de onde parou', { retomado, posSalva });
    check(await vid(page, 'v.muted') === false, 'retomada com som');
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'paused');

    console.log('\nC. Terceira visita: começar do início');
    await page.goto(pagina('t1'));
    await waitState(page, 'autoplaying');
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'modal');
    await page.click('#vsl-teste [data-vsl-action="restart"]');
    await waitState(page, 'playing');
    await sleep(400);
    check((await vid(page, 'v.currentTime')) < 1.5, 'começa do início', await vid(page, 'v.currentTime'));
    ev = await eventos(page);
    check(ev.includes('resume_prompt') && ev.includes('resume_restart'), 'eventos resume_prompt e resume_restart', ev);

    // ---------------------------------------------------------------- D. fim do vídeo
    console.log('\nD. Fim do vídeo');
    await player(page, 'player.seek(28)');
    await waitState(page, 'ended', 15000);
    await page.waitForSelector('#vsl-teste .vsl-ended', { state: 'visible', timeout: 3000 }).then(() => check(true, 'tela de "assistir de novo" visível'), () => check(false, 'tela de "assistir de novo" visível'));
    await sleep(400);
    check((await page.evaluate(() => localStorage.getItem('vsl:vsl-teste:pos'))) === null, 'posição apagada ao terminar');
    ev = await eventos(page);
    check(ev.includes('ended'), 'evento ended disparado');
    check((await page.evaluate(() => window.eventos.filter((e) => e.nome === 'milestone').map((e) => e.detail.percent))).includes(100), 'milestone 100%');
    await page.screenshot({ path: path.join(CAPTURAS, '04-ended.png') });
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    await sleep(400);
    check((await vid(page, 'v.currentTime')) < 1.5, 'clique no fim recomeça do zero');
    check((await eventos(page)).includes('replay'), 'evento replay');
    await ctx.close();

    // ---------------------------------------------------------------- E. autoplay bloqueado
    console.log('\nE. Autoplay bloqueado pelo navegador');
    const ctx2 = await browser.newContext({ viewport });
    await ctx2.addInitScript(() => {
      const original = HTMLMediaElement.prototype.play;
      let blocked = false;
      HTMLMediaElement.prototype.play = function () {
        if (!blocked) { blocked = true; return Promise.reject(new DOMException('blocked', 'NotAllowedError')); }
        return original.call(this);
      };
    });
    page = await ctx2.newPage();
    vigiar(page);
    await page.goto(pagina('t1'));
    await waitState(page, 'idle');
    await page.waitForSelector('#vsl-teste .vsl-idle', { state: 'visible', timeout: 3000 }).then(() => check(true, 'capa com botão de play visível'), () => check(false, 'capa com botão de play visível'));
    await sleep(400);
    check((await eventos(page)).includes('autoplay_blocked'), 'evento autoplay_blocked');
    await page.screenshot({ path: path.join(CAPTURAS, '05-idle.png') });
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    check(await vid(page, 'v.muted') === false, 'clique na capa toca com som');
    await ctx2.close();

    // ---------------------------------------------------------------- F. analytics
    console.log('\nF. Envio de analytics');
    const ctx3 = await browser.newContext({ viewport });
    page = await ctx3.newPage();
    vigiar(page);
    const envios = [];
    await page.route('**/collect', (route) => {
      const req = route.request();
      envios.push({ method: req.method(), body: req.postData(), type: req.resourceType() });
      route.fulfill({ status: 204 });
    });
    await page.goto(pagina('t2', { analytics: '/collect' }));
    await waitState(page, 'autoplaying');
    await waitTime(page, 8);            // 8 s no mudo: não podem contar como assistidos
    await page.click('#vsl-teste', CANTO); // recomeça do zero, com som
    await waitState(page, 'playing');
    await waitTime(page, 5.3);          // passa do pitch (5 s) com som
    await sleep(300);
    await player(page, 'player.tracker.flush()');
    await sleep(500);
    check(envios.length >= 1, 'requisições recebidas no endpoint', envios.length);
    const ultimo = envios.length ? JSON.parse(envios[envios.length - 1].body) : null;
    check(ultimo && ultimo.player === 'vsl-teste' && ultimo.visitor && ultimo.session, 'payload traz player, visitor e session', ultimo && Object.keys(ultimo));
    check(ultimo && ultimo.pitch === 5, 'payload traz o tempo do pitch', ultimo && ultimo.pitch);
    check(ultimo && ultimo.muted === false && ultimo.unmuted === true, 'payload traz muted=false depois do som', ultimo && { muted: ultimo.muted, unmuted: ultimo.unmuted });
    check(ultimo && ultimo.watched.length >= 1 && ultimo.watched[0][0] === 0, 'faixas de retenção acumuladas', ultimo && ultimo.watched);
    const fim = ultimo ? Math.max(...ultimo.watched.map((f) => f[1])) : -1;
    check(ultimo && fim >= 5 && fim <= 8 && ultimo.maxTime <= 9 && ultimo.reached >= 7, 'retenção e maxTime contam só o trecho com som; reached guarda o mudo', ultimo && { watched: ultimo.watched, maxTime: ultimo.maxTime, reached: ultimo.reached });
    check(ultimo && ultimo.events.every((e) => typeof e.seq === 'number'), 'eventos levam um contador seq');
    const tipos = envios.flatMap((e) => JSON.parse(e.body).events.map((ev) => ev.type));
    check(tipos.includes('unmute') && tipos.includes('pitch'), 'eventos unmute e pitch enviados', tipos);
    console.log('  info: tipo da requisição =', envios.map((e) => e.type + '/' + e.method).join(', '));
    await ctx3.close();

    // ---------------------------------------------------------------- G. autoplay desligado + celular
    console.log('\nG. Autoplay desligado e tela de celular');
    const ctx4 = await browser.newContext({ viewport: { width: 375, height: 740 }, isMobile: true, hasTouch: true });
    page = await ctx4.newPage();
    vigiar(page);
    await page.goto(pagina('t3', { autoplay: 'false' }));
    await waitState(page, 'idle');
    check(await vid(page, 'v.paused'), 'autoplay=false não toca sozinho');
    await page.screenshot({ path: path.join(CAPTURAS, '06-mobile-idle.png') });
    await page.tap('#vsl-teste');
    await waitState(page, 'playing');
    check(await vid(page, 'v.muted') === false, 'toque no celular toca com som');
    await sleep(600);
    await page.tap('#vsl-teste');
    await waitState(page, 'paused');
    await page.screenshot({ path: path.join(CAPTURAS, '07-mobile-paused.png') });
    await ctx4.close();

    // ---------------------------------------------------------------- H. modo de revisão
    console.log('\nH. Modo de revisão (só com a chave)');
    const ctx5 = await browser.newContext({ viewport });
    page = await ctx5.newPage();
    vigiar(page);
    await page.goto(pagina('t1') + '?revisar=errada');
    await waitState(page, 'autoplaying');
    check((await page.$('#vsl-teste .vsl-review')) === null, 'chave errada não mostra a barra');
    check(await page.evaluate(() => document.querySelector('link[rel="preconnect"]') === null), 'sem preconnect para vídeo da mesma origem');
    await page.goto(pagina('t1') + '?revisar=chave-secreta');
    await waitState(page, 'autoplaying');
    check((await page.$('#vsl-teste .vsl-review')) !== null, 'chave certa mostra a barra de revisão');
    await page.click('#vsl-teste [data-vsl-speed="2"]');
    await sleep(300);
    check((await vid(page, 'v.playbackRate')) === 2, 'velocidade 2x fica valendo');
    check((await state(page)) === 'autoplaying', 'clicar na barra não pausa nem tira o overlay');
    await page.fill('#vsl-teste [data-vsl-goto]', '0:20');
    await page.click('#vsl-teste [data-vsl-go]');
    await waitState(page, 'playing');
    await sleep(600);
    const pulou = await vid(page, 'v.currentTime');
    check(pulou >= 19 && pulou < 25, 'pular para 0:20 funciona e toca com som', pulou);
    check(await vid(page, 'v.muted') === false, 'depois do pulo o vídeo está com som');
    await page.goto(pagina('t1'));
    await waitState(page, 'autoplaying');
    check((await page.$('#vsl-teste .vsl-review')) !== null, 'o modo continua na mesma aba sem repetir a chave na URL');
    await ctx5.close();

    // ---------------------------------------------------------------- I. vídeo 404: retentativas e saída
    console.log('\nI. Vídeo 404: três retentativas (1 s, 3 s, 8 s), depois botão "Tentar de novo" e elementos liberados');
    const ctx6 = await browser.newContext({ viewport });
    page = await ctx6.newPage();
    vigiar(page, { recursos: false });
    ctl.quebrado = true;
    ctl.pedidosQuebrado = 0;
    const inicioI = Date.now();
    await page.goto(pagina('erro404', { src: 'quebrado.webm' }));
    await sleep(600);
    check((await state(page)) === 'loading', 'logo depois da falha o estado é loading (capa + spinner), não error', await state(page));
    check(!(await page.isVisible('#vsl-teste .vsl-error')), 'tela de erro não aparece durante as retentativas');
    check(!(await page.isVisible('#cta')), 'elemento com delay continua escondido durante as retentativas');
    await sleep(5000);
    check((await state(page)) === 'loading', 'aos 5,6 s ainda loading (segunda retentativa em andamento)', await state(page));
    check(ctl.pedidosQuebrado >= 3, 'o vídeo foi pedido de novo nas retentativas', ctl.pedidosQuebrado);
    await waitState(page, 'error', 15000);
    const demorou = (Date.now() - inicioI) / 1000;
    check(demorou >= 11.5 && demorou < 20, 'estado error só depois de 1 s + 3 s + 8 s de retentativas', demorou);
    check(ctl.pedidosQuebrado === 4, 'quatro pedidos do vídeo: o primeiro e três retentativas', ctl.pedidosQuebrado);
    await page.waitForSelector('#vsl-teste .vsl-error', { state: 'visible', timeout: 3000 }).then(() => check(true, 'tela de erro visível'), () => check(false, 'tela de erro visível'));
    check((await page.textContent('#vsl-teste .vsl-error strong')) === 'O vídeo não carregou', 'texto de erro novo: "O vídeo não carregou"');
    check(await page.isVisible('#vsl-teste .vsl-error .vsl-box > button.vsl-btn--primary[data-vsl-action="retry"]'), 'botão "Tentar de novo" visível dentro da caixa de erro');
    check((await page.textContent('#vsl-teste [data-vsl-action="retry"]')) === 'Tentar de novo', 'texto do botão de retentativa');
    check(await page.isVisible('#cta'), 'fail-open: elemento data-vsl-show-at liberado ao entrar em error');
    const errosI = await page.evaluate(() => window.eventos.filter((e) => e.nome === 'error').map((e) => e.detail));
    check(errosI.length === 1 && errosI[0].code === 4 && errosI[0].attempt === 3, 'um evento error, com code e attempt=3', errosI);
    await sleep(400);
    await page.screenshot({ path: path.join(CAPTURAS, '08-error.png') });
    await page.click('#vsl-teste [data-vsl-action="retry"]');
    await sleep(300);
    check((await state(page)) === 'loading', 'botão "Tentar de novo" volta para loading e zera o contador', await state(page));
    check(!(await page.isVisible('#vsl-teste .vsl-error')), 'tela de erro some ao tentar de novo');
    ctl.quebrado = false; // o arquivo volta: a retentativa automática seguinte (1 s) encontra o vídeo
    await waitState(page, 'autoplaying', 8000);
    check(true, 'quando a fonte volta, o vídeo toca de novo (mudo: a sessão nunca liberou o som)');
    check(await vid(page, 'v.muted') === true, 'retentativa sem som liberado toca mudo');
    check((await page.evaluate(() => window.eventos.filter((e) => e.nome === 'error').length)) === 1, 'nenhum evento error extra na recuperação');
    await ctx6.close();

    // ---------------------------------------------------------------- J. loading até o primeiro quadro + watchdog
    console.log('\nJ. "Seu vídeo já começou" só com imagem na tela; watchdog de 12 s');
    const ctx7 = await browser.newContext({ viewport });
    page = await ctx7.newPage();
    vigiar(page);
    ctl.delayVideoMs = 2500;
    const inicioJ = Date.now();
    await page.goto(pagina('lento', { src: 'lento.webm' }), { waitUntil: 'domcontentloaded' });
    await sleep(400);
    let amostraJ = await amostra(page);
    check(amostraJ.state === 'loading' && amostraJ.paused === false, 'play() aceito mas sem quadro: estado continua loading', amostraJ);
    check(amostraJ.buffering, 'spinner ligado enquanto espera o primeiro quadro', amostraJ);
    check(await page.isVisible('#vsl-teste .vsl-poster'), 'capa visível enquanto carrega');
    check(!(await page.isVisible('#vsl-teste .vsl-unmute')), 'aviso "seu vídeo já começou" ainda escondido');
    await sleep(1200);
    check((await state(page)) === 'loading', 'aos 1,6 s ainda loading (o vídeo demora 2,5 s para responder)', await state(page));
    await waitState(page, 'autoplaying', 10000);
    const evAutoplay = await evento(page, 'autoplay');
    check(evAutoplay && evAutoplay.time > 0.05, 'evento autoplay emitido já com imagem (currentTime > 0.05)', evAutoplay);
    check(Date.now() - inicioJ >= 2400, 'autoplaying só depois do vídeo chegar', Date.now() - inicioJ);
    ctl.delayVideoMs = 0;
    ctl.preso = true;
    const inicioW = Date.now();
    await page.goto(pagina('preso', { src: 'preso.webm' }), { waitUntil: 'domcontentloaded' });
    await sleep(1500);
    amostraJ = await amostra(page);
    check(amostraJ.state === 'loading' && amostraJ.paused === false, 'vídeo que não responde: play() aceito, estado loading', amostraJ);
    await waitState(page, 'idle', 16000);
    const esperou = (Date.now() - inicioW) / 1000;
    check(esperou >= 11.5 && esperou < 16, 'sem quadro em 12 s, vai para idle (capa + play)', esperou);
    check((await vid(page, "v.getAttribute('src')")) === 'preso.webm', 'o <video> não é derrubado (src continua)');
    check(await page.evaluate(() => window.eventos.some((e) => e.nome === 'autoplay_blocked' && e.detail.reason === 'no-frame')), 'evento autoplay_blocked com reason=no-frame');
    check(!(await eventos(page)).includes('autoplay'), 'nenhum evento autoplay sem imagem');
    ctl.preso = false;
    soltar();
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing', 10000);
    await waitTime(page, 0.5, 10000);
    check(await vid(page, 'v.muted') === false, 'toque na capa depois do watchdog toca com som');
    await ctx7.close();

    // ---------------------------------------------------------------- K. pitch só com som e aba visível
    console.log('\nK. Pitch só com som e aba visível');
    const ctx8 = await browser.newContext({ viewport });
    page = await ctx8.newPage();
    vigiar(page);
    await page.goto(pagina('pitch', { pitch: '3' }));
    await waitState(page, 'autoplaying');
    await waitTime(page, 4);
    check(!(await eventos(page)).includes('pitch'), 'passar do pitch mudo não dispara pitch');
    check((await page.evaluate(() => localStorage.getItem('vsl:vsl-teste:pitch'))) === null, 'pitch mudo não é marcado como feito');
    // aba oculta: simula document.visibilityState = 'hidden'
    await page.evaluate(() => { window.__vis = 'hidden'; Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => window.__vis }); document.dispatchEvent(new Event('visibilitychange')); });
    await page.click('#vsl-teste', CANTO); // recomeça do zero com som, mas a aba está "oculta"
    await waitState(page, 'playing');
    await waitTime(page, 4);
    check(!(await eventos(page)).includes('pitch'), 'com som mas aba oculta, pitch não dispara');
    await page.evaluate(() => { window.__vis = 'visible'; document.dispatchEvent(new Event('visibilitychange')); });
    await page.waitForFunction(() => window.eventos.some((e) => e.nome === 'pitch'), null, { timeout: 3000 }).then(() => check(true, 'ao voltar a ficar visível, pitch dispara'), () => check(false, 'ao voltar a ficar visível, pitch dispara'));
    const evPitch = await evento(page, 'pitch');
    check(evPitch && evPitch.detail.at === 3 && evPitch.detail.muted === false && evPitch.detail.time >= 3, 'detalhe do pitch: at, time e muted=false', evPitch);
    check((await page.evaluate(() => localStorage.getItem('vsl:vsl-teste:pitch'))) === '1', 'pitch marcado como feito só agora');
    await ctx8.close();

    // ---------------------------------------------------------------- L. sessão muda envia uma vez
    console.log('\nL. Analytics: sessão muda envia uma vez em 20 s; unmute dispara envio; intervalo cresce depois de 5 min');
    const ctx9 = await browser.newContext({ viewport });
    page = await ctx9.newPage();
    vigiar(page);
    const enviosL = [];
    await page.route('**/collect', (route) => { enviosL.push(JSON.parse(route.request().postData())); route.fulfill({ status: 204 }); });
    await page.goto(pagina('muda', { analytics: '/collect', pitch: '25' }));
    await waitState(page, 'autoplaying');
    await sleep(20000);
    check(enviosL.length === 1, 'sessão muda: exatamente 1 envio em 20 s', enviosL.length);
    check(enviosL[0] && enviosL[0].muted === true && enviosL[0].unmuted === false, 'primeiro envio marca muted=true', enviosL[0] && { muted: enviosL[0].muted, unmuted: enviosL[0].unmuted });
    check(enviosL[0] && enviosL[0].events.some((e) => e.type === 'ready' || e.type === 'autoplay'), 'primeiro envio sai logo no ready/autoplay');
    check(enviosL[0] && !enviosL[0].events.some((e) => e.type === 'milestone'), 'marcos ainda não saíram (ficam acumulando)');
    const t20 = await vid(page, 'v.currentTime');
    check(t20 >= 18, 'o vídeo mudo continuou tocando', t20);
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    await sleep(600);
    check(enviosL.length === 2, 'unmute dispara um envio na hora', enviosL.length);
    const segundo = enviosL[1];
    check(segundo && segundo.muted === false && segundo.events.some((e) => e.type === 'unmute'), 'segundo envio marca muted=false e traz o unmute');
    const marcos = segundo ? segundo.events.filter((e) => e.type === 'milestone').map((e) => e.percent) : [];
    check(marcos.includes(10) && marcos.includes(25) && marcos.includes(50), 'marcos acumulados no mudo saem no unmute', marcos);
    check(segundo && segundo.events.some((e) => e.type === 'reach') && segundo.reached >= 18, 'reach e reached acumulados saem junto', segundo && segundo.reached);
    // depois de 5 min com som o intervalo vira 60 s: adiantando o relógio, nada sai nos próximos 7 s (o intervalo da página é 5 s)
    await player(page, 'player.tracker.soundSince = Date.now() - 6 * 60 * 1000; player.tracker._schedule()');
    const antesL = enviosL.length;
    await sleep(7000);
    check(enviosL.length === antesL, 'depois de 5 min com som, o intervalo de 5 s dá lugar a 60 s', enviosL.length - antesL);
    await ctx9.close();

    // ---------------------------------------------------------------- M. toques
    console.log('\nM. Toques no celular: duplo toque ignorado, textos de toque, aviso como botão');
    const ctx10 = await browser.newContext({ viewport: { width: 375, height: 740 }, isMobile: true, hasTouch: true });
    page = await ctx10.newPage();
    vigiar(page);
    const cdp = await ctx10.newCDPSession(page);
    await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'hover', value: 'none' }, { name: 'pointer', value: 'coarse' }] });
    await page.goto(pagina('toque', { attrs2: 'data-play-text="Clique aqui"' }));
    await waitState(page, 'autoplaying');
    check(await page.evaluate(() => matchMedia('(hover: none) and (pointer: coarse)').matches), 'ambiente de toque detectado');
    check((await page.textContent('#vsl-teste .vsl-unmute .vsl-sub')) === 'Toque para ouvir', 'subtítulo vira "Toque para ouvir"');
    check((await page.textContent('#vsl-teste .vsl-idle .vsl-caption')) === 'Toque para assistir', 'capa diz "Toque para assistir"');
    check((await page.textContent('#vsl-teste .vsl-paused strong')) === 'Toque para continuar', 'pausa diz "Toque para continuar"');
    check((await page.getAttribute('#vsl-teste .vsl-unmute button', 'aria-label')) === 'Seu vídeo já começou. Toque para ouvir', 'aria-label do aviso acompanha o texto');
    check((await page.textContent('#vsl-segundo .vsl-idle .vsl-caption')) === 'Clique aqui', 'data-play-text do HTML continua vencendo');
    await waitTime(page, 1);
    const t0M = Date.now();
    await page.tap('#vsl-teste .vsl-unmute button');
    await page.tap('#vsl-teste');
    const gap = Date.now() - t0M;
    await sleep(300);
    if (gap < 450) check((await state(page)) === 'playing', `dois toques seguidos (${gap} ms): o segundo não pausa`, await state(page));
    else console.log('  info: os dois toques demoraram', gap, 'ms (> 450): anti duplo toque não verificado');
    check(await vid(page, 'v.muted') === false, 'o primeiro toque (no aviso) liberou o som');
    await sleep(500);
    await page.tap('#vsl-teste');
    await waitState(page, 'paused');
    check(true, 'passados 450 ms, o toque volta a pausar');
    await ctx10.close();

    // ---------------------------------------------------------------- N. data-show
    console.log('\nN. data-show: elementos por seletor no próprio player');
    const ctx11 = await browser.newContext({ viewport });
    page = await ctx11.newPage();
    vigiar(page);
    await page.goto(pagina('show', {
      attrs: 'data-show="#oferta, .oferta-extra" data-show-at="3"',
      attrs2: 'data-show=".oferta-segundo" data-pitch="2"',
      extra: '<p class="oferta-extra">Extra</p><p class="oferta-segundo">Do segundo player</p>',
    }));
    await waitState(page, 'autoplaying');
    check(!(await page.isVisible('#oferta')) && !(await page.isVisible('.oferta-extra')), 'elementos de data-show começam escondidos');
    const marcado = { at: await page.getAttribute('#oferta', 'data-vsl-show-at'), dono: await page.getAttribute('#oferta', 'data-vsl-player') };
    check(marcado.at === '3' && marcado.dono === 'vsl-teste', 'elemento casado recebe data-vsl-show-at e data-vsl-player', marcado);
    check(await page.isVisible('#vsl-teste'), 'o próprio player (com data-show-at) não é escondido');
    check(!(await page.isVisible('.oferta-segundo')) && (await page.getAttribute('.oferta-segundo', 'data-vsl-show-at')) === '2', 'sem data-show-at, o tempo é o pitch do player');
    await waitTime(page, 3.3);
    await sleep(300);
    check((await page.isVisible('#oferta')) && (await page.isVisible('.oferta-extra')), 'elementos de data-show aparecem no tempo (mesmo mudo)');
    check((await page.evaluate(() => window.eventos.filter((e) => e.nome === 'reach' && e.detail.at === 3).length)) === 2, 'um evento reach para cada elemento de data-show');
    check((await page.evaluate(() => parseFloat(localStorage.getItem('vsl:vsl-teste:reached')))) >= 3, 'persistência em :reached');
    check(!(await page.isVisible('.oferta-segundo')), 'elemento do segundo player continua escondido');
    await page.click('#vsl-segundo');
    await page.waitForFunction(() => document.getElementById('vsl-segundo').querySelector('video').currentTime >= 2.3);
    await sleep(300);
    check(await page.isVisible('.oferta-segundo'), 'elemento do segundo player aparece no pitch dele');
    await ctx11.close();

    // ---------------------------------------------------------------- O. miniatura de pausa pós-pitch
    console.log('\nO. Miniatura de pausa pós-pitch com botão (CTA)');
    const ctx12 = await browser.newContext({ viewport });
    page = await ctx12.newPage();
    vigiar(page);
    const enviosO = [];
    await page.route('**/collect', (route) => { enviosO.push(JSON.parse(route.request().postData())); route.fulfill({ status: 204 }); });
    await page.goto(pagina('pausa', { analytics: '/collect', pitch: '4', attrs: 'data-pause-poster-late="../demo/capa.jpg" data-pause-cta-text="QUERO A OFERTA" data-pause-cta-link="#oferta" data-pause-cta-pos="bottom-right"' }));
    await waitState(page, 'autoplaying');
    const layerO = await page.evaluate(() => { const l = document.querySelector('#vsl-teste .vsl-pause-poster'); const a = l && l.querySelector('a.vsl-cta'); return { layer: !!l, bg: l && l.style.backgroundImage, a: a && { href: a.getAttribute('href'), target: a.getAttribute('target'), pos: a.getAttribute('data-vsl-pos'), text: a.textContent } }; });
    check(layerO.layer && /capa\.jpg/.test(layerO.bg), 'layer .vsl-pause-poster com a imagem de fundo', layerO.bg);
    check(layerO.a && layerO.a.href === '#oferta' && layerO.a.target === '_top' && layerO.a.pos === 'bottom-right' && layerO.a.text === 'QUERO A OFERTA', 'CTA com link, target _top, posição e texto', layerO.a);
    await waitTime(page, 1);
    await page.click('#vsl-teste', CANTO); // som
    await waitState(page, 'playing');
    await waitTime(page, 1.5);
    await page.click('#vsl-teste', CANTO); // pausa antes do pitch
    await waitState(page, 'paused');
    check((await page.getAttribute('#vsl-teste', 'data-pause-poster')) === null, 'pausa antes do pitch: sem miniatura');
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    await waitTime(page, 4.3);
    await page.click('#vsl-teste', CANTO); // pausa depois do pitch
    await waitState(page, 'paused');
    check((await page.getAttribute('#vsl-teste', 'data-pause-poster')) === 'on', 'pausa depois do pitch: root ganha data-pause-poster="on"');
    await sleep(400);
    await page.screenshot({ path: path.join(CAPTURAS, '09-pause-poster.png') });
    const antesO = enviosO.length;
    await page.evaluate(() => document.querySelector('#vsl-teste .vsl-pause-poster a.vsl-cta').click());
    await sleep(500);
    check((await state(page)) === 'paused', 'clique no CTA não retoma nem pausa', await state(page));
    const ctaEv = await evento(page, 'cta_click');
    check(ctaEv && ctaEv.detail.where === 'pause' && ctaEv.detail.link === '#oferta', 'evento cta_click { where: "pause", link }', ctaEv);
    check((await page.evaluate(() => location.hash)) === '#oferta', 'o link segue (sem preventDefault)');
    check(enviosO.length > antesO && enviosO.slice(antesO).some((p) => p.events.some((e) => e.type === 'cta_click')), 'cta_click vai para o analytics na hora', enviosO.length - antesO);
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    check((await page.getAttribute('#vsl-teste', 'data-pause-poster')) === null, 'ao retomar, o atributo some');
    await ctx12.close();

    // ---------------------------------------------------------------- P. tela final com CTA
    console.log('\nP. Tela final com imagem e botão (CTA)');
    const ctx13 = await browser.newContext({ viewport });
    page = await ctx13.newPage();
    vigiar(page);
    await page.goto(pagina('fim', { attrs: 'data-end-poster="../demo/capa.jpg" data-end-cta-text="GARANTIR MINHA VAGA" data-end-cta-link="#fim" data-end-cta-pos="center"' }));
    await waitState(page, 'autoplaying');
    check((await page.getAttribute('#vsl-teste', 'data-end-screen')) === 'poster-cta', 'root recebe data-end-screen="poster-cta"');
    const fimP = await page.evaluate(() => { const l = document.querySelector('#vsl-teste .vsl-ended'); const a = l.querySelector('a.vsl-cta'); return { bg: l.style.backgroundImage, box: !!l.querySelector('.vsl-box'), a: a && { href: a.getAttribute('href'), pos: a.getAttribute('data-vsl-pos'), text: a.textContent } }; });
    check(/capa\.jpg/.test(fimP.bg) && !fimP.box && fimP.a && fimP.a.href === '#fim' && fimP.a.pos === 'center' && fimP.a.text === 'GARANTIR MINHA VAGA', 'layer final com imagem e CTA no lugar do replay', fimP);
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    await player(page, 'player.seek(28)');
    await waitState(page, 'ended', 15000);
    await page.waitForSelector('#vsl-teste .vsl-ended', { state: 'visible', timeout: 3000 }).then(() => check(true, 'tela final visível'), () => check(false, 'tela final visível'));
    await sleep(400);
    await page.screenshot({ path: path.join(CAPTURAS, '10-end-poster.png') });
    await page.evaluate(() => document.querySelector('#vsl-teste .vsl-ended a.vsl-cta').click());
    await sleep(300);
    check((await state(page)) === 'ended', 'clique no CTA final não reinicia', await state(page));
    const ctaFim = await evento(page, 'cta_click');
    check(ctaFim && ctaFim.detail.where === 'end' && ctaFim.detail.link === '#fim', 'evento cta_click { where: "end", link }', ctaFim);
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    check((await eventos(page)).includes('replay'), 'toque fora do botão continua reiniciando');
    await ctx13.close();

    // ---------------------------------------------------------------- Q. velocidade manual
    console.log('\nQ. Velocidade manual (data-speed)');
    const ctx14 = await browser.newContext({ viewport });
    page = await ctx14.newPage();
    vigiar(page);
    await page.goto(pagina('speed', { attrs: 'data-speed="1.25"', attrs2: 'data-speed="3"' }));
    await waitState(page, 'autoplaying');
    check((await vid(page, 'v.playbackRate')) === 1.25, 'toca em 1.25x', await vid(page, 'v.playbackRate'));
    await vid(page, 'v.playbackRate = 2');
    await sleep(200);
    check((await vid(page, 'v.playbackRate')) === 1.25, 'a trava devolve para 1.25x (não para 1x)', await vid(page, 'v.playbackRate'));
    check((await vid(page, 'v.defaultPlaybackRate')) === 1.25, 'defaultPlaybackRate também (sobrevive ao load() das retentativas)');
    check((await player(page, 'player.opts.speed', 'vsl-segundo')) === 1.5, 'data-speed acima de 1.5 é limitado a 1.5');
    await ctx14.close();

    // ---------------------------------------------------------------- R. HLS via shim
    console.log('\nR. HLS: hls.js carregado pelo player (shim), nível inicial, erro fatal, timeout e fallback');
    const ctx15 = await browser.newContext({ viewport });
    page = await ctx15.newPage();
    vigiar(page, { recursos: false });
    // R1. a página já carregou o hls.js antes: nada é injetado
    await page.goto(pagina('hls-pre', { src: 'video.m3u8', head: '<script>' + SHIM + '</script>' }));
    await waitState(page, 'autoplaying');
    let infoR = await infoHls(page);
    check(infoR.scripts === 0 && infoR.instancias === 1, 'com window.Hls já na página, nada é injetado', infoR);
    check(/teste\.webm$/.test(infoR.src), 'hls (shim) ligou o vídeo ao <video>', infoR.src);
    check(infoR.startLevel === 1, 'nível inicial: o mais perto de 480p (índice 1 de 360/480/720/1080)', infoR.startLevel);
    // R2. auto-load: dois players .m3u8, um <script> só
    await page.goto(pagina('hls-auto', { src: 'video.m3u8', attrs: 'data-hls-url="hls-shim.js"', extra: '<div class="vsl-player" id="vsl-hls2" data-src="video.m3u8" data-hls-url="hls-shim.js" data-autoplay="false"></div>' }));
    await waitState(page, 'autoplaying');
    infoR = await infoHls(page);
    check(infoR.scripts === 1, 'player injeta o <script> do hls.js uma vez só (dois players)', infoR.scripts);
    check(infoR.instancias === 2, 'as duas instâncias usam o mesmo hls.js', infoR.instancias);
    check(infoR.config && infoR.config.capLevelToPlayerSize === true && infoR.config.maxBufferLength === 60 && infoR.config.startLevel === 0, 'capLevelToPlayerSize, maxBufferLength e startLevel 0 continuam na configuração', infoR.config);
    check(/teste\.webm$/.test(infoR.src), 'vídeo ligado pelo hls.js injetado');
    const niveis = await page.evaluate(() => {
      const h = window.__hlsShim.instancias[0];
      h.trigger(window.Hls.Events.MANIFEST_PARSED, { levels: [{ width: 240, height: 426 }, { width: 480, height: 854 }, { width: 720, height: 1280 }] });
      const vertical = h.startLevel;
      h.trigger(window.Hls.Events.MANIFEST_PARSED, { levels: [{}, {}] });
      return { vertical, semMedidas: h.startLevel };
    });
    check(niveis.vertical === 1 && niveis.semMedidas === 0, 'vertical usa o menor lado; sem medidas fica em 0', niveis);
    // R3. erro fatal: rede -> startLoad; mídia -> recoverMediaError; outro -> destroy + recriar
    await page.evaluate(() => window.__hlsShim.instancias[0].erroFatal('networkError'));
    check((await state(page)) === 'loading', 'erro fatal de rede: estado loading (não error)', await state(page));
    await sleep(1300);
    check((await chamadas(page, 0)).includes('startLoad'), 'retentativa de rede chama hls.startLoad()', await chamadas(page, 0));
    await waitState(page, 'autoplaying', 5000);
    check(true, 'voltou a tocar depois do startLoad');
    await page.evaluate(() => window.__hlsShim.instancias[0].erroFatal('mediaError'));
    await sleep(1300);
    check((await chamadas(page, 0)).includes('recoverMediaError'), 'erro de mídia chama hls.recoverMediaError()', await chamadas(page, 0));
    await waitState(page, 'autoplaying', 5000);
    await page.evaluate(() => window.__hlsShim.instancias[0].erroFatal('otherError'));
    await sleep(1300);
    infoR = await infoHls(page);
    check((await chamadas(page, 0)).includes('destroy') && infoR.instancias === 3, 'outro erro: destroy() e recriar a instância', { chamadas: await chamadas(page, 0), instancias: infoR.instancias });
    await waitState(page, 'autoplaying', 5000);
    check(!(await eventos(page)).includes('error'), 'nenhum evento error enquanto a recuperação funciona');
    // R4. hls.js não chega em 8 s -> fallback MP4
    await page.route('**/hls-nunca.js', () => {}); // nunca responde
    const inicioT = Date.now();
    await page.goto(pagina('hls-timeout', { src: 'video.m3u8', attrs: 'data-hls-url="hls-nunca.js" data-fallback="teste.webm"' }), { waitUntil: 'domcontentloaded' });
    await sleep(5000);
    check((await state(page)) === 'loading', 'enquanto espera o hls.js: loading', await state(page));
    await waitState(page, 'autoplaying', 12000);
    const esperouT = (Date.now() - inicioT) / 1000;
    check(esperouT >= 7.5 && esperouT < 12, 'depois de 8 s sem hls.js, usa o fallback MP4', esperouT);
    check((await page.evaluate(() => typeof window.Hls)) === 'undefined' && /teste\.webm$/.test(await vid(page, 'v.currentSrc')), 'tocando o fallback, sem Hls');
    await page.unroute('**/hls-nunca.js');
    // R5. hls.js não baixa (404) e sem fallback -> caminho de erro com code hls-load; toque na tela de erro tenta de novo
    const inicioE = Date.now();
    await page.goto(pagina('hls-404', { src: 'video.m3u8', attrs: 'data-hls-url="nao-existe.js"' }));
    await waitState(page, 'error', 20000);
    const esperouE = (Date.now() - inicioE) / 1000;
    const erroHls = await evento(page, 'error');
    check(erroHls && erroHls.detail.code === 'hls-load' && erroHls.detail.attempt === 3 && esperouE >= 11.5, 'sem hls.js e sem fallback: três retentativas e error com code hls-load', { erroHls, esperouE });
    check(await page.isVisible('#cta'), 'fail-open também no erro de HLS');
    await page.click('#vsl-teste', CANTO);
    await sleep(300);
    check((await state(page)) === 'loading', 'toque em qualquer ponto da tela de erro tenta de novo (volta para loading)', await state(page));
    check((await page.evaluate(() => document.querySelectorAll('script[data-vsl-hls]').length)) >= 4, 'cada tentativa injeta o script de novo', await page.evaluate(() => document.querySelectorAll('script[data-vsl-hls]').length));
    await ctx15.close();

    // ---------------------------------------------------------------- S. erro no meio de uma sessão com som
    console.log('\nS. Erro com som: a retentativa não apaga a posição; rede presa -> "toque para continuar" retoma de onde parou; 404 -> :pos sobrevive');
    // Tudo que o player guarda sobre a posição, lido de uma vez: <video>, _lastTime, seek pendente/recusado e localStorage.
    const guardado = (page) => player(page, '({ time: +player.video.currentTime.toFixed(2), lastTime: +player._lastTime.toFixed(2), pendingSeek: player._pendingSeek, seekRetry: player._seekRetry, pos: localStorage.getItem("vsl:vsl-teste:pos") })');
    // As amostras são tiradas 300 ms depois de `playing`: um vídeo que recomeça do zero ainda está perto de 0 aí, então o
    // teste não passa "sozinho" quando a retomada falha (esperar `currentTime >= 3,5` em até 10 s passaria em 3,5 s).
    //
    // S1. Servidor SEM Range (Safari, cache frio): o load() da retentativa volta à rede. Limitação do Chromium: num stream
    // sem Range `seekable` é [0,0] durante todo o download (mesmo com `buffered` cobrindo o alvo) e o seek para a posição
    // guardada é recusado: o quadro recomeça do zero. O que o player garante é NÃO PERDER a posição: _lastTime fica no
    // alvo, :pos não cai abaixo dele e o alvo fica armado (_seekRetry) para quando `seekable` cobrir. A retomada de
    // verdade é provada em S2 (Range + download lento) e S3 (404 -> "Tentar de novo" com Range).
    const ctx16 = await browser.newContext({ viewport });
    page = await ctx16.newPage();
    vigiar(page, { recursos: false });
    ctl.semRange = true;
    ctl.preso = false;
    await page.goto(pagina('retry-som', { src: 'preso.webm' }));
    await waitState(page, 'autoplaying');
    await page.click('#vsl-teste', CANTO); // som (recomeça do zero)
    await waitState(page, 'playing');
    await waitTime(page, 4);
    const posS = await page.evaluate(() => parseFloat(localStorage.getItem('vsl:vsl-teste:pos')));
    check(posS >= 3, 'posição salva antes do erro', posS);
    ctl.preso = true; // a rede caiu: o pedido do vídeo não responde
    await vid(page, "v.dispatchEvent(new Event('error'))");
    await sleep(1500); // a 1ª retentativa (1 s) já fez load(); o pedido novo está preso
    const amostraS = await amostra(page);
    const guardadoS = await guardado(page);
    check(amostraS.state === 'loading' && amostraS.time === 0, 'retentativa: load() zerou o <video> e o estado é loading', amostraS);
    check(guardadoS.lastTime >= 3.5 && guardadoS.pendingSeek >= 3.5, 'o timeupdate em 0 do load() não apaga _lastTime; a posição vira seek pendente', guardadoS);
    check(parseFloat(guardadoS.pos) >= 3, 'localStorage :pos não vira 0 na retentativa', guardadoS.pos);
    await waitState(page, 'paused', 16000);
    check(true, 'sem imagem em 12 s numa sessão com som: vai para paused ("toque para continuar"), não para a capa');
    check(!(await eventos(page)).includes('autoplay_blocked'), 'sem evento autoplay_blocked numa sessão com som');
    check(parseFloat(await page.evaluate(() => localStorage.getItem('vsl:vsl-teste:pos'))) >= 3, ':pos continua guardado depois do watchdog');
    ctl.preso = false;
    soltar(); // a rede voltou; sem Range, o Chromium recusa o seek pendente (cai em 0)
    await sleep(1500);
    const voltouS = await guardado(page);
    check(voltouS.lastTime >= 3.5 && (voltouS.time >= 3.5 || voltouS.seekRetry >= 3.5), 'rede de volta, ainda pausado: o seek recusado não apaga _lastTime (alvo armado em _seekRetry)', voltouS);
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing', 10000);
    await sleep(300);
    const logoS = await guardado(page);
    check(logoS.lastTime >= 3.5 && parseFloat(logoS.pos) >= 3, 'sem Range: logo depois do toque _lastTime e :pos continuam na posição de antes do erro (o quadro pode recomeçar do zero: limitação do navegador)', logoS);
    await sleep(2000);
    const depoisS = await guardado(page);
    check(depoisS.lastTime >= 3.5 && parseFloat(depoisS.pos) >= 3, 'sem Range: 2 s de reprodução depois, :pos não é sobrescrito com o tempo "regenerado"', depoisS);
    check(await vid(page, 'v.muted') === false, 'retomada com som');
    check(!(await eventos(page)).includes('resume_prompt'), 'sem pergunta "continuar de onde parou" no meio da sessão');
    await ctx16.close();
    ctl.semRange = false;
    // S2. Servidor COM Range (CDN) numa rede lenta (90 KB/s): a queda derruba a conexão, o buffer do Chromium esgota e o
    // load() da retentativa precisa da rede para a posição guardada. Aqui a retomada tem de ser real: o <video> volta
    // para a posição de antes do erro logo depois de `playing`.
    const ctx16b = await browser.newContext({ viewport });
    page = await ctx16b.newPage();
    vigiar(page, { recursos: false });
    ctl.lentoKBs = 90;
    ctl.preso = false;
    await page.goto(pagina('retry-lento', { src: 'lento.webm' }), { waitUntil: 'domcontentloaded' });
    await waitState(page, 'autoplaying', 15000);
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing');
    await waitTime(page, 4, 20000);
    derrubar(); // a rede caiu: conexão cortada, pedidos seguintes presos
    await page.waitForFunction(() => { const r = document.getElementById('vsl-teste'); const v = r.querySelector('video'); return r.classList.contains('vsl-buffering') || v.readyState < 3; }, null, { timeout: 25000 }); // o buffer esgotou
    const antesS2 = await guardado(page);
    await vid(page, "v.dispatchEvent(new Event('error'))"); // o que o Chromium faria (MEDIA_ERR_NETWORK) depois das próprias tentativas
    await waitState(page, 'paused', 16000); // retentativa presa -> watchdog -> "toque para continuar"
    const pausadoS2 = await guardado(page);
    check(pausadoS2.lastTime >= antesS2.time - 0.5 && parseFloat(pausadoS2.pos) >= 3, 'com Range: watchdog -> paused com a posição guardada', { antes: antesS2, pausado: pausadoS2 });
    ctl.preso = false;
    ctl.lentoKBs = 0;
    soltar(); // a rede voltou
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'playing', 10000);
    await sleep(300);
    const logoS2 = await guardado(page);
    check(logoS2.time >= 3.5 && logoS2.time >= antesS2.time - 1, 'com Range: logo depois do toque o <video> está na posição de antes do erro (retomada de verdade, não do zero)', { antes: antesS2.time, depois: logoS2 });
    check(await vid(page, 'v.muted') === false, 'retomada com som');
    check(!(await eventos(page)).includes('resume_prompt'), 'sem pergunta "continuar de onde parou" no meio da sessão');
    await ctx16b.close();
    // S3/S4. 404 nas três retentativas -> error -> "Tentar de novo": com Range na volta (S3) a retomada é real; sem Range
    // (S4) o Chromium recusa o seek, mas _lastTime/:pos não se perdem e, ao recarregar, o player ainda oferece continuar.
    for (const comRange of [true, false]) {
      const rotulo = comRange ? 'com Range' : 'sem Range';
      ctl.semRange = true; // o primeiro play não pode ficar no cache do Chromium (senão o load() nem vai à rede)
      ctl.quebrado = false;
      const ctx17 = await browser.newContext({ viewport });
      page = await ctx17.newPage();
      vigiar(page, { recursos: false });
      await page.goto(pagina('retry-404', { src: 'quebrado.webm' }));
      await waitState(page, 'autoplaying');
      await page.click('#vsl-teste', CANTO);
      await waitState(page, 'playing');
      await waitTime(page, 4);
      ctl.quebrado = true;
      await vid(page, "v.dispatchEvent(new Event('error'))");
      await waitState(page, 'error', 20000);
      const guardado404 = await guardado(page);
      check(guardado404.lastTime >= 3.5 && parseFloat(guardado404.pos) >= 3, `três retentativas em 404 (${rotulo}): _lastTime e :pos preservados no estado error`, guardado404);
      ctl.quebrado = false;
      ctl.semRange = !comRange;
      await page.click('#vsl-teste [data-vsl-action="retry"]');
      await waitState(page, 'playing', 10000);
      await sleep(300);
      const logo404 = await guardado(page);
      if (comRange) check(logo404.time >= 3.5, '"Tentar de novo" com Range: logo depois de playing o <video> está na posição de antes do erro (não do zero)', logo404);
      else check(logo404.lastTime >= 3.5 && parseFloat(logo404.pos) >= 3 && (logo404.time >= 3.5 || logo404.seekRetry >= 3.5), '"Tentar de novo" sem Range: o seek recusado não apaga _lastTime/:pos (alvo armado)', logo404);
      await sleep(2000);
      const depois404 = await guardado(page);
      check(depois404.lastTime >= 3.5 && parseFloat(depois404.pos) >= 3, `2 s depois (${rotulo}): :pos continua na posição de antes do erro`, depois404);
      check(await vid(page, 'v.muted') === false, 'com som (a sessão já tinha liberado o som)');
      await page.click('#vsl-teste', CANTO); // pausa: grava a posição
      await waitState(page, 'paused');
      const posPausa = parseFloat(await page.evaluate(() => localStorage.getItem('vsl:vsl-teste:pos')));
      check(posPausa >= 3.5, `a pausa grava a posição de verdade, não a "regenerada" (${rotulo})`, posPausa);
      await page.goto(pagina('retry-404', { src: 'quebrado.webm' }));
      await waitState(page, 'autoplaying');
      await page.click('#vsl-teste', CANTO);
      await waitState(page, 'modal');
      const textoModal = await page.textContent('#vsl-teste .vsl-card p');
      check(/0:0[4-9]/.test(textoModal), `ao recarregar, o player ainda oferece "continuar de onde parou" com a posição certa (${rotulo})`, textoModal);
      await ctx17.close();
    }
    ctl.semRange = false;

    // ---------------------------------------------------------------- T. erro com o visitante pausado ou no modal
    console.log('\nT. Erro do <video> com o visitante pausado ou no "continuar de onde parou?": a retentativa não retoma sozinha');
    // Pausado DEPOIS do pitch com miniatura de pausa + CTA: a miniatura (mecânica de venda) tem de sobreviver à retentativa,
    // com Range (o seek pendente devolve a posição) e sem Range (o Chromium recusa o seek; vale a posição guardada).
    const posterT = (page) => page.evaluate(() => { const r = document.getElementById('vsl-teste'); return { attr: r.getAttribute('data-pause-poster'), poster: getComputedStyle(r.querySelector('.vsl-pause-poster')).opacity, pausada: getComputedStyle(r.querySelector('.vsl-paused')).opacity }; });
    for (const comRange of [true, false]) {
      const rotulo = comRange ? 'com Range' : 'sem Range';
      ctl.semRange = !comRange;
      const ctx18 = await browser.newContext({ viewport });
      page = await ctx18.newPage();
      vigiar(page);
      await page.goto(pagina('erro-pausado', { pitch: '2', attrs: 'data-pause-poster-late="../demo/capa.jpg" data-pause-cta-text="QUERO A OFERTA" data-pause-cta-link="#oferta"' }));
      await waitState(page, 'autoplaying');
      await page.click('#vsl-teste', CANTO);
      await waitState(page, 'playing');
      await waitTime(page, 3);
      await page.click('#vsl-teste', CANTO);
      await waitState(page, 'paused');
      await sleep(400);
      const antesPT = await posterT(page);
      check(antesPT.attr === 'on' && antesPT.poster === '1' && antesPT.pausada === '0', `pausado depois do pitch (${rotulo}): miniatura de pausa com o botão na tela`, antesPT);
      const playsAntesT = (await eventos(page)).filter((n) => n === 'play').length;
      await vid(page, "v.dispatchEvent(new Event('error'))");
      await sleep(3000); // 1 s até a retentativa, mais a recarga da fonte
      const amostraT = await amostra(page);
      check(amostraT.state === 'paused' && amostraT.paused === true, `depois da retentativa continua pausado, não volta a tocar sozinho (${rotulo})`, amostraT);
      const depoisPT = await posterT(page);
      check(depoisPT.attr === 'on' && depoisPT.poster === '1' && depoisPT.pausada === '0', `depois da retentativa a miniatura de pausa com o botão continua na tela (${rotulo})`, Object.assign(depoisPT, { time: amostraT.time, lastTime: await player(page, 'player._lastTime') }));
      check((await eventos(page)).filter((n) => n === 'play').length === playsAntesT, 'nenhum evento play sem toque');
      check(await vid(page, 'v.muted') === false, 'o som liberado é mantido');
      await page.click('#vsl-teste', CANTO);
      await waitState(page, 'playing');
      await sleep(300); // amostra imediata: um vídeo que recomeça do zero ainda não chegou a 2,5 s
      const logoT = await player(page, '({ time: +player.video.currentTime.toFixed(2), lastTime: +player._lastTime.toFixed(2), seekRetry: player._seekRetry })');
      if (comRange) check(logoT.time >= 2.5, 'o toque retoma de onde tinha pausado (~3 s), não do zero', logoT);
      else check(logoT.lastTime >= 2.5 && (logoT.time >= 2.5 || logoT.seekRetry >= 2.5), 'sem Range: o seek recusado não apaga a posição guardada (~3 s)', logoT);
      check((await page.getAttribute('#vsl-teste', 'data-pause-poster')) === null, 'ao retomar, a miniatura some');
      await ctx18.close();
    }
    ctl.semRange = false;
    // no modal: 12 s salvos, erro com a pergunta aberta -> a pergunta volta e "Continuar" retoma dos 12 s
    const ctx19 = await browser.newContext({ viewport });
    await ctx19.addInitScript(() => { localStorage.setItem('vsl:vsl-teste:pos', '12'); localStorage.setItem('vsl:vsl-teste:reached', '12'); });
    page = await ctx19.newPage();
    vigiar(page);
    await page.goto(pagina('erro-modal'));
    await waitState(page, 'autoplaying');
    await page.click('#vsl-teste', CANTO);
    await waitState(page, 'modal');
    await vid(page, "v.dispatchEvent(new Event('error'))");
    await sleep(2500);
    check((await state(page)) === 'modal' && (await page.isVisible('#vsl-teste .vsl-card')), 'depois da retentativa a pergunta "continuar de onde parou?" continua na tela', await state(page));
    check(await vid(page, 'v.paused'), 'o vídeo segue pausado enquanto a pergunta está aberta');
    await page.click('#vsl-teste [data-vsl-action="continue"]');
    await waitState(page, 'playing');
    await page.waitForFunction(() => document.getElementById('vsl-teste').querySelector('video').currentTime >= 11, null, { timeout: 8000 })
      .then(() => check(true, '"Continuar" retoma dos 12 s salvos'), async () => check(false, '"Continuar" retoma dos 12 s salvos', await amostra(page)));
    check(await vid(page, 'v.muted') === false, 'com som');
    await ctx19.close();

    await browser.close();
  } catch (e) {
    failures++;
    console.log('ERRO', e);
  } finally {
    soltar();
    if (server.closeAllConnections) server.closeAllConnections();
    server.close();
  }
  console.log(`\n${failures === 0 ? 'TODOS OS TESTES PASSARAM' : failures + ' FALHA(S)'}`);
  process.exit(failures ? 1 : 0);
})();
