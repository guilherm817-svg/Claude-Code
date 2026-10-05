"""Transcrição local e gratuita com Whisper (faster-whisper).

O áudio é extraído direto do vídeo (MP4, MKV...) pelo PyAV, então não é preciso instalar o ffmpeg.
Na primeira vez, o modelo escolhido é baixado (de ~75 MB a ~3 GB) e fica guardado no computador.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from . import config
from .biblioteca import Segmento

log = logging.getLogger(__name__)

MODELOS_WHISPER = {
    "large-v3-turbo": "Equilibrado (recomendado): quase a qualidade do large-v3, bem mais rápido",
    "large-v3": "Máxima qualidade: o mais lento",
    "medium": "Bom: mais lento que o turbo e menos preciso",
    "small": "Rápido: erra mais nomes e termos técnicos",
    "base": "Muito rápido: qualidade baixa",
    "tiny": "Só para testar o app",
}

# Recebe (segundos já transcritos, duração total em segundos).
CallbackProgresso = Callable[[float, float], None]

_gpu_indisponivel = False


@lru_cache(maxsize=1)
def _carregar_modelo(modelo: str, dispositivo: str):
    from faster_whisper import BatchedInferencePipeline, WhisperModel
    from huggingface_hub.errors import HfHubHTTPError, LocalEntryNotFoundError

    log.info("Carregando Whisper %s (%s)", modelo, dispositivo)
    try:
        whisper = WhisperModel(modelo, device=dispositivo, compute_type="auto", cpu_threads=os.cpu_count() or 4)
    except (LocalEntryNotFoundError, HfHubHTTPError) as e:
        raise RuntimeError(
            f"Não foi possível baixar o modelo do Whisper ({modelo}). Na primeira vez que cada modelo é usado, "
            "o app precisa de internet para baixá-lo do Hugging Face; depois ele fica salvo no computador."
        ) from e
    # O modo em lote processa vários trechos de uma vez: bem mais rápido em aulas longas.
    return BatchedInferencePipeline(model=whisper)


def _erro_de_gpu(erro: Exception) -> bool:
    texto = str(erro).lower()
    return any(p in texto for p in ("cuda", "cudnn", "cublas", "gpu"))


def transcrever(
    caminho: Path,
    modelo: str = config.MODELO_WHISPER,
    idioma: str | None = config.IDIOMA,
    ao_progredir: CallbackProgresso | None = None,
    dispositivo: str = config.DISPOSITIVO,
) -> tuple[list[Segmento], float]:
    """Transcreve o arquivo e devolve (segmentos, duração em segundos)."""
    global _gpu_indisponivel
    if dispositivo == "auto" and _gpu_indisponivel:
        dispositivo = "cpu"
    try:
        return _transcrever(caminho, modelo, idioma, ao_progredir, dispositivo)
    except RuntimeError as e:
        # Placa NVIDIA detectada mas sem as bibliotecas CUDA/cuDNN instaladas: segue na CPU.
        if dispositivo == "auto" and _erro_de_gpu(e):
            log.warning("Falha ao usar a GPU (%s); transcrevendo na CPU.", e)
            _gpu_indisponivel = True
            return _transcrever(caminho, modelo, idioma, ao_progredir, "cpu")
        raise


def _transcrever(caminho, modelo, idioma, ao_progredir, dispositivo):
    pipeline = _carregar_modelo(modelo, dispositivo)
    resultado, info = pipeline.transcribe(
        str(caminho),
        language=None if idioma in (None, "", "auto") else idioma,
        batch_size=8,
    )
    duracao = float(info.duration)
    segmentos = []
    for s in resultado:
        segmentos.append(Segmento(inicio=round(s.start, 2), fim=round(s.end, 2), texto=s.text.strip()))
        if ao_progredir:
            ao_progredir(min(s.end, duracao), duracao)
    return segmentos, duracao
