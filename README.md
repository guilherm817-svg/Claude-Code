# 🎓 Analisador de Aulas

App local para estudar aulas longas (1 hora ou mais) de cursos que você comprou. Você aponta a pasta com
os vídeos e o app:

1. **transcreve o áudio no seu computador**, de graça, com o Whisper;
2. usa o **Claude** para gerar, de cada aula:
   - **resumo** e pontos-chave, conceitos e ações práticas;
   - **capítulos com minutagem** (ex.: `00:21:30 · Margem e markup`), para pular direto ao trecho;
   - **flashcards** (com modo de estudo e exportação para o Anki) e **quiz** de múltipla escolha com correção;
3. abre um **chat com a aula**: você pergunta e a resposta cita o minuto de onde veio.

Tudo fica numa interface no navegador, rodando só no seu computador.

## Instalação

Você precisa de:

- **Python 3.10 a 3.13** (recomendado 3.12). No Windows, baixe em
  [python.org/downloads](https://www.python.org/downloads/) e **marque "Add python.exe to PATH"** na instalação.
- **Uma chave da API do Claude**, para a análise e o chat. Crie em
  [console.anthropic.com](https://console.anthropic.com/settings/keys) e adicione créditos. A transcrição
  funciona sem ela.
- Internet na primeira transcrição, para baixar o modelo do Whisper (o `large-v3-turbo` tem ~1,6 GB).
  Depois ele fica salvo no computador.

Depois, baixe este projeto (botão **Code › Download ZIP** no GitHub), descompacte e:

- **Windows:** dê dois cliques em `iniciar.bat`.
- **Mac/Linux:** rode `./iniciar.sh` no terminal.

Na primeira vez o app instala as dependências (alguns minutos) e depois abre no navegador, em
`http://localhost:8501`. Cole sua chave da API na barra lateral e clique em **Salvar chave**. Ela fica no
arquivo `.env`, só no seu computador.

## Como usar

1. Em **➕ Adicionar aulas › Pasta do computador**, cole o caminho da pasta do curso (no Windows, clique na
   barra de endereço do Explorador e copie). O app lista os vídeos e áudios, inclusive de subpastas, em ordem
   (Aula 2 antes de Aula 10).
2. Marque as aulas e clique em **Processar**. Elas entram numa fila e são processadas uma por vez, em segundo
   plano. Você pode continuar usando o app, e se fechar no meio, o processamento retoma quando abrir de novo.
3. Clique numa aula na barra lateral para ver as abas **Resumo, Capítulos, Flashcards, Quiz, Chat,
   Transcrição** e **Exportar**.

Formatos aceitos: MP4, MKV, MOV, AVI, WEBM, M4V, WMV, MP3, M4A, WAV, AAC, OGG, OPUS, FLAC e outros. O áudio é
lido direto do vídeo, sem precisar instalar o ffmpeg.

### Processar um curso inteiro pelo terminal

Para deixar o computador processando sem abrir a interface:

```bash
# Rode na pasta do projeto. Windows: .venv\Scripts\python -m analisador ...  Mac/Linux: .venv/bin/python -m analisador ...
python -m analisador processar "C:\Cursos\Meu Curso"
python -m analisador processar aula1.mp4 aula2.mp4 --curso "Meu Curso" --modelo-whisper small
python -m analisador listar
```

O resultado aparece na interface do mesmo jeito.

## Quanto tempo e quanto custa

**Transcrição: grátis, roda no seu computador.** Numa aula de 1 hora, leva em média:

| Computador | `large-v3-turbo` (padrão) | `small` |
|---|---|---|
| Notebook comum (CPU) | 20 a 40 min | 8 a 15 min |
| PC/notebook recente (CPU) | 10 a 20 min | 5 a 8 min |
| Placa NVIDIA (GPU) | 2 a 5 min | 1 a 2 min |

São estimativas: varia bastante com o processador. Troque o modelo em **⚙️ Transcrição** na barra lateral.
O `large-v3-turbo` acerta bem mais nomes e termos técnicos que o `small`.

**Análise com o Claude: paga, por uso.** Com o modelo padrão (Claude Opus 5.5), uma aula de 1 hora sai por
volta de **US$ 0,40 a US$ 0,80** (resumo, capítulos, flashcards e quiz), e cada pergunta no chat, por volta de
**US$ 0,02 a US$ 0,10**. A transcrição vai em cache, então a segunda chamada e as perguntas seguidas no chat
leem a aula por uma fração do preço (até 5 minutos depois da última chamada). A aba **Exportar** mostra quantos tokens cada análise usou. Para gastar menos,
você pode trocar para o Claude Sonnet 5.5 (cerca de metade do preço) no `.env`:
`ANALISADOR_MODELO_CLAUDE=claude-sonnet-5-5`.

## Privacidade

Os vídeos nunca saem do seu computador. Só o **texto** da transcrição é enviado para a API do Claude, para a
análise e o chat. Tudo o que o app gera fica na pasta `biblioteca/`, dentro do projeto.

## Exportar

Na aba **⬇️ Exportar** de cada aula:

- **Resumo completo (Markdown):** resumo, capítulos, flashcards, quiz e gabarito. Abre no Notion, Obsidian,
  Google Docs etc.
- **Flashcards para o Anki:** no Anki, use *Arquivo › Importar* e escolha o arquivo.
- **Transcrição (.txt)** com minutagem e **legenda (.srt)**: salve a legenda ao lado do vídeo, com o mesmo nome,
  para ver no VLC.

## Problemas comuns

- **"Não foi possível baixar o modelo do Whisper":** a primeira transcrição precisa de internet para baixar o
  modelo. Confira a conexão e clique em **Tentar de novo** na aula.
- **Placa NVIDIA, mas a transcrição está lenta:** o app tenta usar a GPU e, se faltarem as bibliotecas CUDA 12
  e cuDNN 9, segue na CPU automaticamente. Para usar a GPU, siga as
  [instruções do faster-whisper](https://github.com/SYSTRAN/faster-whisper#gpu).
- **"Chave da API do Claude inválida" ou "Sem créditos":** confira a chave e o saldo em
  [console.anthropic.com](https://console.anthropic.com).
- **Arquivo enviado muito grande:** a aba *Enviar arquivos* aceita até 2 GB por arquivo. Para vídeos maiores,
  use a aba *Pasta do computador*, que lê o arquivo sem copiar.

## Configurações opcionais

No arquivo `.env` (veja `.env.example`):

| Variável | Padrão | Para quê |
|---|---|---|
| `ANTHROPIC_API_KEY` | | chave da API do Claude |
| `ANALISADOR_MODELO_CLAUDE` | `claude-opus-5-5` | modelo usado na análise e no chat |
| `ANALISADOR_MODELO_WHISPER` | `large-v3-turbo` | modelo de transcrição padrão |
| `ANALISADOR_IDIOMA` | `pt` | idioma das aulas (`auto` para detectar) |
| `ANALISADOR_DISPOSITIVO` | `auto` | `cpu` para nunca tentar a GPU |
| `ANALISADOR_PASTA_DADOS` | `biblioteca` | onde ficam transcrições e análises |

## Para desenvolvedores

```
app.py                     interface (Streamlit)
analisador/
  transcricao.py           Whisper local (faster-whisper, modo em lote)
  analise.py               chamadas ao Claude: análise com saída estruturada e chat em streaming
  pipeline.py              transcrever → analisar, e a fila em segundo plano
  biblioteca.py            armazenamento em pastas/JSON
  modelos.py               formatos da análise (Pydantic)
  exportar.py              Markdown, Anki, .txt e .srt
  __main__.py              linha de comando
tests/                     pytest (o Claude e o Whisper são simulados)
```

```bash
pip install -r requirements.txt pytest
python -m pytest
```
