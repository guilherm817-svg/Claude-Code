"""Processamento completo de uma aula (transcrever e analisar) e a fila que roda em segundo plano."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import analise, config, transcricao
from .biblioteca import Aula, Biblioteca, Etapa, formatar_tempo

log = logging.getLogger(__name__)

# Recebe (etapa, progresso de 0 a 1 ou None, mensagem).
Relator = Callable[[str, float | None, str], None]


def processar_aula(
    aula: Aula,
    *,
    modelo_whisper: str,
    idioma: str | None,
    refazer_analise: bool = False,
    relatar: Relator | None = None,
    transcrever=transcricao.transcrever,
    analisar=analise.analisar,
) -> None:
    """Transcreve (se ainda não tiver transcrição) e analisa a aula, registrando o status no disco."""

    def status(etapa: str, progresso: float | None = None, mensagem: str = "") -> None:
        aula.definir_status(etapa, progresso, mensagem)
        if relatar:
            relatar(etapa, progresso, mensagem)

    try:
        if not aula.tem_transcricao():
            if not aula.origem.exists():
                raise FileNotFoundError(f"Arquivo da aula não encontrado: {aula.origem}")
            status(Etapa.TRANSCREVENDO, 0.0, f"Carregando o Whisper ({modelo_whisper})…")
            inicio = time.monotonic()
            ultimo_aviso = 0.0

            def progresso(feito: float, total: float) -> None:
                nonlocal ultimo_aviso
                agora = time.monotonic()
                if agora - ultimo_aviso < 1:
                    return
                ultimo_aviso = agora
                fracao = feito / total if total else 0.0
                mensagem = f"Transcrevendo {formatar_tempo(feito)} de {formatar_tempo(total)}"
                if fracao > 0.02:
                    restante = (agora - inicio) * (1 - fracao) / fracao
                    mensagem += f" · faltam ~{max(1, round(restante / 60))} min"
                status(Etapa.TRANSCREVENDO, fracao, mensagem)

            segmentos, duracao = transcrever(aula.origem, modelo_whisper, idioma, progresso)
            if not any(s.texto for s in segmentos):
                raise RuntimeError("Nenhuma fala encontrada no áudio. O arquivo tem som?")
            aula.salvar_transcricao(segmentos, duracao, modelo_whisper, idioma)
            if aula.veio_de_envio:
                aula.origem.unlink(missing_ok=True)  # a cópia enviada não é mais necessária

        if refazer_analise or not aula.tem_analise():
            if not config.credenciais_claude():
                status(Etapa.TRANSCRITA, None, "Transcrição pronta. Configure a chave da API do Claude para gerar a análise.")
                return
            status(Etapa.ANALISANDO, 0.0, "Enviando a transcrição para o Claude…")
            resultado = analisar(aula, lambda fracao, mensagem: status(Etapa.ANALISANDO, fracao, mensagem))
            aula.salvar_analise(resultado)

        status(Etapa.PRONTA)
    except Exception as e:
        log.exception("Falha ao processar %s", aula.id)
        status(Etapa.ERRO, None, str(e) or e.__class__.__name__)


@dataclass
class Tarefa:
    aula_id: str
    modelo_whisper: str
    idioma: str | None
    refazer_analise: bool = False


class Processador:
    """Fila de aulas processadas uma por vez numa thread, sem travar a interface."""

    def __init__(self, biblioteca: Biblioteca, **opcoes_processamento):
        self.biblioteca = biblioteca
        self._opcoes = opcoes_processamento
        self._fila: queue.Queue[Tarefa] = queue.Queue()
        self._pendentes: set[str] = set()
        self._trava = threading.Lock()
        threading.Thread(target=self._trabalhar, daemon=True, name="processador-aulas").start()

    def enfileirar(self, aula: Aula, modelo_whisper: str, idioma: str | None, refazer_analise: bool = False) -> None:
        with self._trava:
            if aula.id in self._pendentes:
                return
            self._pendentes.add(aula.id)
        aula.definir_status(Etapa.NA_FILA, None, "Aguardando na fila…")
        self._fila.put(Tarefa(aula.id, modelo_whisper, idioma, refazer_analise))

    def retomar_interrompidas(self) -> None:
        """Recoloca na fila as aulas que estavam em andamento quando o app foi fechado."""
        for aula in self.biblioteca.aulas():
            if aula.status()["etapa"] in Etapa.EM_ANDAMENTO:
                meta = aula.meta
                self.enfileirar(aula, meta.get("modelo_whisper") or config.MODELO_WHISPER, meta.get("idioma", config.IDIOMA))

    def ocupado(self) -> bool:
        with self._trava:
            return bool(self._pendentes)

    def _trabalhar(self) -> None:
        while True:
            tarefa = self._fila.get()
            try:
                aula = self.biblioteca.obter(tarefa.aula_id)
                if aula:  # pode ter sido excluída enquanto esperava
                    processar_aula(
                        aula,
                        modelo_whisper=tarefa.modelo_whisper,
                        idioma=tarefa.idioma,
                        refazer_analise=tarefa.refazer_analise,
                        **self._opcoes,
                    )
            except Exception:
                # Ex.: aula excluída no meio do processamento. A fila precisa continuar viva.
                log.exception("Erro inesperado na fila (%s)", tarefa.aula_id)
            finally:
                with self._trava:
                    self._pendentes.discard(tarefa.aula_id)
                self._fila.task_done()

    def aguardar(self) -> None:
        self._fila.join()
