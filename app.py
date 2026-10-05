"""Interface do Analisador de Aulas. Rode com: streamlit run app.py"""

import random
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st

from analisador import config, exportar
from analisador.analise import ErroAnalise, responder
from analisador.biblioteca import (
    Aula, Biblioteca, Etapa, agrupar_em_blocos, formatar_tempo, listar_midias, ordem_natural,
    sem_acentos, slug,
)
from analisador.modelos import Analise, Flashcard, QuestaoQuiz
from analisador.pipeline import Processador
from analisador.transcricao import MODELOS_WHISPER

st.set_page_config(page_title="Analisador de Aulas", page_icon="🎓", layout="wide")

ICONES = {
    Etapa.NA_FILA: "🕒", Etapa.TRANSCREVENDO: "🎙️", Etapa.ANALISANDO: "🧠",
    Etapa.TRANSCRITA: "📄", Etapa.PRONTA: "✅", Etapa.ERRO: "⚠️",
}
IDIOMAS = {"pt": "Português", "auto": "Detectar automaticamente", "en": "Inglês", "es": "Espanhol"}
ADICIONAR = "__adicionar__"


def md(texto: str) -> str:
    """Escapa símbolos que o Streamlit interpretaria (R$ 10 e R$ 20 viraria fórmula; ~ vira riscado)."""
    return texto.replace("$", "\\$").replace("~", "\\~")


@st.cache_resource
def processador() -> Processador:
    proc = Processador(Biblioteca())
    proc.retomar_interrompidas()
    return proc


# Barra lateral


def barra_lateral(bib: Biblioteca) -> tuple[str, str, str]:
    with st.sidebar:
        st.title("🎓 Analisador de Aulas")
        if config.credenciais_claude():
            st.caption(f"✅ Claude conectado · {config.MODELO_CLAUDE}")
        else:
            with st.container(border=True):
                st.markdown("**🔑 Chave da API do Claude**")
                st.caption(
                    "Necessária para resumo, flashcards, quiz e chat (a transcrição funciona sem ela). "
                    "Crie uma em [console.anthropic.com](https://console.anthropic.com/settings/keys)."
                )
                chave = st.text_input("Chave", type="password", placeholder="sk-ant-...", label_visibility="collapsed")
                if st.button("Salvar chave", width="stretch"):
                    if chave.strip():
                        config.salvar_chave_api(chave)
                        st.rerun()
                    st.warning("Cole a chave no campo acima.")

        with st.expander("⚙️ Transcrição"):
            nomes = list(MODELOS_WHISPER)
            modelo = st.selectbox(
                "Modelo do Whisper", nomes, key="modelo_whisper",
                index=nomes.index(config.MODELO_WHISPER) if config.MODELO_WHISPER in nomes else 0,
            )
            st.caption(MODELOS_WHISPER[modelo])
            idiomas = list(IDIOMAS)
            idioma = st.selectbox(
                "Idioma das aulas", idiomas, format_func=IDIOMAS.get, key="idioma",
                index=idiomas.index(config.IDIOMA) if config.IDIOMA in idiomas else 0,
            )

        st.divider()
        aulas = bib.aulas()
        cursos = sorted({a.curso for a in aulas}, key=ordem_natural)
        if len(cursos) > 1:
            curso = st.selectbox("Curso", ["Todos os cursos", *cursos])
            if curso != "Todos os cursos":
                aulas = [a for a in aulas if a.curso == curso]

        rotulos = {ADICIONAR: "➕ Adicionar aulas"}
        rotulos |= {a.id: f"{ICONES.get(a.status()['etapa'], '')} {a.titulo}" for a in aulas}
        atual = st.query_params.get("aula", ADICIONAR)
        if atual not in rotulos:
            atual = ADICIONAR
        escolha = st.radio(
            "Aulas", list(rotulos), index=list(rotulos).index(atual),
            format_func=rotulos.get, label_visibility="collapsed",
        )
        if escolha != atual:
            st.query_params["aula"] = escolha
    return modelo, idioma, escolha


@st.fragment(run_every=2)
def painel_processamento() -> None:
    ativas = [(a, s) for a in Biblioteca().aulas() if (s := a.status())["etapa"] in Etapa.EM_ANDAMENTO]
    ids = {a.id for a, _ in ativas}
    anteriores = st.session_state.get("ids_em_andamento", set())
    st.session_state["ids_em_andamento"] = ids
    if anteriores - ids:
        st.rerun()  # alguma aula terminou: atualiza a página inteira
    if not ativas:
        return
    with st.container(border=True):
        st.markdown(f"**Processando {len(ativas)} aula(s)** · pode continuar usando o app enquanto isso.")
        for aula, s in ativas:
            texto = f"{ICONES[s['etapa']]} **{md(aula.titulo)}** · {md(s['mensagem'] or s['etapa'])}"
            st.progress(min(max(s["progresso"] or 0.0, 0.0), 1.0), text=texto)


# Página: adicionar aulas


def _tamanho(caminho: Path) -> str:
    n = caminho.stat().st_size
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def _situacao(aula: Aula | None) -> str:
    if not aula:
        return "Nova"
    return {
        Etapa.PRONTA: "✅ Pronta", Etapa.ERRO: "⚠️ Erro", Etapa.TRANSCRITA: "📄 Só transcrita",
    }.get(aula.status()["etapa"], "⏳ Em andamento")


def pagina_adicionar(bib: Biblioteca, proc: Processador, modelo: str, idioma: str) -> None:
    st.header("Adicionar aulas")
    st.markdown(
        "1. O áudio de cada aula é transcrito **no seu computador**, de graça, com o Whisper.\n"
        "2. O Claude lê a transcrição e gera **resumo, capítulos com minutagem, flashcards e quiz**.\n"
        "3. Você estuda pelo app e tira dúvidas no **chat com a aula**."
    )
    st.caption(
        "Na CPU, uma aula de 1 hora leva em média de 10 a 40 minutos para transcrever, conforme o computador "
        "(com placa NVIDIA, poucos minutos). As aulas são processadas uma por vez, em segundo plano."
    )

    aba_pasta, aba_envio = st.tabs(["📁 Pasta do computador", "⬆️ Enviar arquivos"])
    with aba_pasta:
        st.caption("Ideal para um curso inteiro: os vídeos são lidos direto da pasta, sem cópias.")
        caminho = st.text_input(
            "Caminho da pasta com as aulas", placeholder=r"C:\Users\voce\Cursos\Meu Curso",
            help="No Windows, abra a pasta no Explorador, clique na barra de endereço e copie o caminho.",
        )
        if caminho.strip():
            pasta = Path(caminho.strip().strip('"')).expanduser()
            if pasta.is_dir():
                _selecionar_da_pasta(bib, proc, pasta, modelo, idioma)
            else:
                st.error("Pasta não encontrada. Confira o caminho.")

    with aba_envio:
        st.caption("Para arquivos avulsos (até 2 GB cada). A cópia enviada é apagada depois da transcrição.")
        enviados = st.file_uploader(
            "Vídeos ou áudios", accept_multiple_files=True,
            type=sorted(e.lstrip(".") for e in config.EXTENSOES_MIDIA),
        )
        curso = st.text_input("Nome do curso", value="Arquivos enviados", key="curso_envio")
        if enviados and st.button("Processar arquivos enviados", type="primary"):
            for arquivo in enviados:
                destino = bib.pasta_envios / Path(arquivo.name).name
                with open(destino, "wb") as saida:
                    shutil.copyfileobj(arquivo, saida, 16 * 1024 * 1024)
                proc.enfileirar(bib.adicionar(destino, curso, envio=True), modelo, idioma)
            st.rerun()


def _selecionar_da_pasta(bib: Biblioteca, proc: Processador, pasta: Path, modelo: str, idioma: str) -> None:
    arquivos = listar_midias(pasta)
    if not arquivos:
        st.warning("Nenhum vídeo ou áudio encontrado nesta pasta (nem nas subpastas).")
        return
    existentes = bib.por_origem()
    aulas = [existentes.get(str(p.resolve())) for p in arquivos]
    tabela = pd.DataFrame({
        "Processar": [a is None or a.status()["etapa"] == Etapa.ERRO for a in aulas],
        "Arquivo": [str(p.relative_to(pasta)) for p in arquivos],
        "Tamanho": [_tamanho(p) for p in arquivos],
        "Situação": [_situacao(a) for a in aulas],
    })
    editada = st.data_editor(
        tabela, hide_index=True, width="stretch", key=f"selecao-{pasta}",
        disabled=["Arquivo", "Tamanho", "Situação"],
    )
    curso = st.text_input("Nome do curso", value=pasta.name)
    selecionados = [arq for arq, marcado in zip(arquivos, editada["Processar"]) if marcado]
    if st.button(f"Processar {len(selecionados)} aula(s)", type="primary", disabled=not selecionados):
        for arq in selecionados:
            proc.enfileirar(bib.adicionar(arq, curso), modelo, idioma)
        st.rerun()


# Página: aula


def pagina_aula(aula: Aula, proc: Processador, modelo: str, idioma: str) -> None:
    status = aula.status()
    etapa = status["etapa"]
    analise = aula.analise()

    st.header(aula.titulo)
    detalhes = [aula.curso]
    if aula.duracao:
        detalhes.append(f"⏱️ {formatar_tempo(aula.duracao)}")
    st.caption(" · ".join(detalhes))

    if etapa == Etapa.ERRO:
        st.error(f"Falha no processamento: {status['mensagem']}")
        if st.button("🔁 Tentar de novo"):
            proc.enfileirar(aula, modelo, idioma)
            st.rerun()
    elif etapa == Etapa.TRANSCRITA:
        st.info(status["mensagem"])
        if st.button("🧠 Gerar análise", disabled=not config.credenciais_claude()):
            proc.enfileirar(aula, modelo, idioma)
            st.rerun()
    elif etapa in Etapa.EM_ANDAMENTO:
        st.info("Esta aula está sendo processada. O progresso aparece no painel acima.")

    if not aula.tem_transcricao():
        return

    abas = st.tabs(["📝 Resumo", "🗂️ Capítulos", "🃏 Flashcards", "✅ Quiz", "💬 Chat", "📄 Transcrição", "⬇️ Exportar"])
    if analise:
        with abas[0]:
            aba_resumo(analise)
        with abas[1]:
            aba_capitulos(analise)
        with abas[2]:
            aba_flashcards(aula.id, analise.estudo.flashcards)
        with abas[3]:
            aba_quiz(aula.id, analise.estudo.quiz)
    else:
        for aba in abas[:4]:
            aba.info("A análise desta aula ainda não foi gerada.")
    with abas[4]:
        aba_chat(aula)
    with abas[5]:
        aba_transcricao(aula)
    with abas[6]:
        aba_exportar(aula, analise, proc, modelo, idioma, em_andamento=etapa in Etapa.EM_ANDAMENTO)


def aba_resumo(analise: Analise) -> None:
    vg = analise.visao_geral
    st.subheader(md(vg.titulo_sugerido))
    st.markdown(md(vg.resumo))
    esquerda, direita = st.columns(2)
    with esquerda:
        st.markdown("#### Pontos-chave")
        st.markdown("\n".join(f"- {md(p)}" for p in vg.pontos_chave))
    with direita:
        if vg.acoes_praticas:
            st.markdown("#### Para aplicar")
            st.markdown("\n".join(f"- {md(a)}" for a in vg.acoes_praticas))
    if vg.conceitos:
        st.markdown("#### Conceitos")
        st.markdown("\n".join(f"- **{md(c.termo)}**: {md(c.explicacao)}" for c in vg.conceitos))


def aba_capitulos(analise: Analise) -> None:
    st.caption("Use a minutagem para pular direto ao trecho no seu player de vídeo.")
    for c in analise.visao_geral.capitulos:
        st.markdown(f"**`{c.inicio}`** · **{md(c.titulo)}**  \n{md(c.resumo)}")


@st.fragment
def aba_flashcards(aula_id: str, cards: list[Flashcard]) -> None:
    if not cards:
        st.info("Nenhum flashcard gerado.")
        return
    ss = st.session_state
    k_ordem, k_pos, k_virado = f"fc-ordem-{aula_id}", f"fc-pos-{aula_id}", f"fc-virado-{aula_id}"
    if len(ss.get(k_ordem, [])) != len(cards):
        ss[k_ordem], ss[k_pos], ss[k_virado] = list(range(len(cards))), 0, False

    def ir(delta: int) -> None:
        ss[k_pos] = min(max(ss[k_pos] + delta, 0), len(cards) - 1)
        ss[k_virado] = False

    def embaralhar() -> None:
        random.shuffle(ss[k_ordem])
        ss[k_pos], ss[k_virado] = 0, False

    pos = ss[k_pos]
    card = cards[ss[k_ordem][pos]]
    st.progress((pos + 1) / len(cards), text=f"Card {pos + 1} de {len(cards)}")
    with st.container(border=True):
        st.markdown(f"#### {md(card.pergunta)}")
        if ss[k_virado]:
            st.markdown(md(card.resposta))
            st.caption(f"📍 {card.minuto}")
        else:
            st.caption("Pense na resposta antes de virar o card.")
    c1, c2, c3, c4 = st.columns(4)
    c1.button("⬅️ Anterior", on_click=ir, args=(-1,), disabled=pos == 0, width="stretch", key=f"fc-ant-{aula_id}")
    c2.button("🔄 Virar", on_click=lambda: ss.update({k_virado: not ss[k_virado]}), width="stretch", key=f"fc-virar-{aula_id}")
    c3.button("Próximo ➡️", on_click=ir, args=(1,), disabled=pos == len(cards) - 1, width="stretch", key=f"fc-prox-{aula_id}")
    c4.button("🔀 Embaralhar", on_click=embaralhar, width="stretch", key=f"fc-emb-{aula_id}")
    with st.expander("Ver todos os cards"):
        for i, f in enumerate(cards, 1):
            st.markdown(f"**{i}. {md(f.pergunta)}**  \n{md(f.resposta)} *({f.minuto})*")


@st.fragment
def aba_quiz(aula_id: str, quiz: list[QuestaoQuiz]) -> None:
    if not quiz:
        st.info("Nenhuma questão gerada.")
        return
    ss = st.session_state
    k_respostas = f"quiz-respostas-{aula_id}"
    chaves = [f"quiz-{aula_id}-{n}" for n in range(len(quiz))]

    def alternativa(q: QuestaoQuiz, j: int | None) -> str:
        return f"{exportar.LETRAS[j]}) {md(q.alternativas[j])}" if j is not None and 0 <= j < len(q.alternativas) else "?"

    respostas = ss.get(k_respostas)
    if respostas is not None and len(respostas) != len(quiz):  # a análise foi refeita
        respostas = ss[k_respostas] = None
    if respostas is None:
        with st.form(f"quiz-{aula_id}"):
            for n, q in enumerate(quiz):
                st.markdown(f"**{n + 1}. {md(q.pergunta)}**")
                st.radio(f"Questão {n + 1}", list(range(len(q.alternativas))), index=None, key=chaves[n],
                         format_func=lambda j, q=q: alternativa(q, j), label_visibility="collapsed")
            # As respostas são copiadas no envio; o resultado é mostrado sem os widgets do formulário.
            st.form_submit_button("Corrigir", type="primary",
                                  on_click=lambda: ss.update({k_respostas: [ss.get(k) for k in chaves]}))
        return

    def refazer() -> None:
        for k in [k_respostas, *chaves]:
            ss.pop(k, None)

    acertos = sum(r == q.correta for r, q in zip(respostas, quiz))
    st.metric("Acertos", f"{acertos} de {len(quiz)}")
    for n, (q, escolhida) in enumerate(zip(quiz, respostas)):
        st.markdown(f"**{n + 1}. {md(q.pergunta)}**")
        if escolhida == q.correta:
            st.success(f"{alternativa(q, escolhida)}  \nCorreto! {md(q.explicacao)} ({q.minuto})")
        else:
            marcada = alternativa(q, escolhida) if escolhida is not None else "nenhuma"
            st.error(f"Você marcou: {marcada}  \nResposta certa: **{alternativa(q, q.correta)}**. "
                     f"{md(q.explicacao)} ({q.minuto})")
    st.button("🔁 Refazer quiz", key=f"quiz-refazer-{aula_id}", on_click=refazer)


def aba_chat(aula: Aula) -> None:
    if not config.credenciais_claude():
        st.info("Configure a chave da API do Claude na barra lateral para conversar com a aula.")
        return
    historico = aula.chat()
    conversa = st.container(height=520)
    with conversa:
        if not historico:
            st.caption(
                "Pergunte qualquer coisa sobre a aula. As respostas indicam a minutagem [HH:MM:SS] do trecho. "
                "Exemplos: *Explique de novo o método que ele ensinou* · *Em que minuto ele fala de preço?* · "
                "*Monte um passo a passo para eu aplicar isso*"
            )
        for m in historico:
            with st.chat_message(m["role"]):
                st.markdown(md(m["content"]))

    pergunta = st.chat_input("Pergunte algo sobre a aula…", key=f"chat-{aula.id}")
    if pergunta:
        with conversa:
            with st.chat_message("user"):
                st.markdown(md(pergunta))
            with st.chat_message("assistant"):
                pedacos: list[str] = []

                def fluxo():
                    for pedaco in responder(aula, historico, pergunta):
                        pedacos.append(pedaco)
                        yield md(pedaco)

                try:
                    st.write_stream(fluxo())
                except ErroAnalise as e:
                    st.error(str(e))
                    return
        aula.salvar_chat([
            *historico,
            {"role": "user", "content": pergunta},
            {"role": "assistant", "content": "".join(pedacos)},
        ])
        historico = aula.chat()

    if historico and st.button("🧹 Limpar conversa", key=f"chat-limpar-{aula.id}"):
        aula.limpar_chat()
        st.rerun()


def aba_transcricao(aula: Aula) -> None:
    blocos = agrupar_em_blocos(aula.segmentos(), 60)
    busca = st.text_input("🔎 Buscar na transcrição", key=f"busca-{aula.id}")
    if busca.strip():
        termo = sem_acentos(busca.strip()).lower()
        blocos = [b for b in blocos if termo in sem_acentos(b.texto).lower()]
        st.caption(f"{len(blocos)} trecho(s) encontrado(s)")
    with st.container(height=600):
        st.markdown("\n\n".join(f"**`{formatar_tempo(b.inicio)}`** {md(b.texto)}" for b in blocos))
    st.caption(f"Transcrição automática (Whisper {aula.meta.get('modelo_whisper', '')}); pode conter erros.")


def aba_exportar(aula: Aula, analise: Analise | None, proc: Processador, modelo: str, idioma: str,
                 em_andamento: bool) -> None:
    nome = slug(aula.titulo)
    segmentos = aula.segmentos()
    if analise:
        st.download_button("📘 Resumo completo com flashcards e quiz (Markdown)", exportar.markdown(aula, analise),
                           f"{nome}.md", "text/markdown")
        st.download_button("🃏 Flashcards para o Anki", exportar.anki(aula, analise), f"{nome}-anki.txt",
                           "text/plain", help="No Anki: Arquivo › Importar e escolha este arquivo.")
    st.download_button("📄 Transcrição com minutagem (.txt)", exportar.texto_transcricao(segmentos),
                       f"{nome}-transcricao.txt", "text/plain")
    st.download_button("🎬 Legenda (.srt)", exportar.srt(segmentos), f"{nome}.srt", "text/plain",
                       help="Salve ao lado do vídeo com o mesmo nome para ver a legenda no VLC.")

    st.divider()
    if analise:
        uso = analise.uso
        lidos = uso.entrada + uso.entrada_cache_gravada + uso.entrada_cache_lida
        st.caption(f"Análise gerada em {analise.gerada_em} com {analise.modelo} · "
                   f"{lidos:,} tokens lidos e {uso.saida:,} gerados".replace(",", "."))
        if st.button("🔁 Refazer análise", disabled=em_andamento or not config.credenciais_claude()):
            proc.enfileirar(aula, modelo, idioma, refazer_analise=True)
            st.rerun()
    with st.popover("🗑️ Excluir aula", disabled=em_andamento):
        st.write("Apaga a transcrição, a análise e o chat desta aula. O vídeo original no seu computador não é apagado.")
        if st.button("Confirmar exclusão", type="primary"):
            aula.excluir()
            st.query_params.clear()
            st.rerun()


def main() -> None:
    bib = Biblioteca()
    proc = processador()
    modelo, idioma, escolha = barra_lateral(bib)
    painel_processamento()
    aula = bib.obter(escolha) if escolha != ADICIONAR else None
    if aula:
        pagina_aula(aula, proc, modelo, idioma)
    else:
        pagina_adicionar(bib, proc, modelo, idioma)


main()
