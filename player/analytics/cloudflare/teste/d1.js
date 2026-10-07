// Imita a API do D1 (prepare/bind/first/all/run) em cima do node:sqlite, só para os testes.
import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';

export const MIGRACOES = ['0001_inicial.sql', '0002_players_e_indice.sql', '0003_navegador.sql'];

/** SQL de todas as migrações, na ordem, como o index.js entrega ao criarApp. */
export const lerMigracoes = (nomes = MIGRACOES) => nomes.map((a) => fs.readFileSync(new URL('../migrations/' + a, import.meta.url), 'utf8')).join('\n');

/** Envolve um node:sqlite com a API do D1. `migracoes` é a lista de arquivos a aplicar antes (vazia = banco cru). */
export function envolver(db, migracoes = []) {
  for (const arq of migracoes) db.exec(fs.readFileSync(new URL('../migrations/' + arq, import.meta.url), 'utf8'));
  return {
    prepare(sql) {
      const st = db.prepare(sql);
      const stmt = {
        args: [],
        bind(...args) { stmt.args = args.map((a) => (a === undefined ? null : a)); return stmt; },
        async first(coluna) { const r = st.get(...stmt.args); if (r == null) return null; return coluna ? r[coluna] : { ...r }; },
        async all() { return { results: st.all(...stmt.args).map((r) => ({ ...r })), success: true }; },
        async run() { const r = st.run(...stmt.args); return { success: true, meta: { changes: r.changes } }; },
      };
      return stmt;
    },
    async batch(stmts) { return Promise.all(stmts.map((s) => s.run())); },
    async exec(sql) { db.exec(sql); },
  };
}

export function criarD1(migracoes = MIGRACOES) {
  return envolver(new DatabaseSync(':memory:'), migracoes);
}
