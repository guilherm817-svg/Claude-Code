// Tela principal do Estúdio: junta mídia, prévia, linha do tempo, painel do clipe e exportação.

import { api } from './api.js';
import { corretorAberto, iniciarCorretor, mostrarAba } from './corretor.js';
import { icone } from './icones.js';
import { LinhaDoTempo, desenharOnda, desenharTira } from './linha.js';
import { Previa } from './previa.js';
import { $, avisar, el, guardar, lembrar, limitar, relogio, segundos, tamanhoArquivo } from './util.js';

const DURACAO_MINIMA = 0.1;
const QUADRO = 1 / 30; // passo das setas e dos botões de ajuste fino

const estado = {
  config: null,
  projeto: null,
  selecionado: null,
  desfazer: [],
  refazer: [],
  imagens: new Map(),
  ondas: new Map(),
  importando: [],
  errosDePrevia: new Set(),
  edicao: null,
  salvar: { timer: null, emAndamento: null, erro: false },
};

// Utilidades do projeto

function novoId() {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

const midiaDe = (id) => estado.projeto.midias.find((m) => m.id === id);
const formatoAtual = () => estado.config.formatos[estado.projeto.formato];

function sequencia() {
  let inicio = 0;
  return estado.projeto.linha.map((item) => {
    const midia = midiaDe(item.midia_id);
    const duracao = item.saida - item.entrada;
    const segmento = { item, midia, inicio, duracao, url: api.urlArquivo(estado.projeto.id, midia.id) };
    inicio += duracao;
    return segmento;
  });
}

function segmentoEm(tempo) {
  return sequencia().find((s) => tempo >= s.inicio && tempo < s.inicio + s.duracao) || null;
}

function corteSugerido(midia) {
  if (midia.fala_inicio === null || midia.fala_fim === null) return [0, midia.duracao];
  const entrada = Math.max(0, midia.fala_inicio - estado.config.folga_antes);
  const saida = Math.min(midia.duracao, midia.fala_fim + estado.config.folga_depois);
  return saida - entrada < DURACAO_MINIMA ? [0, midia.duracao] : [round3(entrada), round3(saida)];
}

const round3 = (v) => Math.round(v * 1000) / 1000;

// Avisos que dependem do formato escolhido, somados aos que o servidor achou na importação.
function avisosDaMidia(midia) {
  const avisos = midia.avisos.map((a) => a.texto);
  const { largura, altura } = formatoAtual();
  if (Math.abs(midia.largura / midia.altura - largura / altura) > 0.02) {
    avisos.push(estado.projeto.enquadramento === 'preencher'
      ? 'A proporção é diferente do formato: as sobras nas bordas serão cortadas.'
      : 'A proporção é diferente do formato: o vídeo entra inteiro, com fundo desfocado.');
  }
  if (midia.largura < largura * 0.9 && midia.altura < altura * 0.9) {
    avisos.push(`Resolução ${midia.largura}×${midia.altura}: será ampliada para ${largura}×${altura}. `
      + 'Se o gerador oferecer, baixe em 1080p para ficar mais nítido.');
  }
  return avisos;
}

// Desfazer, refazer e salvamento automático

function instantaneo() {
  const { nome, formato, enquadramento, igualar_volume, linha } = estado.projeto;
  return JSON.stringify({ nome, formato, enquadramento, igualar_volume, linha });
}

function registrar(antes) {
  if (antes !== instantaneo()) {
    estado.desfazer.push(antes);
    if (estado.desfazer.length > 200) estado.desfazer.shift();
    estado.refazer = [];
    agendarSalvamento();
  }
  atualizar();
}

function editar(mudanca) {
  const antes = instantaneo();
  mudanca(estado.projeto);
  registrar(antes);
}

function restaurar(texto) {
  Object.assign(estado.projeto, JSON.parse(texto));
  if (!estado.projeto.linha.some((i) => i.id === estado.selecionado)) estado.selecionado = null;
  agendarSalvamento();
  atualizar();
}

function desfazer() {
  if (!estado.desfazer.length) return;
  estado.refazer.push(instantaneo());
  restaurar(estado.desfazer.pop());
}

function refazer() {
  if (!estado.refazer.length) return;
  estado.desfazer.push(instantaneo());
  restaurar(estado.refazer.pop());
}

function mostrarSalvamento(texto, tipo = '') {
  const alvo = $('#estado-salvo');
  alvo.textContent = texto;
  alvo.className = `estado-salvo ${tipo}`;
}

function agendarSalvamento() {
  clearTimeout(estado.salvar.timer);
  mostrarSalvamento('Salvando…');
  estado.salvar.timer = setTimeout(salvarAgora, 400);
}

async function salvarAgora() {
  clearTimeout(estado.salvar.timer);
  estado.salvar.timer = null;
  const projeto = estado.projeto;
  try {
    const salvo = await api.salvar(projeto);
    projeto.atualizado_em = salvo.atualizado_em;
    estado.salvar.erro = false;
    if (!estado.salvar.timer) mostrarSalvamento('Tudo salvo');
  } catch (erro) {
    estado.salvar.erro = true;
    mostrarSalvamento('Não salvo', 'erro');
    avisar(`Não consegui salvar: ${erro.message}`, 'erro');
  }
}

async function garantirSalvo() {
  if (estado.salvar.timer || estado.salvar.erro) await salvarAgora();
}

// Imagens e ondas de cada mídia, carregadas uma vez

function carregarRecursos(midia) {
  if (!estado.imagens.has(midia.id)) {
    const imagem = new Image();
    imagem.onload = () => atualizar();
    imagem.src = api.urlTira(estado.projeto.id, midia.id);
    estado.imagens.set(midia.id, imagem);
  }
  if (!estado.ondas.has(midia.id)) {
    estado.ondas.set(midia.id, null);
    api.onda(estado.projeto.id, midia.id).then((onda) => {
      estado.ondas.set(midia.id, onda);
      atualizar();
    }).catch(() => {});
  }
}

// Ações de edição

function selecionar(id, tempo) {
  estado.selecionado = id;
  if (tempo !== undefined) previa.buscar(tempo);
  atualizar();
}

function aparar(id, lado, valor) {
  const item = estado.projeto.linha.find((i) => i.id === id);
  const midia = midiaDe(item.midia_id);
  if (lado === 'inicio') item.entrada = round3(limitar(valor, 0, item.saida - DURACAO_MINIMA));
  else item.saida = round3(limitar(valor, item.entrada + DURACAO_MINIMA, midia.duracao));
  atualizar();
}

function comecarEdicao() {
  estado.edicao = instantaneo();
}

function terminarEdicao() {
  if (estado.edicao !== null) registrar(estado.edicao);
  estado.edicao = null;
}

function reordenar(id, destino) {
  editar((p) => {
    const atual = p.linha.findIndex((i) => i.id === id);
    const [item] = p.linha.splice(atual, 1);
    p.linha.splice(destino, 0, item);
  });
  estado.selecionado = id;
  const segmento = sequencia().find((s) => s.item.id === id);
  previa.buscar(segmento.inicio);
  atualizar();
}

function itemSelecionado() {
  return estado.projeto.linha.find((i) => i.id === estado.selecionado) || null;
}

function removerSelecionado() {
  const item = itemSelecionado();
  if (!item) return;
  const indice = estado.projeto.linha.indexOf(item);
  editar((p) => p.linha.splice(indice, 1));
  const proximo = estado.projeto.linha[indice] || estado.projeto.linha[indice - 1];
  estado.selecionado = proximo?.id || null;
  atualizar();
}

function duplicarSelecionado() {
  const item = itemSelecionado();
  if (!item) return;
  const copia = { ...item, id: novoId() };
  editar((p) => p.linha.splice(p.linha.indexOf(item) + 1, 0, copia));
  estado.selecionado = copia.id;
  atualizar();
}

function dividirNaAgulha() {
  const segmento = segmentoEm(previa.tempo);
  if (!segmento) return;
  const corte = round3(segmento.item.entrada + (previa.tempo - segmento.inicio));
  if (corte - segmento.item.entrada < DURACAO_MINIMA || segmento.item.saida - corte < DURACAO_MINIMA) {
    avisar('A agulha está muito perto da borda do clipe para dividir.');
    return;
  }
  const segunda = { ...segmento.item, id: novoId(), entrada: corte };
  editar((p) => {
    const item = p.linha.find((i) => i.id === segmento.item.id);
    item.saida = corte;
    p.linha.splice(p.linha.indexOf(item) + 1, 0, segunda);
  });
  estado.selecionado = segunda.id;
  atualizar();
}

// I e O: o clipe embaixo da agulha passa a começar (ou terminar) ali.
function marcarNaAgulha(lado) {
  const segmento = segmentoEm(previa.tempo) || (previa.tempo >= previa.total && sequencia().at(-1));
  if (!segmento) return;
  const ponto = segmento.item.entrada + (previa.tempo - segmento.inicio);
  editar((p) => {
    const item = p.linha.find((i) => i.id === segmento.item.id);
    if (lado === 'inicio') item.entrada = round3(limitar(ponto, 0, item.saida - DURACAO_MINIMA));
    else item.saida = round3(limitar(ponto, item.entrada + DURACAO_MINIMA, segmento.midia.duracao));
  });
  estado.selecionado = segmento.item.id;
  if (lado === 'inicio') previa.buscar(segmento.inicio);
  atualizar();
}

function cortarSilencio(item) {
  const [entrada, saida] = corteSugerido(midiaDe(item.midia_id));
  editar((p) => Object.assign(p.linha.find((i) => i.id === item.id), { entrada, saida }));
}

function usarClipeInteiro(item) {
  const midia = midiaDe(item.midia_id);
  editar((p) => Object.assign(p.linha.find((i) => i.id === item.id), { entrada: 0, saida: midia.duracao }));
}

function ajustarCorte(item, lado, delta) {
  editar(() => aparar(item.id, lado, (lado === 'inicio' ? item.entrada : item.saida) + delta));
}

function adicionarNaLinha(midia) {
  const [entrada, saida] = corteSugerido(midia);
  const item = { id: novoId(), midia_id: midia.id, entrada, saida };
  const selecionado = itemSelecionado();
  editar((p) => {
    const posicao = selecionado ? p.linha.indexOf(p.linha.find((i) => i.id === selecionado.id)) + 1 : p.linha.length;
    p.linha.splice(posicao, 0, item);
  });
  estado.selecionado = item.id;
  previa.buscar(sequencia().find((s) => s.item.id === item.id).inicio);
  atualizar();
}

function irParaClipe(direcao) {
  const seq = sequencia();
  if (!seq.length) return;
  const tempo = previa.tempo;
  if (direcao < 0) {
    const anterior = [...seq].reverse().find((s) => s.inicio < tempo - 0.05);
    previa.buscar(anterior ? anterior.inicio : 0);
  } else {
    const proximo = seq.find((s) => s.inicio > tempo + 0.001);
    previa.buscar(proximo ? proximo.inicio : previa.total);
  }
}

// Importação

async function importar(arquivos) {
  const aceitas = estado.config.extensoes;
  const lista = [...arquivos].sort((a, b) => a.name.localeCompare(b.name, 'pt-BR', { numeric: true }));
  const validos = lista.filter((a) => aceitas.some((ext) => a.name.toLowerCase().endsWith(ext)));
  if (validos.length < lista.length) {
    avisar(`Ignorei ${lista.length - validos.length} arquivo(s) que não são vídeo (aceitos: `
      + `${aceitas.map((e) => e.slice(1).toUpperCase()).join(', ')}).`, 'erro');
  }
  if (!validos.length) return;
  await garantirSalvo();
  const projetoId = estado.projeto.id;
  for (const arquivo of validos) {
    const tarefa = { id: novoId(), nome: arquivo.name, progresso: 0, analisando: false };
    estado.importando.push(tarefa);
    desenharImportacoes();
    try {
      const resposta = await api.importar(projetoId, arquivo, (p) => {
        tarefa.progresso = p;
        tarefa.analisando = p >= 1;
        desenharImportacoes();
      });
      if (estado.projeto.id !== projetoId) continue;
      const antes = instantaneo();
      estado.projeto.midias.push(resposta.midia);
      estado.projeto.linha.push(resposta.item);
      carregarRecursos(resposta.midia);
      // O servidor já gravou o clipe no fim da linha; desfazer tira ele da linha (a mídia continua importada).
      estado.desfazer.push(antes);
      estado.refazer = [];
      agendarSalvamento();
      const primeiro = estado.projeto.linha.length === 1;
      atualizar();
      if (primeiro || estado.projeto.linha.length <= 3) linha.ajustar();
    } catch (erro) {
      avisar(erro.message, 'erro', 8000);
    } finally {
      estado.importando = estado.importando.filter((t) => t !== tarefa);
      desenharImportacoes();
    }
  }
}

function desenharImportacoes() {
  const caixa = $('#importacoes');
  caixa.replaceChildren(...estado.importando.map((t) => el('div', { class: 'importacao' },
    el('div', { class: 'importacao-nome' }, t.analisando ? `Analisando ${t.nome}…` : `Enviando ${t.nome}`),
    el('div', { class: 'barra' }, el('span', { style: { width: `${Math.round(t.progresso * 100)}%` } })))));
}

// Desenho da tela

function atualizar() {
  if (!estado.projeto) return;
  const seq = sequencia();
  const formato = formatoAtual();
  previa.definirFormato(formato.largura, formato.altura, estado.projeto.enquadramento);
  previa.definirSequencia(seq);
  linha.definir({ sequencia: seq, selecionado: estado.selecionado });
  desenharTopo();
  desenharMidias();
  desenharInspetor();
  desenharTransporte();
  $('#previa-vazia').hidden = seq.length > 0;
  $('#zona-segura').hidden = !(estado.projeto.formato === 'reels' && lembrar('zonaSegura', false) && seq.length);
}

function desenharTopo() {
  const nome = $('#nome-projeto');
  if (document.activeElement !== nome) nome.value = estado.projeto.nome;
  $('#btn-desfazer').disabled = !estado.desfazer.length;
  $('#btn-refazer').disabled = !estado.refazer.length;
  $('#btn-exportar').disabled = !estado.projeto.linha.length;
}

function desenharMidias() {
  const lista = $('#lista-midias');
  const usos = new Map();
  estado.projeto.linha.forEach((i) => usos.set(i.midia_id, (usos.get(i.midia_id) || 0) + 1));
  if (!estado.projeto.midias.length) {
    lista.replaceChildren(el('p', { class: 'vazio' }, 'Nenhum clipe ainda. Arraste os vídeos do Flow para cá.'));
    return;
  }
  lista.replaceChildren(...estado.projeto.midias.map((midia) => {
    const avisos = avisosDaMidia(midia);
    const capa = el('div', { class: 'midia-capa' });
    const imagem = estado.imagens.get(midia.id);
    if (midia.tira_quadros && imagem) {
      const meio = Math.floor(midia.tira_quadros / 2);
      capa.style.backgroundImage = `url("${imagem.src}")`;
      capa.style.backgroundSize = `${midia.tira_quadros * 100}% 100%`;
      capa.style.backgroundPosition = `${(meio / Math.max(1, midia.tira_quadros - 1)) * 100}% 0`;
    }
    const usado = usos.get(midia.id) || 0;
    return el('div', { class: 'midia', title: midia.nome },
      capa,
      el('div', { class: 'midia-info' },
        el('div', { class: 'midia-nome' }, midia.nome),
        el('div', { class: 'midia-detalhe' },
          `${segundos(midia.duracao, 1)} · ${midia.largura}×${midia.altura}`,
          usado ? el('span', { class: 'etiqueta' }, usado > 1 ? `na linha ${usado}×` : 'na linha') : null,
          avisos.length ? el('span', { class: 'etiqueta alerta', title: avisos.join('\n') }, icone('alerta', 12), avisos.length) : null)),
      el('div', { class: 'midia-acoes' },
        el('button', { class: 'botao-icone', title: 'Colocar na linha do tempo', onclick: () => adicionarNaLinha(midia) }, icone('mais')),
        el('button', { class: 'botao-icone perigo', title: 'Apagar do projeto', onclick: () => apagarMidia(midia) }, icone('lixeira'))));
  }));
}

async function apagarMidia(midia) {
  const usos = estado.projeto.linha.filter((i) => i.midia_id === midia.id).length;
  const aviso = usos ? `\n\nEle está na linha do tempo ${usos === 1 ? 'uma vez' : `${usos} vezes`} e sai de lá também.` : '';
  if (!confirm(`Apagar “${midia.nome}” do projeto? Isso não dá para desfazer.${aviso}`)) return;
  await garantirSalvo();
  try {
    await api.removerMidia(estado.projeto.id, midia.id);
  } catch (erro) {
    avisar(erro.message, 'erro');
    return;
  }
  estado.projeto.midias = estado.projeto.midias.filter((m) => m.id !== midia.id);
  estado.projeto.linha = estado.projeto.linha.filter((i) => i.midia_id !== midia.id);
  estado.desfazer = [];
  estado.refazer = [];
  if (!estado.projeto.linha.some((i) => i.id === estado.selecionado)) estado.selecionado = null;
  atualizar();
}

function campoDeCorte(item, lado, rotulo) {
  const valor = lado === 'inicio' ? item.entrada : item.saida;
  return el('div', { class: 'campo-corte' },
    el('span', { class: 'rotulo' }, rotulo),
    el('div', { class: 'ajuste-fino' },
      el('button', { class: 'botao-icone pequeno', title: 'Um quadro para trás', onclick: () => ajustarCorte(item, lado, -QUADRO) }, '−'),
      el('output', {}, segundos(valor)),
      el('button', { class: 'botao-icone pequeno', title: 'Um quadro para a frente', onclick: () => ajustarCorte(item, lado, QUADRO) }, '+')));
}

function desenharInspetor() {
  const painel = $('#inspetor');
  const item = itemSelecionado();
  if (!item) {
    painel.replaceChildren(...painelDoProjeto());
    return;
  }
  const midia = midiaDe(item.midia_id);
  const avisos = avisosDaMidia(midia);
  const [entradaSugerida, saidaSugerida] = corteSugerido(midia);
  const jaSugerido = Math.abs(item.entrada - entradaSugerida) < 0.002 && Math.abs(item.saida - saidaSugerida) < 0.002;
  const removido = item.entrada + (midia.duracao - item.saida);
  painel.replaceChildren(
    el('div', { class: 'painel-titulo' }, 'Clipe selecionado',
      el('button', { class: 'botao-icone pequeno', title: 'Fechar (Esc)', onclick: () => selecionar(null) }, icone('fechar', 14))),
    el('div', { class: 'inspetor-corpo' },
      el('h3', { class: 'clipe-titulo' }, midia.nome),
      el('p', { class: 'resumo-corte' },
        `Usando ${segundos(item.saida - item.entrada)} de ${segundos(midia.duracao)}`,
        removido > 0.005 ? ` · ${segundos(removido)} cortados` : ''),
      editorDeCorte(item, midia),
      el('div', { class: 'cortes' }, campoDeCorte(item, 'inicio', 'Começa em'), campoDeCorte(item, 'fim', 'Termina em')),
      el('div', { class: 'grade-botoes' },
        el('button', { class: 'botao', disabled: jaSugerido || midia.fala_inicio === null, onclick: () => cortarSilencio(item),
          title: 'Corta o silêncio antes da primeira e depois da última palavra' }, icone('raio', 15), 'Cortar silêncio'),
        el('button', { class: 'botao', disabled: item.entrada === 0 && item.saida === midia.duracao, onclick: () => usarClipeInteiro(item) },
          icone('expandir', 15), 'Clipe inteiro'),
        el('button', { class: 'botao', onclick: () => marcarNaAgulha('inicio'), title: 'O clipe passa a começar na agulha (I)' }, icone('marcarInicio', 15), 'Início na agulha'),
        el('button', { class: 'botao', onclick: () => marcarNaAgulha('fim'), title: 'O clipe passa a terminar na agulha (O)' }, icone('marcarFim', 15), 'Fim na agulha')),
      avisos.length ? el('div', { class: 'lista-avisos' }, ...avisos.map((texto) => el('p', { class: 'aviso' }, icone('alerta', 14), el('span', {}, texto)))) : null,
      el('dl', { class: 'ficha' },
        el('dt', {}, 'Resolução'), el('dd', {}, `${midia.largura}×${midia.altura}`),
        el('dt', {}, 'Quadros/s'), el('dd', {}, String(midia.fps).replace('.', ',')),
        el('dt', {}, 'Codec'), el('dd', {}, midia.codec),
        el('dt', {}, 'Som'), el('dd', {}, midia.tem_audio ? 'sim' : 'não'),
        midia.fala_inicio !== null ? [el('dt', {}, 'Fala'), el('dd', {}, `de ${segundos(midia.fala_inicio)} a ${segundos(midia.fala_fim)}`)] : null)));
}

// Visão do clipe inteiro, com a parte usada clara e as alças de corte arrastáveis.
function editorDeCorte(item, midia) {
  const canvas = el('canvas', { class: 'editor-corte', 'aria-label': 'Corte do clipe: arraste as alças' });
  requestAnimationFrame(() => {
    const largura = canvas.clientWidth || 260;
    const altura = 76;
    const densidade = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(largura * densidade);
    canvas.height = Math.round(altura * densidade);
    const ctx = canvas.getContext('2d');
    ctx.scale(densidade, densidade);
    const pps = largura / midia.duracao;
    desenharTira(ctx, estado.imagens.get(midia.id), midia, 0, pps, largura, 46);
    ctx.fillStyle = '#151a26';
    ctx.fillRect(0, 46, largura, altura - 46);
    desenharOnda(ctx, estado.ondas.get(midia.id), 0, pps, largura, 48, altura - 50, '#5eead4');
    if (midia.fala_inicio !== null) {
      ctx.fillStyle = '#a78bfa';
      ctx.fillRect(midia.fala_inicio * pps, altura - 2, (midia.fala_fim - midia.fala_inicio) * pps, 2);
    }
    ctx.fillStyle = 'rgba(8, 10, 16, 0.72)';
    ctx.fillRect(0, 0, item.entrada * pps, altura);
    ctx.fillRect(item.saida * pps, 0, largura - item.saida * pps, altura);
    ctx.fillStyle = '#fbbf24';
    for (const t of [item.entrada, item.saida]) ctx.fillRect(Math.round(t * pps) - 1.5, 0, 3, altura);
    const segmento = sequencia().find((s) => s.item.id === item.id);
    if (segmento && previa.tempo >= segmento.inicio && previa.tempo <= segmento.inicio + segmento.duracao) {
      ctx.fillStyle = '#f43f5e';
      ctx.fillRect(Math.round((item.entrada + previa.tempo - segmento.inicio) * pps) - 1, 0, 2, altura);
    }
  });
  canvas.addEventListener('pointerdown', (e) => {
    const largura = canvas.clientWidth;
    const pps = largura / midia.duracao;
    const x = e.clientX - canvas.getBoundingClientRect().left;
    const perto = (t) => Math.abs(t * pps - x) <= 10;
    const lado = perto(item.entrada) ? 'inicio' : perto(item.saida) ? 'fim' : null;
    const segmento = sequencia().find((s) => s.item.id === item.id);
    if (!lado) {
      const t = x / pps;
      if (t >= item.entrada && t <= item.saida) previa.buscar(segmento.inicio + (t - item.entrada));
      return;
    }
    e.preventDefault();
    canvas.setPointerCapture(e.pointerId);
    comecarEdicao();
    const mover = (ev) => aparar(item.id, lado, (ev.clientX - canvas.getBoundingClientRect().left) / pps);
    canvas.addEventListener('pointermove', mover);
    canvas.addEventListener('pointerup', () => {
      canvas.removeEventListener('pointermove', mover);
      terminarEdicao();
    }, { once: true });
  });
  canvas.addEventListener('pointermove', (e) => {
    const pps = canvas.clientWidth / midia.duracao;
    const x = e.clientX - canvas.getBoundingClientRect().left;
    const perto = [item.entrada, item.saida].some((t) => Math.abs(t * pps - x) <= 10);
    canvas.style.cursor = perto ? 'ew-resize' : 'pointer';
  });
  return canvas;
}

function painelDoProjeto() {
  const p = estado.projeto;
  const formatos = Object.entries(estado.config.formatos);
  const seq = sequencia();
  const comAviso = seq.filter((s) => avisosDaMidia(s.midia).length).length;
  const radio = (valor, titulo, descricao) => el('label', { class: 'opcao' },
    el('input', { type: 'radio', name: 'enquadramento', value: valor, checked: p.enquadramento === valor,
      onchange: () => editar((proj) => { proj.enquadramento = valor; }) }),
    el('span', {}, el('strong', {}, titulo), el('small', {}, descricao)));
  return [
    el('div', { class: 'painel-titulo' }, 'Projeto'),
    el('div', { class: 'inspetor-corpo' },
      el('div', { class: 'numeros' },
        el('div', {}, el('strong', {}, relogio(previa.total)), el('small', {}, 'duração')),
        el('div', {}, el('strong', {}, String(seq.length)), el('small', {}, seq.length === 1 ? 'clipe' : 'clipes')),
        el('div', {}, el('strong', {}, String(comAviso)), el('small', {}, 'com aviso'))),
      el('label', { class: 'campo' }, el('span', { class: 'rotulo' }, 'Formato'),
        el('select', { onchange: (e) => editar((proj) => { proj.formato = e.target.value; }) },
          ...formatos.map(([chave, f]) => el('option', { value: chave, selected: chave === p.formato }, `${f.nome} · ${f.largura}×${f.altura}`)))),
      el('div', { class: 'campo' }, el('span', { class: 'rotulo' }, 'Quando o clipe não tem a mesma proporção'),
        radio('preencher', 'Preencher a tela', 'Amplia e corta as sobras das bordas.'),
        radio('desfocado', 'Fundo desfocado', 'Mostra o vídeo inteiro sobre ele mesmo desfocado.')),
      el('label', { class: 'opcao caixa' },
        el('input', { type: 'checkbox', checked: p.igualar_volume, onchange: (e) => editar((proj) => { proj.igualar_volume = e.target.checked; }) }),
        el('span', {}, el('strong', {}, 'Igualar o volume'), el('small', {}, 'Deixa todos os clipes no mesmo volume, no padrão das redes (−14 LUFS).'))),
      el('details', { class: 'atalhos' },
        el('summary', {}, 'Atalhos de teclado'),
        el('dl', {}, ...[
          ['Espaço', 'tocar / pausar'], ['← →', 'um quadro (Shift: 1 s)'], ['↑ ↓', 'clipe anterior / próximo'],
          ['S', 'dividir na agulha'], ['I / O', 'começo / fim do clipe na agulha'], ['Ctrl+D', 'duplicar clipe'],
          ['Delete', 'tirar clipe da linha'], ['Ctrl+Z', 'desfazer'], ['Ctrl+Shift+Z', 'refazer'], ['Z', 'mostrar o vídeo inteiro'],
        ].flatMap(([tecla, acao]) => [el('dt', {}, el('kbd', {}, tecla)), el('dd', {}, acao)])))),
  ];
}

function desenharTransporte() {
  $('#tempo-atual').textContent = relogio(previa.tempo);
  $('#tempo-total').textContent = relogio(previa.total);
  const tocar = $('#btn-tocar');
  tocar.replaceChildren(icone(previa.tocando ? 'pausar' : 'tocar', 20));
  tocar.title = previa.tocando ? 'Pausar (Espaço)' : 'Tocar (Espaço)';
  const mudo = lembrar('mudo', false);
  $('#btn-mudo').replaceChildren(icone(mudo ? 'mudo' : 'som'));
  $('#btn-zona').classList.toggle('ativo', lembrar('zonaSegura', false));
  $('#btn-zona').hidden = estado.projeto.formato !== 'reels';
}

// Exportação

async function abrirExportacao() {
  const dialogo = $('#dialogo-exportar');
  const p = estado.projeto;
  const formato = formatoAtual();
  const seq = sequencia();
  const avisos = seq.filter((s) => s.midia.avisos.some((a) => a.codigo.startsWith('fala_no')));
  $('#exportar-resumo').replaceChildren(
    el('li', {}, el('span', {}, 'Formato'), el('strong', {}, `${formato.nome} · ${formato.largura}×${formato.altura}`)),
    el('li', {}, el('span', {}, 'Duração'), el('strong', {}, `${relogio(previa.total)} · ${seq.length} ${seq.length === 1 ? 'clipe' : 'clipes'}`)),
    el('li', {}, el('span', {}, 'Proporção diferente'), el('strong', {}, p.enquadramento === 'preencher' ? 'preencher a tela' : 'fundo desfocado')),
    el('li', {}, el('span', {}, 'Volume'), el('strong', {}, p.igualar_volume ? 'igualado (−14 LUFS)' : 'original de cada clipe')));
  $('#exportar-avisos').replaceChildren(...(avisos.length ? [el('p', { class: 'aviso' }, icone('alerta', 14),
    el('span', {}, `${avisos.length} ${avisos.length === 1 ? 'clipe pode ter' : 'clipes podem ter'} palavra cortada na geração. Vale ouvir antes de postar.`))] : []));
  mostrarFaseExportacao('inicio');
  dialogo.showModal();
  desenharExportados();
}

function mostrarFaseExportacao(fase) {
  $('#exportar-progresso').hidden = fase !== 'rodando';
  $('#exportar-pronto').hidden = fase !== 'pronto';
  $('#btn-iniciar-exportacao').hidden = fase === 'rodando';
  $('#btn-iniciar-exportacao').textContent = fase === 'pronto' ? 'Exportar de novo' : 'Exportar vídeo';
  $('#btn-cancelar-exportacao').hidden = fase !== 'rodando';
  $('#btn-fechar-exportacao').hidden = fase === 'rodando';
}

async function desenharExportados() {
  const lista = $('#exportados');
  try {
    const arquivos = await api.exportados(estado.projeto.id);
    lista.replaceChildren(...(arquivos.length
      ? [el('h3', {}, 'Já exportados'), ...arquivos.slice(0, 6).map((a) => el('a', {
        class: 'exportado', href: api.urlExportado(estado.projeto.id, a.nome), download: a.nome,
      }, icone('baixar', 15), el('span', {}, a.nome), el('small', {}, tamanhoArquivo(a.tamanho))))]
      : []));
  } catch { lista.replaceChildren(); }
}

let exportacaoAtual = null;

async function iniciarExportacao() {
  await garantirSalvo();
  mostrarFaseExportacao('rodando');
  const barra = $('#exportar-progresso .barra span');
  const etapa = $('#exportar-etapa');
  barra.style.width = '0%';
  etapa.textContent = 'Preparando…';
  try {
    let exportacao = await api.exportar(estado.projeto.id);
    exportacaoAtual = exportacao.id;
    while (exportacao.estado === 'preparando' || exportacao.estado === 'renderizando') {
      barra.style.width = `${Math.round(exportacao.progresso * 100)}%`;
      etapa.textContent = `${exportacao.etapa} ${Math.round(exportacao.progresso * 100)}%`;
      await new Promise((r) => setTimeout(r, 400));
      exportacao = await api.exportacao(exportacao.id);
    }
    exportacaoAtual = null;
    if (exportacao.estado === 'pronta') {
      const link = $('#link-baixar');
      link.href = api.urlExportado(estado.projeto.id, exportacao.arquivo);
      link.download = exportacao.arquivo;
      $('#nome-exportado').textContent = exportacao.arquivo;
      mostrarFaseExportacao('pronto');
      desenharExportados();
    } else if (exportacao.estado === 'cancelada') {
      mostrarFaseExportacao('inicio');
      avisar('Exportação cancelada.');
    } else {
      mostrarFaseExportacao('inicio');
      avisar(exportacao.erro || 'A exportação falhou.', 'erro', 10000);
    }
  } catch (erro) {
    exportacaoAtual = null;
    mostrarFaseExportacao('inicio');
    avisar(erro.message, 'erro', 8000);
  }
}

// Projetos

async function abrirProjeto(id) {
  await garantirSalvo();
  previa.pausar();
  const projeto = await api.abrir(id);
  estado.projeto = projeto;
  estado.selecionado = null;
  estado.desfazer = [];
  estado.refazer = [];
  estado.imagens.clear();
  estado.ondas.clear();
  estado.errosDePrevia.clear();
  projeto.midias.forEach(carregarRecursos);
  guardar('ultimoProjeto', id);
  mostrarSalvamento('Tudo salvo');
  previa.tempo = 0;
  atualizar();
  linha.ajustar();
}

async function novoProjeto() {
  await garantirSalvo();
  const projeto = await api.criar(null);
  await abrirProjeto(projeto.id);
  $('#nome-projeto').select();
}

async function excluirProjeto() {
  if (!confirm(`Excluir o projeto “${estado.projeto.nome}”? Os clipes importados e os vídeos exportados dele `
    + 'também são apagados. Isso não dá para desfazer.')) return;
  clearTimeout(estado.salvar.timer);
  estado.salvar.timer = null;
  await api.excluir(estado.projeto.id);
  const restantes = await api.listar();
  if (restantes.length) await abrirProjeto(restantes[0].id);
  else await abrirProjeto((await api.criar(null)).id);
}

async function alternarMenuProjetos() {
  const menu = $('#menu-projetos');
  if (!menu.hidden) {
    menu.hidden = true;
    return;
  }
  const projetos = await api.listar();
  menu.replaceChildren(
    el('button', { class: 'menu-item destaque', onclick: () => { menu.hidden = true; novoProjeto(); } }, icone('mais', 15), 'Novo projeto'),
    el('div', { class: 'menu-separador' }),
    ...projetos.map((p) => el('button', {
      class: `menu-item${p.id === estado.projeto.id ? ' atual' : ''}`,
      onclick: () => { menu.hidden = true; if (p.id !== estado.projeto.id) abrirProjeto(p.id); },
    }, el('span', { class: 'menu-nome' }, p.nome), el('small', {}, `${p.clipes} ${p.clipes === 1 ? 'clipe' : 'clipes'} · ${relogio(p.duracao, 0)}`))),
    el('div', { class: 'menu-separador' }),
    el('button', { class: 'menu-item perigo', onclick: () => { menu.hidden = true; excluirProjeto(); } }, icone('lixeira', 15), 'Excluir este projeto'));
  menu.hidden = false;
}

// Teclado

function teclado(e) {
  if (corretorAberto()) return; // os atalhos são da montagem, que está escondida
  const alvo = e.target;
  if (alvo.closest('input, select, textarea, dialog[open]') && !(alvo.type === 'range' || alvo.type === 'checkbox' || alvo.type === 'radio')) return;
  if ($('#dialogo-exportar').open) return;
  const ctrl = e.ctrlKey || e.metaKey;
  const tecla = e.key.toLowerCase();
  const acoes = {
    ' ': () => previa.alternar(),
    arrowleft: () => { previa.pausar(); previa.buscar(previa.tempo - (e.shiftKey ? 1 : QUADRO)); },
    arrowright: () => { previa.pausar(); previa.buscar(previa.tempo + (e.shiftKey ? 1 : QUADRO)); },
    arrowup: () => irParaClipe(-1),
    arrowdown: () => irParaClipe(1),
    home: () => previa.buscar(0),
    end: () => previa.buscar(previa.total),
    delete: removerSelecionado,
    backspace: removerSelecionado,
    escape: () => selecionar(null),
    s: dividirNaAgulha,
    i: () => marcarNaAgulha('inicio'),
    o: () => marcarNaAgulha('fim'),
    z: () => linha.ajustar(),
    '+': () => linha.definirZoom(linha.zoom * 1.4, true),
    '=': () => linha.definirZoom(linha.zoom * 1.4, true),
    '-': () => linha.definirZoom(linha.zoom / 1.4, true),
  };
  let acao = null;
  if (ctrl && tecla === 'z') acao = e.shiftKey ? refazer : desfazer;
  else if (ctrl && tecla === 'y') acao = refazer;
  else if (ctrl && tecla === 'd') acao = duplicarSelecionado;
  else if (!ctrl && !e.altKey) acao = acoes[tecla];
  if (!acao) return;
  e.preventDefault();
  acao();
}

// Montagem da tela

const previa = new Previa({
  area: $('#previa-area'),
  quadro: $('#previa-quadro'),
  canvas: $('#previa'),
  aoMudarTempo: (tempo) => {
    linha.definirTempo(tempo, previa.tocando);
    $('#tempo-atual').textContent = relogio(tempo);
  },
  aoTocarOuPausar: () => {
    desenharTransporte();
    if (!previa.tocando) desenharInspetor();
  },
  aoErro: (midiaId) => {
    if (!midiaId || estado.errosDePrevia.has(midiaId)) return;
    estado.errosDePrevia.add(midiaId);
    const midia = midiaDe(midiaId);
    if (midia) avisar(`A prévia não consegue tocar “${midia.nome}” (${midia.codec}) neste navegador. A exportação funciona normalmente.`, 'erro', 9000);
  },
});

const linha = new LinhaDoTempo($('#linha'), {
  imagem: (id) => estado.imagens.get(id),
  onda: (id) => estado.ondas.get(id),
  avisosDo: (segmento) => avisosDaMidia(segmento.midia),
  aoBuscar: (tempo) => {
    previa.buscar(tempo);
    if (!previa.tocando) desenharInspetor();
  },
  aoSelecionar: (id, tempo) => selecionar(id, tempo),
  aoComecarEdicao: (id) => { estado.selecionado = id; comecarEdicao(); },
  aoAparar: aparar,
  aoTerminarEdicao: terminarEdicao,
  aoReordenar: reordenar,
});

function montarAcoesDaLinha() {
  const botao = (nomeIcone, texto, titulo, acao) => el('button', { class: 'botao fantasma', title: titulo, onclick: acao }, icone(nomeIcone, 15), texto);
  linha.acoes.append(
    botao('tesoura', 'Dividir', 'Dividir o clipe na agulha (S)', dividirNaAgulha),
    botao('duplicar', 'Duplicar', 'Duplicar o clipe selecionado (Ctrl+D)', duplicarSelecionado),
    botao('lixeira', 'Tirar', 'Tirar o clipe selecionado da linha (Delete)', removerSelecionado));
}

function montarEventos() {
  const entrada = $('#arquivos');
  $('#btn-importar').addEventListener('click', () => entrada.click());
  $('#btn-importar-vazio').addEventListener('click', () => entrada.click());
  entrada.addEventListener('change', () => {
    importar(entrada.files);
    entrada.value = '';
  });

  // Arrastar arquivos para qualquer lugar da janela.
  let profundidade = 0;
  const temArquivos = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
  window.addEventListener('dragenter', (e) => {
    if (!temArquivos(e)) return;
    profundidade += 1;
    $('#soltar').hidden = false;
  });
  window.addEventListener('dragleave', (e) => {
    if (!temArquivos(e)) return;
    profundidade = Math.max(0, profundidade - 1);
    if (!profundidade) $('#soltar').hidden = true;
  });
  window.addEventListener('dragover', (e) => { if (temArquivos(e)) e.preventDefault(); });
  window.addEventListener('drop', (e) => {
    if (!temArquivos(e)) return;
    e.preventDefault();
    profundidade = 0;
    $('#soltar').hidden = true;
    if (corretorAberto()) mostrarAba('montagem');
    importar(e.dataTransfer.files);
  });

  const nome = $('#nome-projeto');
  nome.addEventListener('change', () => {
    const valor = nome.value.trim();
    if (!valor) {
      nome.value = estado.projeto.nome;
      return;
    }
    editar((p) => { p.nome = valor.slice(0, 120); });
  });
  nome.addEventListener('keydown', (e) => { if (e.key === 'Enter') nome.blur(); });

  $('#btn-projetos').addEventListener('click', (e) => { e.stopPropagation(); alternarMenuProjetos(); });
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#menu-projetos')) $('#menu-projetos').hidden = true;
  });
  $('#btn-desfazer').addEventListener('click', desfazer);
  $('#btn-refazer').addEventListener('click', refazer);
  $('#btn-exportar').addEventListener('click', abrirExportacao);
  $('#btn-iniciar-exportacao').addEventListener('click', iniciarExportacao);
  $('#btn-cancelar-exportacao').addEventListener('click', () => exportacaoAtual && api.cancelar(exportacaoAtual));
  $('#btn-fechar-exportacao').addEventListener('click', () => $('#dialogo-exportar').close());
  $('#dialogo-exportar').addEventListener('cancel', (e) => { if (exportacaoAtual) e.preventDefault(); });
  $('#btn-abrir-pasta').addEventListener('click', () => api.abrirPasta(estado.projeto.id).catch((erro) => avisar(erro.message, 'erro')));

  $('#btn-tocar').addEventListener('click', () => previa.alternar());
  $('#btn-inicio').addEventListener('click', () => previa.buscar(0));
  $('#btn-fim').addEventListener('click', () => previa.buscar(previa.total));
  $('#btn-anterior').addEventListener('click', () => irParaClipe(-1));
  $('#btn-proximo').addEventListener('click', () => irParaClipe(1));
  $('#btn-mudo').addEventListener('click', () => {
    const mudo = !lembrar('mudo', false);
    guardar('mudo', mudo);
    previa.definirMudo(mudo);
    desenharTransporte();
  });
  $('#btn-zona').addEventListener('click', () => {
    guardar('zonaSegura', !lembrar('zonaSegura', false));
    atualizar();
  });

  document.addEventListener('keydown', teclado);
  // Botão clicado com o mouse não fica com o foco: senão o Espaço "clicaria" nele em vez de tocar o vídeo.
  document.addEventListener('mousedown', (e) => { if (e.target.closest('button')) e.preventDefault(); });
  window.addEventListener('beforeunload', (e) => {
    if (estado.salvar.timer || estado.importando.length || exportacaoAtual) {
      salvarAgora();
      e.preventDefault();
    }
  });
}

function montarIcones() {
  document.querySelectorAll('[data-icone]').forEach((alvo) => alvo.prepend(icone(alvo.dataset.icone, Number(alvo.dataset.tamanho) || 18)));
}

async function iniciar() {
  montarIcones();
  montarAcoesDaLinha();
  montarEventos();
  previa.definirMudo(lembrar('mudo', false));
  iniciarCorretor({ aoTrocarDeAba: (aba) => { if (aba !== 'montagem') previa.pausar(); } });
  try {
    estado.config = await api.config();
    const projetos = await api.listar();
    const ultimo = lembrar('ultimoProjeto', null);
    const id = projetos.find((p) => p.id === ultimo)?.id || projetos[0]?.id || (await api.criar(null)).id;
    await abrirProjeto(id);
  } catch (erro) {
    avisar(`Não consegui abrir o Estúdio: ${erro.message}`, 'erro', 60000);
  }
}

iniciar();
