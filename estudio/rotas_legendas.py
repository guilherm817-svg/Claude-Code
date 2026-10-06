"""Rotas das legendas automáticas: pedir a transcrição dos clipes de um projeto e acompanhar o andamento."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .projetos import Estudio
from .transcricao import Transcritor, tamanho_do_modelo


class PedidoLegendas(BaseModel):
    midias: list[str] | None = Field(default=None, max_length=1000)  # None: todas as mídias do projeto
    refazer: bool = False  # True: transcreve de novo mesmo as que já têm legenda


def criar_rotas_legendas(estudio: Estudio) -> APIRouter:
    transcritor = Transcritor(estudio)
    rotas = APIRouter()

    @rotas.post("/api/projetos/{projeto_id}/legendas")
    def transcrever(projeto_id: str, pedido: PedidoLegendas):
        return transcritor.iniciar(projeto_id, pedido.midias, pedido.refazer)

    @rotas.get("/api/legendas/{trabalho_id}")
    def andamento(trabalho_id: str):
        trabalho = transcritor.obter(trabalho_id)
        if trabalho is None:
            raise HTTPException(404, "Transcrição não encontrada.")
        return trabalho

    @rotas.get("/api/legendas")
    def sobre():
        return {"tamanho_do_modelo": tamanho_do_modelo()}

    return rotas
