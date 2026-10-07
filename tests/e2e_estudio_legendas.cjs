// Teste das legendas automáticas num Chromium de verdade: ligar as legendas, receber a transcrição (de um Whisper
// falso, ver tests/servidor_teste_estudio.py), ver a legenda na prévia, corrigir uma palavra, exportar e conferir
// que o vídeo tem a mesma legenda da prévia. Depois, corrigir o texto e ir direto para outra ação sem sair do campo
// (recarregar, desfazer, tirar o clipe, trocar de projeto) e recarregar a página no meio de uma transcrição.
// Rode na raiz do projeto: node tests/e2e_estudio_legendas.cjs
// (precisa do playwright e do .venv; com o playwright global, use NODE_PATH="$(npm root -g)").
// Com CAPTURAS=<pasta>, guarda as imagens da prévia e do vídeo exportado para olhar.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');

const RAIZ = path.dirname(__dirname);
const PYTHON = process.env.PYTHON || [path.join(RAIZ, '.venv', 'bin', 'python'), path.join(RAIZ, '.venv', 'Scripts', 'python.exe')]
  .find((p) => fs.existsSync(p)) || 'python3';
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

// Uma porta livre, escolhida pelo sistema: com outro teste rodando junto, cada um fala com o seu servidor.
function portaLivre() {
  return new Promise((resolver, rejeitar) => {
    const sonda = net.createServer().once('error', rejeitar);
    sonda.listen(0, '127.0.0.1', () => {
      const { port } = sonda.address();
      sonda.close(() => resolver(port));
    });
  });
}

function subirServidor(porta, pasta, ...extra) {
  return spawn(PYTHON, [path.join(RAIZ, 'tests', 'servidor_teste_estudio.py'), '--porta', String(porta), ...extra], {
    cwd: RAIZ, env: { ...process.env, ESTUDIO_PASTA_DADOS: path.join(TEMP, pasta) }, stdio: 'inherit',
  });
}

async function esperarServidor(base) {
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${base}/api/projetos`)).ok) return;
    } catch { /* ainda subindo */ }
    await sleep(100);
  }
  throw new Error('O servidor do Estúdio não respondeu.');
}

(async () => {
  const clipe = gerarClipe();
  if (CAPTURAS) fs.mkdirSync(CAPTURAS, { recursive: true });
  const porta = await portaLivre();
  const base = `http://127.0.0.1:${porta}`;
  const servidores = [subirServidor(porta, 'dados')];
  const navegador = await chromium.launch();
  try {
    await esperarServidor(base);
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
    await pagina.goto(base);
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

    // Daqui em diante o campo do texto nunca perde o foco por conta do teste: é o que acontece quando a pessoa
    // corrige uma palavra e vai direto para outra ação.
    console.log('Corrigir sem sair do campo');
    const projetoId = p.id;
    const projetoDe = (id) => pagina.evaluate(async (i) => (await fetch(`/api/projetos/${i}`)).json(), id);
    const textoDe = (proj) => (proj.legendas[midia.id] || []).map((w) => w.texto).join(' ');
    const textoNoServidor = async () => textoDe(await projetoDe(projetoId));
    const selecionarClipe = async () => {
      const caixa = await (await pagina.$('.clipe')).boundingBox();
      await pagina.mouse.click(caixa.x + 30, caixa.y + 30);
      await pagina.waitForSelector('.legenda-texto');
    };
    const focoNoTexto = () => pagina.evaluate(() => !!document.activeElement?.classList.contains('legenda-texto'));
    const esperarNoServidor = async (texto) => {
      for (let i = 0; i < 100 && await textoNoServidor() !== texto; i++) await sleep(100);
      return textoNoServidor();
    };

    await selecionarClipe();
    await pagina.fill('.legenda-texto', 'Isso virou tudo agora');
    conferir(await esperarNoServidor('Isso virou tudo agora') === 'Isso virou tudo agora' && await focoNoTexto(),
      'a correção é salva enquanto se digita, com o cursor ainda no campo', await textoNoServidor());
    await esperarSalvo();

    await pagina.fill('.legenda-texto', 'Isso ficou tudo agora');
    await pagina.reload();
    await pagina.waitForSelector('.clipe');
    conferir(await esperarNoServidor('Isso ficou tudo agora') === 'Isso ficou tudo agora', 'recarregar a página logo depois de digitar não perde a correção', await textoNoServidor());

    await selecionarClipe();
    await pagina.fill('.legenda-texto', 'Isso mudou tudo agora');
    conferir(await pagina.isEnabled('#btn-desfazer'), 'o botão Desfazer já vale para o que está sendo digitado');
    await pagina.click('#btn-desfazer', { timeout: 5000 }).catch(() => {});
    await esperarSalvo();
    conferir(await pagina.inputValue('.legenda-texto') === 'Isso ficou tudo agora' && await textoNoServidor() === 'Isso ficou tudo agora',
      'o botão Desfazer desfaz a correção que estava sendo digitada, no campo e no projeto',
      { campo: await pagina.inputValue('.legenda-texto'), servidor: await textoNoServidor() });
    conferir(await pagina.isEnabled('#btn-refazer'), 'depois de desfazer, o Refazer fica disponível');
    await pagina.click('#btn-refazer', { timeout: 5000 }).catch(() => {});
    await esperarSalvo();
    conferir(await pagina.inputValue('.legenda-texto') === 'Isso mudou tudo agora' && await textoNoServidor() === 'Isso mudou tudo agora',
      'o Refazer devolve a correção', { campo: await pagina.inputValue('.legenda-texto'), servidor: await textoNoServidor() });

    await pagina.fill('.legenda-texto', 'Isso mudou tudo hoje');
    await pagina.click('.linha-ferramentas button:has-text("Tirar")');
    await esperarSalvo();
    let salvo = await projetoDe(projetoId);
    conferir(!(await pagina.$('.legenda-texto')) && (await pagina.textContent('#inspetor .painel-titulo')).startsWith('Projeto'),
      'tirar o clipe com o cursor no texto atualiza o painel (não fica o clipe que saiu)', await pagina.textContent('#inspetor .painel-titulo'));
    conferir(salvo.linha.length === 0 && textoDe(salvo) === 'Isso mudou tudo hoje', 'a correção e a retirada do clipe ficam salvas',
      { linha: salvo.linha.length, texto: textoDe(salvo) });
    await pagina.keyboard.press('Control+z');
    await esperarSalvo();
    salvo = await projetoDe(projetoId);
    conferir(salvo.linha.length === 1 && textoDe(salvo) === 'Isso mudou tudo hoje', 'Ctrl+Z primeiro devolve o clipe à linha', { linha: salvo.linha.length, texto: textoDe(salvo) });
    await pagina.keyboard.press('Control+z');
    await esperarSalvo();
    conferir(await textoNoServidor() === 'Isso mudou tudo agora', 'e depois desfaz a correção, que é um passo à parte', await textoNoServidor());

    await selecionarClipe();
    await pagina.fill('.legenda-texto', 'Isso mudou tudo mesmo');
    await pagina.click('#btn-projetos');
    await pagina.click('.menu-item:has-text("Novo projeto")');
    await pagina.waitForFunction(() => !document.querySelector('.clipe') && document.querySelector('#estado-salvo').textContent === 'Tudo salvo');
    conferir(await textoNoServidor() === 'Isso mudou tudo mesmo', 'trocar de projeto com o cursor no texto salva a correção no projeto certo', await textoNoServidor());
    conferir(await pagina.isDisabled('#btn-desfazer'), 'o projeto novo começa sem nada para desfazer');
    await pagina.evaluate(() => document.activeElement?.blur()); // o projeto novo abre com o cursor no nome dele
    await pagina.keyboard.press('Control+z');
    await sleep(700);
    conferir(await pagina.textContent('#estado-salvo') === 'Tudo salvo', 'Ctrl+Z no projeto novo não traz nada do projeto anterior', await pagina.textContent('#estado-salvo'));
    await pagina.click('#btn-projetos');
    await pagina.click('.menu-item:not(.destaque):not(.perigo):not(.atual)');
    await pagina.waitForSelector('.clipe');

    console.log('Transcrever de novo enquanto edita outra coisa');
    await selecionarClipe();
    // Segura as consultas da transcrição: a tela não fica sabendo que o texto novo já chegou ao servidor.
    let soltar;
    const segurar = new Promise((r) => { soltar = r; });
    await pagina.route('**/api/legendas/*', async (rota) => { await segurar; await rota.continue().catch(() => {}); });
    await pagina.click('button:has-text("Transcrever de novo")');
    conferir(await esperarNoServidor('Isso muda tudo agora') === 'Isso muda tudo agora', 'a nova transcrição chega ao servidor');
    await pagina.keyboard.press('Escape');
    await pagina.click('label:has-text("Tudo em maiúsculas") input');
    await sleep(100);
    await esperarSalvo();
    conferir(await textoNoServidor() === 'Isso muda tudo agora', 'salvar outra mudança no meio da transcrição não volta o texto antigo no servidor', await textoNoServidor());
    soltar();
    await pagina.waitForSelector('text=Legendas prontas', { timeout: 30000 });
    await pagina.unroute('**/api/legendas/*');
    await esperarSalvo();
    await selecionarClipe();
    conferir(await pagina.inputValue('.legenda-texto') === 'Isso muda tudo agora' && await textoNoServidor() === 'Isso muda tudo agora',
      'tela e servidor ficam com a transcrição nova', { campo: await pagina.inputValue('.legenda-texto'), servidor: await textoNoServidor() });

    console.log('Recarregar no meio da transcrição');
    // Outro Estúdio, com um Whisper falso que leva 2 s por clipe: dá tempo de corrigir o primeiro clipe e recarregar a
    // página com os outros dois ainda na fila do servidor.
    const portaLenta = await portaLivre();
    const baseLenta = `http://127.0.0.1:${portaLenta}`;
    servidores.push(subirServidor(portaLenta, 'dados-lento', '--demora', '2'));
    await esperarServidor(baseLenta);
    const lenta = await navegador.newPage({ viewport: { width: 1440, height: 900 } });
    lenta.on('pageerror', (e) => erros.push(e.message));
    lenta.on('console', (m) => { if (m.type() === 'error') erros.push(m.text()); });
    lenta.on('dialog', (d) => d.accept());
    const salvoNaLenta = () => lenta.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Tudo salvo');
    await lenta.goto(baseLenta);
    const video = fs.readFileSync(clipe);
    await lenta.setInputFiles('#arquivos', ['A', 'B', 'C'].map((letra) => ({ name: `Bloco ${letra}.webm`, mimeType: 'video/webm', buffer: video })));
    await lenta.waitForFunction(() => document.querySelectorAll('.clipe').length === 3, null, { timeout: 60000 });
    await salvoNaLenta();
    await lenta.click('.chave-legendas input');
    const primeiro = await (await lenta.$('.clipe')).boundingBox();
    await lenta.mouse.click(primeiro.x + 30, primeiro.y + 30);
    await lenta.waitForSelector('.legenda-texto', { timeout: 30000 }); // o primeiro clipe já foi transcrito
    await lenta.fill('.legenda-texto', 'Isso mudou tudo agora');
    await lenta.reload();
    await lenta.waitForSelector('.clipe');
    conferir(await lenta.waitForSelector('.andamento-legendas', { timeout: 5000 }).then(() => true, () => false),
      'depois de recarregar, a tela volta a acompanhar a transcrição que continuou no servidor');
    await lenta.waitForSelector('text=Legendas prontas', { timeout: 30000 });
    await lenta.click('label:has-text("Tudo em maiúsculas") input'); // uma mudança qualquer, para salvar tudo de novo
    await salvoNaLenta();
    const textos = await lenta.evaluate(async () => {
      const [{ id }] = await (await fetch('/api/projetos')).json();
      const proj = await (await fetch(`/api/projetos/${id}`)).json();
      return proj.midias.map((m) => (proj.legendas[m.id] || []).map((w) => w.texto).join(' '));
    });
    await lenta.mouse.click(primeiro.x + 30, primeiro.y + 30);
    await lenta.waitForSelector('.legenda-texto');
    const campo = await lenta.inputValue('.legenda-texto');
    conferir(campo === 'Isso mudou tudo agora' && textos.join('|') === 'Isso mudou tudo agora|Isso muda tudo agora|Isso muda tudo agora',
      'a correção feita antes de recarregar continua na tela e no servidor, e os outros clipes recebem a transcrição', { campo, textos });
    await lenta.close();

    conferir(erros.length === 0, 'nenhum erro no console', erros);
  } catch (erro) {
    falhas++;
    console.log('  FAIL', erro.message);
    // Para uma falha que não se repete dar para entender: em que linha do teste parou e o que estava na tela.
    console.log((erro.stack || '').split('\n').filter((l) => l.includes('e2e_estudio_legendas')).slice(0, 2).join('\n'));
    for (const [n, aberta] of navegador.contexts().flatMap((c) => c.pages()).entries()) {
      const estado = await aberta.evaluate(() => ({
        salvo: document.querySelector('#estado-salvo')?.textContent,
        clipes: document.querySelectorAll('.clipe').length,
        importando: document.querySelector('#importacoes')?.textContent,
        avisos: document.querySelector('#avisos-flutuantes')?.textContent,
      })).catch(() => null);
      const imagem = path.join(os.tmpdir(), `e2e-legendas-falha-${n}.png`);
      await aberta.screenshot({ path: imagem }).catch(() => {});
      console.log(`  página ${n} (${aberta.url()}):`, JSON.stringify(estado), `captura em ${imagem}`);
    }
  } finally {
    await navegador.close();
    servidores.forEach((s) => s.kill());
    fs.rmSync(TEMP, { recursive: true, force: true });
  }
  console.log(falhas ? `\n${falhas} falha(s)` : '\nTudo certo');
  process.exit(falhas ? 1 : 0);
})();
