/*!
 * VSL Player 1.1.0
 * Player de vídeo para páginas de vendas (VSL), no estilo VTurb:
 *  - smart autoplay: começa mudo e pede o clique para ouvir (e recomeça com som);
 *  - barra de progresso inteligente, que anda rápido no começo e devagar no fim;
 *  - delay de elementos da página (botão de compra aparece no minuto certo);
 *  - "continuar de onde parou" entre visitas;
 *  - sem controles de avanço: clique pausa/retoma, velocidade e seek travados;
 *  - miniatura de pausa e tela final com botão de compra (CTA);
 *  - retentativa automática quando o vídeo falha, com botão "Tentar de novo";
 *  - eventos para pixels (Meta, GA4...) e envio de retenção para um endpoint seu.
 * Sem dependências (o hls.js é carregado sozinho quando o vídeo é .m3u8). Licença MIT.
 */
(function (global, document) {
  'use strict';

  if (!global || !document) return;

  const VERSION = '1.1.0';
  const STORAGE_PREFIX = 'vsl:';
  const MILESTONES = [10, 25, 50, 75, 90];
  const FLUSH_NOW = ['unmute', 'ended', 'pitch', 'cta_click', 'error']; // eventos que saem na hora para o analytics
  const RETRY_DELAYS = [1000, 3000, 8000]; // esperas entre as retentativas automáticas quando o vídeo falha
  const HLS_TIMEOUT = 8000;                // quanto esperar o hls.js baixar antes de usar o fallback
  const FIRST_FRAME_TIMEOUT = 12000;       // play() aceito mas sem imagem: volta para a capa depois disso
  const FIRST_FRAME_TIME = 0.05;           // currentTime a partir do qual consideramos que há imagem na tela
  const TAP_GUARD = 450;                   // ms ignorando toques depois do toque que liberou o som
  const SOUND_LONG_AFTER = 5 * 60 * 1000;  // depois de 5 min com som, o analytics passa a enviar a cada 60 s
  const TARGET_HEIGHT = 480;               // nível inicial do HLS: o mais perto desta altura
  const POSITIONS = ['top-left', 'top-center', 'top-right', 'center-left', 'center', 'center-right', 'bottom-left', 'bottom-center', 'bottom-right'];
  const EVENTS = [
    'ready', 'autoplay', 'autoplay_blocked', 'unmute', 'play', 'pause', 'ended', 'replay',
    'progress', 'milestone', 'pitch', 'reach', 'resume_prompt', 'resume_continue', 'resume_restart',
    'seek_blocked', 'fullscreen', 'review', 'state', 'error', 'cta_click',
  ];

  const DEFAULTS = {
    id: '',                   // identificador do player (chave do localStorage e dos eventos)
    src: '',                  // MP4 ou .m3u8 (HLS)
    fallback: '',             // MP4 usado quando o navegador não toca HLS
    hlsUrl: 'https://cdn.jsdelivr.net/npm/hls.js@1.5.20/dist/hls.light.min.js', // de onde baixar o hls.js, se precisar
    poster: '',               // imagem de capa
    aspect: 'auto',           // 16:9, 9:16, 4:3, 1:1... ou auto (usa a proporção do vídeo)
    color: '#e11d48',         // cor da barra de progresso e dos botões
    preload: 'auto',          // auto | metadata | none
    autoplay: true,           // smart autoplay: começa mudo e pede o clique para ouvir
    unmuteRestart: true,      // ao clicar para ouvir, volta para o início
    resume: true,             // oferece "continuar de onde parou"
    resumeMin: 10,            // só oferece retomar se o visitante passou de X segundos
    progress: 'smart',        // smart | real | none
    progressIntensity: 2.2,   // quanto maior, mais rápido a barra anda no começo
    pauseOverlay: true,       // mostra "continuar assistindo" quando pausado
    endScreen: 'replay',      // replay | poster | none
    lockSpeed: true,          // impede acelerar o vídeo (extensões, console)
    lockSeek: true,           // impede pular trechos (extensões, console)
    speed: 1,                 // velocidade de reprodução (1 a 1.5); a trava mantém esta velocidade
    fullscreen: false,        // mostra o botão de tela cheia
    pitch: '',                // segundos (ou mm:ss) em que a oferta começa; dispara "pitch" uma vez
    show: '',                 // seletores CSS ("#botao, .oferta") de elementos que aparecem em showAt
    showAt: '',               // tempo em que os elementos de `show` aparecem; vazio = no pitch
    pausePosterLate: '',      // imagem mostrada ao pausar depois do pitch (miniatura de pausa)
    pauseCtaText: '',         // texto do botão sobre a miniatura de pausa
    pauseCtaLink: '',         // link do botão (sem link, não há botão)
    pauseCtaPos: 'bottom-center', // posição do botão: top-left ... bottom-right
    endPoster: '',            // imagem da tela final (no lugar do "assistir de novo")
    endCtaText: '',           // texto do botão da tela final
    endCtaLink: '',           // link do botão da tela final
    endCtaPos: 'bottom-center',
    analytics: '',            // URL que recebe os eventos e a retenção (POST, JSON)
    analyticsInterval: 15,    // segundos entre os envios (com som)
    reviewKey: '',            // chave do modo de revisão: abra a página com ?revisar=CHAVE para acelerar e pular
    texts: {
      unmuteTitle: 'Seu vídeo já começou',
      unmuteSubtitle: 'Clique para ouvir',
      play: 'Clique para assistir',
      pause: 'Continuar assistindo',
      replay: 'Assistir de novo',
      resumeTitle: 'Continuar de onde parou?',
      resumeSubtitle: 'Você parou em {time}',
      resumeContinue: 'Continuar',
      resumeRestart: 'Ver do início',
      error: 'O vídeo não carregou',
      retry: 'Tentar de novo',
      fullscreen: 'Tela cheia',
      review: 'Modo de revisão',
      reviewGo: 'Ir',
    },
  };

  // Em telas de toque (sem mouse), "clique" vira "toque". Os data-* do HTML continuam valendo.
  const TOUCH_TEXTS = { unmuteSubtitle: 'Toque para ouvir', play: 'Toque para assistir', pause: 'Toque para continuar' };

  // data-atributo de cada texto: data-unmute-title="..."
  const TEXT_ATTRS = {
    unmuteTitle: 'unmute-title', unmuteSubtitle: 'unmute-subtitle', play: 'play-text',
    pause: 'pause-text', replay: 'replay-text', resumeTitle: 'resume-title',
    resumeSubtitle: 'resume-subtitle', resumeContinue: 'resume-continue',
    resumeRestart: 'resume-restart', error: 'error-text', retry: 'retry-text', fullscreen: 'fullscreen-label',
    review: 'review-text', reviewGo: 'review-go',
  };

  const ICONS = {
    muted: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4z"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>',
    replay: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>',
    fullscreen: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>',
    warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  };

  // ---------------------------------------------------------------- utilitários

  const storage = {
    get(key) { try { return global.localStorage.getItem(STORAGE_PREFIX + key); } catch (e) { return null; } },
    set(key, value) { try { global.localStorage.setItem(STORAGE_PREFIX + key, String(value)); } catch (e) { /* modo privado */ } },
    remove(key) { try { global.localStorage.removeItem(STORAGE_PREFIX + key); } catch (e) { /* ignora */ } },
  };

  function esc(text) {
    return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function kebab(name) { return name.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()); }

  function clamp(n, min, max) { return Math.min(max, Math.max(min, n)); }

  function round(n, places) {
    const f = Math.pow(10, places == null ? 1 : places);
    return Math.round((Number(n) || 0) * f) / f;
  }

  // Aceita "90", "1:30", "00:01:30" ou "1m30s". Retorna segundos (ou null).
  function parseTime(value) {
    if (value == null || value === '') return null;
    if (typeof value === 'number') return isFinite(value) ? value : null;
    const text = String(value).trim();
    if (/^\d+(\.\d+)?$/.test(text)) return parseFloat(text);
    if (/^(\d+:)?\d{1,2}:\d{1,2}(\.\d+)?$/.test(text)) {
      return text.split(':').reduce((total, part) => total * 60 + parseFloat(part), 0);
    }
    const m = text.match(/^(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?$/);
    if (m && (m[1] || m[2] || m[3])) return (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0);
    return null;
  }

  // 65 -> "1:05"; 3725 -> "1:02:05". Usado no "Você parou em {time}".
  function formatTime(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const pad = (n) => (n < 10 ? '0' : '') + n;
    return h > 0 ? h + ':' + pad(m) + ':' + pad(s) : m + ':' + pad(s);
  }

  function hash(text) {
    let h = 5381;
    for (let i = 0; i < text.length; i++) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  function uuid() {
    try { if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID(); } catch (e) { /* segue */ }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  // Converte um conjunto de segundos assistidos em faixas: {3,4,5,9} -> [[3,5],[9,9]]
  function toRanges(set) {
    const seconds = Array.from(set).sort((a, b) => a - b);
    const ranges = [];
    seconds.forEach((s) => {
      const last = ranges[ranges.length - 1];
      if (last && s === last[1] + 1) last[1] = s;
      else ranges.push([s, s]);
    });
    return ranges;
  }

  // Mantém só valores simples (nada de elementos ou do próprio player) para enviar/serializar.
  function plain(detail) {
    const out = {};
    Object.keys(detail || {}).forEach((key) => {
      const value = detail[key];
      if (['string', 'number', 'boolean'].indexOf(typeof value) >= 0) out[key] = value;
    });
    return out;
  }

  function cssAspect(aspect) {
    const text = String(aspect || '').trim().replace(/\s+/g, '');
    if (!text || text === 'auto') return '16 / 9';
    const m = text.match(/^(\d+(?:\.\d+)?)[:/](\d+(?:\.\d+)?)$/);
    if (m) return m[1] + ' / ' + m[2];
    if (/^\d+(\.\d+)?$/.test(text)) return text;
    return '16 / 9';
  }

  function cssUrl(url) { return 'url("' + String(url).replace(/"/g, '%22') + '")'; }

  function isTouch() {
    try { return !!(global.matchMedia && global.matchMedia('(hover: none) and (pointer: coarse)').matches); } catch (e) { return false; }
  }

  function readOptions(el) {
    const out = { texts: {} };
    Object.keys(DEFAULTS).forEach((key) => {
      if (key === 'texts') return;
      const attr = 'data-' + kebab(key);
      if (!el.hasAttribute(attr)) return;
      const raw = el.getAttribute(attr);
      const kind = typeof DEFAULTS[key];
      if (kind === 'boolean') out[key] = !(raw === 'false' || raw === '0' || raw === 'off' || raw === 'no');
      else if (kind === 'number') out[key] = parseFloat(raw);
      else out[key] = raw;
    });
    Object.keys(TEXT_ATTRS).forEach((key) => {
      const attr = 'data-' + TEXT_ATTRS[key];
      if (el.hasAttribute(attr)) out.texts[key] = el.getAttribute(attr);
    });
    return out;
  }

  function mergeOptions(el, options) {
    const data = readOptions(el);
    const merged = Object.assign({}, DEFAULTS, data, options || {});
    merged.texts = Object.assign({}, DEFAULTS.texts, isTouch() ? TOUCH_TEXTS : {}, data.texts, (options && options.texts) || {});
    if (!(merged.progressIntensity > 0)) merged.progressIntensity = DEFAULTS.progressIntensity;
    if (!(merged.resumeMin >= 0)) merged.resumeMin = DEFAULTS.resumeMin;
    const speed = Number(merged.speed);
    merged.speed = clamp(speed > 0 ? speed : 1, 1, 1.5);
    if (POSITIONS.indexOf(merged.pauseCtaPos) < 0) merged.pauseCtaPos = DEFAULTS.pauseCtaPos;
    if (POSITIONS.indexOf(merged.endCtaPos) < 0) merged.endCtaPos = DEFAULTS.endCtaPos;
    return merged;
  }

  // Baixa o hls.js uma vez só, compartilhado entre os players da página. Resolve com window.Hls.
  function loadHls(url) {
    if (global.Hls) return Promise.resolve(global.Hls);
    if (VSLPlayer._hlsLoading) return VSLPlayer._hlsLoading;
    VSLPlayer._hlsLoading = new Promise((resolve, reject) => {
      let done = false;
      let timer = null;
      const finish = (ok) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        if (ok && global.Hls) { resolve(global.Hls); return; }
        VSLPlayer._hlsLoading = null; // a próxima tentativa injeta de novo
        reject(new Error('hls-load'));
      };
      timer = setTimeout(() => finish(false), HLS_TIMEOUT);
      const script = document.createElement('script');
      script.src = url;
      script.async = true;
      script.setAttribute('data-vsl-hls', '1');
      script.onload = () => finish(true);
      script.onerror = () => finish(false);
      (document.head || document.documentElement).appendChild(script);
    });
    return VSLPlayer._hlsLoading;
  }

  // ------------------------------------------------------------------ analytics

  class Tracker {
    constructor(player) {
      this.player = player;
      this.url = player.opts.analytics;
      this.queue = [];
      this.watched = new Set();
      this.dirty = false;
      this.maxTime = 0; // até onde ESTA sessão chegou com som (o `reached` do player atravessa visitas)
      this.seq = 0;     // distingue eventos emitidos no mesmo milissegundo
      this.timer = null;
      this.firstSent = false; // a sessão muda envia um único pacote (no ready/autoplay ou em até 3 s)
      this.soundSince = 0;    // quando o som foi liberado: depois de 5 min o intervalo passa para 60 s
      if (!this.url) return;
      this.visitor = storage.get('visitor');
      if (!this.visitor) { this.visitor = uuid(); storage.set('visitor', this.visitor); }
      this.session = uuid();
      this.interval = Math.max(5, Number(player.opts.analyticsInterval) || DEFAULTS.analyticsInterval);
      this.onHide = () => this.flush();
      this.onVisibility = () => { if (document.visibilityState === 'hidden') this.flush(); };
      global.addEventListener('pagehide', this.onHide);
      document.addEventListener('visibilitychange', this.onVisibility);
      this._schedule();
    }

    // Sessão muda: um envio só; o resto fica para o unmute ou o pagehide. Com som: a cada `interval` s (60 s depois de 5 min).
    _schedule() {
      clearTimeout(this.timer);
      this.timer = null;
      if (!this.player.unmuted) {
        if (!this.firstSent) this.timer = setTimeout(() => this._sendFirst(), 3000);
        return;
      }
      const longo = this.soundSince && Date.now() - this.soundSince >= SOUND_LONG_AFTER;
      this.timer = setTimeout(() => { this.flush(); this._schedule(); }, (longo ? 60 : this.interval) * 1000);
    }

    _sendFirst() {
      if (this.firstSent) return;
      clearTimeout(this.timer);
      this.timer = null;
      if (this.flush()) this.firstSent = true; // sem nada na fila ainda, o próximo ready/autoplay envia
    }

    second(time) {
      if (!this.url) return;
      if (time > this.maxTime) this.maxTime = time;
      const s = Math.floor(time);
      if (!this.watched.has(s)) { this.watched.add(s); this.dirty = true; }
    }

    track(type, detail) {
      if (!this.url) return;
      this.queue.push(Object.assign({ type, ts: Date.now(), time: round(this.player.currentTime), seq: this.seq++ }, plain(detail)));
      if (type === 'unmute' && !this.soundSince) { this.soundSince = Date.now(); this._schedule(); }
      if (FLUSH_NOW.indexOf(type) >= 0) this.flush();
      else if ((type === 'ready' || type === 'autoplay') && !this.player.unmuted) this._sendFirst();
    }

    flush() {
      if (!this.url || (!this.queue.length && !this.dirty)) return false;
      const payload = {
        v: VERSION,
        player: this.player.id,
        visitor: this.visitor,
        session: this.session,
        url: global.location.href,
        referrer: document.referrer,
        duration: round(this.player.duration),
        maxTime: round(this.maxTime),            // nesta sessão, com som
        reached: round(this.player.reached),     // entre visitas (inclui autoplay mudo)
        unmuted: this.player.unmuted,
        muted: !this.player.unmuted,             // a sessão ainda está muda (nunca liberou o som)
        pitch: this.player._pitchAt == null ? null : this.player._pitchAt,
        watched: toRanges(this.watched), // segundos assistidos com som, acumulados na sessão (o servidor une)
        events: this.queue,
        sentAt: Date.now(),
      };
      this.queue = [];
      this.dirty = false;
      const body = JSON.stringify(payload);
      let sent = false;
      try {
        // text/plain evita o preflight de CORS; o corpo é JSON mesmo assim.
        if (global.navigator && global.navigator.sendBeacon) {
          sent = global.navigator.sendBeacon(this.url, new Blob([body], { type: 'text/plain;charset=UTF-8' }));
        }
      } catch (e) { sent = false; }
      if (!sent && global.fetch) {
        try {
          global.fetch(this.url, {
            method: 'POST', body, keepalive: true, headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
          }).catch(() => {});
        } catch (e) { /* sem rede */ }
      }
      return true;
    }

    destroy() {
      if (!this.url) return;
      this.flush();
      clearTimeout(this.timer);
      global.removeEventListener('pagehide', this.onHide);
      document.removeEventListener('visibilitychange', this.onVisibility);
    }
  }

  // --------------------------------------------------------------------- player

  class VSLPlayer {
    constructor(el, options) {
      if (typeof el === 'string') el = document.querySelector(el);
      if (!el) throw new Error('VSLPlayer: elemento não encontrado.');
      if (el.vslPlayer) return el.vslPlayer;

      this.root = el;
      this.opts = mergeOptions(el, options);
      if (!this.opts.src) throw new Error('VSLPlayer: informe o vídeo em data-src (MP4 ou .m3u8).');
      this.id = String(this.opts.id || el.id || 'v' + hash(this.opts.src));

      el.vslPlayer = this;
      this.state = 'loading';
      this.unmuted = false;                                     // já tocou com som nesta visita
      this.duration = 0;
      this.reached = parseFloat(storage.get(this.id + ':reached')) || 0; // maior tempo já atingido, entre visitas
      this._handlers = {};
      this._milestones = new Set();
      this._pitchAt = parseTime(this.opts.pitch);
      this._pitchDone = storage.get(this.id + ':pitch') === '1';
      this._resumeAsked = false;
      this._readyEmitted = false;
      this._lastTime = 0;
      this._lastSaved = -1;
      this._seekAllowed = false;
      this._pendingSeek = null;
      this._seekTarget = null;     // alvo do último _seek() ainda não confirmado pelo `seeked`
      this._seekRetry = null;      // alvo que o navegador recusou (stream sem Range): a posição fica nele e o seek é refeito quando der
      this._seekRetried = 0;       // quantas vezes o seek recusado já foi refeito (limite para não insistir)
      this._listeners = [];
      this._isFirst = VSLPlayer.instances.length === 0;
      this._attempts = 0;          // retentativas automáticas já feitas desde a última falha
      this._retryTimer = null;     // espera até a próxima retentativa
      this._frameTimer = null;     // watchdog: play() aceito mas sem imagem
      this._tapGuardUntil = 0;     // ignora o segundo toque do impaciente
      this._errorCode = null;
      this._hlsErrorType = null;
      this._stateBeforeError = null; // 'paused' | 'modal' quando o erro pegou o visitante parado: a retentativa não retoma sozinha
      this._sourceAttached = false;

      VSLPlayer.instances.push(this);
      VSLPlayer.byId[this.id] = this;

      this.tracker = new Tracker(this); // antes de tudo: os elementos já alcançados emitem eventos na montagem
      this._build();
      this._bindVideo();
      this._bindUI();
      this._bindElements();
      this._attachSource(() => this._boot());
      if (this._modoRevisaoPedido()) this._ativarRevisao();
    }

    // -- modo de revisão (só para quem tem a chave) --------------------------

    _modoRevisaoPedido() {
      const chave = String(this.opts.reviewKey || '');
      if (!chave) return false;
      let pedido = '';
      try { pedido = new URLSearchParams(global.location.search).get('revisar') || ''; } catch (e) { pedido = ''; }
      if (!pedido) { try { pedido = global.sessionStorage.getItem('vsl:revisar') || ''; } catch (e) { pedido = ''; } }
      if (pedido !== chave) return false;
      try { global.sessionStorage.setItem('vsl:revisar', chave); } catch (e) { /* ignora */ }
      return true;
    }

    _ativarRevisao() {
      if (this.review) return;
      this.opts.lockSpeed = false;
      this.opts.lockSeek = false;
      const t = this.opts.texts;
      const barra = document.createElement('div');
      barra.className = 'vsl-review';
      barra.innerHTML =
        '<span class="vsl-review-titulo">' + esc(t.review) + '</span>' +
        [1, 1.5, 2, 3].map((v) => '<button type="button" data-vsl-speed="' + v + '"' + (v === 1 ? ' class="vsl-on"' : '') + '>' + v + 'x</button>').join('') +
        '<input type="text" data-vsl-goto placeholder="mm:ss" size="6" aria-label="Ir para">' +
        '<button type="button" data-vsl-go>' + esc(t.reviewGo) + '</button>';
      this.root.appendChild(barra);
      this.review = barra;
      const parar = (e) => e.stopPropagation();
      ['click', 'pointerdown', 'keydown'].forEach((tipo) => barra.addEventListener(tipo, parar));
      barra.querySelectorAll('[data-vsl-speed]').forEach((btn) => {
        btn.addEventListener('click', () => {
          this.video.playbackRate = parseFloat(btn.getAttribute('data-vsl-speed'));
          barra.querySelectorAll('[data-vsl-speed]').forEach((b) => b.classList.toggle('vsl-on', b === btn));
        });
      });
      const campo = barra.querySelector('[data-vsl-goto]');
      const ir = () => {
        const alvo = parseTime(campo.value);
        if (alvo == null) return;
        if (!this.unmuted) this._playWithSound(alvo); else { this._seek(alvo); this._play(); }
      };
      barra.querySelector('[data-vsl-go]').addEventListener('click', ir);
      campo.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); ir(); } });
      this.emit('review', {});
    }

    // -- montagem ------------------------------------------------------------

    _cta(text, link, pos) {
      return '<a class="vsl-cta" data-vsl-pos="' + esc(pos) + '" href="' + esc(link) + '" target="_top">' + esc(text || 'Saiba mais') + '</a>';
    }

    _build() {
      const root = this.root;
      const o = this.opts;
      const t = o.texts;
      root.classList.add('vsl-player');
      root.setAttribute('data-vsl-ready', '1');
      root.setAttribute('data-vsl-id', this.id);
      root.setAttribute('data-state', this.state);
      root.setAttribute('data-progress', o.progress);
      root.setAttribute('data-end-screen', o.endPoster ? 'poster-cta' : o.endScreen);
      root.setAttribute('data-pause-overlay', o.pauseOverlay ? 'true' : 'false');
      root.setAttribute('data-fullscreen', o.fullscreen ? 'true' : 'false');
      root.setAttribute('tabindex', '0');
      root.setAttribute('role', 'region');
      root.setAttribute('aria-label', 'Vídeo');
      root.style.setProperty('--vsl-color', o.color);
      root.style.setProperty('--vsl-aspect', cssAspect(o.aspect));

      const replayBox = '<div class="vsl-box"><span class="vsl-icon">' + ICONS.replay + '</span><strong>' + esc(t.replay) + '</strong></div>';
      root.innerHTML =
        '<video class="vsl-video" playsinline webkit-playsinline preload="' + esc(o.preload) + '" ' +
        'disablepictureinpicture disableremoteplayback controlslist="nodownload noplaybackrate noremoteplayback"></video>' +
        '<div class="vsl-layer vsl-poster"></div>' +
        '<div class="vsl-layer vsl-unmute"><button type="button" class="vsl-box" aria-label="' + esc(t.unmuteTitle + '. ' + t.unmuteSubtitle) + '">' +
        '<span class="vsl-icon vsl-icon--pulse">' + ICONS.muted + '</span>' +
        '<strong>' + esc(t.unmuteTitle) + '</strong><span class="vsl-sub">' + esc(t.unmuteSubtitle) + '</span></button></div>' +
        '<div class="vsl-layer vsl-idle"><div class="vsl-play-btn">' + ICONS.play + '</div>' +
        '<span class="vsl-caption">' + esc(t.play) + '</span></div>' +
        '<div class="vsl-layer vsl-paused"><div class="vsl-box"><span class="vsl-icon">' + ICONS.play + '</span>' +
        '<strong>' + esc(t.pause) + '</strong></div></div>' +
        '<div class="vsl-layer vsl-pause-poster">' + (o.pauseCtaLink ? this._cta(o.pauseCtaText, o.pauseCtaLink, o.pauseCtaPos) : '') + '</div>' +
        '<div class="vsl-layer vsl-ended">' + (o.endPoster && o.endCtaLink ? this._cta(o.endCtaText, o.endCtaLink, o.endCtaPos) : replayBox) + '</div>' +
        '<div class="vsl-layer vsl-error"><div class="vsl-box"><span class="vsl-icon">' + ICONS.warning + '</span>' +
        '<strong>' + esc(t.error) + '</strong>' +
        '<button type="button" class="vsl-btn vsl-btn--primary" data-vsl-action="retry">' + esc(t.retry) + '</button></div></div>' +
        '<div class="vsl-layer vsl-loading"><div class="vsl-spinner"></div></div>' +
        '<div class="vsl-layer vsl-modal"><div class="vsl-card" role="dialog" aria-modal="true">' +
        '<strong>' + esc(t.resumeTitle) + '</strong><p>' + esc(t.resumeSubtitle) + '</p>' +
        '<div class="vsl-card-actions">' +
        '<button type="button" class="vsl-btn vsl-btn--primary" data-vsl-action="continue">' + esc(t.resumeContinue) + '</button>' +
        '<button type="button" class="vsl-btn vsl-btn--ghost" data-vsl-action="restart">' + esc(t.resumeRestart) + '</button>' +
        '</div></div></div>' +
        '<div class="vsl-progress" aria-hidden="true"><div class="vsl-progress-bar"></div></div>' +
        '<button type="button" class="vsl-fullscreen" aria-label="' + esc(t.fullscreen) + '">' + ICONS.fullscreen + '</button>';

      this.video = root.querySelector('.vsl-video');
      this.bar = root.querySelector('.vsl-progress-bar');
      this.posterLayer = root.querySelector('.vsl-poster');
      this.modalText = root.querySelector('.vsl-card p');
      if (o.poster) {
        this.video.setAttribute('poster', o.poster);
        this.posterLayer.style.backgroundImage = cssUrl(o.poster);
      }
      if (o.pausePosterLate) root.querySelector('.vsl-pause-poster').style.backgroundImage = cssUrl(o.pausePosterLate);
      if (o.endPoster) root.querySelector('.vsl-ended').style.backgroundImage = cssUrl(o.endPoster);
      // Velocidade manual: defaultPlaybackRate sobrevive ao load() das retentativas.
      this.video.defaultPlaybackRate = o.speed;
      this.video.playbackRate = o.speed;
    }

    _preconectar(src) {
      let origem = '';
      try { origem = new URL(src, global.location.href).origin; } catch (e) { return; }
      if (!origem || origem === global.location.origin || VSLPlayer._preconectados[origem]) return;
      VSLPlayer._preconectados[origem] = true;
      const link = document.createElement('link');
      link.rel = 'preconnect';
      link.href = origem;
      link.crossOrigin = 'anonymous';
      (document.head || document.documentElement).appendChild(link);
    }

    // Liga o vídeo à fonte e chama `done` quando houver fonte (pode ser depois, se o hls.js precisar baixar).
    _attachSource(done) {
      const v = this.video;
      const src = this.opts.src;
      this._preconectar(src);
      const isHls = /\.m3u8(\?|#|$)/i.test(src);
      if (!isHls || v.canPlayType('application/vnd.apple.mpegurl')) { v.src = src; this._sourceAttached = true; done(); return; }
      const fallback = (code) => {
        if (this.opts.fallback) { v.src = this.opts.fallback; this._sourceAttached = true; done(); return; }
        this._onError(code);
      };
      const attach = (Hls) => {
        if (!Hls || !Hls.isSupported()) { fallback('hls-unsupported'); return; }
        // startLevel 0: o vídeo começa na hora, na qualidade mais leve; no manifesto escolhemos o nível perto de 480p.
        this.hls = new Hls(Object.assign({ startLevel: 0, capLevelToPlayerSize: true, maxBufferLength: 60 }, this.opts.hlsConfig || {}));
        this.hls.on(Hls.Events.MANIFEST_PARSED, (_, data) => {
          if (!this.hls) return;
          this.hls.startLevel = this._nivelInicial((data && data.levels) || this.hls.levels);
        });
        this.hls.on(Hls.Events.ERROR, (_, data) => { if (data && data.fatal) this._onError(data.details || data.type, data.type); });
        this.hls.loadSource(src);
        this.hls.attachMedia(v);
        this._sourceAttached = true;
        done();
      };
      if (global.Hls) { attach(global.Hls); return; }
      loadHls(this.opts.hlsUrl).then(attach, () => fallback('hls-load'));
    }

    // Nível do HLS cuja altura (o menor lado, para vídeo vertical) fica mais perto de 480. Sem medidas, 0.
    _nivelInicial(levels) {
      let best = 0;
      let bestDiff = Infinity;
      (levels || []).forEach((level, i) => {
        const h = Number(level && level.height) || 0;
        const w = Number(level && level.width) || 0;
        const lado = h > 0 && w > 0 ? Math.min(h, w) : (h || w);
        if (!(lado > 0)) return;
        const diff = Math.abs(lado - TARGET_HEIGHT);
        if (diff < bestDiff) { bestDiff = diff; best = i; }
      });
      return best;
    }

    _boot() {
      const v = this.video;
      if (!this.opts.autoplay) { this._setState('idle'); return; }
      if (this.state !== 'loading') return;
      v.muted = true;
      v.setAttribute('muted', '');
      this._play(); // fica em loading até o primeiro quadro; bloqueado pelo aparelho -> idle + autoplay_blocked
    }

    // -- eventos do <video> --------------------------------------------------

    _listen(target, type, fn) {
      target.addEventListener(type, fn);
      this._listeners.push([target, type, fn]);
    }

    _bindVideo() {
      const v = this.video;
      this._listen(v, 'loadedmetadata', () => {
        this.duration = v.duration;
        if (this.opts.aspect === 'auto' && v.videoWidth && v.videoHeight) {
          this.root.style.setProperty('--vsl-aspect', v.videoWidth + ' / ' + v.videoHeight);
        }
        if (this._pendingSeek != null) { const t = this._pendingSeek; this._pendingSeek = null; this._seek(t); }
        if (!this._readyEmitted) { this._readyEmitted = true; this.emit('ready', { duration: v.duration }); }
      });
      this._listen(v, 'durationchange', () => { this.duration = v.duration; });
      // Em `loading` o estado só muda com imagem na tela (primeiro quadro), não no play().
      this._listen(v, 'play', () => { if (this.state !== 'error' && this.state !== 'loading') this._setState(v.muted ? 'autoplaying' : 'playing'); });
      this._listen(v, 'playing', () => { this.root.classList.remove('vsl-buffering'); this._firstFrame(); });
      this._listen(v, 'canplay', () => { this.root.classList.remove('vsl-buffering'); this._retrySeek(); });
      this._listen(v, 'progress', () => this._retrySeek());
      this._listen(v, 'waiting', () => this.root.classList.add('vsl-buffering'));
      this._listen(v, 'pause', () => {
        if (v.ended) return;
        if (['modal', 'idle', 'loading', 'error', 'ended'].indexOf(this.state) >= 0) return;
        this._persist(true);
        this._setState('paused');
      });
      this._listen(v, 'ended', () => this._onEnded());
      this._listen(v, 'timeupdate', () => { this._firstFrame(); this._onTime(); });
      this._listen(v, 'seeking', () => this._onSeeking());
      this._listen(v, 'seeked', () => this._onSeeked());
      this._listen(v, 'ratechange', () => { if (this.opts.lockSpeed && v.playbackRate !== this.opts.speed) v.playbackRate = this.opts.speed; });
      this._listen(v, 'error', () => this._onError(v.error && v.error.code));
      this._listen(document, 'visibilitychange', () => this._checkPitch());
      this._listen(global, 'pagehide', () => this._persist(true));
    }

    // Primeiro quadro na tela: sai de `loading` e cancela o watchdog.
    _firstFrame() {
      if (this.state !== 'loading' || this._retryTimer) return; // com retentativa pendente, espera ela acontecer
      const v = this.video;
      if (v.paused || !(v.currentTime > FIRST_FRAME_TIME)) return;
      clearTimeout(this._frameTimer);
      this._frameTimer = null;
      this._attempts = 0; // voltou a tocar: a próxima falha ganha retentativas novas
      this.root.classList.remove('vsl-buffering');
      this._setState(v.muted ? 'autoplaying' : 'playing');
    }

    _onTime() {
      const v = this.video;
      // Há um seek pendente para a posição guardada (retentativa recarregou a fonte; iOS antes dos metadados): o
      // timeupdate em 0 que o load() dispara não pode apagar _lastTime nem a posição salva. Assim que der, aplica o seek.
      if (this._pendingSeek != null) {
        if (v.readyState >= 1) { const alvo = this._pendingSeek; this._pendingSeek = null; this._seek(alvo); }
        return;
      }
      const t = v.currentTime;
      const d = v.duration;
      if (this._seekRetry != null && t >= this._seekRetry) this._seekRetry = null; // tocou até passar do alvo recusado
      // Seek em andamento ou recusado (stream sem Range): o vídeo pode estar em 0, mas a posição que vale é o alvo.
      if (!v.seeking) this._lastTime = this._position();
      if (!v.paused && !v.muted) this.tracker.second(t); // retenção só conta o que foi visto com som
      if (t > this.reached) this.reached = t;
      if (t - this._lastSaved >= 1 || t < this._lastSaved) { this._lastSaved = t; this._persist(false); }
      this._applyElements(t);
      this._renderProgress(t, d);
      if (d > 0) {
        const percent = (t / d) * 100;
        MILESTONES.forEach((m) => {
          if (percent >= m && !this._milestones.has(m)) { this._milestones.add(m); this.emit('milestone', { percent: m }); }
        });
      }
      this._checkPitch();
      this.emit('progress', { time: t, duration: d, percent: d > 0 ? (t / d) * 100 : 0 });
    }

    // O pitch só conta com som e com a aba visível. Se o tempo passou mudo, fica pendente até a condição valer.
    _checkPitch() {
      if (this._pitchAt == null || this._pitchDone) return;
      const v = this.video;
      if (v.muted || !(v.currentTime >= this._pitchAt)) return;
      if (document.visibilityState && document.visibilityState !== 'visible') return;
      this._pitchDone = true;
      storage.set(this.id + ':pitch', '1');
      this.emit('pitch', { at: this._pitchAt, time: round(v.currentTime), muted: false });
    }

    _onSeeking() {
      const v = this.video;
      if (!this.opts.lockSeek || this._seekAllowed) return;
      if (Math.abs(v.currentTime - this._lastTime) > 1.5) {
        const attempted = v.currentTime;
        v.currentTime = this._lastTime;
        this.emit('seek_blocked', { attempted, time: this._lastTime });
      }
    }

    // Fim de um seek. Se o navegador recusou o alvo pedido (num stream sem Range `seekable` é [0,0] e o seek cai em 0),
    // a posição não se perde: _lastTime fica no alvo, :pos não cai abaixo dele e o seek é refeito quando der (_retrySeek).
    _onSeeked() {
      const v = this.video;
      this._seekAllowed = false;
      const alvo = this._seekTarget;
      this._seekTarget = null;
      if (alvo != null && Math.abs(v.currentTime - alvo) > 1.5) { this._seekRetry = alvo; this._lastTime = alvo; }
      else { this._seekRetried = 0; this._lastTime = v.currentTime; }
      this._renderPausePoster();
    }

    // Seek recusado: assim que `seekable` cobrir o alvo (progress/canplay), pede de novo; desiste depois de 3 vezes.
    _retrySeek() {
      const v = this.video;
      const alvo = this._seekRetry;
      if (alvo == null || v.readyState < 1 || v.seeking || this._seekRetried >= 3) return;
      const r = v.seekable;
      for (let i = 0; i < r.length; i++) {
        if (alvo >= r.start(i) && alvo <= r.end(i)) { this._seekRetried++; this._seek(alvo); return; }
      }
    }

    _onEnded() {
      this._setState('ended');
      storage.remove(this.id + ':pos');
      this._resumeAsked = false;
      if (!this._milestones.has(100)) { this._milestones.add(100); this.emit('milestone', { percent: 100 }); }
      this.emit('ended');
    }

    // -- erro, retentativas e saída -----------------------------------------

    // Falha do vídeo: até 3 retentativas automáticas (1 s, 3 s, 8 s) em `loading`; só depois `error`.
    _onError(code, hlsType) {
      if (this.state === 'error' || this._retryTimer) return;
      this._errorCode = code == null ? 'unknown' : code;
      this._hlsErrorType = hlsType || null;
      // Pausado, ou decidindo se continua de onde parou: a retentativa recarrega a fonte, mas não retoma sozinha.
      this._stateBeforeError = this.state === 'paused' || this.state === 'modal' ? this.state : null;
      clearTimeout(this._frameTimer);
      this._frameTimer = null;
      if (code === 'hls-unsupported' || this._attempts >= RETRY_DELAYS.length) { this._fail(); return; }
      const delay = RETRY_DELAYS[this._attempts];
      this._attempts++;
      this.root.classList.add('vsl-buffering');
      this._setState('loading');
      this._retryTimer = setTimeout(() => { this._retryTimer = null; this._retry(); }, delay);
    }

    _retry() {
      const v = this.video;
      this.root.classList.add('vsl-buffering');
      this._setState('loading');
      if (this.hls) {
        const Hls = global.Hls;
        const tipos = (Hls && Hls.ErrorTypes) || {};
        const ultimoRecurso = this._attempts >= RETRY_DELAYS.length;
        if (!ultimoRecurso && this._hlsErrorType === tipos.NETWORK_ERROR) { this.hls.startLoad(); this._resumeAfterRetry(); return; }
        if (!ultimoRecurso && this._hlsErrorType === tipos.MEDIA_ERROR) { this.hls.recoverMediaError(); this._resumeAfterRetry(); return; }
        this._keepPosition();
        this.hls.destroy();
        this.hls = null;
        this._sourceAttached = false;
      }
      this._keepPosition();
      if (!this._sourceAttached) { this._attachSource(() => this._resumeAfterRetry()); return; }
      v.load(); // nativo: recarrega a fonte (zera o currentTime); o seek pendente devolve a posição quando os metadados chegarem
      this._resumeAfterRetry();
    }

    // Antes de recarregar a fonte: a posição vira um seek pendente, que o timeupdate em 0 do load() não apaga (ver _onTime).
    _keepPosition() {
      if (this._pendingSeek == null && this._lastTime > 0) this._pendingSeek = this._lastTime;
      this._seekTarget = null; // o seek em andamento morre com a fonte; a posição segue no seek pendente
    }

    _resumeAfterRetry() {
      const v = this.video;
      v.muted = !this.unmuted; // mudo se ainda não liberou o som; com som se já liberou
      if (v.muted) v.setAttribute('muted', ''); else v.removeAttribute('muted');
      const antes = this._stateBeforeError;
      this._stateBeforeError = null;
      if (antes === 'paused' || antes === 'modal') {
        // O visitante tinha pausado (ou estava no "continuar de onde parou?"): a fonte foi recarregada, mas o vídeo
        // não volta a tocar sozinho. O toque (ou a escolha no modal) retoma da posição guardada.
        this.root.classList.remove('vsl-buffering');
        this._setState(antes, true); // o visitante não pausou de novo: sem evento `pause` repetido
        return;
      }
      this._play();
    }

    _fail() {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
      this.root.classList.remove('vsl-buffering');
      this._setState('error');
      // Fail-open: o botão de compra nunca fica escondido por falha do vídeo.
      this._showAt.forEach((item) => { item.el.classList.add('vsl-visible'); item.el.removeAttribute('hidden'); });
      this.emit('error', { code: this._errorCode, attempt: this._attempts });
    }

    _persist(force) {
      storage.set(this.id + ':reached', round(this.reached));
      if (!this.unmuted || !(force || !this.video.paused)) return;
      storage.set(this.id + ':pos', round(this._position()));
    }

    // Posição que vale para guardar e decidir: a do seek pendente (fonte recarregada, <video> em 0); com um seek em
    // andamento (o Chromium dispara um timeupdate antes do `seeked`) ou recusado (stream sem Range), a maior entre a
    // atual e o alvo (aceito, o <video> já está no alvo; recusado, vale o alvo); senão a atual.
    _position() {
      if (this._pendingSeek != null) return this._pendingSeek;
      const t = this.video ? this.video.currentTime : 0;
      const alvo = this._seekTarget != null ? this._seekTarget : this._seekRetry;
      return alvo != null ? Math.max(t, alvo) : t;
    }

    _savedPosition() {
      const pos = parseFloat(storage.get(this.id + ':pos'));
      if (!(pos > 0)) return 0;
      if (this.duration > 0 && pos >= this.duration - 3) return 0;
      return pos;
    }

    _renderProgress(t, d) {
      if (this.opts.progress === 'none' || !(d > 0)) return;
      const real = clamp(t / d, 0, 1);
      const shown = this.opts.progress === 'smart' ? 1 - Math.pow(1 - real, this.opts.progressIntensity) : real;
      this.bar.style.width = (shown * 100).toFixed(2) + '%';
    }

    _seek(time) {
      const v = this.video;
      if (v.readyState < 1) { this._pendingSeek = time; return; } // iOS: só depois de carregar os metadados
      this._seekAllowed = true;
      this._seekTarget = time;
      this._seekRetry = null;
      this._lastTime = time;
      try { v.currentTime = time; } catch (e) { /* ignora */ }
      clearTimeout(this._seekTimer);
      this._seekTimer = setTimeout(() => { this._seekAllowed = false; }, 1500);
    }

    // -- estados e interação -------------------------------------------------

    // `quiet`: restaura um estado sem repetir o evento de interação (pause/play/autoplay) para o analytics;
    // usado quando a retentativa ou o watchdog devolvem o player ao estado em que o visitante o deixou.
    _setState(state, quiet) {
      if (this.state === state) return;
      const previous = this.state;
      this.state = state;
      this.root.setAttribute('data-state', state);
      if (state !== 'loading') { clearTimeout(this._frameTimer); this._frameTimer = null; }
      this._renderPausePoster();
      if (!quiet) {
        if (state === 'autoplaying') this.emit('autoplay');
        else if (state === 'playing') this.emit('play', { resumed: previous === 'paused' });
        else if (state === 'paused') this.emit('pause');
      }
      this.emit('state', { state, previous, restored: !!quiet });
    }

    // Miniatura de pausa: só pausado, com imagem configurada e depois do pitch (sem pitch, em qualquer pausa).
    _renderPausePoster() {
      // Posição guardada, não o <video> (que está em 0 logo depois do load() de uma retentativa).
      const depoisDoPitch = this._position() >= (this._pitchAt == null ? 0 : this._pitchAt);
      if (this.state === 'paused' && this.opts.pausePosterLate && depoisDoPitch) this.root.setAttribute('data-pause-poster', 'on');
      else this.root.removeAttribute('data-pause-poster');
    }

    _bindUI() {
      const root = this.root;
      this._listen(root, 'click', (e) => {
        if (e.target.closest('[data-vsl-action], .vsl-fullscreen, .vsl-card, .vsl-cta')) return;
        this._onTap();
      });
      this._listen(root, 'keydown', (e) => {
        if (e.target !== root) return;
        if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); this._onTap(); }
        else if (/^Arrow/.test(e.key)) e.preventDefault();
      });
      this._listen(root, 'contextmenu', (e) => e.preventDefault());
      root.querySelectorAll('[data-vsl-action]').forEach((btn) => {
        this._listen(btn, 'click', (e) => {
          e.stopPropagation();
          this._onAction(btn.getAttribute('data-vsl-action'));
        });
      });
      // Botão de compra (CTA): não pausa nem reinicia, deixa o link seguir e avisa o analytics na hora.
      root.querySelectorAll('.vsl-cta').forEach((a) => {
        this._listen(a, 'click', (e) => {
          e.stopPropagation();
          const where = a.closest('.vsl-pause-poster') ? 'pause' : 'end';
          this.emit('cta_click', { where, link: a.getAttribute('href') });
        });
      });
      this._listen(root.querySelector('.vsl-fullscreen'), 'click', (e) => { e.stopPropagation(); this.toggleFullscreen(); });
      this._listen(document, 'fullscreenchange', () => {
        this.emit('fullscreen', { active: document.fullscreenElement === root });
      });
    }

    _onAction(action) {
      if (action === 'retry') { this.retry(); return; }
      this._onResumeChoice(action);
    }

    _onTap() {
      const now = Date.now();
      if (now < this._tapGuardUntil) return; // segundo toque logo depois de liberar o som: não pausa
      switch (this.state) {
        case 'loading':
        case 'idle':
          // Sessão que já tem som (retentativa presa, play() recusado depois de um erro): o toque retoma de onde parou.
          if (this.unmuted) this._playWithSound(this._lastTime > 0 ? this._lastTime : null);
          else this._startWithSound();
          break;
        case 'autoplaying':
          this._startWithSound();
          if (this.state === 'playing') this._tapGuardUntil = now + TAP_GUARD;
          break;
        case 'playing':
          this.pause();
          break;
        case 'paused':
          if (this.unmuted) this.play(); else this._startWithSound();
          break;
        case 'ended':
          this.restart();
          break;
        case 'error':
          this.retry();
          break;
        default:
          break;
      }
    }

    _startWithSound() {
      const saved = this.opts.resume ? this._savedPosition() : 0;
      if (saved >= Math.max(1, this.opts.resumeMin) && !this._resumeAsked) {
        this._resumeAsked = true;
        this.modalText.textContent = String(this.opts.texts.resumeSubtitle).replace('{time}', formatTime(saved));
        this._setState('modal');
        this.video.pause();
        this.emit('resume_prompt', { time: saved });
        return;
      }
      this._playWithSound(this.opts.unmuteRestart || this.state === 'idle' ? 0 : null);
    }

    _onResumeChoice(action) {
      if (this.state !== 'modal') return;
      const saved = this._savedPosition();
      if (action === 'continue' && saved > 0) {
        this.emit('resume_continue', { time: saved });
        this._playWithSound(saved);
      } else {
        storage.remove(this.id + ':pos');
        this.emit('resume_restart');
        this._playWithSound(0);
      }
    }

    _playWithSound(time) {
      const v = this.video;
      if (time != null) this._seek(time);
      v.muted = false;
      v.removeAttribute('muted');
      v.volume = 1;
      if (!this.unmuted) { this.unmuted = true; this.emit('unmute', { time: time == null ? v.currentTime : time }); }
      this._play();
    }

    _play() {
      const v = this.video;
      let promise;
      try { promise = v.play(); } catch (e) { promise = Promise.reject(e); }
      if (this.state === 'error') return;
      if (this.state === 'loading') this._awaitFrame(); // só sai de loading com imagem na tela
      else this._setState(v.muted ? 'autoplaying' : 'playing');
      if (promise && promise.catch) {
        promise.catch((err) => {
          // AbortError: outro play()/pause()/load() tomou a frente. NotSupportedError: o evento `error` cuida.
          const name = err && err.name;
          if (name === 'AbortError' || name === 'NotSupportedError') return;
          if (!v.paused || ['loading', 'autoplaying', 'playing'].indexOf(this.state) < 0) return;
          clearTimeout(this._frameTimer);
          this._frameTimer = null;
          this._setState('idle');
          this.emit('autoplay_blocked');
        });
      }
    }

    // play() aceito: se em 12 s não aparecer imagem, volta para a capa com o play (sem derrubar o <video>).
    _awaitFrame() {
      this.root.classList.add('vsl-buffering');
      clearTimeout(this._frameTimer);
      this._frameTimer = setTimeout(() => {
        this._frameTimer = null;
        if (this.state !== 'loading') return;
        clearTimeout(this._retryTimer);
        this._retryTimer = null;
        this._attempts = 0;
        this.root.classList.remove('vsl-buffering');
        try { this.video.pause(); } catch (e) { /* ignora */ }
        // Sessão que já tem som (uma retentativa presa na rede): "toque para continuar", e o toque retoma de onde parou.
        // A posição volta a ser um seek pendente: se o navegador recarregar o <video> por conta própria enquanto
        // espera, o timeupdate em 0 não a apaga, e o play() seguinte a aplica de novo.
        if (this.unmuted) { this._keepPosition(); this._setState('paused', true); return; } // sem evento `pause`: ninguém pausou
        this._setState('idle');
        this.emit('autoplay_blocked', { reason: 'no-frame' });
      }, FIRST_FRAME_TIMEOUT);
    }

    // -- elementos da página com delay ---------------------------------------

    _bindElements() {
      const root = this.root;
      const mine = (el) => {
        if (el === root || root.contains(el)) return false; // o próprio player pode ter data-show-at
        const owner = el.getAttribute('data-vsl-player');
        return owner ? owner === this.id : this._isFirst;
      };
      // data-show="#botao, .oferta": os elementos casados viram data-vsl-show-at no showAt (ou no pitch).
      const showAt = parseTime(this.opts.showAt);
      const at = showAt != null ? showAt : this._pitchAt;
      if (this.opts.show && at != null) {
        let alvos = [];
        try { alvos = Array.from(document.querySelectorAll(this.opts.show)); } catch (e) { console.error('VSLPlayer: data-show inválido: ' + this.opts.show); }
        alvos.forEach((el) => {
          if (el === root || root.contains(el)) return;
          if (!el.hasAttribute('data-vsl-show-at')) el.setAttribute('data-vsl-show-at', String(at));
          if (!el.hasAttribute('data-vsl-player')) el.setAttribute('data-vsl-player', this.id);
        });
      }
      const collect = (attr) => Array.from(document.querySelectorAll('[' + attr + ']'))
        .filter(mine)
        .map((el) => ({ el, at: parseTime(el.getAttribute(attr)), done: false }))
        .filter((item) => item.at != null);
      this._showAt = collect('data-vsl-show-at');
      this._hideAt = collect('data-vsl-hide-at');
      if (this.state === 'error') this._showAt.forEach((item) => item.el.classList.add('vsl-visible')); // fail-open também para quem chegou depois
      this._applyElements(this.reached, true);
    }

    _applyElements(time, persisted) {
      this._showAt.forEach((item) => {
        if (item.done || time < item.at) return;
        item.done = true;
        item.el.classList.add('vsl-visible');
        item.el.removeAttribute('hidden');
        this.emit('reach', { at: item.at, action: 'show', persisted: !!persisted, element: item.el });
      });
      this._hideAt.forEach((item) => {
        if (item.done || time < item.at) return;
        item.done = true;
        item.el.classList.add('vsl-hidden');
        this.emit('reach', { at: item.at, action: 'hide', persisted: !!persisted, element: item.el });
      });
    }

    // -- API pública ---------------------------------------------------------

    on(type, fn) { (this._handlers[type] = this._handlers[type] || []).push(fn); return this; }

    off(type, fn) {
      const list = this._handlers[type] || [];
      const i = list.indexOf(fn);
      if (i >= 0) list.splice(i, 1);
      return this;
    }

    emit(type, detail) {
      const data = Object.assign({ player: this, id: this.id }, detail || {});
      (this._handlers[type] || []).slice().forEach((fn) => {
        try { fn(data); } catch (e) { console.error(e); }
      });
      (this._handlers['*'] || []).slice().forEach((fn) => {
        try { fn(type, data); } catch (e) { console.error(e); }
      });
      try { this.root.dispatchEvent(new CustomEvent('vsl:' + type, { bubbles: true, detail: data })); } catch (e) { /* ignora */ }
      if (this.tracker && type !== 'progress' && type !== 'state') this.tracker.track(type, detail);
      return this;
    }

    play() { if (this.state === 'ended') return this.restart(); this._play(); }

    pause() { this.video.pause(); }

    unmute() { this._startWithSound(); }

    restart() { this.emit('replay'); this._playWithSound(0); }

    // Tenta carregar o vídeo de novo (botão "Tentar de novo" ou toque na tela de erro); zera o contador.
    retry() {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
      this._attempts = 0;
      this._stateBeforeError = null; // quem pede para tentar de novo quer ver o vídeo tocar
      this._retry();
    }

    seek(time) { this._seek(clamp(parseTime(time) || 0, 0, this.duration || Infinity)); }

    refreshElements() { this._bindElements(); }

    toggleFullscreen() {
      const root = this.root;
      const v = this.video;
      if (document.fullscreenElement === root) { document.exitFullscreen(); return; }
      if (root.requestFullscreen) { root.requestFullscreen().catch(() => {}); return; }
      if (v.webkitEnterFullscreen) v.webkitEnterFullscreen(); // iPhone: usa o player nativo
    }

    forget() {
      ['pos', 'reached', 'pitch'].forEach((key) => storage.remove(this.id + ':' + key));
      this.reached = 0;
      this._pitchDone = false;
    }

    destroy() {
      this.tracker.destroy();
      clearTimeout(this._seekTimer);
      clearTimeout(this._retryTimer);
      clearTimeout(this._frameTimer);
      this._listeners.forEach(([target, type, fn]) => target.removeEventListener(type, fn));
      this._listeners = [];
      if (this.hls) { this.hls.destroy(); this.hls = null; }
      this.video.removeAttribute('src');
      this.video.load();
      this.root.innerHTML = '';
      this.root.removeAttribute('data-vsl-ready');
      this.root.removeAttribute('data-pause-poster');
      delete this.root.vslPlayer;
      VSLPlayer.instances = VSLPlayer.instances.filter((p) => p !== this);
      delete VSLPlayer.byId[this.id];
    }

    get currentTime() { return this.video ? this.video.currentTime : 0; }
    get muted() { return this.video ? this.video.muted : true; }
    get paused() { return this.video ? this.video.paused : true; }
    get percent() { return this.duration > 0 ? (this.currentTime / this.duration) * 100 : 0; }
  }

  VSLPlayer.version = VERSION;
  VSLPlayer.events = EVENTS.slice();
  VSLPlayer.instances = [];
  VSLPlayer.byId = {};
  VSLPlayer._preconectados = {};
  VSLPlayer._hlsLoading = null;
  VSLPlayer.parseTime = parseTime;
  VSLPlayer.formatTime = formatTime;
  VSLPlayer.create = (el, options) => new VSLPlayer(el, options);
  VSLPlayer.get = (id) => VSLPlayer.byId[id] || null;

  // Inicia todos os <div class="vsl-player" data-src="..."> ainda não iniciados.
  VSLPlayer.init = (scope) => Array.from((scope || document).querySelectorAll('.vsl-player:not([data-vsl-ready])'))
    .map((el) => { try { return new VSLPlayer(el); } catch (e) { console.error(e); return null; } })
    .filter(Boolean);

  // Ouve um evento de qualquer player da página: VSLPlayer.on('unmute', (detail) => ...)
  VSLPlayer.on = (type, fn) => {
    const types = type === '*' ? EVENTS : [type];
    const handlers = types.map((name) => {
      const handler = (e) => fn(e.detail, name, e);
      document.addEventListener('vsl:' + name, handler);
      return [name, handler];
    });
    return () => handlers.forEach(([name, handler]) => document.removeEventListener('vsl:' + name, handler));
  };

  global.VSLPlayer = VSLPlayer;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => VSLPlayer.init());
  else VSLPlayer.init();
})(typeof window !== 'undefined' ? window : null, typeof document !== 'undefined' ? document : null);
