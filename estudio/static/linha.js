// Linha do tempo: régua, clipes com miniaturas e forma de onda, agulha de reprodução, cortar pelas bordas e
// arrastar para reordenar. Ela não guarda o projeto: avisa o app (callbacks) e o app manda redesenhar.

import { el, limitar, relogio, segundos } from './util.js';
import { icone } from './icones.js';

const ALTURA_TIRA = 50;
const ALTURA_ONDA = 22;
const ZOOM_MINIMO = 8;
const ZOOM_MAXIMO = 400;
const PASSOS_REGUA = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];

// Miniaturas do clipe, escolhendo para cada espaço o quadro do instante que ele representa.
export function desenharTira(ctx, imagem, midia, entrada, pxPorSegundo, largura, altura) {
  ctx.fillStyle = '#232838';
  ctx.fillRect(0, 0, largura, altura);
  if (!imagem || !imagem.complete || !imagem.naturalWidth || !midia.tira_quadros) return;
  const quadros = midia.tira_quadros;
  const lq = imagem.naturalWidth / quadros;
  const aq = imagem.naturalHeight;
  const espaco = Math.max(10, (altura * lq) / aq);
  const passo = midia.duracao / quadros;
  for (let x = 0; x < largura; x += espaco) {
    const t = entrada + (x + espaco / 2) / pxPorSegundo;
    const i = limitar(Math.floor(t / passo), 0, quadros - 1);
    ctx.drawImage(imagem, i * lq, 0, lq, aq, x, 0, espaco, altura);
  }
}

// Forma de onda: o maior pico de cada coluna de pixels (com raiz quadrada, para a fala baixa aparecer).
export function desenharOnda(ctx, onda, entrada, pxPorSegundo, largura, y, altura, cor) {
  if (!onda?.picos?.length) return;
  const { picos } = onda;
  const porSegundo = onda.por_segundo;
  const meio = y + altura / 2;
  ctx.fillStyle = cor;
  for (let x = 0; x < largura; x++) {
    const a = Math.floor((entrada + x / pxPorSegundo) * porSegundo);
    const b = Math.max(a + 1, Math.floor((entrada + (x + 1) / pxPorSegundo) * porSegundo));
    let maior = 0;
    for (let i = a; i < b && i < picos.length; i++) if (picos[i] > maior) maior = picos[i];
    const h = Math.max(1, Math.sqrt(maior) * (altura - 2));
    ctx.fillRect(x, meio - h / 2, 1, h);
  }
}

export class LinhaDoTempo {
  constructor(raiz, opcoes) {
    this.op = opcoes;
    this.zoom = 80; // pixels por segundo
    this.sequencia = [];
    this.selecionado = null;
    this.tempo = 0;
    this.elementos = new Map();

    this.acoes = el('div', { class: 'linha-acoes' });
    this.controleZoom = el('input', {
      type: 'range', min: 0, max: 1000, class: 'zoom', 'aria-label': 'Zoom da linha do tempo',
      oninput: () => this.definirZoom(this._zoomDoControle(), true),
    });
    const ferramentas = el('div', { class: 'linha-ferramentas' },
      this.acoes,
      el('div', { class: 'linha-zoom' },
        el('button', { class: 'botao-icone', title: 'Afastar (−)', onclick: () => this.definirZoom(this.zoom / 1.4, true) }, icone('afastar')),
        this.controleZoom,
        el('button', { class: 'botao-icone', title: 'Aproximar (+)', onclick: () => this.definirZoom(this.zoom * 1.4, true) }, icone('aproximar')),
        el('button', { class: 'botao-icone', title: 'Mostrar o vídeo inteiro (Z)', onclick: () => this.ajustar() }, icone('ajustar'))));

    this.regua = el('canvas', { class: 'regua' });
    this.trilha = el('div', { class: 'trilha' });
    this.vazia = el('div', { class: 'trilha-vazia' }, 'Arraste seus clipes para cá ou clique em Importar');
    this.agulha = el('div', { class: 'agulha' }, el('div', { class: 'agulha-cabeca' }));
    this.marcador = el('div', { class: 'marcador-insercao', hidden: true });
    this.conteudo = el('div', { class: 'linha-conteudo' }, this.regua, this.trilha, this.marcador, this.agulha);
    this.rolagem = el('div', { class: 'linha-rolagem' }, this.conteudo, this.vazia);
    raiz.append(ferramentas, this.rolagem);

    this._arrastarAgulha(this.regua);
    this._arrastarAgulha(this.trilha, true);
    this.rolagem.addEventListener('wheel', (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      this.definirZoom(this.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), true);
    }, { passive: false });
    this.rolagem.addEventListener('scroll', () => this._desenharRegua());
    new ResizeObserver(() => this.render()).observe(this.rolagem);
    this._sincronizarControle();
  }

  get total() {
    const ultimo = this.sequencia[this.sequencia.length - 1];
    return ultimo ? ultimo.inicio + ultimo.duracao : 0;
  }

  definir({ sequencia, selecionado }) {
    this.sequencia = sequencia;
    this.selecionado = selecionado;
    this.render();
  }

  definirTempo(tempo, acompanhar = false) {
    this.tempo = tempo;
    const x = tempo * this.zoom;
    this.agulha.style.transform = `translateX(${x}px)`;
    if (acompanhar) {
      const { scrollLeft, clientWidth } = this.rolagem;
      if (x < scrollLeft || x > scrollLeft + clientWidth - 40) this.rolagem.scrollLeft = x - clientWidth * 0.2;
    }
  }

  // Controle de zoom em escala logarítmica: o mesmo arrasto vale tanto de perto quanto de longe.
  _zoomDoControle() {
    return ZOOM_MINIMO * (ZOOM_MAXIMO / ZOOM_MINIMO) ** (this.controleZoom.value / 1000);
  }

  _sincronizarControle() {
    this.controleZoom.value = String(Math.round(1000 * Math.log(this.zoom / ZOOM_MINIMO) / Math.log(ZOOM_MAXIMO / ZOOM_MINIMO)));
  }

  definirZoom(zoom, manterAgulha = false) {
    const antes = this.tempo * this.zoom - this.rolagem.scrollLeft;
    this.zoom = limitar(zoom, ZOOM_MINIMO, ZOOM_MAXIMO);
    this._sincronizarControle();
    this.render();
    if (manterAgulha) this.rolagem.scrollLeft = this.tempo * this.zoom - antes;
  }

  ajustar() {
    if (!this.total) return;
    this.definirZoom((this.rolagem.clientWidth - 48) / this.total);
    this.rolagem.scrollLeft = 0;
  }

  // Clicar ou arrastar na régua (ou no espaço vazio da trilha) move a agulha.
  _arrastarAgulha(alvo, soNoVazio = false) {
    alvo.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || (soNoVazio && e.target !== alvo)) return;
      e.preventDefault();
      alvo.setPointerCapture(e.pointerId);
      const mover = (ev) => {
        const x = ev.clientX - this.conteudo.getBoundingClientRect().left;
        this.op.aoBuscar(limitar(x / this.zoom, 0, this.total));
      };
      mover(e);
      alvo.addEventListener('pointermove', mover);
      alvo.addEventListener('pointerup', () => alvo.removeEventListener('pointermove', mover), { once: true });
    });
  }

  render() {
    const visivel = this.rolagem.clientWidth || 800;
    const largura = Math.max(visivel, this.total * this.zoom + 160);
    this.conteudo.style.width = `${largura}px`;
    this.vazia.hidden = this.sequencia.length > 0;

    const vistos = new Set();
    for (const segmento of this.sequencia) {
      vistos.add(segmento.item.id);
      let registro = this.elementos.get(segmento.item.id);
      if (!registro) {
        registro = this._criarClipe(segmento.item.id);
        this.elementos.set(segmento.item.id, registro);
        this.trilha.append(registro.raiz);
      }
      this._atualizarClipe(registro, segmento);
    }
    for (const [id, registro] of this.elementos) {
      if (!vistos.has(id)) {
        registro.raiz.remove();
        this.elementos.delete(id);
      }
    }
    // Mantém a ordem do DOM igual à da linha (para leitores de tela e para a tecla Tab).
    this.sequencia.forEach((s, i) => {
      const raiz = this.elementos.get(s.item.id).raiz;
      if (this.trilha.children[i] !== raiz) this.trilha.insertBefore(raiz, this.trilha.children[i] || null);
    });
    this._desenharRegua();
    this.definirTempo(this.tempo);
  }

  _criarClipe(id) {
    const canvas = el('canvas', { class: 'clipe-imagem' });
    const nome = el('span', { class: 'clipe-nome' });
    const duracao = el('span', { class: 'clipe-duracao' });
    const alerta = el('span', { class: 'clipe-alerta', hidden: true }, icone('alerta', 13));
    const alcaInicio = el('div', { class: 'alca inicio', title: 'Arraste para cortar o começo' });
    const alcaFim = el('div', { class: 'alca fim', title: 'Arraste para cortar o fim' });
    const raiz = el('div', { class: 'clipe', tabindex: 0, 'data-id': id },
      canvas, el('div', { class: 'clipe-rotulo' }, alerta, nome, duracao), alcaInicio, alcaFim);
    const registro = { raiz, canvas, nome, duracao, alerta, chave: '' };
    this._aparar(alcaInicio, id, 'inicio');
    this._aparar(alcaFim, id, 'fim');
    this._mover(raiz, id);
    raiz.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this.op.aoSelecionar(id);
    });
    return registro;
  }

  _atualizarClipe(registro, segmento) {
    const { item, midia, inicio, duracao } = segmento;
    const largura = Math.max(4, duracao * this.zoom - 2);
    registro.raiz.style.left = `${inicio * this.zoom}px`;
    registro.raiz.style.width = `${largura}px`;
    registro.raiz.classList.toggle('selecionado', item.id === this.selecionado);
    registro.raiz.classList.toggle('estreito', largura < 70);
    registro.raiz.setAttribute('aria-label', `${midia.nome}, ${segundos(duracao, 1)}`);
    registro.nome.textContent = midia.nome.replace(/\.[^.]+$/, '');
    registro.duracao.textContent = segundos(duracao, 1);
    const avisos = this.op.avisosDo(segmento);
    registro.alerta.hidden = !avisos.length;
    registro.alerta.title = avisos.join('\n');

    const imagem = this.op.imagem(midia.id);
    const onda = this.op.onda(midia.id);
    const chave = [midia.id, item.entrada, item.saida, this.zoom, imagem?.complete && imagem.naturalWidth, !!onda].join('|');
    if (chave === registro.chave) return;
    registro.chave = chave;
    const densidade = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.min(largura, 12000);
    const h = ALTURA_TIRA + ALTURA_ONDA;
    registro.canvas.width = Math.round(w * densidade);
    registro.canvas.height = Math.round(h * densidade);
    const ctx = registro.canvas.getContext('2d');
    ctx.scale(densidade * (w / largura), densidade);
    desenharTira(ctx, imagem, midia, item.entrada, this.zoom, largura, ALTURA_TIRA);
    ctx.fillStyle = '#151a26';
    ctx.fillRect(0, ALTURA_TIRA, largura, ALTURA_ONDA);
    desenharOnda(ctx, onda, item.entrada, this.zoom, largura, ALTURA_TIRA, ALTURA_ONDA, '#5eead4');
  }

  // Arrastar uma borda corta o clipe. Os clipes seguintes andam junto (não fica buraco).
  _aparar(alca, id, lado) {
    alca.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      alca.setPointerCapture(e.pointerId);
      const segmento = this.sequencia.find((s) => s.item.id === id);
      const original = lado === 'inicio' ? segmento.item.entrada : segmento.item.saida;
      const x0 = e.clientX;
      this.op.aoComecarEdicao(id);
      const mover = (ev) => this.op.aoAparar(id, lado, original + (ev.clientX - x0) / this.zoom);
      const soltar = () => {
        alca.removeEventListener('pointermove', mover);
        this.op.aoTerminarEdicao();
      };
      alca.addEventListener('pointermove', mover);
      alca.addEventListener('pointerup', soltar, { once: true });
      alca.addEventListener('pointercancel', soltar, { once: true });
    });
  }

  // Clique seleciona (e leva a agulha até ali); arrastar muda o clipe de lugar.
  _mover(raiz, id) {
    raiz.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.classList.contains('alca')) return;
      e.preventDefault();
      raiz.setPointerCapture(e.pointerId);
      raiz.focus({ preventScroll: true });
      const x0 = e.clientX;
      let arrastando = false;
      let destino = null;
      const mover = (ev) => {
        const dx = ev.clientX - x0;
        if (!arrastando && Math.abs(dx) < 5) return;
        arrastando = true;
        raiz.classList.add('arrastando');
        raiz.style.transform = `translateX(${dx}px)`;
        const x = ev.clientX - this.conteudo.getBoundingClientRect().left;
        const outros = this.sequencia.filter((s) => s.item.id !== id);
        destino = outros.filter((s) => (s.inicio + s.duracao / 2) * this.zoom < x).length;
        this.marcador.hidden = false;
        this.marcador.style.transform = `translateX(${this._posicaoReal(outros.slice(0, destino), id)}px)`;
      };
      const soltar = (ev) => {
        raiz.removeEventListener('pointermove', mover);
        raiz.classList.remove('arrastando');
        raiz.style.transform = '';
        this.marcador.hidden = true;
        if (arrastando && destino !== null) {
          this.op.aoReordenar(id, destino);
        } else if (ev.type === 'pointerup') {
          const x = ev.clientX - this.conteudo.getBoundingClientRect().left;
          this.op.aoSelecionar(id, limitar(x / this.zoom, 0, this.total));
        }
      };
      raiz.addEventListener('pointermove', mover);
      raiz.addEventListener('pointerup', soltar, { once: true });
      raiz.addEventListener('pointercancel', soltar, { once: true });
    });
  }

  // O marcador fica entre os clipes como eles estão na tela agora (o arrastado ainda ocupa o lugar dele).
  _posicaoReal(antes, id) {
    const ultimo = antes[antes.length - 1];
    if (!ultimo) {
      const primeiro = this.sequencia.find((s) => s.item.id !== id);
      return primeiro ? primeiro.inicio * this.zoom : 0;
    }
    return (ultimo.inicio + ultimo.duracao) * this.zoom;
  }

  _desenharRegua() {
    const canvas = this.regua;
    const largura = this.rolagem.clientWidth || 800;
    const altura = 26;
    const densidade = Math.min(window.devicePixelRatio || 1, 2);
    // A régua só desenha a parte visível e acompanha a rolagem.
    canvas.style.width = `${largura}px`;
    canvas.style.transform = `translateX(${this.rolagem.scrollLeft}px)`;
    canvas.width = Math.round(largura * densidade);
    canvas.height = Math.round(altura * densidade);
    const ctx = canvas.getContext('2d');
    ctx.scale(densidade, densidade);
    ctx.clearRect(0, 0, largura, altura);
    const passo = PASSOS_REGUA.find((p) => p * this.zoom >= 64) || 600;
    const menor = passo / 5;
    const inicio = this.rolagem.scrollLeft / this.zoom;
    const fim = inicio + largura / this.zoom;
    ctx.strokeStyle = '#3a4152';
    ctx.fillStyle = '#8b93a7';
    ctx.font = '11px system-ui, sans-serif';
    ctx.textBaseline = 'top';
    ctx.beginPath();
    for (let t = Math.floor(inicio / menor) * menor; t <= fim; t += menor) {
      const x = Math.round(t * this.zoom - this.rolagem.scrollLeft) + 0.5;
      const principal = Math.abs(t / passo - Math.round(t / passo)) < 1e-6;
      ctx.moveTo(x, principal ? 12 : 19);
      ctx.lineTo(x, altura);
      if (principal) ctx.fillText(relogio(t, passo < 1 ? 1 : 0), x + 4, 3);
    }
    ctx.stroke();
    // Fim do vídeo.
    const xFim = this.total * this.zoom - this.rolagem.scrollLeft;
    if (this.total && xFim >= 0 && xFim <= largura) {
      ctx.fillStyle = '#8b5cf6';
      ctx.fillRect(xFim - 1, 0, 2, altura);
    }
  }
}
