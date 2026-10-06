"""Corte automático do silêncio com fala de verdade: frases sintetizadas pelo espeak-ng, montadas como os clipes do
Veo (respiro antes e depois, som de ambiente por baixo, às vezes um efeito antes da fala) e codificadas em MP4 e WebM.

A referência do começo e do fim da fala é medida no sinal limpo da síntese, antes de misturar o ruído. O corte
sugerido nunca pode comer fala e também não pode deixar silêncio demais, que no Reels faz a pessoa rolar o feed."""

import shutil
import subprocess
from dataclasses import dataclass

import numpy as np
import pytest

from estudio.midia import TAXA_ANALISE, analisar, detectar_fala, ffmpeg
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


@dataclass
class Caso:
    nome: str
    texto: str
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
    voz = sintetizar(caso.texto, caso.voz, caso.velocidade)
    a, b = limites_reais(voz)
    voz = voz[a:b]
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
    audio += ruido_ambiente(len(audio), caso.ruido, caso.cor, rng)
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
    analise = analisar(arquivo)
    info = analise.info
    midia = Midia(id="a" * 12, nome=arquivo.name, arquivo=arquivo.name, duracao=info.duracao, largura=info.largura,
                  altura=info.altura, fps=info.fps, codec=info.codec, tem_audio=info.tem_audio,
                  fala_inicio=analise.fala[0] if analise.fala else None,
                  fala_fim=analise.fala[1] if analise.fala else None)
    return Resultado(caso=caso, fala=montagem.fala, som=montagem.som, detectado=analise.fala,
                     corte=midia.corte_sugerido(), duracao=info.duracao, avisos=[a["codigo"] for a in analise.avisos])


# Regras do detector, com tons (rodam mesmo sem o espeak-ng)


def _tons(*partes, ruido: float = 0.002):
    """partes: (segundos, amplitude de um tom de 300 Hz); por baixo de tudo, um chiado de fundo."""
    sinal = np.concatenate([a * np.sin(2 * np.pi * 300 * np.arange(int(s * TAXA_ANALISE)) / TAXA_ANALISE)
                            for s, a in partes])
    return (sinal + np.random.default_rng(1).normal(0, ruido, len(sinal))).astype(np.float32)


def test_estalo_colado_na_fala_fica_no_corte():
    inicio, fim = detectar_fala(_tons((0.3, 0), (0.02, 0.5), (0.15, 0), (1.0, 0.3), (0.5, 0)))
    assert inicio == pytest.approx(0.3, abs=0.02) and fim == pytest.approx(1.47, abs=0.03)


def test_palavra_fraca_antes_de_uma_pausa_longa_fica_no_corte():
    # A primeira palavra sai baixinha (uns 8 dB acima do ruído) e vem uma vírgula de meio segundo.
    inicio, fim = detectar_fala(_tons((0.4, 0), (0.35, 0.004), (0.5, 0), (1.0, 0.3), (0.5, 0)))
    assert inicio == pytest.approx(0.4, abs=0.03) and fim == pytest.approx(2.25, abs=0.03)


def test_som_inaudivel_no_silencio_digital_nao_puxa_o_corte():
    audio = _tons((0.8, 0), (1.2, 0.3), (0.5, 0), ruido=0)
    for segundo in (0.3, 0.5, 0.65):
        i = int(segundo * TAXA_ANALISE)
        audio[i:i + 32] += 1e-4
    inicio, _ = detectar_fala(audio)
    assert inicio == pytest.approx(0.8, abs=0.02)


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
]


@sem_espeak
@pytest.mark.parametrize("caso", CASOS, ids=lambda caso: caso.nome)
def test_corte_nao_come_fala_nem_deixa_silencio(caso, tmp_path):
    r = avaliar(caso, tmp_path)
    assert r.falhas() == [], (f"som de {r.som[0]:.2f} a {r.som[1]:.2f} s, detectado {r.detectado}, corte "
                              f"{r.corte}, avisos {r.avisos}")
