// Prévia da linha do tempo como se ela já fosse um vídeo só. Dois <video> se revezam: enquanto um toca, o outro
// espera parado no começo do próximo trecho, para a troca ser imediata. O quadro é desenhado num canvas já no
// formato final (9:16, 4:5...), cortando as sobras ou com fundo desfocado, como na exportação.

import { limitar } from './util.js';

export class Previa {
  // aoDesenhar(ctx, tempo, largura, altura): desenha por cima de cada quadro (as legendas).
  constructor({ area, quadro, canvas, aoMudarTempo, aoTocarOuPausar, aoErro, aoDesenhar }) {
    this.area = area;
    this.quadro = quadro;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.aoMudarTempo = aoMudarTempo;
    this.aoTocarOuPausar = aoTocarOuPausar;
    this.aoErro = aoErro;
    this.aoDesenhar = aoDesenhar;
    this.sequencia = [];
    this.total = 0;
    this.indice = -1;
    this.tempo = 0;
    this.tocando = false;
    this.formato = { largura: 1080, altura: 1920 };
    this.enquadramento = 'preencher';
    this._quadro = this._quadro.bind(this);

    // Os vídeos ficam fora da vista: o que aparece é o canvas.
    const escondidos = document.createElement('div');
    escondidos.className = 'videos-ocultos';
    document.body.append(escondidos);
    this.videos = [this._criarVideo(), this._criarVideo()];
    escondidos.append(...this.videos);
    this.ativo = 0;

    new ResizeObserver(() => this._ajustarTamanho()).observe(area);
  }

  _criarVideo() {
    const video = document.createElement('video');
    video.preload = 'auto';
    video.playsInline = true;
    video.addEventListener('seeked', () => { if (!this.tocando) this.desenhar(); });
    video.addEventListener('loadeddata', () => { if (!this.tocando) this.desenhar(); });
    video.addEventListener('error', () => this.aoErro?.(video.dataset.midia));
    return video;
  }

  get videoAtivo() {
    return this.videos[this.ativo];
  }

  definirFormato(largura, altura, enquadramento) {
    if (largura === this.formato.largura && altura === this.formato.altura && enquadramento === this.enquadramento) return;
    this.formato = { largura, altura };
    this.enquadramento = enquadramento;
    this._ajustarTamanho();
  }

  // A tela chama isto a cada atualização; só reposiciona os vídeos se a montagem mudou de verdade.
  definirSequencia(sequencia) {
    const assinatura = sequencia.map((s) => `${s.item.id}:${s.url}:${s.item.entrada}:${s.item.saida}`).join('|');
    if (assinatura === this._assinatura) return;
    this._assinatura = assinatura;
    this.pausar();
    this.sequencia = sequencia;
    const ultimo = sequencia[sequencia.length - 1];
    this.total = ultimo ? ultimo.inicio + ultimo.duracao : 0;
    this.buscar(limitar(this.tempo, 0, this.total), true);
  }

  definirMudo(mudo) {
    this.videos.forEach((v) => { v.muted = mudo; });
  }

  _indiceEm(tempo) {
    if (!this.sequencia.length) return -1;
    for (let i = 0; i < this.sequencia.length; i++) {
      const s = this.sequencia[i];
      if (tempo < s.inicio + s.duracao) return i;
    }
    return this.sequencia.length - 1;
  }

  // Põe o vídeo no arquivo e no instante pedidos (espera os metadados se o arquivo acabou de ser trocado).
  _posicionar(video, segmento, instante) {
    video._alvo = instante;
    if (video.dataset.url !== segmento.url) {
      video.dataset.url = segmento.url;
      video.dataset.midia = segmento.midia.id;
      video.src = segmento.url;
    }
    if (video.readyState >= 1) {
      if (Math.abs(video.currentTime - instante) > 0.004) video.currentTime = instante;
    } else if (!video._esperando) {
      video._esperando = true;
      video.addEventListener('loadedmetadata', () => {
        video._esperando = false;
        video.currentTime = video._alvo;
      }, { once: true });
    }
  }

  _prepararProximo() {
    const proximo = this.sequencia[this.indice + 1];
    const outro = this.videos[1 - this.ativo];
    outro.pause();
    if (proximo) this._posicionar(outro, proximo, proximo.item.entrada);
  }

  buscar(tempo, forcar = false) {
    tempo = limitar(tempo, 0, this.total);
    this.tempo = tempo;
    const indice = this._indiceEm(tempo);
    if (indice < 0) {
      this.indice = -1;
      this.desenhar();
      this.aoMudarTempo?.(tempo);
      return;
    }
    const segmento = this.sequencia[indice];
    const instante = segmento.item.entrada + Math.min(tempo - segmento.inicio, segmento.duracao - 0.001);
    if (forcar || indice !== this.indice) {
      this.indice = indice;
      this._posicionar(this.videoAtivo, segmento, instante);
      this._prepararProximo();
    } else {
      this._posicionar(this.videoAtivo, segmento, instante);
    }
    if (this.tocando) this.videoAtivo.play().catch(() => {});
    this.aoMudarTempo?.(tempo);
  }

  tocar() {
    if (!this.sequencia.length || this.tocando) return;
    if (this.tempo >= this.total - 0.02) this.buscar(0);
    this.tocando = true;
    this.videoAtivo.play().catch(() => { /* o navegador às vezes recusa antes do primeiro clique */ });
    this.aoTocarOuPausar?.(true);
    requestAnimationFrame(this._quadro);
  }

  pausar() {
    if (!this.tocando) return;
    this.tocando = false;
    this.videos.forEach((v) => v.pause());
    this.aoTocarOuPausar?.(false);
    this.desenhar();
  }

  alternar() {
    if (this.tocando) this.pausar();
    else this.tocar();
  }

  _avancar() {
    const anterior = this.videoAtivo;
    this.ativo = 1 - this.ativo;
    this.indice += 1;
    const segmento = this.sequencia[this.indice];
    const video = this.videoAtivo;
    if (video.dataset.url !== segmento.url || Math.abs(video.currentTime - segmento.item.entrada) > 0.05) {
      this._posicionar(video, segmento, segmento.item.entrada);
    }
    video.play().catch(() => {});
    anterior.pause();
    this.tempo = segmento.inicio;
    this._prepararProximo();
  }

  _quadro() {
    if (!this.tocando) return;
    const segmento = this.sequencia[this.indice];
    if (!segmento) {
      this.pausar();
      return;
    }
    const video = this.videoAtivo;
    if (video.currentTime >= segmento.item.saida - 0.015 || video.ended) {
      if (this.indice + 1 < this.sequencia.length) {
        this._avancar();
      } else {
        this.tempo = this.total;
        this.pausar();
        this.aoMudarTempo?.(this.tempo);
        return;
      }
    } else {
      this.tempo = segmento.inicio + Math.max(0, video.currentTime - segmento.item.entrada);
    }
    this.desenhar();
    this.aoMudarTempo?.(this.tempo);
    requestAnimationFrame(this._quadro);
  }

  desenhar() {
    this._desenharVideo();
    this.aoDesenhar?.(this.ctx, this.tempo, this.canvas.width, this.canvas.height);
  }

  _desenharVideo() {
    const { ctx, canvas } = this;
    const L = canvas.width;
    const A = canvas.height;
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, L, A);
    const video = this.videoAtivo;
    if (this.indice < 0 || video.readyState < 2 || !video.videoWidth) return;
    const vl = video.videoWidth;
    const va = video.videoHeight;
    const desenhar = (escala) => {
      const w = vl * escala;
      const h = va * escala;
      ctx.drawImage(video, (L - w) / 2, (A - h) / 2, w, h);
    };
    if (this.enquadramento === 'desfocado' && Math.abs(vl / va - L / A) > 0.01) {
      // Mesmo desfoque da exportação, proporcional ao tamanho da prévia.
      ctx.save();
      ctx.filter = `blur(${Math.round(32 * (L / this.formato.largura))}px) brightness(0.88)`;
      desenhar(Math.max(L / vl, A / va) * 1.08);
      ctx.restore();
      desenhar(Math.min(L / vl, A / va));
    } else {
      desenhar(Math.max(L / vl, A / va));
    }
  }

  _ajustarTamanho() {
    const area = this.area.getBoundingClientRect();
    if (!area.width || !area.height) return;
    const proporcao = this.formato.largura / this.formato.altura;
    let w = area.width;
    let h = w / proporcao;
    if (h > area.height) {
      h = area.height;
      w = h * proporcao;
    }
    this.quadro.style.width = `${Math.floor(w)}px`;
    this.quadro.style.height = `${Math.floor(h)}px`;
    const densidade = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.round(w * densidade);
    this.canvas.height = Math.round(h * densidade);
    this.desenhar();
  }
}
