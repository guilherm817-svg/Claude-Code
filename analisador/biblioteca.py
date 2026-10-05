"""Armazenamento local das aulas: cada aula é uma pasta com arquivos JSON.

    biblioteca/
      aula-01-introducao-3fa2c1/
        aula.json         metadados (arquivo de origem, curso, duração...)
        status.json       etapa atual do processamento e progresso
        transcricao.json  segmentos do Whisper com início/fim em segundos
        analise.json      resumo, capítulos, flashcards e quiz
        chat.json         histórico da conversa com a aula
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import config
from .modelos import Analise


class Etapa:
    NA_FILA = "na_fila"
    TRANSCREVENDO = "transcrevendo"
    ANALISANDO = "analisando"
    TRANSCRITA = "transcrita"  # transcrição pronta, análise pendente (ex.: sem chave da API)
    PRONTA = "pronta"
    ERRO = "erro"

    EM_ANDAMENTO = (NA_FILA, TRANSCREVENDO, ANALISANDO)


@dataclass
class Segmento:
    inicio: float
    fim: float
    texto: str


def formatar_tempo(segundos: float) -> str:
    s = max(0, int(segundos))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def tempo_para_segundos(texto: str) -> int | None:
    """Converte "HH:MM:SS", "MM:SS" ou "[HH:MM:SS]" em segundos."""
    m = re.fullmatch(r"\[?\s*(?:(\d+):)?(\d{1,2}):(\d{2})\s*\]?", texto.strip())
    if not m:
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(s)


def agrupar_em_blocos(segmentos: list[Segmento], duracao_bloco: float = 30.0) -> list[Segmento]:
    """Junta segmentos curtos em blocos de ~30s: minutagem suficiente sem gastar tokens à toa."""
    blocos: list[Segmento] = []
    for seg in segmentos:
        texto = seg.texto.strip()
        if not texto:
            continue
        if blocos and seg.inicio - blocos[-1].inicio < duracao_bloco:
            blocos[-1].texto += " " + texto
            blocos[-1].fim = seg.fim
        else:
            blocos.append(Segmento(seg.inicio, seg.fim, texto))
    return blocos


def transcricao_com_minutagem(segmentos: list[Segmento]) -> str:
    return "\n".join(f"[{formatar_tempo(b.inicio)}] {b.texto}" for b in agrupar_em_blocos(segmentos))


def sem_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def slug(texto: str, limite: int = 50) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", sem_acentos(texto).lower()).strip("-")
    return s[:limite].rstrip("-") or "aula"


def ordem_natural(texto: str) -> list:
    """Chave de ordenação em que "Aula 2" vem antes de "Aula 10"."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", texto)]


def titulo_do_arquivo(caminho: Path) -> str:
    return re.sub(r"[_]+", " ", caminho.stem).strip()


def listar_midias(pasta: Path) -> list[Path]:
    arquivos = [
        p for p in pasta.rglob("*")
        if p.is_file() and p.suffix.lower() in config.EXTENSOES_MIDIA and not p.name.startswith(".")
    ]
    return sorted(arquivos, key=lambda p: ordem_natural(str(p.relative_to(pasta))))


def _salvar_json(caminho: Path, dados) -> None:
    # Grava num arquivo temporário e troca de uma vez, para a interface nunca ler um JSON pela metade.
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


def _ler_json(caminho: Path, padrao=None):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


class Aula:
    def __init__(self, pasta: Path):
        self.pasta = pasta

    @property
    def id(self) -> str:
        return self.pasta.name

    @property
    def meta(self) -> dict:
        return _ler_json(self.pasta / "aula.json", {})

    def _atualizar_meta(self, **campos) -> None:
        _salvar_json(self.pasta / "aula.json", {**self.meta, **campos})

    @property
    def titulo(self) -> str:
        return self.meta.get("titulo", self.id)

    @property
    def curso(self) -> str:
        return self.meta.get("curso") or "Sem curso"

    @property
    def origem(self) -> Path:
        return Path(self.meta["origem"])

    @property
    def veio_de_envio(self) -> bool:
        return bool(self.meta.get("envio"))

    @property
    def duracao(self) -> float | None:
        return self.meta.get("duracao")

    # Status do processamento

    def status(self) -> dict:
        return _ler_json(self.pasta / "status.json", {"etapa": Etapa.NA_FILA, "progresso": None, "mensagem": ""})

    def definir_status(self, etapa: str, progresso: float | None = None, mensagem: str = "") -> None:
        _salvar_json(
            self.pasta / "status.json",
            {"etapa": etapa, "progresso": progresso, "mensagem": mensagem, "atualizado_em": time.time()},
        )

    # Transcrição

    def tem_transcricao(self) -> bool:
        return (self.pasta / "transcricao.json").exists()

    def segmentos(self) -> list[Segmento]:
        return [Segmento(**s) for s in _ler_json(self.pasta / "transcricao.json", [])]

    def salvar_transcricao(self, segmentos: list[Segmento], duracao: float, modelo: str, idioma: str | None) -> None:
        _salvar_json(self.pasta / "transcricao.json", [asdict(s) for s in segmentos])
        self._atualizar_meta(duracao=duracao, modelo_whisper=modelo, idioma=idioma)

    # Análise

    def tem_analise(self) -> bool:
        return (self.pasta / "analise.json").exists()

    def analise(self) -> Analise | None:
        dados = _ler_json(self.pasta / "analise.json")
        return Analise.model_validate(dados) if dados else None

    def salvar_analise(self, analise: Analise) -> None:
        _salvar_json(self.pasta / "analise.json", analise.model_dump())

    # Chat

    def chat(self) -> list[dict]:
        return _ler_json(self.pasta / "chat.json", [])

    def salvar_chat(self, mensagens: list[dict]) -> None:
        _salvar_json(self.pasta / "chat.json", mensagens)

    def limpar_chat(self) -> None:
        (self.pasta / "chat.json").unlink(missing_ok=True)

    def excluir(self) -> None:
        if self.veio_de_envio:
            self.origem.unlink(missing_ok=True)
        shutil.rmtree(self.pasta, ignore_errors=True)


class Biblioteca:
    def __init__(self, pasta: Path | None = None):
        self.pasta = Path(pasta or config.PASTA_DADOS)
        self.pasta.mkdir(parents=True, exist_ok=True)

    @property
    def pasta_envios(self) -> Path:
        p = self.pasta / "_envios"
        p.mkdir(exist_ok=True)
        return p

    def aulas(self) -> list[Aula]:
        aulas = [
            Aula(p) for p in self.pasta.iterdir()
            if p.is_dir() and not p.name.startswith(("_", ".")) and (p / "aula.json").exists()
        ]
        return sorted(aulas, key=lambda a: (ordem_natural(a.curso), ordem_natural(a.titulo)))

    def obter(self, aula_id: str) -> Aula | None:
        pasta = self.pasta / aula_id
        return Aula(pasta) if aula_id and (pasta / "aula.json").exists() else None

    def por_origem(self) -> dict[str, Aula]:
        return {a.meta.get("origem"): a for a in self.aulas()}

    def adicionar(self, origem: Path, curso: str | None = None, envio: bool = False) -> Aula:
        """Registra um arquivo de aula. Se o mesmo arquivo já foi adicionado, devolve a aula existente."""
        origem = Path(origem).resolve()
        hash_origem = hashlib.sha1(str(origem).encode("utf-8")).hexdigest()[:6]
        aula = Aula(self.pasta / f"{slug(origem.stem)}-{hash_origem}")
        if (aula.pasta / "aula.json").exists():
            return aula
        aula.pasta.mkdir(parents=True)
        aula._atualizar_meta(
            titulo=titulo_do_arquivo(origem),
            origem=str(origem),
            curso=curso,
            envio=envio,
            adicionada_em=datetime.now().isoformat(timespec="seconds"),
        )
        aula.definir_status(Etapa.NA_FILA)
        return aula
