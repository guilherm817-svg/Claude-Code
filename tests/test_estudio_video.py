"""Vídeos difíceis no Estúdio: áudio e vídeo que não começam juntos, HDR do iPhone, faixa de áudio que o ffmpeg não
decodifica, WebM sem duração, falhas no meio da importação e arquivos presos por outros programas no Windows. Usa o
ffmpeg de verdade, com clipes curtos gerados na hora."""

import math
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from estudio import exportar as exp
from estudio import midia, projetos, transcricao
from estudio.midia import TAXA_ANALISE, Cor, ErroMidia, ffmpeg, ler_audio, medir_volume, picos_onda, sondar
from estudio.projetos import Ajustes, ErroImportacao, Estudio, Item
from estudio.servidor import criar_app
from whisper_falso import WhisperFalso

CABECALHO = {"X-Estudio": "1"}


def _gerar(*args):
    subprocess.run([ffmpeg(), "-v", "error", "-y", *map(str, args)], check=True)


@pytest.fixture
def estudio(tmp_path):
    return Estudio(tmp_path / "meus-reels")


def _importar(estudio, projeto_id, caminho, nome=None):
    with open(caminho, "rb") as arquivo:
        return estudio.importar(projeto_id, arquivo, nome or caminho.name)


def _exportar(estudio, projeto_id):
    resultado = exp.Exportador(estudio).iniciar(projeto_id, sincrono=True)
    assert resultado.estado == "pronta", resultado.erro
    return estudio.pasta_exportados(projeto_id) / resultado.arquivo


def _arquivos(estudio, projeto_id):
    pasta = estudio.pasta_projeto(projeto_id)
    return sorted(str(p.relative_to(pasta)) for p in pasta.rglob("*") if p.is_file())


def _cores_do_video(caminho) -> Cor:
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(caminho)], capture_output=True, text=True)
    return midia.interpretar_sonda(r.stderr).cor


BT709 = Cor(matriz="bt709", primarias="bt709", transferencia="bt709", faixa="tv")


# Sincronia: um flash branco e um bipe em cada segundo inteiro da linha do tempo do arquivo


def clipe_marcado(destino, atraso_audio=0.0, atraso_video=0.0, duracao=6, fps=24):
    """Cada stream pode começar atrasado, como em vídeo de celular ou recortado em outro programa: o conteúdo
    continua alinhado na linha do tempo do arquivo (o flash e o bipe do segundo 1 acontecem juntos no 1,0 s)."""
    _gerar("-itsoffset", atraso_video, "-f", "lavfi", "-i",
           f"color=c=black:s=180x320:r={fps}:d={duracao - atraso_video},"
           f"drawbox=c=white:t=fill:enable='lt(mod(t+{atraso_video}+0.0001,1),0.02)'",
           "-itsoffset", atraso_audio, "-f", "lavfi", "-i",
           f"aevalsrc='if(lt(mod(t+{atraso_audio},1),0.03),0.5*sin(2*PI*1000*t),0)':s=48000:d={duracao - atraso_audio}",
           "-map", "0:v", "-map", "1:a", "-fps_mode", "passthrough", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-c:a", "aac", destino)
    return destino


def marcas(caminho):
    """Quando cada flash e cada bipe começa, pelos tempos gravados no arquivo."""
    r = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(caminho), "-vf", "blackdetect=d=0.01:pix_th=0.5",
                        "-af", "silencedetect=n=-30dB:d=0.01", "-f", "null", "-"], capture_output=True, text=True)
    return ([float(t) for t in re.findall(r"black_end:(\S+)", r.stderr)],
            [float(t) for t in re.findall(r"silence_end: (\S+)", r.stderr)])


@pytest.fixture(scope="module")
def marcados(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("marcados")
    return {"juntos": clipe_marcado(pasta / "juntos.mp4"),
            "audio_depois": clipe_marcado(pasta / "audio_depois.mp4", atraso_audio=0.25),
            "video_depois": clipe_marcado(pasta / "video_depois.mp4", atraso_video=0.25)}


@pytest.mark.parametrize("entrada", [0.0, 0.5, 2.51])
@pytest.mark.parametrize("clipe", ["juntos", "audio_depois", "video_depois"])
def test_trecho_sai_com_audio_e_video_juntos(marcados, tmp_path, clipe, entrada):
    saida = tmp_path / "trecho.mov"
    trecho = exp.Trecho(arquivo=marcados[clipe], entrada=entrada, duracao=3.0, tem_audio=True)
    subprocess.run([ffmpeg(), "-v", "error", *exp.comando_trecho(trecho, 180, 320, "24", 24.0, "preencher", saida)],
                   check=True)
    flashes, bipes = marcas(saida)
    esperado = [n - entrada for n in range(math.ceil(entrada), 7) if 0.1 < n - entrada < 2.9]
    flashes = [t for t in flashes if t < 2.9]  # o fim do trecho também aparece como fim do preto e do silêncio
    bipes = [t for t in bipes if t < 2.9]
    # O vídeo cai no quadro mais perto (até meio quadro de diferença); o áudio, na amostra.
    assert flashes == pytest.approx(esperado, abs=0.5 / 24 + 0.001)
    assert bipes == pytest.approx(esperado, abs=0.005)


def test_ler_audio_fica_no_tempo_do_video(marcados):
    """A fala, a onda e as legendas vêm do ler_audio: o áudio que começa depois do vídeo não pode chegar adiantado."""
    audio = ler_audio(marcados["audio_depois"])
    assert len(audio) / TAXA_ANALISE == pytest.approx(6.0, abs=0.05)
    alto = np.abs(audio) > 0.05
    inicios = np.flatnonzero(alto[1:] & ~alto[:-1]) + 1
    primeiro = inicios[0] / TAXA_ANALISE
    assert primeiro == pytest.approx(1.0, abs=0.01)


# Cores: HDR do iPhone (HLG) e PQ convertidos para BT.709 SDR, com as mesmas marcações em todo trecho


@pytest.fixture(scope="module")
def cores(tmp_path_factory):
    if not exp.tem_tone_mapping():
        pytest.skip("este ffmpeg não tem o zscale para gerar os clipes HDR do teste")
    pasta = tmp_path_factory.mktemp("cores")
    sdr = pasta / "sdr.mp4"
    _gerar("-f", "lavfi", "-i", "smptehdbars=s=360x640:r=24:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", sdr)
    sem_marcacao = pasta / "sem_marcacao.mp4"
    _gerar("-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", sem_marcacao)
    clipes = {"sdr": sdr, "sem_marcacao": sem_marcacao}
    for nome, transferencia in (("hlg", "arib-std-b67"), ("pq", "smpte2084")):
        # O branco do SDR vira o branco de referência do HDR (203 nits), como recomenda a BT.2408.
        clipes[nome] = pasta / f"{nome}.mp4"
        _gerar("-i", sdr, "-vf", f"zscale=t=linear:npl=203,format=gbrpf32le,"
                                 f"zscale=p=bt2020:t={transferencia}:npl=203:m=bt2020nc:r=tv,format=yuv420p10le",
               "-c:v", "libx264", "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020",
               "-color_trc", transferencia, "-colorspace", "bt2020nc", clipes[nome])
    return clipes


def _render(arquivo, saida):
    trecho = exp.Trecho(arquivo=arquivo, entrada=0, duracao=1.0, tem_audio=False, cor=sondar(arquivo).cor)
    subprocess.run([ffmpeg(), "-v", "error", *exp.comando_trecho(trecho, 360, 640, "24", 24.0, "preencher", saida)],
                   check=True)
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", str(saida), "-frames:v", "1", "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(640, 360, 3).astype(float)


def test_sondar_le_as_cores():
    assert midia._cor("hevc (Main 10), yuv420p10le(tv, bt2020nc/bt2020/arib-std-b67), 1080x1920") == Cor(
        "bt2020nc", "bt2020", "arib-std-b67", "tv")
    assert midia._cor("h264 (High), yuvj420p(pc, bt470bg/unknown/unknown, progressive), 720x1280") == Cor(
        "bt470bg", "", "", "pc")
    assert midia._cor("h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 180x320") == Cor()
    assert Cor(transferencia="arib-std-b67").hdr and Cor(transferencia="smpte2084").hdr and not BT709.hdr


def test_filtro_de_cor_por_origem(monkeypatch):
    assert exp.filtro_cor(Cor()) == exp.filtro_cor(BT709) == ""  # o caso comum (Veo) não ganha conversão
    assert "in_color_matrix=bt709:" in exp.filtro_cor(Cor(faixa="pc"))  # sem matriz marcada: lido como BT.709
    assert "in_color_matrix=auto:" in exp.filtro_cor(Cor(matriz="smpte170m", faixa="tv"))
    hlg = Cor("bt2020nc", "bt2020", "arib-std-b67", "tv")
    monkeypatch.setattr(exp, "filtros", lambda: frozenset({"scale", "zscale", "tonemap"}))
    assert "tonemap" in exp.filtro_cor(hlg)
    monkeypatch.setattr(exp, "filtros", lambda: frozenset({"scale"}))  # o ffmpeg do Windows pode vir sem a zimg
    assert exp.filtro_cor(hlg) == "scale=in_color_matrix=bt2020:out_color_matrix=bt709:out_range=tv,"
    for cor in (Cor(), hlg):
        assert "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,format=yuv420p" in \
            exp.filtro_video(1080, 1920, "30", 90, "preencher", cor=cor)


def test_hdr_vira_sdr_bt709(cores, tmp_path):
    referencia = _render(cores["sdr"], tmp_path / "sdr.mov")
    assert _cores_do_video(tmp_path / "sdr.mov") == BT709
    for nome in ("hlg", "pq"):
        assert sondar(cores[nome]).cor.hdr
        quadro = _render(cores[nome], tmp_path / f"{nome}.mov")
        assert _cores_do_video(tmp_path / f"{nome}.mov") == BT709
        # Sem a conversão, as cores saíam lavadas: diferença média de 30 a 50 e metade da saturação.
        assert np.abs(quadro - referencia).mean() < 15, nome
        saturacao = (quadro.max(axis=2) - quadro.min(axis=2)).mean() / quadro.mean()
        assert saturacao > 0.7, nome


def test_hdr_sem_zscale_ainda_sai_marcado_bt709(cores, tmp_path, monkeypatch):
    monkeypatch.setattr(exp, "filtros", lambda: frozenset())
    _render(cores["hlg"], tmp_path / "hlg.mov")
    assert _cores_do_video(tmp_path / "hlg.mov") == BT709


def test_reels_com_clipe_hdr_sai_inteiro_em_bt709(cores, estudio):
    """A emenda sem recodificar declara as cores do primeiro trecho para o vídeo inteiro: com o HDR primeiro, o
    Reels todo saía marcado como HLG; com ele depois, o trecho HDR aparecia lavado."""
    projeto = estudio.criar("HDR")
    for nome in ("hlg", "sdr", "sem_marcacao"):
        _importar(estudio, projeto.id, cores[nome])
    assert sondar(cores["sem_marcacao"]).cor == Cor()
    saida = _exportar(estudio, projeto.id)
    assert _cores_do_video(saida) == BT709
    trechos = list((estudio.pasta_cache(projeto.id) / "trechos").glob("*.mov"))
    assert len(trechos) == 3 and all(_cores_do_video(t) == BT709 for t in trechos)  # todos com as mesmas marcações


# Faixa de áudio que o ffmpeg não decodifica (o áudio espacial APAC do iPhone 16)


def _com_apac(destino, *faixas):
    """Vídeo e as faixas de áudio pedidas: "apac" (que o ffmpeg não conhece) ou "fala" (tom de 0,5 a 1,5 s)."""
    entradas, mapas, codecs = [], ["-map", "0:v"], []
    for n, faixa in enumerate(faixas, 1):
        fonte = "sine=f=500:d=2" if faixa == "apac" else "sine=f=300:d=1,adelay=500|500,apad=whole_dur=2,volume=0.3"
        entradas += ["-f", "lavfi", "-i", fonte]
        mapas += ["-map", f"{n}:a"]
        codecs += [f"-c:a:{n - 1}", "alac" if faixa == "apac" else "aac"]
    _gerar("-f", "lavfi", "-i", "testsrc2=s=180x320:r=24:d=2", *entradas, *mapas, "-c:v", "libx264",
           "-pix_fmt", "yuv420p", *codecs, "-t", "2", destino)
    # Troca o código do ALAC por "apac": a faixa vira uma que o ffmpeg não sabe decodificar.
    destino.write_bytes(destino.read_bytes().replace(b"alac", b"apac"))
    return destino


@pytest.fixture(scope="module")
def apac(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("apac")
    return {"primeiro": _com_apac(pasta / "IMG_0001.MOV", "apac", "fala"),
            "depois": _com_apac(pasta / "IMG_0002.MOV", "fala", "apac"),
            "so_apac": _com_apac(pasta / "IMG_0003.MOV", "apac")}


def test_sondar_ignora_faixa_que_o_ffmpeg_nao_decodifica(apac):
    assert "could not find codec parameters" in subprocess.run(
        [ffmpeg(), "-hide_banner", "-i", str(apac["primeiro"])], capture_output=True, text=True).stderr.lower()
    primeiro, depois, so_apac = sondar(apac["primeiro"]), sondar(apac["depois"]), sondar(apac["so_apac"])
    assert (primeiro.tem_audio, primeiro.faixa_audio, primeiro.largura, primeiro.duracao) == (True, 1, 180, 2.0)
    assert (depois.tem_audio, depois.faixa_audio) == (True, 0)
    assert (so_apac.tem_audio, so_apac.faixa_audio) == (False, 0)
    with pytest.raises(ErroMidia, match="não é um vídeo que o ffmpeg"):  # quando o que falta é o próprio vídeo
        midia.interpretar_sonda("Could not find codec parameters for stream 0 (Video: none (xyz1)): unknown codec\n"
                                "  Duration: 00:00:02.00\n  Stream #0:0: Video: none (xyz1 / 0x31797a78)")


def test_importa_e_exporta_o_video_do_iphone_16(apac, estudio, monkeypatch):
    assert len(ler_audio(apac["primeiro"], faixa=1)) == pytest.approx(2 * TAXA_ANALISE, abs=800)
    assert medir_volume(apac["primeiro"], 0.4, 1.2, faixa=1) is not None
    projeto = estudio.criar("iPhone 16")
    _, clipe, item = _importar(estudio, projeto.id, apac["primeiro"])
    assert clipe.tem_audio and clipe.fala_inicio == pytest.approx(0.5, abs=0.05)
    _, mudo, _ = _importar(estudio, projeto.id, apac["so_apac"])
    assert [a.codigo for a in mudo.avisos] == ["sem_audio"]

    saida = _exportar(estudio, projeto.id)
    som = ler_audio(saida)
    assert np.abs(som[: int((item.saida - item.entrada) * TAXA_ANALISE)]).max() > 0.1  # a fala, não silêncio

    falso = WhisperFalso()
    monkeypatch.setattr(transcricao, "_carregar_modelo", lambda modelo, dispositivo: falso)
    monkeypatch.setattr(transcricao, "_modelos_prontos", set())
    assert transcricao.transcrever(estudio.arquivo_midia(projeto.id, clipe), "pt").palavras
    assert falso.pedidos[0]["amostras"] == pytest.approx(2 * TAXA_ANALISE, abs=800)


# WebM gravado pelo navegador ou por gravador de tela, sem a duração no cabeçalho


def test_webm_sem_duracao_no_cabecalho(tmp_path, estudio):
    webm = tmp_path / "gravacao.webm"
    with open(webm, "wb") as saida:  # gravado num cano, como faz o MediaRecorder: o muxer não volta para pôr a duração
        subprocess.run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=360x640:r=30:d=3", "-f", "lavfi",
                        "-i", "sine=d=3", "-c:v", "libvpx", "-c:a", "libopus", "-f", "webm", "-"], stdout=saida,
                       check=True)
    texto = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(webm)], capture_output=True, text=True).stderr
    assert "Duration: N/A" in texto
    info = sondar(webm)
    assert info.duracao == pytest.approx(3.0, abs=0.05) and (info.largura, info.altura) == (360, 640)
    projeto = estudio.criar()
    _, clipe, item = _importar(estudio, projeto.id, webm)
    assert clipe.duracao == pytest.approx(3.0, abs=0.05) and item.saida == pytest.approx(3.0, abs=0.05)


# Forma de onda de clipe longo


@pytest.mark.parametrize("segundos", [125, 130, 200])
def test_onda_de_clipe_longo_fica_no_lugar(segundos):
    audio = np.zeros(segundos * TAXA_ANALISE, dtype=np.float32)
    som = int((segundos - 0.1) * TAXA_ANALISE)
    audio[som:som + 160] = 0.5
    onda = picos_onda(audio)
    # A tela acha o pico de cada instante t no índice t·por_segundo.
    assert len(onda["picos"]) / onda["por_segundo"] == pytest.approx(segundos, abs=0.02)
    assert int(np.argmax(onda["picos"])) / onda["por_segundo"] == pytest.approx(segundos - 0.1, abs=0.05)


def test_rms_em_blocos_da_o_mesmo_resultado():
    audio = np.random.default_rng(3).normal(0, 0.1, TAXA_ANALISE).astype(np.float32)
    db, janela, passo = midia._rms_db(audio, TAXA_ANALISE)
    inicios = np.arange(len(db)) * passo
    esperado = [20 * np.log10(np.sqrt(np.mean(audio[i:i + janela].astype(np.float64) ** 2)) + 1e-9) for i in inicios]
    assert db == pytest.approx(esperado, abs=1e-6)


# Importação que falha no meio do caminho


@pytest.fixture(scope="module")
def clipe_curto(tmp_path_factory):
    destino = tmp_path_factory.mktemp("curto") / "Bloco 1.mp4"
    _gerar("-f", "lavfi", "-i", "testsrc2=s=180x320:r=24:d=2", "-f", "lavfi", "-i", "sine=f=300:d=2,volume=0.2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "2", destino)
    return destino


def _barrado(*_, **__):
    raise PermissionError(13, "Acesso negado")


def test_importacao_que_falha_no_meio_nao_deixa_arquivos(estudio, clipe_curto, monkeypatch):
    projeto = estudio.criar()
    antes = _arquivos(estudio, projeto.id)

    monkeypatch.setattr(projetos, "gerar_tira", _barrado)
    with pytest.raises(ErroImportacao, match="Não consegui importar “Bloco 1.mp4”.*antivírus ou o OneDrive"):
        _importar(estudio, projeto.id, clipe_curto)
    assert _arquivos(estudio, projeto.id) == antes
    monkeypatch.undo()

    original = os.replace

    def projeto_preso(origem, destino):  # o projeto.json aberto por outro programa na hora de gravar
        if str(destino).endswith("projeto.json"):
            _barrado()
        original(origem, destino)

    monkeypatch.setattr(projetos.os, "replace", projeto_preso)
    with pytest.raises(ErroImportacao, match="Não consegui importar"):
        _importar(estudio, projeto.id, clipe_curto)
    monkeypatch.undo()
    assert [p for p in _arquivos(estudio, projeto.id) if p != "projeto.json.tmp"] == antes
    assert estudio.abrir(projeto.id).midias == []


def test_ffmpeg_barrado_pelo_antivirus_vira_mensagem_clara(estudio, clipe_curto, monkeypatch):
    projeto = estudio.criar()
    monkeypatch.setattr(midia.subprocess, "run", _barrado)
    with pytest.raises(ErroMidia, match="antivírus"):
        sondar(clipe_curto)
    with pytest.raises(ErroImportacao, match="“Bloco 1.mp4”: Não consegui rodar o ffmpeg.*antivírus"):
        _importar(estudio, projeto.id, clipe_curto)
    assert _arquivos(estudio, projeto.id) == ["projeto.json"]


def test_api_explica_a_falha_da_importacao(estudio, clipe_curto, monkeypatch):
    cliente = TestClient(criar_app(estudio), raise_server_exceptions=False)
    pid = cliente.post("/api/projetos", json={}, headers=CABECALHO).json()["id"]
    monkeypatch.setattr(projetos, "gerar_tira", _barrado)
    with open(clipe_curto, "rb") as arquivo:
        r = cliente.post(f"/api/projetos/{pid}/midias", files={"arquivo": ("Bloco 1.mp4", arquivo)}, headers=CABECALHO)
    assert r.status_code == 400 and "Não consegui importar" in r.json()["detail"]


def test_exportacao_com_ffmpeg_barrado_explica(estudio, clipe_curto, monkeypatch):
    projeto = estudio.criar()
    _importar(estudio, projeto.id, clipe_curto)
    original = subprocess.Popen

    def montagem_barrada(args, *resto, **opcoes):  # só o ffmpeg que monta os trechos, depois de sondar e medir
        if "-progress" in args and "pipe:1" in args and "-filter_complex" in args:
            _barrado()
        return original(args, *resto, **opcoes)

    monkeypatch.setattr(exp.subprocess, "Popen", montagem_barrada)
    resultado = exp.Exportador(estudio).iniciar(projeto.id, sincrono=True)
    assert resultado.estado == "erro" and "antivírus" in resultado.erro


# Cache de trechos no Windows: arquivo aberto por outro programa (OneDrive, antivírus, indexador)


def test_trecho_velho_preso_nao_derruba_a_exportacao(estudio, clipe_curto, monkeypatch):
    projeto = estudio.criar("Teste")
    _, _, item = _importar(estudio, projeto.id, clipe_curto)
    _exportar(estudio, projeto.id)
    pasta = estudio.pasta_cache(projeto.id) / "trechos"
    velhos = list(pasta.glob("*.mov"))

    estudio.aplicar(projeto.id, Ajustes(nome="Teste", igualar_volume=False,
                                        linha=[Item(id=item.id, midia_id=item.midia_id, entrada=0.5, saida=1.5)]))
    original = Path.unlink

    def preso(caminho, *args, **kwargs):
        if caminho.parent == pasta and caminho.suffix == ".mov" and caminho in velhos:
            raise PermissionError(13, "O arquivo já está sendo usado por outro processo")
        return original(caminho, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", preso)
    saida = _exportar(estudio, projeto.id)
    assert saida.exists() and all(v.exists() for v in velhos)  # fica para a próxima limpeza


def test_troca_tenta_de_novo_enquanto_o_antivirus_le_o_arquivo(estudio, clipe_curto, monkeypatch):
    projeto = estudio.criar()
    _importar(estudio, projeto.id, clipe_curto)
    original, falhas = os.replace, []

    def antivirus(origem, destino):  # cada arquivo novo fica preso nas duas primeiras tentativas
        if falhas.count(str(destino)) < 2:
            falhas.append(str(destino))
            raise PermissionError(13, "O arquivo já está sendo usado por outro processo")
        original(origem, destino)

    monkeypatch.setattr(exp.os, "replace", antivirus)
    monkeypatch.setattr(exp, "trocar", lambda origem, destino, f=exp.trocar: f(origem, destino, espera=0))
    saida = _exportar(estudio, projeto.id)
    assert saida.exists() and len(falhas) == 4  # o trecho e o vídeo final
    assert not list(estudio.pasta_exportados(projeto.id).glob("*.tmp"))
