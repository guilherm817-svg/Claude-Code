import threading

from analisador.biblioteca import Etapa
from analisador.pipeline import Processador, processar_aula
from conftest import SEGMENTOS, analise_exemplo


def transcrever_falso(caminho, modelo, idioma, ao_progredir):
    for s in SEGMENTOS:
        ao_progredir(s.fim, 80.0)
    return SEGMENTOS, 80.0


def analisar_falso(aula, ao_progredir):
    ao_progredir(0.5, "metade")
    return analise_exemplo()


def test_sem_chave_so_transcreve(biblioteca, video):
    aula = biblioteca.adicionar(video)
    etapas = []
    processar_aula(aula, modelo_whisper="tiny", idioma="pt", transcrever=transcrever_falso,
                   analisar=analisar_falso, relatar=lambda e, p, m: etapas.append(e))
    assert aula.segmentos() == SEGMENTOS
    assert aula.meta["modelo_whisper"] == "tiny"
    assert aula.status()["etapa"] == Etapa.TRANSCRITA
    assert not aula.tem_analise()
    assert etapas[0] == Etapa.TRANSCREVENDO


def test_com_chave_transcreve_e_analisa(biblioteca, video, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    aula = biblioteca.adicionar(video)
    processar_aula(aula, modelo_whisper="tiny", idioma="pt", transcrever=transcrever_falso, analisar=analisar_falso)
    assert aula.status()["etapa"] == Etapa.PRONTA
    assert aula.analise() == analise_exemplo()


def test_nao_retranscreve_e_refaz_analise_so_quando_pedido(aula_pronta, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    chamadas = []

    def nao_chamar(*a):
        raise AssertionError("não deveria transcrever de novo")

    def analisar_contando(aula, ao_progredir):
        chamadas.append(1)
        return analise_exemplo()

    processar_aula(aula_pronta, modelo_whisper="tiny", idioma="pt", transcrever=nao_chamar, analisar=analisar_contando)
    assert chamadas == []
    processar_aula(aula_pronta, modelo_whisper="tiny", idioma="pt", refazer_analise=True,
                   transcrever=nao_chamar, analisar=analisar_contando)
    assert chamadas == [1]
    assert aula_pronta.status()["etapa"] == Etapa.PRONTA


def test_erro_vira_status(biblioteca, video):
    aula = biblioteca.adicionar(video)
    video.unlink()
    processar_aula(aula, modelo_whisper="tiny", idioma="pt", transcrever=transcrever_falso, analisar=analisar_falso)
    status = aula.status()
    assert status["etapa"] == Etapa.ERRO
    assert "não encontrado" in status["mensagem"]


def test_audio_sem_fala_e_erro(biblioteca, video):
    aula = biblioteca.adicionar(video)
    processar_aula(aula, modelo_whisper="tiny", idioma="pt", transcrever=lambda *a: ([], 10.0), analisar=analisar_falso)
    assert aula.status()["etapa"] == Etapa.ERRO
    assert not aula.tem_transcricao()


def test_copia_enviada_e_apagada_depois_da_transcricao(biblioteca):
    enviado = biblioteca.pasta_envios / "aula.mp4"
    enviado.write_bytes(b"x")
    aula = biblioteca.adicionar(enviado, envio=True)
    processar_aula(aula, modelo_whisper="tiny", idioma="pt", transcrever=transcrever_falso, analisar=analisar_falso)
    assert aula.tem_transcricao()
    assert not enviado.exists()


def test_fila_processa_em_segundo_plano_e_sobrevive_a_erros(biblioteca, video, tmp_path):
    liberar = threading.Event()

    def transcrever_lento(caminho, modelo, idioma, ao_progredir):
        liberar.wait(5)
        if caminho.name == "quebrada.mp4":
            raise RuntimeError("arquivo corrompido")
        return transcrever_falso(caminho, modelo, idioma, ao_progredir)

    quebrada = tmp_path / "quebrada.mp4"
    quebrada.write_bytes(b"x")
    proc = Processador(biblioteca, transcrever=transcrever_lento, analisar=analisar_falso)
    a1, a2 = biblioteca.adicionar(quebrada), biblioteca.adicionar(video)
    proc.enfileirar(a1, "tiny", "pt")
    proc.enfileirar(a2, "tiny", "pt")
    proc.enfileirar(a2, "tiny", "pt")  # duplicada é ignorada
    assert proc.ocupado()
    liberar.set()
    proc.aguardar()
    assert not proc.ocupado()
    assert a1.status()["etapa"] == Etapa.ERRO
    assert a1.status()["mensagem"] == "arquivo corrompido"
    assert a2.status()["etapa"] == Etapa.TRANSCRITA


def test_retomar_aulas_interrompidas(biblioteca, video):
    aula = biblioteca.adicionar(video)
    aula.definir_status(Etapa.TRANSCREVENDO, 0.4, "Transcrevendo…")
    proc = Processador(biblioteca, transcrever=transcrever_falso, analisar=analisar_falso)
    proc.retomar_interrompidas()
    proc.aguardar()
    assert aula.status()["etapa"] == Etapa.TRANSCRITA
