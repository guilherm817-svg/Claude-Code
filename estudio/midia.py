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


ERRO_AO_RODAR = ("Não consegui rodar o ffmpeg, o programa que o Estúdio usa para ler e montar os vídeos. Confira se "
                 "o antivírus não bloqueou o ffmpeg.exe e tente de novo.")


def rodar(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", *args], capture_output=True,
                              creationflags=SEM_JANELA)
    except OSError as erro:  # no Windows, antivírus ou Smart App Control barrando o ffmpeg.exe
        raise ErroMidia(ERRO_AO_RODAR) from erro


@lru_cache(maxsize=1)
def filtros() -> frozenset[str]:
    """Os filtros que este ffmpeg tem. Nem todo build traz os opcionais, como o zscale e o tonemap."""
    texto = rodar(["-filters"]).stdout.decode("utf-8", "replace")
    return frozenset(re.findall(r"^ [A-Z.|]{3} (\w+) ", texto, re.M))


# Sondagem


@dataclass
class Cor:
    """As marcações de cor do vídeo, como o ffmpeg mostra. Vazio: o arquivo não diz."""
    matriz: str = ""  # bt709, bt470bg, bt2020nc…
    primarias: str = ""
    transferencia: str = ""  # arib-std-b67 é o HLG do iPhone; smpte2084, o PQ (HDR10)
    faixa: str = ""  # tv (limitada) ou pc (completa)

    @property
    def hdr(self) -> bool:
        return self.transferencia in ("arib-std-b67", "smpte2084")


@dataclass
class InfoVideo:
    duracao: float
    largura: int  # já considerando a rotação gravada pelo celular
    altura: int
    fps: float
    codec: str
    tem_audio: bool
    faixa_audio: int = 0  # a faixa de áudio usada (0:a:N): a primeira que o ffmpeg sabe decodificar
    cor: Cor = field(default_factory=Cor)


_DURACAO = re.compile(r"Duration: (\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_STREAM = re.compile(r"^\s*Stream #\d+:(\d+).*?: (Video|Audio|Subtitle|Data|Attachment): (.*)$")
_SEM_PARAMETROS = re.compile(r"could not find codec parameters for stream (\d+)", re.I)
_TAMANHO = re.compile(r"(?:^|[ ,])(\d{2,5})x(\d{2,5})(?=[ ,\[]|$)")
_FPS = re.compile(r"(\d+(?:\.\d+)?)(k?) fps")
_TBR = re.compile(r"(\d+(?:\.\d+)?)(k?) tbr")
_ROTACAO = re.compile(r"rotation of (-?\d+(?:\.\d+)?) degrees|^\s*rotate\s*:\s*(-?\d+)")
# O formato dos pixels vem colado nos parênteses com a faixa e as cores: "yuv420p10le(tv, bt2020nc/bt2020/smpte2084)".
_PIXELS = re.compile(r", [a-z0-9_]+\(([^)]*)\)")
_MATRIZES = {"rgb", "bt709", "fcc", "bt470bg", "smpte170m", "smpte240m", "ycgco", "bt2020nc", "bt2020c", "smpte2085",
             "chroma-derived-nc", "chroma-derived-c", "ictcp"}


def _taxa(regex: re.Pattern, texto: str) -> float:
    m = regex.search(texto)
    return float(m.group(1)) * (1000 if m.group(2) else 1) if m else 0.0


def _cor(video: str) -> Cor:
    cor = Cor()
    if not (m := _PIXELS.search(video)):
        return cor
    for parte in m.group(1).split(", "):
        if parte in ("tv", "pc"):
            cor.faixa = parte
        elif parte.count("/") == 2 or parte in _MATRIZES:
            nomes = parte.split("/") if "/" in parte else [parte] * 3  # as três iguais vêm num nome só
            cor.matriz, cor.primarias, cor.transferencia = ("" if n == "unknown" else n for n in nomes)
    return cor


def interpretar_sonda(texto: str, duracao_medida: float = 0.0) -> InfoVideo:
    """Lê a saída de `ffmpeg -i arquivo` (o ffmpeg embutido não traz o ffprobe). duracao_medida: a duração medida
    lendo o arquivo, usada quando o cabeçalho não traz a duração (Duration: N/A)."""
    duracao = duracao_medida
    if m := _DURACAO.search(texto):
        h, mi, s = m.groups()
        duracao = int(h) * 3600 + int(mi) * 60 + float(s)

    # Stream que o ffmpeg não sabe decodificar (como o áudio espacial APAC do iPhone 16) não impede de usar os outros.
    sem_parametros = {int(n) for n in _SEM_PARAMETROS.findall(texto)}
    video, ilegivel, rotacao, faixa_audio, no_video = None, False, 0, None, False
    n_audio = 0
    for linha in texto.splitlines():
        if s := _STREAM.match(linha):
            indice, tipo, resto = int(s.group(1)), s.group(2), s.group(3)
            legivel = indice not in sem_parametros and not resto.startswith("none")
            no_video = False
            if tipo == "Video" and video is None and "attached pic" not in resto:
                if legivel:
                    video, no_video = resto, True
                else:
                    ilegivel = True
            elif tipo == "Audio":
                if legivel and faixa_audio is None:
                    faixa_audio = n_audio
                n_audio += 1
        elif no_video and (r := _ROTACAO.search(linha)):
            rotacao = round(float(r.group(1) or r.group(2)))

    if video is None:
        raise ErroMidia("Este arquivo não é um vídeo que o ffmpeg consiga ler." if ilegivel else
                        "O arquivo não tem vídeo.")
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
        codec=video.split(maxsplit=1)[0].strip(","), tem_audio=faixa_audio is not None,
        faixa_audio=faixa_audio or 0, cor=_cor(video),
    )


def medir_duracao(caminho: Path) -> float:
    """Duração lida percorrendo o arquivo sem decodificar, para vídeos sem a duração no cabeçalho (o WebM gravado
    pelo navegador ou por gravadores de tela). 0 se não der."""
    r = rodar(["-v", "error", "-i", str(caminho), "-map", "0:v:0", "-c", "copy", "-progress", "pipe:1", "-nostats",
               "-f", "null", "-"])
    tempos = re.findall(r"^out_time_us=(\d+)", r.stdout.decode("ascii", "replace"), re.M)
    return int(tempos[-1]) / 1_000_000 if tempos else 0.0


def sondar(caminho: Path) -> InfoVideo:
    texto = rodar(["-i", str(caminho)]).stderr.decode("utf-8", "replace")
    if not re.search(r"^\s*Stream #", texto, re.M):
        raise ErroMidia("Este arquivo não é um vídeo que o ffmpeg consiga ler.")
    return interpretar_sonda(texto, 0.0 if _DURACAO.search(texto) else medir_duracao(caminho))


# Áudio


def ler_audio(caminho: Path, taxa: int = TAXA_ANALISE, faixa: int = 0) -> np.ndarray:
    """Áudio em mono, float32 entre -1 e 1, no tempo do vídeo. Vazio se o arquivo não tiver som.

    A saída crua não leva os tempos: sem o aresample, um áudio que começa depois do vídeo (comum em vídeo de celular
    ou recortado em outro programa) chegaria adiantado, e a fala, a onda e as legendas sairiam fora do lugar."""
    r = rodar(["-v", "error", "-i", str(caminho), "-map", f"0:a:{faixa}", "-vn", "-af", "aresample=async=1:first_pts=0",
               "-ac", "1", "-ar", str(taxa), "-f", "s16le", "-"])
    if r.returncode != 0:
        return np.zeros(0, dtype=np.float32)
    audio = np.frombuffer(r.stdout, dtype="<i2").astype(np.float32)
    audio /= 32768.0  # no lugar, para um vídeo longo não ocupar o dobro de memória
    return audio


def _rms_db(audio: np.ndarray, taxa: int, janela_s: float = 0.02, passo_s: float = 0.01) -> tuple[np.ndarray, int, int]:
    janela, passo = int(taxa * janela_s), int(taxa * passo_s)
    if len(audio) < janela:
        return np.zeros(0), janela, passo
    n = 1 + (len(audio) - janela) // passo
    # Soma acumulada feita no lugar: num vídeo longo, cada cópia do áudio em float64 ocupa centenas de MB.
    acumulado = np.square(audio, dtype=np.float64)
    np.cumsum(acumulado, out=acumulado)
    inicios = np.arange(n) * passo
    antes = np.where(inicios > 0, acumulado[np.maximum(inicios - 1, 0)], 0.0)
    rms = np.sqrt(np.maximum(acumulado[inicios + janela - 1] - antes, 0) / janela)
    return 20 * np.log10(rms + 1e-9), janela, passo


# A fala é procurada em três faixas de frequência, cada uma comparada com o ruído de fundo dela mesma: os graves e os
# agudos da voz e o chiado (s, f, x, ch). O som de ambiente se concentra nos graves e quase não tem chiado, então um
# "s" fraco no começo ou no fim da frase aparece na faixa do chiado mesmo quando some no total. E o ambiente que só
# fica mais alto (vento, trânsito, ar-condicionado) sobe as três por igual, enquanto a fala sobe umas mais que outras.
FAIXAS_FALA = ((200, 1000), (1000, 3500), (3500, 8000))  # Hz
CONTRASTE_MINIMO = 12  # dB entre o ruído e o pico: abaixo disso a fala mal passa do ruído e o corte comeria palavras
PAUSA_DENTRO_DA_FALA = 0.3  # s: sons separados por pausas menores que isto fazem parte da mesma fala
PAUSA_PALAVRA_SOLTA = 0.9  # s: a maior vírgula entre a fala e uma palavra solta ("Ei, ...", "..., tá?")
PALAVRA_SOLTA = 0.07  # s de som que uma palavra solta tem pelo menos; um estalo dura só 20–30 ms
SOM_BAIXO_COLADO = 0.3  # s de som bem abaixo da voz que ainda entra colado nela (consoante fraca, eco)
PONTA_DO_CLIPE = 0.3  # s no começo e no fim do clipe onde se mede o fundo (trilha, ambiente)
# O som no nível da voz tem de começar (ou terminar) a menos disto da borda para o aviso de palavra cortada: som fraco
# encostado na borda (trilha, ambiente) não é palavra cortada.
VOZ_PERTO_DA_BORDA = 0.25


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


def _media_movel(db: np.ndarray, k: int) -> np.ndarray:
    """Energia média de k trechos seguidos (centrada), em dB, em cada faixa."""
    return 10 * np.log10(np.array([np.convolve(np.pad(10 ** (faixa / 10), (k // 2, k - 1 - k // 2), mode="edge"),
                                               np.ones(k) / k, mode="valid") for faixa in db]))


def _seguidos(marcados: np.ndarray, k: int) -> np.ndarray:
    """Os trechos que fazem parte de alguma sequência de pelo menos k marcados."""
    comeco = np.convolve(marcados.astype(int), np.ones(k, dtype=int), mode="valid") == k
    return np.convolve(comeco.astype(int), np.ones(k, dtype=int))[:len(marcados)] > 0


@dataclass
class Fala:
    """Onde está a fala de um clipe, em segundos."""
    inicio: float
    fim: float
    voz: tuple[float, float]  # do primeiro ao último trecho no nível da voz; fora dele só há som mais fraco


def medir_fala(audio: np.ndarray, taxa: int = TAXA_ANALISE) -> Fala | None:
    """Onde a fala começa e termina, com a sílaba fraca, a palavra solta e o efeito sonoro logo antes dela.

    Compara cada trecho de 20 ms com o ruído de fundo do próprio clipe, então funciona com o "som de ambiente" que o
    Veo coloca por baixo da fala. Devolve None quando não dá para cortar com segurança (clipe mudo, só ruído ou
    música contínua, ou fala quase no nível do ruído), e aí o clipe entra inteiro.
    """
    db, janela, passo = _energia_por_faixa(audio, taxa)
    n = db.shape[1]
    if n < 10 or np.percentile(_rms_db(audio, taxa)[0], 98) < -50:
        return None
    por_segundo = taxa / passo
    piso_trecho = np.percentile(db, 5, axis=1, keepdims=True)
    if (np.percentile(db, 98, axis=1, keepdims=True) - piso_trecho).max() < CONTRASTE_MINIMO:
        return None
    # A média de 100 ms junta as sílabas e não deixa a variação natural do ruído passar por som.
    k = round(0.1 * por_segundo)
    media = _media_movel(db, k)
    piso = np.percentile(media, 5, axis=1, keepdims=True)
    acima = media - piso
    contraste = acima.max(axis=0) - acima.min(axis=0)  # quanto umas faixas subiram mais que as outras
    # Nível da voz: o que o clipe passa durante meio segundo (ou metade dele, se for curto). Um efeito curto e mais
    # alto que a fala não conta.
    nivel_voz = np.sort(media.max(axis=0))[::-1][min(n // 2, round(0.5 * por_segundo))]
    nivel = media.max(axis=0) - nivel_voz

    # Fundo: o som que o clipe tem nas duas pontas, onde ninguém fala (trilha, ambiente mais alto). Vale só o que
    # aparece nas duas, bem abaixo da voz e no máximo 10 dB acima do ruído, para nunca esconder uma palavra.
    fundo = np.zeros_like(piso)
    m = round(PONTA_DO_CLIPE * por_segundo)
    if n > 3 * m:
        pontas = np.minimum(media[:, :m].max(axis=1, keepdims=True), media[:, -m:].max(axis=1, keepdims=True))
        fundo = np.clip(np.minimum(pontas - 2, nivel_voz - 12) - piso, 0, 10)

    # Voz clara: 50 ms seguidos 10 dB acima do ruído e do fundo, a menos de 18 dB do nível da voz e com as faixas
    # subindo de modo diferente. Um estalo isolado não chega a tanto, nem a respiração, nem o ambiente que só subiu.
    forte = (db > np.maximum(piso_trecho + fundo + 10, nivel_voz - 18)).any(axis=0) & (contraste >= 3)
    clara = _seguidos(forte, 5)
    if not clara.any():
        return None

    # Som: passa 4 dB do ruído numa faixa, está a menos de 24 dB da voz e as faixas sobem de modo diferente (ou já está
    # no nível da voz); ou é um estalo forte, 20 ms 18 dB acima do ruído e a menos de 16 dB da voz. Colado na voz clara
    # vale o ruído; longe dela, conta também o fundo, para a trilha não virar som.
    perto_da_voz = np.convolve(clara.astype(int), np.ones(2 * round(0.15 * por_segundo) + 1), mode="same") > 0
    fundo_aqui = np.where(perto_da_voz, 0, fundo)
    estalo = ((db - piso_trecho - fundo_aqui).max(axis=0) >= 18) & (db.max(axis=0) >= nivel_voz - 16)
    no_nivel_da_voz = clara | estalo | ((nivel >= -10) & (contraste >= 2))
    som = clara | (((acima - fundo_aqui) > 4).any(axis=0)
                   & (estalo | ((nivel >= -24) & ((contraste >= 3) | no_nivel_da_voz))))
    # Som de verdade em cada trecho de 20 ms, na voz inteira ou no chiado: nas faixas largas o ruído varia menos.
    largas = np.vstack([10 * np.log10(10 ** (db[0] / 10) + 10 ** (db[1] / 10)), db[2]])
    com_som = (largas > np.maximum(np.percentile(largas, 5, axis=1, keepdims=True) + 3, nivel_voz - 50)).any(axis=0)

    # Sons separados por pausas curtas formam um bloco: as sílabas, a consoante fraca, o splash ou o estalo logo antes
    # da primeira palavra. A fala vai do primeiro ao último bloco com voz clara e leva junto a palavra solta depois de
    # uma vírgula, mesmo fraca demais para ter voz clara: com som de palavra (não de estalo) e no nível da voz.
    blocos = []
    for a, b in _trechos(som):
        if blocos and a - blocos[-1][1] - 1 <= PAUSA_DENTRO_DA_FALA * por_segundo:
            blocos[-1][1] = b
        else:
            blocos.append([a, b])
    palavra = [com_som[a:b + 1].sum() >= PALAVRA_SOLTA * por_segundo and no_nivel_da_voz[a:b + 1].any()
               for a, b in blocos]
    com_voz = [i for i, (a, b) in enumerate(blocos) if clara[a:b + 1].any()]
    primeiro, ultimo = com_voz[0], com_voz[-1]
    vao = PAUSA_PALAVRA_SOLTA * por_segundo
    while primeiro > 0 and palavra[primeiro - 1] and blocos[primeiro][0] - blocos[primeiro - 1][1] - 1 <= vao:
        primeiro -= 1
    while ultimo < len(blocos) - 1 and palavra[ultimo + 1] and blocos[ultimo + 1][0] - blocos[ultimo][1] - 1 <= vao:
        ultimo += 1
    ini, fim = blocos[primeiro][0], blocos[ultimo][1]

    # Som bem abaixo da voz colado nela entra só se for curto (consoante fraca, eco). Mais longo é fundo: respiração,
    # trilha.
    nucleo = np.flatnonzero(no_nivel_da_voz[ini:fim + 1]) + ini
    if nucleo[0] - ini > SOM_BAIXO_COLADO * por_segundo:
        ini = nucleo[0] - k
    if fim - nucleo[-1] > SOM_BAIXO_COLADO * por_segundo:
        fim = nucleo[-1] + k

    # A média começa a subir meia janela antes do som e termina meia janela depois: as bordas voltam até o primeiro e
    # o último trecho de 20 ms com som de verdade. Um trecho sozinho é o próprio ruído variando.
    borda = com_som & (np.convolve(com_som.astype(int), [1, 0, 1], mode="same") > 0)
    for _ in range(k // 2):
        if ini < fim and not borda[ini]:
            ini += 1
        if fim > ini and not borda[fim]:
            fim -= 1

    def comeco(trecho: int) -> float:
        return round(float(trecho * passo / taxa), 3)

    def final(trecho: int) -> float:
        return round(float(min((trecho * passo + janela) / taxa, len(audio) / taxa)), 3)

    voz = np.flatnonzero(no_nivel_da_voz[ini:fim + 1]) + ini
    if not len(voz):
        voz = np.array([ini, fim])
    return Fala(inicio=comeco(ini), fim=final(fim), voz=(comeco(voz[0]), final(voz[-1])))


def detectar_fala(audio: np.ndarray, taxa: int = TAXA_ANALISE) -> tuple[float, float] | None:
    """Onde o som útil (a fala) começa e termina, em segundos. None quando o clipe deve entrar inteiro."""
    fala = medir_fala(audio, taxa)
    return (fala.inicio, fala.fim) if fala else None


def picos_onda(audio: np.ndarray, taxa: int = TAXA_ANALISE) -> dict:
    """Forma de onda resumida para desenhar na tela: o pico de cada pedacinho, de 0 a 1."""
    duracao = len(audio) / taxa if taxa else 0
    tamanho = max(1, taxa // (100 if duracao <= 120 else max(10, int(12000 / duracao))))
    por_segundo = taxa / tamanho  # a taxa real: a tela acha cada pico por t·por_segundo
    n = len(audio) // tamanho
    if n == 0:
        return {"por_segundo": por_segundo, "picos": []}
    picos = np.abs(audio[: n * tamanho]).reshape(n, tamanho).max(axis=1)
    maior = float(picos.max())
    if maior > 0:
        picos = picos / maior
    return {"por_segundo": por_segundo, "picos": [round(float(p), 3) for p in picos]}


def medir_volume(caminho: Path, entrada: float, duracao: float, faixa: int = 0) -> tuple[float, float] | None:
    """Volume percebido (LUFS) e pico real (dBTP) de um trecho. None se o trecho for mudo ou curto demais."""
    r = rodar(["-nostats", "-ss", f"{entrada:.3f}", "-t", f"{duracao:.3f}", "-i", str(caminho), "-map", f"0:a:{faixa}",
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


def avisos_do_clipe(info: InfoVideo, fala: tuple[float, float] | None, onda: dict,
                    voz: tuple[float, float] | None = None) -> list[dict]:
    """Avisos sobre o som do clipe. voz: onde o som no nível da voz começa e termina (Fala.voz), se já medido."""
    if not info.tem_audio:
        return [{"codigo": "sem_audio", "texto": "Este clipe não tem som."}]
    if fala is None:
        mudo = not onda["picos"] or max(onda["picos"]) == 0
        texto = ("O som deste clipe está mudo." if mudo else
                 "Não encontrei uma fala clara neste clipe, então ele entra inteiro, sem corte automático.")
        return [{"codigo": "sem_fala", "texto": texto}]
    avisos = []
    if fala[0] < BORDA_SUSPEITA and (voz is None or voz[0] < VOZ_PERTO_DA_BORDA):
        avisos.append({"codigo": "fala_no_inicio", "texto": "A fala começa já no primeiro quadro: a primeira "
                       "palavra pode ter saído cortada na geração. Ouça o começo antes de exportar."})
    if fala[1] > info.duracao - BORDA_SUSPEITA and (voz is None or voz[1] > info.duracao - VOZ_PERTO_DA_BORDA):
        avisos.append({"codigo": "fala_no_fim", "texto": "A fala vai até o último quadro: a última palavra pode "
                       "ter saído cortada na geração."})
    return avisos


def analisar(caminho: Path) -> AnaliseClipe:
    info = sondar(caminho)
    audio = ler_audio(caminho, faixa=info.faixa_audio) if info.tem_audio else np.zeros(0, dtype=np.float32)
    medida = medir_fala(audio)
    fala = (medida.inicio, medida.fim) if medida else None
    onda = picos_onda(audio)
    return AnaliseClipe(info=info, fala=fala, onda=onda,
                        avisos=avisos_do_clipe(info, fala, onda, medida.voz if medida else None))
