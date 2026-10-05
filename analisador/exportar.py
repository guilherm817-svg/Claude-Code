"""Exportação da aula para Markdown, Anki, texto e legenda .srt."""

from __future__ import annotations

from .biblioteca import Aula, Segmento, agrupar_em_blocos, formatar_tempo
from .modelos import Analise

LETRAS = "ABCDEFGH"


def markdown(aula: Aula, analise: Analise) -> str:
    vg, estudo = analise.visao_geral, analise.estudo
    linhas = [f"# {aula.titulo}", ""]
    linhas += [f"*{vg.titulo_sugerido}* · {aula.curso} · duração {formatar_tempo(aula.duracao or 0)}", ""]
    linhas += ["## Resumo", "", vg.resumo, ""]
    linhas += ["## Pontos-chave", ""] + [f"- {p}" for p in vg.pontos_chave] + [""]
    if vg.conceitos:
        linhas += ["## Conceitos", ""] + [f"- **{c.termo}**: {c.explicacao}" for c in vg.conceitos] + [""]
    if vg.acoes_praticas:
        linhas += ["## Para aplicar", ""] + [f"- [ ] {a}" for a in vg.acoes_praticas] + [""]
    linhas += ["## Capítulos", ""]
    for c in vg.capitulos:
        linhas += [f"- **{c.inicio}** {c.titulo}: {c.resumo}"]
    linhas += ["", "## Flashcards", ""]
    for i, f in enumerate(estudo.flashcards, 1):
        linhas += [f"{i}. **{f.pergunta}**", f"   {f.resposta} *({f.minuto})*"]
    linhas += ["", "## Quiz", ""]
    for i, q in enumerate(estudo.quiz, 1):
        linhas += [f"{i}. {q.pergunta}"] + [f"   - {LETRAS[j]}) {alt}" for j, alt in enumerate(q.alternativas)]
    linhas += ["", "### Gabarito", ""]
    for i, q in enumerate(estudo.quiz, 1):
        letra = LETRAS[q.correta] if 0 <= q.correta < len(q.alternativas) else "?"
        linhas += [f"{i}. **{letra}**: {q.explicacao} *({q.minuto})*"]
    return "\n".join(linhas) + "\n"


def _campo_anki(texto: str) -> str:
    return texto.replace("\t", " ").replace("\r", " ").replace("\n", "<br>")


def anki(aula: Aula, analise: Analise) -> str:
    """Arquivo de texto para Arquivo › Importar no Anki (frente, verso e etiqueta)."""
    etiqueta = "".join(ch if ch.isalnum() else "_" for ch in aula.titulo)
    linhas = ["#separator:tab", "#html:true", "#tags column:3"]
    for f in analise.estudo.flashcards:
        verso = f"{f.resposta}<br><small>{aula.titulo} · {f.minuto}</small>"
        linhas.append("\t".join([_campo_anki(f.pergunta), _campo_anki(verso), etiqueta]))
    return "\n".join(linhas) + "\n"


def texto_transcricao(segmentos: list[Segmento]) -> str:
    return "\n\n".join(f"[{formatar_tempo(b.inicio)}] {b.texto}" for b in agrupar_em_blocos(segmentos, 60))


def srt(segmentos: list[Segmento]) -> str:
    def tempo_srt(segundos: float) -> str:
        ms = int(round(segundos * 1000))
        return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    blocos = []
    for i, s in enumerate((s for s in segmentos if s.texto.strip()), 1):
        blocos.append(f"{i}\n{tempo_srt(s.inicio)} --> {tempo_srt(s.fim)}\n{s.texto.strip()}\n")
    return "\n".join(blocos)
