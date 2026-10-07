// Legendas automáticas na tela: a seção do painel do projeto (ligar, estilo, tamanho, posição), a legenda do clipe
// selecionado (corrigir o texto), a transcrição em segundo plano e o desenho na prévia e na linha do tempo.
// Não guarda o projeto: lê e altera pelo `app`, que cuida do desfazer e do salvamento automático.

import { api } from './api.js';
import { icone } from './icones.js';
import { ESTILO_PADRAO, FAMILIA_CANVAS, desenharLegenda, legendasDoTrecho, realinhar, telaEm } from './legendas.js';
import { avisar, el } from './util.js';

const ESTILOS = [
  ['destaque', 'Destaque', 'A palavra falada em amarelo'],
  ['uma_palavra', 'Uma palavra', 'Gigante, uma de cada vez'],
  ['classica', 'Clássica', 'A frase em branco'],
  ['caixa', 'Caixa', 'Texto sobre fundo escuro'],
];
const TAMANHOS = [['P', 'P', 'Pequeno'], ['M', 'M', 'Médio'], ['G', 'G', 'Grande']];
const POSICOES = [['alto', 'Acima', 'Na parte de cima do vídeo'], ['centro', 'Centro', 'No meio da tela'],
  ['baixo', 'Abaixo do rosto', 'Logo abaixo do rosto, acima da legenda do Reels']];
const IDIOMAS = [['auto', 'Detectar sozinho'], ['pt', 'Português'], ['en', 'Inglês'], ['es', 'Espanhol']];
const IDIOMA_DO_TEXTO = { auto: 'pt-BR', pt: 'pt-BR', en: 'en', es: 'es' };
const SOBREPOSICAO_MINIMA = 0.02; // igual à do algoritmo: palavra que mal encosta no corte fica de fora
const MAX_LETRAS = 80; // por palavra, o mesmo limite do servidor
const AMOSTRA = [{ inicio: 0, fim: 0.3, texto: 'Isso' }, { inicio: 0.3, fim: 0.6, texto: 'muda' }, { inicio: 0.6, fim: 0.9, texto: 'tudo' }];

const ativo = (trabalho) => trabalho && (trabalho.estado === 'na_fila' || trabalho.estado === 'transcrevendo');
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

function segmentado(rotulo, opcoes, atual, aoEscolher) {
  return el('div', { class: 'segmentado', role: 'radiogroup', 'aria-label': rotulo },
    ...opcoes.map(([valor, texto, titulo]) => el('button', {
      class: valor === atual ? 'ativo' : '', role: 'radio', 'aria-checked': String(valor === atual), title: titulo,
      onclick: () => { if (valor !== atual) aoEscolher(valor); },
    }, texto)));
}

// Separa as palavras da mídia em antes, dentro e depois do corte do trecho.
function separar(item, palavras) {
  const partes = { antes: [], dentro: [], depois: [] };
  for (const p of palavras) {
    const sobra = Math.min(p.fim, item.saida) - Math.max(p.inicio, item.entrada);
    if (sobra > SOBREPOSICAO_MINIMA) partes.dentro.push(p);
    else partes[p.inicio < item.entrada ? 'antes' : 'depois'].push(p);
  }
  return partes;
}

export class Legendas {
  // app: { projeto(), formato(), editar(fn), mesclar(midiaId, palavras), instantaneo(), guardarPasso(antes),
  //        desenharTopo(), agendarSalvamento(), garantirSalvo(), atualizar(), redesenhar() }
  constructor(app) {
    this.app = app;
    this.trabalho = null;
    this.aplicadas = 0;
    this.acompanhando = false;
    this.edicao = null; // a correção de texto em andamento: { area, projetoId, itemId, antes, timer, pendente }
    this.cache = new WeakMap();
    this.fonteCarregada = !document.fonts;
    this.tamanhoDoModelo = 'cerca de 1,6 GB';
    if (document.fonts) {
      Promise.all([900, 800].map((peso) => document.fonts.load(`${peso} 40px "${FAMILIA_CANVAS}"`)))
        .catch(() => {})
        .then(() => {
          this.fonteCarregada = true;
          this.app.atualizar();
          this.app.redesenhar();
        });
    }
    api.sobreLegendas().then((sobre) => { this.tamanhoDoModelo = sobre.tamanho_do_modelo; }).catch(() => {});
  }

  estilo() {
    return { ...ESTILO_PADRAO, ...this.app.projeto().estilo_legenda };
  }

  // Telas de legenda de um trecho da linha do tempo (null se ele fica sem legenda). Guardadas por lista de
  // palavras: cada edição troca a lista, então o que mudou é recalculado e o resto é reaproveitado.
  legendasDe(item) {
    const projeto = this.app.projeto();
    const palavras = projeto.legendas_ativas ? projeto.legendas?.[item.midia_id] : null;
    if (!palavras?.length) return null;
    const { largura, altura } = this.app.formato();
    const estilo = this.estilo();
    const chave = `${item.entrada}|${item.saida}|${largura}x${altura}|${JSON.stringify(estilo)}`;
    let guardadas = this.cache.get(palavras);
    if (!guardadas) this.cache.set(palavras, (guardadas = new Map()));
    if (!guardadas.has(chave)) {
      if (guardadas.size > 50) guardadas.clear();
      guardadas.set(chave, legendasDoTrecho(palavras, item.entrada, item.saida, estilo, largura, altura));
    }
    return guardadas.get(chave);
  }

  // Prévia: desenha a tela do instante (tempo da linha do tempo) por cima do vídeo.
  desenharNaPrevia(ctx, segmento, tempo, larguraCanvas) {
    if (!segmento || !this.fonteCarregada) return;
    const lista = this.legendasDe(segmento.item);
    if (!lista) return;
    const t = tempo - segmento.inicio;
    const atual = telaEm(lista, t);
    if (atual) desenharLegenda(ctx, atual, this.estilo(), t, larguraCanvas / this.app.formato().largura);
  }

  // Linha do tempo: o texto de cada tela, para a faixa fina por cima das miniaturas.
  telasDaLinha(segmento) {
    const lista = this.legendasDe(segmento.item);
    return lista && lista.map(({ tela }) => ({ inicio: tela.inicio, fim: tela.fim, texto: tela.palavras.map((p) => p.texto).join(' ') }));
  }

  pendente(midiaId) {
    return ativo(this.trabalho) && this.trabalho.pendentes.includes(midiaId);
  }

  // Clipes que o trabalho ainda vai transcrever: o salvamento não manda a legenda que a tela tem deles, senão
  // desfaria no servidor uma transcrição nova que chegou lá e que a tela ainda não buscou.
  emTranscricao(projetoId) {
    const t = this.trabalho;
    return ativo(t) && t.projeto_id === projetoId ? t.pendentes : [];
  }

  // Transcrição em segundo plano

  async aoAbrirProjeto(projeto) {
    this.trabalho = null;
    this.aplicadas = 0;
    // Uma transcrição que continuou no servidor enquanto a página recarregava (ou outro projeto estava aberto) volta a
    // ser acompanhada: senão a tela salvaria o texto antigo por cima do que ela ainda vai gravar.
    const andando = await api.transcricaoEmAndamento(projeto.id).catch(() => null);
    if (this.app.projeto() !== projeto) return;
    if (andando) this._acompanhar(andando);
    // Retoma o que ficou sem legenda (o Estúdio pode ter sido fechado no meio da transcrição).
    if (projeto.legendas_ativas && projeto.midias.some((m) => !(m.id in projeto.legendas) && !this.pendente(m.id))) {
      this.transcrever(null, false);
    }
  }

  aoImportar(midia) {
    if (this.app.projeto().legendas_ativas) this.transcrever([midia.id], false);
  }

  async transcrever(midias, refazer) {
    try {
      await this.app.garantirSalvo(); // a transcrição usa o idioma salvo no projeto
      this._acompanhar(await api.transcrever(this.app.projeto().id, midias, refazer));
    } catch (erro) {
      avisar(erro.message, 'erro', 8000);
    }
  }

  async _acompanhar(trabalho) {
    if (this.trabalho?.id !== trabalho.id) this.aplicadas = 0;
    this.trabalho = trabalho;
    this._aplicar(trabalho);
    this.app.atualizar();
    if (this.acompanhando) return; // o laço que já está rodando pega a novidade
    this.acompanhando = true;
    try {
      while (ativo(this.trabalho) && this.trabalho.projeto_id === this.app.projeto().id) {
        await esperar(600);
        const id = this.trabalho?.id;
        if (!id) break;
        const atualizado = await api.transcricao(id);
        if (this.trabalho?.id !== id) continue; // outro trabalho tomou o lugar enquanto esperava
        const anterior = this.trabalho;
        this.trabalho = atualizado;
        // Redesenhar o painel a cada consulta fecharia uma lista aberta nele: só quando algo mudou de verdade.
        if (this._aplicar(atualizado) || anterior.estado !== atualizado.estado
          || anterior.pendentes.join() !== atualizado.pendentes.join()) this.app.atualizar();
        else this._mostrarAndamento();
      }
    } catch (erro) {
      avisar(`Não consegui acompanhar a transcrição: ${erro.message}`, 'erro', 8000);
    } finally {
      this.acompanhando = false;
    }
    const fim = this.trabalho;
    if (!fim || fim.avisado || fim.projeto_id !== this.app.projeto().id) return;
    fim.avisado = true;
    if (fim.estado === 'erro') avisar(fim.erro, 'erro', 15000);
    else if (fim.estado === 'pronta' && fim.concluidas.length) avisar('Legendas prontas. Para corrigir uma palavra, clique no clipe e edite o texto no painel da direita.');
  }

  // As transcrições chegam sem passar pelo desfazer: são dados novos, não uma edição. Devolve quantas chegaram.
  // O servidor manda a legenda como está gravada, já com as correções feitas depois da transcrição.
  _aplicar(trabalho) {
    if (trabalho.projeto_id !== this.app.projeto().id) return 0;
    const novas = trabalho.concluidas.slice(this.aplicadas);
    for (const midiaId of novas) {
      if (trabalho.resultados[midiaId]) this.app.mesclar(midiaId, trabalho.resultados[midiaId]);
    }
    this.aplicadas = trabalho.concluidas.length;
    return novas.length;
  }

  _mostrarAndamento() {
    for (const caixa of document.querySelectorAll('.andamento-legendas')) {
      caixa.querySelector('.barra span').style.width = `${Math.round(this.trabalho.progresso * 100)}%`;
      caixa.querySelector('p').textContent = this.trabalho.etapa;
    }
  }

  // Painel do projeto

  secaoDoProjeto() {
    const p = this.app.projeto();
    const estilo = this.estilo();
    const mudarEstilo = (mudanca) => this.app.editar((proj) => { proj.estilo_legenda = { ...estilo, ...mudanca }; });
    const chave = el('label', { class: 'opcao caixa chave-legendas' },
      el('input', { type: 'checkbox', role: 'switch', checked: p.legendas_ativas, onchange: (e) => this.ligar(e.target.checked) }),
      el('span', {}, el('strong', {}, 'Legendas automáticas'),
        el('small', {}, 'Escreve na tela o que é falado, palavra por palavra. Muita gente assiste sem som.')));
    const secao = [el('h4', { class: 'secao-titulo' }, 'Legendas'), chave, this._andamento()];
    if (!p.legendas_ativas) {
      secao.push(el('p', { class: 'nota' }, `Na primeira vez, o Estúdio baixa o modelo de transcrição (${this.tamanhoDoModelo}), `
        + 'o que pode levar alguns minutos. Depois tudo funciona sem internet, no seu computador.'));
      return el('div', { class: 'secao-legendas' }, ...secao);
    }
    secao.push(
      el('div', { class: 'campo' }, el('span', { class: 'rotulo' }, 'Estilo'),
        el('div', { class: 'estilos-legenda' }, ...ESTILOS.map(([valor, nome, descricao]) => el('button', {
          class: `estilo-legenda${valor === estilo.preset ? ' ativo' : ''}`, title: descricao, 'aria-pressed': String(valor === estilo.preset),
          onclick: () => { if (valor !== estilo.preset) mudarEstilo({ preset: valor }); },
        }, this._amostra(valor, estilo), el('span', {}, nome))))),
      el('div', { class: 'campo' }, el('span', { class: 'rotulo' }, 'Tamanho'),
        segmentado('Tamanho da legenda', TAMANHOS, estilo.tamanho, (valor) => mudarEstilo({ tamanho: valor }))),
      el('div', { class: 'campo' }, el('span', { class: 'rotulo' }, 'Posição'),
        segmentado('Posição da legenda', POSICOES, estilo.posicao, (valor) => mudarEstilo({ posicao: valor })),
        el('small', { class: 'nota' }, 'Em close, o centro da tela é o rosto: “Abaixo do rosto” não cobre a boca nem a interface do Reels.')),
      el('label', { class: 'opcao caixa' },
        el('input', { type: 'checkbox', checked: estilo.maiusculas, onchange: (e) => mudarEstilo({ maiusculas: e.target.checked }) }),
        el('span', {}, el('strong', {}, 'Tudo em maiúsculas'))),
      el('label', { class: 'opcao caixa' },
        el('input', { type: 'checkbox', checked: estilo.animacao, onchange: (e) => mudarEstilo({ animacao: e.target.checked }) }),
        el('span', {}, el('strong', {}, 'Animação ao aparecer'), el('small', {}, 'Cada tela de legenda entra com um pulinho.'))),
      el('label', { class: 'campo' }, el('span', { class: 'rotulo' }, 'Idioma da fala'),
        el('select', { onchange: (e) => this.app.editar((proj) => { proj.idioma_legenda = e.target.value; }) },
          ...IDIOMAS.map(([valor, nome]) => el('option', { value: valor, selected: valor === p.idioma_legenda }, nome))),
        el('small', { class: 'nota' }, 'Vale para as próximas transcrições. Para refazer as que já existem, use o botão abaixo.')),
      el('button', {
        class: 'botao', disabled: ativo(this.trabalho) || !p.midias.length, title: 'Útil depois de trocar o idioma',
        onclick: () => {
          if (confirm('Transcrever todos os clipes de novo? As correções que você fez no texto das legendas serão perdidas.')) this.transcrever(null, true);
        },
      }, icone('desfazer', 15), 'Transcrever todos de novo'));
    return el('div', { class: 'secao-legendas' }, ...secao);
  }

  ligar(ligadas) {
    this.app.editar((proj) => { proj.legendas_ativas = ligadas; });
    if (ligadas) this.transcrever(null, false);
  }

  _andamento() {
    const t = this.trabalho;
    if (t?.estado === 'erro' && t.projeto_id === this.app.projeto().id) {
      return el('div', { class: 'aviso erro-legendas', role: 'alert' }, icone('alerta', 14),
        el('div', {}, el('span', {}, t.erro),
          el('button', { class: 'botao pequeno', onclick: () => this.transcrever(null, false) }, 'Tentar de novo')));
    }
    if (!ativo(t)) return null;
    return el('div', { class: 'andamento-legendas', role: 'status' },
      el('div', { class: 'barra' }, el('span', { style: { width: `${Math.round(t.progresso * 100)}%` } })),
      el('p', {}, t.etapa));
  }

  // Cartão de estilo: a mesma legenda da prévia, desenhada pequena sobre um fundo escuro.
  _amostra(preset, estilo) {
    const densidade = Math.min(window.devicePixelRatio || 1, 2);
    const canvas = el('canvas', { class: 'amostra-legenda', width: Math.round(124 * densidade), height: Math.round(58 * densidade), 'aria-hidden': 'true' });
    const ctx = canvas.getContext('2d');
    const fundo = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    fundo.addColorStop(0, '#3b4256');
    fundo.addColorStop(1, '#1b1f2a');
    ctx.fillStyle = fundo;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!this.fonteCarregada) return canvas;
    const exemplo = { ...estilo, preset, posicao: 'centro', animacao: false };
    const t = 0.45; // "muda": a palavra destacada no estilo Destaque
    const atual = telaEm(legendasDoTrecho(AMOSTRA, 0, 1, exemplo, 1080, 1920), t);
    if (!atual) return canvas;
    // A amostra ocupa o cartão: o bloco (centrado em 540, 960 no quadro de 1080×1920) é ampliado até caber.
    const { linhas, caixas, em, contorno } = atual.diagrama;
    const largura = Math.max(...linhas.map((l) => l.largura), ...caixas.map((c) => c.largura)) + 2 * contorno;
    const altura = em * (1.4 + 1.2 * (linhas.length - 1));
    const k = Math.min(canvas.width * 0.84 / largura, canvas.height * 0.66 / altura);
    ctx.translate(canvas.width / 2 - 540 * k, canvas.height / 2 - 960 * k);
    desenharLegenda(ctx, atual, exemplo, t, k);
    return canvas;
  }

  // Painel do clipe selecionado

  secaoDoClipe(item, midia) {
    const p = this.app.projeto();
    const titulo = el('h4', { class: 'secao-titulo' }, 'Legenda deste clipe');
    const caixa = (...filhos) => el('div', { class: 'secao-legendas legenda-clipe' }, titulo, ...filhos);
    if (!p.legendas_ativas) {
      return caixa(el('p', { class: 'nota' }, 'As legendas automáticas estão desligadas.'),
        el('button', { class: 'botao', onclick: () => this.ligar(true) }, 'Ligar legendas automáticas'));
    }
    if (this.pendente(midia.id)) {
      return caixa(el('p', { class: 'nota' }, 'Transcrevendo este clipe…'), this._andamento());
    }
    if (!midia.tem_audio) return caixa(el('p', { class: 'nota' }, 'Este clipe não tem som, então fica sem legenda.'));
    if (!(midia.id in p.legendas)) {
      return caixa(el('p', { class: 'nota' }, 'Este clipe ainda não foi transcrito.'),
        el('button', { class: 'botao', onclick: () => this.transcrever([midia.id], false) }, 'Transcrever'));
    }
    return caixa(
      this._editorDeTexto(item, midia),
      el('p', { class: 'nota' }, 'Corrija aqui as palavras que saíram erradas. Cada palavra continua no tempo dela.'),
      el('button', {
        class: 'botao', onclick: () => {
          if (confirm('Transcrever este clipe de novo? As correções que você fez no texto dele serão perdidas.')) this.transcrever([midia.id], true);
        },
      }, icone('desfazer', 15), 'Transcrever de novo'));
  }

  // Enquanto se digita, a prévia acompanha e o projeto é salvo; o desfazer guarda a correção inteira como um passo.
  _editorDeTexto(item, midia) {
    const p = this.app.projeto();
    const area = el('textarea', {
      class: 'legenda-texto', rows: 4, spellcheck: 'true', lang: IDIOMA_DO_TEXTO[p.idioma_legenda] || 'pt-BR',
      placeholder: 'Nenhuma fala neste trecho. Escreva aqui para colocar uma legenda.', 'aria-label': 'Texto da legenda deste clipe',
      'data-item': item.id,
    });
    area.value = separar(item, p.legendas[midia.id] || []).dentro.map((w) => w.texto).join(' ');
    area.addEventListener('input', () => {
      if (this.edicao?.area !== area) {
        this.concluirEdicao();
        this.edicao = { area, projetoId: p.id, itemId: item.id, antes: this.app.instantaneo(), timer: null, pendente: false };
        this.app.desenharTopo(); // o Desfazer já vale para o que está sendo digitado
      }
      const edicao = this.edicao;
      clearTimeout(edicao.timer);
      edicao.pendente = true;
      edicao.timer = setTimeout(() => {
        edicao.pendente = false;
        this._aplicarTexto(edicao.itemId, area.value);
      }, 250);
    });
    area.addEventListener('blur', () => this.concluirEdicao());
    return area;
  }

  emEdicao() {
    return this.edicao !== null;
  }

  // O campo de texto da legenda deste item está com o cursor: redesenhar o painel tiraria o cursor de quem corrige.
  corrigindo(item) {
    const campo = document.activeElement;
    return Boolean(item) && Boolean(campo?.classList.contains('legenda-texto')) && campo.dataset.item === item.id;
  }

  // Encerra a correção de texto em andamento: aplica o que ainda não entrou no projeto e guarda o passo do desfazer.
  // Com `sair`, o campo também perde o cursor, porque outra ação vai mudar o painel (desfazer, tirar o clipe, trocar
  // de projeto...). Nada é redesenhado aqui: isso roda no clique de um botão, que seria trocado e perderia o clique.
  concluirEdicao(sair = false) {
    const edicao = this.edicao;
    this.edicao = null;
    if (edicao && edicao.projetoId === this.app.projeto()?.id) {
      clearTimeout(edicao.timer);
      if (edicao.pendente) this._aplicarTexto(edicao.itemId, edicao.area.value);
      this.app.guardarPasso(edicao.antes);
    }
    const campo = document.activeElement;
    if (sair && campo?.classList.contains('legenda-texto')) campo.blur();
  }

  _aplicarTexto(itemId, texto) {
    const p = this.app.projeto();
    const item = p.linha.find((i) => i.id === itemId);
    const midia = item && p.midias.find((m) => m.id === item.midia_id);
    if (!midia) return;
    const { antes, dentro, depois } = separar(item, p.legendas[midia.id] || []);
    const novas = realinhar(dentro, texto, [item.entrada, item.saida])
      .map((w) => ({
        inicio: Math.max(0, w.inicio), fim: Math.min(midia.duracao, w.fim),
        texto: [...w.texto].slice(0, MAX_LETRAS).join(''), // o servidor não aceita "palavra" maior (um link colado)
      }))
      .filter((w) => w.fim - w.inicio > 0.0005);
    const palavras = [...antes, ...novas, ...depois].sort((a, b) => a.inicio - b.inicio);
    if (JSON.stringify(palavras) === JSON.stringify(p.legendas[midia.id])) return; // só espaços mudaram
    p.legendas = { ...p.legendas, [midia.id]: palavras };
    this.app.agendarSalvamento();
    this.app.redesenhar();
  }
}
