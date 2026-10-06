-- Uma linha por sessão (carregamento de um player). Os eventos ficam contados em JSON na própria linha.
CREATE TABLE IF NOT EXISTS sessoes (
    sessao       TEXT PRIMARY KEY,
    player       TEXT NOT NULL,
    visitante    TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL DEFAULT '',
    referrer     TEXT NOT NULL DEFAULT '',
    origem       TEXT NOT NULL DEFAULT 'direto',
    utm_source   TEXT NOT NULL DEFAULT '',
    utm_medium   TEXT NOT NULL DEFAULT '',
    utm_campaign TEXT NOT NULL DEFAULT '',
    utm_content  TEXT NOT NULL DEFAULT '',
    utm_term     TEXT NOT NULL DEFAULT '',
    dispositivo  TEXT NOT NULL DEFAULT 'computador',
    user_agent   TEXT NOT NULL DEFAULT '',
    inicio       TEXT NOT NULL,
    dia          TEXT NOT NULL,
    ultimo       TEXT NOT NULL,
    duracao      REAL NOT NULL DEFAULT 0,
    max_tempo    REAL NOT NULL DEFAULT 0,
    com_som      INTEGER NOT NULL DEFAULT 0,
    terminou     INTEGER NOT NULL DEFAULT 0,
    assistido    TEXT NOT NULL DEFAULT '[]',
    segundos     REAL NOT NULL DEFAULT 0,
    pitch        REAL,
    eventos      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS sessoes_player_dia ON sessoes (player, dia);
