"""Leitura dos vídeos com o ffmpeg: sondar o arquivo, ler o áudio, achar onde a fala começa e termina, medir o
volume e gerar as miniaturas e a forma de onda da linha do tempo."""

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

TAXA_ANALISE = 16000  # Hz: o suficiente para achar a fala e desenhar a onda
ALTURA_MINIATURA = 96  # px de cada quadro da tira de miniaturas
# Abaixo destes limites, a fala começa (ou termina) colada na borda do clipe: sinal de palavra cortada na geração.
BORDA_SUSPEITA = 0.06


class ErroMidia(Exception):
    """Arquivo que não dá para usar como vídeo."""


@lru_cache(maxsize=1)
def ffmpeg() -> str:
    """O ffmpeg que vem embutido no pacote imageio-ffmpeg ou, na falta dele, o instalado no sistema."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        caminho = shutil.which("ffmpeg")
        if not caminho:
            raise ErroMidia("ffmpeg não encontrado. Abra o Estúdio pelo iniciar-estudio para instalar as dependências.")
        return caminho


# No Windows, sem isso cada chamada ao ffmpeg pisca uma janela preta.
SEM_JANELA = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def rodar(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", *args], capture_output=True, creationflags=SEM_JANELA)


# Sondagem


@dataclass
class InfoVideo:
    duracao: float
    largura: int  # já considerando a rotação gravada pelo celular
    altura: int
    fps: float
    codec: str
    tem_audio: bool


_DURACAO = re.compile(r"Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_STREAM = re.compile(r"^\s*Stream #\d+:\d+.*?: (Video|Audio|Subtitle|Data|Attachment): (.*)$")
_TAMANHO = re.compile(r"(?:^|[ ,])(\d{2,5})x(\d{2,5})(?=[ ,\[]|$)")
_FPS = re.compile(r"(\d+(?:\.\d+)?)(k?) fps")
_TBR = re.compile(r"(\d+(?:\.\d+)?)(k?) tbr")
_ROTACAO = re.compile(r"rotation of (-?\d+(?:\.\d+)?) degrees|^\s*rotate\s*:\s*(-?\d+)")


def _taxa(regex: re.Pattern, texto: str) -> float:
    m = regex.search(texto)
    return float(m.group(1)) * (1000 if m.group(2) else 1) if m else 0.0


def interpretar_sonda(texto: str) -> InfoVideo:
    """Lê a saída de `ffmpeg -i arquivo` (o ffmpeg embutido não traz o ffprobe)."""
    duracao = 0.0
    if m := _DURACAO.search(texto):
        h, mi, s = m.groups()
        duracao = int(h) * 3600 + int(mi) * 60 + float(s)

    video, rotacao, tem_audio, no_video = None, 0, False, False
    for linha in texto.splitlines():
        if s := _STREAM.match(linha):
            tipo, resto = s.groups()
            no_video = False
            if tipo == "Video" and video is None and "attached pic" not in resto:
                video, no_video = resto, True
            elif tipo == "Audio":
                tem_audio = True
        elif no_video and (r := _ROTACAO.search(linha)):
            rotacao = round(float(r.group(1) or r.group(2)))

    if video is None:
        raise ErroMidia("O arquivo não tem vídeo.")
    tamanho = _TAMANHO.search(video)
    if not tamanho:
        raise ErroMidia("Não consegui ler o tamanho do vídeo.")
    if duracao <= 0:
        raise ErroMidia("Não consegui ler a duração do vídeo.")
    largura, altura = int(tamanho.group(1)), int(tamanho.group(2))
    if abs(rotacao) % 180 == 90:
        largura, altura = altura, largura
    return InfoVideo(
        duracao=round(duracao, 3), largura=largura, altura=altura,
        fps=round(_taxa(_FPS, video) or _taxa(_TBR, video) or 30.0, 3),
        codec=video.split(maxsplit=1)[0].strip(","), tem_audio=tem_audio,
    )


def sondar(caminho: Path) -> InfoVideo:
    texto = rodar(["-i", str(caminho)]).stderr.decode("utf-8", "replace")
    if "Invalid data found" in texto or "could not find codec parameters" in texto.lower():
        raise ErroMidia("Este arquivo não é um vídeo que o ffmpeg consiga ler.")
    return interpretar_sonda(texto)


# Áudio


def ler_audio(caminho: Path, taxa: int = TAXA_ANALISE) -> np.ndarray:
    """Áudio em mono, float32 entre -1 e 1. Vazio se o arquivo não tiver som."""
    r = rodar(["-v", "error", "-i", str(caminho), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(taxa),
               "-f", "s16le", "-"])
    if r.returncode != 0:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768.0


def _rms_db(audio: np.ndarray, taxa: int, janela_s: float = 0.02, passo_s: float = 0.01) -> tuple[np.ndarray, int, int]:
    janela, passo = int(taxa * janela_s), int(taxa * passo_s)
    if len(audio) < janela:
        return np.zeros(0), janela, passo
    n = 1 + (len(audio) - janela) // passo
    acumulado = np.concatenate([[0.0], np.cumsum(audio.astype(np.float64) ** 2)])
    inicios = np.arange(n) * passo
    rms = np.sqrt(np.maximum(acumulado[inicios + janela] - acumulado[inicios], 0) / janela)
    return 20 * np.log10(rms + 1e-9), janela, passo


# A fala é procurada em duas faixas de frequência, cada uma comparada com o ruído de fundo dela mesma: a da voz
# (vogais e nasais) e a do chiado (s, f, x, ch). O som de ambiente se concentra nos graves e quase não tem
# chiado, então um "s" fraco no começo ou no fim da frase aparece na segunda faixa mesmo quando some no total.
FAIXAS_FALA = ((200, 3500), (3500, 8000))  # Hz
PAUSA_DENTRO_DA_FALA = 0.3  # s: sons separados por pausas menores que isto fazem parte da mesma fala
PALAVRA_FRACA = 0.2  # s: som contínuo, mesmo baixo, que dura isto conta como fala


def _energia_por_faixa(audio: np.ndarray, taxa: int, janela_s: float = 0.02,
                       passo_s: float = 0.01) -> tuple[np.ndarray, int, int]:
    """Energia em dBFS de cada trecho de 20 ms, a cada 10 ms, em cada faixa de FAIXAS_FALA: (faixas, trechos)."""
    janela, passo = int(taxa * janela_s), int(taxa * passo_s)
    if len(audio) < janela:
        return np.zeros((len(FAIXAS_FALA), 0)), janela, passo
    n = 1 + (len(audio) - janela) // passo
    frequencias = np.fft.rfftfreq(janela, 1 / taxa)
    faixas = [(frequencias >= baixa) & (frequencias < alta) for baixa, alta in FAIXAS_FALA]
    peso = np.hanning(janela).astype(np.float32)
    quadros = np.lib.stride_tricks.sliding_window_view(audio, janela)[::passo][:n]
    energia = np.empty((len(faixas), n))
    for i in range(0, n, 4096):  # em blocos, para um vídeo longo não ocupar memória demais
        espectro = np.abs(np.fft.rfft(quadros[i:i + 4096] * peso, axis=1)) ** 2
        for f, faixa in enumerate(faixas):
            energia[f, i:i + 4096] = espectro[:, faixa].sum(axis=1)
    energia /= (peso.astype(np.float64) ** 2).sum() * janela / 2
    return 10 * np.log10(energia + 1e-12), janela, passo


def _trechos(marcados: np.ndarray) -> list[tuple[int, int]]:
    """Início e fim (inclusive) de cada sequência de valores verdadeiros."""
    bordas = np.diff(np.concatenate([[0], marcados.astype(int), [0]]))
    return list(zip(np.flatnonzero(bordas == 1), np.flatnonzero(bordas == -1) - 1))


def detectar_fala(audio: np.ndarray, taxa: int = TAXA_ANALISE) -> tuple[float, float] | None:
    """Onde o som útil (a fala) começa e termina, em segundos.

    Compara cada trecho de 20 ms com o ruído de fundo do próprio clipe, então funciona com o "som de ambiente"
    que o Veo coloca por baixo da fala. Devolve None quando não há contraste (clipe mudo ou só ruído/música
    contínua), e aí o corte automático não é aplicado.
    """
    db, janela, passo = _energia_por_faixa(audio, taxa)
    n = db.shape[1]
    if n < 10 or np.percentile(_rms_db(audio, taxa)[0], 98) < -50:
        return None
    piso = np.percentile(db, 5, axis=1, keepdims=True)
    topo = np.percentile(db, 98, axis=1, keepdims=True)
    com_contraste = (topo - piso >= 10)[:, 0]
    if not com_contraste.any():
        return None
    db, piso, topo = db[com_contraste], piso[com_contraste], topo[com_contraste]

    # Prova de fala: 50 ms seguidos bem acima do ruído em alguma faixa. Um estalo isolado não chega a tanto.
    forte = (db > np.maximum(piso + 10, topo - 30)).any(axis=0)
    comeco_da_prova = np.convolve(forte.astype(int), np.ones(5, dtype=int), mode="valid") == 5
    if not comeco_da_prova.any():
        return None
    prova = np.convolve(comeco_da_prova.astype(int), np.ones(5, dtype=int))[:n] > 0

    # Onde há som: a média de 100 ms da energia acima do ruído. A média junta as sílabas e não deixa a variação
    # natural do ruído passar por som; abaixo de 50 dB do mais alto do clipe é silêncio para qualquer efeito.
    k = round(0.1 * taxa / passo)
    media = np.array([np.convolve(np.pad(10 ** (faixa / 10), (k // 2, k - 1 - k // 2), mode="edge"),
                                  np.ones(k) / k, mode="valid") for faixa in db])
    media = 10 * np.log10(media)
    limiar = np.maximum(np.percentile(media, 5, axis=1, keepdims=True) + 4,
                        np.percentile(media, 98, axis=1, keepdims=True) - 50)
    trechos = _trechos((media > limiar).any(axis=0))

    # Conta como fala o trecho com prova de fala ou que dura uma palavra, mesmo baixinha (a primeira palavra
    # fraca antes de uma vírgula). Tudo entre o primeiro e o último fica.
    palavra = PALAVRA_FRACA * taxa / passo
    fala = [i for i, (a, b) in enumerate(trechos) if prova[a:b + 1].any() or b - a + 1 >= palavra]
    if not fala:
        return None
    primeiro, ultimo = fala[0], fala[-1]
    # Sons separados por uma pausa curta entram junto: a sílaba fraca, a respiração, o splash ou o estalo que
    # vem logo antes da primeira palavra.
    pausa = PAUSA_DENTRO_DA_FALA * taxa / passo
    while primeiro > 0 and trechos[primeiro][0] - trechos[primeiro - 1][1] - 1 <= pausa:
        primeiro -= 1
    while ultimo < len(trechos) - 1 and trechos[ultimo + 1][0] - trechos[ultimo][1] - 1 <= pausa:
        ultimo += 1
    ini, fim = trechos[primeiro][0], trechos[ultimo][1]

    # A média começa a subir meia janela antes do som e termina meia janela depois: as bordas voltam até o
    # primeiro e o último trecho de 20 ms que já têm som de verdade.
    com_som = (db > np.maximum(piso + 3, topo - 50)).any(axis=0)
    for _ in range(k // 2):
        if ini < fim and not com_som[ini]:
            ini += 1
        if fim > ini and not com_som[fim]:
            fim -= 1
    inicio = ini * passo / taxa
    final = (fim * passo + janela) / taxa
    return round(float(inicio), 3), round(float(min(final, len(audio) / taxa)), 3)


def picos_onda(audio: np.ndarray, taxa: int = TAXA_ANALISE) -> dict:
    """Forma de onda resumida para desenhar na tela: o pico de cada pedacinho, de 0 a 1."""
    duracao = len(audio) / taxa if taxa else 0
    por_segundo = 100 if duracao <= 120 else max(10, int(12000 / duracao))
    tamanho = max(1, taxa // por_segundo)
    n = len(audio) // tamanho
    if n == 0:
        return {"por_segundo": por_segundo, "picos": []}
    picos = np.abs(audio[: n * tamanho]).reshape(n, tamanho).max(axis=1)
    maior = float(picos.max())
    if maior > 0:
        picos = picos / maior
    return {"por_segundo": por_segundo, "picos": [round(float(p), 3) for p in picos]}


def medir_volume(caminho: Path, entrada: float, duracao: float) -> tuple[float, float] | None:
    """Volume percebido (LUFS) e pico real (dBTP) de um trecho. None se o trecho for mudo ou curto demais."""
    r = rodar(["-nostats", "-ss", f"{entrada:.3f}", "-t", f"{duracao:.3f}", "-i", str(caminho), "-map", "0:a:0",
               "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    texto = r.stderr.decode("utf-8", "replace")
    inicio, fim = texto.rfind("{"), texto.rfind("}")
    if r.returncode != 0 or inicio < 0 or fim < inicio:
        return None
    try:
        dados = json.loads(texto[inicio:fim + 1])
        integrado, pico = float(dados["input_i"]), float(dados["input_tp"])
    except (ValueError, KeyError):
        return None
    if not np.isfinite(integrado) or not np.isfinite(pico) or integrado < -60:
        return None
    return integrado, pico


# Miniaturas


def gerar_tira(caminho: Path, destino: Path, duracao: float) -> int:
    """Uma imagem com um quadro a cada meio segundo, lado a lado. Devolve quantos quadros ela tem (0 se falhar)."""
    quadros = max(2, min(120, round(duracao / 0.5)))
    r = rodar(["-v", "error", "-y", "-i", str(caminho),
               "-vf", f"fps={quadros / duracao:.6f},scale=-2:{ALTURA_MINIATURA},tile={quadros}x1",
               "-frames:v", "1", "-update", "1", "-q:v", "5", str(destino)])
    return quadros if r.returncode == 0 and destino.exists() else 0


# Análise completa de um clipe importado


@dataclass
class AnaliseClipe:
    info: InfoVideo
    fala: tuple[float, float] | None
    onda: dict
    avisos: list[dict] = field(default_factory=list)


def avisos_do_clipe(info: InfoVideo, fala: tuple[float, float] | None, onda: dict) -> list[dict]:
    if not info.tem_audio:
        return [{"codigo": "sem_audio", "texto": "Este clipe não tem som."}]
    if fala is None:
        mudo = not onda["picos"] or max(onda["picos"]) == 0
        texto = ("O som deste clipe está mudo." if mudo else
                 "Não encontrei uma fala clara neste clipe, então ele entra inteiro, sem corte automático.")
        return [{"codigo": "sem_fala", "texto": texto}]
    avisos = []
    if fala[0] < BORDA_SUSPEITA:
        avisos.append({"codigo": "fala_no_inicio", "texto": "A fala começa já no primeiro quadro: a primeira "
                       "palavra pode ter saído cortada na geração. Ouça o começo antes de exportar."})
    if fala[1] > info.duracao - BORDA_SUSPEITA:
        avisos.append({"codigo": "fala_no_fim", "texto": "A fala vai até o último quadro: a última palavra pode "
                       "ter saído cortada na geração."})
    return avisos


def analisar(caminho: Path) -> AnaliseClipe:
    info = sondar(caminho)
    audio = ler_audio(caminho) if info.tem_audio else np.zeros(0, dtype=np.float32)
    fala = detectar_fala(audio)
    onda = picos_onda(audio)
    return AnaliseClipe(info=info, fala=fala, onda=onda, avisos=avisos_do_clipe(info, fala, onda))
