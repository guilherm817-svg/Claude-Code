# 🎬 VSL Player

Player de vídeo para páginas de vendas (VSL), no estilo VTurb. Dois arquivos, sem dependências, funciona em
qualquer página (HTML puro, WordPress, Elementor, Atomicat, Framer, etc.): basta colar o HTML.

Abra `index.html` para ver a demonstração.

## O que ele faz

| Recurso | Como funciona |
|---|---|
| **Smart autoplay** | O vídeo começa sozinho, mudo, com a mensagem "Seu vídeo já começou · Clique para ouvir". Ao clicar, volta para o início com som (igual ao VTurb). |
| **Capa com play** | Se o aparelho bloquear o autoplay (iPhone em modo de economia de energia, por exemplo), mostra a capa com um botão de play. |
| **Barra de progresso inteligente** | Anda rápido no começo e devagar no fim, para o vídeo parecer mais curto. Não dá para clicar nela. |
| **Delay de elementos** | Qualquer elemento da página com `data-vsl-show-at="12:30"` fica escondido até o vídeo chegar nesse tempo. Também há `data-vsl-hide-at`. Se a pessoa recarregar a página, o elemento continua visível. |
| **Continuar de onde parou** | Quem volta à página vê "Você já começou a assistir este vídeo. Quer continuar de onde parou?" com os botões *Continuar* e *Começar do início*. |
| **Sem controles** | Não há linha do tempo, nem botão de avançar. Clique pausa, clique retoma. Velocidade e pulos pelo console ou por extensões são desfeitos. Sem botão de download e sem menu do botão direito. |
| **Pausa com mensagem** | Ao pausar aparece "Clique para continuar assistindo". No fim, "Assistir novamente". |
| **Pitch** | `data-pitch="12:30"` dispara o evento `pitch` uma vez por visitante quando a oferta começa. |
| **Eventos para pixels** | `play`, `unmute`, `pitch`, `milestone` (10/25/50/75/90/100 %), `ended`... prontos para o Meta Pixel, GA4, TikTok etc. |
| **Retenção** | Opcionalmente envia para uma URL sua os eventos e os segundos assistidos de cada visitante. A pasta `analytics/` traz um servidor pronto com painel de retenção. |
| **HLS** | Aceita `.m3u8` (nativo no Safari; nos outros navegadores com o hls.js). |
| **Celular** | Toca dentro da página (sem abrir o player do sistema), textos e botões escalam com a largura do player. Botão de tela cheia opcional. |

## Instalação

### Sem hospedar nada (CDN)

Este repositório é público, então o CDN gratuito jsDelivr serve os arquivos direto do GitHub. Cole este
bloco num elemento de **HTML personalizado** da sua página (Atomicat, Elementor, WordPress, Framer...):

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/guilherm817-svg/Claude-Code@f8381a0cab1124a65b2d0b50196784c41ce66235/player/vsl-player.css">

<div class="vsl-player"
     data-id="vsl-principal"
     data-src="https://seu-cdn.com/vsl.mp4"
     data-poster="https://seu-cdn.com/capa.jpg"
     data-color="#e11d48"
     data-pitch="12:30"></div>

<script src="https://cdn.jsdelivr.net/gh/guilherm817-svg/Claude-Code@f8381a0cab1124a65b2d0b50196784c41ce66235/player/vsl-player.js"></script>
```

O endereço está preso a uma versão específica (o código depois do `@`), então ele nunca muda debaixo de você.
Para pegar uma versão nova, troque esse código pelo da versão desejada.

### Com os arquivos no seu site

Copie `vsl-player.js` e `vsl-player.css` para o seu site e cole na página:

```html
<link rel="stylesheet" href="vsl-player.css">

<div class="vsl-player"
     data-id="vsl-principal"
     data-src="https://seu-cdn.com/vsl.mp4"
     data-poster="https://seu-cdn.com/capa.jpg"
     data-color="#e11d48"
     data-pitch="12:30"></div>

<!-- aparece quando o vídeo chega em 12:30 -->
<a class="botao-comprar" data-vsl-show-at="12:30" href="https://pay.exemplo.com/...">COMPRAR AGORA</a>

<script src="vsl-player.js"></script>
```

O script inicia sozinho todos os `<div class="vsl-player">` da página. Dê um `data-id` fixo a cada player: ele é a
chave usada para lembrar a posição e os elementos já mostrados. Sem `data-id`, o player usa o `id` do `div` ou
um código derivado do endereço do vídeo.

Em construtores de página (Elementor, Atomicat, WordPress...), use o bloco de "HTML personalizado" e cole o
mesmo trecho. O CSS e o JS podem ficar hospedados no seu domínio ou em um CDN.

## Opções

Todas vão como `data-...` no `div` (ou como objeto em `VSLPlayer.create(el, { ... })`).

| Atributo | Padrão | Para quê |
|---|---|---|
| `data-src` | | MP4 ou `.m3u8`. Obrigatório. |
| `data-poster` | | Imagem de capa. |
| `data-id` | | Identificador do player (chave do localStorage e dos eventos). |
| `data-color` | `#e11d48` | Cor da barra de progresso, dos ícones e dos botões. |
| `data-aspect` | `auto` | Proporção enquanto o vídeo carrega: `16:9`, `9:16`, `4:3`, `1:1`. Com `auto`, usa a do vídeo. |
| `data-autoplay` | `true` | Smart autoplay (mudo, pedindo o clique). `false` mostra a capa com o play. |
| `data-unmute-restart` | `true` | Ao clicar para ouvir, voltar para o início. `false` continua de onde está, só ligando o som. |
| `data-resume` | `true` | Oferecer "continuar de onde parou". |
| `data-resume-min` | `10` | Só oferece retomar se a pessoa assistiu mais que X segundos (com som). |
| `data-progress` | `smart` | `smart` (inteligente), `real` ou `none`. |
| `data-progress-intensity` | `2.2` | Quanto maior, mais rápido a barra anda no começo. `1` é igual à real. |
| `data-pause-overlay` | `true` | Mensagem ao pausar. |
| `data-end-screen` | `replay` | No fim: `replay` (botão de assistir de novo), `poster` (capa + botão) ou `none`. |
| `data-lock-speed` | `true` | Desfaz mudanças de velocidade. |
| `data-lock-seek` | `true` | Desfaz pulos no vídeo. |
| `data-fullscreen` | `false` | Botão de tela cheia no canto. |
| `data-pitch` | | Tempo da oferta (`750`, `12:30` ou `12m30s`). Dispara o evento `pitch` uma vez por visitante. |
| `data-preload` | `auto` | `auto`, `metadata` ou `none`. |
| `data-fallback` | | MP4 usado se o navegador não tocar o `.m3u8`. |
| `data-analytics` | | URL que recebe os eventos e a retenção (veja abaixo). |
| `data-analytics-interval` | `15` | Segundos entre os envios. |

### Textos

| Atributo | Padrão |
|---|---|
| `data-unmute-title` | Seu vídeo já começou |
| `data-unmute-subtitle` | Clique para ouvir |
| `data-play-text` | Clique para assistir |
| `data-pause-text` | Clique para continuar assistindo |
| `data-replay-text` | Assistir novamente |
| `data-resume-title` | Você já começou a assistir este vídeo |
| `data-resume-subtitle` | Quer continuar de onde parou? |
| `data-resume-continue` | Continuar de onde parei |
| `data-resume-restart` | Começar do início |
| `data-error-text` | Não foi possível carregar o vídeo. |

### Aparência

Além de `data-color`, o CSS usa variáveis que você pode sobrescrever:

```css
.vsl-player {
  --vsl-radius: 12px;             /* cantos arredondados */
  --vsl-progress-height: 6px;     /* altura da barra */
  --vsl-overlay: rgba(0,0,0,.45); /* escurecimento do vídeo sob as mensagens */
  --vsl-box-bg: rgba(0,0,0,.72);  /* fundo da caixa de mensagem */
  --vsl-font: inherit;            /* fonte dos textos */
}
```

## Elementos com delay

```html
<p data-vsl-hide-at="12:30">🔒 O botão de compra aparece ao final da apresentação.</p>

<div data-vsl-show-at="12:30">
  <a href="...">QUERO GARANTIR MINHA VAGA</a>
</div>
```

- O tempo aceita `750`, `12:30`, `1:02:30` ou `12m30s`.
- O player guarda o maior tempo que o visitante já alcançou. Ao recarregar a página, os elementos já
  alcançados aparecem de imediato (mesmo que o vídeo recomece).
- Com mais de um player na página, indique a quem o elemento pertence: `data-vsl-player="vsl-principal"`.
  Sem isso, os elementos seguem o primeiro player da página.
- Os elementos ficam escondidos pelo CSS (`display: none`) até o player liberar. Se o JavaScript não
  carregar, ficam escondidos. Se preferir um botão sempre visível como garantia, coloque-o fora do delay.
- O tempo conta mesmo com o vídeo mudo (autoplay), igual ao VTurb.

## Eventos

Use `VSLPlayer.on(nome, função)` para qualquer player da página, ou `player.on(nome, função)` para um só.
Cada player também dispara um evento DOM `vsl:<nome>` no próprio `div` (com `bubbles`), e `detail` traz os dados.

| Evento | Quando | Dados |
|---|---|---|
| `ready` | metadados carregados | `duration` |
| `autoplay` | começou mudo | |
| `autoplay_blocked` | o aparelho não deixou começar; capa com play | |
| `unmute` | primeira vez com som na visita (o "play" de verdade) | `time` |
| `play` | começou ou retomou com som | `resumed` |
| `pause` | pausou | |
| `progress` | várias vezes por segundo | `time`, `duration`, `percent` |
| `milestone` | passou de 10, 25, 50, 75, 90 e 100 % | `percent` |
| `pitch` | chegou em `data-pitch` (uma vez por visitante) | `at` |
| `reach` | mostrou ou escondeu um elemento com delay | `at`, `action`, `element`, `persisted` |
| `resume_prompt` | perguntou se quer continuar | `time` |
| `resume_continue` / `resume_restart` | resposta à pergunta | `time` |
| `ended` | terminou | |
| `replay` | assistiu de novo | |
| `seek_blocked` | alguém tentou pular | `attempted`, `time` |
| `fullscreen` | entrou ou saiu da tela cheia | `active` |
| `error` | o vídeo não carregou | `code` |

Exemplos com pixels:

```html
<script>
  // Meta Pixel
  VSLPlayer.on('unmute', () => fbq('trackCustom', 'VSL_Play'));
  VSLPlayer.on('pitch',  () => fbq('trackCustom', 'VSL_Pitch'));
  VSLPlayer.on('ended',  () => fbq('trackCustom', 'VSL_Fim'));

  // GA4
  VSLPlayer.on('milestone', ({ percent, id }) => gtag('event', 'video_progress', { video: id, percent }));

  // Qualquer coisa sua: liberar um formulário, mudar o título, etc.
  VSLPlayer.on('reach', ({ element }) => element.scrollIntoView({ behavior: 'smooth', block: 'center' }));
</script>
```

## Retenção e analytics

Informe `data-analytics="https://seu-servidor.com/vsl"` e o player envia um `POST` (via `sendBeacon`, com
`fetch` como reserva) a cada 15 segundos, ao sair da página e em eventos importantes. O corpo é JSON, enviado
como `text/plain` para não exigir preflight de CORS:

```json
{
  "v": "1.0.0",
  "player": "vsl-principal",
  "visitor": "6f1c...-...",          
  "session": "0b7e...-...",          
  "url": "https://seusite.com/vsl?utm_source=meta",
  "referrer": "https://l.facebook.com/",
  "duration": 1830.5,
  "maxTime": 772.3,
  "reached": 772.3,
  "unmuted": true,
  "pitch": 750,
  "watched": [[0, 120], [300, 772]],
  "events": [
    { "type": "unmute", "ts": 1760000000000, "time": 0, "seq": 0 },
    { "type": "milestone", "ts": 1760000183000, "time": 183.1, "seq": 1, "percent": 10 },
    { "type": "pitch", "ts": 1760000750000, "time": 750.0, "seq": 2, "at": 750 }
  ],
  "sentAt": 1760000800000
}
```

- `visitor` fica no localStorage e repete entre visitas; `session` muda a cada carregamento de cada player.
- Em cada evento, `ts` é o horário (ms), `time` o segundo do vídeo em que aconteceu e `seq` um contador que
  distingue eventos emitidos no mesmo milissegundo.
- `watched` são as faixas de segundos assistidos **com som**, acumuladas na sessão: a cada envio vem a lista
  completa, então o servidor deve substituir a anterior (ou unir), não somar. `maxTime` é até onde esta sessão
  chegou com som; `reached` é o maior tempo já alcançado por esse navegador entre visitas, contando o autoplay
  mudo (é o que libera os elementos com delay).
- Com isso dá para montar a curva de retenção (quantos visitantes viram cada segundo), a taxa de play
  (`unmute` ÷ sessões) e quantos chegaram ao pitch.

**Já vem um servidor pronto:** a pasta [`analytics/`](analytics/README.md) tem um servidor em Python (só
biblioteca padrão + SQLite) que recebe esses envios e mostra o painel com curva de retenção, taxa de play,
chegada ao pitch, origens e dispositivos:

```bash
python player/analytics/servidor.py --porta 8080 --token um-segredo
```

Sem servidor próprio, use a versão para Cloudflare em [`analytics/cloudflare/`](analytics/cloudflare/README.md):
um clique no botão "Deploy to Cloudflare" e o painel fica no ar de graça, com HTTPS.

Se preferir o seu próprio backend, qualquer rota que aceite `POST` serve: leia o corpo como JSON (mesmo com
`Content-Type: text/plain`), grave por (`player`, `visitor`, `session`) e responda com
`Access-Control-Allow-Origin` para o domínio da página.

## API em JavaScript

```js
const player = VSLPlayer.get('vsl-principal');      // ou VSLPlayer.create('#meu-div', { src: '...', ... })

player.play();            // toca (com som, se já tiver sido liberado)
player.pause();
player.unmute();          // mesmo que o clique em "clique para ouvir"
player.restart();         // do início, com som
player.seek('5:00');      // pula (só pelo seu código; o visitante não consegue)
player.toggleFullscreen();
player.refreshElements(); // reencontra os elementos com delay (páginas que montam o HTML depois)
player.forget();          // apaga posição, tempo alcançado e pitch deste visitante
player.destroy();

player.currentTime; player.duration; player.percent; player.paused; player.muted;
player.state;   // loading | idle | autoplaying | playing | paused | modal | ended | error
player.unmuted; // já tocou com som nesta visita
player.reached; // maior tempo já alcançado, entre visitas

player.on('milestone', ({ percent }) => ...);
VSLPlayer.instances;     // todos os players da página
VSLPlayer.init();        // inicia divs adicionados depois do carregamento
```

## HLS (`.m3u8`)

O Safari toca HLS sozinho. Para os outros navegadores inclua o [hls.js](https://github.com/video-dev/hls.js)
antes do player; ele é usado automaticamente:

```html
<script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>
<div class="vsl-player" data-src="https://seu-cdn.com/vsl/playlist.m3u8" data-fallback="https://seu-cdn.com/vsl.mp4"></div>
<script src="vsl-player.js"></script>
```

## Onde hospedar o vídeo

Qualquer hospedagem que sirva o arquivo direto por HTTPS com suporte a *range requests* (padrão em
Bunny Storage/Stream, Cloudflare R2/Stream, Amazon S3 + CloudFront, Backblaze B2, Vimeo com link direto etc.).
Links do YouTube, Google Drive e Dropbox não funcionam. Para VSLs longas, prefira HLS: começa mais rápido e
adapta a qualidade à conexão.

Exporte o MP4 com `faststart` (os metadados no início do arquivo) para o vídeo começar antes de baixar tudo:
`ffmpeg -i entrada.mp4 -c copy -movflags +faststart vsl.mp4`.

## Perguntas frequentes

**O vídeo não começa sozinho no iPhone.** Em modo de economia de energia (e em algumas configurações) o iOS
bloqueia até o autoplay mudo. O player percebe e mostra a capa com o botão de play; o primeiro toque já toca
com som.

**O botão de compra apareceu antes da hora.** O player lembra o maior tempo que aquele navegador já alcançou.
Para testar de novo, clique em *Esquecer este visitante* na demonstração ou rode `VSLPlayer.get('id').forget()`
no console.

**Dá para impedir totalmente que pulem o vídeo?** Não há controles e as tentativas pelo console ou por
extensões são desfeitas, mas quem tem acesso ao endereço do vídeo pode abri-lo direto. Isso vale para o VTurb
também; para proteção de verdade, use HLS com token de acesso na sua CDN.

**O que fica salvo no navegador do visitante?** Em `localStorage`: a posição (`vsl:<id>:pos`), o maior tempo
alcançado (`vsl:<id>:reached`), se já viu o pitch (`vsl:<id>:pitch`) e, com analytics ligado, o identificador
do visitante (`vsl:visitor`). Nada é enviado a lugar nenhum sem `data-analytics`.

**Quero dois players na mesma página.** Dê um `data-id` diferente para cada um e use `data-vsl-player` nos
elementos com delay.

## Testes

A pasta `testes/` tem um teste automatizado que abre o player em um Chromium de verdade (Playwright) e
confere autoplay, clique para ouvir, pausa, delay de elementos, retomada, fim do vídeo, travas de
velocidade e de pulo, autoplay bloqueado, analytics e celular. Precisa de Node 18+, ffmpeg e Playwright:

```bash
cd player/testes
npm install playwright && npx playwright install chromium
node run.js
```
