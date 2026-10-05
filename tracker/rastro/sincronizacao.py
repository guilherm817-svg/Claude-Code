"""Traz gastos e status dos anúncios do Meta e roda em segundo plano a cada N minutos."""

import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from rastro.capi import enviar_pendentes
from rastro.db import Banco
from rastro.meta import ClienteMeta, ErroMeta
from rastro.modelos import Conta, ContaAnuncio, EntidadeAnuncio, GastoDiario, agora

log = logging.getLogger(__name__)
MAX_DIAS_POR_CHAMADA = 30


def _orcamento(valor) -> int | None:
    # A API devolve o orçamento já em centavos, como texto.
    try:
        return int(valor) if valor not in (None, "", "0") else None
    except (TypeError, ValueError):
        return None


def atualizar_contas_anuncio(sessao: Session, conta: Conta, cliente: ClienteMeta) -> list[ContaAnuncio]:
    """Lista as contas de anúncio do token. As novas entram desativadas, para o usuário escolher."""
    existentes = {c.meta_id: c for c in sessao.scalars(select(ContaAnuncio).where(ContaAnuncio.conta_id == conta.id))}
    for item in cliente.contas_anuncio():
        conta_anuncio = existentes.get(item["id"])
        if conta_anuncio is None:
            conta_anuncio = ContaAnuncio(conta_id=conta.id, meta_id=item["id"], ativo=False, cotacao=1.0)
            sessao.add(conta_anuncio)
            existentes[item["id"]] = conta_anuncio
        conta_anuncio.nome = item.get("name") or item["id"]
        conta_anuncio.moeda = (item.get("currency") or "BRL").upper()
        conta_anuncio.fuso = item.get("timezone_name")
    sessao.flush()
    return sorted(existentes.values(), key=lambda c: c.nome.lower())


def buscar_gastos(conta_anuncio: ContaAnuncio, cliente: ClienteMeta, inicio: date,
                  fim: date) -> list[tuple[date, date, list[dict]]]:
    """Insights do período, em pedaços de até 30 dias (limite prático da API sem relatório assíncrono)."""
    pedacos = []
    pedaco_inicio = inicio
    while pedaco_inicio <= fim:
        pedaco_fim = min(fim, pedaco_inicio + timedelta(days=MAX_DIAS_POR_CHAMADA - 1))
        pedacos.append((pedaco_inicio, pedaco_fim, list(cliente.insights(conta_anuncio.meta_id, pedaco_inicio,
                                                                         pedaco_fim))))
        pedaco_inicio = pedaco_fim + timedelta(days=1)
    return pedacos


def gravar_gastos(sessao: Session, conta_anuncio: ContaAnuncio, pedacos: list[tuple[date, date, list[dict]]]) -> int:
    """Substitui os gastos de cada período pelo que o Meta informou agora. Devolve o número de linhas."""
    total = 0
    for pedaco_inicio, pedaco_fim, linhas in pedacos:
        sessao.execute(delete(GastoDiario).where(
            GastoDiario.conta_anuncio_id == conta_anuncio.id,
            GastoDiario.dia >= pedaco_inicio, GastoDiario.dia <= pedaco_fim))
        for linha in linhas:
            sessao.add(GastoDiario(conta_id=conta_anuncio.conta_id, conta_anuncio_id=conta_anuncio.id, **linha))
        total += len(linhas)
    sessao.flush()
    return total


def buscar_entidades(conta_anuncio: ContaAnuncio, cliente: ClienteMeta) -> dict[str, list[dict]]:
    return {nivel: list(cliente.entidades(conta_anuncio.meta_id, nivel))
            for nivel in ("campanha", "conjunto", "anuncio")}


def gravar_entidades(sessao: Session, conta_anuncio: ContaAnuncio, por_nivel: dict[str, list[dict]]) -> int:
    total = 0
    for nivel, itens in por_nivel.items():
        for item in itens:
            entidade = sessao.get(EntidadeAnuncio, (conta_anuncio.conta_id, item["id"]))
            if entidade is None:
                entidade = EntidadeAnuncio(conta_id=conta_anuncio.conta_id, id=item["id"], nivel=nivel)
                sessao.add(entidade)
            entidade.conta_anuncio_id = conta_anuncio.id
            entidade.nome = item.get("name") or item["id"]
            entidade.status = item.get("status")
            entidade.status_efetivo = item.get("effective_status")
            entidade.orcamento_diario_cent = _orcamento(item.get("daily_budget"))
            entidade.orcamento_total_cent = _orcamento(item.get("lifetime_budget"))
            entidade.campanha_id = item.get("campaign_id") or (item["id"] if nivel == "campanha" else None)
            entidade.conjunto_id = item.get("adset_id") or (item["id"] if nivel == "conjunto" else None)
            entidade.atualizado_em = agora()
            total += 1
    sessao.flush()
    return total


def hoje_no_fuso(fuso: str | None) -> date:
    try:
        return datetime.now(ZoneInfo(fuso or "America/Sao_Paulo")).date()
    except (KeyError, ValueError):
        return datetime.now(ZoneInfo("America/Sao_Paulo")).date()


def sincronizar_conta_anuncio(sessao: Session, conta_anuncio: ContaAnuncio, cliente: ClienteMeta,
                              inicio: date | None = None, fim: date | None = None) -> None:
    """Sincroniza uma conta de anúncio e guarda o erro nela, sem propagar. Faz commit.

    Primeiro busca tudo no Meta, sem transação aberta, e só depois grava numa transação curta: assim os
    webhooks que chegam durante a sincronização (que pode levar minutos) nunca esperam pelo banco.
    """
    fim = fim or hoje_no_fuso(conta_anuncio.fuso)
    inicio = inicio or fim - timedelta(days=1)  # o Meta ainda ajusta o gasto de ontem
    sessao.commit()
    try:
        pedacos = buscar_gastos(conta_anuncio, cliente, inicio, fim)
        entidades = buscar_entidades(conta_anuncio, cliente)
    except (ErroMeta, OSError) as erro:
        log.warning("Falha ao sincronizar %s: %s", conta_anuncio.meta_id, erro)
        conta_anuncio.erro = str(erro)[:1000]
        sessao.commit()
        return
    gravar_gastos(sessao, conta_anuncio, pedacos)
    gravar_entidades(sessao, conta_anuncio, entidades)
    conta_anuncio.erro = None
    conta_anuncio.ultima_sincronizacao = agora()
    sessao.commit()


def sincronizar_conta(sessao: Session, conta: Conta, versao_api: str, inicio: date | None = None,
                      fim: date | None = None, cliente: ClienteMeta | None = None) -> None:
    if conta.meta_token:
        cliente_meta = cliente or ClienteMeta(conta.meta_token, versao_api)
        ativas = sessao.scalars(select(ContaAnuncio).where(ContaAnuncio.conta_id == conta.id,
                                                           ContaAnuncio.ativo.is_(True))).all()
        for conta_anuncio in ativas:
            sincronizar_conta_anuncio(sessao, conta_anuncio, cliente_meta, inicio, fim)
    enviar_pendentes(sessao, conta, versao_api)
    sessao.commit()


def sincronizar_tudo(banco: Banco, versao_api: str) -> None:
    with banco.sessao() as sessao:
        ids = sessao.scalars(select(Conta.id)).all()
    for conta_id in ids:
        try:
            with banco.sessao() as sessao:
                sincronizar_conta(sessao, sessao.get(Conta, conta_id), versao_api)
        except Exception:  # noqa: BLE001 — uma conta com problema não pode parar as outras
            log.exception("Falha ao sincronizar a conta %s", conta_id)


async def laco_sincronizacao(banco: Banco, versao_api: str, minutos: int) -> None:
    while True:
        await asyncio.to_thread(sincronizar_tudo, banco, versao_api)
        await asyncio.sleep(minutos * 60)

