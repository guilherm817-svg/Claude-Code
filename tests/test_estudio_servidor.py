"""Estúdio de Reels: gravação do projeto e dos vídeos no Windows."""

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from estudio import projetos
from estudio.exportar import Exportador
from estudio.midia import ffmpeg
from estudio.projetos import Ajustes, Estudio


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
    with pytest.raises(PermissionError):
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
