/*
 * Pixel do Rastro. Instale em todas as páginas do funil (pré-venda, página de vendas, obrigado):
 *   <script src="https://SEU-DOMINIO/p.js" data-conta="pk_..." async></script>
 *
 * O que ele faz:
 * 1. guarda UTMs, fbclid/gclid/ttclid e os cookies do pixel do Meta (_fbp/_fbc) por 30 dias;
 * 2. cria um id de visita ("tk...") e registra a visita no servidor;
 * 3. acrescenta UTMs + sck=<id da visita> em todos os links, para o checkout (Hotmart, Kiwify...)
 *    devolver a origem no webhook da venda.
 *
 * Opções no <script>: data-dias="30" (validade da atribuição), data-param="sck" (parâmetro do id).
 * Para redirecionar por JavaScript: location.href = Rastro.url("https://pay.kiwify.com.br/xxx").
 * Para não mexer num link: <a data-rastro="ignorar">. Para marcar um botão como checkout: data-rastro="checkout".
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script || window.Rastro) return;

  var CONTA = script.getAttribute("data-conta");
  var DIAS = parseInt(script.getAttribute("data-dias") || "30", 10);
  var PARAM_ID = script.getAttribute("data-param") || "sck";
  var ENDPOINT = new URL(script.src).origin + "/c";
  var UTMS = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];
  var CLIQUES = ["fbclid", "gclid", "ttclid"];
  var ID_VISITA = /^tk[0-9a-z]{16,30}$/;
  var CHECKOUTS = /(^|\.)(hotmart\.com|kiwify\.com\.br|kiwify\.app|kiwify\.com|eduzz\.com|monetizze\.com\.br|braip\.com|perfectpay\.com\.br|ticto\.app|ticto\.com\.br|lastlink\.com|greenn\.com\.br|payt\.com\.br|yampi\.com\.br|cartpanda\.com|mycartpanda\.com|doppus\.com|hubla\.com|pepper\.com\.br)$|^(checkout|pay|seguro|compra)\./i;
  var CHAVE = "_rastro";

  if (!CONTA) {
    if (window.console) console.warn("[Rastro] falta o atributo data-conta no <script> do pixel.");
    return;
  }

  function novoId(prefixo, tamanho) {
    var letras = "0123456789abcdefghijklmnopqrstuvwxyz";
    var saida = prefixo;
    var aleatorio = new Uint8Array(tamanho);
    (window.crypto || window.msCrypto).getRandomValues(aleatorio);
    for (var i = 0; i < tamanho; i++) saida += letras[aleatorio[i] % 36];
    return saida;
  }

  function lerCookie(nome) {
    var achado = document.cookie.match(new RegExp("(?:^|; )" + nome + "=([^;]*)"));
    return achado ? decodeURIComponent(achado[1]) : null;
  }

  // Grava no domínio mais alto possível (ex.: .site.com.br), para valer em www. e subdomínios.
  function gravarCookie(nome, valor, dias) {
    var expira = new Date(Date.now() + dias * 864e5).toUTCString();
    var partes = location.hostname.split(".");
    for (var i = partes.length - 2; i >= 0; i--) {
      var dominio = partes.slice(i).join(".");
      document.cookie = nome + "=" + encodeURIComponent(valor) + "; expires=" + expira +
        "; path=/; domain=" + dominio + "; SameSite=Lax";
      if (lerCookie(nome) === valor) return;
    }
    document.cookie = nome + "=" + encodeURIComponent(valor) + "; expires=" + expira + "; path=/; SameSite=Lax";
  }

  function lerEstado() {
    var bruto = lerCookie(CHAVE);
    try {
      if (!bruto && window.localStorage) bruto = localStorage.getItem(CHAVE);
      var estado = bruto ? JSON.parse(bruto) : null;
      if (estado && estado.t && Date.now() - estado.t < DIAS * 864e5) return estado;
    } catch (e) { /* estado corrompido: começa de novo */ }
    return null;
  }

  function salvarEstado(estado) {
    var texto = JSON.stringify(estado);
    gravarCookie(CHAVE, texto, DIAS);
    try { if (window.localStorage) localStorage.setItem(CHAVE, texto); } catch (e) { /* modo privado */ }
  }

  var params = new URLSearchParams(location.search);
  var estado = lerEstado() || {};
  var utmsNaUrl = {};
  var temOrigemNova = false;
  UTMS.concat(CLIQUES).forEach(function (nome) {
    var valor = params.get(nome);
    if (valor) { utmsNaUrl[nome] = valor.slice(0, 300); temOrigemNova = true; }
  });

  // O id da visita chega na URL quando o visitante passa de um domínio para outro (pré-venda → página de vendas).
  var idRecebido = null;
  [PARAM_ID, "sck", "src", "xcod"].forEach(function (nome) {
    var valor = (params.get(nome) || "").toLowerCase();
    if (!idRecebido && ID_VISITA.test(valor)) idRecebido = valor;
  });

  var nova = false;
  if (idRecebido) {
    if (idRecebido !== estado.c) nova = true;
    estado.c = idRecebido;
    if (temOrigemNova) estado.u = utmsNaUrl;
  } else if (temOrigemNova || !estado.c) {
    // Clique novo em anúncio (ou primeira visita): nova atribuição. Visita direta mantém a origem anterior.
    estado.c = novoId("tk", 18);
    estado.u = utmsNaUrl;
    nova = true;
  }
  estado.v = estado.v || novoId("v", 16);
  if (params.get("fbclid")) estado.fbc = "fb.1." + Date.now() + "." + params.get("fbclid");
  estado.t = Date.now();
  salvarEstado(estado);

  function enviar(tipo) {
    var dados = {
      k: CONTA, t: tipo, c: estado.c, v: estado.v, u: estado.u || {}, n: nova,
      fbp: lerCookie("_fbp"), fbc: lerCookie("_fbc") || estado.fbc || null,
      url: location.href.slice(0, 1000), ref: document.referrer.slice(0, 1000)
    };
    var corpo = JSON.stringify(dados);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(ENDPOINT, new Blob([corpo], { type: "text/plain" }))) return;
    } catch (e) { /* cai no fetch */ }
    try {
      fetch(ENDPOINT, { method: "POST", body: corpo, mode: "no-cors", keepalive: true,
        headers: { "Content-Type": "text/plain" } });
    } catch (e) { /* sem rede: não atrapalha a página */ }
  }

  function decorar(endereco) {
    var url;
    try { url = new URL(endereco, location.href); } catch (e) { return endereco; }
    if (url.protocol !== "http:" && url.protocol !== "https:") return endereco;
    var utms = estado.u || {};
    UTMS.forEach(function (nome) {
      if (utms[nome] && !url.searchParams.get(nome)) url.searchParams.set(nome, utms[nome]);
    });
    var atual = (url.searchParams.get(PARAM_ID) || "").toLowerCase();
    if (!atual || ID_VISITA.test(atual)) url.searchParams.set(PARAM_ID, estado.c);
    return url.toString();
  }

  function deveDecorar(link) {
    var href = link.getAttribute("href");
    if (!href || href.charAt(0) === "#" || link.getAttribute("data-rastro") === "ignorar") return false;
    if (link.hostname === location.hostname && link.pathname === location.pathname && link.hash) return false;
    return link.protocol === "http:" || link.protocol === "https:";
  }

  function decorarLink(link) {
    if (!deveDecorar(link)) return;
    var novo = decorar(link.href);
    if (novo !== link.href) link.href = novo;
  }

  function decorarTudo(raiz) {
    var links = (raiz || document).querySelectorAll ? (raiz || document).querySelectorAll("a[href]") : [];
    for (var i = 0; i < links.length; i++) decorarLink(links[i]);
  }

  function ehCheckout(link) {
    return link.getAttribute("data-rastro") === "checkout" || CHECKOUTS.test(link.hostname);
  }

  // Decora de novo no clique (links que mudam o href depois do carregamento) e conta cliques para o checkout.
  function aoClicar(evento) {
    var alvo = evento.target && evento.target.closest ? evento.target.closest("a[href], [data-rastro='checkout']") : null;
    if (!alvo) return;
    if (alvo.tagName === "A") decorarLink(alvo);
    if (evento.type === "click" && (alvo.tagName !== "A" || ehCheckout(alvo))) enviar("checkout");
  }

  document.addEventListener("mousedown", aoClicar, true);
  document.addEventListener("touchstart", aoClicar, { capture: true, passive: true });
  document.addEventListener("click", aoClicar, true);

  function iniciar() {
    decorarTudo(document);
    if (window.MutationObserver) {
      new MutationObserver(function (mudancas) {
        mudancas.forEach(function (mudanca) {
          mudanca.addedNodes.forEach(function (no) {
            if (no.nodeType !== 1) return;
            if (no.tagName === "A") decorarLink(no); else decorarTudo(no);
          });
        });
      }).observe(document.documentElement, { childList: true, subtree: true });
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();
  // Envia já: a venda da Hotmart depende deste registro. O _fbp, que o pixel do Meta cria depois,
  // segue no evento de clique para o checkout.
  enviar("pagina");

  window.Rastro = { url: decorar, visita: estado.c, visitante: estado.v, evento: enviar };
})();
