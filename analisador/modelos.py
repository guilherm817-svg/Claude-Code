"""Formatos da análise gerada pelo Claude (também usados como schema de saída estruturada)."""

from pydantic import BaseModel, Field


class Conceito(BaseModel):
    termo: str
    explicacao: str


class Capitulo(BaseModel):
    inicio: str = Field(description="Minutagem HH:MM:SS em que o assunto começa")
    titulo: str
    resumo: str


class VisaoGeral(BaseModel):
    titulo_sugerido: str
    resumo: str
    pontos_chave: list[str]
    conceitos: list[Conceito]
    acoes_praticas: list[str]
    capitulos: list[Capitulo]


class Flashcard(BaseModel):
    pergunta: str
    resposta: str
    minuto: str = Field(description="Minutagem HH:MM:SS onde o assunto aparece na aula")


class QuestaoQuiz(BaseModel):
    pergunta: str
    alternativas: list[str]
    correta: int = Field(description="Índice (começando em 0) da alternativa correta")
    explicacao: str
    minuto: str = Field(description="Minutagem HH:MM:SS onde o assunto aparece na aula")


class MaterialEstudo(BaseModel):
    flashcards: list[Flashcard]
    quiz: list[QuestaoQuiz]


class Uso(BaseModel):
    """Tokens consumidos na API, somados entre as chamadas de uma análise."""

    entrada: int = 0
    entrada_cache_gravada: int = 0
    entrada_cache_lida: int = 0
    saida: int = 0


class Analise(BaseModel):
    visao_geral: VisaoGeral
    estudo: MaterialEstudo
    modelo: str
    gerada_em: str
    uso: Uso = Uso()
