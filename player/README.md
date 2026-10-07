# 🎬 VSL Player

Player de vídeo para páginas de vendas (VSL), no estilo VTurb. Dois arquivos, sem dependências, funciona em
qualquer página (HTML puro, WordPress, Elementor, Atomicat, Framer, etc.): basta colar o HTML.

Abra `index.html` para ver a demonstração.

## O que ele faz

| Recurso | Como funciona |
|---|---|
| **Smart autoplay** | O vídeo começa sozinho, mudo, com a mensagem "Seu vídeo já começou · Clique para ouvir" (no celular, "Toque para ouvir"). Ao clicar, volta para o início com som (igual ao VTurb). A mensagem só aparece quando há imagem na tela de verdade; antes disso fica a capa com um spinner. |
| **Capa com play** | Se o aparelho bloquear o autoplay (iPhone em modo de economia de energia, por exemplo) ou se o vídeo não mostrar imagem em 12 s, mostra a capa com um botão de play. O primeiro toque já toca com som. |
| **Barra de progresso inteligente** | Anda rápido no começo e devagar no fim, para o vídeo parecer mais curto. Não dá para clicar nela. |
| **Delay de elementos** | Qualquer elemento da página com `data-vsl-show-at="12:30"` fica escondido até o vídeo chegar nesse tempo. Também há `data-vsl-hide-at`. Ou, sem mexer no HTML do botão, `data-show="#botao-oferta"` no próprio player. Se a pessoa recarregar a página, o elemento continua visível. |
| **Continuar de onde parou** | Quem volta à página vê "Continuar de onde parou? · Você parou em 7:32" com os botões *Continuar* e *Ver do início*. |
| **Sem controles** | Não há linha do tempo, nem botão de avançar. Clique pausa, clique retoma. Velocidade e pulos pelo console ou por extensões são desfeitos. Sem botão de download e sem menu do botão direito. |
| **Pausa com mensagem** | Ao pausar aparece "Continuar assistindo". No fim, "Assistir de novo". |
| **Miniatura de pausa e tela final com botão** | Depois do pitch, a pausa pode mostrar uma imagem com um botão de compra (`data-pause-poster-late`). No fim do vídeo, uma imagem com o botão no lugar do "assistir de novo" (`data-end-poster`). |
| **Pitch** | `data-pitch="12:30"` dispara o evento `pitch` uma vez por visitante quando a oferta começa, com som e com a aba visível. |
| **Vídeo que falha** | Se o vídeo não carregar (link errado, CDN fora, rede caiu), o player tenta de novo sozinho três vezes (1 s, 3 s, 8 s) e só então mostra "O vídeo não carregou" com o botão "Tentar de novo". Nessa hora os elementos com delay são liberados: o botão de compra nunca fica escondido por falha do vídeo. |
| **Velocidade manual** | `data-speed="1.2"` toca o vídeo um pouco mais rápido (até 1.5x), e a trava mantém essa velocidade. |
| **Eventos para pixels** | `play`, `unmute`, `pitch`, `milestone` (10/25/50/75/90/100 %), `cta_click`, `ended`... prontos para o Meta Pixel, GA4, TikTok etc. |
| **Retenção** | Opcionalmente envia para uma URL sua os eventos e os segundos assistidos de cada visitante. A pasta `analytics/` traz um servidor pronto com painel de retenção. |
| **HLS** | Aceita `.m3u8` (nativo no Safari; nos outros navegadores o player baixa o hls.js sozinho). |
| **Celular** | Toca dentro da página (sem abrir o player do sistema), textos e botões escalam com a largura do player. Ignora o segundo toque de quem toca duas vezes seguidas. Botão de tela cheia opcional. |

## Instalação

### Sem hospedar nada (CDN)

Este repositório é público, então o CDN gratuito jsDelivr serve os arquivos direto do GitHub. Cole este
bloco num elemento de **HTML personalizado** da sua página (Atomicat, Elementor, WordPress, Framer...):

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/guilherm817-svg/Claude-Code@f8381a0cab1124a65b2d0b50196784c41ce66235/player/vsl-player.css">
<style>#botao-oferta:not(.vsl-visible){display:none!important}</style>

<div class="vsl-player"
     data-id="vsl-principal"
     data-src="https://seu-cdn.com/vsl.mp4"
     data-poster="https://seu-cdn.com/capa.jpg"
     data-color="#e11d48"
     data-pitch="12:30"
     data-show="#botao-oferta"></div>

<script src="https://cdn.jsdelivr.net/gh/guilherm817-svg/Claude-Code@f8381a0cab1124a65b2d0b50196784c41ce66235/player/vsl-player.js"></script>
<script>setTimeout(function(){if(!window.VSLPlayer)document.querySelectorAll('[data-vsl-show-at],#botao-oferta').forEach(function(e){e.classList.add('vsl-visible')})},10000)</script>
```

É **um `<script>` do player só**: se o vídeo for `.m3u8`, o hls.js é baixado pelo próprio player quando
precisa. `data-show="#botao-oferta"` esconde o botão de compra da página (pelo seletor CSS) até o pitch, sem
precisar editar o HTML do botão. A linha `<style>` esconde esse botão desde a primeira pintura da página: sem
ela, ele fica visível até o script do player chegar e rodar (um piscar do botão na primeira dobra do celular
quando o CDN demora ou a página é pesada). A última linha é a garantia (*fail-open*): se o script do player
não carregar em 10 s, os elementos com delay aparecem mesmo assim; por isso ela repete o seletor do botão.

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
<script>setTimeout(function(){if(!window.VSLPlayer)document.querySelectorAll('[data-vsl-show-at]').forEach(function(e){e.classList.add('vsl-visible')})},10000)</script>
```

O script inicia sozinho todos os `<div class="vsl-player">` da página. Dê um `data-id` fixo a cada player: ele é a
chave usada para lembrar a posição e os elementos já mostrados. Sem `data-id`, o player usa o `id` do `div` ou
um código derivado do endereço do vídeo.

Ao trocar o vídeo de um player, troque também o `data-id` (por exemplo `vsl-v2`): o painel de retenção agrupa as
sessões por esse identificador, e dois vídeos com o mesmo id misturam curva, duração e taxa de pitch.

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
| `data-end-screen` | `replay` | No fim: `replay` (botão de assistir de novo), `poster` (capa + botão) ou `none`. Com `data-end-poster`, vira a tela final com botão (abaixo). |
| `data-lock-speed` | `true` | Desfaz mudanças de velocidade. |
| `data-lock-seek` | `true` | Desfaz pulos no vídeo. |
| `data-speed` | `1` | Velocidade de reprodução, de `1` a `1.5` (Turbo manual). A trava de velocidade mantém esse valor. |
| `data-fullscreen` | `false` | Botão de tela cheia no canto. |
| `data-pitch` | | Tempo da oferta (`750`, `12:30` ou `12m30s`). Dispara o evento `pitch` uma vez por visitante, com som e aba visível. |
| `data-show` | | Seletores CSS (`#botao-oferta, .oferta`) de elementos da página que ficam escondidos até `data-show-at`. Os elementos são tratados como se tivessem `data-vsl-show-at`. |
| `data-show-at` | = `data-pitch` | Tempo em que os elementos de `data-show` aparecem (`12:30`). Sem ele, usa o pitch. |
| `data-pause-poster-late` | | Imagem mostrada ao pausar **depois do pitch** (miniatura de pausa). Sem `data-pitch`, em qualquer pausa. |
| `data-pause-cta-text` | | Texto do botão sobre a miniatura de pausa. |
| `data-pause-cta-link` | | Link do botão. Sem link, não há botão (só a imagem). |
| `data-pause-cta-pos` | `bottom-center` | Posição do botão: `top-left`, `top-center`, `top-right`, `center-left`, `center`, `center-right`, `bottom-left`, `bottom-center`, `bottom-right`. |
| `data-end-poster` | | Imagem da tela final. Com ela, o fim mostra a imagem e o botão no lugar do "assistir de novo" (toque fora do botão reinicia). |
| `data-end-cta-text` | | Texto do botão da tela final. |
| `data-end-cta-link` | | Link do botão da tela final. |
| `data-end-cta-pos` | `bottom-center` | Posição do botão da tela final (mesmos valores acima). |
| `data-preload` | `auto` | `auto`, `metadata` ou `none`. |
| `data-fallback` | | MP4 usado se o navegador não tocar o `.m3u8` ou se o hls.js não baixar em 8 s. |
| `data-hls-url` | jsDelivr, `hls.js@1.5.20` light | De onde baixar o hls.js quando o vídeo é `.m3u8` e a página não o carregou antes. |
| `data-analytics` | | URL que recebe os eventos e a retenção (veja abaixo). |
| `data-analytics-interval` | `15` | Segundos entre os envios enquanto o vídeo toca com som (depois de 5 min com som, passa a 60 s). |
| `data-review-key` | | Chave do modo de revisão: abrindo a página com `?revisar=CHAVE`, aparece uma barra para acelerar (até 3x) e pular para um minuto. Só para você conferir a página; o visitante continua sem controles. |

### Textos

Todos sem ponto final e sobrescrevíveis pelo `data-*`. Em telas de toque (celular, sem mouse), "Clique" vira
"Toque" nos padrões; o que você escrever no `data-*` vale nos dois casos.

| Atributo | Padrão | No celular |
|---|---|---|
| `data-unmute-title` | Seu vídeo já começou | |
| `data-unmute-subtitle` | Clique para ouvir | Toque para ouvir |
| `data-play-text` | Clique para assistir | Toque para assistir |
| `data-pause-text` | Continuar assistindo | Toque para continuar |
| `data-replay-text` | Assistir de novo | |
| `data-resume-title` | Continuar de onde parou? | |
| `data-resume-subtitle` | Você parou em {time} | |
| `data-resume-continue` | Continuar | |
| `data-resume-restart` | Ver do início | |
| `data-error-text` | O vídeo não carregou | |
| `data-retry-text` | Tentar de novo | |

Em `data-resume-subtitle`, `{time}` vira o tempo em que a pessoa parou (`7:32` ou `1:07:32`).

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
  carregar, ficam escondidos: por isso o bloco de instalação traz a linha de garantia (*fail-open*) que os
  mostra depois de 10 s sem o player. Se o vídeo falhar (estado `error`), o player também libera todos.
- O tempo conta mesmo com o vídeo mudo (autoplay), igual ao VTurb.

### Pelo seletor, sem mexer no botão (`data-show`)

Em construtores onde o botão de compra é um bloco pronto e não dá para acrescentar atributos nele (Atomicat,
por exemplo), aponte o seletor no próprio player:

```html
<div class="vsl-player" data-src="..." data-pitch="12:30" data-show="#botao-oferta, .selo-garantia"></div>
```

Os elementos casados viram `data-vsl-show-at` com o tempo de `data-show-at` (ou do pitch, se omitido) e
seguem as mesmas regras: escondidos até o tempo, visíveis ao recarregar, liberados em caso de erro.

Uma diferença importante: o `data-show` só age quando o script do player roda. Até lá o elemento fica
**visível** (já com `data-vsl-show-at` no próprio elemento, o CSS do player o esconde desde a primeira
pintura). Em páginas pesadas, ou com o script vindo devagar do CDN, o botão de compra aparece e some logo
depois: um piscar na primeira dobra do celular. Para evitar:

- Se o construtor deixa editar os atributos do elemento, prefira `data-vsl-show-at="12:30"` nele mesmo.
- Com `data-show`, acrescente um `<style>` com o mesmo seletor antes do player e repita o seletor na linha
  de garantia (*fail-open*), para o botão aparecer mesmo se o script não carregar:

```html
<style>#botao-oferta:not(.vsl-visible){display:none!important}</style>
<div class="vsl-player" data-src="..." data-pitch="12:30" data-show="#botao-oferta"></div>
<script src="vsl-player.js"></script>
<script>setTimeout(function(){if(!window.VSLPlayer)document.querySelectorAll('[data-vsl-show-at],#botao-oferta').forEach(function(e){e.classList.add('vsl-visible')})},10000)</script>
```

  O player acrescenta a classe `vsl-visible` quando chega a hora (ou ao falhar), e o `<style>` deixa de valer.
  O atributo `hidden` no elemento também funciona (o player o remove ao liberar), mas só se o CSS da página
  não definir `display` para esse elemento, o que é comum em botões de construtores; o `<style>` acima vale
  em qualquer caso.

## Miniatura de pausa e tela final com botão

Depois do pitch, quem pausa já viu a oferta: a pausa pode virar uma imagem com o botão de compra. E no fim
do vídeo, em vez do "assistir de novo", uma imagem com o botão:

```html
<div class="vsl-player" data-src="..." data-pitch="12:30"
     data-pause-poster-late="https://seu-cdn.com/pausa.jpg"
     data-pause-cta-text="QUERO GARANTIR MINHA VAGA" data-pause-cta-link="https://pay.exemplo.com/..." data-pause-cta-pos="bottom-center"
     data-end-poster="https://seu-cdn.com/fim.jpg"
     data-end-cta-text="GARANTIR AGORA" data-end-cta-link="https://pay.exemplo.com/..." data-end-cta-pos="center"></div>
```

- A miniatura de pausa só aparece com `currentTime >= pitch`; antes do pitch a pausa é a de sempre.
- O clique no botão segue o link (`target="_top"`) sem pausar nem reiniciar, dispara `cta_click`
  `{ where: 'pause' | 'end', link }` e manda o evento para o analytics na hora.
- Tocar fora do botão continua retomando (na pausa) ou reiniciando (no fim).

## Eventos

Use `VSLPlayer.on(nome, função)` para qualquer player da página, ou `player.on(nome, função)` para um só.
Cada player também dispara um evento DOM `vsl:<nome>` no próprio `div` (com `bubbles`), e `detail` traz os dados.

| Evento | Quando | Dados |
|---|---|---|
| `ready` | metadados carregados | `duration` |
| `autoplay` | começou mudo (com imagem na tela) | |
| `autoplay_blocked` | o aparelho não deixou começar, ou 12 s sem imagem; capa com play | `reason` (`no-frame` no segundo caso) |
| `unmute` | primeira vez com som na visita (o "play" de verdade) | `time` |
| `play` | começou ou retomou com som | `resumed` |
| `pause` | pausou | |
| `progress` | várias vezes por segundo | `time`, `duration`, `percent` |
| `milestone` | passou de 10, 25, 50, 75, 90 e 100 % | `percent` |
| `pitch` | chegou em `data-pitch` com som e aba visível (uma vez por visitante) | `at`, `time`, `muted: false` |
| `reach` | mostrou ou escondeu um elemento com delay | `at`, `action`, `element`, `persisted` |
| `resume_prompt` | perguntou se quer continuar | `time` |
| `resume_continue` / `resume_restart` | resposta à pergunta | `time` |
| `cta_click` | clique no botão da miniatura de pausa ou da tela final | `where` (`pause` ou `end`), `link` |
| `ended` | terminou | |
| `replay` | assistiu de novo | |
| `seek_blocked` | alguém tentou pular | `attempted`, `time` |
| `fullscreen` | entrou ou saiu da tela cheia | `active` |
| `error` | o vídeo não carregou, mesmo depois das três retentativas | `code`, `attempt` |

Se o tempo do pitch passar com o vídeo mudo, o `pitch` **não** é marcado como feito: ele dispara na primeira
vez que a pessoa estiver com som e com a aba visível a partir desse tempo. `reach`, `milestone` e os elementos
com delay continuam contando por tempo, mudo ou não.

Exemplos com pixels:

```html
<script>
  // Meta Pixel
  VSLPlayer.on('unmute', () => fbq('trackCustom', 'VSL_Play'));
  VSLPlayer.on('pitch',  () => fbq('trackCustom', 'VSL_Pitch'));
  VSLPlayer.on('cta_click', () => fbq('trackCustom', 'VSL_Clique'));
  VSLPlayer.on('ended',  () => fbq('trackCustom', 'VSL_Fim'));

  // GA4
  VSLPlayer.on('milestone', ({ percent, id }) => gtag('event', 'video_progress', { video: id, percent }));

  // Qualquer coisa sua: liberar um formulário, mudar o título, etc.
  VSLPlayer.on('reach', ({ element }) => element.scrollIntoView({ behavior: 'smooth', block: 'center' }));
</script>
```

## Retenção e analytics

Informe `data-analytics="https://seu-servidor.com/vsl"` e o player envia um `POST` (via `sendBeacon`, com
`fetch` como reserva). O corpo é JSON, enviado como `text/plain` para não exigir preflight de CORS:

```json
{
  "v": "1.1.0",
  "player": "vsl-principal",
  "visitor": "6f1c...-...",          
  "session": "0b7e...-...",          
  "url": "https://seusite.com/vsl?utm_source=meta",
  "referrer": "https://l.facebook.com/",
  "duration": 1830.5,
  "maxTime": 772.3,
  "reached": 772.3,
  "unmuted": true,
  "muted": false,
  "pitch": 750,
  "watched": [[0, 120], [300, 772]],
  "events": [
    { "type": "unmute", "ts": 1760000000000, "time": 0, "seq": 0 },
    { "type": "milestone", "ts": 1760000183000, "time": 183.1, "seq": 1, "percent": 10 },
    { "type": "pitch", "ts": 1760000750000, "time": 750.0, "seq": 2, "at": 750, "muted": false }
  ],
  "sentAt": 1760000800000
}
```

Quando os envios acontecem:

- **Sessão muda** (a pessoa nunca ligou o som): um único envio logo que o vídeo carrega, e depois só ao sair
  da página ou trocar de aba. Marcos e `reached` vão acumulando e saem juntos no `unmute` ou na saída.
- **Com som:** a cada `data-analytics-interval` segundos (15 por padrão); depois de 5 minutos com som, a cada
  60 s. `unmute`, `pitch`, `cta_click`, `ended` e `error` saem na hora.

Campos:

- `visitor` fica no localStorage e repete entre visitas; `session` muda a cada carregamento de cada player.
- `muted` diz se a sessão ainda está muda (nunca ligou o som); `unmuted` é o contrário.
- Em cada evento, `ts` é o horário (ms), `time` o segundo do vídeo em que aconteceu e `seq` um contador que
  distingue eventos emitidos no mesmo milissegundo.
- `watched` são as faixas de segundos assistidos **com som**, acumuladas na sessão: a cada envio vem a lista
  completa, então o servidor deve substituir a anterior (ou unir), não somar. `maxTime` é até onde esta sessão
  chegou com som; `reached` é o maior tempo já alcançado por esse navegador entre visitas, contando o autoplay
  mudo (é o que libera os elementos com delay).
- Com isso dá para montar a curva de retenção (quantos visitantes viram cada segundo), a taxa de play
  (`unmute` ÷ sessões), quantos chegaram ao pitch e quantos clicaram no botão.

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
player.retry();           // tenta carregar o vídeo de novo (o mesmo que o botão "Tentar de novo")
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

## Carregamento rápido

O vídeo começa a baixar no instante em que a página abre (`preload="auto"` e autoplay mudo), então quando o
visitante olha, já está tocando. Além disso:

- o player abre a conexão com a CDN do vídeo antes do primeiro byte (`preconnect`);
- com HLS, começa pela qualidade mais leve para o primeiro quadro aparecer na hora e, assim que lê o
  manifesto, escolhe o nível mais perto de 480p (o menor lado, para vídeo vertical), subindo conforme a
  conexão permite, sem baixar 1080p para um player pequeno no celular;
- para MP4, exporte com `faststart` (veja abaixo) para não precisar baixar o arquivo inteiro antes de começar.

Para ganhar mais alguns décimos de segundo, coloque o bloco do player no começo da página e, se o vídeo
estiver em outro domínio, adicione antes dele: `<link rel="preconnect" href="https://sua-cdn.com">`.

## HLS (`.m3u8`)

O Safari toca HLS sozinho. Nos outros navegadores o player baixa o [hls.js](https://github.com/video-dev/hls.js)
por conta própria (uma vez por página, compartilhado entre os players) quando encontra um `.m3u8`:

```html
<div class="vsl-player" data-src="https://seu-cdn.com/vsl/playlist.m3u8" data-fallback="https://seu-cdn.com/vsl.mp4"></div>
<script src="vsl-player.js"></script>
```

- `data-hls-url` troca o endereço de onde o hls.js é baixado (padrão: jsDelivr, `hls.js@1.5.20`, versão light).
- Se o hls.js não chegar em 8 s, o player usa o `data-fallback` (MP4). Sem fallback, entra no caminho de erro
  com retentativas (`code: 'hls-load'`).
- Se quiser, carregue o hls.js antes do player (`<script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>`);
  ele é usado e nada é baixado de novo.
- Em erro fatal do HLS o player se recupera sozinho: `startLoad()` para erro de rede, `recoverMediaError()`
  para erro de mídia e, como último recurso, recria a instância.

## Onde hospedar o vídeo

Qualquer hospedagem que sirva o arquivo direto por HTTPS com suporte a *range requests* (padrão em
Bunny Storage/Stream, Cloudflare R2/Stream, Amazon S3 + CloudFront, Backblaze B2, Vimeo com link direto etc.).
Links do YouTube, Google Drive e Dropbox não funcionam. Para VSLs longas, prefira HLS: começa mais rápido e
adapta a qualidade à conexão. Sem *range requests* o navegador também não consegue voltar à posição depois
de uma retentativa (o vídeo recomeça do zero); a posição salva não se perde, e o "continuar de onde parou"
ao voltar à página continua certo.

Exporte o MP4 com `faststart` (os metadados no início do arquivo) para o vídeo começar antes de baixar tudo:
`ffmpeg -i entrada.mp4 -c copy -movflags +faststart vsl.mp4`.

## Perguntas frequentes

**O vídeo não começa sozinho no iPhone.** Em modo de economia de energia (e em algumas configurações) o iOS
bloqueia até o autoplay mudo. O player percebe e mostra a capa com o botão de play; o primeiro toque já toca
com som.

**Apareceu "O vídeo não carregou".** O player já tentou três vezes (1 s, 3 s e 8 s depois da falha) antes de
mostrar isso; o visitante pode tocar em "Tentar de novo" (ou em qualquer ponto do player). Confira o endereço
em `data-src` e se a CDN responde a *range requests*. Enquanto o erro estiver na tela, os elementos com delay
ficam visíveis, para o botão de compra não sumir junto.

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
elementos com delay (ou `data-show` em cada player).

## Testes

A pasta `testes/` tem um teste automatizado que abre o player em um Chromium de verdade (Playwright) e
confere autoplay, clique para ouvir, pausa, delay de elementos (`data-vsl-show-at` e `data-show`), retomada,
fim do vídeo, travas de velocidade e de pulo, `data-speed`, autoplay bloqueado, vídeo 404 com retentativas e
botão "Tentar de novo", carregamento lento e watchdog, pitch com som e aba visível, analytics (sessão muda e
com som), toques no celular, miniatura de pausa, tela final com botão, HLS (com um `window.Hls` falso, já
que o teste roda sem internet), erro no meio de uma sessão com som (a posição sobrevive à retentativa e ao
"Tentar de novo", com e sem *range requests*; rede presa vira "toque para continuar") e erro com o visitante
pausado ou no "continuar de onde parou?" (a retentativa não retoma sozinha e a miniatura de pausa fica).
Precisa de Node 18+, ffmpeg e Playwright:

```bash
cd player/testes
npm install playwright && npx playwright install chromium
node run.js
```
