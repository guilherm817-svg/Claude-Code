"""Corretor de prompts: confere com o Claude um prompt de vídeo (Flow/Veo, Kling, Seedance) ou de imagem e devolve
os problemas, o porquê de cada um e o prompt corrigido em blocos que cabem no clipe.

As regras ficam em regras_prompts.md e vão no prompt de sistema com cache_control: o texto é o mesmo em toda
correção, então da segunda em diante ele sai do cache por uma fração do preço. Depois da resposta, o próprio
Estúdio confere cada bloco (tamanho e tempo da fala) em vez de confiar só na conta do modelo.
"""

from __future__ import annotations

import re
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

import anthropic
import httpx2
import pydantic
from pydantic import BaseModel, Field, field_validator, model_validator

from . import config

# Se um classificador de segurança recusar o pedido, a API refaz no modelo recomendado.
BETA_FALLBACK = "server-side-fallback-2026-07-01"
REGRAS = Path(__file__).with_name("regras_prompts.md")

LIMITE_PROMPT = 20_000
LIMITE_PEDIDO_ORIGINAL = 5_000
LIMITE_CARACTERES = 2500  # por bloco: acima disso alguns geradores cortam o texto ou recusam o prompt
FOLGA_DA_FALA = 0.9  # s de silêncio somados à fala: ~0,5 antes da primeira palavra e ~0,4 depois da última
PAUSA_NA_TROCA = 0.5  # s a mais cada vez que outra pessoa começa a falar
SOBRA_QUE_REPETE = 3.5  # s sem fala a partir dos quais o gerador costuma repetir a fala para encher o clipe

# Nome na tela, duração padrão, teto e durações oferecidas na tela (em segundos).
GERADORES = {
    "veo": ("Google Flow (Veo 3.1)", 8, 8, [4, 6, 8]),
    "kling": ("Kling", 10, 10, [5, 10]),
    "seedance": ("Seedance", 8, 15, list(range(4, 16))),  # chega a 15 s, mas boca e mãos artefatam mais acima de 8
    "imagem": ("Imagem (foto de referência)", None, None, []),
}
CADENCIAS = {"natural": ("natural", 2.5), "1.1x": ("1.1x", 2.75), "1.25x": ("1.25x", 3.1)}
IDIOMAS = {"auto": "Detectar pelo prompt", "pt-BR": "Português do Brasil", "en": "Inglês", "es": "Espanhol"}
OBJETIVOS = {"reels": "Reels orgânico, para viralizar", "anuncio": "Anúncio pago (Meta Ads)"}

ETAPAS = [
    "Enviando o prompt para o Claude",
    "Lendo o prompt e conferindo as regras",
    "Anotando os problemas e o porquê de cada um",
    "Escrevendo o prompt corrigido",
    "Conferindo o tempo e o tamanho de cada bloco",
]

MENSAGENS_DE_CAMPO = {
    "prompt": f"Cole o prompt que você quer corrigir (até {LIMITE_PROMPT:_} caracteres).".replace("_", "."),
    "gerador": "Escolha o gerador: Veo, Kling, Seedance ou imagem.",
    "duracao_clipe": "A duração do clipe precisa ser um número inteiro de segundos.",
    "cadencia": "Escolha o ritmo da fala: natural, 1.1x ou 1.25x.",
    "idioma_fala": "Escolha o idioma da fala: automático, português, inglês ou espanhol.",
    "objetivo": "Escolha o objetivo: Reels ou anúncio.",
    "pedido_original": f"O que você pediu para a IA passou de {LIMITE_PEDIDO_ORIGINAL:_} caracteres. "
                       "Resuma em poucas frases.".replace("_", "."),
    "remover_itens": "A lista de itens para tirar veio num formato inesperado.",
}


class ErroCorretor(Exception):
    """Erro com mensagem pronta para mostrar ao usuário. `codigo` diz à tela o que oferecer (ex.: trocar a chave)."""

    def __init__(self, mensagem: str, codigo: str = "erro"):
        super().__init__(mensagem)
        self.codigo = codigo


class Cancelamento:
    """Deixa outra thread interromper uma correção em andamento (o usuário clicou em Cancelar ou fechou a aba).

    Derruba a conexão com a API na hora: assim o Claude para de gerar a resposta, e de cobrar por ela.
    """

    def __init__(self) -> None:
        self._solicitado = threading.Event()
        self._trava = threading.Lock()
        self._resposta: httpx2.Response | None = None

    @property
    def solicitado(self) -> bool:
        return self._solicitado.is_set()

    def vigiar(self, resposta: httpx2.Response) -> None:
        with self._trava:
            self._resposta = resposta
            if not self.solicitado:
                return
        _derrubar(resposta)

    def cancelar(self) -> None:
        with self._trava:
            self._solicitado.set()
            resposta = self._resposta
        if resposta is not None:
            _derrubar(resposta)


def _derrubar(resposta: httpx2.Response) -> None:
    # Fechar a resposta de outra thread não acorda quem espera o próximo pedaço do stream, e enquanto raciocina o
    # Claude passa dezenas de segundos sem mandar nada. Desligar o socket acorda essa espera e encerra a conexão.
    rede = resposta.extensions.get("network_stream")
    conexao = rede.get_extra_info("socket") if rede is not None else None
    if conexao is None:
        return
    try:
        conexao.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # a conexão já tinha caído


# Entrada


class PedidoCorrecao(BaseModel):
    prompt: str = Field(max_length=LIMITE_PROMPT)
    gerador: Literal["veo", "kling", "seedance", "imagem"] = "veo"
    duracao_clipe: int | None = None
    cadencia: Literal["natural", "1.1x", "1.25x"] = "natural"
    idioma_fala: Literal["auto", "pt-BR", "en", "es"] = "auto"
    objetivo: Literal["reels", "anuncio"] = "reels"
    pedido_original: str = Field(default="", max_length=LIMITE_PEDIDO_ORIGINAL)
    remover_itens: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("prompt", "pedido_original")
    @classmethod
    def _aparar(cls, valor: str) -> str:
        return valor.strip()

    @model_validator(mode="after")
    def _conferir(self):
        if not self.prompt:
            raise ValueError("Cole o prompt que você quer corrigir.")
        nome, padrao, teto, _ = GERADORES[self.gerador]
        if teto is None:
            self.duracao_clipe = None
        elif self.duracao_clipe is None:
            self.duracao_clipe = padrao
        elif not 2 <= self.duracao_clipe <= teto:
            raise ValueError(f"O {nome} gera clipes de até {teto} segundos. Escolha uma duração entre 2 e {teto} s.")
        self.remover_itens = [item.strip()[:200] for item in self.remover_itens if item.strip()]
        return self


def ler_pedido(dados) -> PedidoCorrecao:
    """Valida o pedido da tela; os erros saem em português, sem repetir o que foi enviado."""
    if not isinstance(dados, dict):
        raise ErroCorretor("Pedido inválido.")
    try:
        return PedidoCorrecao.model_validate(dados)
    except pydantic.ValidationError as e:
        erro = e.errors()[0]
        if erro["type"] == "value_error":
            raise ErroCorretor(str(erro["ctx"]["error"])) from None
        campo = erro["loc"][0] if erro["loc"] else ""
        raise ErroCorretor(MENSAGENS_DE_CAMPO.get(campo, "Pedido inválido.")) from None


# Saída do Claude (também é o schema da saída estruturada)


class Problema(BaseModel):
    gravidade: Literal["alta", "media", "baixa"]
    categoria: Literal[
        "configuracao", "tempo_da_fala", "escrita_da_fala", "vozes", "identidade", "texto_na_tela",
        "maos_e_objetos", "camera_e_movimento", "cenario", "formato_do_prompt", "seguranca", "outro",
    ]
    trecho_original: str = Field(description="Trecho copiado literalmente do prompt do usuário; vazio se é algo que falta")
    problema: str = Field(description="O que está errado, numa frase simples")
    por_que_da_bug: str = Field(description="Por que isso estraga o vídeo ou atrapalha, em português simples")
    o_que_mudou: str = Field(description="O que foi feito no prompt corrigido")


class Fala(BaseModel):
    quem: str = Field(description="Quem fala, em português (ex.: Mulher, Homem); vazio se só uma pessoa fala no vídeo")
    texto: str = Field(description="As palavras exatamente como estão entre as aspas no prompt do bloco")


class Bloco(BaseModel):
    titulo: str = Field(description="Bloco N — o que acontece (curto, em português, sem a duração)")
    falas: list[Fala] = Field(description="Falas do bloco, na ordem; vazio se ninguém fala")
    duracao_estimada_s: float = Field(description="Duração total que o bloco precisa: fala, folgas e ações sem fala")
    prompt: str = Field(description="Prompt completo do bloco, pronto para colar no gerador")


class ItemAcrescentado(BaseModel):
    item: str
    risco: str


class LegendaNoEstudio(BaseModel):
    """O estilo pedido no prompt, traduzido para os ajustes das legendas do Estúdio."""
    preset: Literal["destaque", "uma_palavra", "classica", "caixa"]
    tamanho: Literal["P", "M", "G"]
    posicao: Literal["alto", "centro", "baixo"]
    maiusculas: bool


class RespostaCorretor(BaseModel):
    recusado: bool = Field(description="Verdadeiro só se o pedido inteiro for perigoso")
    motivo_recusa: str = Field(description="Por que recusou, em português simples; vazio se não recusou")
    resumo: str
    problemas: list[Problema] = Field(description="Do mais grave para o mais leve")
    blocos: list[Bloco]
    acrescentados_pela_ia: list[ItemAcrescentado] = Field(
        description="O que apareceu no prompt sem o usuário pedir; vazio se ele não contou o que pediu")
    alertas_de_alcance: list[str]
    estilo_de_legenda: str = Field(description="Estilo de legenda para fazer no Estúdio; vazio se o prompt não pedia")
    legenda_no_estudio: LegendaNoEstudio | None = Field(
        description="O mesmo estilo nos ajustes das legendas do Estúdio; null se o prompt não pedia legenda")


# O que a tela recebe: a resposta do Claude mais a conferência feita aqui


class Aviso(BaseModel):
    tipo: Literal["alerta", "dica"]
    texto: str


class BlocoConferido(Bloco):
    caracteres: int
    palavras: int
    duracao_fala_s: float = Field(description="Palavras ÷ cadência + folgas, contado pelo Estúdio")
    avisos: list[Aviso]


class Correcao(RespostaCorretor):
    blocos: list[BlocoConferido]
    gerador: str
    duracao_clipe: int | None
    cadencia: str
    modelo: str
    gerada_em: str


# Conferência dos blocos


def contar_palavras(texto: str) -> int:
    return len(re.findall(r"\w+(?:[-'’]\w+)*", texto))


def palavras_que_cabem(duracao_clipe: float, cadencia: str) -> int:
    return max(0, int((duracao_clipe - FOLGA_DA_FALA) * CADENCIAS[cadencia][1]))


def _segundos(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",") + " s"


def _milhar(valor: int) -> str:
    return f"{valor:_}".replace("_", ".")


def _normalizar(texto: str) -> str:
    texto = texto.replace("’", "'").replace("“", '"').replace("”", '"').strip().strip("\"'").strip()
    return re.sub(r"\s+", " ", texto).lower()


def conferir_bloco(bloco: Bloco, pedido: PedidoCorrecao) -> BlocoConferido:
    """Mede o bloco e avisa se ele passa do limite de caracteres ou se a fala não cabe no clipe."""
    caracteres = len(bloco.prompt)
    avisos = []
    if caracteres > LIMITE_CARACTERES:
        avisos.append(Aviso(tipo="alerta", texto=(
            f"Este bloco tem {_milhar(caracteres)} caracteres e o limite é {_milhar(LIMITE_CARACTERES)}: alguns "
            "geradores cortam o fim do texto ou recusam o prompt. Corrija de novo ou encurte as descrições repetidas.")))

    palavras, duracao = 0, 0.0
    falas = [f for f in bloco.falas if f.texto.strip()]
    if pedido.duracao_clipe and falas:
        nome_ritmo, cadencia = CADENCIAS[pedido.cadencia]
        clipe = pedido.duracao_clipe
        palavras = sum(contar_palavras(f.texto) for f in falas)
        trocas = sum(1 for a, b in zip(falas, falas[1:]) if a.quem.strip().lower() != b.quem.strip().lower())
        duracao = round(palavras / cadencia + FOLGA_DA_FALA + PAUSA_NA_TROCA * trocas, 1)
        if duracao > clipe:
            avisos.append(Aviso(tipo="alerta", texto=(
                f"A fala tem {palavras} palavras e leva cerca de {_segundos(duracao)} no ritmo {nome_ritmo}, mais que "
                f"os {clipe} s do clipe: o fim pode sair cortado ou corrido. Num clipe de {clipe} s cabem cerca de "
                f"{palavras_que_cabem(clipe, pedido.cadencia)} palavras; divida a fala em dois blocos.")))
        elif clipe - duracao >= SOBRA_QUE_REPETE:
            avisos.append(Aviso(tipo="dica", texto=(
                f"Sobram cerca de {_segundos(clipe - duracao)} sem fala neste clipe de {clipe} s. Confira se o prompt "
                "diz o que acontece nesse tempo (ação sem fala); senão o gerador pode repetir a fala para preencher.")))
        if any(_normalizar(f.texto) not in _normalizar(bloco.prompt) for f in falas):
            avisos.append(Aviso(tipo="dica", texto=(
                "A fala mostrada aqui não aparece igual dentro do prompt. Confira o texto entre aspas antes de gerar.")))

    return BlocoConferido(**bloco.model_dump(), caracteres=caracteres, palavras=palavras, duracao_fala_s=duracao,
                          avisos=avisos)


# Pedido ao Claude


def montar_system() -> list[dict]:
    return [{"type": "text", "text": REGRAS.read_text(encoding="utf-8"), "cache_control": {"type": "ephemeral"}}]


def montar_pedido(pedido: PedidoCorrecao) -> str:
    nome, _, teto, _ = GERADORES[pedido.gerador]
    linhas = [f"Gerador: {nome} ({pedido.gerador})."]
    if pedido.duracao_clipe:
        nome_ritmo, cadencia = CADENCIAS[pedido.cadencia]
        linhas += [
            f"Duração de cada clipe: {pedido.duracao_clipe} s (o gerador faz até {teto} s).",
            f"Ritmo da fala: {nome_ritmo}, cerca de {str(cadencia).replace('.', ',')} palavras por segundo. Cabem "
            f"cerca de {palavras_que_cabem(pedido.duracao_clipe, pedido.cadencia)} palavras de fala por clipe, já "
            "contando a folga.",
        ]
    else:
        linhas.append("É um prompt de imagem: sem fala e sem duração.")
    linhas += [f"Idioma da fala: {IDIOMAS[pedido.idioma_fala]}.", f"Objetivo: {OBJETIVOS[pedido.objetivo]}."]

    partes = ["<configuracao>\n" + "\n".join(linhas) + "\n</configuracao>"]
    if pedido.pedido_original:
        partes.append(f"<pedido_original>\n{pedido.pedido_original}\n</pedido_original>")
    if pedido.remover_itens:
        itens = "\n".join(f"- {item}" for item in pedido.remover_itens)
        partes.append(f"<itens_para_tirar>\n{itens}\n</itens_para_tirar>")
    partes.append(f"<prompt_do_usuario>\n{pedido.prompt}\n</prompt_do_usuario>")
    partes.append("Corrija o prompt do usuário seguindo as regras.")
    return "\n\n".join(partes)


@contextmanager
def _erros_amigaveis():
    modelo = config.MODELO_CLAUDE
    try:
        yield
    except anthropic.AuthenticationError as e:
        raise ErroCorretor("Chave da API do Claude inválida. Confira se você copiou a chave inteira ou crie outra em "
                           "console.anthropic.com.", "chave") from e
    except anthropic.PermissionDeniedError as e:
        raise ErroCorretor(f"A chave não tem permissão para usar o modelo {modelo}.", "chave") from e
    except anthropic.NotFoundError as e:
        raise ErroCorretor(f"Modelo {modelo} não encontrado. Confira ESTUDIO_MODELO_CLAUDE no arquivo .env.") from e
    except anthropic.RateLimitError as e:
        raise ErroCorretor("Limite de uso da API atingido. Espere alguns minutos e tente de novo.") from e
    except anthropic.BadRequestError as e:
        texto = str(e.message)
        if "credit balance" in texto.lower():
            raise ErroCorretor("Sem créditos na conta da API. Adicione créditos em console.anthropic.com, em Billing.",
                               "creditos") from e
        raise ErroCorretor(f"A API recusou o pedido: {texto}") from e
    except anthropic.APIStatusError as e:
        # Um erro no meio da resposta chega com status 200; o tipo dele vem no corpo.
        tipo = (e.body.get("error") or {}).get("type") if isinstance(e.body, dict) else None
        if e.status_code == 529 or tipo == "overloaded_error":
            raise ErroCorretor("Os servidores do Claude estão sobrecarregados agora. Tente de novo em alguns minutos.") from e
        if e.status_code < 400:
            raise ErroCorretor("A resposta do Claude parou no meio. Tente de novo.") from e
        raise ErroCorretor(f"Erro no servidor da API ({e.status_code}). Tente de novo em instantes.") from e
    except anthropic.APIConnectionError as e:
        raise ErroCorretor("Sem conexão com a API do Claude. Verifique sua internet e tente de novo.", "conexao") from e
    except httpx2.TransportError as e:
        # Uma queda depois de a resposta começar chega direto do httpx2, sem passar pelos erros do SDK.
        raise ErroCorretor("A conexão com a API do Claude caiu no meio da resposta. Verifique sua internet e tente "
                           "de novo.", "conexao") from e


def _cliente() -> anthropic.Anthropic:
    # Criado a cada uso para pegar a chave mesmo se ela foi salva depois de o Estúdio abrir.
    return anthropic.Anthropic(max_retries=3)


def _etapa(numero: int) -> dict:
    return {"etapa": numero, "de": len(ETAPAS), "texto": ETAPAS[numero - 1]}


def _cancelada() -> ErroCorretor:
    return ErroCorretor("Correção cancelada.", "cancelada")


@contextmanager
def _parar_se_cancelado(cancelamento: Cancelamento):
    # Derrubar a conexão faz o stream falhar no meio; para quem cancelou, isso é o cancelamento, não um erro.
    try:
        yield
    except ErroCorretor:
        raise
    except Exception as e:
        if cancelamento.solicitado:
            raise _cancelada() from e
        raise


def acompanhar(pedido: PedidoCorrecao, cancelamento: Cancelamento | None = None) -> Iterator[dict]:
    """Corrige o prompt avisando cada etapa ({"etapa", "de", "texto"}); no fim, {"resultado": Correcao}.

    As etapas saem do próprio streaming: o raciocínio começa, o JSON chega aos problemas e depois aos blocos.
    Com `cancelamento`, outra thread pode interromper a correção; aí sai ErroCorretor com o código "cancelada".
    """
    cancelamento = cancelamento or Cancelamento()
    atual = 1
    yield _etapa(atual)
    texto = ""
    with _erros_amigaveis(), _parar_se_cancelado(cancelamento):
        with _cliente().beta.messages.stream(
            model=config.MODELO_CLAUDE,
            max_tokens=64000,
            system=montar_system(),
            messages=[{"role": "user", "content": montar_pedido(pedido)}],
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": anthropic.transform_schema(RespostaCorretor)},
            },
            betas=[BETA_FALLBACK],
            fallbacks="default",
        ) as stream:
            cancelamento.vigiar(stream.response)
            for evento in stream:
                if cancelamento.solicitado:
                    raise _cancelada()
                proxima = atual
                if evento.type == "message_start":
                    proxima = 2
                elif evento.type == "content_block_start" and evento.content_block.type == "text":
                    proxima = 3
                elif evento.type == "content_block_delta" and evento.delta.type == "text_delta":
                    texto += evento.delta.text
                    if '"blocos"' in texto[-(len(evento.delta.text) + 10):]:
                        proxima = 4
                if proxima > atual:
                    atual = proxima
                    yield _etapa(atual)
            resposta = stream.get_final_message()

    # A validação fica para depois de olhar o stop_reason: numa recusa ou num corte por tamanho, o JSON chega
    # incompleto e não deve ser validado.
    if resposta.stop_reason == "refusal":
        raise ErroCorretor("O Claude não quis corrigir este prompt. Reescreva o pedido com outras palavras.")
    if resposta.stop_reason == "max_tokens":
        raise ErroCorretor("A resposta ficou longa demais e foi cortada. Corrija o prompt em partes menores.")
    # Se o modelo recusar no meio e o de reserva assumir, o texto parcial fica num bloco, vem o bloco "fallback" e
    # a continuação chega em outro bloco de texto: o JSON é a junção de todos eles.
    textos = [b.text for b in resposta.content if b.type == "text"]
    if not textos:
        raise ErroCorretor("A resposta do Claude veio vazia. Tente de novo.")
    try:
        saida = RespostaCorretor.model_validate_json("".join(textos))
    except pydantic.ValidationError as e:
        raise ErroCorretor("A resposta do Claude veio num formato inesperado. Tente de novo.") from e

    yield _etapa(len(ETAPAS))
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    blocos = [] if saida.recusado else [conferir_bloco(b, pedido) for b in saida.blocos]
    correcao = Correcao(
        **saida.model_dump(exclude={"blocos", "problemas"}),
        problemas=sorted(saida.problemas, key=lambda p: ordem[p.gravidade]),
        blocos=blocos,
        gerador=pedido.gerador,
        duracao_clipe=pedido.duracao_clipe,
        cadencia=pedido.cadencia,
        modelo=resposta.model or config.MODELO_CLAUDE,
        gerada_em=datetime.now().isoformat(timespec="seconds"),
    )
    yield {"resultado": correcao}


def corrigir(pedido: PedidoCorrecao) -> Correcao:
    for evento in acompanhar(pedido):
        if "resultado" in evento:
            return evento["resultado"]
    raise ErroCorretor("A correção terminou sem resultado. Tente de novo.")


def opcoes() -> dict:
    """O que a tela precisa para montar o formulário."""
    return {
        "geradores": [{"id": chave, "nome": nome, "padrao": padrao, "teto": teto, "duracoes": duracoes}
                      for chave, (nome, padrao, teto, duracoes) in GERADORES.items()],
        "cadencias": [{"id": chave, "nome": nome, "palavras_por_segundo": pps} for chave, (nome, pps) in CADENCIAS.items()],
        "idiomas": [{"id": chave, "nome": nome} for chave, nome in IDIOMAS.items()],
        "objetivos": [{"id": chave, "nome": nome} for chave, nome in OBJETIVOS.items()],
        "etapas": ETAPAS,
        "folga": FOLGA_DA_FALA,
        "limite_caracteres": LIMITE_CARACTERES,
        "limite_prompt": LIMITE_PROMPT,
        "limite_pedido_original": LIMITE_PEDIDO_ORIGINAL,
    }
