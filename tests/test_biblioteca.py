from analisador.biblioteca import (
    Etapa, Segmento, agrupar_em_blocos, formatar_tempo, listar_midias, ordem_natural, slug,
    tempo_para_segundos, transcricao_com_minutagem,
)
from conftest import SEGMENTOS


def test_formatar_e_ler_tempo():
    assert formatar_tempo(0) == "00:00:00"
    assert formatar_tempo(3725.9) == "01:02:05"
    assert tempo_para_segundos("01:02:05") == 3725
    assert tempo_para_segundos("[00:12:30]") == 750
    assert tempo_para_segundos("12:30") == 750
    assert tempo_para_segundos("abc") is None


def test_agrupa_segmentos_em_blocos_de_30s():
    blocos = agrupar_em_blocos(SEGMENTOS)
    assert [b.inicio for b in blocos] == [0.0, 31.0, 65.0]
    assert blocos[0].texto == "Olá, bem-vindos à aula. Hoje vamos falar de precificação."
    assert blocos[0].fim == 29.0


def test_agrupar_ignora_segmentos_vazios():
    assert agrupar_em_blocos([Segmento(0, 1, "  "), Segmento(40, 41, "oi")]) == [Segmento(40, 41, "oi")]


def test_transcricao_com_minutagem():
    texto = transcricao_com_minutagem(SEGMENTOS)
    assert texto.splitlines()[1] == "[00:00:31] O primeiro passo é calcular o custo, uns R$ 10 a R$ 20."


def test_slug_e_ordem_natural():
    assert slug("Aula 01 - Introdução à Precificação!") == "aula-01-introducao-a-precificacao"
    assert slug("???") == "aula"
    assert sorted(["Aula 10", "Aula 2", "aula 1"], key=ordem_natural) == ["aula 1", "Aula 2", "Aula 10"]


def test_listar_midias_em_ordem_natural(tmp_path):
    for nome in ["Aula 10.mp4", "Aula 2.MKV", "notas.pdf", "Módulo 2/Aula 1.mp3", ".oculto.mp4"]:
        (tmp_path / nome).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / nome).write_bytes(b"x")
    nomes = [str(p.relative_to(tmp_path)) for p in listar_midias(tmp_path)]
    assert nomes == ["Aula 2.MKV", "Aula 10.mp4", "Módulo 2/Aula 1.mp3"]


def test_adicionar_aula_e_deduplicar(biblioteca, video):
    aula = biblioteca.adicionar(video, "Curso X")
    assert aula.titulo == "Aula 01 - Introdução"
    assert aula.curso == "Curso X"
    assert aula.status()["etapa"] == Etapa.NA_FILA
    assert aula.id.startswith("aula-01-introducao-")
    assert biblioteca.adicionar(video, "Outro nome").id == aula.id
    assert [a.id for a in biblioteca.aulas()] == [aula.id]
    assert biblioteca.por_origem()[str(video.resolve())].id == aula.id


def test_transcricao_analise_e_chat_persistem(aula_pronta, biblioteca):
    aula = biblioteca.obter(aula_pronta.id)
    assert aula.duracao == 80.0
    assert aula.segmentos() == SEGMENTOS
    assert aula.analise().visao_geral.titulo_sugerido == "Como precificar"
    aula.salvar_chat([{"role": "user", "content": "oi"}])
    assert aula.chat() == [{"role": "user", "content": "oi"}]
    aula.limpar_chat()
    assert aula.chat() == []


def test_excluir_aula_mantem_video_original(aula_pronta, biblioteca, video):
    aula_pronta.excluir()
    assert biblioteca.aulas() == []
    assert video.exists()


def test_pastas_internas_nao_viram_aulas(biblioteca):
    _ = biblioteca.pasta_envios  # cria _envios
    assert biblioteca.aulas() == []
    assert biblioteca.obter("") is None
    assert biblioteca.obter("nao-existe") is None
