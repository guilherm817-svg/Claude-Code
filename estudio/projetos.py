"""Projetos do Estúdio, guardados em pastas: a mídia importada, a linha do tempo e os vídeos exportados.

    meus-reels/<projeto>/projeto.json
    meus-reels/<projeto>/midia/<id>.mp4        cópia de cada clipe importado
    meus-reels/<projeto>/cache/                miniaturas, forma de onda e trechos já renderizados
    meus-reels/<projeto>/exportados/           os vídeos prontos
"""

import json
import os
import re
import secrets
import shutil
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from . import config
from .midia import ErroMidia, analisar, gerar_tira

PADRAO_ID = r"^[0-9a-f]{12}$"
DURACAO_MINIMA = 0.1  # s: o menor trecho que a linha do tempo aceita
MAX_PALAVRAS = 5000  # por clipe: muito mais do que cabe num clipe de IA
MAX_LETRAS = 80  # por palavra
TOLERANCIA_LEGENDA = 0.5  # s: o Whisper às vezes marca a última palavra um pouco depois do fim do clipe
ESPERA_TROCA = 2.0  # s: quanto trocar_arquivo insiste antes de desistir

Formato = Literal["reels", "feed", "quadrado", "youtube"]
Enquadramento = Literal["preencher", "desfocado"]


class ProjetoNaoEncontrado(Exception):
    pass


class ErroImportacao(Exception):
    pass


def novo_id() -> str:
    return secrets.token_hex(6)


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def trocar_arquivo(origem: Path, destino: Path) -> None:
    """Põe `origem` no lugar de `destino` de uma vez (os.replace), insistindo um pouco se o Windows recusar.

    No Windows a troca dá PermissionError enquanto outro programa está com um dos arquivos aberto: o antivírus, o
    indexador ou o OneDrive costumam ler por um instante cada arquivo recém-gravado.
    """
    limite = time.monotonic() + ESPERA_TROCA
    espera = 0.01
    while True:
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if time.monotonic() + espera > limite:
                raise
            time.sleep(espera)
            espera = min(espera * 2, 0.25)


def apagar_arquivos(*arquivos: Path) -> None:
    for arquivo in arquivos:
        try:
            arquivo.unlink(missing_ok=True)
        except OSError:
            pass  # no Windows, o arquivo pode estar aberto pela prévia; sobra no disco, mas fora do projeto


def conferir_legenda(palavras: list["Palavra"], duracao: float) -> list["Palavra"]:
    """Confere as palavras de uma mídia: em ordem, cada uma com duração e dentro do clipe (um pequeno excesso nas
    pontas é só limitado)."""
    if len(palavras) > MAX_PALAVRAS:
        raise ErroImportacao("A legenda de um clipe tem palavras demais.")
    conferidas = []
    for p in palavras:
        if p.inicio < -TOLERANCIA_LEGENDA or p.fim > duracao + TOLERANCIA_LEGENDA:
            raise ErroImportacao("Uma palavra da legenda está fora do tempo do clipe.")
        inicio = round(min(max(p.inicio, 0.0), duracao), 3)
        fim = round(min(max(p.fim, 0.0), duracao), 3)
        if fim <= inicio:
            raise ErroImportacao(f"A palavra “{p.texto}” da legenda termina antes de começar.")
        if conferidas and inicio < conferidas[-1].inicio:
            raise ErroImportacao("As palavras da legenda estão fora de ordem.")
        conferidas.append(Palavra(inicio=inicio, fim=fim, texto=p.texto))
    return conferidas


class Aviso(BaseModel):
    codigo: str
    texto: str


class Midia(BaseModel):
    """Um clipe importado. A análise é feita uma vez, na importação."""
    id: str
    nome: str
    arquivo: str
    duracao: float
    largura: int
    altura: int
    fps: float
    codec: str
    tem_audio: bool
    fala_inicio: float | None = None
    fala_fim: float | None = None
    tira_quadros: int = 0
    avisos: list[Aviso] = []
    importada_em: str = ""

    def corte_sugerido(self) -> tuple[float, float]:
        """Do começo ao fim da fala, com uma folga dos dois lados. Sem fala detectada, o clipe inteiro."""
        if self.fala_inicio is None or self.fala_fim is None:
            return 0.0, self.duracao
        entrada = max(0.0, self.fala_inicio - config.FOLGA_ANTES_DA_FALA)
        saida = min(self.duracao, self.fala_fim + config.FOLGA_DEPOIS_DA_FALA)
        if saida - entrada < DURACAO_MINIMA:
            return 0.0, self.duracao
        return round(entrada, 3), round(saida, 3)


class Item(BaseModel):
    """Um trecho de uma mídia colocado na linha do tempo. A mesma mídia pode aparecer várias vezes."""
    id: str = Field(pattern=PADRAO_ID)
    midia_id: str = Field(pattern=PADRAO_ID)
    entrada: float = Field(ge=0)
    saida: float = Field(gt=0)


class Palavra(BaseModel):
    """Uma palavra da legenda, com o tempo dela em segundos do arquivo da mídia."""
    inicio: float
    fim: float
    texto: str

    @field_validator("texto")
    @classmethod
    def _texto(cls, valor: str) -> str:
        # PydanticCustomError: a mensagem chega à tela sem o "Value error," em inglês na frente.
        valor = " ".join(unicodedata.normalize("NFC", valor).split())
        if not valor:
            raise PydanticCustomError("palavra_vazia", "Uma palavra da legenda está vazia.")
        if len(valor) > MAX_LETRAS:
            raise PydanticCustomError("palavra_longa", "Uma palavra da legenda passou de 80 letras.")
        return valor


class EstiloLegenda(BaseModel):
    preset: Literal["destaque", "uma_palavra", "classica", "caixa"] = "destaque"
    tamanho: Literal["P", "M", "G"] = "M"
    posicao: Literal["alto", "centro", "baixo"] = "baixo"
    maiusculas: bool = True
    animacao: bool = True


class Ajustes(BaseModel):
    """O que a tela pode mudar num projeto."""
    nome: str = Field(min_length=1, max_length=120)
    formato: Formato = "reels"
    enquadramento: Enquadramento = "preencher"
    igualar_volume: bool = True
    linha: list[Item] = []
    legendas_ativas: bool = False
    idioma_legenda: Literal["auto", "pt", "en", "es"] = "auto"
    estilo_legenda: EstiloLegenda = EstiloLegenda()
    # Palavras transcritas de cada mídia. Num salvamento, as mídias que não vierem ficam como estão no servidor:
    # assim a tela nunca apaga uma transcrição que terminou enquanto ela salvava.
    legendas: dict[str, list[Palavra]] = {}

    @field_validator("nome")
    @classmethod
    def _nome(cls, valor: str) -> str:
        valor = " ".join(valor.split())
        if not valor:
            raise ValueError("O nome do projeto não pode ficar vazio.")
        return valor


class Projeto(Ajustes):
    id: str
    criado_em: str
    atualizado_em: str
    midias: list[Midia] = []

    def midia(self, midia_id: str) -> Midia | None:
        return next((m for m in self.midias if m.id == midia_id), None)

    @property
    def duracao(self) -> float:
        return round(sum(i.saida - i.entrada for i in self.linha), 3)

    def resumo(self) -> dict:
        return {"id": self.id, "nome": self.nome, "atualizado_em": self.atualizado_em,
                "clipes": len(self.linha), "duracao": self.duracao}


class Estudio:
    def __init__(self, pasta: Path | None = None):
        self.pasta = Path(pasta or config.PASTA_DADOS)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._trava = threading.RLock()

    # Caminhos

    def pasta_projeto(self, projeto_id: str) -> Path:
        if not re.match(PADRAO_ID, projeto_id or ""):
            raise ProjetoNaoEncontrado(projeto_id)
        return self.pasta / projeto_id

    def pasta_midia(self, projeto_id: str) -> Path:
        return self.pasta_projeto(projeto_id) / "midia"

    def pasta_cache(self, projeto_id: str) -> Path:
        return self.pasta_projeto(projeto_id) / "cache"

    def pasta_exportados(self, projeto_id: str) -> Path:
        return self.pasta_projeto(projeto_id) / "exportados"

    def arquivo_midia(self, projeto_id: str, midia: Midia) -> Path:
        return self.pasta_midia(projeto_id) / midia.arquivo

    def arquivo_tira(self, projeto_id: str, midia_id: str) -> Path:
        return self.pasta_cache(projeto_id) / f"{midia_id}-tira.jpg"

    def arquivo_onda(self, projeto_id: str, midia_id: str) -> Path:
        return self.pasta_cache(projeto_id) / f"{midia_id}-onda.json"

    # Leitura e gravação. As leituras do projeto.json também pegam a trava: no Windows, trocar o arquivo enquanto
    # outra thread o lê (o <video> da prévia pede a mídia o tempo todo) dá PermissionError.

    def listar(self) -> list[Projeto]:
        with self._trava:
            # Bytes, não texto: quem decodifica é o pydantic, e um arquivo que não é UTF-8 vira ValueError lá embaixo.
            conteudos = [arquivo.read_bytes() for arquivo in self.pasta.glob("*/projeto.json")]
        projetos = []
        for conteudo in conteudos:
            try:
                projetos.append(Projeto.model_validate_json(conteudo))
            except ValueError:
                continue  # projeto corrompido não derruba a lista
        return sorted(projetos, key=lambda p: p.atualizado_em, reverse=True)

    def abrir(self, projeto_id: str) -> Projeto:
        arquivo = self.pasta_projeto(projeto_id) / "projeto.json"
        with self._trava:
            if not arquivo.exists():
                raise ProjetoNaoEncontrado(projeto_id)
            texto = arquivo.read_text(encoding="utf-8")
        return Projeto.model_validate_json(texto)

    def salvar(self, projeto: Projeto) -> Projeto:
        with self._trava:
            projeto.atualizado_em = agora()
            pasta = self.pasta_projeto(projeto.id)
            pasta.mkdir(parents=True, exist_ok=True)
            temporario = pasta / "projeto.json.tmp"
            temporario.write_text(projeto.model_dump_json(indent=1), encoding="utf-8")
            trocar_arquivo(temporario, pasta / "projeto.json")  # nunca fica um projeto pela metade
            return projeto

    def criar(self, nome: str | None = None) -> Projeto:
        with self._trava:
            nome = nome or f"Reels {len(self.listar()) + 1}"
            projeto = Projeto(id=novo_id(), nome=nome, criado_em=agora(), atualizado_em=agora())
            return self.salvar(projeto)

    def excluir(self, projeto_id: str) -> None:
        with self._trava:
            self.abrir(projeto_id)
            shutil.rmtree(self.pasta_projeto(projeto_id), ignore_errors=True)

    def aplicar(self, projeto_id: str, ajustes: Ajustes) -> Projeto:
        """Grava o que a tela mandou, conferindo que cada trecho aponta para uma mídia do projeto e cabe nela."""
        with self._trava:
            projeto = self.abrir(projeto_id)
            vistos = set()
            linha = []
            for item in ajustes.linha:
                midia = projeto.midia(item.midia_id)
                if midia is None:
                    raise ErroImportacao("A linha do tempo cita um clipe que não está no projeto.")
                if item.id in vistos:
                    raise ErroImportacao("Há dois trechos com o mesmo identificador na linha do tempo.")
                vistos.add(item.id)
                entrada = min(max(item.entrada, 0.0), max(midia.duracao - DURACAO_MINIMA, 0.0))
                saida = min(max(item.saida, entrada + DURACAO_MINIMA), midia.duracao)
                linha.append(Item(id=item.id, midia_id=midia.id, entrada=round(entrada, 3), saida=round(saida, 3)))
            legendas = {}
            for midia_id, palavras in ajustes.legendas.items():
                midia = projeto.midia(midia_id)
                if midia is None:
                    raise ErroImportacao("A legenda cita um clipe que não está no projeto.")
                legendas[midia_id] = conferir_legenda(palavras, midia.duracao)
            projeto.nome, projeto.formato = ajustes.nome, ajustes.formato
            projeto.enquadramento, projeto.igualar_volume = ajustes.enquadramento, ajustes.igualar_volume
            projeto.linha = linha
            projeto.legendas_ativas, projeto.idioma_legenda = ajustes.legendas_ativas, ajustes.idioma_legenda
            projeto.estilo_legenda = ajustes.estilo_legenda
            projeto.legendas.update(legendas)
            return self.salvar(projeto)

    def gravar_legenda(self, projeto_id: str, midia_id: str, palavras: list[Palavra]) -> bool:
        """Guarda a transcrição de uma mídia. False se a mídia saiu do projeto enquanto era transcrita."""
        with self._trava:
            projeto = self.abrir(projeto_id)
            midia = projeto.midia(midia_id)
            if midia is None:
                return False
            projeto.legendas[midia_id] = conferir_legenda(palavras, midia.duracao)
            self.salvar(projeto)
            return True

    def legendas_gravadas(self, projeto_id: str) -> dict[str, list[Palavra]]:
        """As legendas como estão gravadas agora, lidas com a trava (nunca no meio de uma gravação)."""
        with self._trava:
            return self.abrir(projeto_id).legendas

    # Mídia

    def importar(self, projeto_id: str, origem: BinaryIO, nome_original: str) -> tuple[Projeto, Midia, Item]:
        """Copia o clipe para o projeto, analisa e coloca no fim da linha do tempo já com o corte sugerido."""
        self.abrir(projeto_id)
        extensao = Path(nome_original).suffix.lower()
        if extensao not in config.EXTENSOES_VIDEO:
            aceitos = ", ".join(sorted(e.lstrip(".").upper() for e in config.EXTENSOES_VIDEO))
            raise ErroImportacao(f"“{nome_original}” não é um vídeo aceito. Formatos aceitos: {aceitos}.")

        midia_id = novo_id()
        destino = self.pasta_midia(projeto_id) / f"{midia_id}{extensao}"
        tira, onda = self.arquivo_tira(projeto_id, midia_id), self.arquivo_onda(projeto_id, midia_id)
        destino.parent.mkdir(parents=True, exist_ok=True)
        self.pasta_cache(projeto_id).mkdir(parents=True, exist_ok=True)
        try:
            with open(destino, "wb") as saida:
                shutil.copyfileobj(origem, saida, length=1024 * 1024)
            try:
                analise = analisar(destino)
            except ErroMidia as erro:
                raise ErroImportacao(f"“{nome_original}”: {erro}") from erro
            info = analise.info
            quadros = gerar_tira(destino, tira, info.duracao)
            onda.write_text(json.dumps(analise.onda), encoding="utf-8")

            midia = Midia(
                id=midia_id, nome=Path(nome_original).name, arquivo=destino.name, duracao=info.duracao,
                largura=info.largura, altura=info.altura, fps=info.fps, codec=info.codec, tem_audio=info.tem_audio,
                fala_inicio=analise.fala[0] if analise.fala else None,
                fala_fim=analise.fala[1] if analise.fala else None,
                tira_quadros=quadros, avisos=[Aviso(**a) for a in analise.avisos], importada_em=agora(),
            )
            entrada, saida = midia.corte_sugerido()
            item = Item(id=novo_id(), midia_id=midia_id, entrada=entrada, saida=saida)
            with self._trava:
                projeto = self.abrir(projeto_id)
                projeto.midias.append(midia)
                projeto.linha.append(item)
                return self.salvar(projeto), midia, item
        except BaseException:
            apagar_arquivos(destino, tira, onda)  # fora do projeto, a cópia só ocuparia espaço
            raise

    def remover_midia(self, projeto_id: str, midia_id: str) -> Projeto:
        with self._trava:
            projeto = self.abrir(projeto_id)
            midia = projeto.midia(midia_id)
            if midia is None:
                raise ProjetoNaoEncontrado(midia_id)
            projeto.midias = [m for m in projeto.midias if m.id != midia_id]
            projeto.linha = [i for i in projeto.linha if i.midia_id != midia_id]
            projeto.legendas.pop(midia_id, None)
            self.salvar(projeto)
        apagar_arquivos(self.arquivo_midia(projeto_id, midia), self.arquivo_tira(projeto_id, midia_id),
                        self.arquivo_onda(projeto_id, midia_id))
        return projeto
