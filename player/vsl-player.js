/*!
 * VSL Player 1.0.0
 * Player de vídeo para páginas de vendas (VSL), no estilo VTurb:
 *  - smart autoplay: começa mudo e pede o clique para ouvir (e recomeça com som);
 *  - barra de progresso inteligente, que anda rápido no começo e devagar no fim;
 *  - delay de elementos da página (botão de compra aparece no minuto certo);
 *  - "continuar de onde parou" entre visitas;
 *  - sem controles de avanço: clique pausa/retoma, velocidade e seek travados;
 *  - eventos para pixels (Meta, GA4...) e envio de retenção para um endpoint seu.
 * Sem dependências. Licença MIT.
 */
(function (global, document) {
  'use strict';

  if (!global || !document) return;

  const VERSION = '1.0.0';
  const STORAGE_PREFIX = 'vsl:';
  const MILESTONES = [10, 25, 50, 75, 90];
  const FLUSH_NOW = ['unmute', 'ended', 'pitch'];
  const EVENTS = [
    'ready', 'autoplay', 'autoplay_blocked', 'unmute', 'play', 'pause', 'ended', 'replay',
    'progress', 'milestone', 'pitch', 'reach', 'resume_prompt', 'resume_continue', 'resume_restart',
    'seek_blocked', 'fullscreen', 'state', 'error',
  ];

  const DEFAULTS = {
    id: '',                   // identificador do player (chave do localStorage e dos eventos)
    src: '',                  // MP4 ou .m3u8 (HLS)
    fallback: '',             // MP4 usado quando o navegador não toca HLS
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
    pauseOverlay: true,       // mostra "clique para continuar" quando pausado
    endScreen: 'replay',      // replay | poster | none
    lockSpeed: true,          // impede acelerar o vídeo (extensões, console)
    lockSeek: true,           // impede pular trechos (extensões, console)
    fullscreen: false,        // mostra o botão de tela cheia
    pitch: '',                // segundos (ou mm:ss) em que a oferta começa; dispara "pitch" uma vez
    analytics: '',            // URL que recebe os eventos e a retenção (POST, JSON)
    analyticsInterval: 15,    // segundos entre os envios
    texts: {
      unmuteTitle: 'Seu vídeo já começou',
      unmuteSubtitle: 'Clique para ouvir',
      play: 'Clique para assistir',
      pause: 'Clique para continuar assistindo',
      replay: 'Assistir novamente',
      resumeTitle: 'Você já começou a assistir este vídeo',
      resumeSubtitle: 'Quer continuar de onde parou?',
      resumeContinue: 'Continuar de onde parei',
      resumeRestart: 'Começar do início',
      error: 'Não foi possível carregar o vídeo.',
      fullscreen: 'Tela cheia',
    },
  };

  // data-atributo de cada texto: data-unmute-title="..."
  const TEXT_ATTRS = {
    unmuteTitle: 'unmute-title', unmuteSubtitle: 'unmute-subtitle', play: 'play-text',
    pause: 'pause-text', replay: 'replay-text', resumeTitle: 'resume-title',
    resumeSubtitle: 'resume-subtitle', resumeContinue: 'resume-continue',
    resumeRestart: 'resume-restart', error: 'error-text', fullscreen: 'fullscreen-label',
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
    merged.texts = Object.assign({}, DEFAULTS.texts, data.texts, (options && options.texts) || {});
    if (!(merged.progressIntensity > 0)) merged.progressIntensity = DEFAULTS.progressIntensity;
    if (!(merged.resumeMin >= 0)) merged.resumeMin = DEFAULTS.resumeMin;
    return merged;
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
      if (!this.url) return;
      this.visitor = storage.get('visitor');
      if (!this.visitor) { this.visitor = uuid(); storage.set('visitor', this.visitor); }
      this.session = uuid();
      const interval = Math.max(5, Number(player.opts.analyticsInterval) || DEFAULTS.analyticsInterval);
      this.timer = setInterval(() => this.flush(), interval * 1000);
      this.onHide = () => this.flush();
      this.onVisibility = () => { if (document.visibilityState === 'hidden') this.flush(); };
      global.addEventListener('pagehide', this.onHide);
      document.addEventListener('visibilitychange', this.onVisibility);
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
      if (FLUSH_NOW.indexOf(type) >= 0) this.flush();
    }

    flush() {
      if (!this.url || (!this.queue.length && !this.dirty)) return;
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
    }

    destroy() {
      if (!this.url) return;
      this.flush();
      clearInterval(this.timer);
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
      this._lastTime = 0;
      this._lastSaved = -1;
      this._seekAllowed = false;
      this._pendingSeek = null;
      this._listeners = [];
      this._isFirst = VSLPlayer.instances.length === 0;

      VSLPlayer.instances.push(this);
      VSLPlayer.byId[this.id] = this;

      this.tracker = new Tracker(this); // antes de tudo: os elementos já alcançados emitem eventos na montagem
      this._build();
      this._bindVideo();
      this._bindUI();
      this._bindElements();
      this._attachSource();
      this._boot();
    }

    // -- montagem ------------------------------------------------------------

    _build() {
      const root = this.root;
      const o = this.opts;
      const t = o.texts;
      root.classList.add('vsl-player');
      root.setAttribute('data-vsl-ready', '1');
      root.setAttribute('data-vsl-id', this.id);
      root.setAttribute('data-state', this.state);
      root.setAttribute('data-progress', o.progress);
      root.setAttribute('data-end-screen', o.endScreen);
      root.setAttribute('data-pause-overlay', o.pauseOverlay ? 'true' : 'false');
      root.setAttribute('data-fullscreen', o.fullscreen ? 'true' : 'false');
      root.setAttribute('tabindex', '0');
      root.setAttribute('role', 'region');
      root.setAttribute('aria-label', 'Vídeo');
      root.style.setProperty('--vsl-color', o.color);
      root.style.setProperty('--vsl-aspect', cssAspect(o.aspect));

      root.innerHTML =
        '<video class="vsl-video" playsinline webkit-playsinline preload="' + esc(o.preload) + '" ' +
        'disablepictureinpicture disableremoteplayback controlslist="nodownload noplaybackrate noremoteplayback"></video>' +
        '<div class="vsl-layer vsl-poster"></div>' +
        '<div class="vsl-layer vsl-unmute"><div class="vsl-box">' +
        '<span class="vsl-icon vsl-icon--pulse">' + ICONS.muted + '</span>' +
        '<strong>' + esc(t.unmuteTitle) + '</strong><span class="vsl-sub">' + esc(t.unmuteSubtitle) + '</span></div></div>' +
        '<div class="vsl-layer vsl-idle"><div class="vsl-play-btn">' + ICONS.play + '</div>' +
        '<span class="vsl-caption">' + esc(t.play) + '</span></div>' +
        '<div class="vsl-layer vsl-paused"><div class="vsl-box"><span class="vsl-icon">' + ICONS.play + '</span>' +
        '<strong>' + esc(t.pause) + '</strong></div></div>' +
        '<div class="vsl-layer vsl-ended"><div class="vsl-box"><span class="vsl-icon">' + ICONS.replay + '</span>' +
        '<strong>' + esc(t.replay) + '</strong></div></div>' +
        '<div class="vsl-layer vsl-error"><div class="vsl-box"><span class="vsl-icon">' + ICONS.warning + '</span>' +
        '<strong>' + esc(t.error) + '</strong></div></div>' +
        '<div class="vsl-layer vsl-loading"><div class="vsl-spinner"></div></div>' +
        '<div class="vsl-layer vsl-modal"><div class="vsl-card" role="dialog" aria-modal="true">' +
        '<strong>' + esc(t.resumeTitle) + '</strong><p>' + esc(t.resumeSubtitle) + '</p>' +
        '<button type="button" class="vsl-btn vsl-btn--primary" data-vsl-action="continue">' + esc(t.resumeContinue) + '</button>' +
        '<button type="button" class="vsl-btn vsl-btn--ghost" data-vsl-action="restart">' + esc(t.resumeRestart) + '</button>' +
        '</div></div>' +
        '<div class="vsl-progress" aria-hidden="true"><div class="vsl-progress-bar"></div></div>' +
        '<button type="button" class="vsl-fullscreen" aria-label="' + esc(t.fullscreen) + '">' + ICONS.fullscreen + '</button>';

      this.video = root.querySelector('.vsl-video');
      this.bar = root.querySelector('.vsl-progress-bar');
      this.posterLayer = root.querySelector('.vsl-poster');
      if (o.poster) {
        this.video.setAttribute('poster', o.poster);
        this.posterLayer.style.backgroundImage = 'url("' + o.poster.replace(/"/g, '%22') + '")';
      }
    }

    _attachSource() {
      const v = this.video;
      const src = this.opts.src;
      const isHls = /\.m3u8(\?|#|$)/i.test(src);
      if (!isHls) { v.src = src; return; }
      if (v.canPlayType('application/vnd.apple.mpegurl')) { v.src = src; return; }
      const Hls = global.Hls;
      if (Hls && Hls.isSupported()) {
        this.hls = new Hls();
        this.hls.on(Hls.Events.ERROR, (_, data) => { if (data && data.fatal) this._onError(data.type); });
        this.hls.loadSource(src);
        this.hls.attachMedia(v);
        return;
      }
      if (this.opts.fallback) { v.src = this.opts.fallback; return; }
      this._onError('hls-unsupported');
    }

    _boot() {
      const v = this.video;
      if (!this.opts.autoplay) { this._setState('idle'); return; }
      v.muted = true;
      v.setAttribute('muted', '');
      let promise;
      try { promise = v.play(); } catch (e) { promise = Promise.reject(e); }
      if (promise && promise.then) {
        promise.then(() => { if (this.state !== 'error') this._setState(v.muted ? 'autoplaying' : 'playing'); }).catch(() => {
          // Autoplay bloqueado (ex.: iPhone em modo de economia de energia): mostra a capa com o play.
          if (this.state === 'error') return;
          this._setState('idle');
          this.emit('autoplay_blocked');
        });
      }
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
        this.emit('ready', { duration: v.duration });
      });
      this._listen(v, 'durationchange', () => { this.duration = v.duration; });
      this._listen(v, 'play', () => { if (this.state !== 'error') this._setState(v.muted ? 'autoplaying' : 'playing'); });
      this._listen(v, 'playing', () => this.root.classList.remove('vsl-buffering'));
      this._listen(v, 'canplay', () => this.root.classList.remove('vsl-buffering'));
      this._listen(v, 'waiting', () => this.root.classList.add('vsl-buffering'));
      this._listen(v, 'pause', () => {
        if (v.ended) return;
        if (['modal', 'idle', 'loading', 'error', 'ended'].indexOf(this.state) >= 0) return;
        this._persist(true);
        this._setState('paused');
      });
      this._listen(v, 'ended', () => this._onEnded());
      this._listen(v, 'timeupdate', () => this._onTime());
      this._listen(v, 'seeking', () => this._onSeeking());
      this._listen(v, 'seeked', () => { this._seekAllowed = false; this._lastTime = v.currentTime; });
      this._listen(v, 'ratechange', () => { if (this.opts.lockSpeed && v.playbackRate !== 1) v.playbackRate = 1; });
      this._listen(v, 'error', () => this._onError(v.error && v.error.code));
      this._listen(global, 'pagehide', () => this._persist(true));
    }

    _onTime() {
      const v = this.video;
      const t = v.currentTime;
      const d = v.duration;
      if (!v.seeking) this._lastTime = t;
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
      if (this._pitchAt != null && !this._pitchDone && t >= this._pitchAt) {
        this._pitchDone = true;
        storage.set(this.id + ':pitch', '1');
        this.emit('pitch', { at: this._pitchAt });
      }
      this.emit('progress', { time: t, duration: d, percent: d > 0 ? (t / d) * 100 : 0 });
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

    _onEnded() {
      this._setState('ended');
      storage.remove(this.id + ':pos');
      this._resumeAsked = false;
      if (!this._milestones.has(100)) { this._milestones.add(100); this.emit('milestone', { percent: 100 }); }
      this.emit('ended');
    }

    _onError(code) {
      if (this.state === 'error') return;
      this._setState('error');
      this.emit('error', { code: code == null ? 'unknown' : code });
    }

    _persist(force) {
      storage.set(this.id + ':reached', round(this.reached));
      if (this.unmuted && (force || !this.video.paused)) storage.set(this.id + ':pos', round(this.video.currentTime));
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
      this._lastTime = time;
      try { v.currentTime = time; } catch (e) { /* ignora */ }
      clearTimeout(this._seekTimer);
      this._seekTimer = setTimeout(() => { this._seekAllowed = false; }, 1500);
    }

    // -- estados e interação -------------------------------------------------

    _setState(state) {
      if (this.state === state) return;
      const previous = this.state;
      this.state = state;
      this.root.setAttribute('data-state', state);
      if (state === 'autoplaying') this.emit('autoplay');
      else if (state === 'playing') this.emit('play', { resumed: previous === 'paused' });
      else if (state === 'paused') this.emit('pause');
      this.emit('state', { state, previous });
    }

    _bindUI() {
      const root = this.root;
      this._listen(root, 'click', (e) => {
        if (e.target.closest('[data-vsl-action], .vsl-fullscreen, .vsl-card')) return;
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
          this._onResumeChoice(btn.getAttribute('data-vsl-action'));
        });
      });
      this._listen(root.querySelector('.vsl-fullscreen'), 'click', (e) => { e.stopPropagation(); this.toggleFullscreen(); });
      this._listen(document, 'fullscreenchange', () => {
        this.emit('fullscreen', { active: document.fullscreenElement === root });
      });
    }

    _onTap() {
      switch (this.state) {
        case 'loading':
        case 'idle':
        case 'autoplaying':
          this._startWithSound();
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
        default:
          break;
      }
    }

    _startWithSound() {
      const saved = this.opts.resume ? this._savedPosition() : 0;
      if (saved >= Math.max(1, this.opts.resumeMin) && !this._resumeAsked) {
        this._resumeAsked = true;
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
      this._setState(v.muted ? 'autoplaying' : 'playing');
      if (promise && promise.catch) {
        promise.catch(() => {
          if (!v.paused || this.state === 'error') return;
          this._setState('idle');
          this.emit('autoplay_blocked');
        });
      }
    }

    // -- elementos da página com delay ---------------------------------------

    _bindElements() {
      const mine = (el) => {
        const owner = el.getAttribute('data-vsl-player');
        return owner ? owner === this.id : this._isFirst;
      };
      const collect = (attr) => Array.from(document.querySelectorAll('[' + attr + ']'))
        .filter(mine)
        .map((el) => ({ el, at: parseTime(el.getAttribute(attr)), done: false }))
        .filter((item) => item.at != null);
      this._showAt = collect('data-vsl-show-at');
      this._hideAt = collect('data-vsl-hide-at');
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
      this._listeners.forEach(([target, type, fn]) => target.removeEventListener(type, fn));
      this._listeners = [];
      if (this.hls) { this.hls.destroy(); this.hls = null; }
      this.video.removeAttribute('src');
      this.video.load();
      this.root.innerHTML = '';
      this.root.removeAttribute('data-vsl-ready');
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
  VSLPlayer.parseTime = parseTime;
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
