# 📊 Analytics do VSL Player

Servidor que recebe os envios do `data-analytics` do player, guarda tudo num arquivo SQLite e mostra um painel
com curva de retenção, taxa de play, chegada ao pitch, origens e dispositivos. Só Python 3.10+ e biblioteca
padrão: nada para instalar.

## Rodando

```bash
python player/analytics/servidor.py --porta 8080 --token um-segredo
```

- Envios chegam em `http://localhost:8080/vsl`.
- O painel abre em `http://localhost:8080/?token=um-segredo`.
- Os dados ficam em `player/analytics/dados.sqlite` (mude com `--dados`).
- Sem `--token`, o painel fica aberto para quem acessar a porta. Defina um antes de publicar.
- Também aceita as variáveis `VSL_ANALYTICS_PORTA`, `VSL_ANALYTICS_DADOS` e `VSL_ANALYTICS_TOKEN`.

No player, aponte para o endereço do servidor:

```html
<div class="vsl-player" data-src="https://seu-cdn.com/vsl.mp4" data-pitch="12:30"
     data-analytics="https://analytics.seusite.com/vsl"></div>
```

### Publicando na internet

A página de vendas é HTTPS, então o endereço do `data-analytics` também precisa ser HTTPS (o navegador bloqueia
envios para HTTP a partir de páginas HTTPS). O jeito mais simples é um servidor pequeno (uma VPS de entrada
basta) com o [Caddy](https://caddyserver.com) na frente, que cuida do certificado sozinho:

```bash
# no servidor
python3 player/analytics/servidor.py --porta 8080 --token um-segredo &
caddy reverse-proxy --from analytics.seusite.com --to localhost:8080
```

Depois aponte o DNS de `analytics.seusite.com` para o servidor. Para manter o processo vivo, use `systemd`,
`pm2` ou similar.

## O que o painel mostra

| Número | Como é calculado |
|---|---|
| **Visualizações da página** | sessões, isto é, carregamentos da página com o player (cada aba aberta é uma). Também mostra visitantes únicos (pelo identificador salvo no navegador). |
| **Plays** | sessões em que a pessoa clicou para ouvir (evento `unmute`). A taxa de play é plays ÷ visualizações. |
| **Chegaram ao pitch** | plays que passaram do tempo definido em `data-pitch`. O tempo vem do próprio player; dá para forçar outro com `?pitch=750` na API. |
| **Terminaram o vídeo** | plays que receberam o evento `ended`. |
| **Tempo médio assistido** | média (e mediana) dos segundos assistidos por play, contando cada segundo uma só vez. |
| **Curva de retenção** | para cada segundo do vídeo, a porcentagem dos plays que o assistiu. Vídeos longos são compactados em até 1.200 pontos. |
| **Por dia** | visualizações e plays por dia da primeira chegada da sessão, no fuso do servidor. |
| **Origens** | `utm_source` da URL da página ou, se não houver, o site de onde a pessoa veio (facebook, instagram, google, tiktok...). |
| **Dispositivos** | celular ou computador, pelo `User-Agent`. |
| **Eventos** | contagem de todos os eventos recebidos, inclusive os seus: `VSLPlayer.get('id').emit('cta_click')` registra cliques no botão, por exemplo. |

Os segundos assistidos contam também o trecho visto no mudo (autoplay). As sessões que nunca clicaram para
ouvir aparecem em *Visualizações*, mas ficam fora dos plays, da retenção e dos tempos.

## API

Todas as rotas abaixo pedem o token (`?token=` ou cabeçalho `X-Token`), menos `/vsl`, `/saude` e `/api/config`.

| Rota | Para quê |
|---|---|
| `POST /vsl` | recebe o envio do player (JSON, mesmo com `Content-Type: text/plain`). Responde `204` com CORS liberado. |
| `GET /` | o painel. |
| `GET /api/resumo?player=&de=AAAA-MM-DD&ate=AAAA-MM-DD&pitch=` | todos os números do painel em JSON. |
| `GET /api/players` | players conhecidos, com quantidade de sessões, pitch e duração. |
| `GET /api/sessoes.csv?player=&de=&ate=` | sessões em CSV (separado por `;`, abre direto no Excel). |
| `GET /api/config` | diz se o painel pede token. |
| `GET /saude` | `{"ok": true}`. |

## Limites e segurança

- Cada envio pode ter até 512 KB, 500 eventos e 5.000 faixas assistidas; o resto é recusado com `400`/`413`.
- Textos são cortados (URL e referrer em 2.000 caracteres, identificadores em 120) e caracteres de controle são removidos.
- O servidor não guarda IP. Guarda o `User-Agent` (para o tipo de dispositivo), a URL da página (com UTMs) e o referrer.
- A rota de coleta é pública por natureza: qualquer um que saiba o endereço pode mandar envios. Se isso virar
  problema, filtre pelo `Origin` no proxy ou limite a taxa por IP no Caddy/nginx.
- O painel e a API só saem com o token. Use um token longo e troque se vazar.
- Faça backup do arquivo `.sqlite` de tempos em tempos (basta copiar).

## Testes

```bash
python -m pytest tests/test_vsl_analytics.py --noconftest
```
