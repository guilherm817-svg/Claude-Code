"""Estúdio de Reels: gravação do projeto no Windows, endereço da porta e proteções do servidor local."""

import mimetypes
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from estudio import projetos
from estudio.__main__ import porta_livre
from estudio.exportar import Exportador
from estudio.midia import ffmpeg
from estudio.projetos import Ajustes, Estudio
from estudio.servidor import criar_app


@pytest.fixture(scope="module")
def clipe(tmp_path_factory):
    destino = tmp_path_factory.mktemp("clipe") / "Bloco 1.mp4"
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=180x320:r=24:d=1",
                    "-f", "lavfi", "-i", "sine=f=300:d=1,volume=0.3", "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "1", str(destino)], check=True)
    return destino


@pytest.fixture
def estudio(tmp_path):
    return Estudio(tmp_path / "meus-reels")


@pytest.fixture
def cliente(estudio):
    return TestClient(criar_app(estudio), base_url="http://127.0.0.1")


def _importar(estudio, projeto_id, caminho):
    with open(caminho, "rb") as arquivo:
        return estudio.importar(projeto_id, arquivo, caminho.name)


# Gravação do projeto.json


def _windows_segura(monkeypatch, alvo=lambda destino: True, vezes=None):
    """Faz o os.replace falhar como no Windows quando outro programa está com o arquivo aberto (`vezes` seguidas
    para cada destino, ou sempre)."""
    trocar = os.replace
    falhas = []

    def trocar_no_windows(origem, destino):
        if alvo(Path(destino)) and (vezes is None or falhas.count(Path(destino)) < vezes):
            falhas.append(Path(destino))
            raise PermissionError(13, "O arquivo está sendo usado por outro processo")
        return trocar(origem, destino)

    monkeypatch.setattr(os, "replace", trocar_no_windows)
    return falhas


def test_gravar_o_projeto_espera_a_leitura_que_esta_em_andamento(estudio, monkeypatch):
    """No Windows, trocar o projeto.json enquanto outra thread do servidor o lê dá PermissionError."""
    projeto = estudio.criar("Antes")
    arquivo = estudio.pasta_projeto(projeto.id) / "projeto.json"
    ler = Path.read_text
    abertos, lendo = [0], threading.Event()

    def ler_devagar(caminho, *args, **kwargs):
        if caminho != arquivo:
            return ler(caminho, *args, **kwargs)
        abertos[0] += 1
        try:
            if threading.current_thread().name == "leitura":  # como o GET do <video> no meio de um salvamento
                lendo.set()
                time.sleep(0.3)
            return ler(caminho, *args, **kwargs)
        finally:
            abertos[0] -= 1

    monkeypatch.setattr(Path, "read_text", ler_devagar)
    falhas = _windows_segura(monkeypatch, alvo=lambda destino: destino == arquivo and abertos[0] > 0)
    leitura = threading.Thread(target=estudio.abrir, args=(projeto.id,), name="leitura")
    leitura.start()
    assert lendo.wait(2)
    estudio.aplicar(projeto.id, Ajustes(nome="Depois"))
    leitura.join()
    assert falhas == [] and estudio.abrir(projeto.id).nome == "Depois"


def test_salvar_insiste_enquanto_outro_programa_segura_o_arquivo(estudio, monkeypatch):
    projeto = estudio.criar("Antes")
    falhas = _windows_segura(monkeypatch, vezes=3)  # antivírus ou OneDrive lendo o arquivo recém-gravado
    projeto.nome = "Depois"
    estudio.salvar(projeto)
    assert len(falhas) == 3 and estudio.abrir(projeto.id).nome == "Depois"


def test_salvar_desiste_se_o_arquivo_continua_preso(estudio, monkeypatch):
    projeto = estudio.criar("Antes")
    monkeypatch.setattr(projetos, "ESPERA_TROCA", 0.1)
    falhas = _windows_segura(monkeypatch)
    inicio = time.monotonic()
    with pytest.raises(PermissionError):
        estudio.aplicar(projeto.id, Ajustes(nome="Depois"))
    assert len(falhas) > 1 and time.monotonic() - inicio < 1
    assert estudio.abrir(projeto.id).nome == "Antes"


def test_importacao_que_nao_entra_no_projeto_nao_deixa_arquivos(estudio, clipe, monkeypatch):
    projeto = estudio.criar()
    monkeypatch.setattr(projetos, "ESPERA_TROCA", 0.1)
    _windows_segura(monkeypatch, alvo=lambda destino: destino.name == "projeto.json")
    with pytest.raises(projetos.ErroImportacao, match="antivírus ou o OneDrive"):
        _importar(estudio, projeto.id, clipe)
    assert estudio.abrir(projeto.id).midias == []
    assert list(estudio.pasta_midia(projeto.id).iterdir()) == []
    assert list(estudio.pasta_cache(projeto.id).iterdir()) == []


def test_exportacao_insiste_quando_o_windows_segura_os_arquivos(estudio, clipe, monkeypatch):
    projeto, _, _ = _importar(estudio, estudio.criar("Teste").id, clipe)
    falhas = _windows_segura(monkeypatch, alvo=lambda destino: destino.suffix in (".mov", ".mp4"), vezes=1)
    exportacao = Exportador(estudio).iniciar(projeto.id, sincrono=True)
    assert exportacao.estado == "pronta", exportacao.erro
    assert [p.suffix for p in falhas] == [".mov", ".mp4"]
    assert (estudio.pasta_exportados(projeto.id) / exportacao.arquivo).is_file()


# Tela e endereço


def test_tela_sai_com_o_tipo_certo_mesmo_com_o_registro_do_windows_errado(estudio):
    # No Windows, o mimetypes lê os tipos do registro, que às vezes diz que .js é text/plain.
    for extensao in (".js", ".css", ".json", ".svg", ".ttf", ".woff2"):
        mimetypes.add_type("text/plain", extensao)
    try:
        cliente = TestClient(criar_app(estudio), base_url="http://127.0.0.1")
        assert cliente.get("/static/app.js").headers["content-type"].startswith("text/javascript")
        assert cliente.get("/static/legendas.js").headers["content-type"].startswith("text/javascript")
        assert cliente.get("/static/estilo.css").headers["content-type"].startswith("text/css")
        assert cliente.get("/static/fontes/Poppins-Black.ttf").headers["content-type"] == "font/ttf"
        for extensao, tipo in ((".json", "application/json"), (".svg", "image/svg+xml"), (".woff2", "font/woff2")):
            assert mimetypes.guess_type("x" + extensao)[0] == tipo
    finally:
        for tipo, extensao in (("text/javascript", ".js"), ("text/css", ".css"), ("application/json", ".json"),
                               ("image/svg+xml", ".svg"), ("font/ttf", ".ttf"), ("font/woff2", ".woff2")):
            mimetypes.add_type(tipo, extensao)


@pytest.mark.skipif(os.name != "posix", reason="no Windows, conexões em TIME_WAIT não prendem a porta")
def test_porta_livre_reaproveita_a_porta_de_um_estudio_recem_fechado():
    servidor = socket.socket()
    servidor.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # como o uvicorn
    servidor.bind(("127.0.0.1", 0))
    servidor.listen()
    porta = servidor.getsockname()[1]
    cliente = socket.create_connection(("127.0.0.1", porta))
    conexao, _ = servidor.accept()
    conexao.close()  # o servidor fecha primeiro, como o uvicorn com as conexões paradas: a porta fica em TIME_WAIT
    cliente.close()
    servidor.close()
    time.sleep(0.1)
    assert porta_livre(porta) == porta


def test_porta_livre_pula_a_porta_de_um_estudio_aberto():
    with socket.socket() as aberto:
        if os.name == "posix":
            aberto.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        aberto.bind(("127.0.0.1", 0))
        aberto.listen()
        porta = aberto.getsockname()[1]
        assert porta_livre(porta) != porta


@pytest.mark.parametrize("metodo, caminho, cabecalhos", [
    ("GET", "/static/index.html", {}),
    ("GET", "/static/app.js", {}),
    ("GET", "/", {}),
    ("GET", "/api/projetos", {}),
    ("GET", "/api/projetos/000000000000", {}),
    ("POST", "/api/projetos", {}),
    ("GET", "/api/legendas", {}),
    ("POST", "/api/projetos/000000000000/legendas", {}),
    ("GET", "/api/corretor/estado", {}),
    ("POST", "/api/chave", {}),
    ("POST", "/api/corretor", {}),
    ("GET", "/api/projetos", {"Host": "site-malicioso.com"}),
])
def test_nenhuma_resposta_pode_ser_mostrada_dentro_de_outro_site(cliente, metodo, caminho, cabecalhos):
    resposta = cliente.request(metodo, caminho, headers=cabecalhos, follow_redirects=False)
    assert resposta.headers["x-frame-options"] == "DENY"
    assert resposta.headers["content-security-policy"] == "frame-ancestors 'none'"
    assert resposta.headers["x-content-type-options"] == "nosniff"


def test_so_aceita_os_enderecos_do_proprio_computador(estudio):
    app = criar_app(estudio)
    # "testserver" é só o nome padrão do cliente de teste: na rede, outro computador pode responder por ele.
    assert TestClient(app).get("/api/projetos").status_code == 400
    assert TestClient(app, base_url="http://testserver:8502").get("/api/projetos").status_code == 400
    for base in ("http://127.0.0.1:8502", "http://localhost:8502"):
        assert TestClient(app, base_url=base).get("/api/projetos").status_code == 200


def test_rotas_novas_tambem_recusam_pedido_de_fora(cliente):
    for metodo, caminho in (("POST", "/api/projetos/000000000000/legendas"), ("POST", "/api/chave"),
                            ("POST", "/api/corretor")):
        assert cliente.request(metodo, caminho, json={}).status_code == 403
    for caminho in ("/api/legendas", "/api/corretor/estado", "/api/projetos/000000000000/legendas"):
        assert cliente.get(caminho, headers={"Host": "site-malicioso.com"}).status_code == 400


def test_baixar_exportado_confere_o_nome_antes_de_tocar_no_disco(cliente, estudio, monkeypatch):
    projeto = estudio.criar()
    pasta = estudio.pasta_exportados(projeto.id)
    pasta.mkdir(parents=True)
    (pasta / "Reels 1.mp4").write_bytes(b"video")
    tocados = []
    for nome in ("stat", "lstat", "open", "scandir"):
        original = getattr(os, nome)

        def espiao(caminho=".", *args, _original=original, **kwargs):
            if isinstance(caminho, (str, bytes, os.PathLike)):
                tocados.append(os.fsdecode(caminho))
            return _original(caminho, *args, **kwargs)

        monkeypatch.setattr(os, nome, espiao)

    # No Windows, ler \\atacante\pasta\x.mp4 abre uma conexão de rede e entrega o login do usuário (NTLM).
    for nome in ("%5C%5Catacante.example%5Cshare%5Cx.mp4", "..%5C..%5Catacante.mp4", "C:atacante.mp4",
                 "atacante.mp4:fluxo", "..%2Fatacante.mp4", "atacante.mp4"):
        assert cliente.get(f"/api/projetos/{projeto.id}/exportados/{nome}").status_code == 404
    assert not [caminho for caminho in tocados if "atacante" in caminho]
    r = cliente.get(f"/api/projetos/{projeto.id}/exportados/Reels 1.mp4")
    assert r.status_code == 200 and r.content == b"video" and "attachment" in r.headers["content-disposition"]
