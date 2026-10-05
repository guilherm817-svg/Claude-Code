from analisador import exportar
from conftest import SEGMENTOS


def test_srt():
    srt = exportar.srt(SEGMENTOS)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:12,500\nOlá, bem-vindos à aula.\n")
    assert "4\n00:01:05,000 --> 00:01:20,000\nAgora, a margem de lucro." in srt


def test_texto_transcricao_em_blocos_de_um_minuto():
    texto = exportar.texto_transcricao(SEGMENTOS)
    assert texto.split("\n\n")[0].startswith("[00:00:00] Olá")
    assert texto.split("\n\n")[1] == "[00:01:05] Agora, a margem de lucro."


def test_anki(aula_pronta):
    linhas = exportar.anki(aula_pronta, aula_pronta.analise()).splitlines()
    assert linhas[:3] == ["#separator:tab", "#html:true", "#tags column:3"]
    frente, verso, etiqueta = linhas[3].split("\t")
    assert frente == "Qual o primeiro passo?"
    assert verso.startswith("Calcular o custo.<br><small>Aula 01 - Introdução · 00:00:31")
    assert " " not in etiqueta


def test_markdown(aula_pronta):
    texto = exportar.markdown(aula_pronta, aula_pronta.analise())
    for trecho in ["# Aula 01 - Introdução", "## Resumo", "- [ ] Liste seus custos.",
                   "- **00:00:00** Abertura: Boas-vindas.", "   - A) Custo", "1. **A**: O custo vem antes."]:
        assert trecho in texto
