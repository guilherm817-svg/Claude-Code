# 📊 Analytics do VSL Player na Cloudflare (sem servidor)

A mesma coisa que o `servidor.py` da pasta de cima, mas rodando de graça na Cloudflare: um **Worker** recebe os
envios do player e um banco **D1** guarda as sessões. Não precisa de VPS, não precisa de cartão, e o endereço
já vem com HTTPS.

**Quanto cabe no plano gratuito:** 100 mil requisições e 100 mil gravações por dia. Cada visita gera 1 envio,
mais cerca de 4 por minuto assistido com som (a cada 15 s, mais um ao tirar o mudo, no pitch, no fim e ao sair),
e o painel aberto gasta 2 requisições por minuto. Na prática, uns 20 mil minutos assistidos por dia, por exemplo
2 mil pessoas assistindo 10 minutos. Em sites maiores, suba `data-analytics-interval` para 30 ou 60 no player
e, se precisar, o plano pago da Cloudflare (US$ 5/mês) multiplica os limites por 100 e dá 30 s de CPU por
requisição (no grátis são 10 ms). Para caber nesses 10 ms, quando o período tem mais de 2.000 plays a curva de
retenção é calculada sobre uma amostra aleatória de 2.000 (o painel avisa; os outros números continuam exatos).

## Colocar no ar (um clique)

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/guilherm817-svg/Claude-Code)

1. Clique no botão. Entre (ou crie uma conta) na Cloudflare e conecte o GitHub quando ele pedir.
2. A Cloudflare liga o repositório, cria o banco D1 sozinha e publica o Worker (a configuração na raiz do
   repositório aponta para esta pasta; o Worker cria as tabelas sozinho no primeiro acesso).
3. No fim aparece o endereço, parecido com `https://claude-code.SEU-NOME.workers.dev`.
4. No player, use esse endereço com `/vsl` no final:

```html
<div class="vsl-player" data-src="..." data-pitch="12:30"
     data-analytics="https://claude-code.SEU-NOME.workers.dev/vsl"></div>
```

O painel abre no mesmo endereço, sem o `/vsl`.

### Proteger o painel com senha (recomendado)

No site da Cloudflare: **Workers & Pages → claude-code → Settings → Variables and Secrets → Add**, tipo
*Secret*, nome `TOKEN`, valor uma senha longa. Clique em *Deploy*. A partir daí o painel pede essa senha; os
envios do player continuam abertos. Enquanto não houver token, o painel mostra um aviso em amarelo.

Para abrir o painel já com a senha, use o fragmento da URL: `https://SEU-WORKER.workers.dev/#token=SUA-SENHA`
(o que vem depois de `#` não sai do navegador nem vai para os logs). A API aceita o token só no cabeçalho
`X-Token` (ou `Authorization: Bearer`), nunca na query string. A variável `FUSO` (padrão `America/Sao_Paulo`)
define o fuso das datas.

## Se preferir pelo terminal

```bash
cd player/analytics/cloudflare
npm install
npx wrangler login
npm run deploy          # cria o banco, roda a migração e publica
npx wrangler secret put TOKEN
```

Para rodar no seu computador: `npm run dev` e abra http://localhost:8787.

### Migrações do banco

As migrações ficam em `migrations/` e o Worker as roda sozinho no primeiro acesso de cada instância, então o
banco funciona mesmo sem `wrangler d1 migrations apply`. A `0003_navegador.sql` acrescenta a coluna
`navegador` à tabela `sessoes` (`ALTER TABLE`); o Worker confere antes se a coluna já existe (`PRAGMA
table_info`) e ignora o erro de coluna duplicada, por isso rodar de novo não quebra. Já a `wrangler d1
migrations apply` não tolera o `ALTER` repetido: se o Worker novo receber um acesso antes dela, ela falha com
`duplicate column name: navegador`. Nesse caso a coluna já está lá; basta marcar a migração como aplicada:

```bash
npx wrangler d1 execute DB --remote --command "INSERT OR IGNORE INTO d1_migrations (name) VALUES ('0003_navegador.sql')"
```

Para evitar isso, aplique a migração antes de publicar (`npx wrangler d1 migrations apply DB --remote` e só
depois `npx wrangler deploy`).

## Diferenças em relação ao servidor Python

- Cada sessão é uma linha no D1 e os eventos ficam contados em JSON dentro dela (uma gravação por envio, para
  caber no plano gratuito). Por isso a tabela de eventos conta repetições, sem deduplicar reenvios.
- O pitch e a duração de cada player vêm da sessão mais recente que os informou.
- As datas usam o fuso da variável `FUSO`; o Python usa o relógio do computador onde roda.
- O CSV tem as mesmas 20 colunas do Python (a última delas, `navegador`) e mais uma no fim, `dia`, que é a
  data no fuso `FUSO` (o `inicio` é em UTC).
- Cada sessão guarda até 50 tipos de evento diferentes.
- Arredondamentos em empate exato (.5) podem diferir do Python em uma unidade da última casa decimal.
- A rota de coleta é pública e sem limite de taxa, como no Python. Se alguém inundar o Worker, a proteção que
  poupa a cota é uma regra de *rate limiting* no WAF da Cloudflare (grátis, 1 regra) num domínio seu apontando
  para o Worker.

Tudo o mais (rotas, números, limites, token) é igual ao que está documentado em
[`../README.md`](../README.md).

## Testes

```bash
npm test    # usa o node:sqlite para imitar o D1
```
