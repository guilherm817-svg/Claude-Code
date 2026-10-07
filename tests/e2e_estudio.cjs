// Teste do Estúdio de Reels num Chromium de verdade: importar, tocar, cortar, desfazer, dividir, reordenar e
// exportar. Depois, os casos de borda da tela: arrastar a alça no painel do clipe (também com Esc e O no meio do
// arrasto), I e O na emenda, nome digitado sem Enter, dois lotes de importação, clipe que a prévia não toca, cancelar
// a exportação logo no começo, salvamento que falhou, régua com zoom alto e o dedo na régua (tela touch).
// Rode na raiz do projeto: node tests/e2e_estudio.cjs (precisa do playwright e do .venv instalado;
// se o playwright estiver instalado globalmente, use NODE_PATH="$(npm root -g)"). Com CAPTURAS=<pasta>, guarda a
// imagem da régua com zoom alto para olhar.
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

// Um AVI (MPEG-4 parte 2): o Estúdio aceita e exporta, mas nenhum navegador consegue tocar na prévia.
function gerarAvi() {
  const ffmpeg = spawnSync(PYTHON, ['-c', 'from estudio.midia import ffmpeg; print(ffmpeg())'], { cwd: RAIZ, encoding: 'utf8' }).stdout.trim();
  const destino = path.join(TEMP, 'Bloco 5 quebrado.avi');
  const r = spawnSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=s=720x1280:r=24:d=2', '-c:v', 'mpeg4', '-an', destino], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error('ffmpeg falhou ao gerar o AVI');
  return destino;
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
  const avi = gerarAvi();
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
    erros.length = 0;

    // Um projeto novo, aberto pela tela, com os clipes pedidos.
    const criarProjeto = (nome) => pagina.evaluate(async (n) => {
      const resposta = await fetch('/api/projetos', {
        method: 'POST', headers: { 'X-Estudio': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ nome: n }),
      });
      return (await resposta.json()).id;
    }, nome);
    const abrirNovoProjeto = async (nome, arquivos) => {
      const id = await criarProjeto(nome);
      await pagina.evaluate((i) => localStorage.setItem('estudio.ultimoProjeto', JSON.stringify(i)), id);
      await pagina.reload();
      await pagina.waitForFunction((n) => document.querySelector('#nome-projeto').value === n, nome);
      if (arquivos.length) {
        await pagina.setInputFiles('#arquivos', arquivos);
        await pagina.waitForFunction((k) => document.querySelectorAll('.clipe').length === k, arquivos.length, { timeout: 60000 });
      }
      await esperarSalvo();
      return id;
    };
    const projetoDe = (id) => pagina.evaluate(async (i) => (await fetch(`/api/projetos/${i}`)).json(), id);
    const cortes = (proj) => proj.linha.map((i) => [i.entrada, i.saida]);

    console.log('Cortar arrastando a alça no painel do clipe');
    const idCorte = await abrirNovoProjeto('Corte no painel', clipes);
    let q = await projetoDe(idCorte);
    await (await pagina.$$('.clipe'))[0].click({ position: { x: 40, y: 30 } });
    const editor = await pagina.waitForSelector('#inspetor canvas.editor-corte');
    await sleep(200);
    const caixaEditor = await editor.boundingBox();
    const [item0] = q.linha;
    const ppsEditor = caixaEditor.width / q.midias.find((m) => m.id === item0.midia_id).duracao;
    const xAlca = caixaEditor.x + item0.saida * ppsEditor;
    const yEditor = caixaEditor.y + caixaEditor.height / 2;
    await pagina.mouse.move(xAlca, yEditor);
    await pagina.mouse.down();
    await pagina.mouse.move(xAlca - 0.8 * ppsEditor, yEditor, { steps: 8 });
    const resumoNoArrasto = await pagina.textContent('.resumo-corte');
    const mesmoEditor = await editor.evaluate((canvas) => canvas.isConnected);
    await pagina.mouse.up();
    await esperarSalvo();
    q = await projetoDe(idCorte);
    conferir(Math.abs(q.linha[0].saida - (item0.saida - 0.8)) < 0.05, 'arrastar a alça do painel corta o fim até onde o mouse soltou e salva',
      { antes: item0.saida, depois: q.linha[0].saida });
    conferir(mesmoEditor && resumoNoArrasto.includes(`Usando ${(q.linha[0].saida - item0.entrada).toFixed(2).replace('.', ',')} s`),
      'o painel acompanha o arrasto sem trocar o editor de corte', { mesmoEditor, resumoNoArrasto });
    await pagina.keyboard.press('Control+z');
    await esperarSalvo();
    q = await projetoDe(idCorte);
    conferir(q.linha.length === 3 && Math.abs(q.linha[0].saida - item0.saida) < 0.001, 'Ctrl+Z desfaz o corte feito no painel (e só ele)', cortes(q));

    console.log('Esc e O no meio do arrasto da alça do painel');
    await (await pagina.$$('.clipe'))[0].click({ position: { x: 40, y: 30 } }); // a agulha fica dentro do primeiro clipe
    await pagina.waitForSelector('#inspetor canvas.editor-corte');
    await sleep(200);
    const errosAntes = erros.length;
    await pagina.mouse.move(xAlca, yEditor);
    await pagina.mouse.down();
    await pagina.mouse.move(xAlca - 0.3 * ppsEditor, yEditor, { steps: 3 });
    await pagina.keyboard.press('Escape'); // o painel do clipe dá lugar ao do projeto
    await pagina.mouse.move(xAlca - 0.4 * ppsEditor, yEditor, { steps: 2 });
    await pagina.keyboard.press('o'); // e o mesmo clipe volta a ser selecionado
    const painelDepoisDoO = await pagina.textContent('#inspetor .painel-titulo');
    await pagina.mouse.move(xAlca - 0.6 * ppsEditor, yEditor, { steps: 4 });
    const resumoDepoisDoO = await pagina.textContent('#inspetor .resumo-corte').catch(() => null);
    await pagina.mouse.up();
    await esperarSalvo();
    q = await projetoDe(idCorte);
    const errosDoArrasto = erros.slice(errosAntes);
    conferir(errosDoArrasto.length === 0 && painelDepoisDoO === 'Clipe selecionado'
      && resumoDepoisDoO?.includes(`Usando ${(q.linha[0].saida - item0.entrada).toFixed(2).replace('.', ',')} s`),
    'Esc e O no meio do arrasto: o painel volta ao clipe e acompanha o arrasto, sem erro', { errosDoArrasto, painelDepoisDoO, resumoDepoisDoO });
    conferir(Math.abs(q.linha[0].saida - (item0.saida - 0.6)) < 0.05, 'depois do Esc, a alça continua indo para onde o mouse está',
      { antes: item0.saida, depois: q.linha[0].saida });
    await pagina.keyboard.press('Control+z');
    await esperarSalvo();
    q = await projetoDe(idCorte);
    conferir(Math.abs(q.linha[0].saida - item0.saida) < 0.001, 'Ctrl+Z desfaz o arrasto inteiro', cortes(q));

    console.log('I e O perto da emenda entre dois clipes');
    const cortesOriginais = JSON.stringify(cortes(q));
    let clipeA = await (await pagina.$$('.clipe'))[0].boundingBox();
    await pagina.mouse.click(clipeA.x + 40, clipeA.y + 30); // o painel é do primeiro clipe
    await pagina.keyboard.press('ArrowDown'); // agulha exatamente no começo do segundo
    await pagina.keyboard.press('o');
    await pagina.click('#inspetor button:has-text("Fim na agulha")');
    await pagina.click('#inspetor button:has-text("Início na agulha")');
    await esperarSalvo();
    q = await projetoDe(idCorte);
    conferir(JSON.stringify(cortes(q)) === cortesOriginais, 'O e os botões do painel com a agulha na emenda não cortam o clipe seguinte', cortes(q));
    const painelDoPrimeiro = await pagina.textContent('#inspetor .clipe-titulo');
    conferir(painelDoPrimeiro === 'Bloco 1.webm', 'o painel continua no clipe em que os botões foram clicados', painelDoPrimeiro);
    let seguinteMudou = 0;
    for (const fracao of [0.15, 0.27, 0.38, 0.52, 0.66, 0.79]) {
      clipeA = await (await pagina.$$('.clipe'))[0].boundingBox();
      await pagina.mouse.click(clipeA.x + clipeA.width * fracao, clipeA.y + 30);
      for (let k = 0; k < 3; k++) await pagina.keyboard.press('o'); // a tecla segurada se repete
      await esperarSalvo();
      q = await projetoDe(idCorte);
      if (JSON.stringify(cortes(q)[1]) !== JSON.stringify(JSON.parse(cortesOriginais)[1])) seguinteMudou++;
      await pagina.keyboard.press('Control+z');
      await esperarSalvo();
    }
    q = await projetoDe(idCorte);
    conferir(seguinteMudou === 0 && JSON.stringify(cortes(q)) === cortesOriginais, 'O repetido corta só o clipe da agulha, uma vez (um Ctrl+Z desfaz)',
      { seguinteMudou, cortes: cortes(q) });

    console.log('Nome digitado sem Enter e troca de projeto');
    const idB = await criarProjeto('Projeto B');
    await pagina.fill('#nome-projeto', 'Nome novo do A');
    await pagina.click('#btn-projetos');
    await pagina.click('#menu-projetos .menu-item:has-text("Projeto B")');
    await pagina.waitForFunction(() => document.querySelector('#nome-projeto').value === 'Projeto B', null, { timeout: 5000 }).catch(() => {});
    await esperarSalvo();
    const nomesDe = (ids) => pagina.evaluate((lista) => Promise.all(lista.map(async (i) => (await (await fetch(`/api/projetos/${i}`)).json()).nome)), ids);
    let nomesSalvos = await nomesDe([idCorte, idB]);
    conferir(nomesSalvos.join('|') === 'Nome novo do A|Projeto B', 'o nome digitado sem Enter fica no projeto em que foi digitado', nomesSalvos);
    conferir(await pagina.inputValue('#nome-projeto') === 'Projeto B', 'o campo mostra o nome do projeto aberto', await pagina.inputValue('#nome-projeto'));
    await pagina.fill('#nome-projeto', 'Projeto B2');
    const regua = await (await pagina.$('.regua')).boundingBox();
    await pagina.mouse.click(regua.x + 50, regua.y + 10);
    await esperarSalvo();
    nomesSalvos = await nomesDe([idCorte, idB]);
    conferir(await pagina.evaluate(() => document.activeElement.id !== 'nome-projeto') && nomesSalvos[1] === 'Projeto B2',
      'clicar na régua tira o cursor do nome e confirma o nome digitado', nomesSalvos);

    console.log('Dois lotes importados ao mesmo tempo');
    const idLotes = await abrirNovoProjeto('Lotes', []);
    const webm = fs.readFileSync(clipes[0]);
    const lote = (numeros) => numeros.map((n) => ({ name: `Lote ${n}.webm`, mimeType: 'video/webm', buffer: webm }));
    // Cada envio demora, como o de um clipe de 8 s de verdade: o segundo lote chega com o primeiro no meio.
    await pagina.route('**/midias', async (rota) => { await sleep(300); await rota.continue(); });
    await pagina.setInputFiles('#arquivos', lote([1, 2, 3]));
    await sleep(50);
    await pagina.setInputFiles('#arquivos', lote([4, 5, 6]));
    await pagina.waitForFunction(() => document.querySelectorAll('.clipe').length === 6, null, { timeout: 60000 });
    await esperarSalvo();
    await pagina.unroute('**/midias');
    q = await projetoDe(idLotes);
    conferir(nomes(q).join('|') === [1, 2, 3, 4, 5, 6].map((n) => `Lote ${n}.webm`).join('|'), 'o segundo lote entra inteiro depois do primeiro, sem intercalar', nomes(q));

    console.log('Prévia com um clipe que o navegador não toca');
    await abrirNovoProjeto('Com AVI', [clipes[0], avi, clipes[2]]);
    await pagina.click('#btn-tocar');
    const chegouAoFim = await pagina.waitForFunction(() => document.querySelector('#btn-tocar').title.startsWith('Tocar')
      && document.querySelector('#tempo-atual').textContent === document.querySelector('#tempo-total').textContent, null, { timeout: 20000 })
      .then(() => true, () => false);
    conferir(chegouAoFim, 'a prévia pula o clipe que não toca e vai até o fim', await pagina.textContent('#tempo-atual'));
    if (!chegouAoFim) await pagina.click('#btn-tocar');

    console.log('Cancelar a exportação logo no começo');
    // O pedido de exportação demora a voltar, como quando ele espera uma importação terminar.
    await pagina.route('**/exportar', async (rota) => { await sleep(1500); await rota.continue(); });
    await pagina.click('#btn-exportar');
    await pagina.click('#btn-iniciar-exportacao');
    await pagina.click('#btn-cancelar-exportacao');
    await pagina.keyboard.press('Escape');
    const abertaDepoisDoEsc = await pagina.$eval('#dialogo-exportar', (d) => d.open);
    await pagina.waitForFunction(() => !document.querySelector('#btn-iniciar-exportacao').hidden, null, { timeout: 60000 });
    conferir(abertaDepoisDoEsc, 'Esc não fecha a janela enquanto a exportação começa');
    conferir(await pagina.$eval('#exportar-pronto', (e) => e.hidden), 'Cancelar antes de o servidor responder cancela a exportação');
    await pagina.unroute('**/exportar');
    if (await pagina.$eval('#dialogo-exportar', (d) => d.open)) await pagina.click('#btn-fechar-exportacao');

    console.log('Salvamento que falhou');
    await pagina.route('**/api/projetos/*', (rota) => (rota.request().method() === 'PUT' ? rota.abort() : rota.continue()));
    await pagina.keyboard.press('Escape');
    await pagina.click('text=Igualar o volume');
    await pagina.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Não salvo');
    await sleep(1500); // o Estúdio continua fora do ar por um tempo
    await pagina.unroute('**/api/projetos/*');
    const salvouSozinho = await pagina.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Tudo salvo', null, { timeout: 15000 })
      .then(() => true, () => false);
    q = await projetoDe(await pagina.evaluate(() => JSON.parse(localStorage.getItem('estudio.ultimoProjeto'))));
    conferir(salvouSozinho && q.igualar_volume === false, 'o salvamento que falhou é tentado de novo sozinho', { salvouSozinho, igualar: q.igualar_volume });
    await pagina.route('**/api/projetos/*', (rota) => (rota.request().method() === 'PUT' ? rota.abort() : rota.continue()));
    await pagina.click('text=Igualar o volume');
    await pagina.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Não salvo');
    const avisaAoFechar = await pagina.evaluate(() => {
      const evento = new Event('beforeunload', { cancelable: true });
      window.dispatchEvent(evento);
      return evento.defaultPrevented;
    });
    conferir(avisaAoFechar, 'com um salvamento que falhou, fechar a aba pede confirmação');
    await pagina.unroute('**/api/projetos/*');
    await pagina.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Tudo salvo', null, { timeout: 15000 }).catch(() => {});

    console.log('Régua com zoom alto');
    await pagina.evaluate(() => {
      const original = CanvasRenderingContext2D.prototype.fillText;
      window.rotulosDaRegua = [];
      CanvasRenderingContext2D.prototype.fillText = function fillText(texto, ...resto) {
        if (this.canvas.classList.contains('regua')) window.rotulosDaRegua.push(texto);
        return original.call(this, texto, ...resto);
      };
    });
    await pagina.$eval('.zoom', (controle) => { controle.value = '1000'; controle.dispatchEvent(new Event('input')); });
    const rotulos = await pagina.evaluate(() => window.rotulosDaRegua);
    const emQuartos = (rotulo) => {
      const [minutos, segs] = rotulo.split(':').map(Number);
      return Number.isInteger(Math.round((minutos * 60 + segs) * 1e6) / 1e6 * 4);
    };
    conferir(rotulos.length > 3 && rotulos.every(emQuartos) && rotulos.some((r) => /\.(25|75)$/.test(r)),
      'com zoom máximo, a régua marca cada 0,25 s com o número certo', rotulos.slice(0, 8));
    if (process.env.CAPTURAS) await pagina.screenshot({ path: path.join(process.env.CAPTURAS, 'regua-zoom.png'), clip: { x: 0, y: regua.y - 40, width: 1440, height: 180 } });

    console.log('Arrastar o dedo na régua e na trilha (tela touch)');
    const contextoToque = await navegador.newContext({ viewport: { width: 1440, height: 900 }, hasTouch: true });
    await contextoToque.addInitScript((i) => localStorage.setItem('estudio.ultimoProjeto', JSON.stringify(i)), idCorte);
    const toque = await contextoToque.newPage();
    toque.on('pageerror', (e) => erros.push(e.message));
    await toque.goto(BASE);
    await toque.waitForSelector('.clipe');
    const cdp = await contextoToque.newCDPSession(toque);
    const arrastarDedo = async (x, y, dx) => {
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x, y }] });
      for (let i = 1; i <= 12; i++) {
        await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x + (dx * i) / 12, y }] });
        await sleep(16);
      }
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await sleep(200);
    };
    const passarMouse = async (y) => {
      const antes = await toque.textContent('#tempo-atual');
      await toque.mouse.move(400, y);
      await toque.mouse.move(1000, y, { steps: 6 });
      return [antes, await toque.textContent('#tempo-atual')];
    };
    const reguaToque = await (await toque.$('.regua')).boundingBox();
    await arrastarDedo(reguaToque.x + 700, reguaToque.y + 12, -300);
    const [depoisDoDedo, depoisDoMouse] = await passarMouse(reguaToque.y + 12);
    conferir(depoisDoDedo !== '0:00.0' && depoisDoMouse === depoisDoDedo, 'o dedo na régua move a agulha, e depois passar o mouse não move', { depoisDoDedo, depoisDoMouse });
    const ultimoClipe = await (await toque.$$('.clipe')).at(-1).boundingBox();
    await arrastarDedo(ultimoClipe.x + ultimoClipe.width + 20, ultimoClipe.y + 40, -250);
    const [antesDoMouse, depoisDoMouseNaTrilha] = await passarMouse(ultimoClipe.y + 40);
    conferir(antesDoMouse === depoisDoMouseNaTrilha, 'depois de rolar a trilha com o dedo, passar o mouse não move a agulha', { antesDoMouse, depoisDoMouseNaTrilha });
    await contextoToque.close();

    const errosNovos = erros.filter((e) => !e.includes('Failed to load resource')); // o salvamento derrubado de propósito
    conferir(errosNovos.length === 0, 'nenhum erro no console nos casos de borda', errosNovos);
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
