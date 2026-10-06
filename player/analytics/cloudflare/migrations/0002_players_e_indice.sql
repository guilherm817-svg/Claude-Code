-- Resumo por player (pitch e duração mais recentes, contagem de sessões), para o painel não varrer a tabela inteira.
CREATE TABLE IF NOT EXISTS players (
    player   TEXT PRIMARY KEY,
    pitch    REAL,
    duracao  REAL NOT NULL DEFAULT 0,
    primeiro TEXT NOT NULL,
    ultimo   TEXT NOT NULL,
    sessoes  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sessoes_dia ON sessoes (dia);
