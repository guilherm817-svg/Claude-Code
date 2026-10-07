"""Transcrição das falas dos clipes, com o tempo de cada palavra, para as legendas automáticas.

Usa o Whisper local e gratuito (faster-whisper), o mesmo do Analisador. Na primeira vez o modelo é baixado da
internet e fica guardado no computador. Os pedidos de um projeto viram um trabalho em segundo plano, que transcreve
um clipe de cada vez e grava cada resultado no projeto assim que fica pronto.
"""

from __future__ import annotations

import errno
import logging
import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import config
from .midia import ler_audio
from .projetos import MAX_LETRAS, Estudio, Palavra, ProjetoNaoEncontrado, novo_id

log = logging.getLogger(__name__)

TAMANHO_DOS_MODELOS = {"large-v3-turbo": "cerca de 1,6 GB", "large-v3": "cerca de 3 GB", "medium": "cerca de 1,5 GB",
                       "small": "cerca de 500 MB", "base": "cerca de 150 MB", "tiny": "cerca de 75 MB"}


class ErroTranscricao(Exception):
    """Falha que impede qualquer transcrição (sem modelo), já explicada em português."""


@dataclass
class Transcricao:
    idioma: str
    palavras: list[dict]  # {inicio, fim, texto}, em segundos do arquivo


_gpu_indisponivel = False
_modelos_prontos: set[str] = set()
_trava_whisper = threading.Lock()  # um clipe de cada vez: o modelo já ocupa a máquina inteira


def tamanho_do_modelo(modelo: str = config.MODELO_WHISPER) -> str:
    return TAMANHO_DOS_MODELOS.get(modelo, "mais de 1 GB")


def modelo_pronto(modelo: str = config.MODELO_WHISPER) -> bool:
    """Se o modelo já foi carregado nesta sessão (então não há download nem espera pela frente)."""
    return modelo in _modelos_prontos


@lru_cache(maxsize=1)
def _carregar_modelo(modelo: str, dispositivo: str):
    """O modelo do Whisper, carregado uma vez. Os testes trocam esta função por um modelo falso."""
    import httpx
    from faster_whisper import WhisperModel
    from huggingface_hub.errors import HfHubHTTPError, LocalEntryNotFoundError

    try:
        return WhisperModel(modelo, device=dispositivo, compute_type="auto", cpu_threads=os.cpu_count() or 4)
    except ValueError as erro:
        raise ErroTranscricao(f"O modelo de transcrição “{modelo}” não existe. Confira o ESTUDIO_MODELO_WHISPER "
                              "no arquivo .env.") from erro
    except OSError as erro:
        if erro.errno == errno.ENOSPC:
            raise ErroTranscricao(f"Não há espaço no disco para baixar o modelo de transcrição "
                                  f"({tamanho_do_modelo(modelo)}).") from erro
        raise ErroTranscricao(_sem_internet(modelo)) from erro
    except (LocalEntryNotFoundError, HfHubHTTPError, httpx.HTTPError) as erro:
        raise ErroTranscricao(_sem_internet(modelo)) from erro


def _sem_internet(modelo: str) -> str:
    return (f"Não consegui baixar o modelo de transcrição ({tamanho_do_modelo(modelo)}). Na primeira vez, as "
            "legendas precisam de internet para baixá-lo; depois ele fica salvo no computador e funciona sem "
            "internet. Confira a conexão e tente de novo.")


def _erro_de_gpu(erro: Exception) -> bool:
    texto = str(erro).lower()
    return any(p in texto for p in ("cuda", "cudnn", "cublas", "gpu"))


def transcrever(caminho: Path, idioma: str | None = None, modelo: str = config.MODELO_WHISPER,
                dispositivo: str = config.DISPOSITIVO) -> Transcricao:
    """O idioma falado e cada palavra com início e fim. idioma None: o Whisper detecta."""
    global _gpu_indisponivel
    audio = ler_audio(caminho)
    if not len(audio):
        return Transcricao(idioma=idioma or "", palavras=[])
    if dispositivo == "auto" and _gpu_indisponivel:
        dispositivo = "cpu"
    with _trava_whisper:
        try:
            resultado = _transcrever(audio, idioma, modelo, dispositivo)
        except RuntimeError as erro:
            # Placa NVIDIA detectada mas sem as bibliotecas CUDA/cuDNN instaladas: segue na CPU.
            if dispositivo != "auto" or not _erro_de_gpu(erro):
                raise
            log.warning("Falha ao usar a GPU (%s); transcrevendo na CPU.", erro)
            _gpu_indisponivel = True
            resultado = _transcrever(audio, idioma, modelo, "cpu")
    _modelos_prontos.add(modelo)
    return resultado


def _transcrever(audio, idioma, modelo, dispositivo) -> Transcricao:
    whisper = _carregar_modelo(modelo, dispositivo)
    # Clipes curtos: sem o modo em lote. Sem condicionar no texto anterior e com o filtro de voz, o Whisper não
    # "inventa" frases no silêncio do fim do clipe.
    segmentos, info = whisper.transcribe(audio, language=idioma, word_timestamps=True,
                                         condition_on_previous_text=False, vad_filter=True)
    palavras = []
    for segmento in segmentos:
        for palavra in segmento.words or []:
            texto = palavra.word.strip()
            if texto:
                palavras.append({"inicio": round(float(palavra.start), 3), "fim": round(float(palavra.end), 3),
                                 "texto": texto})
    return Transcricao(idioma=info.language, palavras=palavras)


def ajustar_palavras(palavras: list[dict], duracao: float) -> list[Palavra]:
    """As palavras no formato que o projeto aceita: dentro do clipe, em ordem e cada uma com alguma duração."""
    ajustadas = []
    for p in sorted(palavras, key=lambda p: p["inicio"]):
        texto = " ".join(p["texto"].split())[:MAX_LETRAS]
        inicio = min(max(p["inicio"], 0.0), duracao)
        fim = min(max(p["fim"], inicio), duracao)
        if fim - inicio < 0.01:  # o Whisper às vezes devolve palavra sem duração, quase sempre a última
            fim = min(inicio + 0.05, duracao)
            inicio = max(0.0, min(inicio, fim - 0.05))
        if texto and fim > inicio:
            ajustadas.append(Palavra(inicio=round(inicio, 3), fim=round(fim, 3), texto=texto))
    return ajustadas


# Trabalhos em segundo plano


@dataclass
class TrabalhoLegendas:
    id: str
    projeto_id: str
    estado: str = "na_fila"  # na_fila, transcrevendo, pronta, erro
    etapa: str = "Preparando…"
    erro: str | None = None
    fila: list[str] = field(default_factory=list)
    atual: str | None = None
    total: int = 0
    feitos: int = 0
    resultados: dict[str, list[dict]] = field(default_factory=dict)  # o mais recente de cada mídia
    concluidas: list[str] = field(default_factory=list)  # na ordem em que terminaram (uma mídia pode repetir)
    falhas: dict[str, str] = field(default_factory=dict)

    @property
    def ativo(self) -> bool:
        return self.estado in ("na_fila", "transcrevendo")

    def como_dict(self) -> dict:
        return {"id": self.id, "projeto_id": self.projeto_id, "estado": self.estado,
                "progresso": round(self.feitos / self.total, 4) if self.total else 1.0, "etapa": self.etapa,
                "erro": self.erro, "pendentes": ([self.atual] if self.atual else []) + list(self.fila),
                "resultados": dict(self.resultados), "concluidas": list(self.concluidas)}


class Transcritor:
    def __init__(self, estudio: Estudio):
        self.estudio = estudio
        self._trabalhos: dict[str, TrabalhoLegendas] = {}
        self._trava = threading.Lock()

    def obter(self, trabalho_id: str) -> dict | None:
        with self._trava:
            trabalho = self._trabalhos.get(trabalho_id)
            dados = trabalho.como_dict() if trabalho else None
        return self._com_gravadas(dados) if dados else None

    def em_andamento(self, projeto_id: str) -> dict | None:
        """O trabalho do projeto que ainda está andando, para a tela voltar a acompanhá-lo depois de recarregar."""
        with self._trava:
            trabalho = self._ativo_do_projeto(projeto_id)
            dados = trabalho.como_dict() if trabalho else None
        return self._com_gravadas(dados) if dados else None

    def _ativo_do_projeto(self, projeto_id: str) -> TrabalhoLegendas | None:
        return next((t for t in self._trabalhos.values() if t.projeto_id == projeto_id and t.ativo), None)

    def _com_gravadas(self, dados: dict) -> dict:
        """Troca o resultado de cada mídia concluída pela legenda que está gravada no projeto. Uma tela que recarregou
        no meio do trabalho recebe as correções feitas depois da transcrição, e não o texto que saiu do Whisper."""
        if dados["resultados"]:
            try:
                gravadas = self.estudio.legendas_gravadas(dados["projeto_id"])
            except ProjetoNaoEncontrado:
                gravadas = {}
            dados["resultados"] = {midia_id: [p.model_dump() for p in gravadas[midia_id]]
                                   for midia_id in dados["resultados"] if midia_id in gravadas}
        return dados

    def iniciar(self, projeto_id: str, midias: list[str] | None = None, refazer: bool = False,
                sincrono: bool = False) -> dict:
        """Transcreve as mídias pedidas (todas, se None) que ainda não têm legenda, ou todas elas se refazer.
        Se o projeto já tem um trabalho andando, as mídias entram na fila dele."""
        projeto = self.estudio.abrir(projeto_id)
        if midias is None:
            alvo = [m.id for m in projeto.midias]
        else:
            if any(projeto.midia(m) is None for m in midias):
                raise ProjetoNaoEncontrado(projeto_id)
            alvo = list(dict.fromkeys(midias))
        if not refazer:
            alvo = [m for m in alvo if m not in projeto.legendas]

        with self._trava:
            trabalho = self._ativo_do_projeto(projeto_id)
            if trabalho:
                for midia_id in alvo:
                    if midia_id in trabalho.fila:
                        continue
                    if not refazer and (midia_id == trabalho.atual or midia_id in trabalho.resultados):
                        continue
                    trabalho.fila.append(midia_id)
                    trabalho.total += 1
                dados = trabalho.como_dict()
            else:
                trabalho = TrabalhoLegendas(id=novo_id(), projeto_id=projeto_id, fila=alvo, total=len(alvo))
                self._trabalhos[trabalho.id] = trabalho
                self._esquecer_antigos()
                dados = None
        if dados is None:
            if sincrono:
                self._rodar(trabalho)
            else:
                threading.Thread(target=self._rodar, args=(trabalho,), daemon=True).start()
            with self._trava:
                dados = trabalho.como_dict()
        return self._com_gravadas(dados)

    def _esquecer_antigos(self) -> None:
        terminados = [t for t in self._trabalhos.values() if not t.ativo]
        for trabalho in terminados[:-20]:
            del self._trabalhos[trabalho.id]

    def _rodar(self, trabalho: TrabalhoLegendas) -> None:
        while True:
            with self._trava:
                if not trabalho.fila:
                    trabalho.atual = None
                    if trabalho.falhas:
                        trabalho.estado = "erro"
                        trabalho.erro = (f"Não consegui transcrever {len(trabalho.falhas)} "
                                         f"{'clipe' if len(trabalho.falhas) == 1 else 'clipes'}: "
                                         + next(iter(trabalho.falhas.values())))
                        trabalho.etapa = "A transcrição terminou com erro."
                    else:
                        trabalho.estado, trabalho.etapa = "pronta", "Legendas prontas."
                    return
                midia_id = trabalho.fila.pop(0)
                trabalho.atual = midia_id
                trabalho.estado = "transcrevendo"
                trabalho.etapa = f"Transcrevendo clipe {trabalho.feitos + 1} de {trabalho.total}…"
                if not modelo_pronto():
                    trabalho.etapa += (f" Na primeira vez, o modelo de transcrição ({tamanho_do_modelo()}) é baixado"
                                       " e carregado, o que pode levar alguns minutos.")
            try:
                palavras = self._transcrever_midia(trabalho.projeto_id, midia_id)
            except (ErroTranscricao, ProjetoNaoEncontrado) as erro:
                # Sem modelo (ou sem projeto), nenhum outro clipe vai dar certo: para e explica.
                with self._trava:
                    trabalho.estado, trabalho.etapa, trabalho.atual = "erro", "A transcrição parou.", None
                    trabalho.erro = str(erro) if isinstance(erro, ErroTranscricao) else "O projeto foi excluído."
                    trabalho.fila.clear()
                return
            except Exception as erro:  # um clipe com problema não impede os outros
                log.exception("Falha ao transcrever a mídia %s", midia_id)
                with self._trava:
                    trabalho.falhas[midia_id] = str(erro) or erro.__class__.__name__
                    trabalho.feitos += 1
                continue
            with self._trava:
                if palavras is not None:
                    trabalho.resultados[midia_id] = palavras
                    trabalho.concluidas.append(midia_id)
                trabalho.feitos += 1
                trabalho.atual = None

    def _transcrever_midia(self, projeto_id: str, midia_id: str) -> list[dict] | None:
        """Transcreve e grava no projeto. None se a mídia saiu do projeto no meio do caminho."""
        projeto = self.estudio.abrir(projeto_id)
        midia = projeto.midia(midia_id)
        if midia is None:
            return None
        palavras: list[Palavra] = []
        if midia.tem_audio:
            idioma = None if projeto.idioma_legenda == "auto" else projeto.idioma_legenda
            transcricao = transcrever(self.estudio.arquivo_midia(projeto_id, midia), idioma)
            palavras = ajustar_palavras(transcricao.palavras, midia.duracao)
        if not self.estudio.gravar_legenda(projeto_id, midia_id, palavras):
            return None
        return [p.model_dump() for p in palavras]
