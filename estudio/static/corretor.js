// Corretor de prompts: o usuário cola um prompt de vídeo, o Claude aponta o que pode dar bug e explica o porquê, e a
// tela mostra a versão corrigida em blocos prontos para copiar. Fica numa aba própria, ao lado da Montagem.

import { icone } from './icones.js';
import { $, avisar, el, guardar, lembrar } from './util.js';

const HISTORICO_MAXIMO = 10;
const GRAVIDADES = { alta: 'Alta', media: 'Média', baixa: 'Baixa' };
const CATEGORIAS = {
  configuracao: 'Configuração do gerador',
  tempo_da_fala: 'Tempo da fala',
  escrita_da_fala: 'Escrita da fala',
  vozes: 'Vozes',
  identidade: 'Pessoas e identidade',
  texto_na_tela: 'Texto e legendas',
  maos_e_objetos: 'Mãos e objetos',
  camera_e_movimento: 'Câmera e movimento',
  cenario: 'Cenário',
  formato_do_prompt: 'Formato do prompt',
  seguranca: 'Segurança',
  outro: 'Outro',
};
const NOMES_DO_RITMO = { natural: 'Natural', '1.1x': '1.1x · mais rápido', '1.25x': '1.25x · rápido' };
const O_QUE_CONFERE = ['Fala que não cabe no clipe', 'Pontuação, acentos e números', 'Texto e legendas na tela',
  'Gêmeos e identidade', 'Vozes e sotaque', 'Mãos e objetos', 'Configurações do Flow', 'Segurança de quem assiste',
  'Alcance no Reels'];

const estado = {
  opcoes: null,
  temChave: false,
  modelo: '',
  trocandoChave: false,
  fase: 'vazio', // vazio | corrigindo | erro | pronto
  etapa: 0,
  inicio: 0,
  erro: null,
  pedido: null,
  resultado: null,
  historicoId: null,
  controle: null,
  relogio: null,
  aoTrocarDeAba: null,
  aplicarEstiloDeLegenda: null,
};

// Volta o formulário a um pedido já feito (histórico, corrigir de novo). Definida ao montar o formulário.
let preencherFormulario = () => {};

const numero = (valor, casas = 1) => valor.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });
const milhar = (valor) => valor.toLocaleString('pt-BR');
const gerador = (id) => estado.opcoes.geradores.find((g) => g.id === id);
const cadencia = (id) => estado.opcoes.cadencias.find((c) => c.id === id);
const palavrasQueCabem = (duracao, ritmo) => Math.max(0, Math.floor((duracao - estado.opcoes.folga) * cadencia(ritmo).palavras_por_segundo));

export const corretorAberto = () => document.body.classList.contains('aba-corretor');

export function mostrarAba(aba) {
  const corretor = aba === 'corretor';
  document.body.classList.toggle('aba-corretor', corretor);
  $('#corretor').hidden = !corretor;
  document.querySelectorAll('.aba').forEach((botao) => botao.setAttribute('aria-selected', String(botao.dataset.aba === aba)));
  guardar('aba', aba);
  estado.aoTrocarDeAba?.(aba);
  if (corretor && estado.opcoes && !$('#corretor-prompt').value) $('#corretor-prompt').focus();
}

// `aplicarEstiloDeLegenda(texto)`, quando o Estúdio tiver legendas, liga o botão de aplicar o estilo sugerido.
export async function iniciarCorretor({ aoTrocarDeAba, aplicarEstiloDeLegenda } = {}) {
  estado.aoTrocarDeAba = aoTrocarDeAba;
  estado.aplicarEstiloDeLegenda = aplicarEstiloDeLegenda || null;
  document.querySelectorAll('.aba').forEach((botao) => botao.addEventListener('click', () => mostrarAba(botao.dataset.aba)));
  const raiz = $('#corretor');
  try {
    const resposta = await fetch('/api/corretor/estado');
    if (!resposta.ok) throw new Error();
    const dados = await resposta.json();
    estado.opcoes = dados;
    estado.temChave = dados.tem_chave;
    estado.modelo = dados.modelo;
  } catch {
    raiz.replaceChildren(el('div', { class: 'corretor-lado' }, el('div', { class: 'cartao cartao-erro', role: 'alert' },
      el('h3', {}, 'O Corretor não abriu'), el('p', {}, 'Não consegui falar com o Estúdio. Feche e abra o Estúdio de novo.'))));
    mostrarAba(lembrar('aba', 'montagem'));
    return;
  }
  raiz.replaceChildren(montarFormulario(), el('div', { id: 'corretor-lado', class: 'corretor-lado', 'aria-live': 'polite' }));
  desenharHistorico();
  desenharLado();
  mostrarAba(lembrar('aba', 'montagem'));
}

// Formulário

function campo(rotulo, controle, ajuda) {
  return el('label', { class: 'campo' }, el('span', { class: 'rotulo' }, rotulo), controle, ajuda ? el('small', { class: 'ajuda' }, ajuda) : null);
}

function opcoesDe(lista, escolhido, nome = (item) => item.nome) {
  return lista.map((item) => el('option', { value: item.id, selected: item.id === escolhido }, nome(item)));
}

function montarFormulario() {
  const o = estado.opcoes;
  const salvo = lembrar('corretor.rascunho', {});
  const rascunho = salvo && typeof salvo === 'object' ? salvo : {};
  const prompt = el('textarea', {
    id: 'corretor-prompt', class: 'entrada entrada-prompt', rows: 9, maxlength: o.limite_prompt, spellcheck: 'false',
    placeholder: 'Cole aqui o prompt do vídeo (do Meta AI, ChatGPT, Gemini…)',
  });
  prompt.value = rascunho.prompt || '';
  const pedidoOriginal = el('textarea', {
    id: 'corretor-pedido', class: 'entrada', rows: 3, maxlength: o.limite_pedido_original,
    placeholder: 'Ex.: casal no quarto, ele tira a balança e ela conta que parou com o bicarbonato',
  });
  pedidoOriginal.value = rascunho.pedido_original || '';
  const escolhido = gerador(rascunho.gerador) ? rascunho.gerador : 'veo';

  const formulario = el('form', { id: 'corretor-form', class: 'corretor-form', novalidate: true },
    el('div', { class: 'corretor-cabeca' },
      el('h1', {}, icone('varinha', 20), 'Corretor de prompts'),
      el('p', {}, 'Cole o prompt que você gerou em outra IA. O Corretor aponta o que pode dar bug, explica o porquê e '
        + 'devolve a versão corrigida, dividida em blocos que cabem no clipe.')),
    el('div', { class: 'campo' },
      el('span', { class: 'rotulo rotulo-linha' }, el('label', { for: 'corretor-prompt' }, 'Prompt para corrigir'),
        el('span', { id: 'corretor-contador', class: 'contador' })),
      prompt),
    el('div', { class: 'grade-campos' },
      campo('Gerador', el('select', { id: 'corretor-gerador' }, ...opcoesDe(o.geradores, escolhido))),
      campo('Duração do clipe', el('select', { id: 'corretor-duracao' })),
      campo('Ritmo da fala', el('select', { id: 'corretor-cadencia' },
        ...opcoesDe(o.cadencias, rascunho.cadencia || 'natural', (c) => NOMES_DO_RITMO[c.id] || c.nome))),
      campo('Idioma da fala', el('select', { id: 'corretor-idioma' }, ...opcoesDe(o.idiomas, rascunho.idioma_fala || 'auto')))),
    campo('Objetivo', el('select', { id: 'corretor-objetivo' }, ...opcoesDe(o.objetivos, rascunho.objetivo || 'reels'))),
    el('p', { id: 'corretor-cabe', class: 'cabe' }),
    campo('O que você pediu para a IA (opcional)', pedidoOriginal,
      'Se você contar, o Corretor aponta o que a IA colocou sem você pedir (marca, produto, frase).'),
    el('div', { class: 'envio' },
      el('button', { id: 'corretor-enviar', class: 'botao primario grande', type: 'submit' }, icone('varinha', 16), 'Corrigir prompt'),
      el('p', { class: 'atalho-envio' }, el('kbd', {}, 'Ctrl'), ' + ', el('kbd', {}, 'Enter'), ' também corrige')),
    el('div', { id: 'corretor-historico', class: 'historico' }),
    el('div', { class: 'rodape-form' },
      el('button', { type: 'button', class: 'botao fantasma pequeno', onclick: () => { estado.trocandoChave = true; desenharLado(); focarChave(); } },
        icone('chave', 14), 'Chave da API do Claude'),
      el('span', { class: 'modelo', title: 'Modelo usado nas correções (ESTUDIO_MODELO_CLAUDE)' }, estado.modelo)));

  const selecionarDuracao = (padrao) => {
    const g = gerador($('#corretor-gerador', formulario).value);
    const select = $('#corretor-duracao', formulario);
    if (!g.duracoes.length) {
      select.replaceChildren(el('option', { value: '' }, 'Não se aplica'));
      select.disabled = true;
      return;
    }
    const valor = g.duracoes.includes(Number(padrao)) ? Number(padrao) : g.padrao;
    select.disabled = false;
    select.replaceChildren(...g.duracoes.map((d) => el('option', { value: d, selected: d === valor },
      `${d} s${d === g.teto ? ' (máximo)' : ''}`)));
  };
  const atualizarDicas = () => {
    const tamanho = prompt.value.length;
    const contador = $('#corretor-contador', formulario);
    contador.textContent = `${milhar(tamanho)} / ${milhar(o.limite_prompt)}`;
    contador.classList.toggle('cheio', tamanho > o.limite_prompt * 0.95);
    const dados = lerFormulario(formulario);
    const ritmo = cadencia(dados.cadencia);
    $('#corretor-cabe', formulario).textContent = dados.duracao_clipe
      ? `Num clipe de ${dados.duracao_clipe} s, no ritmo ${ritmo.id === 'natural' ? 'natural' : ritmo.nome} `
        + `(~${numero(ritmo.palavras_por_segundo, 2).replace(/0$/, '')} palavras por segundo), cabem cerca de `
        + `${palavrasQueCabem(dados.duracao_clipe, dados.cadencia)} palavras de fala. O que passar disso vira outro bloco.`
      : 'Prompt de imagem: sem fala e sem duração. Serve para gerar a foto que vira ingrediente ou primeiro quadro.';
  };
  let rascunhoTimer = null;
  const lembrarRascunho = () => {
    clearTimeout(rascunhoTimer);
    rascunhoTimer = setTimeout(() => guardar('corretor.rascunho', lerFormulario(formulario)), 300);
  };

  selecionarDuracao(rascunho.duracao_clipe);
  atualizarDicas();
  formulario.addEventListener('input', () => { atualizarDicas(); lembrarRascunho(); });
  formulario.addEventListener('change', (e) => {
    if (e.target.id === 'corretor-gerador') selecionarDuracao(null);
    atualizarDicas();
    lembrarRascunho();
  });
  formulario.addEventListener('submit', (e) => { e.preventDefault(); corrigir(); });
  formulario.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); corrigir(); }
  });
  preencherFormulario = (pedido) => {
    prompt.value = pedido.prompt || '';
    pedidoOriginal.value = pedido.pedido_original || '';
    for (const [id, valor] of [['gerador', pedido.gerador], ['cadencia', pedido.cadencia], ['idioma', pedido.idioma_fala], ['objetivo', pedido.objetivo]]) {
      if (valor) $(`#corretor-${id}`, formulario).value = valor;
    }
    selecionarDuracao(pedido.duracao_clipe);
    atualizarDicas();
    lembrarRascunho();
  };
  return formulario;
}

function lerFormulario(formulario = $('#corretor-form')) {
  const valor = (id) => $(`#corretor-${id}`, formulario).value;
  const duracao = valor('duracao');
  return {
    prompt: valor('prompt'),
    gerador: valor('gerador'),
    duracao_clipe: duracao ? Number(duracao) : null,
    cadencia: valor('cadencia'),
    idioma_fala: valor('idioma'),
    objetivo: valor('objetivo'),
    pedido_original: valor('pedido'),
  };
}

// Correção

async function* linhasDe(resposta) {
  const leitor = resposta.body.getReader();
  const decodificador = new TextDecoder();
  let resto = '';
  for (;;) {
    const { value, done } = await leitor.read();
    resto += decodificador.decode(value || new Uint8Array(), { stream: !done });
    const linhas = resto.split('\n');
    resto = linhas.pop();
    for (const linha of linhas) if (linha.trim()) yield JSON.parse(linha);
    if (done) break;
  }
  if (resto.trim()) yield JSON.parse(resto);
}

function erroComCodigo(mensagem, codigo) {
  return Object.assign(new Error(mensagem), { codigo });
}

async function corrigir(extra = {}) {
  if (estado.controle) return;
  const pedido = { ...lerFormulario(), ...extra };
  if (!pedido.prompt.trim()) {
    avisar('Cole o prompt que você quer corrigir.', 'erro');
    $('#corretor-prompt').focus();
    return;
  }
  if (!estado.temChave) {
    estado.trocandoChave = true;
    desenharLado();
    focarChave();
    avisar('Primeiro conecte o Corretor ao Claude com a sua chave da API.');
    return;
  }
  const controle = new AbortController();
  const anterior = { fase: estado.fase, resultado: estado.resultado };
  Object.assign(estado, { controle, fase: 'corrigindo', etapa: 0, inicio: Date.now(), erro: null, pedido, trocandoChave: false });
  desenharLado();
  estado.relogio = setInterval(desenharTempo, 1000);
  try {
    const resposta = await fetch('/api/corretor', {
      method: 'POST', headers: { 'X-Estudio': '1', 'Content-Type': 'application/json' }, body: JSON.stringify(pedido), signal: controle.signal,
    });
    if (!resposta.ok) {
      const dados = await resposta.json().catch(() => null);
      throw erroComCodigo(dados?.detail || `O Estúdio respondeu com erro ${resposta.status}.`, dados?.codigo);
    }
    let resultado = null;
    for await (const evento of linhasDe(resposta)) {
      if (evento.erro) throw erroComCodigo(evento.erro, evento.codigo);
      if (evento.etapa) {
        estado.etapa = evento.etapa;
        desenharProgresso();
      }
      if (evento.resultado) resultado = evento.resultado;
    }
    if (!resultado) throw new Error('A correção parou antes do fim. Tente de novo.');
    Object.assign(estado, { fase: 'pronto', resultado, historicoId: salvarNoHistorico(pedido, resultado) });
  } catch (erro) {
    if (controle.signal.aborted) {
      Object.assign(estado, anterior);
      avisar('Correção cancelada.');
    } else {
      const semConexao = erro instanceof TypeError;
      estado.fase = 'erro';
      estado.erro = {
        mensagem: semConexao ? 'Sem conexão com o Estúdio. A janela dele ainda está aberta?' : erro.message,
        codigo: erro.codigo || 'erro',
      };
      if (erro.codigo === 'chave' && /Falta conectar/.test(erro.message)) estado.temChave = false;
    }
  } finally {
    clearInterval(estado.relogio);
    estado.controle = null;
    desenharLado();
    desenharHistorico();
  }
}

// Chave da API

function focarChave() {
  requestAnimationFrame(() => $('#corretor-chave')?.focus());
}

async function salvarChave(e) {
  e.preventDefault();
  const entrada = $('#corretor-chave');
  const mensagem = $('#corretor-chave-erro');
  const botao = e.target.querySelector('button[type=submit]');
  botao.disabled = true;
  mensagem.textContent = '';
  try {
    const resposta = await fetch('/api/chave', {
      method: 'POST', headers: { 'X-Estudio': '1', 'Content-Type': 'application/json' }, body: JSON.stringify({ chave: entrada.value }),
    });
    const dados = await resposta.json().catch(() => null);
    if (!resposta.ok) throw new Error(dados?.detail || `O Estúdio respondeu com erro ${resposta.status}.`);
    entrada.value = '';
    Object.assign(estado, { temChave: true, trocandoChave: false, modelo: dados.modelo });
    if (estado.fase === 'erro' && estado.erro?.codigo === 'chave') estado.fase = estado.resultado ? 'pronto' : 'vazio';
    avisar('Chave salva. O Corretor está pronto para usar.');
    desenharLado();
  } catch (erro) {
    mensagem.textContent = erro instanceof TypeError ? 'Sem conexão com o Estúdio. A janela dele ainda está aberta?' : erro.message;
    botao.disabled = false;
    entrada.focus();
  }
}

function cartaoDaChave() {
  const trocando = estado.temChave;
  return el('section', { class: 'cartao cartao-chave', 'aria-labelledby': 'titulo-chave' },
    el('div', { class: 'cartao-chave-icone' }, icone('chave', 22)),
    el('div', {},
      el('h2', { id: 'titulo-chave' }, trocando ? 'Trocar a chave da API do Claude' : 'Conecte o Corretor ao Claude'),
      el('p', {}, 'O Corretor usa o Claude, a inteligência artificial da Anthropic. Para isso ele precisa de uma chave da API, '
        + 'que é paga por uso, direto na sua conta da Anthropic.'),
      el('ol', { class: 'passos' },
        el('li', {}, 'Entre em ', el('a', { href: 'https://console.anthropic.com', target: '_blank', rel: 'noopener noreferrer' }, 'console.anthropic.com'),
          ' e crie a sua conta (ou entre nela).'),
        el('li', {}, 'Em ', el('strong', {}, 'Billing'), ', adicione créditos.'),
        el('li', {}, 'Em ', el('strong', {}, 'API Keys'), ', clique em ', el('strong', {}, 'Create Key'), ' e copie a chave. Ela começa com ',
          el('code', {}, 'sk-ant-'), '.'),
        el('li', {}, 'Cole a chave aqui embaixo e clique em ', el('strong', {}, 'Salvar chave'), '.')),
      el('form', { class: 'chave-form', onsubmit: salvarChave },
        el('input', { id: 'corretor-chave', class: 'entrada', type: 'password', placeholder: 'sk-ant-…', autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Chave da API do Claude' }),
        el('button', { class: 'botao primario', type: 'submit' }, 'Salvar chave'),
        trocando ? el('button', { class: 'botao fantasma', type: 'button', onclick: () => { estado.trocandoChave = false; desenharLado(); } }, 'Cancelar') : null),
      el('p', { id: 'corretor-chave-erro', class: 'erro-campo', role: 'alert' }),
      el('p', { class: 'nota' }, 'A chave fica guardada só neste computador, no arquivo .env do Estúdio (o mesmo do Analisador de aulas). '
        + 'Ela nunca aparece de novo na tela.')));
}

// Painel da direita

function desenharLado() {
  const lado = $('#corretor-lado');
  if (!lado) return;
  const partes = [];
  if (!estado.temChave || estado.trocandoChave) partes.push(cartaoDaChave());
  if (estado.fase === 'corrigindo') partes.push(cartaoDeProgresso());
  else if (estado.fase === 'erro') partes.push(cartaoDeErro());
  else if (estado.fase === 'pronto') partes.push(...desenharResultado(estado.resultado));
  else if (estado.temChave && !estado.trocandoChave) partes.push(estadoVazio());
  lado.replaceChildren(...partes);
  if (estado.fase === 'corrigindo') desenharProgresso();
  const enviar = $('#corretor-enviar');
  enviar.disabled = Boolean(estado.controle);
  enviar.replaceChildren(icone('varinha', 16), estado.controle ? 'Corrigindo…' : 'Corrigir prompt');
}

function estadoVazio() {
  return el('div', { class: 'corretor-vazio' },
    el('div', { class: 'vazio-icone' }, icone('varinha', 30)),
    el('h2', {}, 'Cole um prompt e clique em Corrigir'),
    el('p', {}, 'O Corretor confere o prompt com as regras que evitam os bugs mais comuns do Veo, do Kling e do Seedance, '
      + 'explica cada mudança em português e devolve o prompt pronto para copiar.'),
    el('ul', { class: 'confere' }, ...O_QUE_CONFERE.map((item) => el('li', {}, icone('certo', 13), item))));
}

function tempoDecorrido() {
  const s = Math.floor((Date.now() - estado.inicio) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function desenharTempo() {
  const alvo = $('#corretor-tempo');
  if (alvo) alvo.textContent = tempoDecorrido();
}

function cartaoDeProgresso() {
  const etapas = estado.opcoes.etapas;
  return el('section', { class: 'cartao cartao-progresso', 'aria-busy': 'true' },
    el('div', { class: 'progresso-cabeca' },
      el('span', { class: 'girando', 'aria-hidden': 'true' }),
      el('h2', {}, 'Corrigindo o prompt…'),
      el('span', { id: 'corretor-tempo', class: 'tempo-decorrido' }, tempoDecorrido())),
    el('div', { class: 'barra grande' }, el('span', { id: 'corretor-barra' })),
    el('ol', { id: 'corretor-etapas', class: 'etapas' }, ...etapas.map((texto) => el('li', {}, el('span', { class: 'marcador' }), texto))),
    el('p', { class: 'nota' }, 'Costuma levar de meio minuto a dois minutos. Você pode voltar para a Montagem enquanto isso.'),
    el('button', { class: 'botao fantasma', type: 'button', onclick: () => estado.controle?.abort() }, 'Cancelar'));
}

function desenharProgresso() {
  const lista = $('#corretor-etapas');
  if (!lista) return;
  [...lista.children].forEach((item, i) => {
    const n = i + 1;
    item.className = n < estado.etapa ? 'feita' : n === estado.etapa ? 'atual' : '';
    item.querySelector('.marcador').replaceChildren(n < estado.etapa ? icone('certo', 12) : '');
  });
  const total = estado.opcoes.etapas.length;
  $('#corretor-barra').style.width = `${Math.max(0, Math.round(((estado.etapa - 0.5) / total) * 100))}%`;
}

function cartaoDeErro() {
  const { mensagem, codigo } = estado.erro;
  return el('section', { class: 'cartao cartao-erro', role: 'alert' },
    el('div', { class: 'erro-cabeca' }, icone('alerta', 20), el('h2', {}, 'Não deu para corrigir')),
    el('p', {}, mensagem),
    el('div', { class: 'linha-botoes' },
      el('button', { class: 'botao primario', type: 'button', onclick: () => corrigir(estado.pedido?.remover_itens ? { remover_itens: estado.pedido.remover_itens } : {}) }, 'Tentar de novo'),
      codigo === 'chave' || codigo === 'creditos'
        ? el('button', { class: 'botao', type: 'button', onclick: () => { estado.trocandoChave = true; desenharLado(); focarChave(); } }, icone('chave', 15), 'Trocar a chave')
        : null));
}

// Resultado

async function copiar(texto, botao) {
  let copiou = false;
  try {
    await navigator.clipboard.writeText(texto);
    copiou = true;
  } catch {
    // Sem acesso à área de transferência: copia do jeito antigo, por uma caixa de texto escondida.
    const caixa = el('textarea', { class: 'copia-oculta', readonly: true }, texto);
    document.body.append(caixa);
    caixa.select();
    try { copiou = document.execCommand('copy'); } catch { copiou = false; }
    caixa.remove();
  }
  if (!copiou) {
    avisar('Não consegui copiar. Selecione o texto do prompt e use Ctrl+C.', 'erro');
    return;
  }
  const original = [...botao.childNodes];
  botao.classList.add('copiado');
  botao.replaceChildren(icone('certo', 14), 'Copiado');
  setTimeout(() => { botao.classList.remove('copiado'); botao.replaceChildren(...original); }, 1800);
}

function secao(id, titulo, nomeIcone, dica, ...conteudo) {
  return el('section', { id, class: 'secao' },
    el('div', { class: 'secao-titulo' }, el('h3', {}, icone(nomeIcone, 16), titulo)),
    dica ? el('p', { class: 'secao-dica' }, dica) : null,
    ...conteudo);
}

function desenharResultado(r) {
  const g = gerador(r.gerador);
  const contagem = { alta: 0, media: 0, baixa: 0 };
  r.problemas.forEach((p) => { contagem[p.gravidade] += 1; });
  const quando = new Date(r.gerada_em);
  const ir = (id) => () => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const atalho = (id, texto, quantidade, classe = '') => el('button', { type: 'button', class: `atalho ${classe}`, onclick: ir(id) },
    texto, quantidade !== undefined ? el('span', { class: 'quantidade' }, String(quantidade)) : null);

  const partes = [el('section', { class: 'resultado-topo' },
    el('div', { class: 'resultado-cabeca' },
      el('h2', {}, r.recusado ? 'Este prompt não foi refeito' : 'Prompt corrigido'),
      el('span', { class: 'resultado-meta' },
        [g?.nome, r.duracao_clipe ? `clipe de ${r.duracao_clipe} s` : null,
          Number.isNaN(quando.getTime()) ? null : quando.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })].filter(Boolean).join(' · '))),
    el('p', { class: 'resumo' }, r.resumo),
    el('nav', { class: 'resultado-nav', 'aria-label': 'Partes do resultado' },
      r.blocos.length ? atalho('corretor-blocos', r.blocos.length === 1 ? 'Prompt pronto' : 'Blocos prontos', r.blocos.length) : null,
      r.problemas.length ? atalho('corretor-problemas', 'Problemas', r.problemas.length, contagem.alta ? 'tem-alta' : '') : null,
      r.acrescentados_pela_ia.length ? atalho('corretor-acrescentados', 'Itens a mais', r.acrescentados_pela_ia.length) : null,
      r.alertas_de_alcance.length ? atalho('corretor-alcance', 'Alcance', r.alertas_de_alcance.length) : null,
      r.estilo_de_legenda ? atalho('corretor-legenda', 'Legenda') : null))];

  if (r.recusado) {
    partes.push(el('section', { class: 'cartao cartao-erro recusa', role: 'alert' },
      el('div', { class: 'erro-cabeca' }, icone('alerta', 20), el('h2', {}, 'O pedido inteiro pode machucar quem copiar')),
      el('p', {}, r.motivo_recusa)));
  }
  if (r.blocos.length) {
    const dica = r.gerador === 'imagem'
      ? 'Cole no gerador de imagem e escolha a proporção nas configurações dele.'
      : r.blocos.length > 1
        ? `Gere cada bloco como um clipe separado de ${r.duracao_clipe} s e junte tudo na aba Montagem.`
        : `Gere como um clipe de ${r.duracao_clipe} s.`;
    partes.push(secao('corretor-blocos', r.blocos.length === 1 ? 'Prompt pronto para copiar' : 'Blocos prontos para copiar', 'copiar', dica,
      ...r.blocos.map((b) => cartaoDoBloco(b, r))));
  }
  if (r.problemas.length) {
    partes.push(secao('corretor-problemas', 'Problemas encontrados', 'alerta', null,
      el('p', { class: 'contagens' }, ...['alta', 'media', 'baixa'].filter((n) => contagem[n]).map((n) =>
        el('span', { class: `contagem ${n}` }, el('span', { class: 'ponto' }), `${contagem[n]} ${n === 'alta' ? 'grave' : n === 'media' ? 'médio' : 'leve'}${contagem[n] > 1 ? 's' : ''}`))),
      el('div', { class: 'problemas' }, ...r.problemas.map(cartaoDoProblema))));
  }
  if (r.acrescentados_pela_ia.length) partes.push(secaoAcrescentados(r));
  if (r.alertas_de_alcance.length) {
    partes.push(secao('corretor-alcance', 'Alertas de alcance no Reels', 'alcance',
      'Nada foi tirado por causa disso: a decisão é sua. São coisas que costumam fazer o Instagram mostrar menos o vídeo para quem não segue você.',
      el('ul', { class: 'alertas' }, ...r.alertas_de_alcance.map((texto) => el('li', {}, icone('alcance', 15), el('span', {}, texto))))));
  }
  if (r.estilo_de_legenda) {
    const aplicar = estado.aplicarEstiloDeLegenda;
    partes.push(secao('corretor-legenda', 'Estilo de legenda sugerido', 'legenda',
      'Faça as legendas no Estúdio, não no gerador: legenda gerada pela IA sai com palavras erradas e fora de sincronia com a voz.',
      el('p', { class: 'estilo-legenda' }, r.estilo_de_legenda),
      aplicar ? el('button', { class: 'botao', type: 'button', onclick: () => aplicar(r.estilo_de_legenda) }, icone('legenda', 15), 'Aplicar nas legendas do Estúdio') : null));
  }
  partes.push(el('p', { class: 'rodape-resultado' }, `Corrigido pelo modelo ${r.modelo}. Confira o resultado antes de gerar: a IA também erra.`));
  return partes;
}

function cartaoDoBloco(b, r) {
  const limite = estado.opcoes.limite_caracteres;
  const botao = el('button', { class: 'botao primario pequeno botao-copiar', type: 'button', onclick: () => copiar(b.prompt, botao) }, icone('copiar', 14), 'Copiar');
  const medidas = [];
  if (b.duracao_estimada_s > 0) medidas.push(el('span', { class: 'medida', title: 'Duração estimada do bloco, com as ações sem fala' }, icone('relogio', 13), `~${numero(b.duracao_estimada_s)} s`));
  if (b.palavras) medidas.push(el('span', { class: 'medida', title: 'Contado pelo Estúdio: palavras ÷ ritmo da fala + folga de silêncio' }, `${b.palavras} palavras · ${numero(b.duracao_fala_s)} s de fala`));
  medidas.push(el('span', { class: `medida${b.caracteres > limite ? ' estourou' : ''}` }, `${milhar(b.caracteres)} / ${milhar(limite)} caracteres`));
  return el('article', { class: 'bloco' },
    el('header', { class: 'bloco-cabeca' }, el('h4', {}, b.titulo), botao),
    el('div', { class: 'medidas' }, ...medidas),
    b.falas.length ? el('div', { class: 'falas' }, ...b.falas.map((f) => el('p', { class: 'fala' },
      f.quem ? el('span', { class: 'quem' }, f.quem) : null, el('span', { class: 'texto-fala' }, `“${f.texto}”`)))) : null,
    ...b.avisos.map((a) => el('p', { class: `aviso ${a.tipo}` }, icone(a.tipo === 'alerta' ? 'alerta' : 'ia', 14), el('span', {}, a.texto))),
    el('pre', { class: 'prompt-corrigido', tabindex: 0 }, b.prompt));
}

function cartaoDoProblema(p) {
  return el('article', { class: `problema ${p.gravidade}` },
    el('div', { class: 'problema-topo' },
      el('span', { class: `selo ${p.gravidade}` }, GRAVIDADES[p.gravidade] || p.gravidade),
      el('span', { class: 'categoria' }, CATEGORIAS[p.categoria] || p.categoria)),
    el('p', { class: 'problema-texto' }, p.problema),
    p.trecho_original ? el('blockquote', { class: 'trecho' }, el('small', {}, 'No seu prompt'), p.trecho_original) : null,
    el('dl', { class: 'detalhes' },
      el('dt', {}, 'Por que dá bug'), el('dd', {}, p.por_que_da_bug),
      el('dt', {}, 'O que mudou'), el('dd', {}, p.o_que_mudou)));
}

function secaoAcrescentados(r) {
  const refazer = el('button', { class: 'botao', type: 'button', disabled: true }, icone('varinha', 15), 'Corrigir de novo sem os desmarcados');
  const caixas = r.acrescentados_pela_ia.map((a) => ({ item: a.item, caixa: el('input', { type: 'checkbox', checked: true }) }));
  const conferir = () => { refazer.disabled = !caixas.some((c) => !c.caixa.checked) || Boolean(estado.controle); };
  caixas.forEach((c) => c.caixa.addEventListener('change', conferir));
  refazer.addEventListener('click', () => {
    const remover = caixas.filter((c) => !c.caixa.checked).map((c) => c.item);
    if (estado.pedido) preencherFormulario(estado.pedido);
    corrigir({ remover_itens: remover });
  });
  return secao('corretor-acrescentados', 'O que a IA colocou sem você pedir', 'ia',
    'Marcado continua no prompt. Desmarque o que você não quer e corrija de novo.',
    el('div', { class: 'acrescentados' }, ...r.acrescentados_pela_ia.map((a, i) => el('label', { class: 'item-a-mais' },
      caixas[i].caixa,
      el('span', {}, el('strong', {}, a.item), el('small', {}, a.risco))))),
    refazer);
}

// Histórico (só neste navegador)

function lerHistorico() {
  const lista = lembrar('corretor.historico', []);
  return Array.isArray(lista) ? lista.filter((h) => h && h.resultado && h.pedido) : [];
}

function salvarNoHistorico(pedido, resultado) {
  const id = `${Date.now()}`;
  const lista = [{ id, pedido, resultado }, ...lerHistorico()].slice(0, HISTORICO_MAXIMO);
  guardar('corretor.historico', lista);
  return id;
}

function desenharHistorico() {
  const caixa = $('#corretor-historico');
  if (!caixa) return;
  const lista = lerHistorico();
  if (!lista.length) {
    caixa.replaceChildren();
    return;
  }
  caixa.replaceChildren(
    el('div', { class: 'historico-titulo' }, el('span', {}, icone('relogio', 14), 'Últimas correções'),
      el('button', { class: 'botao fantasma pequeno', type: 'button', onclick: () => {
        if (!confirm('Apagar o histórico de correções deste navegador?')) return;
        guardar('corretor.historico', []);
        desenharHistorico();
      } }, 'Limpar')),
    el('ul', {}, ...lista.map((h) => {
      const r = h.resultado;
      const quando = new Date(r.gerada_em);
      const titulo = h.pedido.prompt.replace(/\s+/g, ' ').trim();
      return el('li', {}, el('button', {
        type: 'button', class: `historico-item${h.id === estado.historicoId ? ' atual' : ''}`, title: titulo.slice(0, 300),
        onclick: () => abrirDoHistorico(h),
      },
      el('span', { class: 'historico-prompt' }, titulo),
      el('small', {}, [gerador(r.gerador)?.nome.replace(/ \(.*\)$/, ''), `${r.problemas.length} problemas`, `${r.blocos.length} ${r.blocos.length === 1 ? 'bloco' : 'blocos'}`,
        Number.isNaN(quando.getTime()) ? null : quando.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })].filter(Boolean).join(' · '))));
    })));
}

function abrirDoHistorico(h) {
  if (estado.controle) return;
  preencherFormulario(h.pedido);
  Object.assign(estado, { fase: 'pronto', resultado: h.resultado, pedido: h.pedido, historicoId: h.id, erro: null });
  desenharLado();
  desenharHistorico();
  $('#corretor-lado').scrollTop = 0;
}
