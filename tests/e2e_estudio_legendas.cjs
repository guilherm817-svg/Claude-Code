// Teste das legendas automáticas num Chromium de verdade: ligar as legendas, receber a transcrição (de um Whisper
// falso, ver tests/servidor_teste_estudio.py), ver a legenda na prévia, corrigir uma palavra, exportar e conferir
// que o vídeo tem a mesma legenda da prévia. Rode na raiz do projeto: node tests/e2e_estudio_legendas.cjs
// (precisa do playwright e do .venv; com o playwright global, use NODE_PATH="$(npm root -g)").
// Com CAPTURAS=<pasta>, guarda as imagens da prévia e do vídeo exportado para olhar.
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
const TEMP = fs.mkdtempSync(path.join(os.tmpdir(), 'estudio-e2e-legendas-'));
const CAPTURAS = process.env.CAPTURAS ? path.resolve(process.env.CAPTURAS) : null;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let falhas = 0;
function conferir(condicao, mensagem, extra) {
  if (condicao) console.log('  PASS', mensagem);
  else { falhas++; console.log('  FAIL', mensagem, extra !== undefined ? JSON.stringify(extra) : ''); }
}

// Um clipe falado (voz sintética do espeak-ng, se houver) sobre um fundo liso, em WebM: o Chromium do Playwright
// não decodifica H.264.
function gerarClipe() {
  const ffmpeg = spawnSync(PYTHON, ['-c', 'from estudio.midia import ffmpeg; print(ffmpeg())'], { cwd: RAIZ, encoding: 'utf8' }).stdout.trim();
  const voz = path.join(TEMP, 'voz.wav');
  const espeak = spawnSync('espeak-ng', ['-v', 'pt-br', '-s', '140', '-w', voz, 'Isso muda tudo agora.']);
  const audio = espeak.status === 0 ? ['-i', voz] : ['-f', 'lavfi', '-i', 'sine=f=300:d=1.6,volume=0.3'];
  const destino = path.join(TEMP, 'Bloco 1.webm');
  const r = spawnSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x22324a:s=720x1280:r=30:d=4', ...audio,
    '-f', 'lavfi', '-i', 'anoisesrc=d=4:a=0.002', '-filter_complex', '[1:a]adelay=500|500,apad=whole_dur=4[v1];[v1][2:a]amix=inputs=2:normalize=0[a]',
    '-map', '0:v', '-map', '[a]', '-c:v', 'libvpx-vp9', '-b:v', '300k', '-deadline', 'realtime', '-cpu-used', '8',
    '-c:a', 'libopus', '-t', '4', destino], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error('ffmpeg falhou ao gerar o clipe');
  return destino;
}

// Quadro do vídeo exportado no instante t, reduzido para o tamanho da prévia (rgb24).
function quadroExportado(arquivo, t, largura, altura) {
  const codigo = 'import subprocess, sys\nfrom estudio.midia import ffmpeg\n'
    + 'r = subprocess.run([ffmpeg(), "-v", "error", "-ss", sys.argv[2], "-i", sys.argv[1], "-frames:v", "1", "-vf", '
    + 'f"scale={sys.argv[3]}:{sys.argv[4]}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)\n'
    + 'sys.stdout.buffer.write(r.stdout)';
  const r = spawnSync(PYTHON, ['-c', codigo, arquivo, t.toFixed(3), String(largura), String(altura)], { cwd: RAIZ, maxBuffer: 64 * 1024 * 1024 });
  if (r.status !== 0) throw new Error(`não consegui ler o quadro exportado: ${r.stderr}`);
  return r.stdout;
}

// Máscaras da legenda: 2 = amarelo, 1 = branco, 0 = o resto. Contadas só na faixa de baixo, onde a legenda fica.
function mascara(pixels, canais, largura, altura) {
  const classes = new Uint8Array(largura * altura);
  for (let i = 0; i < largura * altura; i++) {
    const r = pixels[i * canais]; const g = pixels[i * canais + 1]; const b = pixels[i * canais + 2];
    if (r > 190 && g > 150 && b < 110) classes[i] = 2;
    else if (r > 200 && g > 200 && b > 200) classes[i] = 1;
  }
  return classes;
}

function contar(classes, largura, altura) {
  const conta = { amarelo: 0, branco: 0 };
  for (let y = Math.floor(altura * 0.55); y < Math.floor(altura * 0.75); y++) {
    for (let x = 0; x < largura; x++) {
      const c = classes[y * largura + x];
      if (c === 2) conta.amarelo++;
      else if (c === 1) conta.branco++;
    }
  }
  return conta;
}

function iou(a, b, classe) {
  let juntos = 0; let algum = 0;
  for (let i = 0; i < a.length; i++) {
    const x = a[i] === classe; const y = b[i] === classe;
    if (x && y) juntos++;
    if (x || y) algum++;
  }
  return algum ? juntos / algum : 1;
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
  const clipe = gerarClipe();
  if (CAPTURAS) fs.mkdirSync(CAPTURAS, { recursive: true });
  const servidor = spawn(PYTHON, [path.join(RAIZ, 'tests', 'servidor_teste_estudio.py'), '--porta', String(PORTA)], {
    cwd: RAIZ, env: { ...process.env, ESTUDIO_PASTA_DADOS: path.join(TEMP, 'dados') }, stdio: 'inherit',
  });
  const navegador = await chromium.launch();
  try {
    await esperarServidor();
    const pagina = await navegador.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, acceptDownloads: true });
    const erros = [];
    pagina.on('pageerror', (e) => erros.push(e.message));
    pagina.on('console', (m) => { if (m.type() === 'error') erros.push(m.text()); });
    pagina.on('dialog', (d) => d.accept());
    const projeto = () => pagina.evaluate(async () => {
      const [primeiro] = await (await fetch('/api/projetos')).json();
      return (await fetch(`/api/projetos/${primeiro.id}`)).json();
    });
    const esperarSalvo = () => pagina.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Tudo salvo');
    const capturar = async (nome) => {
      if (CAPTURAS) await (await pagina.$('#previa-quadro')).screenshot({ path: path.join(CAPTURAS, nome) });
    };
    // Leva a agulha até t (segundos), um quadro de cada vez a partir do começo.
    const irPara = async (t) => {
      await pagina.evaluate(() => document.activeElement?.blur());
      await pagina.keyboard.press('Home');
      for (let i = 0; i < Math.round(t * 30); i++) await pagina.keyboard.press('ArrowRight');
      await sleep(700);
    };
    const pixelsDaPrevia = () => pagina.evaluate(() => {
      const canvas = document.querySelector('#previa');
      const dados = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
      return { largura: canvas.width, altura: canvas.height, rgba: Array.from(dados) };
    });
    const legendaNaPrevia = async () => {
      const p = await pixelsDaPrevia();
      const classes = mascara(p.rgba, 4, p.largura, p.altura);
      return { ...contar(classes, p.largura, p.altura), classes, largura: p.largura, altura: p.altura };
    };

    console.log('Ligar as legendas');
    await pagina.goto(BASE);
    await pagina.setInputFiles('#arquivos', [clipe]);
    await pagina.waitForFunction(() => document.querySelectorAll('.clipe').length === 1, null, { timeout: 60000 });
    await esperarSalvo();
    conferir(await pagina.isVisible('text=Na primeira vez, o Estúdio baixa o modelo de transcrição'), 'avisa que a primeira vez baixa o modelo');
    await pagina.click('.chave-legendas input');
    await pagina.waitForFunction(() => document.querySelector('.estilos-legenda'), null, { timeout: 30000 });
    await pagina.waitForSelector('text=Legendas prontas', { timeout: 60000 });
    await esperarSalvo();
    let p = await projeto();
    const midia = p.midias[0];
    const item = p.linha[0];
    const palavras = p.legendas[midia.id];
    conferir(p.legendas_ativas && palavras?.map((w) => w.texto).join(' ') === 'Isso muda tudo agora', 'a transcrição chega e fica salva no projeto', palavras);

    console.log('Legenda na prévia');
    const muda = palavras[1];
    const t = (muda.inicio + muda.fim) / 2 - item.entrada; // no meio de "muda", já depois do pop da tela
    await irPara(t);
    let antes = await legendaNaPrevia();
    await capturar('1-previa.png');
    conferir(antes.amarelo > 800 && antes.branco > 800, 'a prévia mostra a legenda, com a palavra falada em amarelo', { amarelo: antes.amarelo, branco: antes.branco });
    const tela = await pagina.textContent('#tempo-atual');
    conferir(Math.abs(Number(tela.split(':')[1]) - t) < 0.06, 'a agulha está no meio da palavra', { tela, t });

    console.log('Corrigir uma palavra');
    const caixa = await (await pagina.$('.clipe')).boundingBox();
    await pagina.mouse.click(caixa.x + 30, caixa.y + 30);
    await pagina.waitForSelector('.legenda-texto');
    conferir(await pagina.inputValue('.legenda-texto') === 'Isso muda tudo agora', 'o painel do clipe mostra o texto transcrito');
    await pagina.fill('.legenda-texto', 'Isso mudou tudo agora');
    await pagina.evaluate(() => document.activeElement.blur());
    await esperarSalvo();
    p = await projeto();
    const corrigidas = p.legendas[midia.id];
    conferir(corrigidas.map((w) => w.texto).join(' ') === 'Isso mudou tudo agora'
      && corrigidas.every((w, i) => w.inicio === palavras[i].inicio && w.fim === palavras[i].fim), 'a correção é salva e cada palavra mantém o tempo', corrigidas);
    await irPara(t);
    const depois = await legendaNaPrevia();
    await capturar('2-previa-corrigida.png');
    conferir(depois.amarelo > antes.amarelo * 1.15, 'a prévia mostra a palavra corrigida (MUDOU é mais larga que MUDA)', { antes: antes.amarelo, depois: depois.amarelo });

    await pagina.keyboard.press('Control+z');
    await esperarSalvo();
    conferir((await projeto()).legendas[midia.id][1].texto === 'muda', 'Ctrl+Z desfaz a correção');
    await pagina.keyboard.press('Control+Shift+z');
    await esperarSalvo();
    conferir((await projeto()).legendas[midia.id][1].texto === 'mudou', 'Ctrl+Shift+Z refaz a correção');

    console.log('Trocar o estilo');
    await pagina.keyboard.press('Escape');
    await pagina.click('.estilo-legenda:has-text("Uma palavra")');
    await esperarSalvo();
    conferir((await projeto()).estilo_legenda.preset === 'uma_palavra', 'escolher o cartão "Uma palavra" muda o estilo');
    await irPara(t);
    const umaPalavra = await legendaNaPrevia();
    await capturar('3-uma-palavra.png');
    conferir(umaPalavra.amarelo > depois.amarelo && umaPalavra.branco < 50, 'a prévia passa a mostrar só a palavra, grande e amarela', umaPalavra.amarelo);
    await pagina.click('.estilo-legenda:has-text("Destaque")');
    await esperarSalvo();

    console.log('Exportar');
    await pagina.click('#btn-exportar');
    conferir((await pagina.textContent('#exportar-resumo')).includes('Legendasligadas'), 'o resumo da exportação mostra as legendas ligadas');
    await pagina.click('#btn-iniciar-exportacao');
    await pagina.waitForSelector('#exportar-pronto:not([hidden])', { timeout: 180000 });
    const [download] = await Promise.all([pagina.waitForEvent('download'), pagina.click('#link-baixar')]);
    const baixado = path.join(TEMP, 'baixado.mp4');
    await download.saveAs(baixado);
    await pagina.click('#btn-fechar-exportacao');

    await irPara(t);
    const previa = await legendaNaPrevia();
    const quadro = quadroExportado(baixado, t, previa.largura, previa.altura);
    const exportada = mascara(quadro, 3, previa.largura, previa.altura);
    const noVideo = contar(exportada, previa.largura, previa.altura);
    conferir(noVideo.amarelo > 800 && noVideo.branco > 800, 'o vídeo exportado tem a legenda, com a palavra falada em amarelo', noVideo);
    const semelhanca = { amarelo: iou(previa.classes, exportada, 2), branco: iou(previa.classes, exportada, 1) };
    conferir(semelhanca.amarelo > 0.75 && semelhanca.branco > 0.75, 'a legenda do vídeo coincide com a da prévia no mesmo instante '
      + `(sobreposição: amarelo ${semelhanca.amarelo.toFixed(2)}, branco ${semelhanca.branco.toFixed(2)})`, semelhanca);
    if (CAPTURAS) {
      await capturar('4-previa-na-exportacao.png');
      const ppm = Buffer.concat([Buffer.from(`P6 ${previa.largura} ${previa.altura} 255\n`), quadro]);
      fs.writeFileSync(path.join(CAPTURAS, '4-video-exportado.ppm'), ppm);
    }
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
