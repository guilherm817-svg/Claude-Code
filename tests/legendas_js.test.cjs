// As legendas da prévia (estudio/static/legendas.js) têm que sair iguais às da exportação (estudio/legendas.py).
// Este teste roda os mesmos casos de tests/casos_legendas.json que o pytest. Rode na raiz do projeto:
// node tests/legendas_js.test.cjs
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const RAIZ = path.dirname(__dirname);
const CASOS = JSON.parse(fs.readFileSync(path.join(__dirname, 'casos_legendas.json'), 'utf8'));

// Módulo ES dentro de um .cjs: carregado de uma URL data:, por isso o legendas.js não pode importar nada.
async function carregar() {
  const codigo = fs.readFileSync(path.join(RAIZ, 'estudio', 'static', 'legendas.js'));
  return import(`data:text/javascript;base64,${codigo.toString('base64')}`);
}

function comparar(obtido, esperado, caminho = '') {
  if (typeof esperado === 'number') {
    assert.strictEqual(typeof obtido, 'number', `${caminho}: esperava número, veio ${JSON.stringify(obtido)}`);
    assert.ok(Math.abs(obtido - esperado) < 1e-9, `${caminho}: ${obtido} ≠ ${esperado}`);
  } else if (Array.isArray(esperado)) {
    assert.ok(Array.isArray(obtido), `${caminho}: esperava lista, veio ${JSON.stringify(obtido)}`);
    assert.strictEqual(obtido.length, esperado.length, `${caminho}: tamanho ${obtido.length} ≠ ${esperado.length}`);
    esperado.forEach((valor, i) => comparar(obtido[i], valor, `${caminho}[${i}]`));
  } else if (esperado && typeof esperado === 'object') {
    assert.deepStrictEqual(Object.keys(obtido).sort(), Object.keys(esperado).sort(), `${caminho}: chaves diferentes`);
    for (const chave of Object.keys(esperado)) comparar(obtido[chave], esperado[chave], `${caminho}.${chave}`);
  } else {
    assert.strictEqual(obtido, esperado, `${caminho}: ${JSON.stringify(obtido)} ≠ ${JSON.stringify(esperado)}`);
  }
}

test('telas e diagramas iguais aos do Python', async (t) => {
  const L = await carregar();
  for (const caso of CASOS.casos) {
    await t.test(caso.nome, () => {
      const telas = L.montarTelas(caso.palavras, caso.entrada, caso.saida, caso.estilo);
      comparar(telas, caso.telas, 'telas');
      comparar(telas.map((tela) => L.diagramar(tela, caso.estilo, caso.largura, caso.altura)), caso.diagramas, 'diagramas');
    });
  }
});

test('realinhamento do texto corrigido igual ao do Python', async (t) => {
  const L = await carregar();
  for (const caso of CASOS.realinhar) {
    await t.test(caso.nome, () => comparar(L.realinhar(caso.palavras, caso.texto, caso.intervalo), caso.esperado, 'palavras'));
  }
});

test('animação de entrada igual à do .ass', async () => {
  const L = await carregar();
  for (const [t, escala] of CASOS.pop) comparar(L.escalaPop(t), escala, `pop(${t})`);
});

test('as palavras da tela não mudam o texto salvo', async () => {
  const L = await carregar();
  const palavras = [{ inicio: 0, fim: 0.5, texto: 'olá' }];
  L.montarTelas(palavras, 0, 1, L.ESTILO_PADRAO);
  assert.strictEqual(palavras[0].texto, 'olá');
});
