// Legendas automáticas na prévia: o mesmo algoritmo de estudio/legendas.py (agrupar as palavras em telas e
// diagramar cada tela no quadro) e o desenho delas no canvas, igual ao que o libass queima na exportação.
// Os dois lados precisam dar resultados idênticos, e tests/casos_legendas.json confere isso: mudou um, mude o
// outro. Este arquivo não importa nada, para o teste do Node conseguir carregá-lo sozinho.

export const FONTES = {
  black: { familia: 'Poppins Black', peso: 900 },
  extrabold: { familia: 'Poppins ExtraBold', peso: 800 },
};
export const FAMILIA_CANVAS = 'Poppins Estudio'; // o @font-face do estilo.css, com os dois pesos
// O libass mede o Fontsize pela altura usWinAscent + usWinDescent da fonte; o canvas, pelo em.
export const FATOR_ASS = 1.762;
const DESLOCAMENTO_ASS = 0.254;
const ALTURA_MAIUSCULA = 0.71;
const ACIMA = 1.01;
const ABAIXO = 0.28;

const CARACTERES = String.fromCharCode(...Array.from({ length: 95 }, (_, i) => 32 + i))
  + String.fromCharCode(...Array.from({ length: 95 }, (_, i) => 0xA1 + i).filter((c) => c !== 0xAD))
  + '‘’“”–—…•€';
const LARGURAS_BRUTAS = {
  black: [
    170, 455, 490, 933, 665, 938, 831, 265, 463, 463, 561, 551, 342, 576, 319, 399, 662, 399, 566, 615, 704, 660,
    633, 512, 657, 597, 319, 385, 497, 626, 497, 538, 1129, 773, 684, 753, 743, 556, 575, 752, 755, 322, 590, 755,
    506, 951, 779, 788, 649, 788, 670, 625, 616, 719, 763, 1100, 764, 730, 630, 533, 878, 533, 758, 764, 324, 680,
    680, 609, 680, 616, 385, 680, 697, 322, 320, 676, 322, 1076, 697, 636, 680, 680, 467, 579, 436, 697, 671, 903,
    668, 677, 518, 484, 262, 484, 711, 455, 579, 679, 603, 730, 432, 595, 417, 771, 481, 618, 778, 511, 451, 496,
    551, 422, 403, 279, 751, 778, 349, 343, 285, 470, 618, 879, 928, 1024, 538, 773, 773, 773, 773, 773, 773, 986,
    753, 556, 556, 556, 556, 322, 322, 322, 322, 743, 779, 788, 788, 788, 788, 788, 581, 788, 719, 719, 719, 719,
    730, 649, 815, 680, 680, 680, 680, 680, 680, 1054, 609, 616, 616, 616, 616, 372, 372, 372, 372, 643, 697, 636,
    636, 636, 636, 636, 551, 621, 697, 697, 697, 697, 677, 680, 677, 378, 378, 648, 648, 683, 936, 869, 536, 790,
  ],
  extrabold: [
    191, 423, 451, 919, 661, 904, 814, 243, 470, 470, 548, 589, 314, 578, 301, 426, 657, 387, 569, 610, 691, 655,
    635, 523, 653, 606, 302, 366, 524, 661, 519, 538, 1104, 755, 671, 758, 735, 548, 561, 757, 743, 308, 584, 726,
    491, 935, 765, 787, 636, 788, 661, 620, 604, 712, 747, 1076, 739, 701, 613, 522, 840, 521, 733, 772, 307, 680,
    680, 607, 680, 616, 373, 680, 686, 308, 307, 647, 308, 1067, 686, 636, 680, 680, 447, 568, 421, 686, 649, 885,
    628, 655, 507, 492, 277, 492, 674, 423, 605, 671, 590, 701, 407, 591, 392, 775, 475, 588, 748, 512, 436, 480,
    590, 403, 389, 270, 728, 743, 324, 328, 267, 464, 588, 833, 874, 957, 538, 755, 755, 755, 755, 755, 755, 971,
    758, 548, 548, 548, 548, 308, 308, 308, 308, 738, 765, 787, 787, 787, 787, 787, 609, 787, 712, 712, 712, 712,
    701, 636, 788, 680, 680, 680, 680, 680, 680, 1061, 607, 616, 616, 616, 616, 347, 347, 347, 347, 641, 686, 636,
    636, 636, 636, 636, 581, 625, 686, 686, 686, 686, 655, 680, 655, 346, 346, 595, 595, 689, 933, 815, 519, 793,
  ],
};
const LARGURAS = Object.fromEntries(Object.entries(LARGURAS_BRUTAS)
  .map(([fonte, valores]) => [fonte, new Map([...CARACTERES].map((c, i) => [c, valores[i]]))]));
const LARGURA_DESCONHECIDA = 1000;

export const AMARELO = '#FFDD00';
const BRANCO = '#FFFFFF';
const PRETO = '#000000';

export const PRESETS = {
  destaque: {
    fonte: 'black', tamanho: 0.082, palavras: 3, linhas: 2, caracteres: { P: 18, M: 14, G: 11 },
    entrelinha: 1.12, contorno: 0.12, cor: BRANCO, destaque: AMARELO, caixa: null,
  },
  uma_palavra: {
    fonte: 'black', tamanho: 0.13, palavras: 1, linhas: 1, caracteres: { P: 40, M: 40, G: 40 },
    entrelinha: 1.0, contorno: 0.1, cor: AMARELO, destaque: null, caixa: null,
  },
  classica: {
    fonte: 'extrabold', tamanho: 0.058, palavras: 7, linhas: 2, caracteres: { P: 27, M: 22, G: 18 },
    entrelinha: 1.18, contorno: 0.09, cor: BRANCO, destaque: null, caixa: null,
  },
  caixa: {
    fonte: 'extrabold', tamanho: 0.064, palavras: 4, linhas: 2, caracteres: { P: 22, M: 18, G: 15 },
    entrelinha: 1.36, contorno: 0.0, cor: BRANCO, destaque: null,
    caixa: { cor: PRETO, opacidade: 0.62, folga: 0.36, altura: 1.36, raio: 0.22 },
  },
};
const FATOR_TAMANHO = { P: 0.82, M: 1.0, G: 1.22 };
const POSICOES = { alto: 0.28, centro: 0.5, baixo: 0.66 };
const LIMITE_TOPO = 0.12;
const LIMITE_BASE = 0.75;
const LARGURA_UTIL = 0.84;

const SOBREPOSICAO_MINIMA = 0.02;
const PAUSA_QUEBRA = 0.5;
const SOBRA_FINAL = 0.6;
const EMENDA = 0.25;
const POP = [[0.0, 0.75], [0.09, 1.08], [0.15, 1.0]];

export const ESTILO_PADRAO = { preset: 'destaque', tamanho: 'M', posicao: 'baixo', maiusculas: true, animacao: true };

// Meio para cima, como o arred() do Python.
export function arred(valor, casas) {
  const fator = 10 ** casas;
  return Math.floor(valor * fator + 0.5) / fator;
}

const tamanho = (texto) => [...texto].length; // em caracteres, como o len() do Python (não em UTF-16)

export function terminaFrase(texto) {
  return /[.!?…]$/u.test(texto.replace(/["'”’»)\]]+$/u, ''));
}

export function larguraEm(texto, fonte) {
  const tabela = LARGURAS[fonte];
  let soma = 0;
  for (const c of texto) soma += tabela.get(c) ?? LARGURA_DESCONHECIDA;
  return soma / 1000;
}

// Linhas de até `limite` caracteres, o mais equilibradas possível; null se não couber em `maxLinhas`.
export function quebrarLinhas(textos, limite, maxLinhas) {
  const tamanhos = textos.map(tamanho);
  const comprimento = (a, b) => tamanhos.slice(a, b).reduce((s, t) => s + t, 0) + (b - a - 1);
  const cabe = (a, b) => b - a === 1 || comprimento(a, b) <= limite;
  const n = textos.length;
  const faixa = (a, b) => Array.from({ length: b - a }, (_, i) => a + i);
  if (cabe(0, n)) return [faixa(0, n)];
  if (maxLinhas < 2) return null;
  let melhor = null;
  for (let k = 1; k < n; k++) {
    if (cabe(0, k) && cabe(k, n)) {
      const maior = Math.max(comprimento(0, k), comprimento(k, n));
      if (melhor === null || maior < melhor[0]) melhor = [maior, k];
    }
  }
  return melhor === null ? null : [faixa(0, melhor[1]), faixa(melhor[1], n)];
}

export function palavrasNoCorte(palavras, entrada, saida) {
  const resultado = [];
  for (const p of palavras) {
    const inicio = Math.max(p.inicio, entrada);
    const fim = Math.min(p.fim, saida);
    if (fim - inicio > SOBREPOSICAO_MINIMA) resultado.push({ texto: p.texto, inicio: inicio - entrada, fim: fim - entrada });
  }
  return resultado;
}

export function montarTelas(palavras, entrada, saida, estilo) {
  const preset = PRESETS[estilo.preset];
  const limite = preset.caracteres[estilo.tamanho];
  const duracao = saida - entrada;
  const locais = palavrasNoCorte(palavras, entrada, saida);
  for (const p of locais) p.texto = estilo.maiusculas ? p.texto.toUpperCase() : p.texto;

  const grupos = [];
  let atual = [];
  for (const p of locais) {
    if (atual.length) {
      const anterior = atual[atual.length - 1];
      if (atual.length >= preset.palavras || p.inicio - anterior.fim > PAUSA_QUEBRA
        || terminaFrase(anterior.texto)
        || quebrarLinhas([...atual, p].map((q) => q.texto), limite, preset.linhas) === null) {
        grupos.push(atual);
        atual = [];
      }
    }
    atual.push(p);
  }
  if (atual.length) grupos.push(atual);

  const telas = [];
  grupos.forEach((grupo, n) => {
    let fim = Math.min(grupo[grupo.length - 1].fim + SOBRA_FINAL, duracao);
    if (n + 1 < grupos.length) {
      const proxima = grupos[n + 1][0].inicio;
      fim = Math.min(fim, proxima);
      if (proxima - fim < EMENDA) fim = proxima;
    }
    const inicio = arred(grupo[0].inicio, 2);
    fim = arred(fim, 2);
    if (fim <= inicio) return;
    const exibidas = grupo.map((p) => ({ texto: p.texto, inicio: arred(p.inicio, 2), fim: arred(p.fim, 2) }));
    let destaques = null;
    if (preset.destaque) {
      destaques = exibidas.map((p, k) => {
        const a = Math.max(p.inicio, inicio);
        const b = Math.min(k + 1 < exibidas.length ? exibidas[k + 1].inicio : fim, fim);
        return [a, Math.max(a, b)];
      });
    }
    telas.push({
      inicio, fim, palavras: exibidas,
      linhas: quebrarLinhas(grupo.map((p) => p.texto), limite, preset.linhas),
      destaques,
    });
  });
  return telas;
}

export function diagramar(tela, estilo, largura, altura) {
  const preset = PRESETS[estilo.preset];
  const fonte = FONTES[preset.fonte];
  const { caixa } = preset;
  const textos = tela.linhas.map((linha) => linha.map((i) => tela.palavras[i].texto).join(' '));
  const larguras = textos.map((t) => larguraEm(t, preset.fonte));

  let em = Math.min(largura, altura) * preset.tamanho * FATOR_TAMANHO[estilo.tamanho];
  const lado = caixa ? caixa.folga : preset.contorno;
  const ocupado = (Math.max(...larguras) + 2 * lado) * em;
  const escala = Math.min(1, Math.floor(largura * LARGURA_UTIL / ocupado * 1000) / 1000);
  em = em * escala;
  const contorno = preset.contorno * em;
  const passo = preset.entrelinha * em;
  const meio = ALTURA_MAIUSCULA / 2 * em;
  const n = textos.length;

  let base = altura * POSICOES[estilo.posicao] + meio - (n - 1) * passo / 2;
  let acima;
  let abaixo;
  if (caixa) {
    acima = meio + caixa.altura / 2 * em;
    abaixo = caixa.altura / 2 * em - meio;
  } else {
    acima = ACIMA * em + contorno;
    abaixo = ABAIXO * em + contorno;
  }
  const topo = base - acima;
  const fundo = base + (n - 1) * passo + abaixo;
  const minimo = altura * LIMITE_TOPO;
  const maximo = altura * LIMITE_BASE;
  if (fundo - topo > maximo - minimo) base += (minimo + maximo) / 2 - (topo + fundo) / 2;
  else if (fundo > maximo) base -= fundo - maximo;
  else if (topo < minimo) base += minimo - topo;

  const linhas = [];
  const caixas = [];
  textos.forEach((texto, i) => {
    const b = base + i * passo;
    linhas.push({
      texto, palavras: [...tela.linhas[i]], x: arred(largura / 2, 2),
      y: arred(b - DESLOCAMENTO_ASS * em, 2), base: arred(b, 2), largura: arred(larguras[i] * em, 2),
    });
    if (caixa) {
      caixas.push({
        x: arred(largura / 2, 2), y: arred(b - meio, 2), largura: arred((larguras[i] + 2 * caixa.folga) * em, 2),
        altura: arred(caixa.altura * em, 2), raio: arred(caixa.raio * em, 2),
      });
    }
  });
  return {
    fonte: fonte.familia, peso: fonte.peso, em: arred(em, 2), fs: arred(em * FATOR_ASS, 2),
    contorno: arred(contorno, 2), escala, linhas, caixas,
  };
}

export function escalaPop(t) {
  if (t <= POP[0][0]) return POP[0][1];
  for (let i = 0; i + 1 < POP.length; i++) {
    const [t0, e0] = POP[i];
    const [t1, e1] = POP[i + 1];
    if (t < t1) return e0 + (e1 - e0) * (t - t0) / (t1 - t0);
  }
  return POP[POP.length - 1][1];
}

export function legendasDoTrecho(palavras, entrada, saida, estilo, largura, altura) {
  return montarTelas(palavras, entrada, saida, estilo).map((tela) => ({ tela, diagrama: diagramar(tela, estilo, largura, altura) }));
}

// Realinhamento do texto corrigido

function distribuir(textos, a, b) {
  const pesos = textos.map(tamanho);
  const total = pesos.reduce((s, p) => s + p, 0);
  let acumulado = 0;
  return textos.map((texto, i) => {
    const inicio = a + (b - a) * acumulado / total;
    acumulado += pesos[i];
    const fim = a + (b - a) * acumulado / total;
    return { inicio: arred(inicio, 3), fim: arred(fim, 3), texto };
  });
}

// Mesmo número de palavras: cada uma mantém o tempo. Se mudou, as palavras iguais do começo e do fim mantêm o
// tempo e só o trecho alterado é redistribuído, na proporção do tamanho de cada palavra. `intervalo` ([a, b]) é
// usado quando ainda não havia palavra nenhuma.
export function realinhar(palavras, texto, intervalo = null) {
  const novas = texto.normalize('NFC').split(/\s+/u).filter(Boolean);
  if (!novas.length) return [];
  if (novas.length === palavras.length) return palavras.map((p, i) => ({ inicio: p.inicio, fim: p.fim, texto: novas[i] }));
  if (!palavras.length) return intervalo ? distribuir(novas, intervalo[0], intervalo[1]) : [];
  const antigas = palavras.map((p) => p.texto);
  let i = 0;
  while (i < novas.length && i < antigas.length && novas[i] === antigas[i]) i++;
  let j = 0;
  while (j < novas.length - i && j < antigas.length - i && novas[novas.length - 1 - j] === antigas[antigas.length - 1 - j]) j++;
  if (i + j === antigas.length) {
    if (i > 0) i--;
    else j--;
  }
  const meioAntigo = palavras.slice(i, palavras.length - j);
  const meioNovo = novas.slice(i, novas.length - j);
  const meio = meioNovo.length ? distribuir(meioNovo, meioAntigo[0].inicio, meioAntigo[meioAntigo.length - 1].fim) : [];
  return [...palavras.slice(0, i).map((p) => ({ ...p })), ...meio, ...palavras.slice(palavras.length - j).map((p) => ({ ...p }))];
}

// Desenho no canvas

export function telaEm(legendas, t) {
  return legendas.find((l) => t >= l.tela.inicio && t < l.tela.fim) || null;
}

function rgba(cor, opacidade = 1) {
  const n = parseInt(cor.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${opacidade})`;
}

// O mesmo retângulo de cantos arredondados do .ass (curvas de Bézier), com o centro em 0,0.
function caminhoCaixa(ctx, largura, altura, raio) {
  const r = Math.min(raio, largura / 2, altura / 2);
  const c = r * 0.4477;
  const x = -largura / 2;
  const y = -altura / 2;
  const w = largura;
  const h = altura;
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.bezierCurveTo(x + w - c, y, x + w, y + c, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.bezierCurveTo(x + w, y + h - c, x + w - c, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.bezierCurveTo(x + c, y + h, x, y + h - c, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.bezierCurveTo(x, y + c, x + c, y, x + r, y);
  ctx.closePath();
}

// Desenha uma tela no instante t (segundos do trecho). k: pixels do canvas por pixel do vídeo exportado.
// Como no libass: as caixas por baixo, depois o contorno de todas as letras e por cima o preenchimento.
export function desenharLegenda(ctx, { tela, diagrama }, estilo, t, k) {
  const preset = PRESETS[estilo.preset];
  const s = estilo.animacao ? escalaPop(t - tela.inicio) : 1;
  ctx.save();
  if (preset.caixa) {
    ctx.fillStyle = rgba(preset.caixa.cor, preset.caixa.opacidade);
    for (const c of diagrama.caixas) {
      ctx.save();
      ctx.translate(c.x * k, c.y * k);
      ctx.scale(s * k, s * k);
      caminhoCaixa(ctx, c.largura, c.altura, c.raio);
      ctx.fill();
      ctx.restore();
    }
  }
  ctx.font = `${diagrama.peso} ${diagrama.em * k}px "${FAMILIA_CANVAS}"`;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'alphabetic';
  if ('fontKerning' in ctx) ctx.fontKerning = 'normal';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = PRETO;
  const posicoes = diagrama.linhas.map((linha) => {
    const textos = linha.palavras.map((i) => tela.palavras[i].texto);
    const inicio = -ctx.measureText(linha.texto).width / 2;
    return textos.map((_, j) => inicio + (j ? ctx.measureText(`${textos.slice(0, j).join(' ')} `).width : 0));
  });
  const emLinha = (linha, desenho) => {
    ctx.save();
    ctx.translate(linha.x * k, linha.y * k);
    ctx.scale(s, s);
    desenho((linha.base - linha.y) * k);
    ctx.restore();
  };
  if (diagrama.contorno > 0) {
    // A espessura do contorno não muda com o pop, como no libass.
    ctx.lineWidth = 2 * diagrama.contorno * k / s;
    diagrama.linhas.forEach((linha, n) => emLinha(linha, (y) => ctx.strokeText(linha.texto, posicoes[n][0], y)));
  }
  diagrama.linhas.forEach((linha, n) => emLinha(linha, (y) => {
    linha.palavras.forEach((i, j) => {
      const faixa = tela.destaques?.[i];
      ctx.fillStyle = faixa && t >= faixa[0] && t < faixa[1] ? preset.destaque : preset.cor;
      ctx.fillText(tela.palavras[i].texto, posicoes[n][j], y);
    });
  }));
  ctx.restore();
}
