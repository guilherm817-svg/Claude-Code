"""Corte automático do silêncio com fala de verdade: frases sintetizadas pelo espeak-ng, montadas como os clipes do
Veo (respiro antes e depois, som de ambiente por baixo, às vezes um efeito antes da fala) e codificadas em MP4 e WebM.

A referência do começo e do fim da fala é medida no sinal limpo da síntese, antes de misturar o ruído. O corte
sugerido nunca pode comer fala e também não pode deixar silêncio demais, que no Reels faz a pessoa rolar o feed.

No fim do arquivo há uma bancada com muitos clipes sorteados, que compara o detector atual com o de outro commit
e mostra a tabela antes/depois (sem o commit, só o atual):
    python -m tests.test_estudio_fala [quantidade] [semente] [commit]"""

import shutil
import subprocess
import sys
import tempfile
import types
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from estudio import midia
from estudio.midia import TAXA_ANALISE, InfoVideo, analisar, avisos_do_clipe, detectar_fala, ffmpeg
from estudio.projetos import Midia

TAXA = 48000  # Hz: a taxa do áudio que o Veo entrega
FPS = 24

# Quanto o corte tem de deixar antes e depois do som: no mínimo a margem, no máximo a sobra (s).
MARGEM_ANTES = 0.02
MARGEM_DEPOIS = 0.05
SOBRA_ANTES = 0.30
SOBRA_DEPOIS = 0.45

sem_espeak = pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng não instalado")


# Geração dos clipes


def sintetizar(texto: str, voz: str, velocidade: int) -> np.ndarray:
    """Fala do espeak-ng em mono, float32 a 48 kHz."""
    wav = subprocess.run(["espeak-ng", "-v", voz, "-s", str(velocidade), "--stdout", texto],
                         capture_output=True, check=True).stdout
    r = subprocess.run([ffmpeg(), "-v", "error", "-f", "wav", "-i", "-", "-ac", "1", "-ar", str(TAXA),
                        "-f", "f32le", "-"], input=wav, capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype="<f4").copy()


def limites_reais(sinal: np.ndarray, abaixo_do_pico: float = 40.0) -> tuple[int, int]:
    """Primeira e última amostra do som, com limiar bem baixo (40 dB abaixo do pico da própria fala)."""
    janela, passo = int(TAXA * 0.005), int(TAXA * 0.001)
    acumulado = np.concatenate([[0.0], np.cumsum(sinal.astype(np.float64) ** 2)])
    inicios = np.arange(1 + (len(sinal) - janela) // passo) * passo
    db = 10 * np.log10((acumulado[inicios + janela] - acumulado[inicios]) / janela + 1e-20)
    acima = np.flatnonzero(db > db.max() - abaixo_do_pico)
    return int(inicios[acima[0]]), int(inicios[acima[-1]] + janela)


def ruido_ambiente(n: int, nivel_db: float, cor: str, rng: np.random.Generator) -> np.ndarray:
    """Som de ambiente com o RMS pedido: branco (chiado), rosa (sala) ou marrom (ar-condicionado, trânsito)."""
    espectro = np.fft.rfft(rng.normal(size=n))
    freqs = np.fft.rfftfreq(n, 1 / TAXA)
    expoente = {"branco": 0.0, "rosa": 0.5, "marrom": 1.0}[cor]
    espectro *= np.where(freqs > 40, 1 / np.maximum(freqs, 40) ** expoente, 0)
    sinal = np.fft.irfft(espectro, n)
    return (sinal / np.sqrt(np.mean(sinal ** 2)) * 10 ** (nivel_db / 20)).astype(np.float32)


def _banda(sinal: np.ndarray, baixa: float, alta: float) -> np.ndarray:
    espectro = np.fft.rfft(sinal)
    freqs = np.fft.rfftfreq(len(sinal), 1 / TAXA)
    espectro[(freqs < baixa) | (freqs > alta)] = 0
    return np.fft.irfft(espectro, len(sinal))


def efeito_sonoro(tipo: str, rng: np.random.Generator) -> np.ndarray:
    """Som curto que não é fala, com pico 1: splash de água, estalo de dedo ou whoosh de transição."""
    if tipo == "splash":
        n = int(TAXA * 0.35)
        t = np.arange(n) / TAXA
        corpo = _banda(rng.normal(size=n), 400, 7000) * np.exp(-t / 0.07) * np.minimum(t / 0.004, 1)
        for atraso in rng.uniform(0.04, 0.25, 6):  # gotinhas caindo depois do impacto
            i = int(atraso * TAXA)
            m = min(n - i, int(TAXA * 0.012))
            corpo[i:i + m] += 0.3 * np.sin(2 * np.pi * rng.uniform(900, 2500) * t[:m]) * np.exp(-t[:m] / 0.003)
        sinal = corpo
    elif tipo == "estalo":
        n = int(TAXA * 0.03)
        t = np.arange(n) / TAXA
        sinal = _banda(rng.normal(size=n), 1000, 9000) * np.exp(-t / 0.004)
    elif tipo == "whoosh":
        n = int(TAXA * 0.40)
        t = np.arange(n) / TAXA
        sinal = _banda(rng.normal(size=n), 150, 3500) * np.sin(np.pi * t / t[-1]) ** 2
    else:
        raise ValueError(tipo)
    return (sinal / np.abs(sinal).max()).astype(np.float32)


def respiracao(rng: np.random.Generator) -> np.ndarray:
    """Respiração de 0,4 s antes da fala, com pico 1: chiado largo com um pouco de ressonância."""
    n = int(TAXA * 0.4)
    t = np.arange(n) / TAXA
    sinal = _banda(rng.normal(size=n), 300, 7500) + 0.6 * _banda(rng.normal(size=n), 900, 2200)
    sinal *= np.sin(np.pi * t / t[-1]) ** 1.5
    return (sinal / np.abs(sinal).max()).astype(np.float32)


def musica_de_fundo(n: int, nivel_db: float, rng: np.random.Generator) -> np.ndarray:
    """Música baixinha com o RMS pedido: um acorde por segundo que vai sumindo e uma batida a cada meio segundo."""
    t = np.arange(n) / TAXA
    sinal = np.zeros(n)
    acordes = [(220, 277, 330), (196, 247, 294), (175, 220, 262), (196, 247, 294)]
    for i in range(int(np.ceil(n / TAXA))):
        trecho = slice(i * TAXA, min(n, (i + 1) * TAXA))
        tt = t[trecho] - i
        for nota in acordes[i % len(acordes)]:
            for harmonico, ganho in ((1, 1), (2, 0.4), (3, 0.2)):
                sinal[trecho] += ganho * np.sin(2 * np.pi * nota * harmonico * tt) * np.exp(-tt / 0.6)
    for ini in range(0, n, TAXA // 2):
        m = min(int(TAXA * 0.05), n - ini)
        sinal[ini:ini + m] += 2 * rng.normal(size=m) * np.exp(-np.arange(m) / TAXA / 0.01)
    return (sinal / np.sqrt(np.mean(sinal ** 2)) * 10 ** (nivel_db / 20)).astype(np.float32)


def oscilacao(n: int, desvio_db: float, rng: np.random.Generator) -> np.ndarray:
    """Ganho que sobe e desce ao acaso a cada 0,4 s, como o ambiente de rua, vento ou ar-condicionado."""
    pontos = rng.normal(0, desvio_db, int(n / TAXA / 0.4) + 3)
    return 10 ** (np.interp(np.arange(n) / TAXA / 0.4, np.arange(len(pontos)), pontos) / 20)


@dataclass
class Caso:
    nome: str
    texto: str  # "|" separa trechos ditos com uma pausa entre eles: "Ei|presta atenção"
    voz: str = "pt-br"
    velocidade: int = 170
    antes: float = 0.5  # s de silêncio antes da primeira palavra
    depois: float = 0.6  # s de silêncio depois da última
    pico_fala: float = -6.0  # dBFS
    ruido: float = -45.0  # dBFS (RMS) do som de ambiente
    cor: str = "rosa"
    efeito: str | None = None  # som antes da fala, que tem de ficar no corte
    efeito_db: float = -8.0  # pico do efeito em dBFS
    vao_efeito: float = 0.12  # s entre o fim do efeito e o começo da fala
    corta_fim: bool = False  # a fala termina cortada no meio da palavra, colada no fim do clipe
    pausa: float = 0.35  # s entre os trechos do texto separados por "|"
    variacao: float = 0.0  # dB: o quanto o nível do ambiente oscila
    musica: float | None = None  # dBFS (RMS) de uma música baixinha por baixo de tudo
    respiracao: float | None = None  # pico em dBFS de uma respiração logo antes da fala, que tem de sair do corte
    formato: str = "mp4"
    semente: int = 0


@dataclass
class Montagem:
    audio: np.ndarray
    fala: tuple[float, float]  # referência: começo e fim da fala no clipe, em segundos
    som: tuple[float, float]  # o que tem de ficar no corte: a fala e o efeito que vem antes dela


def montar(caso: Caso) -> Montagem:
    """Respiro, fala e respiro, com o efeito antes da fala e o som de ambiente por baixo de tudo."""
    rng = np.random.default_rng(caso.semente)
    trechos = []
    for trecho in caso.texto.split("|"):  # cada trecho com o mesmo pico, como se dito no mesmo tom
        voz = sintetizar(trecho, caso.voz, caso.velocidade)
        a, b = limites_reais(voz)
        trechos += [np.zeros(int(round(caso.pausa * TAXA)), dtype=np.float32), voz[a:b] / np.abs(voz[a:b]).max()]
    voz = np.concatenate(trechos[1:])
    if caso.corta_fim:  # corta no ponto mais alto do último terço: no meio de uma vogal, como a geração faz
        ultimo_terco = int(len(voz) * 0.7)
        voz = voz[: ultimo_terco + int(np.argmax(np.abs(voz[ultimo_terco:])))]
    voz = voz / np.abs(voz).max() * 10 ** (caso.pico_fala / 20)
    inicio = int(round(caso.antes * TAXA))
    depois = 0 if caso.corta_fim else int(round(caso.depois * TAXA))
    audio = np.zeros(inicio + len(voz) + depois, dtype=np.float32)
    audio[inicio:inicio + len(voz)] += voz
    comeco_do_som = inicio
    if caso.efeito:
        efeito = efeito_sonoro(caso.efeito, rng) * 10 ** (caso.efeito_db / 20)
        ini_efeito = inicio - int(round(caso.vao_efeito * TAXA)) - len(efeito)
        assert ini_efeito >= 0, "efeito não cabe no silêncio antes da fala"
        audio[ini_efeito:ini_efeito + len(efeito)] += efeito
        comeco_do_som = ini_efeito + limites_reais(efeito)[0]
    if caso.respiracao is not None:  # termina 80 ms antes da primeira palavra
        sopro = respiracao(rng) * 10 ** (caso.respiracao / 20)
        ini_sopro = inicio - int(TAXA * 0.08) - len(sopro)
        assert ini_sopro >= 0, "respiração não cabe no silêncio antes da fala"
        audio[ini_sopro:ini_sopro + len(sopro)] += sopro
    ambiente = ruido_ambiente(len(audio), caso.ruido, caso.cor, rng)
    if caso.variacao:
        ambiente *= oscilacao(len(audio), caso.variacao, rng).astype(np.float32)
    audio += ambiente
    if caso.musica is not None:
        audio += musica_de_fundo(len(audio), caso.musica, rng)
    fala = (inicio / TAXA, (inicio + len(voz)) / TAXA)
    return Montagem(audio=audio, fala=fala, som=(comeco_do_som / TAXA, fala[1]))


def codificar(audio: np.ndarray, destino, formato: str = "mp4"):
    """Como o Veo entrega (H.264 + AAC 48 kHz em MP4) ou em WebM (VP9 + Opus)."""
    duracao = len(audio) / TAXA
    if formato == "mp4":
        codecs = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    else:
        codecs = ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "200k",
                  "-c:a", "libopus", "-b:a", "128k"]
    estereo = np.repeat(audio.astype("<f4")[:, None], 2, axis=1)
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-f", "f32le", "-ar", str(TAXA), "-ac", "2", "-i", "-",
                    "-f", "lavfi", "-i", f"testsrc2=s=180x320:r={FPS}", "-map", "1:v", "-map", "0:a",
                    *codecs, "-ar", str(TAXA), "-t", f"{duracao:.3f}", str(destino)],
                   input=estereo.tobytes(), capture_output=True, check=True)
    return destino


@dataclass
class Resultado:
    caso: Caso
    fala: tuple[float, float]  # referência
    som: tuple[float, float]
    detectado: tuple[float, float] | None
    corte: tuple[float, float]
    duracao: float
    avisos: list[str]

    @property
    def sobra_antes(self) -> float:
        """Quanto o corte deixa antes do som (negativo: comeu o começo)."""
        return self.som[0] - self.corte[0]

    @property
    def sobra_depois(self) -> float:
        return self.corte[1] - self.som[1]

    def falhas(self) -> list[str]:
        problemas = []
        if self.sobra_antes < min(self.som[0], MARGEM_ANTES):  # rente ao começo do clipe, basta começar no zero
            problemas.append("comeu o começo" if not self.caso.efeito else "cortou o efeito")
        if self.sobra_depois < min(self.duracao - self.som[1], MARGEM_DEPOIS):
            problemas.append("comeu o fim")
        if self.sobra_antes > SOBRA_ANTES:
            problemas.append("silêncio demais no começo")
        if self.sobra_depois > SOBRA_DEPOIS:
            problemas.append("silêncio demais no fim")
        avisou = "fala_no_inicio" in self.avisos
        if (self.fala[0] <= 0.02 and not avisou) or (self.som[0] >= 0.15 and avisou):
            problemas.append("aviso de começo errado")
        if self.caso.corta_fim != ("fala_no_fim" in self.avisos):
            problemas.append("aviso de fim errado")
        return problemas


def avaliar(caso: Caso, pasta) -> Resultado:
    """Monta e codifica o clipe e aplica a análise e o corte sugerido, como na importação."""
    montagem = montar(caso)
    arquivo = codificar(montagem.audio, pasta / f"{caso.nome}.{caso.formato}", caso.formato)
    return julgar(caso, montagem, analisar(arquivo))


def julgar(caso: Caso, montagem: Montagem, analise) -> Resultado:
    """O corte que a importação sugere a partir da análise, comparado com a referência do clipe montado."""
    info, fala = analise.info, analise.fala
    nome = f"{caso.nome}.{caso.formato}"
    clipe = Midia(id="a" * 12, nome=nome, arquivo=nome, duracao=info.duracao, largura=info.largura, altura=info.altura,
                  fps=info.fps, codec=info.codec, tem_audio=info.tem_audio,
                  fala_inicio=fala[0] if fala else None, fala_fim=fala[1] if fala else None)
    return Resultado(caso=caso, fala=montagem.fala, som=montagem.som, detectado=fala, corte=clipe.corte_sugerido(),
                     duracao=info.duracao, avisos=[a["codigo"] for a in analise.avisos])


# Regras do detector, com tons (rodam mesmo sem o espeak-ng)


def _tons(*partes, ruido: float = 0.002):
    """partes: (segundos, amplitude de um tom de 300 Hz); por baixo de tudo, um chiado de fundo."""
    sinal = np.concatenate([a * np.sin(2 * np.pi * 300 * np.arange(int(s * TAXA_ANALISE)) / TAXA_ANALISE)
                            for s, a in partes])
    return (sinal + np.random.default_rng(1).normal(0, ruido, len(sinal))).astype(np.float32)


def test_estalo_colado_na_fala_fica_no_corte():
    inicio, fim = detectar_fala(_tons((0.3, 0), (0.02, 0.5), (0.15, 0), (1.0, 0.3), (0.5, 0)))
    assert inicio == pytest.approx(0.3, abs=0.02) and fim == pytest.approx(1.47, abs=0.03)


def test_palavra_solta_num_clipe_barulhento_fica_no_corte():
    # Fala baixa sobre ambiente alto: a primeira palavra, no nível da fala mas sem chegar a 10 dB acima do ruído,
    # vem antes de uma vírgula de meio segundo. Não tem prova de fala, mas é palavra e não pode sair do corte.
    inicio, fim = detectar_fala(_tons((0.4, 0), (0.25, 0.002), (0.5, 0), (1.5, 0.006), (0.5, 0)))
    assert inicio == pytest.approx(0.4, abs=0.03) and fim == pytest.approx(2.65, abs=0.03)


def test_ambiente_que_aumenta_nao_vira_fala():
    # O ambiente sobe 6 dB por meio segundo antes da fala, por igual em todas as frequências, como um carro
    # passando: é ruído, e o corte não pode começar nele.
    audio = _tons((1.2, 0), (1.5, 0.02), (0.5, 0))
    trecho = slice(int(0.3 * TAXA_ANALISE), int(0.8 * TAXA_ANALISE))
    n = trecho.stop - trecho.start
    subida = np.random.default_rng(7).normal(0, 0.002 * np.sqrt(10 ** 0.6 - 1), n) * np.sin(np.linspace(0, np.pi, n))
    audio[trecho] += subida.astype(np.float32)
    inicio, fim = detectar_fala(audio)
    assert inicio == pytest.approx(1.2, abs=0.03) and fim == pytest.approx(2.7, abs=0.03)


def test_som_inaudivel_no_silencio_digital_nao_puxa_o_corte():
    audio = _tons((0.8, 0), (1.2, 0.3), (0.5, 0), ruido=0)
    for segundo in (0.3, 0.5, 0.65):
        i = int(segundo * TAXA_ANALISE)
        audio[i:i + 32] += 1e-4
    inicio, _ = detectar_fala(audio)
    assert inicio == pytest.approx(0.8, abs=0.02)


def test_aviso_de_palavra_cortada_so_com_a_voz_na_borda():
    info = InfoVideo(duracao=4.0, largura=720, altura=1280, fps=24, codec="h264", tem_audio=True)
    onda = {"picos": [1.0]}
    # Trilha ou ambiente encostado nas bordas e a voz só bem depois: não é palavra cortada.
    assert avisos_do_clipe(info, (0.0, 4.0), onda, voz=(0.6, 3.4)) == []
    codigos = [a["codigo"] for a in avisos_do_clipe(info, (0.0, 4.0), onda, voz=(0.1, 3.9))]
    assert codigos == ["fala_no_inicio", "fala_no_fim"]


def test_so_som_de_ambiente_nao_vira_fala(tmp_path):
    rng = np.random.default_rng(5)
    for cor, nivel in (("rosa", -45.0), ("marrom", -38.0), ("branco", -55.0)):
        analise = analisar(codificar(ruido_ambiente(TAXA * 4, nivel, cor, rng), tmp_path / f"{cor}.mp4"))
        assert analise.fala is None and [a["codigo"] for a in analise.avisos] == ["sem_fala"], cor


# Clipes com fala sintetizada, como os do Veo

CASOS = [
    # Começo com fricativa e fim fraco, em ambientes e volumes diferentes.
    Caso("sabe", "Sabe o que acontece quando você toma bicarbonato todo dia? Pouca gente sabe disso.",
         velocidade=130, antes=0.6, depois=0.3, pico_fala=-10, ruido=-38, cor="rosa", semente=1),
    Caso("show", "Show de bola, agora presta atenção no que vem depois.", voz="pt-br+m3", velocidade=150,
         antes=0.25, depois=1.5, pico_fala=-25, ruido=-45, cor="marrom", formato="webm", semente=2),
    Caso("fica-sodio", "Fica até o final que eu te conto o segredo do sódio.", voz="pt-br+f3", velocidade=190,
         antes=0.6, depois=0.5, pico_fala=-20, ruido=-38, cor="marrom", semente=3),
    Caso("anything-else", "Every single morning I drink this before anything else.", voz="en-us+m4",
         velocidade=130, antes=0.15, depois=0.8, pico_fala=-15, ruido=-38, cor="rosa", semente=4),
    Caso("around", "Have you ever wondered why your belly keeps growing around.", voz="en-us", velocidade=150,
         antes=0.8, depois=0.4, pico_fala=-3, ruido=-45, cor="branco", formato="webm", semente=5),
    # Começo nasal, baixinho, com a primeira palavra separada por vírgula.
    Caso("meninas", "Meninas, prestem atenção nessa dica que ninguém conta pra vocês.", voz="pt-br+m7",
         velocidade=130, antes=0.4, depois=0.5, pico_fala=-25, ruido=-45, cor="rosa", semente=6),
    Caso("nao-se-pesa", "Não se pesa hoje, espera mais uns dias e me conta depois.", voz="pt-br+m3",
         velocidade=190, antes=0.4, depois=0.3, pico_fala=-20, ruido=-45, cor="marrom", formato="webm", semente=7),
    # Efeito sonoro antes da fala: tem de ficar no corte.
    Caso("efeito-estalo", "Comenta aqui embaixo se você também sente isso.", voz="pt-br+m3", antes=0.8,
         efeito="estalo", vao_efeito=0.25, efeito_db=-10, ruido=-38, semente=8),
    Caso("efeito-splash", "Aprendi isso com a minha avó e nunca mais parei.", voz="pt-br+f3", antes=0.9,
         efeito="splash", vao_efeito=0.15, ruido=-45, formato="webm", semente=9),
    Caso("efeito-whoosh", "Kids love this recipe and it only takes five minutes.", voz="en-us", antes=0.9,
         efeito="whoosh", vao_efeito=0.05, efeito_db=-10, ruido=-38, formato="webm", semente=10),
    # Palavra cortada na geração: fala colada no primeiro quadro ou no último.
    Caso("quadro-zero", "So my man here thinks he can lose weight without changing anything, yes.", voz="en",
         antes=0.0, depois=0.6, ruido=-45, formato="webm", semente=11),
    Caso("cortada-no-fim", "Tem gente que ainda não sabe o perigo do excesso de sódio.", antes=0.5, corta_fim=True,
         ruido=-45, semente=12),
    # Fala baixa sobre ambiente alto, com uma palavra curta separada do resto por uma vírgula longa.
    Caso("ei-pausa", "Ei|presta atenção nisso aqui.", antes=0.6, pico_fala=-20, ruido=-38, semente=1),
    Caso("please", "Do this every single morning, please.", voz="en-us", pico_fala=-20, ruido=-38,
         formato="webm", semente=13),
    # Fundo que não é fala e tem de sair do corte.
    Caso("ambiente-oscila", "Tem gente que ainda não sabe o perigo do excesso de sódio.", antes=0.6, depois=0.8,
         ruido=-42, variacao=2.0, formato="webm", semente=5),
    Caso("musica-baixa", "Comenta aqui embaixo se você também sente isso.", voz="pt-br+m3", antes=0.8,
         depois=0.5, pico_fala=-10, ruido=-45, musica=-40, semente=14),
    Caso("respiracao", "Olha só o que aconteceu comigo essa semana.", antes=0.8, respiracao=-35, semente=15),
]


@sem_espeak
@pytest.mark.parametrize("caso", CASOS, ids=lambda caso: caso.nome)
def test_corte_nao_come_fala_nem_deixa_silencio(caso, tmp_path):
    r = avaliar(caso, tmp_path)
    assert r.falhas() == [], (f"som de {r.som[0]:.2f} a {r.som[1]:.2f} s, detectado {r.detectado}, corte "
                              f"{r.corte}, avisos {r.avisos}")


# Fala quase no nível do ruído, com palavra separada por vírgula. O corte pode deixar o clipe inteiro, mas nunca pode
# comer palavra. Aqui só isso é exigido, sem a margem: o "s" fraco do começo fica abaixo do ruído.
CASOS_RUIDOSOS = [
    Caso("ei-pausa-baixo", "Ei|presta atenção nisso aqui.", antes=0.5, pico_fala=-25, ruido=-45, semente=16),
    Caso("ta-no-fim", "Faz isso todo dia de manhã|tá?", pausa=0.5, pico_fala=-20, ruido=-38, semente=17),
    Caso("hey-pausa", "Hey|look at this right now.", voz="en-us", antes=0.6, pausa=0.5, pico_fala=-24, ruido=-38,
         formato="webm", semente=18),
    Caso("have-you", "Have you ever wondered why your belly keeps growing?", voz="en-us+f2", velocidade=130,
         antes=0.8, depois=0.4, pico_fala=-25, ruido=-38, semente=19),
]


@sem_espeak
@pytest.mark.parametrize("caso", CASOS_RUIDOSOS, ids=lambda caso: caso.nome)
def test_fala_quase_no_ruido_nunca_e_comida(caso, tmp_path):
    r = avaliar(caso, tmp_path)
    assert r.sobra_antes >= 0 and r.sobra_depois >= 0, (f"som de {r.som[0]:.2f} a {r.som[1]:.2f} s, detectado "
                                                         f"{r.detectado}, corte {r.corte}")


# Bancada: clipes sorteados com tudo o que já deu problema. Rode antes e depois de mexer no detector e compare.

FRASES_BANCADA = [
    ("pt", "Sabe o que acontece quando você toma isso todo dia?"),
    ("pt", "Fiz esse teste em casa e o resultado me surpreendeu demais."),
    ("pt", "Show, agora presta atenção no que vem depois."),
    ("pt", "Para de jogar dinheiro fora com remédio caro e olha aqui."),
    ("pt", "Meninas, prestem atenção nessa dica que ninguém conta."),
    ("pt", "Não se pesa hoje, espera mais uns dias e me conta depois."),
    ("pt", "Ei|presta atenção nisso aqui."),
    ("pt", "Faz isso todo dia de manhã,|tá?"),
    ("en", "So my man here thinks he can lose weight without changing anything, yes."),
    ("en", "Have you ever wondered why your belly keeps growing around."),
    ("en", "Honestly I didn't believe it either, but it works."),
    ("en", "Do this every single morning, please."),
    ("en", "Hey|look at this right now."),
]
VOZES_BANCADA = {"pt": ["pt-br", "pt-br+f3", "pt-br+m3", "pt-br+f5", "pt-br+m7"],
                 "en": ["en-us", "en", "en-us+f2", "en-us+m4"]}


def sortear(i: int, rng: np.random.Generator) -> Caso:
    """Um clipe como os do Veo, com voz, volumes, ambiente e um extra (efeito, música...) sorteados."""
    lingua, texto = FRASES_BANCADA[rng.integers(len(FRASES_BANCADA))]
    ruido = float(rng.choice([-55, -45, -38]))
    caso = Caso(nome=f"b{i:03d}", texto=texto, voz=str(rng.choice(VOZES_BANCADA[lingua])),
                velocidade=int(rng.choice([130, 150, 170, 190, 210])),
                antes=float(rng.choice([0.0, 0.15, 0.3, 0.5, 0.8, 1.0])),
                depois=float(rng.choice([0.2, 0.5, 0.8, 1.5])),
                pico_fala=float(rng.choice([p for p in (-3, -6, -10, -15, -20, -25) if p - ruido >= 13])), ruido=ruido,
                cor=str(rng.choice(["branco", "rosa", "marrom"])), formato=str(rng.choice(["mp4", "webm"])),
                semente=int(rng.integers(1 << 30)))
    extra = rng.choice(["nenhum", "nenhum", "nenhum", "efeito", "oscila", "musica", "respiracao"])
    if extra == "efeito":
        caso.antes, caso.efeito = 1.0, str(rng.choice(["splash", "estalo", "whoosh"]))
        caso.efeito_db, caso.vao_efeito = float(rng.choice([-4, -8, -12, -16])), float(rng.choice([0.05, 0.15, 0.25]))
    elif extra == "oscila":
        caso.variacao = float(rng.choice([1.0, 2.0, 3.0]))
    elif extra == "musica":
        caso.musica = caso.pico_fala - float(rng.choice([30, 34, 38]))
    elif extra == "respiracao":
        caso.antes, caso.respiracao = max(caso.antes, 0.6), caso.pico_fala - float(rng.choice([29, 34]))
    return caso


@lru_cache
def midia_do_commit(commit: str) -> types.ModuleType:
    """O estudio/midia.py de outro commit, carregado à parte, para comparar com o atual."""
    fonte = subprocess.run(["git", "show", f"{commit}:estudio/midia.py"], capture_output=True, text=True, check=True,
                           cwd=Path(__file__).parent).stdout
    modulo = types.ModuleType(f"midia_{commit}")
    sys.modules[modulo.__name__] = modulo  # as dataclasses procuram o módulo aqui
    exec(compile(fonte, f"estudio/midia.py@{commit}", "exec"), modulo.__dict__)
    return modulo


def _avaliar_versoes(caso: Caso, commit: str | None) -> list[Resultado]:
    """O mesmo clipe analisado pelo detector atual e, se pedido, pelo de outro commit."""
    versoes = [midia] + ([midia_do_commit(commit)] if commit else [])
    montagem = montar(caso)
    with tempfile.TemporaryDirectory() as pasta:
        arquivo = codificar(montagem.audio, Path(pasta) / f"{caso.nome}.{caso.formato}", caso.formato)
        return [julgar(caso, montagem, versao.analisar(arquivo)) for versao in versoes]


def _resumo(resultados: list[Resultado]) -> str:
    falhas = [r.falhas() for r in resultados]
    return (f"{sum(not f for f in falhas)}/{len(falhas)} ok; comeu fala ou efeito em "
            f"{sum(any('comeu' in x or 'cortou' in x for x in f) for f in falhas)}; silêncio demais em "
            f"{sum(any('silêncio' in x for x in f) for f in falhas)}; aviso errado em "
            f"{sum(any('aviso' in x for x in f) for f in falhas)}")


def bancada(quantidade: int = 60, semente: int = 2026, commit: str | None = None):
    """Avalia clipes sorteados e mostra uma tabela em Markdown (antes e depois, se houver commit) e o resumo."""
    rng = np.random.default_rng(semente)
    casos = [sortear(i, rng) for i in range(quantidade)]
    with ProcessPoolExecutor() as executor:
        resultados = list(executor.map(_avaliar_versoes, casos, [commit] * len(casos)))
    versoes = ["atual"] + ([commit] if commit else [])  # na ordem dos resultados de cada caso
    print("| caso | frase | voz/vel | fala/ambiente | extra | som | "
          + " | ".join(f"corte ({v}) | resultado ({v})" for v in reversed(versoes)) + " |")
    print("|---" * (6 + 2 * len(versoes)) + "|")
    for por_versao in resultados:
        r = por_versao[0]
        c = r.caso
        extra = (c.efeito or (f"oscila {c.variacao:g} dB" if c.variacao else "")
                 or (f"música {c.musica:g}" if c.musica is not None else "")
                 or (f"respiração {c.respiracao:g}" if c.respiracao is not None else "") or "—")
        colunas = [f"{v.corte[0]:.2f}–{v.corte[1]:.2f} | {', '.join(v.falhas()) or 'ok'}" for v in reversed(por_versao)]
        print(f"| {c.nome} | {c.texto.replace('|', ' ')[:28]}… | {c.voz}/{c.velocidade} | {c.pico_fala:g}/{c.ruido:g} "
              f"{c.cor} {c.formato} | {extra} | {r.som[0]:.2f}–{r.som[1]:.2f} | {' | '.join(colunas)} |")
    print()
    for i in reversed(range(len(versoes))):
        print(f"{versoes[i]}: {_resumo([por_versao[i] for por_versao in resultados])}")


if __name__ == "__main__":
    argumentos = sys.argv[1:]
    bancada(*(int(x) for x in argumentos[:2]), *argumentos[2:3])
