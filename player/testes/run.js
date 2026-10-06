// Teste do VSL Player num Chromium de verdade. Rode: node run.js (precisa de playwright e ffmpeg).
const { chromium } = require('playwright');
const { spawnSync } = require('child_process');
const fs = require('fs');
const http = require('http');
const path = require('path');

const DIR = __dirname;                 // player/testes
const ROOT = path.dirname(DIR);        // player
const PORT = 8700 + Math.floor(Math.random() * 200); // porta aleatória: não briga com servidores esquecidos
const BASE = `http://127.0.0.1:${PORT}/testes`;
const CAPTURAS = path.join(DIR, 'capturas');

// Vídeo de 30 s em WebM (o Chromium do Playwright não decodifica H.264) e as variantes da página.
function preparar() {
  const video = path.join(DIR, 'teste.webm');
  if (!fs.existsSync(video)) {
    const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'testsrc2=duration=30:size=640x360:rate=25',
      '-f', 'lavfi', '-i', 'sine=frequency=440:duration=30', '-c:v', 'libvpx-vp9', '-b:v', '400k', '-deadline', 'realtime',
      '-cpu-used', '8', '-c:a', 'libopus', video], { stdio: 'inherit' });
    if (r.status !== 0) throw new Error('ffmpeg falhou ao gerar teste.webm');
  }
  const modelo = fs.readFileSync(path.join(DIR, 'pagina.html'), 'utf8');
  const variantes = { t1: ['', 'true'], t2: ['/collect', 'true'], t3: ['', 'false'] };
  Object.entries(variantes).forEach(([nome, [analytics, autoplay]]) => {
    fs.writeFileSync(path.join(DIR, nome + '.html'), modelo.replace('__ANALYTICS__', analytics).replace('__AUTOPLAY__', autoplay));
  });
  fs.mkdirSync(CAPTURAS, { recursive: true });
}
let failures = 0;
function check(cond, msg, extra) {
  if (cond) console.log('  PASS', msg);
  else { failures++; console.log('  FAIL', msg, extra !== undefined ? JSON.stringify(extra) : ''); }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// Servidor estático mínimo para a pasta player/, com suporte a Range (o <video> precisa).
const TIPOS = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.webm': 'video/webm', '.mp4': 'video/mp4', '.png': 'image/png' };
function servidor() {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      const alvo = path.normalize(path.join(ROOT, decodeURIComponent(req.url.split('?')[0])));
      if (!alvo.startsWith(ROOT) || !fs.existsSync(alvo) || fs.statSync(alvo).isDirectory()) { res.writeHead(404); res.end(); return; }
      const tamanho = fs.statSync(alvo).size;
      const tipo = TIPOS[path.extname(alvo)] || 'application/octet-stream';
      const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
      if (range) {
        const inicio = range[1] ? parseInt(range[1], 10) : Math.max(0, tamanho - parseInt(range[2], 10));
        const fim = range[1] && range[2] ? Math.min(parseInt(range[2], 10), tamanho - 1) : tamanho - 1;
        res.writeHead(206, { 'Content-Type': tipo, 'Accept-Ranges': 'bytes', 'Content-Range': `bytes ${inicio}-${fim}/${tamanho}`, 'Content-Length': fim - inicio + 1 });
        fs.createReadStream(alvo, { start: inicio, end: fim }).pipe(res);
        return;
      }
      res.writeHead(200, { 'Content-Type': tipo, 'Accept-Ranges': 'bytes', 'Content-Length': tamanho, 'Cache-Control': 'no-store' });
      fs.createReadStream(alvo).pipe(res);
    });
    srv.listen(PORT, '127.0.0.1', () => resolve(srv));
  });
}
const state = (page, id = '#vsl-teste') => page.getAttribute(id, 'data-state');
const vid = (page, expr, id = 'vsl-teste') => page.evaluate(([id, expr]) => { const v = document.getElementById(id).querySelector('video'); return eval(expr); }, [id, expr]);
const player = (page, expr, id = 'vsl-teste') => page.evaluate(([id, expr]) => { const player = VSLPlayer.get(id); return eval(expr); }, [id, expr]);
const eventos = (page) => page.evaluate(() => window.eventos.map((e) => e.nome));
async function waitState(page, s, timeout = 8000) {
  await page.waitForFunction((s) => document.getElementById('vsl-teste').getAttribute('data-state') === s, s, { timeout });
}
async function waitTime(page, t, timeout = 15000) {
  await page.waitForFunction((t) => document.getElementById('vsl-teste').querySelector('video').currentTime >= t, t, { timeout });
}

(async () => {
  preparar();
  const server = await servidor();
  try {
    const browser = await chromium.launch();

    // ---------------------------------------------------------------- A. visita nova, autoplay permitido
    console.log('\nA. Visita nova: autoplay mudo, clique para ouvir, pausa, delay de elementos, travas');
    const ctx = await browser.newContext({ viewport: { width: 1000, height: 800 } });
    let page = await ctx.newPage();
    page.on('pageerror', (e) => { failures++; console.log('  PAGEERROR', e.message); });
    page.on('console', (m) => { if (m.type() === 'error') { failures++; console.log('  CONSOLE ERROR', m.text()); } });
    await page.goto(BASE + '/t1.html');
    await waitState(page, 'autoplaying');
    check(await vid(page, 'v.muted') === true, 'autoplay começa mudo');
    check(await vid(page, '!v.paused'), 'vídeo está tocando no autoplay');
    check(await page.isVisible('#vsl-teste .vsl-unmute'), 'overlay "clique para ouvir" visível');
    check(!(await page.isVisible('#cta')), 'elemento com data-vsl-show-at começa escondido');
    check(await page.isVisible('#aviso'), 'elemento com data-vsl-hide-at começa visível');
    check(!(await page.isVisible('#cta2')), 'elemento do segundo player começa escondido');
    await page.screenshot({ path: path.join(CAPTURAS, '01-autoplaying.png') });
    await waitTime(page, 2);
    await page.click('#vsl-teste');
    await waitState(page, 'playing');
    check(await vid(page, 'v.muted') === false, 'ao clicar, vídeo fica com som');
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
    check(ev.includes('pitch'), 'evento pitch disparado aos 5s');
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
    await page.click('#vsl-teste');
    await waitState(page, 'paused');
    check(await vid(page, 'v.paused'), 'clique pausa o vídeo');
    await page.waitForSelector('#vsl-teste .vsl-paused', { state: 'visible', timeout: 3000 }).then(() => check(true, 'overlay de pausa visível'), () => check(false, 'overlay de pausa visível'));
    await sleep(400);
    await page.screenshot({ path: path.join(CAPTURAS, '02-paused.png') });
    const pos = await page.evaluate(() => parseFloat(localStorage.getItem('vsl:vsl-teste:pos')));
    check(pos > 5, 'posição salva no localStorage ao pausar', pos);
    await page.click('#vsl-teste');
    await waitState(page, 'playing');
    check(await vid(page, '!v.paused'), 'clique retoma o vídeo');
    await page.click('#vsl-teste');
    await waitState(page, 'paused');
    const posSalva = await page.evaluate(() => parseFloat(localStorage.getItem('vsl:vsl-teste:pos')));
    // segundo player (autoplay off) e elemento com escopo
    check((await state(page, '#vsl-segundo')) === 'idle', 'segundo player com autoplay=false fica em idle');
    await page.click('#vsl-segundo');
    await page.waitForFunction(() => document.getElementById('vsl-segundo').getAttribute('data-state') === 'playing');
    check(await vid(page, 'v.muted', 'vsl-segundo') === false, 'segundo player toca com som ao clicar');
    await page.waitForFunction(() => document.getElementById('vsl-segundo').querySelector('video').currentTime >= 2.2);
    await sleep(300);
    check(await page.isVisible('#cta2'), 'elemento com data-vsl-player aparece pelo segundo player');
    await page.click('#vsl-segundo');

    // ---------------------------------------------------------------- B. volta: continuar de onde parou
    console.log('\nB. Segunda visita: elementos persistidos e "continuar de onde parou"');
    await page.goto(BASE + '/t1.html');
    await waitState(page, 'autoplaying');
    check(await page.isVisible('#cta'), 'elemento show-at já aparece ao recarregar (persistido)');
    check(!(await page.isVisible('#aviso')), 'elemento hide-at continua escondido ao recarregar');
    check(!(await eventos(page)).includes('pitch'), 'pitch não dispara de novo para o mesmo visitante');
    await page.click('#vsl-teste');
    await waitState(page, 'modal');
    check(await vid(page, 'v.paused'), 'vídeo pausa enquanto a pergunta está aberta');
    await page.waitForSelector('#vsl-teste .vsl-card', { state: 'visible', timeout: 3000 }).then(() => check(true, 'pergunta "continuar de onde parou" visível'), () => check(false, 'pergunta "continuar de onde parou" visível'));
    await sleep(400);
    await page.screenshot({ path: path.join(CAPTURAS, '03-modal.png') });
    await page.click('#vsl-teste [data-vsl-action="continue"]');
    await waitState(page, 'playing');
    await sleep(500);
    const retomado = await vid(page, 'v.currentTime');
    check(Math.abs(retomado - posSalva) < 2.5, 'continua de onde parou', { retomado, posSalva });
    check(await vid(page, 'v.muted') === false, 'retomada com som');
    await page.click('#vsl-teste');
    await waitState(page, 'paused');

    console.log('\nC. Terceira visita: começar do início');
    await page.goto(BASE + '/t1.html');
    await waitState(page, 'autoplaying');
    await page.click('#vsl-teste');
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
    await page.waitForSelector('#vsl-teste .vsl-ended', { state: 'visible', timeout: 3000 }).then(() => check(true, 'tela de "assistir novamente" visível'), () => check(false, 'tela de "assistir novamente" visível'));
    await sleep(400);
    check((await page.evaluate(() => localStorage.getItem('vsl:vsl-teste:pos'))) === null, 'posição apagada ao terminar');
    ev = await eventos(page);
    check(ev.includes('ended'), 'evento ended disparado');
    check((await page.evaluate(() => window.eventos.filter((e) => e.nome === 'milestone').map((e) => e.detail.percent))).includes(100), 'milestone 100%');
    await page.screenshot({ path: path.join(CAPTURAS, '04-ended.png') });
    await page.click('#vsl-teste');
    await waitState(page, 'playing');
    await sleep(400);
    check((await vid(page, 'v.currentTime')) < 1.5, 'clique no fim recomeça do zero');
    check((await eventos(page)).includes('replay'), 'evento replay');
    await ctx.close();

    // ---------------------------------------------------------------- E. autoplay bloqueado
    console.log('\nE. Autoplay bloqueado pelo navegador');
    const ctx2 = await browser.newContext({ viewport: { width: 1000, height: 800 } });
    await ctx2.addInitScript(() => {
      const original = HTMLMediaElement.prototype.play;
      let blocked = false;
      HTMLMediaElement.prototype.play = function () {
        if (!blocked) { blocked = true; return Promise.reject(new DOMException('blocked', 'NotAllowedError')); }
        return original.call(this);
      };
    });
    page = await ctx2.newPage();
    page.on('pageerror', (e) => { failures++; console.log('  PAGEERROR', e.message); });
    await page.goto(BASE + '/t1.html');
    await waitState(page, 'idle');
    await page.waitForSelector('#vsl-teste .vsl-idle', { state: 'visible', timeout: 3000 }).then(() => check(true, 'capa com botão de play visível'), () => check(false, 'capa com botão de play visível'));
    await sleep(400);
    check((await eventos(page)).includes('autoplay_blocked'), 'evento autoplay_blocked');
    await page.screenshot({ path: path.join(CAPTURAS, '05-idle.png') });
    await page.click('#vsl-teste');
    await waitState(page, 'playing');
    check(await vid(page, 'v.muted') === false, 'clique na capa toca com som');
    await ctx2.close();

    // ---------------------------------------------------------------- F. analytics
    console.log('\nF. Envio de analytics');
    const ctx3 = await browser.newContext({ viewport: { width: 1000, height: 800 } });
    page = await ctx3.newPage();
    page.on('pageerror', (e) => { failures++; console.log('  PAGEERROR', e.message); });
    const envios = [];
    await page.route('**/collect', (route) => {
      const req = route.request();
      envios.push({ method: req.method(), body: req.postData(), type: req.resourceType() });
      route.fulfill({ status: 204 });
    });
    await page.goto(BASE + '/t2.html');
    await waitState(page, 'autoplaying');
    await waitTime(page, 8);            // 8 s no mudo: não podem contar como assistidos
    await page.click('#vsl-teste');     // recomeça do zero, com som
    await waitState(page, 'playing');
    await waitTime(page, 3);
    await sleep(300);
    await player(page, 'player.tracker.flush()');
    await sleep(500);
    check(envios.length >= 1, 'requisições recebidas no endpoint', envios.length);
    const ultimo = envios.length ? JSON.parse(envios[envios.length - 1].body) : null;
    check(ultimo && ultimo.player === 'vsl-teste' && ultimo.visitor && ultimo.session, 'payload traz player, visitor e session', ultimo && Object.keys(ultimo));
    check(ultimo && ultimo.pitch === 5, 'payload traz o tempo do pitch', ultimo && ultimo.pitch);
    check(ultimo && ultimo.watched.length >= 1 && ultimo.watched[0][0] === 0, 'faixas de retenção acumuladas', ultimo && ultimo.watched);
    const fim = ultimo ? Math.max(...ultimo.watched.map((f) => f[1])) : -1;
    check(ultimo && fim >= 2 && fim <= 5 && ultimo.maxTime <= 6 && ultimo.reached >= 7, 'retenção e maxTime contam só o trecho com som; reached guarda o mudo', ultimo && { watched: ultimo.watched, maxTime: ultimo.maxTime, reached: ultimo.reached });
    check(ultimo && ultimo.events.every((e) => typeof e.seq === 'number'), 'eventos levam um contador seq');
    const tipos = envios.flatMap((e) => JSON.parse(e.body).events.map((ev) => ev.type));
    check(tipos.includes('unmute') && tipos.includes('pitch'), 'eventos unmute e pitch enviados', tipos);
    console.log('  info: tipo da requisição =', envios.map((e) => e.type + '/' + e.method).join(', '));
    await ctx3.close();

    // ---------------------------------------------------------------- G. autoplay desligado + celular
    console.log('\nG. Autoplay desligado e tela de celular');
    const ctx4 = await browser.newContext({ viewport: { width: 375, height: 740 }, isMobile: true, hasTouch: true });
    page = await ctx4.newPage();
    page.on('pageerror', (e) => { failures++; console.log('  PAGEERROR', e.message); });
    await page.goto(BASE + '/t3.html');
    await waitState(page, 'idle');
    check(await vid(page, 'v.paused'), 'autoplay=false não toca sozinho');
    await page.screenshot({ path: path.join(CAPTURAS, '06-mobile-idle.png') });
    await page.tap('#vsl-teste');
    await waitState(page, 'playing');
    check(await vid(page, 'v.muted') === false, 'toque no celular toca com som');
    await page.tap('#vsl-teste');
    await waitState(page, 'paused');
    await page.screenshot({ path: path.join(CAPTURAS, '07-mobile-paused.png') });
    await ctx4.close();

    // ---------------------------------------------------------------- H. modo de revisão
    console.log('\nH. Modo de revisão (só com a chave)');
    const ctx5 = await browser.newContext({ viewport: { width: 1000, height: 800 } });
    page = await ctx5.newPage();
    page.on('pageerror', (e) => { failures++; console.log('  PAGEERROR', e.message); });
    await page.goto(BASE + '/t1.html?revisar=errada');
    await waitState(page, 'autoplaying');
    check((await page.$('#vsl-teste .vsl-review')) === null, 'chave errada não mostra a barra');
    check(await page.evaluate(() => document.querySelector('link[rel="preconnect"]') === null), 'sem preconnect para vídeo da mesma origem');
    await page.goto(BASE + '/t1.html?revisar=chave-secreta');
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
    await page.goto(BASE + '/t1.html');
    await waitState(page, 'autoplaying');
    check((await page.$('#vsl-teste .vsl-review')) !== null, 'o modo continua na mesma aba sem repetir a chave na URL');
    await ctx5.close();

    await browser.close();
  } catch (e) {
    failures++;
    console.log('ERRO', e);
  } finally {
    server.close();
  }
  console.log(`\n${failures === 0 ? 'TODOS OS TESTES PASSARAM' : failures + ' FALHA(S)'}`);
  process.exit(failures ? 1 : 0);
})();
