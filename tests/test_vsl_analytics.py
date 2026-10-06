"""Testes do servidor de analytics do VSL Player (player/analytics/servidor.py).

Rodam sem as dependências do app: python -m pytest tests/test_vsl_analytics.py --noconftest
"""

import http.client
import json
import logging
import socket
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "player" / "analytics"))

import servidor  # noqa: E402


def envio(sessao="s1", **extra):
    base = {
        "v": "1.0.0", "player": "vsl-principal", "visitor": "vis-1", "session": sessao,
        "url": "https://site.com/vsl?utm_source=Facebook&utm_campaign=lancamento", "referrer": "https://l.facebook.com/",
        "duration": 120, "maxTime": 40, "unmuted": True, "pitch": 30, "watched": [[0, 39]],
        "events": [{"type": "unmute", "ts": 1000, "time": 0}, {"type": "pitch", "ts": 2000, "time": 30, "at": 30}],
        "sentAt": 3000,
    }
    base.update(extra)
    return base


# ---------------------------------------------------------------- cálculos


def test_unir_faixas_junta_sobrepostas_e_vizinhas():
    assert servidor.unir_faixas([[10, 20], [0, 5], [6, 8], [15, 30], [50, 50]]) == [[0, 8], [10, 30], [50, 50]]


def test_unir_faixas_ignora_lixo():
    assert servidor.unir_faixas([[5, 2], ["a", 1], None, [-3, 4], [1, 2]]) == [[1, 2]]


def test_curva_retencao_conta_sessoes_por_segundo():
    curva = servidor.curva_retencao([[[0, 3]], [[2, 5]], [[0, 9]]], 6)
    assert curva == [2, 2, 3, 3, 2, 2, 1]


def test_compactar_curva_reduz_pontos():
    passo, pontos = servidor.compactar_curva(list(range(3000)), 1000)
    assert passo == 3 and len(pontos) == 1000 and pontos[0] == 1.0


def test_origem_e_dispositivo():
    assert servidor.origem("", "https://l.facebook.com/l.php?u=x") == "facebook"
    assert servidor.origem("", "https://www.google.com.br/") == "google"
    assert servidor.origem("", "https://blog.exemplo.com/post") == "blog.exemplo.com"
    assert servidor.origem("", "") == "direto"
    assert servidor.origem("TikTok", "https://www.google.com/") == "tiktok"
    assert servidor.dispositivo("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "celular"
    assert servidor.dispositivo("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "computador"


def test_validar_envio_rejeita_o_que_nao_serve():
    with pytest.raises(ValueError):
        servidor.validar_envio([1, 2])
    with pytest.raises(ValueError):
        servidor.validar_envio({"player": "p"})
    with pytest.raises(ValueError):
        servidor.validar_envio({"player": "p", "session": "s", "events": "x"})
    with pytest.raises(ValueError):
        servidor.validar_envio({"player": "p", "session": "s", "events": [{}] * (servidor.MAX_EVENTOS + 1)})


def test_validar_envio_limpa_valores():
    limpo = servidor.validar_envio({
        "player": " p\x00\n ", "session": "s", "duration": "nan", "maxTime": -5, "unmuted": "sim",
        "watched": [[3, 1], [0, 2]], "pitch": "",
        "events": [{"type": "x", "ts": "abc", "time": 1.234, "percent": 50, "element": {"a": 1}, "texto": "a" * 400}, "lixo"],
    })
    assert limpo["player"] == "p" and limpo["duracao"] == 0 and limpo["max_tempo"] == 0 and limpo["com_som"] == 1
    assert limpo["faixas"] == [[0, 2]] and limpo["pitch"] is None
    assert limpo["eventos"] == [{"tipo": "x", "ts": 0, "tempo": 1.23, "dados": '{"percent": 50}'}]


# ---------------------------------------------------------------- banco


def test_registrar_cria_sessao_com_origem_utm_e_dispositivo():
    banco = servidor.Banco()
    banco.registrar(envio(), "Mozilla/5.0 (iPhone)")
    sessao = banco.sessoes()[0]
    assert sessao["origem"] == "facebook" and sessao["utm_campaign"] == "lancamento"
    assert sessao["dispositivo"] == "celular" and sessao["segundos"] == 40 and sessao["com_som"] == 1
    assert banco.players()[0]["pitch"] == 30


def test_registrar_de_novo_une_faixas_e_nao_duplica_eventos():
    banco = servidor.Banco()
    banco.registrar(envio())
    banco.registrar(envio(maxTime=100, watched=[[0, 39], [60, 99]], unmuted=False,
                          events=[{"type": "unmute", "ts": 1000, "time": 0}, {"type": "ended", "ts": 5000, "time": 120}]))
    sessao = banco.sessoes()[0]
    assert json.loads(sessao["assistido"]) == [[0, 39], [60, 99]]
    assert sessao["segundos"] == 80 and sessao["max_tempo"] == 100 and sessao["com_som"] == 1 and sessao["terminou"] == 1
    resumo = banco.resumo()
    assert {e["tipo"]: e["total"] for e in resumo["eventos"]} == {"unmute": 1, "pitch": 1, "ended": 1}


def test_resumo_calcula_plays_pitch_e_retencao():
    banco = servidor.Banco()
    banco.registrar(envio("a"))                                                   # play, chegou ao pitch (40 >= 30)
    banco.registrar(envio("b", visitor="vis-2", maxTime=10, watched=[[0, 9]]))    # play, não chegou
    banco.registrar(envio("c", visitor="vis-3", unmuted=False, maxTime=50, watched=[[0, 49]], events=[]))  # só autoplay mudo
    r = banco.resumo("vsl-principal")
    assert (r["sessoes"], r["visitantes"], r["plays"]) == (3, 3, 2)
    assert r["taxa_play"] == pytest.approx(2 / 3, abs=1e-3)
    assert r["chegaram_pitch"] == 1 and r["taxa_pitch"] == 0.5 and r["pitch"] == 30
    assert r["tempo_medio"] == 25 and r["tempo_mediano"] == 25 and r["duracao"] == 120
    pontos = r["retencao"]["pontos"]
    assert r["retencao"]["passo"] == 1 and len(pontos) == 121
    assert pontos[0] == 2 and pontos[9] == 2 and pontos[10] == 1 and pontos[39] == 1 and pontos[40] == 0
    assert r["origens"][0]["nome"] == "facebook" and r["origens"][0]["plays"] == 2
    assert r["por_dia"][0]["sessoes"] == 3 and r["por_dia"][0]["plays"] == 2


def test_resumo_filtra_por_player_e_periodo():
    banco = servidor.Banco()
    banco.registrar(envio("a"), agora=datetime(2026, 10, 1, 10))
    banco.registrar(envio("b", player="outro"), agora=datetime(2026, 10, 3, 10))
    banco.registrar(envio("c"), agora=datetime(2026, 10, 5, 10))
    assert banco.resumo("vsl-principal")["sessoes"] == 2
    assert banco.resumo("outro")["sessoes"] == 1
    assert banco.resumo(None, "2026-10-02", "2026-10-04")["sessoes"] == 1
    assert banco.resumo(None, "2026-10-02", "2026-10-04")["eventos"][0]["sessoes"] == 1
    dias = banco.resumo(None, "2026-10-01", "2026-10-05")["por_dia"]
    assert [d["dia"][-2:] for d in dias] == ["01", "02", "03", "04", "05"] and dias[1]["sessoes"] == 0


def test_resumo_pitch_por_parametro_e_origens_agrupadas():
    banco = servidor.Banco()
    for i in range(15):
        banco.registrar(envio(f"s{i}", url=f"https://site.com/?utm_source=fonte{i}", pitch=None))
    r = banco.resumo(pitch=10)
    assert r["chegaram_pitch"] == 15 and r["pitch"] == 10
    assert len(r["origens"]) == 13 and r["origens"][-1]["nome"] == "outras" and r["origens"][-1]["sessoes"] == 3


def test_csv():
    banco = servidor.Banco()
    banco.registrar(envio())
    linhas = banco.csv().splitlines()
    assert linhas[0].startswith("sessao;player;visitante;inicio")
    assert linhas[1].startswith("s1;vsl-principal;vis-1;")


def test_csv_neutraliza_formulas():
    banco = servidor.Banco()
    banco.registrar(envio(session="=cmd|' /C calc'!A0", visitor="+1", url="https://site.com/?utm_source=@SUM(1)&utm_campaign=-x"))
    linha = banco.csv().splitlines()[1].split(";")
    assert linha[0].startswith("'=") and linha[2] == "'+1" and linha[5] == "'@sum(1)" and linha[6] == "'@SUM(1)" and linha[8] == "'-x"
    assert linha[14] == "120.0"  # números continuam números


def test_teto_de_duracao_nao_derruba_o_resumo():
    banco = servidor.Banco()
    banco.registrar(envio(duration=1e300, maxTime=1e300, watched=[[0, 1e300], [5, 10 ** 400]],
                          events=[{"type": "x", "ts": 1e300, "time": 1e300, "n": 10 ** 400}]))
    r = banco.resumo()
    assert r["duracao"] == servidor.MAX_SEGUNDOS and len(r["retencao"]["pontos"]) <= servidor.PONTOS_CURVA
    sessao = banco.sessoes()[0]
    assert sessao["max_tempo"] == servidor.MAX_SEGUNDOS + 1 - 1 and json.loads(sessao["assistido"]) == [[0, servidor.MAX_SEGUNDOS]]
    assert r["eventos"][0]["tipo"] == "x"


def test_max_tempo_nunca_passa_do_que_foi_assistido():
    banco = servidor.Banco()
    banco.registrar(envio(maxTime=500, watched=[[0, 4]]))          # maxTime inflado (ex.: player antigo mandando o reached)
    assert banco.sessoes()[0]["max_tempo"] == 5
    assert banco.resumo()["chegaram_pitch"] == 0                     # pitch aos 30 s: não chegou
    banco.registrar(envio(maxTime=500, watched=[[0, 4], [5, 35]]))  # agora assistiu até 35
    assert banco.sessoes()[0]["max_tempo"] == 36 and banco.resumo()["chegaram_pitch"] == 1


def test_pitch_de_cada_player_na_vista_geral():
    banco = servidor.Banco()
    banco.registrar(envio("a", player="curto", pitch=10, maxTime=20, watched=[[0, 19]]))
    banco.registrar(envio("b", player="longo", pitch=50, maxTime=20, watched=[[0, 19]]))
    geral = banco.resumo()
    assert geral["chegaram_pitch"] == 1 and geral["pitch"] is None and geral["pitch_misto"] is True
    assert {o["nome"]: o["pitch"] for o in geral["origens"]} == {"facebook": 1}
    assert banco.resumo("longo")["pitch"] == 50 and banco.resumo("longo")["chegaram_pitch"] == 0
    assert banco.resumo(pitch=15)["chegaram_pitch"] == 2 and banco.resumo(pitch=15)["pitch_misto"] is False


def test_duracao_do_player_e_a_ultima_e_o_resumo_usa_a_do_periodo():
    banco = servidor.Banco()
    banco.registrar(envio("a", duration=600, maxTime=300, watched=[[0, 299]]), agora=datetime(2026, 9, 1, 10))
    banco.registrar(envio("b", duration=120, maxTime=60, watched=[[0, 59]]), agora=datetime(2026, 10, 1, 10))
    assert banco.players()[0]["duracao"] == 120
    assert banco.resumo(de="2026-10-01")["duracao"] == 120
    assert banco.resumo(ate="2026-09-30")["duracao"] == 600
    assert banco.resumo(de="2026-10-01")["engajamento"] == 0.5


def test_pitch_invalido_e_pitch_zero():
    assert servidor._pitch("abc") is None and servidor._pitch(True) is None and servidor._pitch(-1) is None
    assert servidor._pitch([1]) is None and servidor._pitch("nan") is None and servidor._pitch("12.5") == 12.5
    assert servidor._pitch(0) == 0.0
    banco = servidor.Banco()
    banco.registrar(envio(pitch="abc"))
    assert banco.players()[0]["pitch"] is None
    banco.registrar(envio(pitch=0))
    assert banco.players()[0]["pitch"] == 0 and banco.resumo()["chegaram_pitch"] == 1
    banco.registrar(envio(pitch="lixo"))
    assert banco.players()[0]["pitch"] == 0  # pitch inválido não apaga o que já estava gravado


def test_segundos_nao_passam_da_duracao():
    banco = servidor.Banco()
    banco.registrar(envio(duration=30.5, maxTime=30.5, watched=[[0, 30]]))
    r = banco.resumo()
    assert banco.sessoes()[0]["segundos"] == 30.5 and r["tempo_medio"] == 30.5 and r["engajamento"] == 1.0


def test_periodo_pelo_relogio_do_servidor():
    banco = servidor.Banco()
    hoje = datetime.now().replace(hour=12)
    banco.registrar(envio("recente"), agora=hoje)
    banco.registrar(envio("antiga"), agora=hoje - timedelta(days=40))
    assert banco.resumo(periodo="30")["sessoes"] == 1 and banco.resumo(periodo="hoje")["sessoes"] == 1
    assert banco.resumo(periodo="tudo")["sessoes"] == 2 and banco.resumo(periodo="90")["sessoes"] == 2
    r = banco.resumo(periodo="7")
    assert r["de"] == (date.today() - timedelta(days=6)).isoformat() and r["ate"] == date.today().isoformat() == r["hoje"]
    with pytest.raises(ValueError):
        banco.resumo(periodo="ontem")
    assert banco.csv(periodo="30").count("\n") == 2


def test_evento_no_mesmo_milissegundo_com_seq_nao_e_descartado():
    banco = servidor.Banco()
    banco.registrar(envio(events=[{"type": "reach", "ts": 5, "time": 10, "at": 10, "seq": 1},
                                  {"type": "reach", "ts": 5, "time": 10, "at": 10, "seq": 2}]))
    assert banco.resumo()["eventos"][0]["total"] == 2


# ---------------------------------------------------------------- HTTP


@pytest.fixture
def pedir(tmp_path):
    banco = servidor.Banco(tmp_path / "dados.sqlite")
    srv = servidor.criar_servidor("127.0.0.1", 0, banco, token="segredo")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    porta = srv.server_address[1]

    def _pedir(metodo, caminho, corpo=None, cabecalhos=None):
        con = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
        con.request(metodo, caminho, body=corpo, headers=cabecalhos or {})
        resp = con.getresponse()
        dados = resp.read()
        con.close()
        return resp.status, dict(resp.getheaders()), dados

    _pedir.porta = porta
    yield _pedir
    srv.shutdown()
    srv.server_close()
    banco.fechar()


def test_coleta_aceita_text_plain_com_cors(pedir):
    corpo = json.dumps(envio()).encode()
    status, cab, _ = pedir("POST", "/vsl", corpo, {"Content-Type": "text/plain;charset=UTF-8", "Content-Length": str(len(corpo)),
                                                   "User-Agent": "Mozilla/5.0 (Android 14; Mobile)"})
    assert status == 204 and cab["Access-Control-Allow-Origin"] == "*"
    status, cab, _ = pedir("OPTIONS", "/vsl", None, {"Origin": "https://site.com", "Access-Control-Request-Method": "POST"})
    assert status == 204 and "POST" in cab["Access-Control-Allow-Methods"]
    status, _, dados = pedir("GET", "/api/resumo?token=segredo&player=vsl-principal")
    resumo = json.loads(dados)
    assert status == 200 and resumo["sessoes"] == 1 and resumo["dispositivos"][0]["nome"] == "celular"


def test_coleta_recusa_envios_ruins(pedir):
    assert pedir("POST", "/vsl", b"{nao e json", {"Content-Length": "11"})[0] == 400
    assert pedir("POST", "/vsl", b'{"player": "p"}', {"Content-Length": "15"})[0] == 400
    assert pedir("POST", "/vsl", b"", {"Content-Length": "0"})[0] == 411
    grande = b"x" * (servidor.LIMITE_CORPO + 1)
    assert pedir("POST", "/vsl", grande, {"Content-Length": str(len(grande))})[0] == 413
    assert pedir("POST", "/outro", b"{}", {"Content-Length": "2"})[0] == 404


def test_painel_e_api_pedem_token(pedir):
    assert pedir("GET", "/api/resumo")[0] == 401
    assert pedir("GET", "/api/resumo", None, {"X-Token": "errado"})[0] == 401
    assert pedir("GET", "/api/resumo", None, {"X-Token": "segredo"})[0] == 200
    status, cab, html = pedir("GET", "/")
    assert status == 200 and "text/html" in cab["Content-Type"] and b"Reten" in html  # o painel abre e pede o token
    assert pedir("GET", "/api/sessoes.csv")[0] == 401
    status, cab, csv = pedir("GET", "/api/sessoes.csv?token=segredo&player=vsl-principal")
    assert status == 200 and "attachment" in cab["Content-Disposition"] and csv.decode("utf-8-sig").startswith("sessao;")
    assert json.loads(pedir("GET", "/api/config")[2]) == {"token": True, "versao": "1.0", "hoje": date.today().isoformat()}
    assert pedir("GET", "/saude")[0] == 200
    assert pedir("GET", "/nada")[0] == 404
    assert pedir("GET", "/painel.html")[0] == 404  # nada de servir arquivos da pasta
    status, cab, _ = pedir("HEAD", "/api/resumo?token=segredo")
    assert status == 200 and int(cab["Content-Length"]) > 10


def test_parametros_invalidos_dao_400(pedir):
    cab = {"X-Token": "segredo"}
    assert pedir("GET", "/api/resumo?de=2026-13-01", None, cab)[0] == 400
    assert pedir("GET", "/api/resumo?ate=ontem", None, cab)[0] == 400
    assert pedir("GET", "/api/resumo?pitch=abc", None, cab)[0] == 400
    assert pedir("GET", "/api/resumo?periodo=x", None, cab)[0] == 400
    assert pedir("GET", "/api/resumo?periodo=7&pitch=12.5", None, cab)[0] == 200
    assert pedir("GET", "/api/sessoes.csv?de=2026-99-99", None, cab)[0] == 400


def test_nome_do_csv_e_seguro(pedir):
    status, cab, _ = pedir("GET", '/api/sessoes.csv?token=segredo&player=../x"y;%20z%C3%A7')
    assert status == 200 and cab["Content-Disposition"] == 'attachment; filename="sessoes-.._x_y_z.csv"'


def test_coleta_aguenta_numeros_absurdos(pedir):
    corpo = b'{"player":"p","session":"s","duration":1e300,"watched":[[0,Infinity],[1,1e300]],"events":[{"type":"a","ts":1e300,"n":1e999}]}'
    assert pedir("POST", "/vsl", corpo, {"Content-Length": str(len(corpo))})[0] == 204
    corpo = b'{"player":"p","session":"s","events":[' + b'[' * 100000 + b']' * 100000 + b']}'
    assert pedir("POST", "/vsl", corpo, {"Content-Length": str(len(corpo))})[0] == 400


def test_log_esconde_o_token(pedir, caplog):
    with caplog.at_level(logging.INFO, logger="vsl.analytics"):
        pedir("GET", "/api/resumo?token=segredo&player=p")
        # http.client recusa caracteres de controle na URL, então manda a linha crua pelo socket
        sock = socket.create_connection(("127.0.0.1", pedir.porta), timeout=5)
        sock.sendall(b"GET /\x1b[31mnada HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        sock.recv(4096)
        sock.close()
    texto = caplog.text
    assert "segredo" not in texto and "token=***" in texto and "player=p" in texto
    assert "\x1b" not in texto and "\\x1b" in texto
