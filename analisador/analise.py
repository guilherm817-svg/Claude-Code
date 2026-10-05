"""Análise da aula com o Claude: resumo, capítulos, flashcards, quiz e chat.

A transcrição inteira vai no prompt de sistema com cache_control. Assim, as duas chamadas da
análise e cada pergunta do chat reaproveitam o mesmo prefixo em cache, e a leitura da aula
sai por uma fração do preço normal depois da primeira chamada.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

import anthropic
import pydantic

from . import config
from .biblioteca import Aula, formatar_tempo, transcricao_com_minutagem
from .modelos import Analise, MaterialEstudo, Uso, VisaoGeral

# Se um classificador de segurança recusar o pedido, a API refaz no modelo recomendado.
BETA_FALLBACK = "server-side-fallback-2026-07-01"

INSTRUCOES = """\
Você é um assistente de estudos. O aluno comprou um curso e está estudando uma aula a partir \
da transcrição dela, que está abaixo.

Sobre a transcrição:
- Foi gerada automaticamente a partir do áudio (Whisper), então pode ter palavras trocadas, nomes \
próprios escritos errado e pontuação imperfeita. Interprete pelo contexto e use a forma correta \
dos termos; só comente um erro de transcrição se ele mudar o sentido.
- Cada bloco começa com a minutagem [HH:MM:SS] em que aquele trecho começa na aula.

Como trabalhar:
- Baseie-se no que o professor realmente disse. Quando acrescentar algo que não está na aula \
(contexto, ressalva, correção de um dado), deixe claro que é um complemento seu.
- Ao se referir a um trecho, indique a minutagem no formato [HH:MM:SS], usando as marcações da \
transcrição, para o aluno ir direto ao ponto no vídeo.
- Se o aluno perguntar algo que a aula não aborda, diga isso antes de responder com conhecimento geral.
- Escreva em português do Brasil, de forma clara e direta."""

PEDIDO_VISAO_GERAL = """\
Analise a aula inteira e produza a visão geral para estudo:

- titulo_sugerido: título curto e descritivo do assunto da aula.
- resumo: 2 a 4 parágrafos que expliquem o conteúdo e o raciocínio da aula, não apenas listem \
temas. Quem não assistiu deve entender a ideia central.
- pontos_chave: as ideias mais importantes, cada uma numa frase completa e específica (evite \
frases genéricas como "a importância do planejamento").
- conceitos: termos, ferramentas ou métodos que a aula apresenta, explicados no sentido em que o \
professor os usa.
- acoes_praticas: o que o aluno deve fazer ou aplicar depois da aula. Lista vazia se a aula não \
tiver orientações práticas.
- capitulos: índice da aula em ordem cronológica, do início ao fim. Abra um capítulo a cada \
mudança real de assunto (em geral a cada 3 a 15 minutos). Em inicio, use a minutagem HH:MM:SS \
(sem colchetes) do bloco da transcrição em que o assunto começa."""

PEDIDO_ESTUDO = """\
Crie material de revisão para o aluno fixar o conteúdo desta aula de {duracao}:

- flashcards: cerca de {n_cards} perguntas de recordação ativa sobre o que a aula ensina \
(conceitos, passos, números, critérios, exemplos importantes), distribuídas pela aula inteira. \
Respostas curtas (1 a 3 frases) e verificáveis na aula. Em minuto, a minutagem HH:MM:SS onde o \
assunto aparece.
- quiz: {n_quiz} questões de múltipla escolha com 4 alternativas, que testem compreensão e \
aplicação, não só memorização literal. Alternativas erradas plausíveis. Em correta, o índice \
(0 a 3) da alternativa certa; varie a posição dela entre as questões. Em explicacao, por que a \
correta está certa segundo a aula. Em minuto, a minutagem HH:MM:SS do assunto.

Deixe de fora propaganda, avisos sobre o curso e conversa fora do assunto."""


class ErroAnalise(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


def montar_system(aula: Aula) -> list[dict]:
    duracao = formatar_tempo(aula.duracao or 0)
    transcricao = transcricao_com_minutagem(aula.segmentos())
    bloco_aula = f'<aula arquivo="{aula.origem.name}" duracao="{duracao}">\n{transcricao}\n</aula>'
    return [
        {"type": "text", "text": INSTRUCOES},
        {"type": "text", "text": bloco_aula, "cache_control": {"type": "ephemeral"}},
    ]


@contextmanager
def _erros_amigaveis():
    try:
        yield
    except anthropic.AuthenticationError as e:
        raise ErroAnalise("Chave da API do Claude inválida. Confira a chave na barra lateral.") from e
    except anthropic.PermissionDeniedError as e:
        raise ErroAnalise(f"A chave não tem permissão para usar o modelo {config.MODELO_CLAUDE}.") from e
    except anthropic.NotFoundError as e:
        raise ErroAnalise(f"Modelo {config.MODELO_CLAUDE} não encontrado. Confira ANALISADOR_MODELO_CLAUDE.") from e
    except anthropic.RateLimitError as e:
        raise ErroAnalise("Limite de uso da API atingido. Espere alguns minutos e tente de novo.") from e
    except anthropic.BadRequestError as e:
        texto = str(e.message)
        if "credit balance" in texto.lower():
            raise ErroAnalise("Sem créditos na conta da API. Adicione créditos em console.anthropic.com.") from e
        raise ErroAnalise(f"A API recusou o pedido: {texto}") from e
    except anthropic.APIStatusError as e:
        raise ErroAnalise(f"Erro no servidor da API ({e.status_code}). Tente de novo em instantes.") from e
    except anthropic.APIConnectionError as e:
        raise ErroAnalise("Sem conexão com a API do Claude. Verifique sua internet.") from e


def _cliente() -> anthropic.Anthropic:
    # Criado a cada uso para pegar a chave mesmo se ela foi configurada depois de o app abrir.
    return anthropic.Anthropic(max_retries=4)


def _somar_uso(uso: Uso, resposta) -> None:
    u = resposta.usage
    uso.entrada += u.input_tokens or 0
    uso.entrada_cache_gravada += u.cache_creation_input_tokens or 0
    uso.entrada_cache_lida += u.cache_read_input_tokens or 0
    uso.saida += u.output_tokens or 0


def _gerar(cliente, system: list[dict], pedido: str, formato: type[pydantic.BaseModel], uso: Uso):
    # O schema vai em output_config e a validação fica para depois de olhar o stop_reason:
    # numa recusa ou num corte por tamanho, o JSON chega incompleto e não deve ser validado.
    with cliente.beta.messages.stream(
        model=config.MODELO_CLAUDE,
        max_tokens=64000,
        system=system,
        messages=[{"role": "user", "content": pedido}],
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": anthropic.transform_schema(formato)},
        },
        betas=[BETA_FALLBACK],
        fallbacks="default",
    ) as stream:
        resposta = stream.get_final_message()
    _somar_uso(uso, resposta)
    if resposta.stop_reason == "refusal":
        raise ErroAnalise("O Claude recusou analisar esta aula.")
    if resposta.stop_reason == "max_tokens":
        raise ErroAnalise("A resposta ficou longa demais e foi cortada. Tente gerar de novo.")
    textos = [b.text for b in resposta.content if b.type == "text"]
    if not textos:
        raise ErroAnalise("A resposta do Claude veio vazia. Tente gerar de novo.")
    try:
        return formato.model_validate_json(textos[-1])
    except pydantic.ValidationError as e:
        raise ErroAnalise("A resposta do Claude veio num formato inesperado. Tente gerar de novo.") from e


def analisar(aula: Aula, ao_progredir: Callable[[float, str], None] | None = None) -> Analise:
    avisar = ao_progredir or (lambda fracao, mensagem: None)
    cliente = _cliente()
    system = montar_system(aula)
    uso = Uso()
    minutos = (aula.duracao or 0) / 60

    with _erros_amigaveis():
        avisar(0.1, "Gerando resumo e capítulos…")
        visao_geral = _gerar(cliente, system, PEDIDO_VISAO_GERAL, VisaoGeral, uso)

        avisar(0.55, "Gerando flashcards e quiz…")
        pedido_estudo = PEDIDO_ESTUDO.format(
            duracao=formatar_tempo(aula.duracao or 0),
            n_cards=int(min(50, max(10, minutos / 3))),
            n_quiz=int(min(20, max(6, minutos / 6))),
        )
        estudo = _gerar(cliente, system, pedido_estudo, MaterialEstudo, uso)

    return Analise(
        visao_geral=visao_geral,
        estudo=estudo,
        modelo=config.MODELO_CLAUDE,
        gerada_em=datetime.now().isoformat(timespec="seconds"),
        uso=uso,
    )


def responder(aula: Aula, historico: list[dict], pergunta: str) -> Iterator[str]:
    """Responde no chat em streaming. `historico` traz mensagens {"role", "content": texto}.

    O histórico guarda só o texto das respostas e é enviado sempre igual, só crescendo no fim:
    o prefixo continua em cache e nenhum bloco de raciocínio antigo precisa ser reenviado.
    """
    mensagens = [*historico, {"role": "user", "content": pergunta}]
    with _erros_amigaveis():
        with _cliente().beta.messages.stream(
            model=config.MODELO_CLAUDE,
            max_tokens=16000,
            system=montar_system(aula),
            messages=mensagens,
            cache_control={"type": "ephemeral"},  # também guarda a conversa em cache
            output_config={"effort": "medium"},
            betas=[BETA_FALLBACK],
            fallbacks="default",
        ) as stream:
            yield from stream.text_stream
            resposta = stream.get_final_message()
    if resposta.stop_reason == "refusal":
        yield "\n\n_O Claude não respondeu a esta pergunta._"
    elif resposta.stop_reason == "max_tokens":
        yield "\n\n_(resposta cortada por ser longa demais)_"
