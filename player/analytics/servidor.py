"""Analytics do VSL Player: recebe os envios do `data-analytics`, guarda em SQLite e serve o painel de retenção.

Rode:   python player/analytics/servidor.py --porta 8080 --token um-segredo
Player: <div class="vsl-player" data-analytics="https://analytics.seusite.com/vsl" ...>
Painel: http://localhost:8080/?token=um-segredo

Só biblioteca padrão. Um arquivo SQLite (padrão: player/analytics/dados.sqlite) guarda tudo.
"""

from __future__ import annotations

import argparse
import csv
import hmac
import io
import json
import logging
import math
import os
import re
import sqlite3
import statistics
import sys
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PASTA = Path(__file__).resolve().parent
PAINEL = PASTA / "painel.html"
DADOS_PADRAO = PASTA / "dados.sqlite"

LIMITE_CORPO = 512 * 1024   # bytes por envio
MAX_EVENTOS = 500           # eventos por envio
MAX_FAIXAS = 5000           # faixas assistidas por sessão
MAX_TEXTO = 2000            # tamanho de url, referrer e user agent guardados
MAX_ID = 120                # tamanho de player, sessão e visitante
MAX_DIAS = 400              # dias na série diária
PONTOS_CURVA = 1200         # pontos máximos na curva de retenção
CAMINHOS_COLETA = {"/vsl", "/vsl/", "/coletar", "/coletar/", "/"}

ORIGENS_CONHECIDAS = [
    (r"(^|\.)facebook\.com$|^fb\.me$|^fb\.com$", "facebook"),
    (r"(^|\.)instagram\.com$", "instagram"),
    (r"(^|\.)youtube\.com$|^youtu\.be$", "youtube"),
    (r"(^|\.)tiktok\.com$", "tiktok"),
    (r"(^|\.)google\.[a-z.]+$", "google"),
    (r"^t\.co$|(^|\.)twitter\.com$|(^|\.)x\.com$", "x"),
    (r"(^|\.)whatsapp\.com$", "whatsapp"),
    (r"(^|\.)linkedin\.com$", "linkedin"),
]

log = logging.getLogger("vsl.analytics")

SCHEMA = """
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
    ultimo       TEXT NOT NULL,
    duracao      REAL NOT NULL DEFAULT 0,
    max_tempo    REAL NOT NULL DEFAULT 0,
    com_som      INTEGER NOT NULL DEFAULT 0,
    terminou     INTEGER NOT NULL DEFAULT 0,
    assistido    TEXT NOT NULL DEFAULT '[]',
    segundos     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sessoes_player_inicio ON sessoes (player, inicio);

CREATE TABLE IF NOT EXISTS eventos (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao   TEXT NOT NULL,
    player   TEXT NOT NULL,
    tipo     TEXT NOT NULL,
    ts       INTEGER NOT NULL DEFAULT 0,
    tempo    REAL NOT NULL DEFAULT 0,
    dados    TEXT NOT NULL DEFAULT '{}',
    recebido TEXT NOT NULL,
    UNIQUE (sessao, tipo, ts, dados)
);
CREATE INDEX IF NOT EXISTS eventos_sessao ON eventos (sessao);

CREATE TABLE IF NOT EXISTS players (
    player   TEXT PRIMARY KEY,
    pitch    REAL,
    duracao  REAL NOT NULL DEFAULT 0,
    primeiro TEXT NOT NULL,
    ultimo   TEXT NOT NULL
);
"""


# ----------------------------------------------------------------------------- cálculos


def unir_faixas(faixas) -> list[list[int]]:
    """Une faixas [[a, b], ...] de segundos (inclusivas) em faixas ordenadas, sem sobreposição."""
    limpas: list[tuple[int, int]] = []
    for faixa in faixas or []:
        try:
            a, b = int(faixa[0]), int(faixa[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if a < 0 or b < a:
            continue
        limpas.append((a, b))
    limpas.sort()
    saida: list[list[int]] = []
    for a, b in limpas:
        if saida and a <= saida[-1][1] + 1:
            saida[-1][1] = max(saida[-1][1], b)
        else:
            saida.append([a, b])
    return saida


def segundos_assistidos(faixas) -> int:
    return sum(b - a + 1 for a, b in faixas)


def curva_retencao(listas_de_faixas, duracao: float) -> list[int]:
    """Quantas sessões assistiram cada segundo, de 0 até a duração (inclusive)."""
    n = int(duracao) + 1
    if n <= 0:
        return []
    diferenca = [0] * (n + 1)
    for faixas in listas_de_faixas:
        for a, b in faixas:
            if a >= n:
                continue
            diferenca[a] += 1
            diferenca[min(b, n - 1) + 1] -= 1
    curva, acumulado = [], 0
    for i in range(n):
        acumulado += diferenca[i]
        curva.append(acumulado)
    return curva


def compactar_curva(curva: list[int], maximo: int = PONTOS_CURVA) -> tuple[int, list[float]]:
    """Reduz a curva a no máximo `maximo` pontos, tirando a média de cada bloco de `passo` segundos."""
    if len(curva) <= maximo:
        return 1, [float(v) for v in curva]
    passo = math.ceil(len(curva) / maximo)
    pontos = [round(sum(curva[i:i + passo]) / len(curva[i:i + passo]), 2) for i in range(0, len(curva), passo)]
    return passo, pontos


def dispositivo(user_agent: str) -> str:
    return "celular" if re.search(r"Mobi|Android|iPhone|iPad|iPod", user_agent or "", re.I) else "computador"


def utms(url: str) -> dict[str, str]:
    try:
        query = parse_qs(urlparse(url).query)
    except ValueError:
        query = {}
    return {chave: (query.get(chave) or [""])[0][:200].strip() for chave in
            ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term")}


def origem(utm_source: str, referrer: str) -> str:
    if utm_source:
        return utm_source.lower()
    try:
        host = (urlparse(referrer).hostname or "").lower()
    except ValueError:
        host = ""
    if not host:
        return "direto"
    host = host[4:] if host.startswith("www.") else host
    for padrao, nome in ORIGENS_CONHECIDAS:
        if re.search(padrao, host):
            return nome
    return host


def _texto(valor, maximo: int = MAX_TEXTO) -> str:
    if not isinstance(valor, str):
        return ""
    return "".join(c for c in valor[:maximo] if c >= " " or c == "\t").strip()


def _numero(valor, minimo: float = 0.0) -> float:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return minimo
    if math.isnan(n) or math.isinf(n):
        return minimo
    return max(minimo, n)


def _dia_valido(texto) -> str | None:
    if not texto:
        return None
    try:
        return date.fromisoformat(str(texto)[:10]).isoformat()
    except ValueError:
        return None


def validar_envio(dados) -> dict:
    """Confere e limpa um envio do player. Levanta ValueError se não servir."""
    if not isinstance(dados, dict):
        raise ValueError("o envio precisa ser um objeto JSON")
    player = _texto(dados.get("player"), MAX_ID)
    sessao = _texto(dados.get("session"), MAX_ID)
    if not player or not sessao:
        raise ValueError("faltam player e session")
    eventos = dados.get("events") or []
    faixas = dados.get("watched") or []
    if not isinstance(eventos, list) or not isinstance(faixas, list):
        raise ValueError("events e watched precisam ser listas")
    if len(eventos) > MAX_EVENTOS or len(faixas) > MAX_FAIXAS:
        raise ValueError("envio grande demais")
    limpos = []
    for ev in eventos:
        if not isinstance(ev, dict):
            continue
        tipo = _texto(ev.get("type"), 60)
        if not tipo:
            continue
        extras = {k: v for k, v in ev.items()
                  if k not in ("type", "ts", "time") and isinstance(k, str) and len(k) <= 40
                  and isinstance(v, (str, int, float, bool)) and not (isinstance(v, str) and len(v) > 300)}
        limpos.append({
            "tipo": tipo,
            "ts": int(_numero(ev.get("ts"))),
            "tempo": round(_numero(ev.get("time")), 2),
            "dados": json.dumps(extras, sort_keys=True, ensure_ascii=False),
        })
    pitch = dados.get("pitch")
    return {
        "player": player,
        "sessao": sessao,
        "visitante": _texto(dados.get("visitor"), MAX_ID),
        "url": _texto(dados.get("url")),
        "referrer": _texto(dados.get("referrer")),
        "duracao": round(_numero(dados.get("duration")), 2),
        "max_tempo": round(_numero(dados.get("maxTime")), 2),
        "com_som": 1 if dados.get("unmuted") else 0,
        "faixas": unir_faixas(faixas),
        "eventos": limpos,
        "pitch": None if pitch in (None, "", False) else _numero(pitch),
    }


# ----------------------------------------------------------------------------- banco


class Banco:
    def __init__(self, caminho: str | Path = ":memory:"):
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            if str(caminho) != ":memory:":
                self.con.execute("PRAGMA journal_mode=WAL")
            self.con.executescript(SCHEMA)

    def fechar(self) -> None:
        with self.lock:
            self.con.close()

    def registrar(self, dados: dict, user_agent: str = "", agora: datetime | None = None) -> None:
        """Guarda um envio do player: cria ou atualiza a sessão e acrescenta os eventos novos."""
        envio = validar_envio(dados)
        agora = agora or datetime.now()
        momento = agora.isoformat(timespec="seconds")
        terminou = 1 if any(ev["tipo"] == "ended" for ev in envio["eventos"]) else 0
        with self.lock, self.con:
            atual = self.con.execute(
                "SELECT assistido, max_tempo, com_som, duracao, terminou FROM sessoes WHERE sessao = ?",
                (envio["sessao"],),
            ).fetchone()
            if atual:
                faixas = unir_faixas(json.loads(atual["assistido"]) + envio["faixas"])
                self.con.execute(
                    "UPDATE sessoes SET ultimo = ?, duracao = ?, max_tempo = ?, com_som = ?, terminou = ?, "
                    "assistido = ?, segundos = ? WHERE sessao = ?",
                    (momento, max(atual["duracao"], envio["duracao"]), max(atual["max_tempo"], envio["max_tempo"]),
                     max(atual["com_som"], envio["com_som"]), max(atual["terminou"], terminou),
                     json.dumps(faixas), segundos_assistidos(faixas), envio["sessao"]),
                )
            else:
                faixas = envio["faixas"]
                marcas = utms(envio["url"])
                self.con.execute(
                    "INSERT INTO sessoes (sessao, player, visitante, url, referrer, origem, utm_source, utm_medium, "
                    "utm_campaign, utm_content, utm_term, dispositivo, user_agent, inicio, ultimo, duracao, max_tempo, "
                    "com_som, terminou, assistido, segundos) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (envio["sessao"], envio["player"], envio["visitante"], envio["url"], envio["referrer"],
                     origem(marcas["utm_source"], envio["referrer"]), marcas["utm_source"], marcas["utm_medium"],
                     marcas["utm_campaign"], marcas["utm_content"], marcas["utm_term"], dispositivo(user_agent),
                     _texto(user_agent, 500), momento, momento, envio["duracao"], envio["max_tempo"],
                     envio["com_som"], terminou, json.dumps(faixas), segundos_assistidos(faixas)),
                )
            self.con.executemany(
                "INSERT OR IGNORE INTO eventos (sessao, player, tipo, ts, tempo, dados, recebido) VALUES (?,?,?,?,?,?,?)",
                [(envio["sessao"], envio["player"], ev["tipo"], ev["ts"], ev["tempo"], ev["dados"], momento)
                 for ev in envio["eventos"]],
            )
            self.con.execute(
                "INSERT INTO players (player, pitch, duracao, primeiro, ultimo) VALUES (?,?,?,?,?) "
                "ON CONFLICT(player) DO UPDATE SET pitch = COALESCE(excluded.pitch, players.pitch), "
                "duracao = MAX(players.duracao, excluded.duracao), ultimo = excluded.ultimo",
                (envio["player"], envio["pitch"], envio["duracao"], momento, momento),
            )

    def players(self) -> list[dict]:
        with self.lock:
            linhas = self.con.execute(
                "SELECT p.player, p.pitch, p.duracao, p.primeiro, p.ultimo, "
                "(SELECT COUNT(*) FROM sessoes s WHERE s.player = p.player) AS sessoes "
                "FROM players p ORDER BY p.ultimo DESC"
            ).fetchall()
        return [dict(linha) for linha in linhas]

    @staticmethod
    def _filtro(player: str | None, de: str | None, ate: str | None, tabela: str = "") -> tuple[str, list]:
        condicoes, params = [], []
        if player:
            condicoes.append(f"{tabela}player = ?")
            params.append(player)
        if de:
            condicoes.append(f"substr({tabela}inicio, 1, 10) >= ?")
            params.append(de)
        if ate:
            condicoes.append(f"substr({tabela}inicio, 1, 10) <= ?")
            params.append(ate)
        return (" WHERE " + " AND ".join(condicoes)) if condicoes else "", params

    def sessoes(self, player: str | None = None, de: str | None = None, ate: str | None = None) -> list[dict]:
        where, params = self._filtro(player, de, ate)
        with self.lock:
            linhas = self.con.execute("SELECT * FROM sessoes" + where + " ORDER BY inicio", params).fetchall()
        return [dict(linha) for linha in linhas]

    def resumo(self, player: str | None = None, de: str | None = None, ate: str | None = None,
               pitch: float | None = None) -> dict:
        """Métricas do painel para um player e um período (datas no formato AAAA-MM-DD, inclusivas)."""
        where, params = self._filtro(player, de, ate)
        with self.lock:
            sessoes = [dict(l) for l in self.con.execute("SELECT * FROM sessoes" + where, params).fetchall()]
            where_s, _ = self._filtro(player, de, ate, "s.")
            eventos = self.con.execute(
                "SELECT e.tipo, COUNT(*) AS total, COUNT(DISTINCT e.sessao) AS sessoes FROM eventos e "
                "JOIN sessoes s ON s.sessao = e.sessao" + where_s + " GROUP BY e.tipo ORDER BY total DESC", params
            ).fetchall()
            config = self.con.execute(
                "SELECT MAX(pitch) AS pitch, MAX(duracao) AS duracao FROM players" + (" WHERE player = ?" if player else ""),
                [player] if player else [],
            ).fetchone()

        plays = [s for s in sessoes if s["com_som"]]
        duracao = max([config["duracao"] or 0] + [s["duracao"] for s in sessoes])
        pitch_em = pitch if pitch is not None else config["pitch"]
        chegaram_pitch = [s for s in plays if pitch_em is not None and s["max_tempo"] >= pitch_em]
        terminaram = [s for s in plays if s["terminou"]]
        tempos = [s["segundos"] for s in plays]

        passo, pontos = compactar_curva(curva_retencao([json.loads(s["assistido"]) for s in plays], duracao))

        por_dia: dict[str, dict] = {}
        for s in sessoes:
            dia = por_dia.setdefault(s["inicio"][:10], {"dia": s["inicio"][:10], "sessoes": 0, "plays": 0})
            dia["sessoes"] += 1
            dia["plays"] += s["com_som"]
        if por_dia or (de and ate):
            primeiro = date.fromisoformat(de or min(por_dia))
            ultimo = date.fromisoformat(ate or max(por_dia))
            if (ultimo - primeiro).days < MAX_DIAS:
                d = primeiro
                while d <= ultimo:
                    por_dia.setdefault(d.isoformat(), {"dia": d.isoformat(), "sessoes": 0, "plays": 0})
                    d += timedelta(days=1)

        def agrupar(chave: str, limite: int | None = None) -> list[dict]:
            grupos: dict[str, dict] = {}
            for s in sessoes:
                g = grupos.setdefault(s[chave], {"nome": s[chave], "sessoes": 0, "plays": 0, "pitch": 0, "terminaram": 0})
                g["sessoes"] += 1
                g["plays"] += s["com_som"]
                g["pitch"] += 1 if (s["com_som"] and pitch_em is not None and s["max_tempo"] >= pitch_em) else 0
                g["terminaram"] += 1 if (s["com_som"] and s["terminou"]) else 0
            lista = sorted(grupos.values(), key=lambda g: (-g["sessoes"], g["nome"]))
            if limite and len(lista) > limite:
                resto = {"nome": "outras", "sessoes": 0, "plays": 0, "pitch": 0, "terminaram": 0}
                for g in lista[limite:]:
                    for k in ("sessoes", "plays", "pitch", "terminaram"):
                        resto[k] += g[k]
                lista = lista[:limite] + [resto]
            return lista

        return {
            "player": player,
            "de": de,
            "ate": ate,
            "duracao": round(duracao, 1),
            "pitch": pitch_em,
            "sessoes": len(sessoes),
            "visitantes": len({s["visitante"] for s in sessoes if s["visitante"]}),
            "plays": len(plays),
            "taxa_play": round(len(plays) / len(sessoes), 4) if sessoes else 0,
            "chegaram_pitch": len(chegaram_pitch),
            "taxa_pitch": round(len(chegaram_pitch) / len(plays), 4) if plays else 0,
            "terminaram": len(terminaram),
            "taxa_conclusao": round(len(terminaram) / len(plays), 4) if plays else 0,
            "tempo_medio": round(statistics.fmean(tempos), 1) if tempos else 0,
            "tempo_mediano": round(statistics.median(tempos), 1) if tempos else 0,
            "engajamento": round(statistics.fmean(tempos) / duracao, 4) if tempos and duracao else 0,
            "retencao": {"passo": passo, "pontos": pontos},
            "por_dia": sorted(por_dia.values(), key=lambda d: d["dia"]),
            "origens": agrupar("origem", 12),
            "dispositivos": agrupar("dispositivo"),
            "eventos": [dict(e) for e in eventos],
        }

    def csv(self, player: str | None = None, de: str | None = None, ate: str | None = None) -> str:
        colunas = ["sessao", "player", "visitante", "inicio", "ultimo", "origem", "utm_source", "utm_medium",
                   "utm_campaign", "utm_content", "utm_term", "dispositivo", "url", "referrer", "duracao",
                   "max_tempo", "segundos", "com_som", "terminou"]
        saida = io.StringIO()
        escritor = csv.writer(saida, delimiter=";", lineterminator="\n")
        escritor.writerow(colunas)
        for s in self.sessoes(player, de, ate):
            escritor.writerow([s[c] for c in colunas])
        return saida.getvalue()


# ----------------------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "VSLAnalytics/1.0"
    protocol_version = "HTTP/1.1"
    banco: Banco
    token: str = ""

    def log_message(self, formato, *args):  # noqa: N802 (nome da classe-mãe)
        log.info("%s %s", self.address_string(), formato % args)

    # -- respostas

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def _responder(self, status: int, corpo: bytes = b"", tipo: str = "text/plain; charset=utf-8",
                   cors: bool = False, extras: dict | None = None) -> None:
        self.send_response(status)
        if corpo:
            self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cors:
            self._cors()
        for chave, valor in (extras or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        if corpo and self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, status: int, dados) -> None:
        self._responder(status, json.dumps(dados, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _descartar_corpo(self, maximo: int = 16 * 1024 * 1024) -> None:
        """Lê e joga fora o corpo (até `maximo`), para a resposta de erro chegar inteira ao cliente."""
        try:
            tamanho = min(int(self.headers.get("Content-Length") or 0), maximo)
        except ValueError:
            return
        while tamanho > 0:
            lido = self.rfile.read(min(tamanho, 65536))
            if not lido:
                break
            tamanho -= len(lido)

    def _autorizado(self, query: dict) -> bool:
        if not self.token:
            return True
        enviado = (query.get("token") or [""])[0] or self.headers.get("X-Token") or ""
        return hmac.compare_digest(enviado.encode(), self.token.encode())

    # -- métodos

    def do_OPTIONS(self):  # noqa: N802
        self._responder(204, cors=True)

    def do_POST(self):  # noqa: N802
        caminho = urlparse(self.path).path
        if caminho not in CAMINHOS_COLETA:
            self._descartar_corpo()
            self._responder(404, b"nao encontrado", cors=True)
            return
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            tamanho = -1
        if tamanho <= 0:
            self._responder(411, b"informe o Content-Length", cors=True)
            return
        if tamanho > LIMITE_CORPO:
            self._descartar_corpo()
            self.close_connection = True
            self._responder(413, b"envio grande demais", cors=True)
            return
        corpo = self.rfile.read(tamanho)
        try:
            dados = json.loads(corpo.decode("utf-8"))
            self.banco.registrar(dados, self.headers.get("User-Agent", ""))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as erro:
            self._responder(400, f"envio invalido: {erro}".encode(), cors=True)
            return
        self._responder(204, cors=True)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        query = parse_qs(url.query)
        caminho = url.path.rstrip("/") or "/"
        if caminho == "/saude":
            self._json(200, {"ok": True})
            return
        if caminho == "/api/config":
            self._json(200, {"token": bool(self.token), "versao": "1.0"})
            return
        if caminho not in ("/", "/painel", "/api/resumo", "/api/players", "/api/sessoes.csv"):
            self._responder(404, b"nao encontrado")
            return
        if not self._autorizado(query):
            if caminho in ("/", "/painel"):
                self._responder(200, PAINEL.read_bytes(), "text/html; charset=utf-8")  # o painel pede o token
            else:
                self._json(401, {"erro": "token invalido"})
            return
        if caminho in ("/", "/painel"):
            self._responder(200, PAINEL.read_bytes(), "text/html; charset=utf-8")
            return
        player = _texto((query.get("player") or [""])[0], MAX_ID) or None
        de, ate = _dia_valido((query.get("de") or [""])[0]), _dia_valido((query.get("ate") or [""])[0])
        if caminho == "/api/players":
            self._json(200, {"players": self.banco.players()})
        elif caminho == "/api/resumo":
            pitch_txt = (query.get("pitch") or [""])[0]
            pitch = _numero(pitch_txt) if pitch_txt else None
            self._json(200, self.banco.resumo(player, de, ate, pitch))
        else:
            nome = "sessoes-" + (player or "todos") + ".csv"
            self._responder(200, ("﻿" + self.banco.csv(player, de, ate)).encode("utf-8"), "text/csv; charset=utf-8",
                            extras={"Content-Disposition": f'attachment; filename="{nome}"'})


def criar_servidor(host: str, porta: int, banco: Banco, token: str = "") -> ThreadingHTTPServer:
    handler = type("HandlerConfigurado", (Handler,), {"banco": banco, "token": token})
    servidor = ThreadingHTTPServer((host, porta), handler)
    servidor.daemon_threads = True
    return servidor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Servidor de analytics do VSL Player.")
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 para aceitar conexões de fora (padrão: 127.0.0.1)")
    parser.add_argument("--porta", type=int, default=int(os.environ.get("VSL_ANALYTICS_PORTA", "8080")))
    parser.add_argument("--dados", default=os.environ.get("VSL_ANALYTICS_DADOS", str(DADOS_PADRAO)),
                        help="arquivo SQLite (padrão: player/analytics/dados.sqlite)")
    parser.add_argument("--token", default=os.environ.get("VSL_ANALYTICS_TOKEN", ""),
                        help="senha do painel e da API (o recebimento dos envios continua aberto)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    banco = Banco(args.dados)
    servidor = criar_servidor(args.host, args.porta, banco, args.token)
    log.info("Recebendo envios em http://%s:%d/vsl  ·  painel em http://%s:%d/%s", args.host, args.porta, args.host,
             args.porta, "?token=..." if args.token else "")
    if not args.token:
        log.warning("Sem --token: o painel fica aberto para quem acessar a porta. Defina um token antes de publicar.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        banco.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
