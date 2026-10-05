"""Dependências comuns das rotas: sessão do banco, usuário logado e filtros de período."""

from collections.abc import Iterator
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from rastro.metricas import Filtros
from rastro.modelos import Conta, Usuario
from rastro.seguranca import ler_cookie_sessao

COOKIE_SESSAO = "rastro_sessao"


def sessao_db(request: Request) -> Iterator[Session]:
    # Use sempre com scope="function": o commit acontece antes da resposta sair, então o painel nunca lê
    # dados antigos logo depois de salvar.
    with request.app.state.banco.sessao() as sessao:
        yield sessao


def usuario_opcional(request: Request, sessao: Session = Depends(sessao_db, scope="function")) -> Usuario | None:
    valor = request.cookies.get(COOKIE_SESSAO)
    if not valor:
        return None
    lido = ler_cookie_sessao(valor, request.app.state.config.chave_secreta)
    if lido is None:
        return None
    usuario = sessao.get(Usuario, lido[0])
    if usuario is None or usuario.versao_sessao != lido[1]:
        return None
    return usuario


def usuario_logado(usuario: Usuario | None = Depends(usuario_opcional)) -> Usuario:
    if usuario is None:
        raise HTTPException(401, "Faça login para continuar.")
    return usuario


def usuario_admin(usuario: Usuario = Depends(usuario_logado)) -> Usuario:
    if not usuario.admin:
        raise HTTPException(403, "Só administradores podem fazer isso.")
    return usuario


def conta_atual(usuario: Usuario = Depends(usuario_logado), sessao: Session = Depends(sessao_db, scope="function")) -> Conta:
    return sessao.get(Conta, usuario.conta_id)


def filtros(
    conta: Conta = Depends(conta_atual),
    inicio: date | None = Query(None),
    fim: date | None = Query(None),
    plataforma: str | None = Query(None),
    produto_id: int | None = Query(None),
    conta_anuncio_id: int | None = Query(None),
    campanha: str | None = Query(None),
) -> Filtros:
    hoje = datetime.now(ZoneInfo(conta.fuso)).date()
    fim = fim or hoje
    inicio = inicio or fim
    if inicio > fim:
        inicio, fim = fim, inicio
    if (fim - inicio).days > 731:
        raise HTTPException(400, "Escolha um período de até 2 anos.")
    return Filtros(inicio=inicio, fim=fim, plataforma=plataforma or None, produto_id=produto_id,
                   conta_anuncio_id=conta_anuncio_id, campanha=(campanha or "").strip() or None)

