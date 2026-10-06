// Teste do Corretor de prompts num Chromium de verdade: troca de aba, atalhos da montagem desligados no Corretor,
// chave da API, colar o prompt real do usuário, corrigir (com a API do Claude simulada por
// tests/servidor_teste_corretor.py), ver problemas e blocos, copiar, corrigir de novo sem um item, histórico e erro.
// Rode na raiz do projeto: NODE_PATH="$(npm root -g)" node tests/e2e_estudio_corretor.cjs
// Com CAPTURAS=<pasta>, salva capturas de tela nessa pasta.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const RAIZ = path.dirname(__dirname);
const PYTHON = process.env.PYTHON || [path.join(RAIZ, '.venv', 'bin', 'python'), path.join(RAIZ, '.venv', 'Scripts', 'python.exe')]
  .find((p) => fs.existsSync(p)) || 'python3';
const PORTA = 8900 + Math.floor(Math.random() * 200);
const BASE = `http://127.0.0.1:${PORTA}`;
const TEMP = fs.mkdtempSync(path.join(os.tmpdir(), 'estudio-corretor-e2e-'));
const CAPTURAS = process.env.CAPTURAS;
const EXEMPLO = JSON.parse(fs.readFileSync(path.join(__dirname, 'dados', 'correcao_exemplo.json'), 'utf8'));
const PROMPT_REAL = 'Vertical 9:16 4K 8s iPhone. Identical couple from Ingredient 1 in bedroom at night warm lamp, bathroom '
  + 'scale in corner. Man gently takes scale away. Man says in PT-BR: "Nao se pesa hoje" Woman says in PT-BR: "Aprendi '
  + 'parei com bicarbonato pra emagrecer tem muito sodio agora e comida simples e 30 min de caminhada comenta YES" No captions.';
const CHAVE = 'sk-ant-api03-chave-do-teste-e2e_0123456789';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let falhas = 0;
function conferir(condicao, mensagem, extra) {
  if (condicao) console.log('  PASS', mensagem);
  else { falhas++; console.log('  FAIL', mensagem, extra !== undefined ? JSON.stringify(extra) : ''); }
}

// O Chromium do Playwright não decodifica H.264, então o clipe de teste é WebM.
function gerarClipe() {
  const ffmpeg = spawnSync(PYTHON, ['-c', 'from estudio.midia import ffmpeg; print(ffmpeg())'], { cwd: RAIZ, encoding: 'utf8' }).stdout.trim();
  const destino = path.join(TEMP, 'Bloco 1.webm');
  const r = spawnSync(ffmpeg, ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=360x640:r=24:d=3',
    '-f', 'lavfi', '-i', 'sine=f=300:d=1.5,adelay=600|600,apad=whole_dur=3,volume=0.25',
    '-c:v', 'libvpx-vp9', '-b:v', '300k', '-deadline', 'realtime', '-cpu-used', '8', '-c:a', 'libopus', '-t', '3', destino], { stdio: 'inherit' });
  if (r.status !== 0) throw new Error('ffmpeg falhou ao gerar o clipe');
  return destino;
}

async function esperarServidor() {
  for (let i = 0; i < 150; i++) {
    try {
      if ((await fetch(`${BASE}/api/corretor/estado`)).ok) return;
    } catch { /* ainda subindo */ }
    await sleep(100);
  }
  throw new Error('O servidor de teste do Corretor não respondeu.');
}

(async () => {
  const clipe = gerarClipe();
  const servidor = spawn(PYTHON, [path.join(__dirname, 'servidor_teste_corretor.py'), '--porta', String(PORTA), '--pasta', TEMP],
    { cwd: RAIZ, stdio: 'inherit' });
  const navegador = await chromium.launch();
  try {
    await esperarServidor();
    const contexto = await navegador.newContext({ viewport: { width: 1440, height: 900 } });
    await contexto.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
    const pagina = await contexto.newPage();
    const erros = [];
    pagina.on('pageerror', (e) => erros.push(e.message));
    pagina.on('console', (m) => {
      // A chave errada de propósito volta 400, e o Chromium anota isso no console: é esperado.
      if (m.type() === 'error' && !(m.location().url.endsWith('/api/chave') && m.text().includes('400'))) erros.push(m.text());
    });
    pagina.on('dialog', (d) => d.accept());
    const capturar = async (nome) => { if (CAPTURAS) await pagina.screenshot({ path: path.join(CAPTURAS, `${nome}.png`) }); };
    const linhaDoProjeto = () => pagina.evaluate(async () => {
      const [primeiro] = await (await fetch('/api/projetos')).json();
      return (await (await fetch(`/api/projetos/${primeiro.id}`)).json()).linha;
    });
    const textoDoLado = () => pagina.textContent('#corretor-lado');

    console.log('Montagem com um clipe selecionado');
    await pagina.goto(BASE);
    await pagina.waitForSelector('#previa-vazia:not([hidden])');
    await pagina.setInputFiles('#arquivos', [clipe]);
    await pagina.waitForFunction(() => document.querySelectorAll('.clipe').length === 1, null, { timeout: 60000 });
    await pagina.waitForFunction(() => document.querySelector('#estado-salvo').textContent === 'Tudo salvo');
    await (await pagina.$('.clipe')).click({ position: { x: 30, y: 30 } });
    await pagina.waitForSelector('.clipe.selecionado');

    console.log('Trocar para o Corretor');
    await pagina.click('.aba[data-aba="corretor"]');
    conferir(await pagina.isVisible('#corretor-form'), 'o Corretor aparece');
    conferir(await pagina.isHidden('.area') && await pagina.isHidden('#linha') && await pagina.isHidden('#btn-exportar'),
      'mídia, prévia, linha do tempo e botões da montagem somem');
    conferir(await pagina.getAttribute('.aba[data-aba="corretor"]', 'aria-selected') === 'true', 'a aba fica marcada');
    conferir(await pagina.evaluate(() => document.activeElement.id) === 'corretor-prompt', 'o cursor vai para o campo do prompt');
    conferir(await pagina.isVisible('.cartao-chave'), 'sem chave, aparece o cartão explicando como criar');
    conferir((await pagina.textContent('.cartao-chave')).includes('console.anthropic.com'), 'o cartão aponta para console.anthropic.com');
    await capturar('01-sem-chave');

    console.log('Atalhos da montagem desligados no Corretor');
    await pagina.click('.cartao-chave h2');
    for (const tecla of ['Delete', 's', 'Control+d', 'Space']) await pagina.keyboard.press(tecla);
    await sleep(700);
    conferir((await linhaDoProjeto()).length === 1, 'Delete, S e Ctrl+D não mexem na linha do tempo', await linhaDoProjeto());

    console.log('Chave da API');
    await pagina.fill('#corretor-prompt', PROMPT_REAL);
    await pagina.click('#corretor-enviar');
    const foiParaChave = await pagina.waitForFunction(() => document.activeElement.id === 'corretor-chave', null, { timeout: 3000 })
      .then(() => true, () => false);
    conferir(foiParaChave, 'corrigir sem chave leva para o campo da chave');
    await pagina.fill('#corretor-chave', 'abc');
    await pagina.click('.chave-form button[type=submit]');
    await pagina.waitForSelector('#corretor-chave-erro:not(:empty)');
    conferir((await pagina.textContent('#corretor-chave-erro')).includes('sk-ant-'), 'chave errada mostra o formato certo');
    await pagina.fill('#corretor-chave', CHAVE);
    await pagina.click('.chave-form button[type=submit]');
    await pagina.waitForSelector('.cartao-chave', { state: 'detached' });
    const env = fs.readFileSync(path.join(TEMP, '.env'), 'utf8');
    conferir(env.includes(`ANTHROPIC_API_KEY=${CHAVE}`), 'a chave é gravada no .env');
    conferir(!(await pagina.content()).includes(CHAVE) && !(await (await fetch(`${BASE}/api/corretor/estado`)).text()).includes(CHAVE),
      'a chave não volta para a tela nem para a API');

    console.log('Corrigir o prompt real');
    await pagina.fill('#corretor-pedido', 'Casal no quarto: ele tira a balança e ela conta que parou de usar bicarbonato pra emagrecer');
    conferir((await pagina.textContent('#corretor-cabe')).includes('cabem cerca de 17 palavras'), 'mostra quantas palavras cabem no clipe');
    await pagina.click('#corretor-enviar');
    await pagina.waitForSelector('.cartao-progresso');
    await pagina.waitForSelector('#corretor-etapas li.atual:nth-child(2), #corretor-etapas li.atual:nth-child(3)');
    conferir(await pagina.isDisabled('#corretor-enviar'), 'o botão fica desligado enquanto corrige');
    await capturar('02-progresso');
    await pagina.waitForSelector('.resultado-topo', { timeout: 30000 });
    await capturar('03-resultado');

    const problemas = await pagina.$$eval('.problema', (cartoes) => cartoes.map((c) => c.className));
    conferir(problemas.length === EXEMPLO.problemas.length, 'um cartão por problema', problemas.length);
    conferir(problemas[0].includes('alta') && problemas.at(-1).includes('baixa'), 'problemas do mais grave para o mais leve');
    const primeiro = await pagina.textContent('.problema');
    conferir(['Por que dá bug', 'O que mudou', 'No seu prompt', 'Tempo da fala'].every((t) => primeiro.includes(t)),
      'cada problema traz o trecho, o porquê e o que mudou', primeiro);
    const blocos = await pagina.$$('.bloco');
    conferir(blocos.length === 2, 'dois blocos corrigidos', blocos.length);
    const bloco1 = await blocos[0].textContent();
    const caracteres = EXEMPLO.blocos[0].prompt.length.toLocaleString('pt-BR');
    conferir(bloco1.includes('Bloco 1') && bloco1.includes('Não se pesa hoje.') && bloco1.includes(`${caracteres} / 2.500 caracteres`)
      && bloco1.includes('13 palavras') && bloco1.includes('6,6 s de fala'), 'bloco com fala, duração e caracteres', bloco1.slice(0, 300));
    conferir(await pagina.$$eval('.alertas li', (l) => l.length) === 2, 'alertas de alcance');
    conferir(await pagina.$$eval('.item-a-mais input:checked', (l) => l.length) === 2, 'itens que a IA acrescentou, marcados');

    console.log('Copiar');
    await blocos[0].$('.botao-copiar').then((b) => b.click());
    await pagina.waitForSelector('.botao-copiar.copiado');
    const copiado = await pagina.evaluate(() => navigator.clipboard.readText());
    conferir(copiado === EXEMPLO.blocos[0].prompt, 'Copiar põe o prompt do bloco na área de transferência');

    await pagina.click('.atalho:has-text("Problemas")');
    await sleep(600);
    await capturar('04-problemas');
    await pagina.click('.atalho:has-text("Itens a mais")');
    await sleep(600);
    await capturar('05-itens-e-alcance');

    console.log('Corrigir de novo sem um item');
    await pagina.uncheck('.item-a-mais input >> nth=0');
    await pagina.click('button:has-text("Corrigir de novo sem os desmarcados")');
    await pagina.waitForSelector('.cartao-progresso');
    await pagina.waitForSelector('.resultado-topo', { timeout: 30000 });
    const ultimo = JSON.parse(fs.readFileSync(path.join(TEMP, 'ultimo_pedido.json'), 'utf8'));
    const mensagem = ultimo.messages[0].content;
    conferir(mensagem.includes(`<itens_para_tirar>\n- ${EXEMPLO.acrescentados_pela_ia[0].item}\n</itens_para_tirar>`)
      && mensagem.includes('<pedido_original>'), 'o item desmarcado vai na lista de itens para tirar');

    console.log('Histórico e erro');
    await pagina.reload();
    await pagina.waitForSelector('#corretor-form');
    conferir(await pagina.isVisible('#corretor-form'), 'ao abrir de novo, volta na aba do Corretor');
    conferir(await pagina.$$eval('.historico-item', (l) => l.length) === 2, 'histórico com as duas correções');
    conferir(await pagina.inputValue('#corretor-prompt') === PROMPT_REAL, 'o rascunho do prompt continua no campo');
    await pagina.click('.historico-item >> nth=1');
    await pagina.waitForSelector('.resultado-topo');
    conferir((await textoDoLado()).includes('Encontrei 14 problemas'), 'abrir do histórico mostra a correção');

    await pagina.fill('#corretor-prompt', 'ERRO-401 Woman says hi');
    await pagina.keyboard.press('Control+Enter');
    await pagina.waitForSelector('.cartao-erro');
    conferir((await textoDoLado()).includes('Chave da API do Claude inválida'), 'erro da API em português');
    await capturar('06-erro');
    await pagina.click('.cartao-erro button:has-text("Trocar a chave")');
    conferir(await pagina.isVisible('.cartao-chave') && await pagina.isVisible('.chave-form button:has-text("Cancelar")'),
      'o erro de chave oferece trocar a chave');

    console.log('Voltar para a Montagem');
    await pagina.click('.aba[data-aba="montagem"]');
    conferir(await pagina.isVisible('.area') && await pagina.isVisible('#linha') && await pagina.isHidden('#corretor'), 'a montagem volta');
    conferir(await pagina.$$eval('.clipe', (l) => l.length) === 1 && (await linhaDoProjeto()).length === 1, 'o clipe continua na linha do tempo');
    // O projeto abriu com a linha do tempo escondida (a página recarregou na aba do Corretor): o zoom se ajusta ao voltar.
    const largura = await pagina.$eval('.clipe', (c) => c.getBoundingClientRect().width);
    conferir(largura > 600, 'a linha do tempo mostra o vídeo inteiro ao voltar', largura);
    await capturar('07-montagem');
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
