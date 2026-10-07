"""Exportação: transforma a linha do tempo num MP4 pronto para postar.

Cada trecho é renderizado separado, já no tamanho, na taxa de quadros e no volume finais, com o áudio sem
compressão. Depois os trechos são emendados sem recodificar o vídeo, e o áudio é comprimido uma vez só. Assim
não há estalo nem atraso de áudio nas emendas, os trechos que não mudaram são reaproveitados na próxima
exportação e a memória não cresce com o número de clipes.
"""

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config, legendas
from .midia import ERRO_AO_RODAR, SEM_JANELA, Cor, ErroMidia, ffmpeg, filtros, medir_volume, sondar
from .projetos import Estudio, Item, Projeto, novo_id

PASTA_FONTES = Path(__file__).parent / "static" / "fontes"

VERSAO_RENDER = 3  # mude quando a receita dos trechos mudar, para não reaproveitar trechos antigos
FADE_EMENDA = 0.012  # s de fade em cada ponta do áudio, para a emenda não estalar
LER_DO_COMECO = 2.0  # s: trecho com a entrada antes disto é lido desde o começo do arquivo (ver comando_trecho)

# Taxas de quadros padrão. O vídeo final usa a que mais aparece entre os clipes.
TAXAS = [(24000 / 1001, "24000/1001"), (24.0, "24"), (25.0, "25"), (30000 / 1001, "30000/1001"), (30.0, "30"),
         (50.0, "50"), (60000 / 1001, "60000/1001"), (60.0, "60")]


class ErroExportacao(Exception):
    pass


class Cancelada(Exception):
    pass


@dataclass
class Trecho:
    arquivo: Path
    entrada: float
    duracao: float
    tem_audio: bool
    ganho_db: float = 0.0
    legenda: str | None = None  # o .ass das legendas deste trecho, se houver
    faixa_audio: int = 0  # qual faixa de áudio do arquivo usar (0:a:N)
    cor: Cor = field(default_factory=Cor)


def escolher_fps(usos: list[tuple[float, float]]) -> tuple[str, float]:
    """usos: (fps da mídia, segundos dela no vídeo). Vence a taxa padrão com mais tempo de tela."""
    peso: dict[str, float] = {}
    valores = {}
    for fps, segundos in usos:
        if fps <= 0:
            continue
        valor, nome = min(TAXAS, key=lambda t: abs(t[0] - fps))
        peso[nome] = peso.get(nome, 0) + segundos
        valores[nome] = valor
    if not peso:
        return "30", 30.0
    nome = max(peso, key=peso.get)
    return nome, valores[nome]


def contar_quadros(duracao: float, fps: float) -> int:
    return max(1, round(duracao * fps))


def calcular_ganho(medida: tuple[float, float] | None) -> float:
    """Quanto subir ou baixar o trecho para chegar no volume das redes, sem passar do teto de pico."""
    if medida is None:
        return 0.0
    integrado, pico = medida
    ganho = min(config.VOLUME_ALVO - integrado, config.PICO_MAXIMO - pico)
    return round(max(-20.0, min(20.0, ganho)), 2)


def _par(valor: int) -> int:
    return max(2, valor - valor % 2)


def tem_tone_mapping() -> bool:
    """O ffmpeg do imageio no Windows pode vir sem a zimg: sem o zscale, não há como converter HDR direito."""
    return {"zscale", "tonemap"} <= filtros()


def filtro_cor(cor: Cor) -> str:
    """Leva o vídeo para BT.709 SDR em faixa limitada, o padrão das redes. Todo trecho precisa sair igual: a emenda
    sem recodificar declara as cores do primeiro trecho para o vídeo inteiro."""
    if cor.hdr:
        if tem_tone_mapping():
            # Há HDR com só a transferência marcada: sem a matriz ou as primárias, o zscale não tem de onde converter
            # ("no path between colorspaces") e a exportação inteira falha. O que falta vale BT.2020, o do HDR.
            faltando = [p for p, falta in (("color_primaries=bt2020", not cor.primarias),
                                           ("colorspace=bt2020nc", not cor.matriz)) if falta]
            marcar = f"setparams={':'.join(faltando)}," if faltando else ""
            # O branco de referência do HDR (203 nits, BT.2408) vira o branco do SDR: o mobius mantém o que fica
            # abaixo dele (pele, roupa, parede) e só comprime os brilhos acima, sem escurecer o vídeo todo.
            return (f"{marcar}zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:desat=0,"
                    "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")
        # Sem eles, ao menos a matriz e a faixa ficam certas (as cores ficam um pouco lavadas).
        return "scale=in_color_matrix=bt2020:out_color_matrix=bt709:out_range=tv,"
    if cor.matriz in ("", "bt709") and cor.faixa != "pc":
        return ""  # já é BT.709; sem marcação, é tratado como BT.709, como fazem os players
    # Vídeo sem a matriz marcada é lido como BT.709 (o scale, sozinho, o leria como BT.601).
    return f"scale=in_color_matrix={'auto' if cor.matriz else 'bt709'}:out_color_matrix=bt709:out_range=tv,"


def filtro_video(largura: int, altura: int, fps: str, quadros: int, enquadramento: str,
                 legenda: str | None = None, cor: Cor | None = None, corte: float = 0.0) -> str:
    """legenda: caminho do .ass relativo à pasta onde o ffmpeg roda (a de cache do projeto). corte: segundos do
    começo do que foi lido que ficam fora do trecho (a entrada, quando o arquivo é lido desde o começo)."""
    if enquadramento == "desfocado":
        # Fundo: o próprio vídeo ampliado e desfocado (reduzido antes, para o desfoque sair barato).
        pl, pa = _par(largura // 8), _par(altura // 8)
        corpo = (f"split=2[fundo][frente];"
                 f"[fundo]scale={pl}:{pa}:force_original_aspect_ratio=increase,crop={pl}:{pa},gblur=sigma=4,"
                 f"scale={largura}:{altura},eq=brightness=-0.06[fundo2];"
                 f"[frente]scale={largura}:{altura}:force_original_aspect_ratio=decrease:force_divisible_by=2"
                 f":flags=lanczos[frente2];[fundo2][frente2]overlay=(W-w)/2:(H-h)/2,")
    else:
        corpo = (f"scale={largura}:{altura}:force_original_aspect_ratio=increase:flags=lanczos,"
                 f"crop={largura}:{altura},")
    # Sem setpts=PTS-STARTPTS: o -ss (ou o corte, que desconta a mesma constante dos dois) já deixa a linha do tempo
    # do arquivo começando em 0 na entrada, igual para o vídeo e o áudio. Zerar cada um pelo seu primeiro quadro
    # perderia o desencontro entre eles (áudio que começa depois do vídeo) e adiantaria o vídeo em até um quadro
    # quando a entrada cai entre dois quadros. O fps com start_time=0 repete o primeiro quadro se o vídeo começar um
    # pouco depois do 0.
    # tpad + trim garantem exatamente `quadros` quadros, mesmo que o clipe acabe um quadro antes. Nada de setpts
    # depois do fps: ele apaga a taxa de quadros e o ffmpeg cai nos 25 quadros/s padrão, descartando quadros.
    # A legenda entra por último, já no tamanho final. Caminhos relativos e simples: no Windows, o C:\ de um
    # caminho completo quebraria o filtro.
    texto = f",ass=filename={legenda}:fontsdir=fontes" if legenda else ""
    inicio = f"trim=start={corte:.6f},setpts=PTS-{corte:.6f}/TB," if corte else ""
    return (f"[0:v]{inicio}{filtro_cor(cor or Cor())}{corpo}setsar=1,fps={fps}:start_time=0,"
            f"setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709,format=yuv420p,"
            f"tpad=stop_mode=clone:stop_duration=1,trim=end_frame={quadros}{texto}[v]")


def filtro_audio(indice: int, duracao: float, ganho_db: float, faixa: int = 0, corte: float = 0.0) -> str:
    # O aresample com first_pts=0 completa com silêncio o começo, se o áudio começar depois do vídeo.
    inicio = f"atrim=start={corte:.6f},asetpts=PTS-{corte:.6f}/TB," if corte else ""
    return (f"[{indice}:a:{faixa}]{inicio}aresample=48000:async=1:first_pts=0,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"volume={ganho_db:.2f}dB,apad,atrim=end={duracao:.6f},"
            f"afade=t=in:d={FADE_EMENDA},afade=t=out:st={max(0.0, duracao - FADE_EMENDA):.6f}:d={FADE_EMENDA}[a]")


def comando_trecho(trecho: Trecho, largura: int, altura: int, fps: str, fps_valor: float, enquadramento: str,
                   saida: Path, legenda: str | None = None) -> list[str]:
    quadros = contar_quadros(trecho.duracao, fps_valor)
    duracao = quadros / fps_valor
    # O -ss põe todos os streams no quadro-chave do vídeo: se a entrada cai antes do primeiro quadro do vídeo (MP4 em
    # que o vídeo entra depois do áudio), o som de antes dele nunca é lido e o trecho começa mudo, cortando a primeira
    # sílaba. Perto do começo, o arquivo é lido desde o início, sem -ss nenhum (até o -ss 0 busca), e cortado nos
    # filtros; mais adiante, o -ss evita decodificar o vídeo todo até a entrada.
    if trecho.entrada < LER_DO_COMECO:
        busca, corte = [], trecho.entrada
    else:
        busca, corte = ["-ss", f"{trecho.entrada:.3f}"], 0.0
    leitura = f"{corte + duracao + 0.5:.3f}"  # lê um pouco a mais; o corte exato é feito pelos filtros
    args = ["-y", *busca, "-t", leitura, "-i", str(trecho.arquivo)]
    indice_audio = 0
    if not trecho.tem_audio:
        args += ["-f", "lavfi", "-t", leitura, "-i", "anullsrc=r=48000:cl=stereo"]
        indice_audio = 1
    grafo = (filtro_video(largura, altura, fps, quadros, enquadramento, legenda, trecho.cor, corte) + ";"
             + filtro_audio(indice_audio, duracao, trecho.ganho_db if trecho.tem_audio else 0.0,
                            trecho.faixa_audio if trecho.tem_audio else 0, corte if trecho.tem_audio else 0.0))
    return args + [
        "-filter_complex", grafo, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
        "-g", str(max(1, round(fps_valor * 2))),
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-f", "mov", str(saida),
    ]


def comando_juntar(lista: Path, saida: Path) -> list[str]:
    return ["-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-map", "0:v:0", "-map", "0:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-f", "mp4", str(saida)]


def legenda_do_item(projeto: Projeto, item: Item, largura: int, altura: int) -> str | None:
    """O .ass das legendas de um trecho da linha do tempo, ou None se ele fica sem legenda."""
    palavras = projeto.legendas.get(item.midia_id) if projeto.legendas_ativas else None
    if not palavras:
        return None
    estilo = projeto.estilo_legenda.model_dump()
    telas = legendas.legendas_do_trecho([p.model_dump() for p in palavras], item.entrada, item.saida, estilo,
                                        largura, altura)
    return legendas.gerar_ass(telas, estilo, largura, altura) if telas else None


def preparar_legenda(cache: Path, texto: str) -> str:
    """Grava o .ass e as fontes dentro da pasta de cache. Devolve o caminho do .ass relativo a ela."""
    fontes = cache / "fontes"
    fontes.mkdir(parents=True, exist_ok=True)
    for fonte in legendas.FONTES.values():
        origem, copia = PASTA_FONTES / fonte["arquivo"], fontes / fonte["arquivo"]
        if not copia.exists() or copia.stat().st_size != origem.stat().st_size:
            shutil.copyfile(origem, copia)
    pasta = cache / "legendas"
    pasta.mkdir(exist_ok=True)
    nome = hashlib.sha1(texto.encode()).hexdigest()[:20] + ".ass"
    (pasta / nome).write_text(texto, encoding="utf-8")
    return f"legendas/{nome}"


def trocar(origem: Path, destino: Path, tentativas: int = 20, espera: float = 0.25) -> None:
    """Troca atômica com novas tentativas: no Windows, o antivírus, o indexador ou o OneDrive às vezes abrem o
    arquivo que o ffmpeg acabou de fechar, e a troca falha por alguns instantes."""
    for n in range(tentativas):
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if n == tentativas - 1:
                raise
            time.sleep(espera)


def apagar(arquivo: Path) -> None:
    """Apaga se der. No Windows, um arquivo aberto por outro programa não pode ser apagado; fica para depois."""
    try:
        arquivo.unlink(missing_ok=True)
    except OSError:
        pass


def linha_da_lista(caminho: Path) -> str:
    return "file '" + caminho.resolve().as_posix().replace("'", "'\\''") + "'"


def nome_do_arquivo(nome_projeto: str, pasta: Path, momento: datetime | None = None) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome_projeto)
    base = " ".join(base.split()).strip(" .")[:60] or "reels"
    carimbo = (momento or datetime.now()).strftime("%Y-%m-%d %Hh%M")
    nome = f"{base} {carimbo}.mp4"
    n = 2
    while (pasta / nome).exists():
        nome = f"{base} {carimbo} ({n}).mp4"
        n += 1
    return nome


@dataclass
class Exportacao:
    id: str
    projeto_id: str
    estado: str = "preparando"  # preparando, renderizando, pronta, erro, cancelada
    progresso: float = 0.0
    etapa: str = "Preparando…"
    arquivo: str | None = None
    erro: str | None = None
    _cancelar: threading.Event = field(default_factory=threading.Event, repr=False)
    _processo: subprocess.Popen | None = field(default=None, repr=False)

    def como_dict(self) -> dict:
        return {"id": self.id, "projeto_id": self.projeto_id, "estado": self.estado,
                "progresso": round(self.progresso, 4), "etapa": self.etapa, "arquivo": self.arquivo,
                "erro": self.erro}


class Exportador:
    def __init__(self, estudio: Estudio):
        self.estudio = estudio
        self._exportacoes: dict[str, Exportacao] = {}
        self._trava = threading.Lock()

    def obter(self, exportacao_id: str) -> Exportacao | None:
        return self._exportacoes.get(exportacao_id)

    def iniciar(self, projeto_id: str, sincrono: bool = False) -> Exportacao:
        projeto = self.estudio.abrir(projeto_id)
        if not projeto.linha:
            raise ErroExportacao("Coloque pelo menos um clipe na linha do tempo antes de exportar.")
        with self._trava:
            for outra in self._exportacoes.values():
                if outra.projeto_id == projeto_id and outra.estado in ("preparando", "renderizando"):
                    return outra  # já está exportando este projeto
            exportacao = Exportacao(id=novo_id(), projeto_id=projeto_id)
            self._exportacoes[exportacao.id] = exportacao
        if sincrono:
            self._rodar(exportacao, projeto)
        else:
            threading.Thread(target=self._rodar, args=(exportacao, projeto), daemon=True).start()
        return exportacao

    def cancelar(self, exportacao_id: str) -> Exportacao | None:
        exportacao = self.obter(exportacao_id)
        if exportacao:
            exportacao._cancelar.set()
            if exportacao._processo and exportacao._processo.poll() is None:
                exportacao._processo.terminate()
        return exportacao

    # Execução

    def _rodar(self, exp: Exportacao, projeto: Projeto) -> None:
        try:
            exp.arquivo = self._exportar(exp, projeto)
            exp.estado, exp.progresso, exp.etapa = "pronta", 1.0, "Pronto!"
        except Cancelada:
            exp.estado, exp.etapa = "cancelada", "Exportação cancelada."
        except Exception as erro:  # a tela precisa saber de qualquer falha, não só das previstas
            exp.estado, exp.erro = "erro", str(erro) or erro.__class__.__name__
            exp.etapa = "A exportação falhou."

    def _verificar(self, exp: Exportacao) -> None:
        if exp._cancelar.is_set():
            raise Cancelada()

    def _exportar(self, exp: Exportacao, projeto: Projeto) -> str:
        largura, altura, _ = config.FORMATOS[projeto.formato]
        cache = self.estudio.pasta_cache(projeto.id).resolve()  # o ffmpeg dos trechos roda nesta pasta
        trechos = []
        infos = {}
        for item in projeto.linha:
            midia = projeto.midia(item.midia_id)
            arquivo = self.estudio.arquivo_midia(projeto.id, midia).resolve()
            if midia.id not in infos:  # as cores e a faixa de áudio vêm do arquivo: valem para projetos antigos
                try:
                    infos[midia.id] = sondar(arquivo)
                except ErroMidia as erro:
                    raise ErroExportacao(f"“{midia.nome}”: {erro}") from erro
            info = infos[midia.id]
            trechos.append((midia, Trecho(arquivo=arquivo, entrada=item.entrada, duracao=item.saida - item.entrada,
                                          tem_audio=midia.tem_audio and info.tem_audio,
                                          legenda=legenda_do_item(projeto, item, largura, altura),
                                          faixa_audio=info.faixa_audio, cor=info.cor)))
        fps, fps_valor = escolher_fps([(m.fps, t.duracao) for m, t in trechos])

        if projeto.igualar_volume:
            for n, (_, trecho) in enumerate(trechos, 1):
                self._verificar(exp)
                exp.etapa = f"Medindo o volume do clipe {n} de {len(trechos)}…"
                if trecho.tem_audio:
                    trecho.ganho_db = calcular_ganho(medir_volume(trecho.arquivo, trecho.entrada, trecho.duracao,
                                                                  trecho.faixa_audio))
                exp.progresso = 0.1 * n / len(trechos)

        exp.estado = "renderizando"
        pasta_trechos = cache / "trechos"
        pasta_trechos.mkdir(parents=True, exist_ok=True)
        total = sum(contar_quadros(t.duracao, fps_valor) for _, t in trechos) / fps_valor
        feito = 0.0
        prontos = []
        for n, (midia, trecho) in enumerate(trechos, 1):
            self._verificar(exp)
            exp.etapa = f"Montando o clipe {n} de {len(trechos)}…"
            arquivo = trecho.arquivo
            partes = [
                VERSAO_RENDER, arquivo.name, arquivo.stat().st_size, arquivo.stat().st_mtime_ns,
                f"{trecho.entrada:.3f}", contar_quadros(trecho.duracao, fps_valor), largura, altura, fps,
                projeto.enquadramento, f"{trecho.ganho_db:.2f}",
            ]
            if trecho.legenda:  # sem legenda, a chave fica igual à de antes: os trechos já feitos continuam valendo
                partes.append(hashlib.sha1(trecho.legenda.encode()).hexdigest())
            if trecho.cor.hdr:  # se o ffmpeg ganhar o tone mapping, o trecho HDR é refeito
                partes.append(f"hdr-{tem_tone_mapping()}")
            chave = "|".join(map(str, partes))
            destino = pasta_trechos / (hashlib.sha1(chave.encode()).hexdigest()[:20] + ".mov")
            duracao = contar_quadros(trecho.duracao, fps_valor) / fps_valor
            if not destino.exists():
                temporario = destino.with_suffix(".tmp.mov")
                inicio = 0.1 + 0.85 * feito / total
                ass = preparar_legenda(cache, trecho.legenda) if trecho.legenda else None
                try:
                    self._ffmpeg(exp, comando_trecho(trecho, largura, altura, fps, fps_valor, projeto.enquadramento,
                                                     temporario, ass),
                                 lambda t, inicio=inicio, d=duracao: setattr(
                                     exp, "progresso", inicio + 0.85 * min(t, d) / total), pasta=cache)
                finally:
                    if ass:
                        apagar(cache / ass)
                trocar(temporario, destino)
            feito += duracao
            exp.progresso = 0.1 + 0.85 * feito / total
            prontos.append(destino)

        self._verificar(exp)
        exp.etapa = "Finalizando o vídeo…"
        pasta_saida = self.estudio.pasta_exportados(projeto.id)
        pasta_saida.mkdir(parents=True, exist_ok=True)
        nome = nome_do_arquivo(projeto.nome, pasta_saida)
        lista = pasta_trechos / "lista.txt"
        lista.write_text("\n".join(linha_da_lista(p) for p in prontos) + "\n", encoding="utf-8")
        temporario = pasta_saida / (nome + ".tmp")
        try:
            self._ffmpeg(exp, comando_juntar(lista, temporario),
                         lambda t: setattr(exp, "progresso", 0.95 + 0.05 * min(t / total, 1)))
            trocar(temporario, pasta_saida / nome)
        finally:
            apagar(temporario)

        # Mantém no cache só os trechos desta versão: são os que a próxima exportação provavelmente reaproveita.
        # O vídeo já está pronto: um trecho velho preso por outro programa não pode virar falha da exportação.
        usados = set(prontos)
        for arquivo in pasta_trechos.glob("*.mov"):
            if arquivo not in usados:
                apagar(arquivo)
        return nome

    def _ffmpeg(self, exp: Exportacao, args: list[str], ao_avancar, pasta: Path | None = None) -> None:
        """Roda o ffmpeg acompanhando o progresso (segundos já gravados) e permitindo cancelar."""
        with tempfile.TemporaryFile() as erros:
            try:
                processo = subprocess.Popen(
                    [ffmpeg(), "-hide_banner", "-nostdin", "-v", "error", "-progress", "pipe:1", "-nostats", *args],
                    stdout=subprocess.PIPE, stderr=erros, creationflags=SEM_JANELA, cwd=pasta,
                )
            except OSError as erro:
                raise ErroExportacao(ERRO_AO_RODAR) from erro
            exp._processo = processo
            for linha in processo.stdout:
                chave, _, valor = linha.decode("ascii", "replace").strip().partition("=")
                if chave in ("out_time_us", "out_time_ms") and valor.lstrip("-").isdigit():
                    ao_avancar(max(0, int(valor)) / 1_000_000)
            processo.wait()
            exp._processo = None
            self._verificar(exp)
            if processo.returncode != 0:
                erros.seek(0)
                detalhe = erros.read().decode("utf-8", "replace").strip().splitlines()[-3:]
                raise ErroExportacao("O ffmpeg falhou ao montar o vídeo. " + " ".join(detalhe))
