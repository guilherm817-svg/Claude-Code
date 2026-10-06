import painel from '../painel.html';
import esquema from '../migrations/0001_inicial.sql';
import { criarApp } from './app.js';

export default criarApp({ painel, esquema });
