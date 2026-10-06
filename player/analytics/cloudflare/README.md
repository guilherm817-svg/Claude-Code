# 📊 Analytics do VSL Player na Cloudflare (sem servidor)

A mesma coisa que o `servidor.py` da pasta de cima, mas rodando de graça na Cloudflare: um **Worker** recebe os
envios do player e um banco **D1** guarda as sessões. Não precisa de VPS, não precisa de cartão, e o endereço
já vem com HTTPS. O plano gratuito dá 100 mil requisições por dia e 100 mil gravações por dia no banco, o que
cobre dezenas de milhares de visitas diárias.

## Colocar no ar (um clique)

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/guilherm817-svg/Claude-Code/tree/claude/determined-planck-3oymh2/player/analytics/cloudflare)

1. Clique no botão. Entre (ou crie uma conta) na Cloudflare e conecte o GitHub quando ele pedir.
2. A Cloudflare copia esta pasta para um repositório seu, cria o banco D1 sozinha e publica o Worker.
3. No fim aparece o endereço, parecido com `https://vsl-analytics.SEU-NOME.workers.dev`.
4. No player, use esse endereço com `/vsl` no final:

```html
<div class="vsl-player" data-src="..." data-pitch="12:30"
     data-analytics="https://vsl-analytics.SEU-NOME.workers.dev/vsl"></div>
```

O painel abre no mesmo endereço, sem o `/vsl`.

### Proteger o painel com senha (recomendado)

No site da Cloudflare: **Workers & Pages → vsl-analytics → Settings → Variables and Secrets → Add**, tipo
*Secret*, nome `TOKEN`, valor uma senha longa. Clique em *Deploy*. A partir daí o painel pede essa senha; os
envios do player continuam abertos. A variável `FUSO` (padrão `America/Sao_Paulo`) define o fuso das datas.

## Se preferir pelo terminal

```bash
cd player/analytics/cloudflare
npm install
npx wrangler login
npm run deploy          # cria o banco, roda a migração e publica
npx wrangler secret put TOKEN
```

Para rodar no seu computador: `npm run dev` e abra http://localhost:8787.

## Diferenças em relação ao servidor Python

- Cada sessão é uma linha no D1 e os eventos ficam contados em JSON dentro dela (uma gravação por envio, para
  caber no plano gratuito). Por isso a tabela de eventos conta repetições, sem deduplicar reenvios.
- O pitch e a duração de cada player vêm da sessão mais recente que os informou.
- As datas usam o fuso da variável `FUSO`; o Python usa o relógio do computador onde roda.
- O CSV sai com `Content-Disposition`, mas o download pelo painel é o mesmo.

Tudo o mais (rotas, números, limites, token) é igual ao que está documentado em
[`../README.md`](../README.md).

## Testes

```bash
npm test    # usa o node:sqlite para imitar o D1
```
