// Imita a API do D1 (prepare/bind/first/all/run) em cima do node:sqlite, só para os testes.
import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';

export function criarD1() {
  const db = new DatabaseSync(':memory:');
  for (const arq of ['0001_inicial.sql', '0002_players_e_indice.sql']) {
    db.exec(fs.readFileSync(new URL('../migrations/' + arq, import.meta.url), 'utf8'));
  }
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
