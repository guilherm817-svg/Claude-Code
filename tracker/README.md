# 📈 Rastro — rastreamento de vendas por anúncio

Tracker próprio, no estilo da Utmify, para quem vende com tráfego pago. Ele junta numa tela só:

- **as vendas** que chegam do checkout (Hotmart, Kiwify ou qualquer outro via webhook),
- **o gasto** de cada campanha, conjunto e anúncio do Meta Ads,
- **a origem** de cada venda (UTMs + pixel próprio que leva a origem até o checkout),

e calcula **lucro, ROAS, ROI, CPA e margem** no total, por dia e **por anúncio**, com pausa/ativação e ajuste
de orçamento das campanhas direto do painel e envio das vendas para a **API de Conversões do Meta**.

Roda no seu servidor, com os seus dados. Sem mensalidade.

## O que tem

| Área | Recursos |
|---|---|
| **Painel** | Lucro, faturamento líquido e bruto, gasto, ROAS, ROI, margem, CPA, ticket médio, vendas pendentes, reembolsos e chargebacks, comparação com o período anterior, gráfico diário, conversão de Pix/cartão/boleto, vendas por origem e por produto, filtros por período, conta de anúncio, plataforma, produto e nome de campanha. Atualiza sozinho a cada minuto. |
| **Campanhas** | Tabela de campanhas → conjuntos → anúncios com gasto, vendas, faturamento, lucro, ROAS, CPA, margem, IC, CPM, CTR, CPC e visitas. Liga/desliga e muda o orçamento diário no Meta sem sair do painel. |
| **Vendas** | Lista com busca e filtro por status, e o detalhe de cada venda (UTMs, campanha, anúncio, envio à API de Conversões). |
| **Pixel** | Um `<script>` para todas as páginas: guarda UTMs, fbclid e cookies do Meta por 30 dias, mantém a origem entre domínios (pré-venda → página de vendas) e coloca UTMs + `sck` em todos os links do checkout. |
| **Webhooks** | Hotmart (2.0.0), Kiwify e um formato genérico (Zapier, n8n, Make, checkout próprio). Validação de assinatura, log de tudo o que chegou e reprocessamento. |
| **Meta Ads** | Gasto, impressões, cliques, visualizações de página, checkouts iniciados e compras por anúncio e por dia, atualizados a cada 15 minutos; várias contas de anúncio, inclusive em dólar (com cotação). |
| **API de Conversões** | Cada venda aprovada vira um evento `Purchase` com e-mail, telefone e nome (SHA-256), IP, user agent, fbp e fbc da visita. |
| **Custos** | Imposto sobre faturamento, imposto sobre anúncios (ex.: 12,15%) e custo por produto. |
| **Equipe** | Vários usuários por operação. Membros veem tudo e controlam as campanhas; só administradores mudam integrações, custos e usuários. Pronto para várias operações (modo SaaS, `RASTRO_PERMITIR_CADASTRO=1`). |

## Como funciona

```
 Anúncio do Meta ──(UTMs com IDs)──▶ Página de vendas + pixel do Rastro ──(UTMs + sck=id da visita)──▶ Checkout
                                              │                                                        │
                                       registra a visita                                      webhook da venda
                                              ▼                                                        ▼
                                      ┌──────────────────────────── Rastro ─────────────────────────────┐
  API do Meta ──(gasto por anúncio)──▶│  liga venda ↔ visita ↔ anúncio · calcula lucro · painel         │──▶ API de Conversões
                                      └─────────────────────────────────────────────────────────────────┘
```

O segredo está nas UTMs com o **ID** de cada nível (`Nome|ID`): mesmo renomeando a campanha, a venda continua
ligada ao anúncio certo. A Hotmart não devolve `utm_*` no webhook, só `src`, `sck` e `xcod`: por isso o pixel
coloca o id da visita no `sck`, e o Rastro recupera as UTMs da visita quando a venda chega.

## Experimentar no computador

Precisa do **Python 3.10 ou mais novo** ([python.org](https://www.python.org/downloads/); no Windows, marque
"Add python.exe to PATH").

- **Windows:** dois cliques em `iniciar.bat`.
- **Mac/Linux:** `./iniciar.sh`

Abra `http://localhost:8000` e crie o acesso de administrador. Para ver o painel cheio de dados de exemplo:

```bash
.venv/bin/python -m rastro.demo        # Windows: .venv\Scripts\python -m rastro.demo
```

e entre com `demo@rastro.local` / `demo12345`.

> No computador as plataformas não conseguem mandar webhooks (o endereço não é público). Para isso, publique
> num servidor (abaixo) ou use um túnel como o [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
> ou o ngrok e coloque o endereço dele em `RASTRO_URL_PUBLICA`.

## Colocar no ar

O Rastro precisa de um endereço **público com HTTPS**, porque recebe webhooks e o pixel roda nas suas páginas.

### Opção 1 — Railway, Render ou similar (mais fácil)

1. Suba esta pasta (`tracker/`) para um repositório no GitHub.
2. Crie o serviço a partir do repositório (o `Dockerfile` já está pronto) e adicione um **PostgreSQL**.
3. Defina as variáveis:
   - `DATABASE_URL` → a URL do PostgreSQL que a plataforma fornece;
   - `RASTRO_URL_PUBLICA` → o endereço do serviço, ex.: `https://rastro-producao.up.railway.app` (ou seu domínio);
   - `RASTRO_CHAVE_SECRETA` → um texto aleatório longo (as sessões de login dependem dele).
4. Rode **uma instância só** (a sincronização com o Meta roda dentro do processo).

### Opção 2 — Servidor próprio (VPS) com Docker

Com o domínio apontado para o servidor:

```bash
cd tracker
echo "DOMINIO=rastro.suaempresa.com.br" > .env
echo "SENHA_BANCO=$(openssl rand -hex 16)" >> .env
docker compose up -d
```

Sobe o Rastro, um PostgreSQL e o Caddy, que emite o certificado HTTPS sozinho.

## Configurar (no menu Integrações)

1. **Pixel** — copie o `<script>` e cole antes do `</head>` em **todas** as páginas do funil (pré-venda, página
   de vendas, obrigado). Funciona em WordPress, Elementor, Atomicat, GreatPages ou HTML.
   - Redireciona por JavaScript (quiz, botão com código)? Use `location.href = Rastro.url("https://pay...")`.
   - `data-rastro="ignorar"` deixa um link intocado; `data-rastro="checkout"` conta um botão como clique no checkout.
2. **UTMs** — cole o padrão abaixo em *Rastreamento › Parâmetros de URL* de **cada anúncio** (dá para editar
   vários de uma vez):
   ```
   utm_source=FB&utm_campaign={{campaign.name}}|{{campaign.id}}&utm_medium={{adset.name}}|{{adset.id}}&utm_content={{ad.name}}|{{ad.id}}&utm_term={{placement}}
   ```
3. **Checkout** — gere a URL de webhook da sua plataforma e cole lá:
   - **Hotmart:** *Ferramentas › Webhook (API e notificações)*, versão **2.0.0**, todos os eventos de compra.
     Cole o **Hottok** no campo Segredo para recusar chamadas falsas. Se você é afiliado ou coprodutor, escolha
     isso na integração, para o faturamento líquido usar a sua comissão.
   - **Kiwify:** *Apps › Webhooks*, todos os eventos de compra. Cole o token do webhook no campo Segredo para
     validar a assinatura.
   - **Outras plataformas:** use a integração **Genérico** (formato abaixo) via Zapier, Make ou n8n.
4. **Meta Ads** — gere um token de **Usuário do Sistema** no Gerenciador de Negócios (permissões `ads_read` e
   `ads_management`), cole no Rastro e ative as contas de anúncio. Ao ativar, ele traz os últimos 30 dias; depois
   atualiza hoje e ontem a cada 15 minutos. Para mais histórico, use *Trazer histórico desde*.
5. **API de Conversões** (opcional, em Configurações) — ID do pixel + token do Gerenciador de Eventos. Se o
   checkout já envia o `Purchase` para o mesmo pixel, deixe desligado para não contar em dobro.
6. **Custos** (Configurações) — imposto sobre o faturamento, imposto sobre anúncios e custo de cada produto.

O menu **Integrações › Webhooks recebidos** mostra tudo o que chegou. Se algum webhook der erro (por exemplo, um
formato que mudou), ele fica guardado e pode ser **reprocessado** depois do ajuste.

## Como cada número é calculado

| Métrica | Fórmula |
|---|---|
| Faturamento líquido | o que fica para você das vendas aprovadas (já sem a taxa da plataforma) |
| Gasto com anúncios | gasto do Meta × cotação da conta × (1 + imposto sobre anúncios) |
| Impostos | faturamento líquido × imposto sobre faturamento |
| **Lucro** | faturamento líquido − gasto − impostos − custo dos produtos |
| ROAS | faturamento líquido ÷ gasto |
| ROI | lucro ÷ (gasto + impostos + custo dos produtos) |
| CPA | gasto ÷ vendas aprovadas |
| Margem | lucro ÷ faturamento líquido |

As vendas entram no dia em que foram **criadas** (no fuso da operação). Uma venda reembolsada sai do faturamento
do dia original e aparece em Reembolsos. A atribuição é de **último clique** com origem: uma visita direta não
apaga a origem anterior (validade de 30 dias). Webhooks fora de ordem não fazem o status voltar atrás (uma venda
reembolsada não volta a "aprovada").

## Webhook genérico

`POST` em JSON na URL gerada pela integração **Genérico**:

```json
{
  "id": "pedido-123",
  "status": "aprovada",
  "valor": 197.00,
  "valor_liquido": 180.50,
  "metodo_pagamento": "pix",
  "data": "2026-10-05T14:30:00-03:00",
  "produto": {"id": "curso-x", "nome": "Curso X"},
  "cliente": {"nome": "Maria", "email": "maria@exemplo.com", "telefone": "11999998888"},
  "rastreio": {"utm_source": "FB", "utm_campaign": "Campanha|1202...", "sck": "tk..."}
}
```

`status`: `aprovada`, `pendente`, `recusada`, `cancelada`, `reembolsada` ou `chargeback`. `metodo_pagamento`:
`pix`, `cartao` ou `boleto`. Mande o mesmo `id` de novo para atualizar o status. Com Segredo preenchido, envie-o
no cabeçalho `X-Rastro-Token` (ou o HMAC-SHA256 do corpo em `X-Rastro-Assinatura`).

## Segurança e privacidade

- Senhas com scrypt; sessão em cookie assinado, `HttpOnly`; proteção contra CSRF; limite de tentativas de login.
- Cada webhook tem uma URL secreta própria e, opcionalmente, validação de assinatura (Hottok, assinatura da Kiwify).
- O Rastro guarda dados pessoais de compradores (nome, e-mail, telefone, IP) para atribuição e API de
  Conversões. Você é o controlador desses dados (LGPD): mantenha o servidor protegido e informe isso na sua
  política de privacidade.
- Os tokens do Meta ficam no banco: proteja o acesso ao banco e aos backups.

## Para desenvolvedores

```
rastro/
  app.py              monta o FastAPI (rotas, painel, sincronização em segundo plano)
  modelos.py          tabelas (SQLAlchemy); dinheiro em centavos, datas em UTC
  plataformas/        um adaptador por checkout: hotmart.py, kiwify.py, generico.py
  vendas.py           webhook → venda (status que não volta atrás, log, reprocessamento)
  atribuicao.py       venda ↔ visita ↔ campanha/conjunto/anúncio
  meta.py             cliente da Graph API (insights, status, orçamento, API de Conversões)
  sincronizacao.py    gastos e status do Meta a cada N minutos
  capi.py             eventos Purchase da API de Conversões
  metricas.py         todas as contas do painel
  rotas/              API (publico.py: pixel e webhooks; conta.py; painel.py)
  static/             painel (HTML/CSS/JS puro, sem build) e pixel.js
  demo.py             dados de demonstração
tests/                pytest (Meta simulado)
```

```bash
pip install -r requirements.txt pytest
python -m pytest                                   # SQLite
RASTRO_TESTE_DATABASE_URL=postgresql://... python -m pytest   # PostgreSQL
```

**Nova plataforma de checkout:** crie `rastro/plataformas/<nome>.py` com `NOME`, `verificar()` e `interpretar()`
(que devolve uma `VendaNormalizada`), registre em `plataformas/__init__.py` e adicione um teste com um webhook real
de exemplo.

## Limitações e próximos passos

- Só o **Meta Ads** traz gastos. Google Ads e TikTok Ads são os próximos candidatos (a estrutura de
  `GastoDiario` já comporta outras fontes).
- Checkouts com adaptador próprio: Hotmart e Kiwify. Braip, Monetizze, Eduzz, Perfect Pay, Ticto, Yampi, Shopify
  etc. funcionam hoje pelo genérico (via Zapier/n8n); adaptadores diretos são simples de acrescentar.
- O Meta Ads é conectado por token de Usuário do Sistema, não por login com o Facebook (isso exigiria um app
  aprovado pelo Meta).
- O banco é criado automaticamente na primeira execução; mudanças futuras no esquema vão precisar de migrações
  (ex.: Alembic).
