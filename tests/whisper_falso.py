"""Um Whisper de mentira para os testes (o modelo de verdade não é baixado aqui): "ouve" sempre a mesma frase,
espalhada pelo trecho com fala do clipe, no formato de resposta do faster-whisper."""

from types import SimpleNamespace

from estudio.midia import TAXA_ANALISE, detectar_fala


class WhisperFalso:
    def __init__(self, frase: str = "Isso muda tudo agora", idioma: str = "pt"):
        self.frase = frase.split()
        self.idioma = idioma
        self.pedidos: list[dict] = []

    def transcribe(self, audio, language=None, **opcoes):
        self.pedidos.append({"idioma": language, "amostras": len(audio), **opcoes})
        inicio, fim = detectar_fala(audio) or (0.0, len(audio) / TAXA_ANALISE)
        passo = (fim - inicio) / len(self.frase)
        palavras = [SimpleNamespace(word=f" {texto}", start=inicio + i * passo, end=inicio + (i + 0.9) * passo)
                    for i, texto in enumerate(self.frase)]
        return iter([SimpleNamespace(words=palavras)]), SimpleNamespace(language=language or self.idioma)
