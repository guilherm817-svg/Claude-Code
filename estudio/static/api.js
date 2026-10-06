// Conversa com o servidor do Estúdio. Os pedidos que mudam o projeto entram numa fila, um de cada vez, para um
// salvamento nunca atropelar uma importação.

const CABECALHO = { 'X-Estudio': '1' };
let fila = Promise.resolve();

function enfileirar(tarefa) {
  const resultado = fila.then(tarefa, tarefa);
  fila = resultado.catch(() => {});
  return resultado;
}

function mensagemDeErro(dados, status) {
  const detalhe = dados?.detail;
  if (typeof detalhe === 'string') return detalhe;
  if (Array.isArray(detalhe) && detalhe.length) return detalhe.map((d) => d.msg).join(' ');
  return status ? `O Estúdio respondeu com erro ${status}.` : 'Sem conexão com o Estúdio. A janela dele ainda está aberta?';
}

async function pedir(metodo, url, corpo) {
  const opcoes = { method: metodo, headers: metodo === 'GET' ? {} : { ...CABECALHO } };
  if (corpo !== undefined) {
    opcoes.headers['Content-Type'] = 'application/json';
    opcoes.body = JSON.stringify(corpo);
  }
  let resposta;
  try {
    resposta = await fetch(url, opcoes);
  } catch {
    throw new Error(mensagemDeErro(null, 0));
  }
  if (resposta.status === 204) return null;
  const dados = await resposta.json().catch(() => null);
  if (!resposta.ok) throw new Error(mensagemDeErro(dados, resposta.status));
  return dados;
}

function enviarArquivo(projetoId, arquivo, aoProgresso) {
  return new Promise((resolver, rejeitar) => {
    const pedido = new XMLHttpRequest();
    pedido.open('POST', `/api/projetos/${projetoId}/midias`);
    pedido.setRequestHeader('X-Estudio', '1');
    pedido.upload.onprogress = (e) => e.lengthComputable && aoProgresso?.(e.loaded / e.total);
    pedido.onload = () => {
      let dados = null;
      try { dados = JSON.parse(pedido.responseText); } catch { /* resposta vazia */ }
      if (pedido.status >= 200 && pedido.status < 300) resolver(dados);
      else rejeitar(new Error(mensagemDeErro(dados, pedido.status)));
    };
    pedido.onerror = () => rejeitar(new Error(mensagemDeErro(null, 0)));
    const formulario = new FormData();
    formulario.append('arquivo', arquivo, arquivo.name);
    pedido.send(formulario);
  });
}

// O que a tela pode alterar num projeto (o resto é do servidor).
export function ajustesDe(projeto) {
  const { nome, formato, enquadramento, igualar_volume, linha, legendas_ativas, idioma_legenda, estilo_legenda, legendas } = projeto;
  return { nome, formato, enquadramento, igualar_volume, linha, legendas_ativas, idioma_legenda, estilo_legenda, legendas };
}

export const api = {
  config: () => pedir('GET', '/api/config'),
  listar: () => pedir('GET', '/api/projetos'),
  abrir: (id) => pedir('GET', `/api/projetos/${id}`),
  criar: (nome) => enfileirar(() => pedir('POST', '/api/projetos', { nome })),
  salvar: (projeto) => enfileirar(() => pedir('PUT', `/api/projetos/${projeto.id}`, ajustesDe(projeto))),
  excluir: (id) => enfileirar(() => pedir('DELETE', `/api/projetos/${id}`)),
  importar: (id, arquivo, aoProgresso) => enfileirar(() => enviarArquivo(id, arquivo, aoProgresso)),
  removerMidia: (id, midiaId) => enfileirar(() => pedir('DELETE', `/api/projetos/${id}/midias/${midiaId}`)),
  onda: (id, midiaId) => pedir('GET', `/api/projetos/${id}/midias/${midiaId}/onda`),
  exportar: (id) => enfileirar(() => pedir('POST', `/api/projetos/${id}/exportar`)),
  exportacao: (exportacaoId) => pedir('GET', `/api/exportacoes/${exportacaoId}`),
  cancelar: (exportacaoId) => pedir('POST', `/api/exportacoes/${exportacaoId}/cancelar`),
  exportados: (id) => pedir('GET', `/api/projetos/${id}/exportados`),
  abrirPasta: (id) => pedir('POST', `/api/projetos/${id}/abrir-pasta`),
  transcrever: (id, midias, refazer) => enfileirar(() => pedir('POST', `/api/projetos/${id}/legendas`, { midias, refazer })),
  transcricao: (trabalhoId) => pedir('GET', `/api/legendas/${trabalhoId}`),
  sobreLegendas: () => pedir('GET', '/api/legendas'),
  urlArquivo: (id, midiaId) => `/api/projetos/${id}/midias/${midiaId}/arquivo`,
  urlTira: (id, midiaId) => `/api/projetos/${id}/midias/${midiaId}/tira.jpg`,
  urlExportado: (id, nome) => `/api/projetos/${id}/exportados/${encodeURIComponent(nome)}`,
};
