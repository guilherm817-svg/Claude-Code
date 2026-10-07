"""Servidor local do Estúdio: a API que a tela usa e os arquivos da própria tela (pasta static/)."""

import mimetypes
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import config
from .exportar import ErroExportacao, Exportador
from .projetos import Ajustes, ErroImportacao, Estudio, ProjetoNaoEncontrado
from .rotas_legendas import criar_rotas_legendas
from .rotas_corretor import rotas_corretor

ESTATICOS = Path(__file__).parent / "static"
# Pedidos que mudam algo precisam deste cabeçalho. Um site qualquer aberto no navegador não consegue mandá-lo
# para o Estúdio sem permissão (o navegador exige CORS), então só a própria tela do Estúdio altera projetos.
CABECALHO = "x-estudio"
# Endereços aceitos: o navegador sempre leva estes dois ao próprio computador. Outro nome (como o "testserver" dos
# testes) é resolvido pela rede, e quem responder por ele pode apontá-lo para cá e usar a API (DNS rebinding).
HOSTS = ("127.0.0.1", "localhost")
# A tela não pode ser mostrada dentro de outro site (clickjacking): os cliques do usuário iriam para os botões dela.
PROTECOES = {"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'",
             "X-Content-Type-Options": "nosniff"}
# No Windows, o mimetypes lê os tipos do registro, onde .js às vezes aparece como text/plain; aí o navegador recusa os
# módulos da tela e nada funciona. Estes valem mais que o registro.
TIPOS = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json",
         ".svg": "image/svg+xml", ".ttf": "font/ttf", ".woff2": "font/woff2"}


class NovoProjeto(BaseModel):
    nome: str | None = Field(default=None, max_length=120)


def _abrir_pasta(pasta: Path) -> None:
    if sys.platform == "win32":
        os.startfile(pasta)  # noqa: S606 (pasta do próprio projeto)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(pasta)])


def criar_app(estudio: Estudio | None = None, hosts: tuple[str, ...] = HOSTS) -> FastAPI:
    estudio = estudio or Estudio()
    exportador = Exportador(estudio)
    for extensao, tipo in TIPOS.items():
        mimetypes.add_type(tipo, extensao)
    app = FastAPI(title="Estúdio de Reels", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.estudio, app.state.exportador = estudio, exportador
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))

    @app.middleware("http")
    async def so_a_tela_altera(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CABECALHO) != "1":
            resposta = JSONResponse({"detail": "Pedido recusado."}, status_code=403)
        else:
            resposta = await call_next(request)
        resposta.headers.update(PROTECOES)
        if request.url.path.startswith("/static/"):
            # Depois de atualizar o Estúdio, o navegador confere se a tela mudou em vez de usar a versão velha.
            resposta.headers["Cache-Control"] = "no-cache"
        return resposta

    @app.exception_handler(ProjetoNaoEncontrado)
    async def _nao_encontrado(_, __):
        return JSONResponse({"detail": "Projeto ou clipe não encontrado."}, status_code=404)

    @app.exception_handler(ErroImportacao)
    @app.exception_handler(ErroExportacao)
    async def _erro_de_uso(_, erro):
        return JSONResponse({"detail": str(erro)}, status_code=400)

    def midia_ou_404(projeto_id: str, midia_id: str):
        projeto = estudio.abrir(projeto_id)
        midia = projeto.midia(midia_id)
        if midia is None:
            raise ProjetoNaoEncontrado(midia_id)
        return projeto, midia

    # Projetos

    @app.get("/api/config")
    def ver_config():
        return {"formatos": {k: {"largura": l, "altura": a, "nome": n} for k, (l, a, n) in config.FORMATOS.items()},
                "extensoes": sorted(config.EXTENSOES_VIDEO),
                "folga_antes": config.FOLGA_ANTES_DA_FALA, "folga_depois": config.FOLGA_DEPOIS_DA_FALA}

    @app.get("/api/projetos")
    def listar():
        return [p.resumo() for p in estudio.listar()]

    @app.post("/api/projetos")
    def criar(dados: NovoProjeto):
        return estudio.criar(dados.nome.strip() if dados.nome and dados.nome.strip() else None)

    @app.get("/api/projetos/{projeto_id}")
    def abrir(projeto_id: str):
        return estudio.abrir(projeto_id)

    @app.put("/api/projetos/{projeto_id}")
    def salvar(projeto_id: str, ajustes: Ajustes):
        return estudio.aplicar(projeto_id, ajustes)

    @app.delete("/api/projetos/{projeto_id}", status_code=204)
    def excluir(projeto_id: str):
        estudio.excluir(projeto_id)

    # Mídia

    @app.post("/api/projetos/{projeto_id}/midias")
    def importar(projeto_id: str, arquivo: UploadFile):
        _, midia, item = estudio.importar(projeto_id, arquivo.file, arquivo.filename or "video.mp4")
        return {"midia": midia, "item": item}

    @app.delete("/api/projetos/{projeto_id}/midias/{midia_id}", status_code=204)
    def remover_midia(projeto_id: str, midia_id: str):
        estudio.remover_midia(projeto_id, midia_id)

    @app.get("/api/projetos/{projeto_id}/midias/{midia_id}/arquivo")
    def arquivo_midia(projeto_id: str, midia_id: str):
        _, midia = midia_ou_404(projeto_id, midia_id)
        return FileResponse(estudio.arquivo_midia(projeto_id, midia))

    @app.get("/api/projetos/{projeto_id}/midias/{midia_id}/tira.jpg")
    def tira(projeto_id: str, midia_id: str):
        midia_ou_404(projeto_id, midia_id)
        caminho = estudio.arquivo_tira(projeto_id, midia_id)
        if not caminho.exists():
            raise HTTPException(404)
        return FileResponse(caminho, headers={"Cache-Control": "max-age=31536000, immutable"})

    @app.get("/api/projetos/{projeto_id}/midias/{midia_id}/onda")
    def onda(projeto_id: str, midia_id: str):
        midia_ou_404(projeto_id, midia_id)
        caminho = estudio.arquivo_onda(projeto_id, midia_id)
        if not caminho.exists():
            return {"por_segundo": 100, "picos": []}
        return FileResponse(caminho, media_type="application/json",
                            headers={"Cache-Control": "max-age=31536000, immutable"})

    # Exportação

    @app.post("/api/projetos/{projeto_id}/exportar")
    def exportar(projeto_id: str):
        return exportador.iniciar(projeto_id).como_dict()

    @app.get("/api/exportacoes/{exportacao_id}")
    def ver_exportacao(exportacao_id: str):
        exportacao = exportador.obter(exportacao_id)
        if exportacao is None:
            raise HTTPException(404, "Exportação não encontrada.")
        return exportacao.como_dict()

    @app.post("/api/exportacoes/{exportacao_id}/cancelar")
    def cancelar(exportacao_id: str):
        exportacao = exportador.cancelar(exportacao_id)
        if exportacao is None:
            raise HTTPException(404, "Exportação não encontrada.")
        return exportacao.como_dict()

    @app.get("/api/projetos/{projeto_id}/exportados")
    def exportados(projeto_id: str):
        estudio.abrir(projeto_id)
        pasta = estudio.pasta_exportados(projeto_id)
        arquivos = sorted(pasta.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if pasta.exists() else []
        return [{"nome": p.name, "tamanho": p.stat().st_size} for p in arquivos]

    @app.get("/api/projetos/{projeto_id}/exportados/{nome}")
    def baixar(projeto_id: str, nome: str):
        estudio.abrir(projeto_id)
        pasta = estudio.pasta_exportados(projeto_id)
        # O nome pedido só vira caminho depois de conferido, como texto, com os vídeos da pasta. No Windows, só de
        # olhar um caminho como \\servidor\pasta\x.mp4 o computador abre uma conexão de rede e entrega o login.
        if nome not in {p.name for p in pasta.glob("*.mp4") if p.is_file()}:
            raise HTTPException(404, "Vídeo não encontrado.")
        return FileResponse(pasta / nome, filename=nome)

    @app.post("/api/projetos/{projeto_id}/abrir-pasta", status_code=204)
    def abrir_pasta(projeto_id: str):
        estudio.abrir(projeto_id)
        pasta = estudio.pasta_exportados(projeto_id)
        pasta.mkdir(parents=True, exist_ok=True)
        _abrir_pasta(pasta)

    app.include_router(criar_rotas_legendas(estudio))
    app.include_router(rotas_corretor())

    # A tela

    @app.get("/", include_in_schema=False)
    def inicio():
        return RedirectResponse("/static/index.html")

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
    return app
