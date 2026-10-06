// Funções pequenas usadas pela tela toda.

export const $ = (seletor, raiz = document) => raiz.querySelector(seletor);

export function el(tag, atributos = {}, ...filhos) {
  const elemento = document.createElement(tag);
  for (const [nome, valor] of Object.entries(atributos)) {
    if (valor === undefined || valor === null || valor === false) continue;
    if (nome === 'class') elemento.className = valor;
    else if (nome === 'style' && typeof valor === 'object') Object.assign(elemento.style, valor);
    else if (nome.startsWith('on')) elemento.addEventListener(nome.slice(2), valor);
    else if (nome in elemento && typeof valor !== 'string') elemento[nome] = valor;
    else elemento.setAttribute(nome, valor === true ? '' : valor);
  }
  for (const filho of filhos.flat()) {
    if (filho === null || filho === undefined || filho === false) continue;
    elemento.append(filho instanceof Node ? filho : document.createTextNode(String(filho)));
  }
  return elemento;
}

export const limitar = (valor, minimo, maximo) => Math.min(maximo, Math.max(minimo, valor));

// 0:04.2 — minutos:segundos.décimos, como nos editores de vídeo.
export function relogio(segundos, casas = 1) {
  if (!Number.isFinite(segundos) || segundos < 0) segundos = 0;
  const fator = 10 ** casas;
  const total = Math.round(segundos * fator) / fator;
  const minutos = Math.floor(total / 60);
  const resto = (total - minutos * 60).toFixed(casas);
  return `${minutos}:${resto.padStart(casas ? 3 + casas : 2, '0')}`;
}

// 3,25 s — número em português.
export function segundos(valor, casas = 2) {
  return `${valor.toFixed(casas).replace('.', ',')} s`;
}

export function tamanhoArquivo(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1).replace('.', ',')} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1).replace('.', ',')} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export function avisar(mensagem, tipo = 'info', duracao = 5000) {
  const caixa = document.getElementById('avisos-flutuantes');
  const aviso = el('div', { class: `aviso-flutuante ${tipo}`, role: tipo === 'erro' ? 'alert' : 'status' }, mensagem);
  caixa.append(aviso);
  setTimeout(() => aviso.classList.add('saindo'), duracao);
  setTimeout(() => aviso.remove(), duracao + 400);
}

export function guardar(chave, valor) {
  try { localStorage.setItem(`estudio.${chave}`, JSON.stringify(valor)); } catch { /* navegador sem armazenamento */ }
}

export function lembrar(chave, padrao) {
  try {
    const valor = localStorage.getItem(`estudio.${chave}`);
    return valor === null ? padrao : JSON.parse(valor);
  } catch {
    return padrao;
  }
}
