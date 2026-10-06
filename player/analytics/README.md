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
- Por padrão só aceita conexões da própria máquina (`127.0.0.1`), o que basta com o Caddy abaixo. Para expor a
  porta direto (Docker, proxy em outra máquina, testar pelo celular na rede), rode com `--host 0.0.0.0`, sempre
  com `--token`.
- Também aceita as variáveis `VSL_ANALYTICS_HOST`, `VSL_ANALYTICS_PORTA`, `VSL_ANALYTICS_DADOS` e
  `VSL_ANALYTICS_TOKEN`.

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
| **Visualizações da página** | sessões, isto é, carregamentos de um player (cada aba aberta é uma; com dois players na mesma página, são duas). Também mostra visitantes únicos (pelo identificador salvo no navegador). |
| **Plays** | sessões em que a pessoa clicou para ouvir (evento `unmute`). A taxa de play é plays ÷ visualizações. |
| **Chegaram ao pitch** | plays que, com som, passaram do tempo definido em `data-pitch` do player daquela sessão. Em "Todos os players" cada sessão é julgada pelo pitch do seu player. Dá para forçar outro tempo com `?pitch=750` na API. |
| **Terminaram o vídeo** | plays que receberam o evento `ended`. |
| **Tempo médio assistido** | média (e mediana) dos segundos assistidos com som por play, contando cada segundo uma só vez e nunca além da duração. |
| **Curva de retenção** | para cada segundo do vídeo, a porcentagem dos plays que o assistiu com som. Vídeos longos são compactados em até 1.200 pontos. |
| **Por dia** | visualizações e plays por dia da primeira chegada da sessão. Os períodos prontos do painel (hoje, 7, 30 e 90 dias) são calculados pelo relógio do servidor, o mesmo que carimba as sessões. |
| **Origens** | `utm_source` da URL da página ou, se não houver, o site de onde a pessoa veio (facebook, instagram, google, tiktok...). |
| **Dispositivos** | celular ou computador, pelo `User-Agent`. |
| **Eventos** | contagem de todos os eventos recebidos, inclusive os seus: `VSLPlayer.get('id').emit('cta_click')` registra cliques no botão, por exemplo. |

Só conta o que foi visto com som: o trecho do autoplay mudo entra em *Visualizações*, mas não na retenção,
nos tempos nem no pitch. O evento `pitch` listado na tabela de eventos é outra coisa: o player o dispara uma
vez por visitante (para os pixels), inclusive no mudo, por isso ele não bate com o número *Chegaram ao pitch*.

## API

As rotas `/api/resumo`, `/api/players` e `/api/sessoes.csv` pedem o token (cabeçalho `X-Token`, ou `?token=`).
`GET /` entrega o HTML do painel sem token: a página pede o token na tela e só mostra dados depois que a API o
aceita. `/vsl`, `/saude` e `/api/config` são públicas.

| Rota | Para quê |
|---|---|
| `POST /vsl` | recebe o envio do player (JSON, mesmo com `Content-Type: text/plain`). Responde `204` com CORS liberado. |
| `GET /` | o painel. |
| `GET /api/resumo?player=&periodo=hoje|7|30|90|tudo&pitch=` | todos os números do painel em JSON. Em vez de `periodo`, dá para passar `de=AAAA-MM-DD&ate=AAAA-MM-DD`. Datas, período ou pitch inválidos respondem `400`. |
| `GET /api/players` | players conhecidos, com quantidade de sessões, pitch e duração. |
| `GET /api/sessoes.csv?player=&periodo=` (ou `de`/`ate`) | sessões em CSV (separado por `;`, abre direto no Excel). Células de texto que começam com `=`, `+`, `-` ou `@` ganham um apóstrofo na frente, para a planilha não executá-las como fórmula. |
| `GET /api/config` | diz se o painel pede token e a data de hoje no servidor. |
| `GET /saude` | `{"ok": true}`. |

## Limites e segurança

- Cada envio pode ter até 512 KB, 500 eventos e 5.000 faixas assistidas; o resto é recusado com `400`/`413`.
  Durações, tempos e faixas são limitados a 24 horas; carimbos de hora, a 2^53.
- Textos são cortados (URL e referrer em 2.000 caracteres, identificadores em 120) e caracteres de controle são removidos.
- O banco não guarda IP. Guarda o `User-Agent` (para o tipo de dispositivo), a URL da página (com UTMs) e o
  referrer. O log de acesso no terminal mostra o IP de cada requisição (com o token mascarado), como qualquer
  servidor web.
- Conexões paradas por 30 segundos são fechadas.
- A rota de coleta é pública por natureza: qualquer um que saiba o endereço pode mandar envios. Se isso virar
  problema, filtre pelo `Origin` no proxy ou limite a taxa por IP no Caddy/nginx.
- Os dados (API e CSV) só saem com o token. Use um token longo e troque se vazar. O painel manda o token no
  cabeçalho `X-Token`; se você mesmo chamar a API, prefira o cabeçalho à query string, que acaba em históricos
  e logs de proxy.
- Faça backup do arquivo `.sqlite` de tempos em tempos (basta copiar).

## Testes

```bash
python -m pytest tests/test_vsl_analytics.py --noconftest
```
