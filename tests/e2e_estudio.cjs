// Teste do Estúdio de Reels num Chromium de verdade: importar, tocar, cortar, desfazer, dividir, reordenar e
// exportar. Rode na raiz do projeto: node tests/e2e_estudio.cjs (precisa do playwright e do .venv instalado;
// se o playwright estiver instalado globalmente, use NODE_PATH="$(npm root -g)").
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const RAIZ = path.dirname(__dirname);
const PYTHON = process.env.PYTHON || [path.join(RAIZ, '.venv', 'bin', 'python'), path.join(RAIZ, '.venv', 'Scripts', 'python.exe')]
  .find((p) => fs.existsSync(p)) || 'python3';
const PORTA = 8700 + Math.floor(Math.random() * 200);
const BASE = `http://127.0.0.1:${PORTA}`;
const TEMP = fs.mkdtempSync(path.join(os.tmpdir(), 'estudio-e2e-'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let falhas = 0;
function conferir(condicao, mensagem, extra) {
  if (condicao) console.log('  PASS', mensagem);
  else { falhas++; console.log('  FAIL', mensagem, extra !== undefined ? JSON.stringify(extra) : ''); }
}

// O Chromium do Playwright não decodifica H.264, então os clipes de teste são WebM (o Estúdio aceita os dois).
function gerarClipes() {
  const ffmpeg = spawnSync(PYTHON, ['-c', 'from estudio.midia import ffmpeg; print(ffmpeg())'], { cwd: RAIZ, encoding: 'utf8' }).stdout.trim();
  const clipes = [
    ['Bloco 1.webm', '720x1280', 24, 4, 600, 2.2, 300, 'testsrc2'],
    ['Bloco 2.webm', '720x1280', 24, 5, 300, 3.6, 420, 'smptehdbars'],
    ['Bloco 10 horizontal.webm', '1280x720', 30, 3, 0, 2.9, 520, 'testsrc'],
  ];
  return clipes.map(([nome, tamanho, fps, dur, atraso, fala, freq, fonte]) => {
    const destino = path.join(TEMP, nome);
    const r = spawnSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i', `${fonte}=s=${tamanho}:r=${fps}:d=${dur}`,
      '-f', 'lavfi', '-i', `sine=f=${freq}:d=${fala},adelay=${atraso}|${atraso},apad=whole_dur=${dur},volume=0.25`,
      '-f', 'lavfi', '-i', `anoisesrc=d=${dur}:a=0.002`, '-filter_complex', '[1:a][2:a]amix=inputs=2:normalize=0[a]',
      '-map', '0:v', '-map', '[a]', '-c:v', 'libvpx-vp9', '-b:v', '500k', '-deadline', 'realtime', '-cpu-used', '8',
      '-c:a', 'libopus', '-t', String(dur), destino], { stdio: 'inherit' });
    if (r.status !== 0) throw new Error(`ffmpeg falhou ao gerar ${nome}`);
    return destino;
  });
}

async function esperarServidor() {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${BASE}/api/projetos`)).ok) return;
    } catch { /* ainda subindo */ }
    await sleep(100);
  }
  throw new Error('O servidor do Estúdio não respondeu.');
}

(async () => {
  const clipes = gerarClipes();
  const servidor = spawn(PYTHON, ['-m', 'estudio', '--sem-navegador', '--porta', String(PORTA)], {
    cwd: RAIZ, env: { ...process.env, ESTUDIO_PASTA_DADOS: path.join(TEMP, 'dados') }, stdio: 'inherit',
  });
  const navegador = await chromium.launch();
  try {
    await esperarServidor();
    const pagina = await navegador.newPage({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
    const erros = [];
    pagina.on('pageerror', (e) => erros.push(e.message));
    pagina.on('console', (m) => { if (m.type() === 'error') erros.push(m.text()); });
    pagina.on('dialog', (d) => d.accept());
    const projeto = () => pagina.evaluate(async () => {
      const [primeiro] = await (await fetch('/api/projetos')).json();
      return (await fetch(`/api/projetos/${primeiro.id}`)).json();
    });
    const esperarSalvo = () => pagina.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Tudo salvo');

    console.log('Importar');
    await pagina.goto(BASE);
    await pagina.waitForSelector('#previa-vazia:not([hidden])');
    await pagina.setInputFiles('#arquivos', clipes);
    await pagina.waitForFunction(() => document.querySelectorAll('.clipe').length === 3, null, { timeout: 60000 });
    await esperarSalvo();
    let p = await projeto();
    const nomes = (proj) => proj.linha.map((i) => proj.midias.find((m) => m.id === i.midia_id).nome);
    conferir(nomes(p).join('|') === 'Bloco 1.webm|Bloco 2.webm|Bloco 10 horizontal.webm', 'clipes em ordem natural (2 antes de 10)', nomes(p));
    conferir(Math.abs(p.linha[0].entrada - 0.47) < 0.05 && Math.abs(p.linha[0].saida - 3.06) < 0.05, 'silêncio do começo e do fim cortado', p.linha[0]);
    conferir(await pagina.isHidden('#previa-vazia'), 'prévia sai do estado vazio');

    console.log('Tocar');
    await pagina.click('#btn-tocar');
    await sleep(3000);
    await pagina.click('#btn-tocar');
    const tempo = await pagina.textContent('#tempo-atual');
    conferir(tempo >= '0:02.5' && tempo <= '0:03.5', 'a prévia toca e passa do primeiro para o segundo clipe', tempo);

    console.log('Cortar arrastando a borda e desfazer');
    let clipe = (await pagina.$$('.clipe'))[0];
    await clipe.click({ position: { x: 40, y: 30 } });
    const alca = await (await pagina.$('.clipe.selecionado .alca.fim')).boundingBox();
    await pagina.mouse.move(alca.x + 5, alca.y + 40);
    await pagina.mouse.down();
    await pagina.mouse.move(alca.x - 60, alca.y + 40, { steps: 6 });
    await pagina.mouse.up();
    await esperarSalvo();
    const saidaAntes = p.linha[0].saida;
    p = await projeto();
    conferir(p.linha[0].saida < saidaAntes - 0.3, 'arrastar a borda corta o fim e salva', p.linha[0].saida);
    await pagina.keyboard.press('Control+z');
    await esperarSalvo();
    p = await projeto();
    conferir(Math.abs(p.linha[0].saida - saidaAntes) < 0.001, 'Ctrl+Z desfaz o corte', p.linha[0].saida);

    console.log('Dividir e reordenar');
    clipe = (await pagina.$$('.clipe'))[1];
    const caixa = await clipe.boundingBox();
    await pagina.mouse.click(caixa.x + caixa.width / 2, caixa.y + 30);
    await pagina.keyboard.press('s');
    await esperarSalvo();
    p = await projeto();
    conferir(p.linha.length === 4 && p.linha[1].saida === p.linha[2].entrada, 'S divide o clipe na agulha', p.linha);
    const todos = await pagina.$$('.clipe');
    const ultimo = await todos[todos.length - 1].boundingBox();
    const primeiro = await todos[0].boundingBox();
    await pagina.mouse.move(ultimo.x + ultimo.width / 2, ultimo.y + 30);
    await pagina.mouse.down();
    await pagina.mouse.move(primeiro.x + 10, primeiro.y + 30, { steps: 12 });
    await pagina.mouse.up();
    await esperarSalvo();
    p = await projeto();
    conferir(nomes(p)[0] === 'Bloco 10 horizontal.webm', 'arrastar leva o clipe para o começo', nomes(p));

    console.log('Exportar');
    await pagina.keyboard.press('Escape');
    await pagina.click('text=Fundo desfocado');
    await esperarSalvo();
    await pagina.click('#btn-exportar');
    await pagina.click('#btn-iniciar-exportacao');
    await pagina.waitForSelector('#exportar-pronto:not([hidden])', { timeout: 180000 });
    const [download] = await Promise.all([pagina.waitForEvent('download'), pagina.click('#link-baixar')]);
    const baixado = path.join(TEMP, 'baixado.mp4');
    await download.saveAs(baixado);
    const sonda = spawnSync(PYTHON, ['-c', 'import sys; from estudio.midia import sondar; i = sondar(sys.argv[1]); print(i.largura, i.altura, i.duracao)', baixado],
      { cwd: RAIZ, encoding: 'utf8' }).stdout.trim().split(' ').map(Number);
    const esperado = p.linha.reduce((soma, i) => soma + i.saida - i.entrada, 0);
    conferir(sonda[0] === 1080 && sonda[1] === 1920, 'vídeo exportado em 1080×1920', sonda);
    conferir(Math.abs(sonda[2] - esperado) < 0.1, 'duração do vídeo = soma dos cortes', { sonda: sonda[2], esperado });
    conferir(erros.length === 0, 'nenhum erro no console', erros);
  } catch (erro) {
    falhas++;
    console.log('  FAIL', erro.message);
  } finally {
    await navegador.close();
    servidor.kill();
    fs.rmSync(TEMP, { recursive: true, force: true });
  }
  console.log(falhas ? `\n${falhas} falha(s)` : '\nTudo certo');
  process.exit(falhas ? 1 : 0);
})();
