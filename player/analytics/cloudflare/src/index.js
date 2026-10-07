import painel from '../painel.html';
import esquema1 from '../migrations/0001_inicial.sql';
import esquema2 from '../migrations/0002_players_e_indice.sql';
import esquema3 from '../migrations/0003_navegador.sql';
import { criarApp } from './app.js';

export default criarApp({ painel, esquema: esquema1 + '\n' + esquema2 + '\n' + esquema3 });
