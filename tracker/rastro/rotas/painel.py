"""API dos números do painel: resumo, gráfico, tabela de anúncios e lista de vendas."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rastro import metricas
from rastro.meta import ClienteMeta, ErroMeta
from rastro.metricas import Filtros
from rastro.modelos import Conta, ContaAnuncio, EntidadeAnuncio, Produto, StatusVenda, Venda
from rastro.rotas.dependencias import conta_atual, filtros, sessao_db

rotas = APIRouter(prefix="/api")

CHAVES_COMPARACAO = ("faturamento_liquido", "gasto", "lucro", "roas", "vendas", "cpa", "margem", "roi")


@rotas.get("/painel")
def painel(f: Filtros = Depends(filtros), conta: Conta = Depends(conta_atual),
           sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    resumo = metricas.resumo(sessao, conta, f)
    anterior = metricas.resumo(sessao, conta, f.periodo_anterior())
    contas_meta = sessao.scalars(select(ContaAnuncio).where(ContaAnuncio.conta_id == conta.id,
                                                            ContaAnuncio.ativo.is_(True))).all()
    return {
        "periodo": {"inicio": f.inicio.isoformat(), "fim": f.fim.isoformat()},
        "resumo": resumo,
        "anterior": {chave: anterior[chave] for chave in CHAVES_COMPARACAO},
        "serie": metricas.serie_diaria(sessao, conta, f),
        "pagamentos": metricas.pagamentos(sessao, conta, f),
        "por_origem": metricas.agrupar_vendas(sessao, conta, f, "origem"),
        "por_produto": metricas.agrupar_vendas(sessao, conta, f, "produto"),
        "por_plataforma": metricas.agrupar_vendas(sessao, conta, f, "plataforma"),
        "meta": {
            "conectado": bool(conta.meta_token),
            "contas_ativas": len(contas_meta),
            "ultima_sincronizacao": max((c.ultima_sincronizacao for c in contas_meta if c.ultima_sincronizacao),
                                        default=None),
            "erros": [{"conta": c.nome, "erro": c.erro} for c in contas_meta if c.erro],
        },
    }


@rotas.get("/anuncios")
def anuncios(nivel: Literal["campanha", "conjunto", "anuncio"] = "campanha", pai: str | None = None,
             f: Filtros = Depends(filtros), conta: Conta = Depends(conta_atual),
             sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    linhas = metricas.tabela_anuncios(sessao, conta, f, nivel, pai)
    pai_info = None
    if pai:
        entidade = sessao.get(EntidadeAnuncio, (conta.id, pai))
        pai_info = {"id": pai, "nome": entidade.nome if entidade else pai,
                    "campanha_id": entidade.campanha_id if entidade else None}
    return {"nivel": nivel, "pai": pai_info, "linhas": linhas, "totais": metricas.resumo(sessao, conta, f)}


class NovoStatus(BaseModel):
    status: Literal["ACTIVE", "PAUSED"]


class NovoOrcamento(BaseModel):
    orcamento_diario: float = Field(gt=0, le=10_000_000)


def _entidade_e_cliente(sessao: Session, conta: Conta, entidade_id: str,
                        request: Request) -> tuple[EntidadeAnuncio, ClienteMeta]:
    entidade = sessao.get(EntidadeAnuncio, (conta.id, entidade_id))
    if entidade is None:
        raise HTTPException(404, "Campanha, conjunto ou anúncio não encontrado. Sincronize o Meta antes.")
    if not conta.meta_token:
        raise HTTPException(400, "Conecte o Meta Ads em Integrações primeiro.")
    return entidade, ClienteMeta(conta.meta_token, request.app.state.config.meta_versao_api)


@rotas.post("/anuncios/{entidade_id}/status")
def alterar_status(entidade_id: str, dados: NovoStatus, request: Request, conta: Conta = Depends(conta_atual),
                   sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    entidade, cliente = _entidade_e_cliente(sessao, conta, entidade_id, request)
    try:
        cliente.alterar_status(entidade.id, dados.status)
    except ErroMeta as erro:
        raise HTTPException(502, str(erro)) from None
    entidade.status = dados.status
    entidade.status_efetivo = dados.status
    return {"ok": True, "status": entidade.status}


@rotas.post("/anuncios/{entidade_id}/orcamento")
def alterar_orcamento(entidade_id: str, dados: NovoOrcamento, request: Request,
                      conta: Conta = Depends(conta_atual), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    entidade, cliente = _entidade_e_cliente(sessao, conta, entidade_id, request)
    if not entidade.orcamento_diario_cent:
        raise HTTPException(400, "Este item não tem orçamento diário próprio (o orçamento fica na campanha ou no conjunto).")
    centavos = round(dados.orcamento_diario * 100)
    try:
        cliente.alterar_orcamento_diario(entidade.id, centavos)
    except ErroMeta as erro:
        raise HTTPException(502, str(erro)) from None
    entidade.orcamento_diario_cent = centavos
    return {"ok": True, "orcamento_diario": centavos / 100}


@rotas.get("/vendas")
def vendas(status: str | None = None, busca: str | None = None, pagina: int = Query(1, ge=1),
           f: Filtros = Depends(filtros), conta: Conta = Depends(conta_atual),
           sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    if status and status not in StatusVenda.TODOS:
        raise HTTPException(400, "Status inválido.")
    return metricas.listar_vendas(sessao, conta, f, status=status, busca=busca, pagina=pagina)


@rotas.get("/opcoes")
def opcoes(conta: Conta = Depends(conta_atual), sessao: Session = Depends(sessao_db, scope="function")) -> dict:
    """Valores para os filtros do topo do painel."""
    produtos = sessao.scalars(select(Produto).where(Produto.conta_id == conta.id).order_by(Produto.nome)).all()
    plataformas = sessao.scalars(select(Venda.plataforma).where(Venda.conta_id == conta.id)
                                 .group_by(Venda.plataforma)).all()
    contas = sessao.scalars(select(ContaAnuncio).where(ContaAnuncio.conta_id == conta.id,
                                                       ContaAnuncio.ativo.is_(True)).order_by(ContaAnuncio.nome)).all()
    total_vendas = sessao.scalar(select(func.count()).select_from(Venda).where(Venda.conta_id == conta.id))
    return {
        "produtos": [{"id": p.id, "nome": p.nome, "plataforma": p.plataforma} for p in produtos],
        "plataformas": plataformas,
        "contas_anuncio": [{"id": c.id, "nome": c.nome} for c in contas],
        "tem_vendas": bool(total_vendas),
        "fuso": conta.fuso,
        "moeda": conta.moeda,
    }
